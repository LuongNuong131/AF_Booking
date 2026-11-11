import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.request_context import WebSocketTokenRedaction
from app.core.security import TokenClaims
from app.services.lock_manager import LockManager
from app.services.scheduler import Scheduler
from app.services.session_cache import CurrentUser
from app.services.ws_manager import WebSocketManager

KEY = "CW2154654-RDU-2609"
OTHER = "CW2154654-RDU-2610"


def actor(identifier=1, connection_id="first"):
    return SimpleNamespace(
        id=connection_id,
        user=CurrentUser(identifier, "agent", "Agent", "agent", True, str(uuid4()), None),
    )


def test_advisory_lock_expiry_heartbeat_single_lease_and_ownership():
    events = []
    locks = LockManager(lambda *args: events.append(args))
    now = [100.0]
    locks.clock = lambda: now[0]
    locks.now = lambda: datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=now[0])
    a, b = actor(), actor(2, "second")
    assert locks.acquire(a, KEY)
    now[0] += 100
    assert locks.heartbeat(a, KEY)
    now[0] += 100
    locks.expire()
    assert KEY in locks.locks
    assert not locks.acquire(b, KEY)
    assert events[-1][0] == "lock.denied" and events[-1][2] == 2
    locks.release(2, KEY)
    assert KEY in locks.locks
    assert locks.acquire(a, OTHER)
    assert KEY not in locks.locks and len(locks.by_user) == 1
    assert [e[0] for e in events[-2:]] == ["lock.released", "lock.acquired"]
    now[0] += 151
    assert locks.snapshot() == [] and locks.by_user == {}
    assert events[-1][0] == "lock.released"


def test_reconnect_transfers_lease_and_old_disconnect_cannot_release_new_lock():
    locks = LockManager(lambda *args: None)
    a = actor()
    b = SimpleNamespace(id="replacement", user=a.user)
    locks.acquire(a, KEY)
    locks.transfer(a, b)
    locks.disconnect(a)
    assert KEY in locks.locks
    assert locks.heartbeat(b, KEY)
    locks.disconnect(b)
    assert not locks.locks


class FakeSocket:
    def __init__(self, slow=False):
        self.slow = slow
        self.messages = []
        self.closed = None
        self.sent = asyncio.Event()

    async def accept(self):
        pass

    async def send_json(self, frame):
        if self.slow:
            await asyncio.Event().wait()
        self.messages.append(frame)
        self.sent.set()

    async def close(self, code):
        self.closed = code


async def attach(manager, identifier, socket=None):
    user = actor(identifier).user
    claims = TokenClaims(
        sub=str(identifier),
        role="agent",
        sid=user.session_id,
        iat=int(time.time()) - 1,
        exp=int(time.time()) + 3600,
    )
    return await manager.connect(socket or FakeSocket(), user, claims)


async def test_slow_client_does_not_delay_broadcast_and_is_closed():
    manager = WebSocketManager(Settings(_env_file=None, ws_send_timeout_seconds=0.05))
    slow, fast = FakeSocket(slow=True), FakeSocket()
    try:
        a = await attach(manager, 1, slow)
        await attach(manager, 2, fast)
        await manager.broadcast("notification.new", {"booking_key": KEY})
        await asyncio.wait_for(fast.sent.wait(), 0.5)
        await asyncio.sleep(0)
        assert any(m["event"] == "notification.new" for m in fast.messages)
        assert not a.finished.is_set()  # Fast client already received while slow send is blocked.
        await asyncio.wait_for(a.finished.wait(), 0.5)
        assert slow.closed == 4408 and 1 not in manager.connections
    finally:
        await manager.stop()


async def test_queue_overflow_is_bounded_and_revocation_targets_only_old_sid():
    manager = WebSocketManager(Settings(_env_file=None, ws_queue_size=1))
    try:
        connection = await attach(manager, 1)
        manager.emit("ping", {}, 1)  # Snapshot still occupies the single slot.
        assert connection.closing
        await connection.finished.wait()
        assert connection.socket.closed == 4408
        active = await attach(manager, 1)
        await manager.force_logout(1, str(uuid4()), "new_login")
        assert manager.current(active)
        await manager.force_logout(1, active.user.session_id, "new_login")
        await active.finished.wait()
        assert active.socket.messages[-1]["event"] == "session.force_logout"
        assert active.socket.closed == 4401
    finally:
        await manager.stop()


async def test_ping_idle_timeout_and_token_expiry_close():
    settings = Settings(_env_file=None, ws_ping_interval_seconds=0.01, ws_idle_timeout_seconds=0.04)
    manager = WebSocketManager(settings)
    try:
        conn = await attach(manager, 1)
        await asyncio.wait_for(conn.finished.wait(), 0.5)
        assert any(m["event"] == "ping" for m in conn.socket.messages)
        assert conn.socket.closed == 4408
        expired = await attach(manager, 2)
        expired.claims.exp = int(time.time()) - 1
        assert not await manager.verify(expired)
        await asyncio.wait_for(expired.finished.wait(), 0.5)
        assert expired.socket.closed == 4401
        assert expired.socket.messages[-1]["data"]["reason"] == "token_expired"
    finally:
        await manager.stop()


async def test_scheduler_immediate_catchup_failure_isolation_no_overlap_and_stop(caplog):
    scheduler = Scheduler()
    good_calls, bad_calls, concurrent = [], [], [0, 0]

    async def good():
        concurrent[0] += 1
        concurrent[1] = max(concurrent)
        good_calls.append(True)
        await asyncio.sleep(0.02)
        concurrent[0] -= 1

    async def broken():
        bad_calls.append(True)
        raise RuntimeError("private detail must not be logged")

    scheduler.add_job("good", good, interval=0.01)
    scheduler.add_job("bad", broken, interval=0.01)
    scheduler.start()
    await asyncio.sleep(0.075)
    await scheduler.stop()
    assert len(good_calls) >= 2 and len(bad_calls) >= 2 and concurrent[1] == 1
    assert scheduler.tasks == {} and not scheduler.running
    assert "private detail" not in caplog.text and "bad" in caplog.text


@pytest.mark.parametrize("parameter", ["token", "%74oken"])
def test_uvicorn_websocket_handshake_tokens_are_redacted(parameter):
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        "",
        0,
        '%s - "WebSocket %s" [accepted]',
        ("client", f"/api/v1/ws?{parameter}=private.jwt.value&flag=1"),
        None,
    )
    WebSocketTokenRedaction().filter(record)
    assert "private.jwt.value" not in record.getMessage()
    assert "?[REDACTED]" in record.getMessage()


async def test_booking_broadcast_coalesces_per_key_and_retains_newest_version():
    manager = WebSocketManager(Settings(_env_file=None))
    socket = FakeSocket()
    try:
        await attach(manager, 1, socket)
        for key, version in ((KEY, 2), (KEY, 4), (KEY, 3), ("CW9999999-YUL-2609", 1)):
            await manager.broadcast("booking.updated", {"booking_key": key, "version": version})
        await asyncio.sleep(0.04)
        assert not any(m["event"] == "booking.updated" for m in socket.messages)
        async with asyncio.timeout(1):
            while sum(m["event"] == "booking.updated" for m in socket.messages) < 2:
                socket.sent.clear()
                await socket.sent.wait()
        updates = [m["data"] for m in socket.messages if m["event"] == "booking.updated"]
        assert len(updates) == 2
        assert next(m for m in updates if m["booking_key"] == KEY)["version"] == 4
    finally:
        await manager.stop()
