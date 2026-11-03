import hashlib
import json
import re
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
    BookingInvoice,
    BookingNote,
    Notification,
    Station,
    Status,
    User,
)
from app.schemas.bookings import GroupInfo, NoteSaveResponse
from app.schemas.contracts import BookingSnapshot, ErrorCode, Note, NoteSaveRequest
from app.schemas.realtime import BookingUpdatedData, NotificationNewData
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.services.booking_reads import invoice_previews, snapshot_from_row, snapshot_query
from app.services.key_index import GroupEntry, KeyEntry
from app.services.suggestions import Suggestions
from app.utils.booking_key import ParsedKey, PartialKey, build_key, parse, to_display
from app.utils.text import clean_note


def group_entry(group: BookingGroup) -> GroupEntry:
    return GroupEntry(
        group.id,
        GroupInfo(
            cw_number=group.cw_number,
            station_code=group.station_code,
            supplier_name=group.supplier_name,
            supplier_type=group.supplier_type,
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

    async def invoices(self, session, booking, change, user, status):
        rows = (
            await session.scalars(
                select(BookingInvoice)
                .where(BookingInvoice.booking_id == booking.id)
                .order_by(BookingInvoice.id)
            )
        ).all()
        added, removed = [], []
        declared = None
        if change is not None:
            values = list(dict.fromkeys(value.strip().upper() for value in change.add))
            invalid = [
                value
                for value in values
                if re.fullmatch(self.settings.invoice_number_pattern, value, re.ASCII) is None
            ]
            if invalid:
                raise ApiException(ErrorCode.INVOICE_INVALID, details={"invalid": invalid})
            ids = set(change.remove_ids)
            if ids - {row.id for row in rows}:
                raise ApiException(ErrorCode.NOT_FOUND)
            for row in rows:
                if row.id in ids:
                    if row.added_by != user.id and user.role not in {"admin", "qc"}:
                        raise ApiException(ErrorCode.FORBIDDEN)
                    removed.append(row.invoice_number)
                    await session.delete(row)
            rows = [row for row in rows if row.id not in ids]
            existing = {row.invoice_number for row in rows}
            added = [value for value in values if value not in existing]
            if change.no_invoice and (rows or added):
                raise ApiException(ErrorCode.INVOICE_STATE_CONFLICT)
            if len(rows) + len(added) > self.settings.invoice_max_per_booking:
                raise ApiException(ErrorCode.INVOICE_LIMIT_REACHED)
            for number in added:
                session.add(
                    BookingInvoice(booking_id=booking.id, invoice_number=number, added_by=user.id)
                )
            booking.invoice_count = len(rows) + len(added)
            if "no_invoice" in change.model_fields_set:
                declared = change.no_invoice
            if booking.invoice_count:
                booking.invoice_state = "has_invoice"
            elif change.no_invoice:
                booking.invoice_state = "no_invoice"
            elif declared is False or removed:
                booking.invoice_state = "unknown"
        if status.invoice_required and booking.invoice_state == "unknown":
            raise ApiException(ErrorCode.INVOICE_REQUIRED)
        return (
            {"added": added, "removed": removed, "no_invoice": declared}
            if change is not None
            else None
        )

    async def save(self, raw: str, body: NoteSaveRequest, user, context) -> NoteSaveResponse:
        parsed = parse(raw, self.settings.station_code_pattern)
        if isinstance(parsed, PartialKey):
            async with transaction(self.engine, self.settings) as session:
                station = await session.scalar(
                    select(BookingGroup.station_code).where(
                        BookingGroup.cw_number == parsed.cw_number
                    )
                )
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
                    self.ws_manager.saved(
                        user.id, user.session_id, booking_event, notification_event
                    )
                else:
                    self.ws_manager.locks.release(user.id, parsed.key, session_id=user.session_id)

        # One deadline spans both attempts, including lock waits and post-commit hooks.
        async with request_budget(self.settings.note_save_timeout_seconds):
            for attempt in range(2):
                new_write = False
                notification_row = None
                notification_event = None
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
                        if body.assign_to is not None or body.assign_message is not None:
                            raise ApiException(
                                ErrorCode.ASSIGNMENT_INVALID,
                                message="Assignments are not enabled yet.",
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
                            .where(BookingGroup.cw_number == parsed.cw_number)
                            .with_for_update()
                        )
                        now = datetime.now(UTC)
                        now = now.replace(microsecond=now.microsecond // 1000 * 1000)
                        if group is None:
                            name = supplier_name(body.supplier_name)
                            if body.supplier_type is None:
                                raise ApiException(ErrorCode.SUPPLIER_REQUIRED)
                            group = BookingGroup(
                                cw_number=parsed.cw_number,
                                station_code=parsed.station_code,
                                supplier_name=name,
                                supplier_type=body.supplier_type.value,
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
                        elif group.station_code != parsed.station_code:
                            suggested = build_key(
                                parsed.cw_number,
                                group.station_code,
                                parsed.period,
                                self.settings.station_code_pattern,
                            )
                            raise ApiException(
                                ErrorCode.STATION_MISMATCH,
                                details={
                                    "expected_station": group.station_code,
                                    "suggested_key": suggested,
                                    "display_key": to_display(suggested),
                                },
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
                        change = await self.invoices(session, booking, body.invoices, live, status)
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
                        if previous_agent and previous_agent != user.id:
                            notification_row = Notification(
                                user_id=previous_agent,
                                booking_id=booking.id,
                                type="taken_over",
                                note_id=note.id,
                                by_agent_id=user.id,
                                created_at=now,
                            )
                            session.add(notification_row)
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
                            snapshot=BookingSnapshot.model_validate(
                                snapshot.model_dump(
                                    exclude={
                                        "supplier_name",
                                        "supplier_type",
                                        "my_pending_tasks",
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
                            last_agent_id=live.id,
                            last_agent_name=live.full_name,
                            status_code=status.code,
                            position=status.position_label,
                            updated_at=snapshot.updated_at,
                            is_done=snapshot.is_done,
                        ).model_dump(mode="json")
                        if notification_row is not None:
                            notification_event = (
                                previous_agent,
                                NotificationNewData(
                                    id=notification_row.id,
                                    booking_key=parsed.key,
                                    display_key=parsed.display_key,
                                    by_agent_name=live.full_name,
                                    created_at=now,
                                    type="taken_over",
                                ).model_dump(mode="json"),
                            )
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
        if not re.fullmatch(r"CW[0-9]{5,10}", cw, re.ASCII):
            raise ApiException(ErrorCode.INVALID_BOOKING_KEY)
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
                group = await session.scalar(
                    select(BookingGroup).where(BookingGroup.cw_number == cw).with_for_update()
                )
                if group is None:
                    raise ApiException(ErrorCode.NOT_FOUND)
                group_id = group.id
                if "supplier_name" in body.model_fields_set:
                    group.supplier_name = supplier_name(body.supplier_name)
                if body.supplier_type is not None:
                    group.supplier_type = body.supplier_type.value
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
