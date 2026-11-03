"""Real Uvicorn/WebSocket peers plus isolated TLS MySQL/TiDB business transactions."""

import asyncio
import json
import os
import socket
import weakref
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
import test_booking_database as support
import uvicorn
from sqlalchemy import func, select, update
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.core.security import create_access_token
from app.models import Booking, Notification

Rig = support.Rig
migrated = support.migrated
password_pair = support.password_pair
rig = support.rig
KEY = support.KEY
OTHER = KEY[:-4] + "2610"
pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated realtime database"
)


@pytest_asyncio.fixture
async def live(rig):
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            rig.app,
            host="127.0.0.1",
            port=port,
            lifespan="off",
            log_level="warning",
            access_log=False,
            ws="websockets-sansio",
            ws_max_size=rig.app.state.settings.ws_max_message_bytes,
            timeout_graceful_shutdown=1,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield f"ws://127.0.0.1:{port}/api/v1/ws"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        listener.close()


@asynccontextmanager
async def peer(live, rig, name="agent", token=None):
    token = (
        token if token is not None else rig.headers[name]["Authorization"].removeprefix("Bearer ")
    )
    # Only the test's loopback ASGI listener uses proxy=None; external networking is unchanged.
    async with connect(
        live + "?token=" + token, proxy=None, open_timeout=3, close_timeout=1, ping_interval=None
    ) as websocket:
        yield websocket


pending_frames = weakref.WeakKeyDictionary()


async def event(websocket, name, key=None):
    def matches(frame):
        return frame["event"] == name and (key is None or frame["data"].get("booking_key") == key)

    pending = pending_frames.setdefault(websocket, [])
    for i, frame in enumerate(pending):
        if matches(frame):
            return pending.pop(i)["data"]
    async with asyncio.timeout(3):
        while True:
            frame = json.loads(await websocket.recv())
            if frame["event"] == "ping":
                await websocket.send(json.dumps({"event": "pong", "data": {}}))
            elif matches(frame):
                return frame["data"]
            else:
                pending.append(frame)


async def command(websocket, name, key=KEY):
    await websocket.send(json.dumps({"event": name, "data": {"booking_key": key}}))


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():  # noqa: ASYNC110 - cross-transport state has no public wait event
            await asyncio.sleep(0.01)


async def test_note_commit_broadcast_cache_order_lock_release_and_private_takeover(live, rig):
    async with peer(live, rig) as a, peer(live, rig, "other") as b:
        assert (await event(a, "lock.snapshot"))["locks"] == []
        await event(b, "lock.snapshot")
        await command(a, "lock.acquire")
        assert (await event(b, "lock.acquired"))["user_id"] == 3
        saving = asyncio.create_task(rig.save())
        data = await event(b, "booking.updated")
        assert set(data) == {
            "booking_key",
            "display_key",
            "cw_number",
            "station_code",
            "version",
            "last_agent_id",
            "last_agent_name",
            "status_code",
            "position",
            "updated_at",
            "is_done",
            "snapshot_rebuilt",
        }
        assert data["booking_key"] == KEY and data["version"] == 1 and data["last_agent_id"] == 3
        assert data["updated_at"].endswith("Z") and data["status_code"] == "BUNDLE"
        lookup = (await rig.get("/bookings/lookup", user="other", key=KEY)).json()
        assert lookup["version"] == 1 and KEY in rig.app.state.key_index.keys
        assert KEY not in rig.app.state.lock_manager.locks
        assert (await saving).status_code == 200
        await event(a, "booking.updated")
        second = await rig.save(user="other", version=1)
        assert second.status_code == 200
        assert (await event(a, "booking.updated"))["version"] == 2
        notification = await event(a, "notification.new")
        assert notification["by_agent_name"] == "Other" and notification["type"] == "taken_over"
        assert notification["booking_key"] == KEY
        assert (await rig.get("/notifications")).json()["items"][0]["id"] == notification["id"]
        await event(b, "booking.updated")
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await event(b, "notification.new")


async def test_advisory_denial_does_not_block_note_and_expiry_heartbeat_disconnect(live, rig):
    manager = rig.app.state.lock_manager
    now = [100.0]
    manager.clock = lambda: now[0]
    async with peer(live, rig) as a, peer(live, rig, "other") as b:
        await event(a, "lock.snapshot")
        await event(b, "lock.snapshot")
        await command(a, "lock.acquire")
        await event(b, "lock.acquired", KEY)
        await command(b, "lock.acquire")
        assert (await event(b, "lock.denied"))["user_name"] == "Agent"
        assert (await rig.save(user="other")).status_code == 200  # Advisory, never a write ACL.
        await event(b, "booking.updated")
        assert KEY in manager.locks  # A different saver cannot release the holder's lease.
        now[0] += 100
        await command(a, "lock.heartbeat")
        await eventually(lambda: manager.locks[KEY].deadline == now[0] + 150)
        now[0] += 100
        manager.expire()
        assert KEY in manager.locks
        now[0] += 51
        await manager.sweep()
        assert (await event(b, "lock.released", KEY))["user_id"] == 3
        assert not manager.locks
        await command(a, "lock.acquire")
        await event(b, "lock.acquired", KEY)
        await a.close()
        await event(b, "lock.released", KEY)
        assert not manager.locks


