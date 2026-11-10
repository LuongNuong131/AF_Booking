"""Typed administrative CRUD and dependency-aware recycle/restore/purge."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from pydantic import AwareDatetime, Field, ValidationError, create_model
from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import IntegrityError

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import (
    Attachment,
    Booking,
    BookingAssignment,
    BookingGroup,
    BookingInvoice,
    BookingNote,
    BookingTask,
    BookingWatcher,
    BookingWorkTask,
    DailyReport,
    NoteSnippet,
    Notification,
    PushSubscription,
    RecycleEntry,
    Station,
    Status,
    StorageGarbage,
    User,
)
from app.schemas.admin import StatusCreate, StatusUpdate, UserCreate, UserUpdate
from app.schemas.bookings import BookingCreateRequest
from app.schemas.contracts import ContractModel, ErrorCode, Page
from app.schemas.management import DataField, PurgePreview, TrashItem
from app.services.admin import locked_admin
from app.services.audit import record_audit
from app.services.snapshot_values import apply_snapshot, note_snapshot
from app.utils.invoice import normalize, validate
from app.utils.text import clean_note


def field(
    name, kind="text", required=False, options=(), readonly=False, max_length=None, reference=None
):
    return DataField(
        name=name,
        kind=kind,
        required=required,
        options=list(options),
        readonly=readonly,
        max_length=max_length,
        reference=reference,
    )


SPECS = {
    "users": (
        User,
        "full_name",
        [
            field("username", required=True, readonly=True, max_length=50),
            field("full_name", required=True, max_length=100),
            field("role", "select", True, ["agent", "qc", "admin"]),
            field("temporary_password", "password", True),
            field("is_active", "boolean"),
        ],
    ),
    "bookings": (
        Booking,
        "booking_key",
        [
            field("booking_key", required=True, readonly=True),
            field("supplier_name", required=True, readonly=True, max_length=255),
            field("supplier_type", "select", False, ["unclassified", "hotel", "transportation"]),
        ],
    ),
    "suppliers": (
        BookingGroup,
        "supplier_name",
        [
            field("cw_number", required=True, readonly=True),
            field("station_code", required=True, readonly=True),
            field("supplier_name", required=True, max_length=255),
            field("supplier_type", "select", True, ["unclassified", "hotel", "transportation"]),
            field("recurring_enabled", "boolean"),
        ],
    ),
    "stations": (
        Station,
        "code",
        [field("code", required=True, readonly=True, max_length=4), field("name", max_length=100)],
    ),
    "statuses": (
        Status,
        "label",
        [
            field("code", required=True, readonly=True, max_length=40),
            field("label", required=True, max_length=100),
            field("position_label", required=True, max_length=60),
            field("sort_order", "number"),
            *[
                field(k, "boolean")
                for k in [
                    "is_active",
                    "is_done",
                    "note_required",
                    "invoice_required",
                    "suggest_task",
                ]
            ],
            field("stale_after_hours", "number"),
            field("default_task_days", "number"),
        ],
    ),
    "notes": (
        BookingNote,
        "note",
        [
            field("booking_id", "number", True, readonly=True, reference="bookings"),
            field("agent_id", "number", True, reference="users"),
            field("status_id", "number", True, reference="statuses"),
            field("note", "textarea", max_length=5000),
        ],
    ),
    "invoices": (
        BookingInvoice,
        "invoice_number",
        [
            field("booking_id", "number", True, readonly=True, reference="bookings"),
            field("invoice_number", required=True, max_length=40),
        ],
    ),
    "tickets": (
        BookingWorkTask,
        "message",
        [
            field("booking_id", "number", True, readonly=True, reference="bookings"),
            field("message", "textarea", True, max_length=2000),
            field("status", "select", True, ["pending", "handled"]),
            field("handling_note", "textarea", max_length=2000),
        ],
    ),
    "reminders": (
        BookingTask,
        "message",
        [
            field("booking_id", "number", True, readonly=True, reference="bookings"),
            field("user_id", "number", True, reference="users"),
            field("message", "textarea", True, max_length=255),
            field("remind_at", "datetime", True),
            field("status", "select", True, ["pending", "done", "cancelled"]),
        ],
    ),
    "snippets": (
        NoteSnippet,
        "title",
        [
            field("user_id", "number", True, readonly=True, reference="users"),
            field("title", required=True, max_length=80),
            field("text", "textarea", True, max_length=1000),
        ],
    ),
    "assignments": (
        BookingAssignment,
        "message",
        [
            field("booking_id", "number", True, readonly=True, reference="bookings"),
            field("note_id", "number", True, reference="notes"),
            field("from_user_id", "number", True, reference="users"),
            field("to_user_id", "number", True, reference="users"),
            field("message", "textarea", max_length=255),
            field("status", "select", True, ["open", "done", "declined"]),
        ],
    ),
    "notifications": (
        Notification,
        "type",
        [
            field("user_id", "number", True, readonly=True, reference="users"),
            field("booking_id", "number", True, readonly=True, reference="bookings"),
            field(
                "type",
                "select",
                True,
                [
                    "taken_over",
                    "stale",
                    "task_due",
                    "watch_update",
                    "assigned",
                    "assignment_done",
                    "work_task_created",
                    "work_task_handled",
                ],
            ),
        ],
    ),
}
SOFT = {"users", "bookings", "suppliers", "stations", "statuses", "notes"}
BOOKING_CHILDREN = [
    Attachment,
    Notification,
    BookingAssignment,
    BookingWatcher,
    BookingTask,
    BookingWorkTask,
    BookingInvoice,
    BookingNote,
]


def spec(resource):
    if resource not in SPECS:
        raise ApiException(ErrorCode.NOT_FOUND)
    return SPECS[resource]


def row_values(row):
    return {c.key: getattr(row, c.key) for c in inspect(type(row)).columns if not c.computed}


def identity(model):
    return inspect(model).primary_key[0]


def public(row, resource):
    model, label, fields = spec(resource)
    result = {f.name: getattr(row, f.name, None) for f in fields if f.kind != "password"}
    if resource == "bookings":
        result["supplier_type"] = row.classification
    result.update(
        id=str(getattr(row, identity(model).key)), label=str(getattr(row, label) or "—")[:255]
    )
    if hasattr(row, "created_at"):
        result["created_at"] = row.created_at
    return jsonable_encoder(result)


class Management:
    def __init__(self, state):
        self.state = state

    def tx(self, after_commit=None):
        return transaction(
            self.state.engine,
            self.state.settings,
            seconds=self.state.settings.export_timeout_seconds,
            after_commit=after_commit,
        )

    def invalidate_reads(self):
        self.state.key_index.invalidate()
        self.state.snapshot_cache.clear()
        self.state.reports.invalidate()

    def changed(self):
        state = self.state
        state.snapshot_cache.clear()
        state.reports.invalidate()
        state.stations.invalidate()
        state.key_index.invalidate()
        state.ws_manager.spawn(state.key_index.load())
        state.admin.catalog("suppliers", True)
        state.admin.catalog("users")
        state.admin.catalog("statuses", True)
        state.daily_reports.cache = None
        state.daily_reports.wire_cache.clear()

    async def listing(self, resource, q, page, size):
        model, label, _ = spec(resource)
        conditions = [getattr(model, label).contains(q, autoescape=True)] if q else []
        if resource in SOFT:
            conditions.append(model.deleted_at.is_(None))
        async with self.tx() as session:
            total = await session.scalar(select(func.count()).select_from(model).where(*conditions))
            rows = (
                await session.scalars(
                    select(model)
                    .where(*conditions)
                    .order_by(identity(model).desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
            values = [public(r, resource) for r in rows]
            if resource == "bookings":
                groups = {
                    g.id: g
                    for g in (
                        await session.scalars(
                            select(BookingGroup).where(
                                BookingGroup.id.in_([r.group_id for r in rows])
                            )
                        )
                    ).all()
                }
                for row, value in zip(rows, values, strict=True):
                    group = groups.get(row.group_id)
                    value["supplier_name"] = group.supplier_name if group else None
                    value["supplier_type"] = row.classification or (
                        group.supplier_type if group else "unclassified"
                    )
            return Page(items=values, total=total, page=page, size=size)

    def validated(self, resource, values, creating):
        definitions = {}
        for f in spec(resource)[2]:
            if not creating and (f.readonly or f.kind == "password"):
                continue
            typ = (
                bool
                if f.kind == "boolean"
                else int
                if f.kind == "number"
                else AwareDatetime
                if f.kind == "datetime"
                else str
            )
            default = ... if creating and f.required else None
            definitions[f.name] = (
                typ if default is ... else typ | None,
                Field(
                    default=default,
                    max_length=f.max_length if typ is str else None,
                    ge=1 if f.reference else None,
                ),
            )
        schema = create_model("DataValues", __base__=ContractModel, **definitions)
        try:
            parsed = schema.model_validate(values).model_dump(exclude_unset=True)
        except ValidationError:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR, message="Check the required fields and their formats."
            ) from None
        for f in spec(resource)[2]:
            if (
                f.name in parsed
                and f.kind in {"text", "textarea"}
                and isinstance(parsed[f.name], str)
            ):
                parsed[f.name] = clean_note(parsed[f.name])
            if f.required and f.name in parsed and parsed[f.name] is None:
                raise ApiException(ErrorCode.VALIDATION_ERROR, message=f"{f.name} is required.")
            if (
                f.name in parsed
                and f.required
                and isinstance(parsed[f.name], str)
                and not parsed[f.name].strip()
            ):
                raise ApiException(ErrorCode.VALIDATION_ERROR, message=f"{f.name} is required.")
            if f.name in parsed and f.options and parsed[f.name] not in f.options:
                raise ApiException(ErrorCode.VALIDATION_ERROR, message=f"Invalid {f.name}.")
        return parsed

    async def save(self, resource, identifier, body, actor, context):
        values = body.values
        if resource == "users":
            try:
                return jsonable_encoder(
                    await (
                        self.state.admin.create_user(
                            UserCreate.model_validate(values),
                            actor,
                            context,
                        )
                        if identifier is None
                        else self.state.admin.update_user(
                            int(identifier), UserUpdate.model_validate(values), actor, context
                        )
                    )
                )
            except ValidationError:
                raise ApiException(ErrorCode.VALIDATION_ERROR) from None
        if resource == "statuses":
            try:
                schema = StatusCreate if identifier is None else StatusUpdate
                return jsonable_encoder(
                    await self.state.admin.save_status(
                        schema.model_validate(
                            {**values, **({"id": int(identifier)} if identifier else {})}
                        ),
                        actor,
                        context,
                    )
                )
            except ValidationError:
                raise ApiException(ErrorCode.VALIDATION_ERROR) from None
        if resource == "bookings" and identifier is None:
            try:
                return jsonable_encoder(
                    await self.state.booking_writes.create(
                        BookingCreateRequest.model_validate({**values, "confirm_new": True}),
                        actor,
                        context,
                    )
                )
            except ValidationError:
                raise ApiException(ErrorCode.VALIDATION_ERROR) from None
        model, _, _ = spec(resource)
        values = self.validated(resource, values, identifier is None)
        if not values:
            raise ApiException(ErrorCode.VALIDATION_ERROR)
        try:
            async with self.tx(after_commit=self.changed) as session:
                await locked_admin(session, actor)
                row = (
                    await session.scalar(
                        select(model).where(identity(model) == identifier).with_for_update()
                    )
                    if identifier is not None
                    else model()
                )
                if row is None or (resource in SOFT and row.deleted_at is not None):
                    raise ApiException(ErrorCode.NOT_FOUND)
                before = public(row, resource) if identifier is not None else None
                for f in spec(resource)[2]:
                    if f.reference and f.name in values:
                        refmodel = spec(f.reference)[0]
                        target = await session.get(refmodel, values[f.name])
                        changed_reference = (
                            identifier is None or getattr(row, f.name, None) != values[f.name]
                        )
                        if target is None or (
                            changed_reference and getattr(target, "deleted_at", None) is not None
                        ):
                            raise ApiException(
                                ErrorCode.VALIDATION_ERROR,
                                message=f"Choose an existing {f.reference} record.",
                            )
                if resource == "bookings":
                    if "supplier_type" in values:
                        row.classification = values.pop("supplier_type")
                    if "supplier_name" in values:
                        raise ApiException(
                            ErrorCode.VALIDATION_ERROR,
                            message="Edit the supplier name in Suppliers.",
                        )
                if resource == "stations" and identifier is None:
                    import re

                    values["code"] = values["code"].strip().upper()
                    if not re.fullmatch(self.state.settings.station_code_pattern, values["code"]):
                        raise ApiException(
                            ErrorCode.VALIDATION_ERROR, message="Enter a valid station code."
                        )
                if resource == "suppliers" and "supplier_name" in values:
                    from app.services.booking_writes import supplier_name

                    values["supplier_name"] = supplier_name(values["supplier_name"])
                if resource == "suppliers":
                    if identifier is None:
                        import re

                        if not re.fullmatch(
                            r"CW\d{5,10}", values.get("cw_number", "")
                        ) or not re.fullmatch(r"[A-Z]{3}", values.get("station_code", "")):
                            raise ApiException(ErrorCode.VALIDATION_ERROR)
                        row.created_by = actor.id
                        row.last_activity_at = datetime.now(UTC)
                        row.recurring_enabled = values.get("recurring_enabled", True)
                        if await session.get(Station, values["station_code"]) is None:
                            session.add(Station(code=values["station_code"]))
                for key, value in values.items():
                    setattr(row, key, value)
                if resource == "notes":
                    status = await session.get(Status, row.status_id)
                    if status is None or (status.note_required and not (row.note or "").strip()):
                        raise ApiException(ErrorCode.NOTE_REQUIRED)
                    row.position_label = status.position_label
                    row.save_result = None
                if resource == "invoices":
                    row.invoice_number_normalized = normalize(row.invoice_number)
                    if not validate(
                        row.invoice_number_normalized, self.state.settings.invoice_number_pattern
                    ):
                        raise ApiException(ErrorCode.INVOICE_INVALID)
                    if identifier is None:
                        row.added_by = actor.id
                if resource == "tickets":
                    if identifier is None:
                        row.created_by = actor.id
                        row.client_request_id = str(uuid4())
                    row.handled_by = actor.id if row.status == "handled" else None
                    row.handled_at = datetime.now(UTC) if row.status == "handled" else None
                if resource == "assignments":
                    row.resolved_at = datetime.now(UTC) if row.status != "open" else None
                if resource == "reminders":
                    row.completed_at = (
                        datetime.now(UTC) if row.status in {"done", "cancelled"} else None
                    )
                session.add(row)
                await session.flush()
                await session.refresh(row)
                if resource in {"notes", "invoices"}:
                    await self.rebuild(session, row.booking_id)
                # Frozen daily reports must not retain administratively edited/deleted records.
                await session.execute(delete(DailyReport))
                record_audit(
                    session,
                    "admin_record_created" if identifier is None else "admin_record_updated",
                    actor_id=actor.id,
                    entity_type=resource,
                    entity_id=str(getattr(row, identity(model).key)),
                    context=context,
                    meta={"before": before, "after": public(row, resource)},
                )
                result = public(row, resource)
            return result
        except IntegrityError:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR,
                message="These unique values are already used. Check the recycle bin too.",
            ) from None

    async def rebuild(self, session, booking_id):
        book = await session.scalar(
            select(Booking).where(Booking.id == booking_id).with_for_update()
        )
        if book is None:
            return
        latest = (
            await session.execute(
                select(BookingNote, Status.is_done)
                .join(Status, Status.id == BookingNote.status_id)
                .where(BookingNote.booking_id == booking_id, BookingNote.deleted_at.is_(None))
                .order_by(BookingNote.id.desc())
                .limit(1)
            )
        ).first()
        note = latest.BookingNote if latest else None
        apply_snapshot(
            book,
            note_snapshot(
                note.id if note else None,
                note.agent_id if note else None,
                note.status_id if note else None,
                note.position_label if note else None,
                note.created_at if note else None,
                note.note if note else None,
                latest.is_done if latest else False,
            ),
        )
        book.invoice_count = await session.scalar(
            select(func.count())
            .select_from(BookingInvoice)
            .where(BookingInvoice.booking_id == booking_id)
        )
        book.invoice_state = (
            "has_invoice"
            if book.invoice_count
            else "no_invoice"
            if book.invoice_state == "no_invoice"
            else "unknown"
        )
        book.version += 1

    async def recount(self, session, ids):
        for identifier in set(ids):
            count = (
                select(func.count())
                .select_from(Booking)
                .where(Booking.group_id == identifier, Booking.deleted_at.is_(None))
                .scalar_subquery()
            )
            await session.execute(
                update(BookingGroup)
                .where(BookingGroup.id == identifier)
                .values(booking_count=count)
                .execution_options(synchronize_session=False)
            )

    async def remove(self, resource, identifier, reason, actor, context, notify=True):
        model, label, _ = spec(resource)
        old_session = None

        def committed():
            if resource == "users":
                self.state.auth.cache.invalidate(int(identifier))
            if notify:
                self.changed()
            else:
                self.invalidate_reads()

        async with self.tx(after_commit=committed) as session:
            await locked_admin(session, actor, int(identifier) if resource == "users" else None)
            row = await session.scalar(
                select(model)
                .where(
                    Booking.booking_key == identifier
                    if resource == "bookings" and str(identifier).startswith("CW")
                    else identity(model) == identifier
                )
                .with_for_update()
            )
            if row is None or (resource in SOFT and row.deleted_at is not None):
                raise ApiException(ErrorCode.NOT_FOUND)
            if resource == "users" and row.id == actor.id:
                raise ApiException(
                    ErrorCode.FORBIDDEN,
                    message="You cannot delete your signed-in administrator account.",
                )
            payload = {}
            if resource in SOFT:
                payload["was_active"] = getattr(row, "is_active", None)
                row.deleted_at = datetime.now(UTC)
                if resource == "notes":
                    row.deleted_by = actor.id
                    row.delete_reason = reason
                if resource == "bookings":
                    from sqlalchemy.orm.attributes import flag_modified

                    flag_modified(row, "updated_at")
                if resource in {"users", "statuses", "stations"}:
                    row.is_active = False
                if resource == "users":
                    old_session = row.current_session_id
                    row.current_session_id = None
                if resource in {"suppliers", "stations"}:
                    groups = (
                        [row]
                        if resource == "suppliers"
                        else list(
                            (
                                await session.scalars(
                                    select(BookingGroup)
                                    .where(BookingGroup.station_code == row.code)
                                    .with_for_update()
                                )
                            ).all()
                        )
                    )
                    group_ids = [g.id for g in groups]
                    books = list(
                        (
                            await session.scalars(
                                select(Booking)
                                .where(Booking.group_id.in_(group_ids))
                                .with_for_update()
                            )
                        ).all()
                    )
                    payload["group_ids"] = group_ids
                    payload["booking_ids"] = [b.id for b in books]
                    for entry in [*groups, *books]:
                        entry.deleted_at = row.deleted_at
                        if isinstance(entry, Booking):
                            from sqlalchemy.orm.attributes import flag_modified

                            flag_modified(entry, "updated_at")
            else:
                payload["row"] = jsonable_encoder(row_values(row))
                await session.delete(row)
            entry = RecycleEntry(
                resource=resource,
                record_id=str(getattr(row, identity(model).key)),
                label=str(getattr(row, label) or identifier)[:255],
                deleted_by=actor.id,
                reason=reason.strip(),
                payload=payload,
            )
            session.add(entry)
            await session.flush()
            if resource == "bookings":
                await self.recount(session, [row.group_id])
            elif resource in {"suppliers", "stations"}:
                await self.recount(session, payload.get("group_ids", []))
            if resource in {"notes", "invoices"}:
                await self.rebuild(session, row.booking_id)
            await session.execute(delete(DailyReport))
            record_audit(
                session,
                "admin_record_recycled",
                actor_id=actor.id,
                entity_type=resource,
                entity_id=str(identifier),
                context=context,
                meta={"reason": reason, "trash_id": entry.id},
            )
        if resource == "users":
            await self.state.auth.invalidate_user(int(identifier))
            await self.state.auth.notify_old_session(int(identifier), old_session, "user_disabled")
        return {"ok": True}

    async def bulk_remove(self, resource, ids, reason, actor, context):
        spec(resource)
        removed, failed = [], []
        for identifier in dict.fromkeys(ids):
            try:
                await self.remove(resource, identifier, reason, actor, context, notify=False)
                removed.append(identifier)
            except ApiException as error:
                failed.append({"id": identifier, "message": error.message or error.code.value})
        self.changed()
        return {"removed": removed, "failed": failed}

    async def trash(self, q, page, size):
        async with self.tx() as session:
            condition = RecycleEntry.label.contains(q, autoescape=True)
            total = await session.scalar(
                select(func.count()).select_from(RecycleEntry).where(condition)
            )
            rows = (
                await session.scalars(
                    select(RecycleEntry)
                    .where(condition)
                    .order_by(RecycleEntry.id.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
            return Page(
                items=[TrashItem.model_validate(r, from_attributes=True) for r in rows],
                total=total,
                page=page,
                size=size,
            )

    async def restore(self, identifier, actor, context):
        try:
            async with self.tx(after_commit=self.changed) as session:
                session.info["include_deleted"] = True
                await locked_admin(session, actor)
                entry = await session.scalar(
                    select(RecycleEntry).where(RecycleEntry.id == identifier).with_for_update()
                )
                if entry is None:
                    raise ApiException(ErrorCode.NOT_FOUND)
                model = spec(entry.resource)[0]
                if entry.resource in SOFT:
                    row = await session.get(model, entry.record_id)
                    if row is None:
                        raise ApiException(ErrorCode.NOT_FOUND)
                    if entry.resource == "suppliers":
                        station = await session.get(Station, row.station_code)
                        if station is None or station.deleted_at is not None:
                            raise ApiException(
                                ErrorCode.VALIDATION_ERROR, message="Restore the station first."
                            )
                    if entry.resource == "bookings":
                        group = await session.get(BookingGroup, row.group_id)
                        if group is None or group.deleted_at:
                            raise ApiException(
                                ErrorCode.VALIDATION_ERROR,
                                message="Restore the supplier folder first.",
                            )
                    row.deleted_at = None
                    if entry.resource == "notes":
                        row.deleted_by = None
                        row.delete_reason = None
                    if isinstance(row, Booking):
                        from sqlalchemy.orm.attributes import flag_modified

                        flag_modified(row, "updated_at")
                    if entry.resource in {"users", "statuses", "stations"}:
                        row.is_active = bool(entry.payload.get("was_active", True))
                    for cls, key in [(BookingGroup, "group_ids"), (Booking, "booking_ids")]:
                        for item in (
                            await session.scalars(
                                select(cls).where(cls.id.in_(entry.payload.get(key, [])))
                            )
                        ).all():
                            item.deleted_at = None
                            if isinstance(item, Booking):
                                from sqlalchemy.orm.attributes import flag_modified

                                flag_modified(item, "updated_at")
                else:
                    data = entry.payload["row"].copy()
                    for column in inspect(model).columns:
                        if (
                            column.key in data
                            and data[column.key] is not None
                            and hasattr(column.type, "timezone")
                        ):
                            data[column.key] = datetime.fromisoformat(data[column.key])
                    row = model(**data)
                    for f in spec(entry.resource)[2]:
                        if f.reference and getattr(row, f.name, None) is not None:
                            target = await session.get(spec(f.reference)[0], getattr(row, f.name))
                            if target is None:
                                raise ApiException(
                                    ErrorCode.VALIDATION_ERROR,
                                    message="A referenced record was permanently deleted.",
                                )
                    if hasattr(row, "booking_id"):
                        book = await session.get(Booking, row.booking_id)
                        if book is None or book.deleted_at:
                            raise ApiException(
                                ErrorCode.VALIDATION_ERROR, message="Restore the booking first."
                            )
                    session.add(row)
                await session.flush()
                if entry.resource == "bookings":
                    await self.recount(session, [row.group_id])
                elif entry.resource in {"suppliers", "stations"}:
                    await self.recount(session, entry.payload.get("group_ids", []))
                if entry.resource in {"notes", "invoices"}:
                    await self.rebuild(session, row.booking_id)
                record_audit(
                    session,
                    "admin_record_restored",
                    actor_id=actor.id,
                    entity_type=entry.resource,
                    entity_id=entry.record_id,
                    context=context,
                )
                await session.delete(entry)
                await session.execute(delete(DailyReport))
            return {"ok": True}
        except IntegrityError:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR,
                message="A conflicting record exists. Resolve the duplicate before restoring.",
            ) from None

    async def purge_plan(self, session, ids):
        entries = list(
            (
                await session.scalars(
                    select(RecycleEntry)
                    .where(RecycleEntry.id.in_(ids))
                    .order_by(RecycleEntry.id)
                    .with_for_update()
                )
            ).all()
        )
        if len(entries) != len(set(ids)):
            raise ApiException(
                ErrorCode.VERSION_CONFLICT, message="Trash changed. Preview the selection again."
            )
        counts, blockers = {}, []
        booking_ids, group_ids, station_ids = set(), set(), set()
        selected_notes = {int(e.record_id) for e in entries if e.resource == "notes"}
        for e in entries:
            counts[e.resource] = counts.get(e.resource, 0) + 1
            if e.resource == "bookings":
                booking_ids.add(int(e.record_id))
            if e.resource == "suppliers":
                group_ids.add(int(e.record_id))
            if e.resource == "stations":
                station_ids.add(e.record_id)
        if station_ids:
            group_ids.update(
                (
                    await session.scalars(
                        select(BookingGroup.id).where(BookingGroup.station_code.in_(station_ids))
                    )
                ).all()
            )
        if group_ids:
            booking_ids.update(
                (
                    await session.scalars(select(Booking.id).where(Booking.group_id.in_(group_ids)))
                ).all()
            )
        counts["bookings"] = len(booking_ids)
        counts["suppliers"] = len(group_ids)
        for e in entries:
            if e.resource in {"users", "statuses"}:
                refs = (
                    [BookingNote.status_id, Booking.last_status_id]
                    if e.resource == "statuses"
                    else [
                        BookingNote.agent_id,
                        Booking.last_agent_id,
                        BookingGroup.created_by,
                        BookingWorkTask.created_by,
                        BookingWorkTask.handled_by,
                        BookingTask.user_id,
                        BookingInvoice.added_by,
                        Notification.user_id,
                        Notification.by_agent_id,
                        BookingAssignment.from_user_id,
                        BookingAssignment.to_user_id,
                        BookingWatcher.user_id,
                        NoteSnippet.user_id,
                        PushSubscription.user_id,
                    ]
                )
                for col in refs:
                    cls = next(
                        m
                        for m in [
                            BookingNote,
                            Booking,
                            BookingGroup,
                            BookingWorkTask,
                            BookingTask,
                            BookingInvoice,
                            Notification,
                            BookingAssignment,
                            BookingWatcher,
                            NoteSnippet,
                            PushSubscription,
                        ]
                        if m.__table__.name == col.table.name
                    )
                    condition = [col == int(e.record_id)]
                    if hasattr(cls, "booking_id"):
                        condition.append(cls.booking_id.not_in(booking_ids))
                    if cls is BookingNote:
                        condition.append(BookingNote.id.not_in(selected_notes))
                    if cls is Booking:
                        condition.append(Booking.id.not_in(booking_ids))
                    if cls is BookingGroup:
                        condition.append(BookingGroup.id.not_in(group_ids))
                    n = await session.scalar(
                        select(func.count()).select_from(cls).where(*condition)
                    )
                    if n:
                        blockers.append(
                            f"{e.resource} · {e.label}: {n} reference(s) in {col.table.name}. "
                            "Delete/reassign the linked records first."
                        )
        if booking_ids:
            notes = select(BookingNote.id).where(BookingNote.booking_id.in_(booking_ids))
            for cls in BOOKING_CHILDREN:
                condition = (
                    cls.note_id.in_(notes) if cls is Attachment else cls.booking_id.in_(booking_ids)
                )
                counts[cls.__tablename__] = await session.scalar(
                    select(func.count()).select_from(cls).where(condition)
                )
        # Include row versions/content so concurrent edits invalidate the preview lease.
        signatures = []
        for e in entries:
            model = spec(e.resource)[0]
            row = await session.get(model, e.record_id) if e.resource in SOFT else None
            signatures.append(
                [
                    e.id,
                    e.resource,
                    e.record_id,
                    jsonable_encoder(row_values(row)) if row else e.payload,
                ]
            )
        token = hashlib.sha256(
            json.dumps([signatures, counts, blockers], sort_keys=True).encode()
        ).hexdigest()
        return (
            PurgePreview(token=token, entries=len(entries), counts=counts, blockers=blockers),
            entries,
            booking_ids,
            group_ids,
            station_ids,
        )

    async def preview(self, ids, actor):
        if not ids or len(ids) > 2000:
            raise ApiException(ErrorCode.VALIDATION_ERROR)
        async with self.tx() as session:
            session.info["include_deleted"] = True
            await locked_admin(session, actor)
            return (await self.purge_plan(session, ids))[0]

    async def purge(self, body, actor, context):
        async with self.tx(after_commit=self.changed) as session:
            session.info["include_deleted"] = True
            await locked_admin(session, actor)
            plan, entries, booking_ids, group_ids, station_ids = await self.purge_plan(
                session, body.ids
            )
            if plan.blockers or body.preview_token != plan.token:
                raise ApiException(
                    ErrorCode.VERSION_CONFLICT,
                    message="Deletion is blocked or the preview changed. Review a fresh preview.",
                    details={"blockers": plan.blockers},
                )
            if booking_ids:
                notes = list(
                    (
                        await session.scalars(
                            select(BookingNote.id).where(BookingNote.booking_id.in_(booking_ids))
                        )
                    ).all()
                )
                keys = (
                    await session.scalars(
                        select(Attachment.storage_key).where(Attachment.note_id.in_(notes))
                    )
                ).all()
                for key in keys:
                    await session.execute(
                        insert(StorageGarbage)
                        .values(storage_key=key)
                        .on_duplicate_key_update(storage_key=key)
                    )
                await session.execute(delete(Attachment).where(Attachment.note_id.in_(notes)))
                await session.execute(
                    delete(RecycleEntry).where(
                        RecycleEntry.resource == "notes",
                        RecycleEntry.record_id.in_([str(i) for i in notes]),
                        RecycleEntry.id.not_in(body.ids),
                    )
                )
                for cls in BOOKING_CHILDREN[1:]:
                    await session.execute(delete(cls).where(cls.booking_id.in_(booking_ids)))
                await session.execute(delete(Booking).where(Booking.id.in_(booking_ids)))
            if group_ids:
                await session.execute(delete(BookingGroup).where(BookingGroup.id.in_(group_ids)))
            if station_ids:
                await session.execute(delete(Station).where(Station.code.in_(station_ids)))
            for e in entries:
                if e.resource in {"users", "statuses", "notes"}:
                    model = spec(e.resource)[0]
                    if e.resource == "notes":
                        keys = (
                            await session.scalars(
                                select(Attachment.storage_key).where(
                                    Attachment.note_id == int(e.record_id)
                                )
                            )
                        ).all()
                        for key in keys:
                            await session.execute(
                                insert(StorageGarbage)
                                .values(storage_key=key)
                                .on_duplicate_key_update(storage_key=key)
                            )
                        await session.execute(
                            delete(Attachment).where(Attachment.note_id == int(e.record_id))
                        )
                        await session.execute(
                            delete(Notification).where(Notification.note_id == int(e.record_id))
                        )
                        await session.execute(
                            delete(BookingAssignment).where(
                                BookingAssignment.note_id == int(e.record_id)
                            )
                        )

                        await session.execute(
                            update(BookingTask)
                            .where(BookingTask.note_id == int(e.record_id))
                            .values(note_id=None)
                        )
                    await session.execute(delete(model).where(identity(model) == e.record_id))
                await session.delete(e)
            # Remove obsolete recycle handles for any cascade-deleted children.
            if booking_ids:
                await session.execute(
                    delete(RecycleEntry).where(
                        RecycleEntry.resource == "bookings",
                        RecycleEntry.record_id.in_([str(i) for i in booking_ids]),
                    )
                )
            if booking_ids:
                await session.execute(
                    delete(RecycleEntry).where(
                        RecycleEntry.payload["row"]["booking_id"].as_integer().in_(booking_ids)
                    )
                )
            if group_ids:
                await session.execute(
                    delete(RecycleEntry).where(
                        RecycleEntry.resource == "suppliers",
                        RecycleEntry.record_id.in_([str(i) for i in group_ids]),
                    )
                )
            await session.execute(delete(DailyReport))
            record_audit(
                session,
                "trash_purged",
                actor_id=actor.id,
                entity_type="trash",
                context=context,
                meta={"counts": plan.counts, "entries": plan.entries},
            )
        return {"ok": True, "counts": plan.counts}
