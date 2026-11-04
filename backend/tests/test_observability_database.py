import json
from datetime import UTC, datetime, timedelta

import test_booking_database as support
from sqlalchemy import select, update

from app.models import AuditLog, BookingTask, Notification

migrated, password_pair, rig = support.migrated, support.password_pair, support.rig
pytestmark = support.pytestmark


async def test_retention_only_removes_expired_read_and_terminal_rows_in_batches(rig):
    assert (await rig.save()).status_code == 200
    now = datetime.now(UTC)
    async with rig.app.state.engine.begin() as c:
        await c.execute(
            AuditLog.__table__.insert(),
            [
                {"action": "old-test", "created_at": now - timedelta(days=181)},
                {"action": "recent-test", "created_at": now - timedelta(days=179)},
            ],
        )
        await c.execute(
            Notification.__table__.insert(),
            [
                {
                    "id": 100 + i,
                    "user_id": 3,
                    "booking_id": 1,
                    "type": "stale",
                    "created_at": now - timedelta(days=100),
                    "read_at": read,
                }
                for i, read in enumerate([None, now - timedelta(days=61), now - timedelta(days=59)])
            ],
        )
        await c.execute(
            BookingTask.__table__.insert(),
            [
                {
                    "id": 100 + i,
                    "booking_id": 1,
                    "user_id": 3,
                    "message": "Test retention",
                    "remind_at": now - timedelta(days=100),
                    "status": status,
                    "created_at": now - timedelta(days=100),
                    "updated_at": now - timedelta(days=age),
                }
                for i, (status, age) in enumerate(
                    [
                        ("pending", 100),
                        ("done", 91),
                        ("cancelled", 91),
                        ("done", 89),
                        ("cancelled", 89),
                    ]
                )
            ],
        )
        await c.execute(update(Notification).where(Notification.id == 100).values(task_id=101))
    service = rig.app.state.retention
    service.settings = service.settings.model_copy(update={"retention_batch_size": 1})
    removed = await service.run(now)
    assert removed == {"audit_logs": 1, "notifications": 1, "booking_tasks": 2}
    assert await service.run(now) == {"audit_logs": 0, "notifications": 0, "booking_tasks": 0}
    async with rig.app.state.engine.connect() as c:
        assert (await c.execute(select(Notification.id))).scalars().all() == [100, 102]
        assert await c.scalar(select(Notification.task_id).where(Notification.id == 100)) is None
        assert set((await c.execute(select(BookingTask.id))).scalars()) == {100, 103, 104}
    service.settings = service.settings.model_copy(update={"retention_enabled": False})
    assert await service.run(now) == {}


async def test_health_reports_index_cache_error_counts_and_structured_identity(rig, caplog):
    assert (await rig.save()).status_code == 200
    await rig.get("/bookings/lookup", key=support.KEY)
    await rig.get("/bookings/lookup", key=support.KEY)
    report = (await rig.get("/admin/system/health", user="admin")).json()
    assert report["key_index"]["keys"] == 1 and report["key_index"]["folders"] == 1
    assert report["key_index"]["container_bytes"] > 0
    assert report["snapshot_cache"]["hits"] >= 1 and report["snapshot_cache"]["hit_ratio"] > 0
    logs = [r for r in caplog.records if getattr(r, "event", None) == "http.request"]
    assert any(r.user_id == 3 and isinstance(r.duration_ms, float) for r in logs)
    from app.core.logging import JsonFormatter

    assert "Bearer" not in json.dumps([json.loads(JsonFormatter().format(r)) for r in logs])


async def test_owned_pool_default_and_snapshot_override_restore_isolation(rig):
    from sqlalchemy import text

    from app.core.unit_of_work import transaction

    async def level(isolation="READ COMMITTED"):
        async with transaction(
            rig.app.state.engine, rig.app.state.settings, isolation_level=isolation
        ) as session:
            return (
                (await session.scalar(text("SELECT @@transaction_isolation")))
                .replace("-", " ")
                .upper()
            )

    assert await level() == "READ COMMITTED"
    assert await level("REPEATABLE READ") == "REPEATABLE READ"
    assert await level() == "READ COMMITTED"