async def test_same_sid_reconnect_keeps_lock_and_old_cleanup_cannot_remove_it(live, rig):
    async with peer(live, rig) as old:
        await event(old, "lock.snapshot")
        await command(old, "lock.acquire")
        await event(old, "lock.acquired")
        async with peer(live, rig) as fresh:
            snapshot = await event(fresh, "lock.snapshot")
            assert snapshot["locks"][0]["booking_key"] == KEY
            with pytest.raises(ConnectionClosed) as closed:
                await old.recv()
            assert closed.value.rcvd.code == 4409
            manager = rig.app.state.ws_manager
            assert len(manager.connections) == 1 and KEY in manager.locks.locks
            current = manager.connections[3]
            assert manager.locks.locks[KEY].connection_id == current.id
            await command(fresh, "lock.acquire", OTHER)
            await event(fresh, "lock.acquired", OTHER)
            assert KEY not in manager.locks.locks and list(manager.locks.locks) == [OTHER]


async def test_second_login_forces_old_socket_logout_then_new_sid_connects(
    live, rig, password_pair
):
    async with peer(live, rig) as old:
        await event(old, "lock.snapshot")
        await command(old, "lock.acquire")
        await event(old, "lock.acquired")
        response = await rig.client.post(
            "/api/v1/auth/login", json={"username": "agent", "password": password_pair[0]}
        )
        assert response.status_code == 200
        frame = await event(old, "session.force_logout")
        assert frame["reason"] == "new_login"
        with pytest.raises(ConnectionClosed) as closed:
            await old.recv()
        assert closed.value.rcvd.code == 4401
        assert (await rig.get("/auth/me")).json()["code"] == "SESSION_REPLACED"
        async with peer(live, rig, token=response.json()["access_token"]) as fresh:
            assert (await event(fresh, "lock.snapshot"))["locks"] == []
            assert len(rig.app.state.ws_manager.connections) == 1


@pytest.mark.parametrize("action", ["kick", "logout", "disable"])
async def test_revocation_helpers_close_current_socket(live, rig, action):
    async with peer(live, rig) as websocket:
        await event(websocket, "lock.snapshot")
        if action == "kick":
            assert await rig.app.state.auth.kick_session(3, actor_id=1)
            reason = "admin_kick"
        elif action == "disable":
            await rig.app.state.auth.set_user_active(3, False, actor_id=1)
            reason = "user_disabled"
        else:
            assert (
                await rig.client.post("/api/v1/auth/logout", headers=rig.headers["agent"])
            ).status_code == 200
            reason = "logout"
        assert (await event(websocket, "session.force_logout"))["reason"] == reason
        with pytest.raises(ConnectionClosed) as closed:
            await websocket.recv()
        assert closed.value.rcvd.code == 4401


@pytest.mark.parametrize("bad", ["malformed", "wrong_sid", "missing_user"])
async def test_invalid_handshake_has_real_4401_close(live, rig, bad):
    settings = rig.app.state.settings
    token = "invalid"
    if bad == "wrong_sid":
        token = create_access_token(3, "agent", str(uuid4()), settings)
    elif bad == "missing_user":
        token = create_access_token(9999, "agent", str(uuid4()), settings)
    async with peer(live, rig, token=token) as websocket:
        with pytest.raises(ConnectionClosed) as closed:
            await websocket.recv()
        assert closed.value.rcvd.code == 4401
    assert not rig.app.state.ws_manager.connections


async def test_handshake_checks_db_even_when_principal_cache_has_old_sid(live, rig):
    from app.models import User

    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            update(User).where(User.id == 3).values(current_session_id=str(uuid4()))
        )
    async with peer(live, rig) as websocket:
        with pytest.raises(ConnectionClosed) as closed:
            await websocket.recv()
        assert closed.value.rcvd.code == 4401


async def test_ping_pong_keeps_alive_then_silence_closes(live, rig):
    settings = rig.app.state.settings
    settings.ws_ping_interval_seconds = 0.02
    settings.ws_idle_timeout_seconds = 0.1
    async with peer(live, rig) as websocket:
        await event(websocket, "lock.snapshot")
        for _ in range(7):
            frame = json.loads(await websocket.recv())
            assert frame["event"] == "ping"
            await websocket.send(json.dumps({"event": "pong", "data": {}}))
        assert rig.app.state.ws_manager.connections
        with pytest.raises(ConnectionClosed) as closed:
            async with asyncio.timeout(1):
                while True:
                    await websocket.recv()
        assert closed.value.rcvd.code == 4408


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("not json", 4400),
        (b"binary", 1003),
        (
            json.dumps({"event": "lock.acquire", "data": {"booking_key": "CW 2154654-RDU-2609"}}),
            4400,
        ),
        ("x" * 5000, 1009),
    ],
)
async def test_bad_frames_close_and_release_locks(live, rig, message, code):
    async with peer(live, rig) as websocket:
        await event(websocket, "lock.snapshot")
        await command(websocket, "lock.acquire")
        await event(websocket, "lock.acquired")
        await websocket.send(message)
        with pytest.raises(ConnectionClosed) as closed:
            async with asyncio.timeout(3):
                await websocket.recv()
        assert closed.value.rcvd.code == code
        await eventually(lambda: KEY not in rig.app.state.lock_manager.locks)


