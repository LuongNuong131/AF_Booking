"""Single-instance, resumable-by-new-run integrity checks; repairs recheck under locks."""

import asyncio
import logging
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, BookingInvoice, BookingNote, IntegrityRun, Status
from app.schemas.contracts import ErrorCode
from app.schemas.integrity import (
    IntegrityDetails,
    IntegrityFinding,
    IntegrityHistory,
    IntegrityRunDTO,
)
from app.schemas.realtime import BookingUpdatedData
from app.services.admin import locked_admin
from app.services.audit import record_audit
from app.services.booking_reads import invoice_previews, snapshot_from_row, snapshot_query
from app.services.booking_writes import group_entry
from app.services.key_index import KeyEntry
from app.services.snapshot_values import apply_snapshot, note_snapshot
from app.utils.booking_key import to_display

logger = logging.getLogger(__name__)


def now():
    value = datetime.now(UTC)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def batch_query(after, high_water, size=1000):
    # Constrain MAX(id) to this batch, never GROUP BY the entire note table per batch.
    batch = (
        select(Booking.id)
        .where(Booking.id > after, Booking.id <= high_water)
        .order_by(Booking.id)
        .limit(size)
        .cte("integrity_batch")
    )
    latest = (
        select(BookingNote.booking_id, func.max(BookingNote.id).label("note_id"))
        .join(batch, batch.c.id == BookingNote.booking_id)
        .where(BookingNote.deleted_at.is_(None))
        .group_by(BookingNote.booking_id)
        .subquery()
    )
    invoices = (
        select(BookingInvoice.booking_id, func.count().label("actual_invoice_count"))
        .join(batch, batch.c.id == BookingInvoice.booking_id)
        .group_by(BookingInvoice.booking_id)
        .subquery()
    )
    names = (
        "invoice_state",
        "invoice_count",
        "last_note_id",
        "last_agent_id",
        "last_status_id",
        "last_position",
        "last_note_preview",
        "is_done",
        "done_at",
    )
    return (
        select(
            Booking.id,
            Booking.booking_key,
            *[getattr(Booking, field) for field in names],
            func.coalesce(invoices.c.actual_invoice_count, 0).label("actual_invoice_count"),
            BookingNote.id.label("expected_id"),
            BookingNote.agent_id,
            BookingNote.status_id,
            BookingNote.position_label,
            BookingNote.created_at,
            func.left(BookingNote.note, 255).label("note"),
            Status.id.label("source_status_id"),
            Status.is_done.label("expected_done"),
        )
        .join(batch, batch.c.id == Booking.id)
        .outerjoin(invoices, invoices.c.booking_id == Booking.id)
        .outerjoin(latest, latest.c.booking_id == Booking.id)
        .outerjoin(BookingNote, BookingNote.id == latest.c.note_id)
        .outerjoin(Status, Status.id == BookingNote.status_id)
        .order_by(Booking.id)
    )


def derive(row):
    values = note_snapshot(
        row.expected_id,
        row.agent_id,
        row.status_id,
        row.position_label,
        row.created_at,
        row.note,
        row.expected_done,
    )
    if hasattr(row, "actual_invoice_count"):
        values.update(
            invoice_count=row.actual_invoice_count,
            invoice_state="has_invoice"
            if row.actual_invoice_count
            else "no_invoice"
            if row.invoice_state == "no_invoice"
            else "unknown",
        )
    return values


def difference(actual, expected):
    def wire(value):
        return (
            value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            if isinstance(value, datetime)
            else value
        )

    return {
        field: {"actual": wire(getattr(actual, field)), "expected": wire(value)}
        for field, value in expected.items()
        if getattr(actual, field) != value
    }


