"""Private reminders, idempotency, local time and due-event delivery on real TLS databases."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_booking_database as support
import test_realtime_database as realtime
from sqlalchemy import func, select, update

from app.models import BookingTask, Notification, User

migrated = support.migrated
password_pair = support.password_pair
rig = support.rig
live = realtime.live
KEY = support.KEY
pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated task database"
)


def payload(**changes):
    return {
        "remind_date": (datetime.now(UTC).date() + timedelta(days=2)).isoformat(),
        "remind_time": "09:00",
        "message": "Check supplier mail",
        "client_request_id": str(uuid4()),
        **changes,
    }


async def create(rig, body=None, user="agent"):
    return await rig.client.post(
        f"/api/v1/bookings/{KEY}/tasks", headers=rig.headers[user], json=body or payload()
    )


async def test_create_replay_ownership_limit_and_public_settings(rig):
    await rig.save()
    body = payload()
    first = await create(rig, body)
    assert first.status_code == 200 and first.json()["booking_key"] == KEY
    assert first.json()["booking_changed_since"] is False
    assert first.json()["remind_at"].endswith("T02:00:00.000Z")
    again = await create(rig, body)
    assert again.json() == first.json()
    assert (await create(rig, {**body, "message": "different"})).status_code == 422
    identifier = first.json()["id"]
    assert (await rig.get(f"/bookings/{KEY}/tasks", user="other")).json() == []
    for method, path, json in [
        ("post", f"/tasks/{identifier}/complete", None),
        ("patch", f"/tasks/{identifier}", {"message": "attack"}),
        ("delete", f"/tasks/{identifier}", None),
    ]:
        response = await rig.client.request(
            method,
            "/api/v1" + path,
            headers=rig.headers["other"],
            **({"json": json} if json else {}),
        )
        assert response.status_code == 404
    for _ in range(4):
        assert (await create(rig)).status_code == 200
    denied = await create(rig)
    assert denied.status_code == 422 and denied.json()["code"] == "TASK_LIMIT_REACHED"
    assert (await rig.get("/auth/me")).json()["settings"]["timezone"] == "Asia/Ho_Chi_Minh"


async def test_concurrent_limit_and_uuid_are_atomic(rig):
    await rig.save()
    body = payload()
    responses = await asyncio.gather(*[create(rig, body) for _ in range(3)])
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 1
    responses = await asyncio.gather(*[create(rig) for _ in range(6)])
    assert sum(r.status_code == 200 for r in responses) == 4
    async with rig.app.state.engine.connect() as c:
        assert await c.scalar(select(func.count()).select_from(BookingTask)) == 5


async def test_mutations_due_catchup_notification_once_and_realtime(live, rig):
    await rig.save()
    original_body = payload()
    task = (await create(rig, original_body)).json()
    identifier = task["id"]
    async with rig.app.state.engine.begin() as c:
        await c.execute(
            update(BookingTask)
            .where(BookingTask.id == identifier)
            .values(remind_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    async with realtime.peer(live, rig) as ws:
        await realtime.event(ws, "lock.snapshot")
        await rig.app.state.tasks.due_job()
        notice = await realtime.event(ws, "notification.new")
        event = await realtime.event(ws, "task.due")
        assert event["task"]["id"] == identifier and event["notification_id"] == notice["id"]
        assert event["task"]["is_due"] and notice["type"] == "task_due"
    await rig.app.state.tasks.due_job()
    async with rig.app.state.engine.connect() as c:
        assert (
            await c.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.task_id == identifier)
            )
            == 1
        )
    due = (await rig.get("/tasks/due")).json()
    assert due["total"] == 1 and due["items"][0]["id"] == identifier
    edited = await rig.client.patch(
        f"/api/v1/tasks/{identifier}",
        headers=rig.headers["agent"],
        json={"message": "Recheck overdue mail"},
    )
    assert edited.status_code == 200 and edited.json()["is_due"]
    assert edited.json()["remind_at"] == due["items"][0]["remind_at"]
    body = {"remind_date": payload()["remind_date"], "remind_time": "10:00"}
    for _ in range(2):
        result = await rig.client.post(
            f"/api/v1/tasks/{identifier}/snooze", headers=rig.headers["agent"], json=body
        )
        assert result.status_code == 200 and result.json()["snooze_count"] == 1
    assert (await rig.get("/tasks/due")).json()["total"] == 0
    for _ in range(2):
        done = await rig.client.post(
            f"/api/v1/tasks/{identifier}/complete", headers=rig.headers["agent"]
        )
        assert done.json()["status"] == "done"
    assert (await rig.get("/tasks", view="done")).json()["total"] == 1
    assert (await rig.get("/notifications")).json()["unread_count"] == 0
    assert (await create(rig, original_body)).json() == task
    assert (await rig.get("/tasks", view="done")).json()["total"] == 1


async def test_profile_merge_timezone_validation_and_future_range(rig):
    await rig.save()
    result = await rig.client.patch(
        "/api/v1/profile",
        headers=rig.headers["agent"],
        json={
            "settings": {
                "timezone": "America/Toronto",
                "default_remind_time": "10:30",
                "skip_weekends": False,
                "task_sound": True,
            }
        },
    )
    assert result.status_code == 200
    assert (await rig.get("/auth/me")).json()["settings"]["task_sound"] is True
    task = await create(rig, payload(remind_time=None))
    assert task.status_code == 200 and task.json()["remind_at"].endswith("T15:30:00.000Z")
    for settings in [{"timezone": "Invalid/Zone"}, {"default_remind_time": "25:00"}]:
        assert (
            await rig.client.patch(
                "/api/v1/profile", headers=rig.headers["agent"], json={"settings": settings}
            )
        ).status_code == 422
    assert (
        await create(
            rig, payload(remind_date=(datetime.now(UTC).date() + timedelta(days=92)).isoformat())
        )
    ).status_code == 422
    assert (await create(rig, payload(remind_date="2020-01-01"))).status_code == 422
    async with rig.app.state.engine.connect() as c:
        assert (await c.scalar(select(User.settings).where(User.id == 3)))["skip_weekends"] is False
