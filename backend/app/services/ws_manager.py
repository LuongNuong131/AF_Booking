"""Single-instance socket registry and bounded per-client writers. Redis is needed to scale."""

import asyncio
import logging
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from app.core.errors import ApiException
from app.core.security import TokenClaims
from app.schemas.contracts import ErrorCode
from app.schemas.realtime import ForceLogoutFrame
from app.services.lock_manager import LockManager
from app.services.session_cache import CurrentUser

logger = logging.getLogger(__name__)


@dataclass
class Outgoing:
    frame: dict | None
    close_code: int | None = None


@dataclass(eq=False)
class Connection:
    socket: WebSocket = field(repr=False)
    user: CurrentUser
    claims: TokenClaims = field(repr=False)
    queue: asyncio.Queue[Outgoing] = field(repr=False)
    id: str = field(default_factory=lambda: str(uuid4()))
    closing: bool = False
    finished: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    writer: asyncio.Task | None = field(default=None, repr=False)
    heartbeat: asyncio.Task | None = field(default=None, repr=False)
    last_pong: float = 0


class WebSocketManager:
    def __init__(self, settings):
        self.settings = settings
        self.auth = None
        self.connections: dict[int, Connection] = {}
        self.push = None
        self.health_status = None
        self._all: dict[str, Connection] = {}
        self._background: set[asyncio.Task] = set()
        self.stopping = False
        self._booking_batch: dict[str, dict] = {}
        self._batch_task: asyncio.Task | None = None
        self.clock = time.monotonic
        self.locks = LockManager(self.emit, settings.lock_ttl_seconds)

    def current(self, connection: Connection) -> bool:
        return self.connections.get(connection.user.id) is connection and not connection.closing

    def _detach(self, connection: Connection) -> None:
        if self.connections.get(connection.user.id) is connection:
            self.connections.pop(connection.user.id)
            self.locks.disconnect(connection)

    def retire(self, connection: Connection, code: int = 1000, frame: dict | None = None) -> None:
        self._detach(connection)
        if connection.closing:
            return
        connection.closing = True
        while not connection.queue.empty():
            connection.queue.get_nowait()
            connection.queue.task_done()
        connection.queue.put_nowait(Outgoing(frame, code))

    def _offer(self, connection: Connection, frame: dict) -> None:
        if not self.current(connection):
            return
        try:
            connection.queue.put_nowait(Outgoing(frame))
        except asyncio.QueueFull:
            logger.warning("WebSocket queue full user_id=%s", connection.user.id)
            self.retire(connection, 4408)

    def emit(self, event: str, data: dict, user_id: int | None = None) -> None:
        frame = {"event": event, "data": data}
        targets = (
            list(self.connections.values()) if user_id is None else [self.connections.get(user_id)]
        )
        for connection in targets:
            if connection is not None:
                self._offer(connection, frame)

    async def broadcast(self, event: str, payload: dict) -> None:
        # No network await here: a blocked writer can only delay its own client.
        if event == "booking.updated":
            key = payload["booking_key"]
            previous = self._booking_batch.get(key)
            if previous is None or payload["version"] > previous["version"]:
                self._booking_batch[key] = payload
            if self._batch_task is None or self._batch_task.done():
                self._batch_task = asyncio.create_task(self._flush_bookings())
            return
        self.emit(event, payload)

    async def _flush_bookings(self) -> None:
        await asyncio.sleep(0.1)
        batch, self._booking_batch = self._booking_batch, {}
        for payload in batch.values():
            self.emit("booking.updated", payload)

    async def send_user(self, user_id: int, event: str, payload: dict) -> None:
        self.emit(event, payload, user_id)
        if event == "notification.new" and self.push is not None:
            self.push.enqueue(user_id, payload)

    @staticmethod
    def logout_frame(reason: str) -> dict:
        message = (
            "Your account was signed in on another device."
            if reason in {"new_login", "session_replaced"}
            else "Your session has ended. Please sign in again."
        )
        return ForceLogoutFrame(data={"reason": reason, "message": message}).model_dump(mode="json")

    async def force_logout(self, user_id: int, session_id: str, reason: str) -> None:
        connection = self.connections.get(user_id)
        if connection is not None and connection.user.session_id == session_id:
            self.retire(connection, 4401, self.logout_frame(reason))

    async def connect(
        self, socket: WebSocket, user: CurrentUser, claims: TokenClaims
    ) -> Connection:
        async with asyncio.timeout(self.settings.ws_send_timeout_seconds):
            await socket.accept()
        connection = Connection(
            socket, user, claims, asyncio.Queue(self.settings.ws_queue_size), last_pong=self.clock()
        )
        old = self.connections.get(user.id)
        if old is not None and old.user.session_id != user.session_id:
            self.retire(old, 4401, self.logout_frame("session_replaced"))
        elif old is not None:
            self.locks.transfer(old, connection)
        snapshot = self.locks.snapshot()
        self.connections[user.id] = connection
        self._all[connection.id] = connection
        self._offer(connection, {"event": "lock.snapshot", "data": {"locks": snapshot}})
        if user.role == "admin" and self.health_status is not None:
            self._offer(
                connection, {"event": "system.health", "data": {"degraded": self.health_status()}}
            )
        connection.writer = asyncio.create_task(
            self._write(connection), name=f"ws-writer:{user.id}"
        )
        connection.heartbeat = asyncio.create_task(
            self._heartbeat(connection), name=f"ws-heartbeat:{user.id}"
        )
        if old is not None and not old.closing:
            self.retire(old, 4409)
        return connection

    async def _write(self, connection: Connection) -> None:
        code = 1000
        try:
            while True:
                outgoing = await connection.queue.get()
                try:
                    if outgoing.frame is not None:
                        async with asyncio.timeout(self.settings.ws_send_timeout_seconds):
                            await connection.socket.send_json(outgoing.frame)
                    if outgoing.close_code is not None:
                        code = outgoing.close_code
                        break
                finally:
                    connection.queue.task_done()
        except TimeoutError:
            code = 4408
            logger.warning("WebSocket send timeout user_id=%s", connection.user.id)
        except asyncio.CancelledError:
            code = 1001
            raise
        except Exception as exc:
            code = 1011
            logger.warning(
                "WebSocket send failed user_id=%s (%s)", connection.user.id, type(exc).__name__
            )
        finally:
            self._detach(connection)
            connection.closing = True
            try:
                async with asyncio.timeout(self.settings.ws_send_timeout_seconds):
                    await connection.socket.close(code=code)
            except Exception:
                pass
            finally:
                connection.finished.set()
                self._all.pop(connection.id, None)

    async def verify(self, connection: Connection) -> bool:
        if not self.current(connection):
            return False
        if connection.claims.exp <= datetime.now(UTC).timestamp():
            self.retire(connection, 4401, self.logout_frame("token_expired"))
            return False
        if self.auth is not None:
            try:
                await self.auth.authenticate(connection.claims)
            except ApiException as exc:
                if exc.code in {ErrorCode.UNAUTHORIZED, ErrorCode.SESSION_REPLACED}:
                    self.retire(
                        connection,
                        4401,
                        self.logout_frame(
                            "session_replaced"
                            if exc.code == ErrorCode.SESSION_REPLACED
                            else "session_revoked"
                        ),
                    )
                else:
                    self.retire(connection, 1013)
                return False
        return self.current(connection)

    async def _heartbeat(self, connection: Connection) -> None:
        try:
            while self.current(connection):
                remaining = self.settings.ws_idle_timeout_seconds - (
                    self.clock() - connection.last_pong
                )
                if remaining <= 0:
                    self.retire(connection, 4408)
                    return
                delay = min(self.settings.ws_ping_interval_seconds, remaining)
                try:
                    await asyncio.wait_for(connection.finished.wait(), delay)
                    return
                except TimeoutError:
                    pass
                if not self.current(connection):
                    return
                if self.clock() - connection.last_pong >= self.settings.ws_idle_timeout_seconds:
                    self.retire(connection, 4408)
                    return
                if await self.verify(connection):
                    self.emit("ping", {}, connection.user.id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "WebSocket heartbeat failed user_id=%s (%s)", connection.user.id, type(exc).__name__
            )
            self.retire(connection, 1011)

    def spawn(self, work: Coroutine[Any, Any, None]) -> None:
        if self.stopping:
            work.close()
            return
        task = asyncio.create_task(work, name="ws-post-commit")
        self._background.add(task)
        task.add_done_callback(self._background_done)

    def _background_done(self, task: asyncio.Task) -> None:
        self._background.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                "WebSocket post-commit dispatch failed (%s)", type(task.exception()).__name__
            )

    async def _saved(
        self, booking: dict, notification: tuple[int, dict] | list[tuple[int, dict]] | None
    ) -> None:
        await self.broadcast("booking.updated", booking)
        if notification:
            events = notification if isinstance(notification, list) else [notification]
            await asyncio.gather(
                *(
                    self.send_user(user_id, "notification.new", payload)
                    for user_id, payload in events
                )
            )

    def saved(
        self,
        user_id: int,
        session_id: str,
        booking: dict,
        notification: tuple[int, dict] | list[tuple[int, dict]] | None,
    ) -> None:
        self.locks.release(user_id, booking["booking_key"], session_id=session_id)
        # Owned background work survives cancellation of the committed HTTP request.
        self.spawn(self._saved(booking, notification))

    async def disconnect(self, connection: Connection) -> None:
        self.retire(connection)
        try:
            async with asyncio.timeout(self.settings.ws_send_timeout_seconds * 2 + 1):
                await connection.finished.wait()
        finally:
            if connection.heartbeat:
                connection.heartbeat.cancel()
                await asyncio.gather(connection.heartbeat, return_exceptions=True)

    async def stop(self) -> None:
        self.stopping = True
        if self._batch_task is not None:
            self._batch_task.cancel()
            await asyncio.gather(self._batch_task, return_exceptions=True)
        self._booking_batch.clear()
        connections = list(self._all.values())
        for connection in connections:
            self.retire(connection, 1001)
        await asyncio.gather(*(self.disconnect(c) for c in connections), return_exceptions=True)
        tasks = list(self._background)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
