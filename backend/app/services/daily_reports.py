"""Business-day SQL aggregates, provisional evening snapshots and immutable past days."""

import asyncio
import base64
import json
import tempfile
import time
import zlib
from datetime import UTC, datetime, timedelta
from datetime import time as local_time
from zoneinfo import ZoneInfo

from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, BookingNote, BookingTask, DailyReport, Status, User
from app.schemas.contracts import ErrorCode
from app.schemas.operations import DailyBooking, DailyReportDTO
from app.services.audit import record_audit
from app.services.exports import (
    COLUMNS,
    date_text,
    invoice_numbers,
    invoice_numbers_query,
    safe_cell,
)
from app.services.reports import day_bounds
from app.utils.booking_key import to_display
from app.utils.invoice import state_label


def pack_report(payload):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(raw) < 512 * 1024:
        return payload
    packed = zlib.compress(raw)
    if len(raw) > 128 * 1024 * 1024 or len(packed) > 4 * 1024 * 1024:
        raise ApiException(
            ErrorCode.SERVICE_BUSY, message="This report exceeds the storage budget."
        )
    # Keep the JSON column and a readable provisional marker while fitting TiDB's
    # row budget for large stale lists. API consumers still receive normal JSON.
    return {
        "encoding": "zlib-base64-v1",
        "provisional": payload["provisional"],
        "data": base64.b64encode(packed).decode(),
    }


def unpack_report(payload):
    if payload.get("encoding") != "zlib-base64-v1":
        return payload
    decompressor = zlib.decompressobj()
    value = decompressor.decompress(
        base64.b64decode(payload["data"], validate=True), 128 * 1024 * 1024 + 1
    )
    if not decompressor.eof or decompressor.unconsumed_tail or len(value) > 128 * 1024 * 1024:
        raise ApiException(ErrorCode.INTERNAL, message="The stored daily report could not be read.")
    return json.loads(value)


