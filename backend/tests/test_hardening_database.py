"""Authenticated IDOR, initial-password and injection checks on disposable TLS databases."""

import json
from datetime import UTC, datetime, timedelta

import pytest
import test_booking_database as support
import test_realtime_database as realtime_support
from sqlalchemy import select, update
from websockets.exceptions import ConnectionClosed

from app.models import BookingNote, User

migrated, password_pair, rig = support.migrated, support.password_pair, support.rig
live = realtime_support.live
pytestmark = support.pytestmark
KEY = support.KEY


async def test_created_reset_account_requires_password_change_at_every_api(rig, password_pair):
    temporary = "Temporary-12345"
    created = await rig.client.post(
        "/api/v1/admin/users",
        headers=rig.headers["admin"],
        json={
            "username": "new-agent",
            "full_name": "New Agent",
            "role": "agent",
            "temporary_password": temporary,
        },
    )
    assert created.status_code in (200, 201), created.text
    identifier = created.json()["id"]

    async def login(password):
        return await rig.client.post(
            "/api/v1/auth/login", json={"username": "new-agent", "password": password}
        )

    signed = await login(temporary)
    assert signed.status_code == 200
    assert signed.json()["user"]["must_change_password"] is True
    headers = {"Authorization": "Bearer " + signed.json()["access_token"]}
    for route in ("/statuses", "/bookings", "/profile/stats", "/notifications", "/users/lookup"):
        response = await rig.client.get("/api/v1" + route, headers=headers)
        assert response.status_code == 403 and response.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    bad = await rig.client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"old_password": temporary, "new_password": "NEW-AGENT"},
    )
    assert bad.status_code == 422
    changed = await rig.client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"old_password": temporary, "new_password": "A-new-safe-password-123"},
    )
    assert changed.status_code == 200, changed.text
    assert (await rig.client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    signed = await login("A-new-safe-password-123")
    assert signed.json()["user"]["must_change_password"] is False
    headers = {"Authorization": "Bearer " + signed.json()["access_token"]}
    assert (await rig.client.get("/api/v1/statuses", headers=headers)).status_code == 200
    reset = await rig.client.post(
        f"/api/v1/admin/users/{identifier}/reset-password",
        headers=rig.headers["admin"],
        json={"temporary_password": temporary},
    )
    assert reset.status_code == 200, reset.text
    assert (await login(temporary)).json()["user"]["must_change_password"] is True


async def test_password_not_username_and_admin_acl(rig):
    response = await rig.client.post(
        "/api/v1/admin/users",
        headers=rig.headers["admin"],
        json={
            "username": "username1234",
            "full_name": "New User",
            "role": "agent",
            "temporary_password": "USERNAME1234",
        },
    )
    assert response.status_code == 422
    assert (await rig.get("/admin/users")).status_code == 403
    assert (await rig.get("/admin/system/health")).status_code == 403


async def test_note_script_sql_input_and_oversize_are_plain_text_or_rejected(rig):
    content = "<script>alert('x')</script> ' OR 1=1 --\x00\u202e"
    response = await rig.save(note=content)
    assert response.status_code == 200, response.text
    assert response.json()["note"]["note"] == content.replace("\x00", "").replace("\u202e", "")
    assert (await rig.save(version=1, note="x" * 5001)).status_code == 422
    for raw in ("' OR 1=1 --", "<script>alert(1)</script>", "CW" + "1" * 101):
        response = await rig.get("/bookings/lookup", key=raw)
        assert response.status_code == 422 or response.json()["exists"] is False
    async with rig.app.state.engine.connect() as c:
        assert len((await c.execute(select(BookingNote.id))).all()) == 1


async def test_notification_task_private_ids_and_bounded_queries(rig):
    await rig.save()
    await rig.save(user="other", version=1, note="Other agent update")
    notifications = (await rig.get("/notifications")).json()["items"]
    assert notifications
    response = await rig.client.post(
        "/api/v1/notifications/" + str(notifications[0]["id"]) + "/read",
        headers=rig.headers["other"],
    )
    assert response.status_code == 404
    date = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    created = await rig.client.post(
        f"/api/v1/bookings/{KEY}/tasks",
        headers=rig.headers["agent"],
        json={"remind_date": date, "message": "Owner only"},
    )
    assert created.status_code in (200, 201), created.text
    identifier = created.json()["id"]
    for method, path, body in [
        ("POST", f"/tasks/{identifier}/complete", None),
        ("POST", f"/tasks/{identifier}/snooze", {"remind_date": date}),
        ("PATCH", f"/tasks/{identifier}", {"message": "Stolen"}),
        ("DELETE", f"/tasks/{identifier}", None),
    ]:
        response = await rig.client.request(
            method, "/api/v1" + path, headers=rig.headers["other"], json=body
        )
        assert response.status_code == 404, response.text
    rig.app.state.search_limiter.limit = 1
    assert (await rig.get("/bookings/lookup", key=KEY)).status_code == 200
    limited = await rig.get("/bookings/lookup", key=KEY)
    assert limited.status_code == 429 and limited.headers["retry-after"].isdecimal()
    assert (await rig.get("/search", q="x" * 101)).status_code == 422


async def test_websocket_missing_token_wrong_origin_burst_and_forced_rotation(rig, live):
    from websockets.asyncio.client import connect

    token = rig.headers["agent"]["Authorization"].removeprefix("Bearer ")
    for origin, suffix, code in [
        ("https://evil.example", "?token=" + token, 4403),
        ("http://localhost:5173", "", 4401),
        (None, "?token=" + token, 4403),
    ]:
        async with connect(live + suffix, origin=origin, proxy=None) as ws:
            with pytest.raises(ConnectionClosed) as error:
                await ws.recv()
            assert error.value.rcvd.code == code
    async with realtime_support.peer(live, rig) as ws:
        await realtime_support.event(ws, "lock.snapshot")
        for _ in range(21):
            try:
                await ws.send(json.dumps({"event": "pong", "data": {}}))
            except ConnectionClosed:
                break
        with pytest.raises(ConnectionClosed) as error:
            while True:
                await ws.recv()
        assert error.value.rcvd.code == 1008
    async with rig.app.state.engine.begin() as c:
        await c.execute(update(User).where(User.id == 3).values(must_change_password=True))
    async with realtime_support.peer(live, rig) as ws:
        with pytest.raises(ConnectionClosed) as error:
            await ws.recv()
        assert error.value.rcvd.code == 4401
