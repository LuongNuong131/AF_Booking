"""Generate clean monthly records with durable, per-folder catch-up checkpoints."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select

from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup
from app.schemas.admin import MonthlyBookingResult, MonthlyBookingStatus
from app.services.audit import record_audit
from app.services.booking_writes import group_entry
from app.services.key_index import KeyEntry
from app.utils.booking_key import build_key


def next_period(period: str) -> str:
    year, month = 2000 + int(period[:2]), int(period[2:])
    if not 1 <= month <= 12 or not 2000 <= year <= 2099:
        raise ValueError("Invalid monthly booking period")
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    if year > 2099:
        raise ValueError("Monthly booking periods end in 2099")
    return f"{year % 100:02d}{month:02d}"


def due_period(now: datetime, timezone: str, day: int = 25) -> str:
    local = now.astimezone(ZoneInfo(timezone)).date()
    if local.day < day:
        local = local.replace(day=1) - timedelta(days=1)
    return f"{local.year % 100:02d}{local.month:02d}"


class MonthlyBookings:
    def __init__(self, state):
        self.state = state
        self.settings = state.settings

    async def status(self, now: datetime | None = None) -> MonthlyBookingStatus:
        now = now or datetime.now(UTC)
        local = now.astimezone(ZoneInfo(self.settings.business_timezone))
        day = self.settings.monthly_booking_day
        target = due_period(now, self.settings.business_timezone, day)
        next_day = date(local.year, local.month, day)
        if local.day >= day:
            period = next_period(f"{local.year % 100:02d}{local.month:02d}")
            next_day = date(2000 + int(period[:2]), int(period[2:]), day)
        async with transaction(self.state.engine, self.settings) as session:
            active = await session.scalar(
                select(func.count())
                .select_from(BookingGroup)
                .where(BookingGroup.recurring_enabled.is_(True))
            )
            pending = await session.scalar(
                select(func.count())
                .select_from(BookingGroup)
                .where(
                    BookingGroup.recurring_enabled.is_(True),
                    or_(
                        BookingGroup.recurring_through_period.is_(None),
                        BookingGroup.recurring_through_period < target,
                    ),
                    BookingGroup.id.in_(select(Booking.group_id).where(Booking.period <= target)),
                )
            )
        return MonthlyBookingStatus(
            enabled=self.settings.monthly_booking_enabled,
            day=day,
            timezone=self.settings.business_timezone,
            due_period=target,
            next_run_at=datetime.combine(
                next_day, datetime.min.time(), ZoneInfo(self.settings.business_timezone)
            ),
            active_folders=active or 0,
            pending_folders=pending or 0,
            external_trigger_configured=self.settings.monthly_booking_token is not None,
        )

    async def run(self, now: datetime | None = None) -> MonthlyBookingResult:
        target = due_period(
            now or datetime.now(UTC),
            self.settings.business_timezone,
            self.settings.monthly_booking_day,
        )
        if not self.settings.monthly_booking_enabled:
            return MonthlyBookingResult(
                period=target, created=0, processed_folders=0, enabled=False
            )
        async with transaction(self.state.engine, self.settings) as session:
            ids = list(
                (
                    await session.scalars(
                        select(BookingGroup.id)
                        .where(
                            BookingGroup.recurring_enabled.is_(True),
                            or_(
                                BookingGroup.recurring_through_period.is_(None),
                                BookingGroup.recurring_through_period < target,
                            ),
                            BookingGroup.id.in_(
                                select(Booking.group_id).where(Booking.period <= target)
                            ),
                        )
                        .order_by(BookingGroup.id)
                        .limit(100)
                    )
                ).all()
            )
        count = 0
        processed = 0
        for identifier in ids:
            created = []
            changed = []

            def committed(created=created, changed=changed):
                if changed:
                    for booking in created:
                        self.state.key_index.update(
                            KeyEntry(
                                booking.id,
                                booking.group_id,
                                booking.booking_key,
                                booking.cw_number,
                                booking.period,
                                booking.station_code,
                            ),
                            changed[0],
                        )
                    if created:
                        self.state.invoices.report_cache.clear()

            async with transaction(
                self.state.engine, self.settings, seconds=10, after_commit=committed
            ) as session:
                group = await session.scalar(
                    select(BookingGroup).where(BookingGroup.id == identifier).with_for_update()
                )
                if not group or not group.recurring_enabled:
                    continue
                cursor = group.recurring_through_period
                if cursor is None:
                    cursor = await session.scalar(
                        select(func.max(Booking.period)).where(
                            Booking.group_id == identifier, Booking.period <= target
                        )
                    )
                if not cursor or cursor > target:
                    continue
                periods = []
                while cursor < target and len(periods) < 12:
                    cursor = next_period(cursor)
                    periods.append(cursor)
                existing = (
                    set(
                        (
                            await session.scalars(
                                select(Booking.period).where(
                                    Booking.group_id == identifier, Booking.period.in_(periods)
                                )
                            )
                        ).all()
                    )
                    if periods
                    else set()
                )
                for period in periods:
                    if period in existing:
                        continue
                    booking = Booking(
                        booking_key=build_key(group.cw_number, group.station_code, period),
                        group_id=group.id,
                        cw_number=group.cw_number,
                        station_code=group.station_code,
                        period=period,
                    )
                    session.add(booking)
                    created.append(booking)
                group.recurring_through_period = cursor
                group.booking_count += len(created)
                await session.flush()
                changed.append(group_entry(group))
                if created:
                    record_audit(
                        session,
                        "bookings_monthly_generated",
                        actor_id=None,
                        entity_type="booking_group",
                        entity_id=str(group.id),
                        meta={"through_period": cursor, "created": len(created)},
                    )
            count += len(created)
            processed += 1
        return MonthlyBookingResult(
            period=target, created=count, processed_folders=processed, enabled=True
        )

    async def tick(self):
        await self.run()
