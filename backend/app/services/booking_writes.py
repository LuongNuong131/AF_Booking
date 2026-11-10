import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import DBAPIError

from app.core.errors import ApiException
from app.core.timeouts import request_budget
from app.core.unit_of_work import error_number, transaction
from app.models import (
    Booking,
    BookingGroup,
    BookingNote,
    BookingWatcher,
    Station,
    Status,
    User,
)
from app.schemas.bookings import BookingCreateRequest, BookingItem, GroupInfo, NoteSaveResponse
from app.schemas.contracts import BookingSnapshot, ErrorCode, Note, NoteSaveRequest
from app.schemas.realtime import BookingUpdatedData
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.services.booking_reads import invoice_previews, snapshot_from_row, snapshot_query
from app.services.invoice_service import invoice_items
from app.services.key_index import GroupEntry, KeyEntry
from app.services.suggestions import Suggestions
from app.utils.booking_key import ParsedKey, PartialKey, build_key, parse
from app.utils.folder_key import folder_parts
from app.utils.text import clean_note


def group_entry(group: BookingGroup) -> GroupEntry:
    return GroupEntry(
        group.id,
        GroupInfo(
            cw_number=group.cw_number,
            station_code=group.station_code,
            supplier_name=group.supplier_name,
            supplier_type=group.supplier_type,
            recurring_enabled=group.recurring_enabled,
        ),
        group.last_activity_at,
    )


def supplier_name(value: str | None) -> str:
    result = clean_note(value)
    if result is None or not 3 <= len(result) <= 255:
        raise ApiException(ErrorCode.SUPPLIER_REQUIRED)
    return result


