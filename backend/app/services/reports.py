from collections import OrderedDict
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, BookingNote, BookingTask, Status, User
from app.schemas.admin import PerformanceReport
from app.schemas.contracts import ErrorCode
from app.services.booking_reads import stale_condition


def day_bounds(day, zone):
    start = datetime.combine(day, time(), zone).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(UTC)
    return start, end


def report_range(period, start, end, zone):
    today = datetime.now(zone).date()
    if start is None:
        start = (
            today
            if period == "day"
            else today - timedelta(days=today.weekday())
            if period == "week"
            else today.replace(day=1)
        )
    end = end or today
    if end < start or (end - start).days > 365:
        raise ApiException(
            ErrorCode.VALIDATION_ERROR, message="Choose an ordered date range of at most 366 days."
        )
    return start, end


def agent(identifier, name):
    return {"id": identifier, "full_name": name} if identifier and name else None


class ReportService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self.cache = OrderedDict()
        self.generation = 0

    def invalidate(self):
        self.generation += 1
        self.cache.clear()

    async def performance(self, period, start, end):
        zone = ZoneInfo(self.settings.business_timezone)
        start, end = report_range(period, start, end, zone)
        key = (start, end)
        saved = self.cache.get(key)
        now = datetime.now(UTC)
        if saved and (now - saved.generated_at).total_seconds() < 45:
            self.cache.move_to_end(key)
            return saved.model_copy(deep=True)
        generation = self.generation
        lo = day_bounds(start, zone)[0]
        hi = day_bounds(end, zone)[1]
        notes = [
            BookingNote.deleted_at.is_(None),
            BookingNote.created_at >= lo,
            BookingNote.created_at < hi,
        ]
        # UTC boundaries per local day work without MySQL timezone tables, including
        # DST and offsets not aligned to whole hours. SQL still does the aggregation.
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        buckets = case(
            *[(BookingNote.created_at < day_bounds(day, zone)[1], day.isoformat()) for day in days]
        )
        async with transaction(self.engine, self.settings) as session:
            users = (
                await session.execute(
                    select(User.id, User.full_name, func.count(BookingNote.id).label("n"))
                    .join(BookingNote, BookingNote.agent_id == User.id)
                    .where(*notes)
                    .group_by(User.id, User.full_name)
                )
            ).all()
            done = (
                await session.execute(
                    select(User.id, User.full_name, func.count(Booking.id).label("n"))
                    .join(Booking, Booking.last_agent_id == User.id)
                    .where(Booking.is_done.is_(True), Booking.done_at >= lo, Booking.done_at < hi)
                    .group_by(User.id, User.full_name)
                )
            ).all()
            statuses = (
                await session.execute(
                    select(Status.code, Status.label, func.count(BookingNote.id).label("n"))
                    .join(BookingNote, BookingNote.status_id == Status.id)
                    .where(*notes)
                    .group_by(Status.id, Status.code, Status.label)
                )
            ).all()
            trend = (
                await session.execute(
                    select(buckets.label("day"), func.count().label("n"))
                    .select_from(BookingNote)
                    .where(*notes)
                    .group_by(buckets)
                )
            ).all()
            stale_users = (
                await session.execute(
                    select(User.id, User.full_name, func.count(Booking.id).label("n"))
                    .select_from(Booking)
                    .outerjoin(Status, Status.id == Booking.last_status_id)
                    .outerjoin(User, User.id == Booking.last_agent_id)
                    .where(stale_condition(self.settings))
                    .group_by(User.id, User.full_name)
                )
            ).all()
            stale_status = (
                await session.execute(
                    select(Status.code, Status.label, func.count(Booking.id).label("n"))
                    .select_from(Booking)
                    .outerjoin(Status, Status.id == Booking.last_status_id)
                    .where(stale_condition(self.settings))
                    .group_by(Status.id, Status.code, Status.label)
                )
            ).all()
            tasks = (
                await session.execute(
                    select(User.id, User.full_name, func.count(BookingTask.id).label("n"))
                    .join(BookingTask, BookingTask.user_id == User.id)
                    .where(BookingTask.status == "pending", BookingTask.remind_at < now)
                    .group_by(User.id, User.full_name)
                )
            ).all()
        combined = {
            r.id: {"agent": agent(r.id, r.full_name), "note_count": r.n, "done_count": 0}
            for r in users
        }
        for r in done:
            combined.setdefault(r.id, {"agent": agent(r.id, r.full_name), "note_count": 0})[
                "done_count"
            ] = r.n
        counts = {r.day: r.n for r in trend}
        result = PerformanceReport(
            date_from=start,
            date_to=end,
            timezone=zone.key,
            generated_at=now,
            note_count=sum(r.n for r in users),
            done_count=sum(r.n for r in done),
            users=sorted(combined.values(), key=lambda r: r["agent"]["full_name"]),
            statuses=[
                {"status": {"code": r.code, "label": r.label}, "count": r.n} for r in statuses
            ],
            trend=[{"date": day, "count": counts.get(day.isoformat(), 0)} for day in days],
            stale_by_user=[{"agent": agent(r.id, r.full_name), "count": r.n} for r in stale_users],
            stale_by_status=[
                {"status": {"code": r.code, "label": r.label} if r.code else None, "count": r.n}
                for r in stale_status
            ],
            overdue_tasks_by_user=[
                {"agent": agent(r.id, r.full_name), "count": r.n} for r in tasks
            ],
        )
        if generation == self.generation:
            self.cache[key] = result.model_copy(deep=True)
            while len(self.cache) > 64:
                self.cache.popitem(last=False)
        return result