class DailyReports:
    def __init__(self, engine, settings, exports):
        self.engine, self.settings, self.exports = engine, settings, exports
        self.lock = asyncio.Lock()
        self.cache = None
        self.clock = lambda: datetime.now(UTC)

    def tx(self, **kwargs):
        return transaction(self.engine, self.settings, **kwargs)

    async def get(self, day, *, persist_today=False):
        zone = ZoneInfo(self.settings.business_timezone)
        today = self.clock().astimezone(zone).date()
        if day > today:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR, message="Choose today or an earlier date."
            )
        async with self.lock:
            if day < today or persist_today:
                async with self.tx() as session:
                    existing = await session.get(DailyReport, day)
                    if existing and (
                        day == today or not existing.payload.get("provisional", False)
                    ):
                        payload = dict(await asyncio.to_thread(unpack_report, existing.payload))
                        records = payload.pop("_records", [])
                        return DailyReportDTO.model_validate({**payload, "record_rows": records})
            if (
                day == today
                and not persist_today
                and self.cache
                and self.cache[0] == day
                and self.cache[1] > time.monotonic()
            ):
                return self.cache[2].model_copy(deep=True)
            value = await self.calculate(day)
            if day < today or persist_today:
                async with self.tx() as session:
                    payload = await asyncio.to_thread(
                        pack_report,
                        {**value.model_dump(mode="json"), "_records": value.record_rows},
                    )
                    statement = insert(DailyReport).values(
                        report_date=day,
                        payload=payload,
                        generated_at=value.generated_at,
                    )
                    await session.execute(
                        statement.on_duplicate_key_update(
                            payload=statement.inserted.payload,
                            generated_at=statement.inserted.generated_at,
                        )
                    )
            if day == today:
                self.cache = (day, time.monotonic() + 60, value.model_copy(deep=True))
            return value

    async def calculate(self, day):
        now = self.clock()
        zone = ZoneInfo(self.settings.business_timezone)
        lo, hi = day_bounds(day, zone)
        cutoff = min(now, hi)
        day_notes = [
            BookingNote.created_at >= lo,
            BookingNote.created_at < cutoff,
            BookingNote.deleted_at.is_(None),
        ]
        latest = (
            select(BookingNote.booking_id, func.max(BookingNote.id).label("note_id"))
            .where(BookingNote.created_at < cutoff, BookingNote.deleted_at.is_(None))
            .group_by(BookingNote.booking_id)
            .subquery()
        )
        by_book = (
            select(BookingNote.booking_id, func.count().label("note_count"))
            .where(*day_notes)
            .group_by(BookingNote.booking_id)
            .subquery()
        )
        current = (
            select(
                Booking.booking_key,
                Booking.station_code,
                Booking.invoice_state,
                Booking.invoice_count,
                invoice_numbers_query(),
                Booking.created_at,
                BookingGroup.supplier_name,
                BookingGroup.supplier_type,
                BookingNote.created_at.label("last_at"),
                BookingNote.agent_id,
                Status.code,
                Status.label,
                Status.is_done,
                Status.stale_after_hours,
                User.full_name,
                by_book.c.note_count,
            )
            .join(BookingGroup, BookingGroup.id == Booking.group_id)
            .outerjoin(latest, latest.c.booking_id == Booking.id)
            .outerjoin(BookingNote, BookingNote.id == latest.c.note_id)
            .outerjoin(Status, Status.id == BookingNote.status_id)
            .outerjoin(User, User.id == BookingNote.agent_id)
            .outerjoin(by_book, by_book.c.booking_id == Booking.id)
            .where(Booking.created_at < cutoff)
            .order_by(Booking.id)
        )
        async with self.tx(
            seconds=self.settings.export_timeout_seconds, isolation_level="REPEATABLE READ"
        ) as session:
            note_count = await session.scalar(
                select(func.count()).select_from(BookingNote).where(*day_notes)
            )
            new_count = await session.scalar(
                select(func.count())
                .select_from(Booking)
                .where(Booking.created_at >= lo, Booking.created_at < cutoff)
            )
            statuses = (
                (
                    await session.execute(
                        select(Status.code, Status.label, func.count().label("count"))
                        .join(BookingNote, BookingNote.status_id == Status.id)
                        .where(*day_notes)
                        .group_by(Status.id, Status.code, Status.label)
                        .order_by(Status.sort_order, Status.id)
                    )
                )
                .mappings()
                .all()
            )
            agents = (
                (
                    await session.execute(
                        select(User.id, User.full_name, func.count().label("note_count"))
                        .join(BookingNote, BookingNote.agent_id == User.id)
                        .where(*day_notes)
                        .group_by(User.id, User.full_name)
                        .order_by(User.full_name, User.id)
                    )
                )
                .mappings()
                .all()
            )
            stations = (
                (
                    await session.execute(
                        select(
                            Booking.station_code,
                            BookingGroup.supplier_type,
                            func.count().label("note_count"),
                        )
                        .join(BookingNote, BookingNote.booking_id == Booking.id)
                        .join(BookingGroup, BookingGroup.id == Booking.group_id)
                        .where(*day_notes)
                        .group_by(Booking.station_code, BookingGroup.supplier_type)
                        .order_by(Booking.station_code, BookingGroup.supplier_type)
                    )
                )
                .mappings()
                .all()
            )
            tasks = await session.scalar(
                select(func.count())
                .select_from(BookingTask)
                .where(
                    BookingTask.status == "pending",
                    BookingTask.remind_at < cutoff,
                    BookingTask.created_at < cutoff,
                )
            )
            rows = (await session.execute(current)).all()
            record_rows = []
            query = (
                select(
                    BookingNote.created_at,
                    User.full_name,
                    Booking.booking_key,
                    BookingGroup.supplier_name,
                    Booking.station_code,
                    Booking.invoice_state,
                    Booking.invoice_count,
                    invoice_numbers_query(),
                    BookingGroup.supplier_type,
                    Status.label,
                    BookingNote.position_label,
                    BookingNote.note,
                )
                .join(Booking, Booking.id == BookingNote.booking_id)
                .join(BookingGroup, BookingGroup.id == Booking.group_id)
                .join(User, User.id == BookingNote.agent_id)
                .join(Status, Status.id == BookingNote.status_id)
                .where(*day_notes)
                .order_by(BookingNote.created_at, BookingNote.id)
                .execution_options(yield_per=500)
            )
            result = await session.stream(query)
            try:
                async for batch in result.partitions(500):
                    for r in batch:
                        record_rows.append(
                            [
                                date_text(r.created_at, zone),
                                r.full_name,
                                r.booking_key,
                                r.supplier_name,
                                r.station_code,
                                "Hotel" if r.supplier_type == "hotel" else "Transportation",
                                r.label,
                                r.position_label,
                                r.note or "",
                                state_label(r.invoice_state),
                                "; ".join(invoice_numbers(r.invoice_numbers)),
                            ]
                        )
                    await asyncio.sleep(0)
            except (asyncio.CancelledError, TimeoutError, GeneratorExit):
                connection = await session.connection()
                await connection.invalidate()
                raise
            finally:
                await result.close()
        stale, open_rows, repeated, done_not_declared = [], [], [], []
        done_agents, done_stations = {}, {}
        done_count = 0
        for r in rows:
            updated = r.last_at or r.created_at
            if r.is_done and lo <= updated < cutoff:
                done_count += 1
                done_agents[r.agent_id] = done_agents.get(r.agent_id, 0) + 1
                pair = (r.station_code, r.supplier_type)
                done_stations[pair] = done_stations.get(pair, 0) + 1
            dto = DailyBooking(
                invoice_state=r.invoice_state,
                invoice_count=r.invoice_count,
                invoices_preview=invoice_numbers(r.invoice_numbers)[:3],
                booking_key=r.booking_key,
                display_key=to_display(r.booking_key),
                supplier_name=r.supplier_name,
                supplier_type=r.supplier_type,
                station_code=r.station_code,
                status={"code": r.code, "label": r.label} if r.code else None,
                agent={"id": r.agent_id, "full_name": r.full_name} if r.agent_id else None,
                updated_at=updated,
                note_count=r.note_count or 0,
            )
            if (
                not r.is_done
                and (cutoff - updated).total_seconds()
                >= (r.stale_after_hours or self.settings.stale_hours_default) * 3600
            ):
                stale.append(dto)
            if not r.is_done and r.code in {"REJECTION", "PARKING"}:
                open_rows.append(dto)
            if r.is_done and lo <= updated < cutoff and r.invoice_state == "unknown":
                done_not_declared.append(dto)
            if (r.note_count or 0) >= 3:
                repeated.append(dto)
        return DailyReportDTO(
            record_rows=record_rows,
            report_date=day,
            timezone=self.settings.business_timezone,
            generated_at=now,
            cutoff_at=cutoff,
            provisional=day == now.astimezone(zone).date(),
            note_count=note_count,
            new_booking_count=new_count,
            done_count=done_count,
            overdue_task_count=tasks,
            status_distribution=[dict(r) for r in statuses],
            agents=[{**dict(r), "done_count": done_agents.get(r["id"], 0)} for r in agents],
            stations=[
                {
                    **dict(r),
                    "done_count": done_stations.get((r["station_code"], r["supplier_type"]), 0),
                }
                for r in stations
            ],
            stale=stale,
            open_rejection_parking=open_rows,
            repeated=repeated,
            done_not_declared=done_not_declared,
        )

    async def tick(self):
        if self.engine is None:
            return
        local = self.clock().astimezone(ZoneInfo(self.settings.business_timezone))
        # Finalize yesterday even before today's scheduled time; a provisional
        # 18:30 snapshot must not omit notes added later that evening.
        await self.get(local.date() - timedelta(days=1))
        if local.time().replace(tzinfo=None) >= local_time.fromisoformat(
            self.settings.daily_report_time
        ):
            await self.get(local.date(), persist_today=True)

    async def export(self, day, request, actor, context):
        work = asyncio.create_task(self.prepare_export(day, request, actor, context))
        try:
            while not work.done():
                await asyncio.wait({work}, timeout=0.1)
                if not work.done() and await request.is_disconnected():
                    raise asyncio.CancelledError
            return await work
        finally:
            if not work.done():
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)

    async def prepare_export(self, day, request, actor, context):
        report = await self.get(day)
        async with self.tx() as session:
            record_audit(
                session,
                "daily_report_export",
                actor_id=actor.id,
                context=context,
                entity_type="export",
                entity_id=f"daily-report:{day}",
            )
        workbook = Workbook(write_only=True)
        overview = workbook.create_sheet("Overview")
        records = workbook.create_sheet("Daily record")
        stale = workbook.create_sheet("Stale")
        overview.append(["Metric", "Value"])
        for key in (
            "report_date",
            "timezone",
            "generated_at",
            "cutoff_at",
            "note_count",
            "new_booking_count",
            "done_count",
            "overdue_task_count",
        ):
            overview.append([key, safe_cell(str(getattr(report, key)))])
        overview.append([])
        overview.append(["Status code", "Status", "Notes"])
        for row in report.status_distribution:
            overview.append([safe_cell(row.code), safe_cell(row.label), row.count])
        overview.append([])
        overview.append(["Station", "Type", "Notes", "Done"])
        for row in report.stations:
            overview.append(
                [
                    safe_cell(row.station_code),
                    "Hotel" if row.supplier_type == "hotel" else "Transportation",
                    row.note_count,
                    row.done_count,
                ]
            )
        overview.append([])
        overview.append(["Agent", "Notes", "Done"])
        for row in report.agents:
            overview.append([safe_cell(row.full_name), row.note_count, row.done_count])
        records.append(COLUMNS)
        stale.append(["Booking", "Supplier", "Station", "Type", "Status", "Agent", "Updated at"])
        for row in report.stale:
            stale.append(
                [
                    safe_cell(value)
                    for value in (
                        to_display(row.booking_key)
                        if self.settings.export_booking_key_style == "display"
                        else row.booking_key,
                        row.supplier_name,
                        row.station_code,
                        "Hotel" if row.supplier_type == "hotel" else "Transportation",
                        row.status.label if row.status else "",
                        row.agent.full_name if row.agent else "",
                        date_text(row.updated_at, ZoneInfo(report.timezone)),
                    )
                ]
            )
        file = tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b")
        saving = None

        def cleanup(task=None):
            if task is not None and not task.cancelled():
                task.exception()
            file.close()
            workbook.close()
            if saving is None:
                for sheet in workbook:
                    sheet.close()
                    writer = getattr(sheet, "_writer", None)
                    if writer is not None:
                        writer.cleanup()

        try:
            async with asyncio.timeout(self.settings.export_timeout_seconds):
                for index, row in enumerate(report.record_rows):
                    values = list(row)
                    if len(values) == 9:
                        values += ["Not declared", ""]  # Immutable pre-8F report source.
                    if self.settings.export_booking_key_style == "display":
                        values[2] = to_display(values[2])
                    records.append([safe_cell(value) for value in values])
                    if index % 500 == 0:
                        if await request.is_disconnected():
                            raise asyncio.CancelledError
                        await asyncio.sleep(0)
                saving = asyncio.create_task(asyncio.to_thread(workbook.save, file))
                await asyncio.shield(saving)
                file.seek(0)
        except BaseException:
            if saving is not None and not saving.done():
                saving.add_done_callback(cleanup)
            else:
                cleanup()
            raise

        async def chunks():
            try:
                async with asyncio.timeout(self.settings.export_timeout_seconds):
                    while chunk := await asyncio.to_thread(file.read, 65536):
                        yield chunk
            finally:
                cleanup()

        return StreamingResponse(
            chunks(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="daily-report-{day}.xlsx"',
                "Cache-Control": "no-store",
            },
        )
