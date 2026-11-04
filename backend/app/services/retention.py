"""Bounded cleanup transactions; only read notifications and terminal tasks expire."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update

from app.core.unit_of_work import transaction
from app.models import AuditLog, BookingTask, Notification

logger = logging.getLogger(__name__)


class RetentionService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self.last_deleted = {}

    async def run(self, now=None):
        if not self.settings.retention_enabled or self.engine is None:
            return {}
        now = now or datetime.now(UTC)
        jobs = [
            (
                AuditLog,
                AuditLog.created_at < now - timedelta(days=self.settings.audit_retention_days),
                AuditLog.created_at,
            ),
            (
                Notification,
                Notification.read_at
                < now - timedelta(days=self.settings.notification_retention_days),
                Notification.read_at,
            ),
            (
                BookingTask,
                (BookingTask.status == "done")
                & (
                    BookingTask.updated_at < now - timedelta(days=self.settings.task_retention_days)
                ),
                BookingTask.updated_at,
            ),
            (
                BookingTask,
                (BookingTask.status == "cancelled")
                & (
                    BookingTask.updated_at < now - timedelta(days=self.settings.task_retention_days)
                ),
                BookingTask.updated_at,
            ),
        ]
        removed = {"audit_logs": 0, "notifications": 0, "booking_tasks": 0}
        for model, condition, clock in jobs:
            for _ in range(self.settings.retention_max_batches):
                async with transaction(self.engine, self.settings) as session:
                    ids = (
                        await session.scalars(
                            select(model.id)
                            .where(condition)
                            .order_by(clock, model.id)
                            .limit(self.settings.retention_batch_size)
                        )
                    ).all()
                    if not ids:
                        break
                    if model is BookingTask:
                        await session.execute(
                            update(Notification)
                            .where(Notification.task_id.in_(ids))
                            .values(task_id=None)
                        )
                    result = await session.execute(
                        delete(model).where(model.id.in_(ids), condition)
                    )
                    removed[model.__tablename__] += result.rowcount
                await asyncio.sleep(0.01)
        self.last_deleted = removed
        logger.info(
            "Expired operational data removed",
            extra={"event": "data.retention", "deleted": removed},
        )
        return removed
