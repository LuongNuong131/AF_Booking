"""Bounded, formula-safe, cancellation-aware invoice reconciliation downloads."""

import asyncio
import csv
import io
import tempfile
from zoneinfo import ZoneInfo

from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, BookingInvoice, Status, User
from app.services.audit import record_audit
from app.services.exports import date_text, safe_cell
from app.services.workflow_xlsx import professional_workbook
from app.utils.booking_key import period_label, to_display
from app.utils.invoice import state_label

INVOICE_COLUMNS = (
    "Period",
    "Booking",
    "Supplier",
    "Station",
    "Type",
    "Status",
    "Agent",
    "Invoice State",
    "Invoice Number",
    "Added By",
    "Added At",
)
BOOKING_COLUMNS = (
    "Period",
    "Booking",
    "Supplier",
    "Station",
    "Type",
    "Status",
    "Agent",
    "Invoice State",
    "Invoice Count",
    "Invoice Numbers",
)


async def rows(engine, settings, period, request):
    author = aliased(User)
    query = (
        select(
            Booking,
            BookingGroup,
            Status.label,
            User.full_name,
            BookingInvoice,
            author.full_name.label("added_name"),
        )
        .join(BookingGroup, BookingGroup.id == Booking.group_id)
        .outerjoin(Status, Status.id == Booking.last_status_id)
        .outerjoin(User, User.id == Booking.last_agent_id)
        .outerjoin(BookingInvoice, BookingInvoice.booking_id == Booking.id)
        .outerjoin(author, author.id == BookingInvoice.added_by)
        .where(Booking.period == period)
        .order_by(Booking.id, BookingInvoice.id)
        .execution_options(yield_per=500)
    )
    async with transaction(
        engine, settings, seconds=settings.export_timeout_seconds, isolation_level="REPEATABLE READ"
    ) as session:
        stream = await session.stream(query)
        try:
            async for batch in stream.partitions(500):
                if await request.is_disconnected():
                    raise asyncio.CancelledError
                for book, folder, status, agent, invoice, added in batch:
                    base = [
                        period_label(period),
                        to_display(book.booking_key)
                        if settings.export_booking_key_style == "display"
                        else book.booking_key,
                        folder.supplier_name,
                        book.station_code,
                        {"hotel": "Hotel", "transportation": "Transportation"}.get(
                            book.classification or folder.supplier_type, "Unclassified"
                        ),
                        status or "",
                        agent or "",
                        state_label(book.invoice_state),
                    ]
                    yield (
                        book.id,
                        base,
                        [
                            invoice.invoice_number,
                            added or "",
                            date_text(invoice.created_at, ZoneInfo(settings.business_timezone)),
                        ]
                        if invoice
                        else ["", "", ""],
                        book.invoice_count,
                    )
                await asyncio.sleep(0)
        except (asyncio.CancelledError, TimeoutError, GeneratorExit):
            connection = await session.connection()
            await connection.invalidate()
            raise
        finally:
            await stream.close()


async def export_invoices(engine, settings, period, format, request, actor, context):
    async with transaction(engine, settings) as session:
        record_audit(
            session,
            "invoice_export",
            actor_id=actor.id,
            entity_type="export",
            entity_id=period,
            context=context,
            meta={"format": format},
        )
    headers = {
        "Content-Disposition": f'attachment; filename="invoices-{period}.{format}"',
        "Cache-Control": "no-store",
    }
    if format == "csv":

        async def chunks():
            async with asyncio.timeout(settings.export_timeout_seconds):
                buffer = io.StringIO(newline="")
                writer = csv.writer(buffer)
                writer.writerow(INVOICE_COLUMNS)
                yield ("\ufeff" + buffer.getvalue()).encode()
                buffer.seek(0)
                buffer.truncate(0)
                async for _, base, invoice, _ in rows(engine, settings, period, request):
                    writer.writerow([safe_cell(v) for v in base + invoice])
                    yield buffer.getvalue().encode()
                    buffer.seek(0)
                    buffer.truncate(0)

        return StreamingResponse(chunks(), media_type="text/csv; charset=utf-8", headers=headers)

    async def prepare():
        workbook = professional_workbook()
        invoices = workbook.create_sheet("Invoices")
        bookings = workbook.create_sheet("Bookings")
        invoices.append(INVOICE_COLUMNS)
        bookings.append(BOOKING_COLUMNS)
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
                    if writer:
                        writer.cleanup()

        try:
            async with asyncio.timeout(settings.export_timeout_seconds):
                previous = None
                base_row = None
                values = []
                count = 0
                async for identifier, base, invoice, invoice_count in rows(
                    engine, settings, period, request
                ):
                    if previous is not None and previous != identifier:
                        bookings.append(
                            [safe_cell(v) for v in base_row + [count, "; ".join(values)]]
                        )
                        values = []
                    previous = identifier
                    base_row = base
                    count = invoice_count
                    invoices.append([safe_cell(v) for v in base + invoice])
                    if invoice[0]:
                        values.append(invoice[0])
                if previous is not None:
                    bookings.append([safe_cell(v) for v in base_row + [count, "; ".join(values)]])
                saving = asyncio.create_task(asyncio.to_thread(workbook.save, file))
                await asyncio.shield(saving)
                file.seek(0)
        except BaseException:
            if saving and not saving.done():
                saving.add_done_callback(cleanup)
            else:
                cleanup()
            raise

        async def chunks():
            try:
                async with asyncio.timeout(settings.export_timeout_seconds):
                    while chunk := await asyncio.to_thread(file.read, 65536):
                        yield chunk
            finally:
                cleanup()

        return StreamingResponse(
            chunks(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )

    work = asyncio.create_task(prepare())
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