class BookingWrites:
    def __init__(self, engine, settings, index, cache, ws_manager):
        self.engine, self.settings, self.index, self.cache = engine, settings, index, cache
        self.ws_manager = ws_manager
        self.suggestions = Suggestions(engine, settings, index)

    async def create(self, body: BookingCreateRequest, user, context) -> BookingItem:
        """Insert an empty booking; the unique key remains the duplicate authority."""
        parsed = parse(body.booking_key, self.settings.station_code_pattern)
        if isinstance(parsed, PartialKey):
            raise ApiException(ErrorCode.STATION_REQUIRED)
        if not isinstance(parsed, ParsedKey):
            raise ApiException(ErrorCode.INVALID_BOOKING_KEY)

        identifier = None
        key_entry = changed_group = event = None

        def committed() -> None:
            self.cache.invalidate(identifier)
            self.index.update(key_entry, changed_group)
            self.invoice_service.report_cache.clear()
            self.ws_manager.saved(user.id, user.session_id, event, None)

        async with request_budget(self.settings.note_save_timeout_seconds):
            for attempt in range(2):
                try:
                    async with transaction(
                        self.engine,
                        self.settings,
                        seconds=self.settings.note_save_timeout_seconds,
                        retryable=True,
                        after_commit=committed,
                    ) as session:
                        live = await session.scalar(
                            select(User).where(User.id == user.id).with_for_update()
                        )
                        AuthService.require_live_row(live, user)
                        group = await session.scalar(
                            select(BookingGroup)
                            .where(
                                BookingGroup.cw_number == parsed.cw_number,
                                BookingGroup.station_code == parsed.station_code,
                            )
                            .with_for_update()
                        )
                        existing = await session.scalar(
                            select(Booking.id)
                            .where(Booking.booking_key == parsed.key)
                            .with_for_update()
                        )
                        if existing is not None:
                            raise ApiException(
                                ErrorCode.BOOKING_EXISTS,
                                details={
                                    "booking_key": parsed.key,
                                    "display_key": parsed.display_key,
                                },
                            )
                        # Existing folders retain their supplier and recurrence settings.
                        if group is None:
                            name = supplier_name(body.supplier_name)
                            if body.supplier_type is None:
                                raise ApiException(ErrorCode.SUPPLIER_REQUIRED)
                        if not body.confirm_new:
                            suggestions = await self.suggestions.find(parsed.key, session)
                            if suggestions:
                                raise ApiException(
                                    ErrorCode.NEW_BOOKING_NEEDS_CONFIRM,
                                    details={
                                        "suggestions": [
                                            row.model_dump(mode="json") for row in suggestions
                                        ]
                                    },
                                )
                        now = datetime.now(UTC)
                        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
                        if group is None:
                            group = BookingGroup(
                                cw_number=parsed.cw_number,
                                station_code=parsed.station_code,
                                supplier_name=name,
                                supplier_type=body.supplier_type,
                                created_by=user.id,
                                booking_count=0,
                                last_activity_at=now,
                            )
                            session.add(group)
                            await session.flush()
                            station_insert = insert(Station).values(code=parsed.station_code)
                            await session.execute(
                                station_insert.on_duplicate_key_update(
                                    code=station_insert.inserted.code
                                )
                            )
                        booking = Booking(
                            booking_key=parsed.key,
                            group_id=group.id,
                            cw_number=parsed.cw_number,
                            station_code=parsed.station_code,
                            period=parsed.period,
                            version=1,
                            invoice_state="unknown",
                            invoice_count=0,
                            updated_at=now,
                        )
                        session.add(booking)
                        await session.flush()
                        identifier = booking.id
                        group.booking_count += 1
                        group.last_activity_at = group.updated_at = now
                        record_audit(
                            session,
                            "booking_created",
                            actor_id=user.id,
                            entity_type="booking",
                            entity_id=str(booking.id),
                            context=context,
                            meta={"booking_key": parsed.key},
                        )
                        await session.flush()
                        row = (
                            await session.execute(snapshot_query().where(Booking.id == booking.id))
                        ).one()
                        result = snapshot_from_row(row, self.settings)
                        changed_group = group_entry(group)
                        key_entry = KeyEntry(
                            booking.id,
                            group.id,
                            parsed.key,
                            parsed.cw_number,
                            parsed.period,
                            parsed.station_code,
                        )
                        event = BookingUpdatedData(
                            booking_key=parsed.key,
                            display_key=parsed.display_key,
                            cw_number=parsed.cw_number,
                            station_code=parsed.station_code,
                            version=result.version,
                            last_agent_id=None,
                            last_agent_name=None,
                            status_code=None,
                            position=None,
                            updated_at=result.updated_at,
                            is_done=False,
                        ).model_dump(mode="json")
                    return result
                except DBAPIError as exc:
                    # A concurrent insert may win either unique key. Re-read it on retry
                    # so the loser returns BOOKING_EXISTS without a second row or count.
                    if error_number(exc) in {1062, 1213} and attempt == 0:
                        continue
                    raise ApiException(ErrorCode.SERVICE_BUSY) from None
                finally:
                    if identifier is not None:
                        self.cache.invalidate(identifier)

    async def save(self, raw: str, body: NoteSaveRequest, user, context) -> NoteSaveResponse:
        parsed = parse(raw, self.settings.station_code_pattern)
        if isinstance(parsed, PartialKey):
            async with transaction(self.engine, self.settings) as session:
                stations = list(
                    (
                        await session.scalars(
                            select(BookingGroup.station_code).where(
                                BookingGroup.cw_number == parsed.cw_number
                            )
                        )
                    ).all()
                )
                station = stations[0] if len(stations) == 1 else None
            details = (
                {
                    "suggested_key": build_key(
                        parsed.cw_number, station, parsed.period, self.settings.station_code_pattern
                    )
                }
                if station
                else None
            )
            raise ApiException(ErrorCode.STATION_REQUIRED, details=details)
        if not isinstance(parsed, ParsedKey):
            raise ApiException(ErrorCode.INVALID_BOOKING_KEY)
        if raw != parsed.key:
            raise ApiException(
                ErrorCode.INVALID_BOOKING_KEY,
                details={"suggested_key": parsed.key, "display_key": parsed.display_key},
            )
        cleaned = clean_note(body.note)
        if body.note is not None and len(body.note) > 5000:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR, message="Notes may contain up to 5,000 characters."
            )
        if body.expected_version < 0:
            raise ApiException(ErrorCode.VALIDATION_ERROR)
        payload = body.model_dump(mode="json", exclude_unset=True)
        payload["note"] = cleaned
        fingerprint = hashlib.sha256(
            json.dumps(
                [user.id, parsed.key, payload], sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        identifier = None
        result = None
        changed_group = None
        key_entry = None
        new_write = False
        booking_event = None
        notification_event = None

        def committed() -> None:
            if identifier is not None and key_entry is not None and changed_group is not None:
                self.cache.invalidate(identifier)
                self.index.update(key_entry, changed_group)
                if new_write:
                    self.invoice_service.report_cache.clear()
                    self.ws_manager.saved(
                        user.id, user.session_id, booking_event, notification_event
                    )
                else:
                    self.ws_manager.locks.release(user.id, parsed.key, session_id=user.session_id)

        # One deadline spans both attempts, including lock waits and post-commit hooks.
        async with request_budget(self.settings.note_save_timeout_seconds):
            for attempt in range(2):
                new_write = False
                notification_event = None
                try:
                    async with transaction(
                        self.engine,
                        self.settings,
                        seconds=self.settings.note_save_timeout_seconds,
                        retryable=True,
                        after_commit=committed,
                    ) as session:
                        ids = sorted({user.id, body.assign_to or user.id})
                        users = {
                            r.id: r
                            for r in (
                                await session.scalars(
                                    select(User)
                                    .where(User.id.in_(ids))
                                    .order_by(User.id)
                                    .with_for_update()
                                )
                            ).all()
                        }
                        live = users.get(user.id)
                        AuthService.require_live_row(live, user)
                        prior = await session.scalar(
                            select(BookingNote).where(
                                BookingNote.client_request_id == str(body.client_request_id)
                            )
                        )
                        if prior:
                            if (
                                prior.agent_id != user.id
                                or prior.request_fingerprint != fingerprint
                                or prior.save_result is None
                            ):
                                raise ApiException(
                                    ErrorCode.VALIDATION_ERROR,
                                    message="This request ID belongs to a different note.",
                                )
                            identifier = prior.booking_id
                            existing = await session.get(Booking, identifier)
                            folder = await session.get(BookingGroup, existing.group_id)
                            changed_group = group_entry(folder)
                            key_entry = KeyEntry(
                                existing.id,
                                existing.group_id,
                                existing.booking_key,
                                existing.cw_number,
                                existing.period,
                                existing.station_code,
                            )
                            return NoteSaveResponse.model_validate(prior.save_result)
                        if body.assign_to is not None:
                            target = users.get(body.assign_to)
                            if body.assign_to == user.id or target is None or not target.is_active:
                                raise ApiException(
                                    ErrorCode.ASSIGNMENT_INVALID,
                                    message="Choose another active user.",
                                )
                        elif body.assign_message is not None:
                            raise ApiException(
                                ErrorCode.ASSIGNMENT_INVALID,
                                message="Choose an assignee for this message.",
                            )
                        status = await session.scalar(
                            select(Status).where(Status.code == body.status_code).with_for_update()
                        )
                        if status is None or not status.is_active:
                            raise ApiException(ErrorCode.STATUS_INACTIVE)
                        if status.note_required and not cleaned:
                            raise ApiException(ErrorCode.NOTE_REQUIRED)
                        group = await session.scalar(
                            select(BookingGroup)
                            .where(
                                BookingGroup.cw_number == parsed.cw_number,
                                BookingGroup.station_code == parsed.station_code,
                            )
                            .with_for_update()
                        )
                        now = datetime.now(UTC)
                        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
                        if group is None:
                            name = supplier_name(body.supplier_name)
                            group = BookingGroup(
                                cw_number=parsed.cw_number,
                                station_code=parsed.station_code,
                                supplier_name=name,
                                supplier_type=body.supplier_type.value
                                if body.supplier_type
                                else "unclassified",
                                created_by=user.id,
                                booking_count=0,
                                last_activity_at=now,
                            )
                            session.add(group)
                            await session.flush()
                            station_insert = insert(Station).values(code=parsed.station_code)
                            await session.execute(
                                station_insert.on_duplicate_key_update(
                                    code=station_insert.inserted.code
                                )
                            )
                        booking = await session.scalar(
                            select(Booking)
                            .where(Booking.booking_key == parsed.key)
                            .with_for_update()
                        )
                        if booking is None:
                            if not body.confirm_new:
                                suggestions = await self.suggestions.find(parsed.key, session)
                                if suggestions:
                                    raise ApiException(
                                        ErrorCode.NEW_BOOKING_NEEDS_CONFIRM,
                                        details={
                                            "suggestions": [
                                                s.model_dump(mode="json") for s in suggestions
                                            ]
                                        },
                                    )
                            if body.expected_version != 0:
                                raise ApiException(
                                    ErrorCode.VERSION_CONFLICT,
                                    details={"snapshot": None, "version": 0},
                                )
                            booking = Booking(
                                booking_key=parsed.key,
                                group_id=group.id,
                                cw_number=parsed.cw_number,
                                station_code=parsed.station_code,
                                period=parsed.period,
                                version=0,
                                invoice_state="unknown",
                                invoice_count=0,
                            )
                            session.add(booking)
                            await session.flush()
                            group.booking_count += 1
                        identifier = booking.id
                        if booking.version != body.expected_version:
                            row = (
                                await session.execute(
                                    snapshot_query().where(Booking.id == booking.id)
                                )
                            ).one()
                            previews = await invoice_previews(session, [booking.id])
                            latest = snapshot_from_row(row, self.settings, previews.get(booking.id))
                            raise ApiException(
                                ErrorCode.VERSION_CONFLICT, details=latest.model_dump(mode="json")
                            )
                        if not body.allow_duplicate:
                            recent = (
                                await session.scalars(
                                    select(BookingNote)
                                    .where(
                                        BookingNote.booking_id == booking.id,
                                        BookingNote.agent_id == user.id,
                                        BookingNote.status_id == status.id,
                                        BookingNote.created_at >= now - timedelta(seconds=60),
                                        BookingNote.created_at <= now,
                                        BookingNote.deleted_at.is_(None),
                                    )
                                    .order_by(BookingNote.id.desc())
                                )
                            ).all()
                            normalized = " ".join((cleaned or "").split()).casefold()
                            for previous in recent:
                                if " ".join((previous.note or "").split()).casefold() == normalized:
                                    dto = Note(
                                        id=previous.id,
                                        agent={"id": live.id, "full_name": live.full_name},
                                        status={"code": status.code, "label": status.label},
                                        position=previous.position_label,
                                        note=previous.note,
                                        created_at=previous.created_at,
                                        attachments=[],
                                        invoice_change=previous.invoice_change,
                                    )
                                    raise ApiException(
                                        ErrorCode.DUPLICATE_RECENT_NOTE,
                                        details={
                                            "note": dto.model_dump(mode="json"),
                                            "seconds": max(
                                                0, int((now - previous.created_at).total_seconds())
                                            ),
                                        },
                                    )
                        invoice_result = (
                            await self.invoice_service.apply_changes(
                                session, booking, live, body.invoices, context=context
                            )
                            if body.invoices is not None
                            else None
                        )
                        if status.invoice_required and booking.invoice_state == "unknown":
                            raise ApiException(ErrorCode.INVOICE_REQUIRED)
                        change = (
                            {
                                name: invoice_result[name]
                                for name in ("added", "removed", "no_invoice")
                            }
                            if invoice_result
                            else None
                        )
                        note = BookingNote(
                            booking_id=booking.id,
                            agent_id=user.id,
                            status_id=status.id,
                            position_label=status.position_label,
                            note=cleaned,
                            created_at=now,
                            client_request_id=str(body.client_request_id),
                            request_fingerprint=fingerprint,
                            invoice_change=change,
                        )
                        session.add(note)
                        await session.flush()
                        previous_agent = booking.last_agent_id
                        booking.last_note_id, booking.last_agent_id, booking.last_status_id = (
                            note.id,
                            user.id,
                            status.id,
                        )
                        booking.last_position, booking.last_note_preview = (
                            status.position_label,
                            cleaned[:255] if cleaned else None,
                        )
                        booking.is_done, booking.done_at = (
                            status.is_done,
                            now if status.is_done else None,
                        )
                        booking.updated_at, booking.stale_notified_at = now, None
                        booking.version += 1
                        group.last_activity_at, group.updated_at = now, now
                        notification_event = await self.collaboration.note_effects(
                            session, booking, note, live, body, previous_agent, now
                        )
                        record_audit(
                            session,
                            "booking_note_created",
                            actor_id=user.id,
                            entity_type="note",
                            entity_id=str(note.id),
                            context=context,
                            meta={
                                "booking_key": booking.booking_key,
                                "note_id": note.id,
                                "version": booking.version,
                            },
                        )
                        await session.flush()
                        row = (
                            await session.execute(snapshot_query().where(Booking.id == booking.id))
                        ).one()
                        previews = await invoice_previews(session, [booking.id])
                        snapshot = snapshot_from_row(row, self.settings, previews.get(booking.id))
                        result = NoteSaveResponse(
                            invoices=await invoice_items(session, booking.id)
                            if booking.invoice_count
                            else [],
                            skipped_duplicates=invoice_result["skipped_duplicates"]
                            if invoice_result
                            else [],
                            warnings=invoice_result["warnings"] if invoice_result else [],
                            my_watching=await session.get(BookingWatcher, (booking.id, user.id))
                            is not None,
                            snapshot=BookingSnapshot.model_validate(
                                snapshot.model_dump(
                                    exclude={
                                        "supplier_name",
                                        "supplier_type",
                                        "my_pending_tasks",
                                        "my_watching",
                                        "stale_hours",
                                    }
                                )
                            ),
                            note=Note(
                                id=note.id,
                                agent={"id": live.id, "full_name": live.full_name},
                                status={"code": status.code, "label": status.label},
                                position=status.position_label,
                                note=cleaned,
                                created_at=now,
                                attachments=[],
                                invoice_change=change,
                            ),
                        )
                        note.save_result = result.model_dump(mode="json")
                        booking_event = BookingUpdatedData(
                            booking_key=parsed.key,
                            display_key=parsed.display_key,
                            cw_number=parsed.cw_number,
                            station_code=parsed.station_code,
                            version=snapshot.version,
                            invoice_state=snapshot.invoice_state,
                            invoice_count=snapshot.invoice_count,
                            last_agent_id=live.id,
                            last_agent_name=live.full_name,
                            status_code=status.code,
                            position=status.position_label,
                            updated_at=snapshot.updated_at,
                            is_done=snapshot.is_done,
                        ).model_dump(mode="json")
                        new_write = True
                        changed_group = group_entry(group)
                        key_entry = KeyEntry(
                            booking.id,
                            group.id,
                            booking.booking_key,
                            booking.cw_number,
                            booking.period,
                            booking.station_code,
                        )
                    break
                except DBAPIError as exc:
                    if error_number(exc) in {1062, 1213} and attempt == 0:
                        continue
                    raise ApiException(ErrorCode.SERVICE_BUSY) from None
                finally:
                    # Also covers cancelled/uncertain commits; a later read must query the DB.
                    if identifier is not None:
                        self.cache.invalidate(identifier)
            return result

    async def patch_folder(self, cw: str, body, user, context) -> GroupInfo:
        cw, station = folder_parts(cw)
        if not body.model_fields_set or (
            body.supplier_type is None and "supplier_type" in body.model_fields_set
        ):
            raise ApiException(ErrorCode.VALIDATION_ERROR)
        group_id = None
        try:

            def committed() -> None:
                self.cache.invalidate_group(group_id)
                self.index.update(None, changed)

            async with transaction(self.engine, self.settings, after_commit=committed) as session:
                live = await session.scalar(
                    select(User).where(User.id == user.id).with_for_update()
                )
                AuthService.require_live_row(live, user)
                if live.role not in {"admin", "qc"}:
                    raise ApiException(ErrorCode.FORBIDDEN)
                conditions = [BookingGroup.cw_number == cw]
                if station:
                    conditions.append(BookingGroup.station_code == station)
                groups = list(
                    (
                        await session.scalars(
                            select(BookingGroup).where(*conditions).with_for_update()
                        )
                    ).all()
                )
                if len(groups) > 1:
                    raise ApiException(
                        ErrorCode.VALIDATION_ERROR, message="Choose a station folder."
                    )
                group = groups[0] if groups else None
                if group is None:
                    raise ApiException(ErrorCode.NOT_FOUND)
                group_id = group.id
                if "supplier_name" in body.model_fields_set:
                    group.supplier_name = supplier_name(body.supplier_name)
                if body.supplier_type is not None:
                    group.supplier_type = body.supplier_type.value
                if "recurring_enabled" in body.model_fields_set:
                    if body.recurring_enabled is None:
                        raise ApiException(ErrorCode.VALIDATION_ERROR)
                    group.recurring_enabled = body.recurring_enabled
                group.updated_at = datetime.now(UTC)
                changed = group_entry(group)
                record_audit(
                    session,
                    "folder_updated",
                    actor_id=user.id,
                    entity_type="booking",
                    entity_id=cw,
                    context=context,
                    meta={"cw_number": cw},
                )
            return changed.info
        finally:
            if group_id is not None:
                self.cache.invalidate_group(group_id)
