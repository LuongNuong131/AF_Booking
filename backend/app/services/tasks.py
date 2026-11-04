import hashlib
import json
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.errors import ApiException
from app.core.unit_of_work import error_number, transaction
from app.models import Booking, BookingTask, Notification, Status, User
from app.schemas.contracts import ErrorCode, Page, Task
from app.schemas.realtime import NotificationNewData, TaskDueData
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.utils.booking_key import ParsedKey, parse, to_display


def now_utc():
    value = datetime.now(UTC)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def effective_settings(settings, business_timezone):
    values = {
        "timezone": business_timezone,
        "default_remind_time": "09:00",
        "auto_watch_on_note": False,
        "web_push_enabled": False,
        "task_sound": False,
        "web_notifications": False,
        "skip_weekends": True,
        **(settings or {}),
    }
    try:
        ZoneInfo(values["timezone"])
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        values["timezone"] = business_timezone
    return values


def remind_instant(day, clock, preferences, now):
    zone = ZoneInfo(preferences["timezone"])
    today = now.astimezone(zone).date()
    if not today <= day <= today + timedelta(days=90):
        raise ApiException(
            ErrorCode.VALIDATION_ERROR, message="Choose a date from today through 90 days ahead."
        )
    if clock is None:
        try:
            clock = time.fromisoformat(preferences.get("default_remind_time", "09:00"))
            if clock.tzinfo or clock.second or clock.microsecond:
                raise ValueError
        except (ValueError, TypeError):
            clock = time(9)
    local = datetime.combine(day, clock)
    instant = local.replace(tzinfo=zone, fold=0).astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) != local:
        raise ApiException(
            ErrorCode.VALIDATION_ERROR,
            message="This time does not exist because the clock changes. Choose another time.",
        )
    if instant <= now:
        raise ApiException(
            ErrorCode.VALIDATION_ERROR, message="Choose a reminder time in the future."
        )
    return instant


def task_query():
    return (
        select(
            BookingTask,
            Booking.booking_key,
            Booking.updated_at.label("booking_updated"),
            Booking.is_done,
            User.id.label("agent_id"),
            User.full_name,
            Status.code,
            Status.label,
        )
        .join(Booking, Booking.id == BookingTask.booking_id)
        .outerjoin(User, User.id == Booking.last_agent_id)
        .outerjoin(Status, Status.id == Booking.last_status_id)
    )


def task_dto(row, now):
    task = row.BookingTask
    return Task(
        id=task.id,
        booking_key=row.booking_key,
        display_key=to_display(row.booking_key),
        message=task.message,
        remind_at=task.remind_at,
        status=task.status,
        is_due=task.status == "pending" and task.remind_at <= now,
        is_overdue=task.status == "pending" and task.remind_at < now,
        snooze_count=task.snooze_count,
        created_at=task.created_at,
        completed_at=task.completed_at,
        booking_changed_since=row.booking_updated > task.created_at,
        booking={
            "last_status": {"code": row.code, "label": row.label} if row.code else None,
            "last_agent": {"id": row.agent_id, "full_name": row.full_name}
            if row.agent_id
            else None,
            "is_done": row.is_done,
            "updated_at": row.booking_updated,
        },
    )


