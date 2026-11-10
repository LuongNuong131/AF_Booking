"""A single filtered, role-scoped source for report pages and professional exports."""

import asyncio
import csv
import io
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import aliased

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, BookingInvoice, BookingNote, Status, User
from app.schemas.contracts import ErrorCode
from app.schemas.report_center import ReportCenter, ReportRecord
from app.services.audit import record_audit
from app.services.exports import safe_cell
from app.services.reports import day_bounds
from app.utils.booking_key import to_display


def excel_value(value):
    return value if isinstance(value, (int, float, bool)) else safe_cell(value)


TYPE_LABELS = {"hotel": "Hotel", "transportation": "Transportation", "unclassified": "Unclassified"}
COLUMNS = [
    "Booking",
    "Supplier",
    "Classification",
    "Station",
    "Booking period",
    "Final agent",
    "Final status in range",
    "Position",
    "Updates in range",
    "Final note in range",
    "Updated at",
    "Invoice declaration",
    "Invoice count",
    "Invoice numbers",
]


class ReportCenterService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def scoped(self, filters, user):
        if filters.date_to < filters.date_from or (filters.date_to - filters.date_from).days > 365:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR, message="Select a date range of at most 366 days."
            )
        if filters.scope == "team" and user.role not in {"admin", "qc"}:
            raise ApiException(ErrorCode.FORBIDDEN)
        if filters.scope == "mine":
            if filters.agent_id is not None and filters.agent_id != user.id:
                raise ApiException(ErrorCode.FORBIDDEN)
            filters = filters.model_copy(update={"agent_id": user.id})
        return filters

    def query(self, filters):
        zone = ZoneInfo(self.settings.business_timezone)
        lo, hi = day_bounds(filters.date_from, zone)[0], day_bounds(filters.date_to, zone)[1]
        where = [
            BookingNote.deleted_at.is_(None),
            BookingNote.created_at >= lo,
            BookingNote.created_at < hi,
        ]
        if filters.agent_id:
            where.append(BookingNote.agent_id == filters.agent_id)
        latest = (
            select(
                BookingNote.booking_id,
                func.max(BookingNote.id).label("note_id"),
                func.count().label("note_count"),
            )
            .where(*where)
            .group_by(BookingNote.booking_id)
            .subquery()
        )
        classification = func.coalesce(Booking.classification, BookingGroup.supplier_type)
        query = (
            select(
                Booking.id.label("booking_id"),
                Booking.booking_key,
                Booking.station_code.label("station"),
                Booking.period,
                BookingGroup.supplier_name,
                classification.label("supplier_type"),
                User.id.label("agent_id"),
                User.full_name.label("agent_name"),
                Status.code.label("status_code"),
                Status.label.label("status_label"),
                Status.is_done,
                BookingNote.position_label.label("position"),
                BookingNote.note,
                BookingNote.created_at.label("updated_at"),
                latest.c.note_count,
                Booking.invoice_state,
                Booking.invoice_count,
            )
            .join(latest, latest.c.booking_id == Booking.id)
            .join(BookingGroup, BookingGroup.id == Booking.group_id)
            .join(BookingNote, BookingNote.id == latest.c.note_id)
            .join(User, User.id == BookingNote.agent_id)
            .join(Status, Status.id == BookingNote.status_id)
        )
        for value, column in [
            (filters.station, Booking.station_code),
            (filters.supplier_type, classification),
            (filters.status_code, Status.code),
            (filters.invoice_state, Booking.invoice_state),
        ]:
            if value is not None:
                query = query.where(column == value)
        return query

    async def get(self, filters, user, page=1, size=20, export=False):
        filters = self.scoped(filters, user)
        query = self.query(filters)
        # Group operations stay in SQL; only the visible detail page is hydrated.
        data = query.subquery("report_records")
        async with transaction(
            self.engine,
            self.settings,
            seconds=self.settings.export_timeout_seconds,
            isolation_level="REPEATABLE READ",
        ) as session:
            totals = (
                await session.execute(
                    select(
                        func.count().label("bookings"),
                        func.coalesce(func.sum(data.c.note_count), 0).label("updates"),
                        func.coalesce(func.sum(data.c.is_done), 0).label("done"),
                        func.coalesce(
                            func.sum(case((data.c.supplier_type == "unclassified", 1), else_=0)), 0
                        ).label("unclassified"),
                        func.coalesce(
                            func.sum(case((data.c.invoice_state == "unknown", 1), else_=0)), 0
                        ).label("undeclared"),
                    ).select_from(data)
                )
            ).one()
            if export and totals.bookings > 50000:
                raise ApiException(
                    ErrorCode.VALIDATION_ERROR,
                    message="Narrow the range to at most 50,000 bookings before exporting.",
                )
            groups = {}
            for name, key, label in [
                ("agents", data.c.agent_id, data.c.agent_name),
                ("statuses", data.c.status_code, data.c.status_label),
                ("stations", data.c.station, data.c.station),
                ("classifications", data.c.supplier_type, data.c.supplier_type),
            ]:
                rows = (
                    await session.execute(
                        select(
                            key.label("key"),
                            label.label("label"),
                            func.count().label("bookings"),
                            func.sum(data.c.note_count).label("updates"),
                            func.sum(data.c.is_done).label("done"),
                        )
                        .group_by(key, label)
                        .order_by(func.count().desc(), key)
                    )
                ).all()
                groups[name] = [
                    dict(
                        key=str(r.key),
                        label=TYPE_LABELS.get(str(r.label), str(r.label)),
                        bookings=r.bookings,
                        updates=int(r.updates),
                        done=int(r.done),
                    )
                    for r in rows
                ]
            days = [
                filters.date_from + timedelta(days=i)
                for i in range((filters.date_to - filters.date_from).days + 1)
            ]
            lo = day_bounds(filters.date_from, ZoneInfo(self.settings.business_timezone))[0]
            hi = day_bounds(filters.date_to, ZoneInfo(self.settings.business_timezone))[1]
            event_conditions = [
                BookingNote.deleted_at.is_(None),
                BookingNote.created_at >= lo,
                BookingNote.created_at < hi,
            ]
            if filters.agent_id:
                event_conditions.append(BookingNote.agent_id == filters.agent_id)
            participation = (
                await session.execute(
                    select(
                        User.id.label("key"),
                        User.full_name.label("label"),
                        func.count(func.distinct(BookingNote.booking_id)).label("bookings"),
                        func.count(BookingNote.id).label("updates"),
                        func.count(
                            func.distinct(
                                case(
                                    (
                                        and_(data.c.agent_id == User.id, data.c.is_done.is_(True)),
                                        BookingNote.booking_id,
                                    ),
                                    else_=None,
                                )
                            )
                        ).label("done"),
                    )
                    .join(BookingNote, BookingNote.agent_id == User.id)
                    .join(data, data.c.booking_id == BookingNote.booking_id)
                    .where(*event_conditions)
                    .group_by(User.id, User.full_name)
                    .order_by(func.count(BookingNote.id).desc(), User.id)
                )
            ).all()
            groups["agents"] = [
                dict(
                    key=str(r.key),
                    label=r.label,
                    bookings=r.bookings,
                    updates=r.updates,
                    done=r.done,
                )
                for r in participation
            ]
            bucket = case(
                *[
                    (
                        BookingNote.created_at
                        < day_bounds(day, ZoneInfo(self.settings.business_timezone))[1],
                        day.isoformat(),
                    )
                    for day in days
                ]
            )
            daily = (
                select(
                    bucket.label("day"),
                    BookingNote.booking_id,
                    func.max(BookingNote.id).label("last_id"),
                    func.count(BookingNote.id).label("updates"),
                )
                .join(data, data.c.booking_id == BookingNote.booking_id)
                .where(*event_conditions)
                .group_by(bucket, BookingNote.booking_id)
                .subquery("daily_activity")
            )
            final_note = aliased(BookingNote)
            trend = (
                await session.execute(
                    select(
                        daily.c.day,
                        func.count().label("bookings"),
                        func.sum(daily.c.updates).label("updates"),
                        func.sum(Status.is_done).label("done"),
                    )
                    .join(final_note, final_note.id == daily.c.last_id)
                    .join(Status, Status.id == final_note.status_id)
                    .group_by(daily.c.day)
                )
            ).all()
            trend_map = {r.day: r for r in trend}
            groups["trend"] = [
                dict(
                    key=str(day),
                    label=str(day),
                    bookings=trend_map[str(day)].bookings if str(day) in trend_map else 0,
                    updates=int(trend_map[str(day)].updates) if str(day) in trend_map else 0,
                    done=int(trend_map[str(day)].done) if str(day) in trend_map else 0,
                )
                for day in days
            ]
            rows = (
                await session.execute(
                    query.order_by(BookingNote.created_at.desc(), Booking.id.desc())
                    .offset(0 if export else (page - 1) * size)
                    .limit(50000 if export else size)
                )
            ).all()
            invoices = {}
            for chunk in range(0, len(rows), 500):
                ids = [r.booking_id for r in rows[chunk : chunk + 500]]
                for invoice in (
                    await session.execute(
                        select(BookingInvoice.booking_id, BookingInvoice.invoice_number)
                        .where(BookingInvoice.booking_id.in_(ids))
                        .order_by(BookingInvoice.invoice_number)
                    )
                ).all():
                    invoices.setdefault(invoice.booking_id, []).append(invoice.invoice_number)
        return ReportCenter(
            filters=filters,
            generated_at=datetime.now(UTC),
            timezone=self.settings.business_timezone,
            requested_by=user.full_name,
            bookings=totals.bookings,
            updates=int(totals.updates),
            done=int(totals.done),
            unclassified=int(totals.unclassified),
            undeclared_invoices=int(totals.undeclared),
            total=totals.bookings,
            page=page,
            size=size,
            **groups,
            items=[
                ReportRecord(
                    booking_key=r.booking_key,
                    display_key=to_display(r.booking_key),
                    supplier_name=r.supplier_name,
                    supplier_type=r.supplier_type,
                    station=r.station,
                    period=r.period,
                    agent={"id": r.agent_id, "full_name": r.agent_name},
                    status_code=r.status_code,
                    status_label=r.status_label,
                    position=r.position,
                    note=r.note,
                    updated_at=r.updated_at,
                    note_count=r.note_count,
                    is_done=bool(r.is_done),
                    invoice_state=r.invoice_state,
                    invoice_count=r.invoice_count,
                    invoices=invoices.get(r.booking_id, []),
                )
                for r in rows
            ],
        )

    def detail_rows(self, report):
        zone = ZoneInfo(report.timezone)
        for r in report.items:
            yield [
                r.display_key,
                r.supplier_name,
                TYPE_LABELS.get(r.supplier_type, r.supplier_type),
                r.station,
                r.period,
                r.agent.full_name,
                r.status_label,
                r.position,
                r.note_count,
                r.note or "",
                r.updated_at.astimezone(zone).strftime("%d %b %Y %H:%M:%S"),
                r.invoice_state.replace("_", " ").title(),
                r.invoice_count,
                ", ".join(r.invoices),
            ]

    async def export(self, filters, user, context, format="xlsx"):
        report = await self.get(filters, user, export=True)
        if format == "csv":
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow(COLUMNS)
            for row in self.detail_rows(report):
                writer.writerow([safe_cell(v) for v in row])
            content = ("\ufeff" + output.getvalue()).encode("utf-8")
            media = "text/csv; charset=utf-8"
        else:
            content = await asyncio.to_thread(self.workbook, report)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        async with transaction(self.engine, self.settings) as session:
            record_audit(
                session,
                "report_center_export",
                actor_id=user.id,
                entity_type="export",
                context=context,
                meta={
                    "filters": report.filters.model_dump(mode="json"),
                    "bookings": report.bookings,
                    "format": format,
                },
            )
        name = f"af-booking-{report.filters.scope}-{filters.date_from}-{filters.date_to}.{format}"
        return Response(
            content,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "no-store",
            },
        )

    def workbook(self, report):
        wb = Workbook()
        overview = wb.active
        overview.title = "Executive summary"
        navy, muted = "172F49", "526579"
        overview.merge_cells("A1:F2")
        overview["A1"] = "AF BOOKING | OPERATIONS REPORT"
        overview["A1"].font = Font(name="Aptos Display", size=20, bold=True, color=navy)
        overview.merge_cells("A3:F3")
        overview["A3"] = (
            f"{report.filters.date_from:%d %b %Y} — "
            f"{report.filters.date_to:%d %b %Y} · {report.timezone}"
        )
        overview.append([])
        for label, value in [
            ("Scope", report.filters.scope.title()),
            ("Prepared for", report.requested_by),
            (
                "Generated",
                report.generated_at.astimezone(ZoneInfo(report.timezone)).strftime(
                    "%d %b %Y %H:%M:%S"
                ),
            ),
            ("Distinct bookings worked", report.bookings),
            ("Updates written", report.updates),
            ("Done in final update", report.done),
            ("Completion rate", report.done / report.bookings if report.bookings else 0),
            ("Unclassified bookings", report.unclassified),
            ("Invoice declaration missing", report.undeclared_invoices),
        ]:
            overview.append([label, excel_value(value)])
        for row in overview.iter_rows(min_row=5, max_row=13):
            row[0].font = Font(name="Aptos", bold=True, color=muted)
            row[1].font = Font(name="Aptos", size=12, color=navy)
            overview.row_dimensions[row[0].row].height = 25
        overview["B11"].number_format = "0.0%"
        line = 16
        overview.cell(line, 1, "Applied filters").font = Font(bold=True, color=navy, size=13)
        for name, value in report.filters.model_dump(mode="json").items():
            line += 1
            overview.cell(line, 1, name.replace("_", " ").title())
            overview.cell(line, 2, safe_cell(value if value is not None else "All"))
        line += 3
        for note in [
            "Counting rules",
            "Each booking appears once, using the final matching agent update "
            "within the selected period.",
            "Update counts include all undeleted updates for each included booking "
            "in that scope and date range.",
            "Agent participation counts work by every agent; the same booking may appear "
            "under several agents. Completed counts follow the final agent in the range.",
            "Daily trend counts updates on their actual save dates, with the final status "
            "for each booking on that day.",
            "Invoice declarations and classification reflect the current booking metadata "
            "at generation time.",
            "Historical notes remain attributable after a user or status "
            "is moved to the recycle bin.",
        ]:
            overview.merge_cells(start_row=line, start_column=1, end_row=line, end_column=6)
            cell = overview.cell(line, 1, note)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.font = Font(name="Aptos", size=10, color=muted)
            overview.row_dimensions[line].height = 30
            line += 1
        details = wb.create_sheet("Booking detail")
        self.table(
            details,
            COLUMNS,
            list(self.detail_rows(report)),
            "BookingDetail",
            [29, 38, 22, 13, 16, 25, 25, 22, 18, 75, 27, 24, 16, 42],
        )
        for key, title in [
            ("agents", "Agent performance"),
            ("statuses", "Status distribution"),
            ("stations", "Station breakdown"),
            ("classifications", "Supplier classification"),
            ("trend", "Daily trend"),
        ]:
            sheet = wb.create_sheet(title)
            self.table(
                sheet,
                ["Category", "Bookings", "Updates", "Done", "Completion rate"],
                [
                    [
                        r.label,
                        r.bookings,
                        r.updates,
                        r.done,
                        r.done / r.bookings if r.bookings else 0,
                    ]
                    for r in getattr(report, key)
                ],
                key.title(),
                [35, 18, 18, 18, 23],
            )
            for cell in sheet["E"][1:]:
                cell.number_format = "0.0%"
        for sheet in wb:
            sheet.sheet_view.showGridLines = False
            sheet.sheet_properties.pageSetUpPr.fitToPage = True
            sheet.page_setup.orientation = "landscape"
            sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
            sheet.page_setup.fitToWidth = 1
            sheet.page_setup.fitToHeight = 0
            sheet.oddFooter.center.text = "AF Booking · &A · Page &P of &N"
            sheet.oddFooter.right.text = report.generated_at.strftime("%d %b %Y")
            sheet.sheet_properties.outlinePr.summaryRight = False
        overview.column_dimensions["A"].width = 34
        overview.column_dimensions["B"].width = 30
        for col in "CDEF":
            overview.column_dimensions[col].width = 15
        wb.properties.creator = "AF Booking"
        wb.properties.title = "Booking Operations Report"
        wb.properties.subject = f"{report.filters.date_from} — {report.filters.date_to}"
        output = io.BytesIO()
        try:
            wb.save(output)
            return output.getvalue()
        finally:
            wb.close()
            output.close()

    @staticmethod
    def table(sheet, headers, rows, name, widths):
        from openpyxl.utils import get_column_letter

        sheet.append(headers)
        for row in rows:
            sheet.append([excel_value(v) for v in row])
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="172F49")
            cell.font = Font(name="Aptos", color="FFFFFF", bold=True, size=11)
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[1].height = 32
        for index, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name="Aptos", size=10, color="25384B")
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                cell.border = Border(bottom=Side(style="hair", color="DDE6EE"))
            sheet.row_dimensions[row[0].row].height = 36 if len(headers) > 8 else 23
        if rows:
            table = Table(
                displayName=name, ref=f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
            )
            table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            sheet.add_table(table)
        sheet.freeze_panes = "B2"
        sheet.print_title_rows = "1:1"
        sheet.auto_filter.ref = sheet.dimensions
        sheet.print_options.horizontalCentered = True
