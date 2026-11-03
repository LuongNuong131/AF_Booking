"""Durable once-per-stale-episode notifications; sockets are best-effort after commit."""

from datetime import UTC, datetime

from sqlalchemy import func, or_, select, text, update

from app.core.unit_of_work import transaction
from app.models import Booking, Notification, Status
from app.schemas.realtime import NotificationNewData
from app.utils.booking_key import to_display


class StaleReminders:
    def __init__(self, engine, settings, ws_manager):
        self.engine, self.settings, self.ws_manager = engine, settings, ws_manager

    async def run(self) -> None:
        if self.engine is None:
            return
        while True:
            now = datetime.now(UTC)
            now = now.replace(microsecond=now.microsecond // 1000 * 1000)
            messages = []

            def committed(batch_messages=messages) -> None:
                for user_id, payload in batch_messages:
                    self.ws_manager.spawn(
                        self.ws_manager.send_user(user_id, "notification.new", payload)
                    )

            async with transaction(self.engine, self.settings, after_commit=committed) as session:
                # Pessimistic row locks serialize against note saves and another run.
                # Avoid SKIP LOCKED: not all supported TiDB variants implement it.
                rows = (
                    await session.execute(
                        select(Booking.id, Booking.booking_key, Booking.last_agent_id)
                        .outerjoin(Status, Status.id == Booking.last_status_id)
                        .where(
                            Booking.is_done.is_(False),
                            Booking.last_agent_id.is_not(None),
                            Booking.updated_at
                            <= func.timestampadd(
                                text("HOUR"),
                                -func.coalesce(
                                    Status.stale_after_hours, self.settings.stale_hours_default
                                ),
                                func.utc_timestamp(3),
                            ),
                            or_(
                                Booking.stale_notified_at.is_(None),
                                Booking.stale_notified_at < Booking.updated_at,
                            ),
                        )
                        .order_by(Booking.updated_at, Booking.id)
                        .limit(self.settings.stale_job_batch_size)
                        .with_for_update()
                    )
                ).all()
                if not rows:
                    return
                notifications = []
                for row in rows:
                    notification = Notification(
                        user_id=row.last_agent_id, booking_id=row.id, type="stale", created_at=now
                    )
                    session.add(notification)
                    notifications.append((row, notification))
                await session.flush()
                # Explicit self-assignment prevents MySQL's ON UPDATE timestamp from
                # resetting the booking's stale clock when only the marker changes.
                await session.execute(
                    update(Booking)
                    .where(Booking.id.in_([r.id for r in rows]))
                    .values(stale_notified_at=now, updated_at=Booking.updated_at)
                )
                for row, notification in notifications:
                    data = NotificationNewData(
                        id=notification.id,
                        booking_key=row.booking_key,
                        display_key=to_display(row.booking_key),
                        by_agent_name=None,
                        created_at=now,
                        type="stale",
                    )
                    messages.append((row.last_agent_id, data.model_dump(mode="json")))
            if len(rows) < self.settings.stale_job_batch_size:
                return