async def test_stale_job_once_per_episode_preserves_clock_and_delivers_privately(live, rig):
    assert (await rig.save()).status_code == 200
    assert (
        await rig.save(key=OTHER, status_code="DONE", invoices={"no_invoice": True})
    ).status_code == 200
    old = datetime.now(UTC) - timedelta(hours=25)
    old = old.replace(microsecond=old.microsecond // 1000 * 1000)
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(update(Booking).values(updated_at=old))
    async with peer(live, rig) as owner, peer(live, rig, "other") as other:
        await event(owner, "lock.snapshot")
        await event(other, "lock.snapshot")
        await asyncio.gather(
            rig.app.state.stale_reminders.run(), rig.app.state.stale_reminders.run()
        )
        data = await event(owner, "notification.new")
        assert (
            data["type"] == "stale" and data["by_agent_name"] is None and data["booking_key"] == KEY
        )
        async with rig.app.state.engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.type == "stale")
                )
                == 1
            )
            row = (
                await connection.execute(
                    select(Booking.updated_at, Booking.version, Booking.stale_notified_at).where(
                        Booking.booking_key == KEY
                    )
                )
            ).one()
            assert row.updated_at == old and row.version == 1 and row.stale_notified_at is not None
        assert (await rig.get("/bookings/stale")).json()["total"] == 1
        await rig.app.state.stale_reminders.run()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await event(other, "notification.new")
        assert (await rig.save(version=1)).status_code == 200
        async with rig.app.state.engine.begin() as connection:
            await connection.execute(
                update(Booking).where(Booking.booking_key == KEY).values(updated_at=old)
            )
        await rig.app.state.stale_reminders.run()
        assert (await event(owner, "notification.new"))["type"] == "stale"
        async with rig.app.state.engine.connect() as connection:
            assert (
                await connection.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.type == "stale")
                )
                == 2
            )


async def test_scheduler_runs_stale_catchup_immediately_at_start(live, rig):
    await rig.save()
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            update(Booking).values(updated_at=datetime.now(UTC) - timedelta(hours=30))
        )
    async with peer(live, rig) as websocket:
        await event(websocket, "lock.snapshot")
        rig.app.state.scheduler.start()
        data = await event(websocket, "notification.new")
        assert data["type"] == "stale"
        await rig.app.state.scheduler.stop()


async def test_idempotent_retry_does_not_duplicate_realtime_events(live, rig):
    request_id = str(uuid4())
    async with peer(live, rig) as websocket:
        await event(websocket, "lock.snapshot")
        first = await rig.save(client_request_id=request_id)
        assert first.status_code == 200
        await event(websocket, "booking.updated")
        second = await rig.save(client_request_id=request_id)
        assert second.json() == first.json()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await websocket.recv()


async def test_stale_custom_threshold_old_marker_and_batch_paging(rig):
    keys = [KEY, OTHER, KEY[:-4] + "2611", KEY[:-4] + "2612"]
    for key in keys[:3]:
        assert (await rig.save(key=key)).status_code == 200
    assert (
        await rig.save(key=keys[3], status_code="DONE", invoices={"no_invoice": True})
    ).status_code == 200
    from app.models import Status

    now = datetime.now(UTC)
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            update(Status).where(Status.code == "BUNDLE").values(stale_after_hours=2)
        )
        await connection.execute(update(Booking).values(updated_at=now - timedelta(hours=3)))
        await connection.execute(
            update(Booking)
            .where(Booking.booking_key == KEY)
            .values(stale_notified_at=now - timedelta(hours=4), updated_at=Booking.updated_at)
        )
        await connection.execute(
            update(Booking)
            .where(Booking.booking_key == OTHER)
            .values(stale_notified_at=now - timedelta(hours=1), updated_at=Booking.updated_at)
        )
    rig.app.state.settings.stale_job_batch_size = 1
    await rig.app.state.stale_reminders.run()
    await rig.app.state.stale_reminders.run()
    async with rig.app.state.engine.connect() as connection:
        result = (
            (
                await connection.execute(
                    select(Booking.booking_key)
                    .join(Notification, Notification.booking_id == Booking.id)
                    .where(Notification.type == "stale")
                )
            )
            .scalars()
            .all()
        )
        assert set(result) == {KEY, keys[2]} and len(result) == 2