class TaskService:
    def __init__(self, engine, settings, auth, ws_manager):
        self.engine, self.settings, self.auth, self.ws = engine, settings, auth, ws_manager

    def tx(self, **kwargs):
        return transaction(self.engine, self.settings, **kwargs)

    async def listing(self, user_id, view="pending", page=1, size=10, key=None):
        conditions = [
            BookingTask.user_id == user_id,
            BookingTask.status == ("done" if view == "done" else "pending"),
        ]
        now = datetime.now(UTC)
        if view == "due":
            conditions.append(BookingTask.remind_at <= now)
        if key:
            conditions.append(Booking.booking_key == key)
        query = task_query().where(*conditions)
        async with self.tx() as session:
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            ordering = (
                (BookingTask.completed_at.desc(), BookingTask.id.desc())
                if view == "done"
                else (BookingTask.remind_at, BookingTask.id)
            )
            rows = (
                await session.execute(
                    query.order_by(*ordering).offset((page - 1) * size).limit(size)
                )
            ).all()
        return Page(items=[task_dto(row, now) for row in rows], total=total, page=page, size=size)

    async def create(self, key, body, user, context):
        try:
            return await self._create(key, body, user, context)
        except IntegrityError as error:
            # Different accounts can race on the globally unique request UUID.
            # Same-account requests are serialized by the user row lock below.
            if error_number(error) == 1062:
                raise ApiException(
                    ErrorCode.VALIDATION_ERROR,
                    message="This request ID belongs to a different task.",
                ) from None
            raise

    async def _create(self, key, body, user, context):
        parsed = parse(key, self.settings.station_code_pattern)
        if not isinstance(parsed, ParsedKey) or parsed.key != key:
            raise ApiException(ErrorCode.INVALID_BOOKING_KEY)
        fingerprint = hashlib.sha256(
            json.dumps(
                [key, body.model_dump(mode="json", exclude={"client_request_id"})], sort_keys=True
            ).encode()
        ).hexdigest()
        async with self.tx() as session:
            live = AuthService.require_live_row(
                await session.scalar(select(User).where(User.id == user.id).with_for_update()), user
            )
            if body.client_request_id:
                prior = await session.scalar(
                    select(BookingTask).where(
                        BookingTask.client_request_id == str(body.client_request_id)
                    )
                )
                if prior:
                    if (
                        prior.user_id != user.id
                        or prior.request_fingerprint != fingerprint
                        or prior.create_result is None
                    ):
                        raise ApiException(
                            ErrorCode.VALIDATION_ERROR,
                            message="This request ID belongs to a different task.",
                        )
                    return Task.model_validate(prior.create_result)
            booking = await session.scalar(
                select(Booking).where(Booking.booking_key == key).with_for_update()
            )
            if booking is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            count = await session.scalar(
                select(func.count())
                .select_from(BookingTask)
                .where(
                    BookingTask.booking_id == booking.id,
                    BookingTask.user_id == user.id,
                    BookingTask.status == "pending",
                )
            )
            if count >= 5:
                raise ApiException(
                    ErrorCode.TASK_LIMIT_REACHED,
                    message="You can have up to 5 pending reminders. Complete or cancel one first.",
                )
            now = now_utc()
            preferences = effective_settings(live.settings, self.settings.business_timezone)
            task = BookingTask(
                booking_id=booking.id,
                user_id=user.id,
                message=(body.message or "Check mail supplier...").strip()
                or "Check mail supplier...",
                remind_at=remind_instant(body.remind_date, body.remind_time, preferences, now),
                status="pending",
                snooze_count=0,
                client_request_id=str(body.client_request_id) if body.client_request_id else None,
                request_fingerprint=fingerprint,
                created_at=now,
            )
            session.add(task)
            await session.flush()
            result = task_dto(
                (await session.execute(task_query().where(BookingTask.id == task.id))).one(), now
            )
            task.create_result = result.model_dump(mode="json")
            record_audit(
                session,
                "task_created",
                actor_id=user.id,
                entity_type="task",
                entity_id=str(task.id),
                context=context,
                meta={"task_id": task.id},
            )
        return result

    async def change(self, task_id, operation, body, user, context):
        async with self.tx() as session:
            live = AuthService.require_live_row(
                await session.scalar(select(User).where(User.id == user.id).with_for_update()), user
            )
            task = await session.scalar(
                select(BookingTask)
                .where(BookingTask.id == task_id, BookingTask.user_id == user.id)
                .with_for_update()
            )
            if task is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            now = now_utc()
            if operation in {"complete", "cancel"}:
                wanted = "done" if operation == "complete" else "cancelled"
                if task.status == "pending":
                    task.status = wanted
                    task.completed_at = now if wanted == "done" else None
                elif task.status != wanted:
                    raise ApiException(
                        ErrorCode.VALIDATION_ERROR, message="This reminder is no longer pending."
                    )
            else:
                if task.status != "pending":
                    raise ApiException(
                        ErrorCode.VALIDATION_ERROR, message="Only pending reminders can be changed."
                    )
                prefs = effective_settings(live.settings, self.settings.business_timezone)
                local = task.remind_at.astimezone(ZoneInfo(prefs["timezone"]))
                if body.remind_date is not None or body.remind_time is not None:
                    chosen_day = body.remind_date or local.date()
                    chosen_time = body.remind_time or local.time().replace(tzinfo=None)
                    instant = (
                        task.remind_at
                        if (
                            chosen_day == local.date()
                            and chosen_time == local.time().replace(tzinfo=None)
                        )
                        else remind_instant(chosen_day, chosen_time, prefs, now)
                    )
                    if instant != task.remind_at:
                        task.remind_at = instant
                        task.notified_at = None
                        if operation == "snooze":
                            task.snooze_count += 1
                elif operation == "snooze":
                    raise ApiException(
                        ErrorCode.VALIDATION_ERROR, message="Choose a new reminder date."
                    )
                if body.message is not None:
                    task.message = body.message.strip() or "Check mail supplier..."
            await session.execute(
                update(Notification)
                .where(
                    Notification.user_id == user.id,
                    Notification.task_id == task.id,
                    Notification.read_at.is_(None),
                )
                .values(read_at=now)
            )
            await session.flush()
            result = task_dto(
                (await session.execute(task_query().where(BookingTask.id == task.id))).one(), now
            )
            record_audit(
                session,
                "task_" + operation,
                actor_id=user.id,
                entity_type="task",
                entity_id=str(task.id),
                context=context,
                meta={"task_id": task.id},
            )
        return result

    async def due_job(self):
        if self.engine is None:
            return
        while True:
            messages = []

            def committed(batch_messages=messages):
                for owner, notification, payload in batch_messages:
                    self.ws.spawn(self.ws.send_user(owner, "notification.new", notification))
                    self.ws.spawn(self.ws.send_user(owner, "task.due", payload))

            async with self.tx(after_commit=committed) as session:
                now = now_utc()
                tasks = (
                    await session.scalars(
                        select(BookingTask)
                        .where(
                            BookingTask.user_id.in_(
                                select(User.id).where(User.is_active.is_(True))
                            ),
                            BookingTask.status == "pending",
                            BookingTask.notified_at.is_(None),
                            BookingTask.remind_at <= now,
                        )
                        .order_by(BookingTask.remind_at, BookingTask.id)
                        .limit(100)
                        .with_for_update()
                    )
                ).all()
                if not tasks:
                    return
                for task in tasks:
                    task.notified_at = now
                    notification = Notification(
                        user_id=task.user_id,
                        booking_id=task.booking_id,
                        task_id=task.id,
                        type="task_due",
                        created_at=now,
                    )
                    session.add(notification)
                    await session.flush()
                    row = (
                        await session.execute(task_query().where(BookingTask.id == task.id))
                    ).one()
                    dto = task_dto(row, now)
                    new = NotificationNewData(
                        id=notification.id,
                        booking_key=dto.booking_key,
                        display_key=dto.display_key,
                        by_agent_name=None,
                        created_at=now,
                        type="task_due",
                    )
                    data = TaskDueData(task=dto, notification_id=notification.id, created_at=now)
                    messages.append(
                        (task.user_id, new.model_dump(mode="json"), data.model_dump(mode="json"))
                    )
            if len(tasks) < 100:
                return