class IntegrityService:
    def __init__(self, engine, settings, admin):
        self.engine, self.settings, self.admin = engine, settings, admin
        self.lock = asyncio.Lock()
        self.task = None
        self.recovered = False
        self.scheduled_day = None
        self.clock = now

    def tx(self, **kwargs):
        return transaction(self.engine, self.settings, **kwargs)

    async def recover(self):
        async with self.lock:
            if self.recovered:
                return
            async with self.tx() as session:
                await session.execute(
                    update(IntegrityRun)
                    .where(IntegrityRun.status == "running")
                    .values(status="interrupted", finished_at=self.clock())
                )
            self.recovered = True

    async def history(self, page=1, size=20):
        await self.recover()
        async with self.tx() as session:
            total = await session.scalar(select(func.count()).select_from(IntegrityRun))
            rows = (
                await session.scalars(
                    select(IntegrityRun)
                    .order_by(IntegrityRun.started_at.desc(), IntegrityRun.id.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
            return IntegrityHistory(
                items=[IntegrityRunDTO.model_validate(r, from_attributes=True) for r in rows],
                total=total,
                page=page,
                size=size,
                autofix_enabled=self.settings.integrity_autofix,
                run_time=self.settings.integrity_run_time,
                timezone=self.settings.business_timezone,
            )

    async def start(self, actor=None, context=None, *, source_run_id=None, scheduled_day=None):
        async with self.lock:
            if self.task is not None and not self.task.done():
                raise ApiException(
                    ErrorCode.SERVICE_BUSY, message="An integrity check is already running."
                )
            details = IntegrityDetails(
                mode="fix" if source_run_id or self.settings.integrity_autofix else "report",
                trigger="scheduled" if scheduled_day else "manual",
                requested_by=actor.id if actor else None,
                source_run_id=source_run_id,
                scheduled_day=scheduled_day,
            )
            row = IntegrityRun(
                started_at=self.clock(),
                status="running",
                checked=0,
                mismatched=0,
                fixed=0,
                details=details.model_dump(mode="json"),
            )

            def launch():
                # Commit-owned work survives a cancelled HTTP acknowledgement.
                self.task = asyncio.create_task(
                    self.execute(row.id, details, actor, context), name="integrity-run"
                )
                self.task.add_done_callback(self.consume)

            async with self.tx(after_commit=launch) as session:
                if actor is not None:
                    await locked_admin(session, actor)
                if not self.recovered:
                    await session.execute(
                        update(IntegrityRun)
                        .where(IntegrityRun.status == "running")
                        .values(status="interrupted", finished_at=self.clock())
                    )
                if source_run_id:
                    source = await session.get(IntegrityRun, source_run_id)
                    if source is None:
                        raise ApiException(ErrorCode.NOT_FOUND)
                    if source.status == "running" or source.mismatched == 0:
                        raise ApiException(
                            ErrorCode.VALIDATION_ERROR,
                            message="Choose a finished run with mismatches.",
                        )
                session.add(row)
                await session.flush()
                record_audit(
                    session,
                    "integrity_fix_started" if details.mode == "fix" else "integrity_run_started",
                    actor_id=actor.id if actor else None,
                    context=context,
                    entity_type="integrity_run",
                    entity_id=str(row.id),
                    meta={
                        "mode": details.mode,
                        "trigger": details.trigger,
                        "source_run_id": source_run_id,
                    },
                )
            self.recovered = True
            return IntegrityRunDTO.model_validate(row, from_attributes=True)

    @staticmethod
    def consume(task):
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Integrity worker failed (%s)", type(task.exception()).__name__)

    async def progress(self, run_id, details, checked, mismatched, status):
        async with self.tx() as session:
            await session.execute(
                update(IntegrityRun)
                .where(IntegrityRun.id == run_id)
                .values(
                    checked=checked,
                    mismatched=mismatched,
                    details=details.model_dump(mode="json"),
                    status=status,
                    finished_at=self.clock() if status != "running" else None,
                )
            )

    async def execute(self, run_id, details, actor, context):
        checked = mismatched = 0
        state = "completed"
        try:
            async with asyncio.timeout(self.settings.integrity_timeout_seconds):
                async with self.tx() as session:
                    details.high_water_id = await session.scalar(select(func.max(Booking.id))) or 0
                after = 0
                while after < details.high_water_id:
                    async with self.tx() as session:
                        rows = (
                            await session.execute(batch_query(after, details.high_water_id))
                        ).all()
                    if not rows:
                        break
                    for row in rows:
                        checked += 1
                        fields = difference(row, derive(row))
                        repairable = row.expected_id is None or row.source_status_id is not None
                        if not repairable:
                            fields["source_status"] = {
                                "actual": row.status_id,
                                "expected": "An existing status",
                            }
                        if fields:
                            mismatched += 1
                            item = IntegrityFinding(
                                booking_key=row.booking_key,
                                display_key=to_display(row.booking_key),
                                fields=fields,
                                repairable=repairable,
                            )
                            if len(details.items) < 200:
                                details.items.append(item)
                            else:
                                details.truncated = True
                            if details.mode == "fix" and repairable:
                                item.fixed = await self.repair(row.id, run_id, actor, context)
                    after = rows[-1].id
                    await self.progress(run_id, details, checked, mismatched, "running")
                    if after < details.high_water_id:
                        await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            state = "interrupted"
            raise
        except Exception as exc:
            state = "failed"
            details.error = "The integrity check could not finish. Start a new check."
            logger.warning("Integrity run %s failed (%s)", run_id, type(exc).__name__)
        finally:
            await self.progress(run_id, details, checked, mismatched, state)

    async def repair(self, identifier, run_id, actor, context):
        event = entry = folder = None

        def committed():
            if event:
                self.admin.writes.cache.invalidate(identifier)
                self.admin.writes.index.update(entry, folder)
                self.admin.reports.invalidate()
                self.admin.writes.invoice_service.report_cache.clear()
                self.admin.ws.spawn(self.admin.ws.broadcast("booking.updated", event))

        async with self.tx(after_commit=committed) as session:
            if actor:
                await locked_admin(session, actor)
            group_id = await session.scalar(
                select(Booking.group_id).where(Booking.id == identifier)
            )
            if group_id is None:
                return False
            group = await session.scalar(
                select(BookingGroup).where(BookingGroup.id == group_id).with_for_update()
            )
            book = await session.scalar(
                select(Booking).where(Booking.id == identifier).with_for_update()
            )
            latest = (
                await session.execute(
                    select(BookingNote, Status.is_done)
                    .outerjoin(Status, Status.id == BookingNote.status_id)
                    .where(BookingNote.booking_id == identifier, BookingNote.deleted_at.is_(None))
                    .order_by(BookingNote.id.desc())
                    .limit(1)
                )
            ).first()
            note = latest.BookingNote if latest else None
            if note and latest.is_done is None:
                return False
            expected = note_snapshot(
                note.id if note else None,
                note.agent_id if note else None,
                note.status_id if note else None,
                note.position_label if note else None,
                note.created_at if note else None,
                note.note if note else None,
                latest.is_done if latest else False,
            )
            count = await session.scalar(
                select(func.count())
                .select_from(BookingInvoice)
                .where(BookingInvoice.booking_id == identifier)
            )
            expected.update(
                invoice_count=count,
                invoice_state="has_invoice"
                if count
                else "no_invoice"
                if book.invoice_state == "no_invoice"
                else "unknown",
            )
            changed = difference(book, expected)
            if not changed:
                return False
            apply_snapshot(book, expected)
            book.version += 1
            flag_modified(book, "updated_at")  # Explicitly bind unchanged operational time.
            if set(changed) - {"invoice_count", "invoice_state"}:
                book.stale_notified_at = None
            await session.execute(
                update(IntegrityRun)
                .where(IntegrityRun.id == run_id)
                .values(fixed=IntegrityRun.fixed + 1)
            )
            record_audit(
                session,
                "integrity_snapshot_fixed",
                actor_id=actor.id if actor else None,
                context=context,
                entity_type="booking",
                entity_id=book.booking_key,
                meta={"run_id": run_id, "fields": list(changed), "version": book.version},
            )
            await session.flush()
            row = (await session.execute(snapshot_query().where(Booking.id == identifier))).one()
            snapshot = snapshot_from_row(
                row, self.settings, (await invoice_previews(session, [identifier])).get(identifier)
            )
            event = BookingUpdatedData(
                booking_key=book.booking_key,
                display_key=to_display(book.booking_key),
                cw_number=book.cw_number,
                station_code=book.station_code,
                version=book.version,
                last_agent_id=book.last_agent_id,
                last_agent_name=snapshot.last_agent.full_name if snapshot.last_agent else None,
                status_code=snapshot.last_status.code if snapshot.last_status else None,
                position=book.last_position,
                updated_at=book.updated_at,
                is_done=book.is_done,
                snapshot_rebuilt=True,
                invoice_state=book.invoice_state,
                invoice_count=book.invoice_count,
            ).model_dump(mode="json")
            entry = KeyEntry(
                book.id,
                book.group_id,
                book.booking_key,
                book.cw_number,
                book.period,
                book.station_code,
            )
            folder = group_entry(group)
            return True

    async def tick(self):
        if self.engine is None or (self.task is not None and not self.task.done()):
            return
        await self.recover()
        local = self.clock().astimezone(ZoneInfo(self.settings.business_timezone))
        day = local.date().isoformat()
        if (
            local.time().replace(tzinfo=None) < time.fromisoformat(self.settings.integrity_run_time)
            or self.scheduled_day == day
        ):
            return
        midnight = datetime.combine(local.date(), time.min, local.tzinfo).astimezone(UTC)
        async with self.tx() as session:
            previous = await session.scalar(
                select(IntegrityRun.id)
                .where(
                    IntegrityRun.started_at >= midnight,
                    IntegrityRun.details["scheduled_day"].as_string() == day,
                )
                .limit(1)
            )
        if not previous:
            await self.start(scheduled_day=day)
        self.scheduled_day = day

    async def stop(self):
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
