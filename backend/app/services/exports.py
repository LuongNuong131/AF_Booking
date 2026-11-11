import asyncio
import csv
import io
import json
import re
import tempfile
from zoneinfo import ZoneInfo

from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, BookingInvoice, BookingNote, Status, User
from app.services.audit import record_audit
from app.services.report_charts import ActivityCharts, Metric, add_dashboard
from app.services.reports import day_bounds
from app.services.workflow_xlsx import professional_workbook
from app.utils.booking_key import to_display
from app.utils.invoice import state_label

COLUMNS = (
    "Date",
    "Agent",
    "Booking",
    "Supplier",
    "Station",
    "Type",
    "Status",
    "Position",
    "Note",
    "Invoice State",
    "Invoice Numbers",
)


def invoice_numbers_query():
    return (
        select(func.json_arrayagg(BookingInvoice.invoice_number))
        .where(BookingInvoice.booking_id == Booking.id)
        .correlate(Booking)
        .scalar_subquery()
        .label("invoice_numbers")
    )


def invoice_numbers(value):
    if isinstance(value, str):
        value = json.loads(value)
    return sorted(value or [])


def safe_cell(value):
    value = "" if value is None else str(value)
    dangerous = value.startswith(
        ("=", "+", "-", "@", "\t", "\r", "\n")
    ) or value.lstrip().startswith(("=", "+", "-", "@"))
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    return "'" + value if dangerous else value


def date_text(instant, zone):
    local = instant.astimezone(zone)
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{local.day:02} {months[local.month - 1]} {local.year} {local:%H:%M:%S %z} ({zone.key})"


class ExportService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    async def rows(self, day, user_id, status, request):
        zone = ZoneInfo(self.settings.business_timezone)
        lo, hi = day_bounds(day, zone)
        conditions = [
            BookingNote.created_at >= lo,
            BookingNote.created_at < hi,
            BookingNote.deleted_at.is_(None),
        ]
        if user_id:
            conditions.append(BookingNote.agent_id == user_id)
        if status:
            conditions.append(Status.code == status)
        query = (
            select(
                BookingNote.created_at,
                User.full_name,
                Booking.booking_key,
                BookingGroup.supplier_name,
                Booking.station_code,
                func.coalesce(Booking.classification, BookingGroup.supplier_type).label(
                    "supplier_type"
                ),
                Status.label,
                BookingNote.position_label,
                BookingNote.note,
                Booking.invoice_state,
                invoice_numbers_query(),
            )
            .join(Booking, Booking.id == BookingNote.booking_id)
            .join(BookingGroup, BookingGroup.id == Booking.group_id)
            .join(User, User.id == BookingNote.agent_id)
            .join(Status, Status.id == BookingNote.status_id)
            .where(*conditions)
            .order_by(BookingNote.created_at, BookingNote.id)
            .execution_options(yield_per=500)
        )
        async with transaction(
            self.engine, self.settings, seconds=self.settings.export_timeout_seconds
        ) as session:
            result = await session.stream(query)
            try:
                async for batch in result.partitions(500):
                    if await request.is_disconnected():
                        raise asyncio.CancelledError
                    yield [
                        [
                            safe_cell(value)
                            for value in (
                                date_text(r.created_at, zone),
                                r.full_name,
                                to_display(r.booking_key)
                                if self.settings.export_booking_key_style == "display"
                                else r.booking_key,
                                r.supplier_name,
                                r.station_code,
                                {"hotel": "Hotel", "transportation": "Transportation"}.get(
                                    r.supplier_type, "Unclassified"
                                ),
                                r.label,
                                r.position_label,
                                r.note,
                                state_label(r.invoice_state),
                                "; ".join(invoice_numbers(r.invoice_numbers)),
                            )
                        ]
                        for r in batch
                    ]
            except (asyncio.CancelledError, TimeoutError, GeneratorExit):
                # Closing an unbuffered cursor can otherwise drain the remaining
                # query. Drop its connection first when a download is cancelled.
                connection = await session.connection()
                await connection.invalidate()
                raise
            finally:
                await result.close()

    async def daily(self, day, format, user_id, status, request, actor, context):
        async with transaction(self.engine, self.settings) as session:
            record_audit(
                session,
                "daily_export",
                actor_id=actor.id,
                context=context,
                entity_type="export",
                entity_id=f"daily:{day}",
                meta={
                    "date": str(day),
                    "format": format,
                    "agent_id": user_id,
                    "status_code": status,
                },
            )
        headers = {
            "Content-Disposition": f'attachment; filename="daily-record-{day}.{format}"',
            "Cache-Control": "no-store",
        }
        if format == "csv":

            async def stream():
                async with asyncio.timeout(self.settings.export_timeout_seconds):
                    output = io.StringIO(newline="")
                    writer = csv.writer(output)
                    writer.writerow(COLUMNS)
                    yield ("\ufeff" + output.getvalue()).encode()
                    output.seek(0)
                    output.truncate(0)
                    async for batch in self.rows(day, user_id, status, request):
                        writer.writerows(batch)
                        yield output.getvalue().encode()
                        output.seek(0)
                        output.truncate(0)

            return StreamingResponse(
                stream(), media_type="text/csv; charset=utf-8", headers=headers
            )
        workbook = professional_workbook()
        activity = ActivityCharts()
        sheet = workbook.create_sheet("Daily record")
        sheet.append(COLUMNS)
        file = tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b")
        saving = None

        def cleanup(task=None):
            if task is not None and not task.cancelled():
                task.exception()
            file.close()
            workbook.close()
            # write_only worksheets own a temporary XML file until save().
            # A cancelled DB stream never reaches save(), so close and remove it.
            if saving is None:
                for partial_sheet in workbook:
                    partial_sheet.close()
                    writer = getattr(partial_sheet, "_writer", None)
                    if writer is not None:
                        writer.cleanup()

        try:
            async with asyncio.timeout(self.settings.export_timeout_seconds):
                async for batch in self.rows(day, user_id, status, request):
                    for row in batch:
                        sheet.append(row)
                        activity.add(
                            agent=row[1], status=row[6], station=row[4], classification=row[5]
                        )
                    await asyncio.sleep(0)
                add_dashboard(
                    workbook,
                    title="AF BOOKING | DAILY UPDATE INSIGHTS",
                    subtitle=(
                        f"{day} · {self.settings.business_timezone} · "
                        f"Agent: {user_id or 'All'} · Status: {status or 'All'}"
                    ),
                    metrics=[
                        Metric("Updates exported", activity.updates),
                        Metric("Agents represented", len(activity.agents)),
                        Metric("Stations represented", len(activity.stations)),
                    ],
                    charts=activity.specs(),
                    note=(
                        "Each detail row is an update. Multiple updates to the same "
                        "booking are counted separately. All applied export filters "
                        "are retained."
                    ),
                )
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
                file.close()
                workbook.close()

        return StreamingResponse(
            chunks(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )
