"""Agent-scoped daily work: one booking counts once, irrespective of note count."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, BookingNote, Status
from app.schemas.contracts import ErrorCode
from app.schemas.workflow import PersonalBookingRow, PersonalDailyReport
from app.services.audit import record_audit
from app.services.exports import date_text, safe_cell
from app.services.reports import day_bounds
from app.services.workflow_xlsx import WorkflowWorkbook
from app.utils.booking_key import to_display


class PersonalReports:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings

    def query(self, day, user_id):
        zone = ZoneInfo(self.settings.business_timezone)
        if day > datetime.now(zone).date():
            raise ApiException(
                ErrorCode.VALIDATION_ERROR, message="Choose today or an earlier date."
            )
        lo, hi = day_bounds(day, zone)
        latest = (
            select(
                BookingNote.booking_id,
                func.max(BookingNote.id).label("note_id"),
                func.count().label("note_count"),
            )
            .where(
                BookingNote.agent_id == user_id,
                BookingNote.created_at >= lo,
                BookingNote.created_at < hi,
                BookingNote.deleted_at.is_(None),
            )
            .group_by(BookingNote.booking_id)
            .subquery()
        )
        return (
            select(
                Booking.booking_key,
                Booking.station_code,
                BookingGroup.supplier_name,
                latest.c.note_count,
                BookingNote.note,
                BookingNote.created_at,
                Status.code,
                Status.label,
                Status.is_done,
            )
            .select_from(latest)
            .join(Booking, Booking.id == latest.c.booking_id)
            .join(BookingGroup, BookingGroup.id == Booking.group_id)
            .join(BookingNote, BookingNote.id == latest.c.note_id)
            .join(Status, Status.id == BookingNote.status_id)
        )

    async def get(self, day, user, page=1, size=20):
        query = self.query(day, user.id)
        summary = query.subquery()
        async with transaction(self.engine, self.settings) as session:
            count, notes, done = (
                await session.execute(
                    select(
                        func.count(),
                        func.coalesce(func.sum(summary.c.note_count), 0),
                        func.coalesce(func.sum(summary.c.is_done), 0),
                    ).select_from(summary)
                )
            ).one()
            rows = (
                await session.execute(
                    query.order_by(BookingNote.created_at.desc(), Booking.id.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
        return PersonalDailyReport(
            report_date=day,
            timezone=self.settings.business_timezone,
            agent={"id": user.id, "full_name": user.full_name},
            booking_count=count,
            note_count=notes,
            done_count=done,
            total=count,
            page=page,
            size=size,
            items=[
                PersonalBookingRow(
                    booking_key=r.booking_key,
                    display_key=to_display(r.booking_key),
                    supplier_name=r.supplier_name,
                    station_code=r.station_code,
                    note_count=r.note_count,
                    last_status={"code": r.code, "label": r.label},
                    last_note=r.note,
                    updated_at=r.created_at,
                    is_done=r.is_done,
                )
                for r in rows
            ],
        )

    async def export(self, day, user, context):
        report = await self.get(day, user)
        with WorkflowWorkbook() as document:
            workbook = document.workbook
            overview = workbook.create_sheet("Overview")
            overview.append(["Date", str(day)])
            overview.append(["Timezone", report.timezone])
            overview.append(["Agent", safe_cell(user.full_name)])
            overview.append(["Distinct bookings worked", report.booking_count])
            overview.append(["Updates written", report.note_count])
            overview.append(["Done in my final update", report.done_count])
            sheet = workbook.create_sheet("Bookings")
            sheet.append(
                [
                    "Booking",
                    "Supplier",
                    "Station",
                    "Updates",
                    "My final status",
                    "My final note",
                    "Updated at",
                ]
            )
            async with transaction(
                self.engine, self.settings, seconds=self.settings.export_timeout_seconds
            ) as session:
                result = await session.stream(
                    self.query(day, user.id)
                    .order_by(BookingNote.created_at, Booking.id)
                    .execution_options(yield_per=200)
                )
                try:
                    async for r in result:
                        sheet.append(
                            [
                                safe_cell(v)
                                for v in (
                                    to_display(r.booking_key),
                                    r.supplier_name,
                                    r.station_code,
                                    r.note_count,
                                    r.label,
                                    r.note,
                                    date_text(r.created_at, ZoneInfo(report.timezone)),
                                )
                            ]
                        )
                        await asyncio.sleep(0)
                finally:
                    await result.close()
                record_audit(
                    session,
                    "personal_daily_export",
                    actor_id=user.id,
                    context=context,
                    entity_type="export",
                    entity_id=str(day),
                    meta={"agent_id": user.id},
                )
            return await document.response(f"my-daily-report-{day}.xlsx")
