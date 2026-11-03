"""Advisory leases for ONE event loop/instance. Use Redis pub/sub before scaling."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.schemas.realtime import LockHolder, LockInfo
from app.utils.booking_key import to_display


@dataclass
class Lease:
    info: LockInfo
    deadline: float
    connection_id: str
    session_id: str


class LockManager:
    def __init__(self, emit: Callable, ttl: float = 150):
        self.emit, self.ttl = emit, ttl
        self.clock = time.monotonic
        self.now = lambda: datetime.now(UTC)
        self.locks: dict[str, Lease] = {}
        self.by_user: dict[int, str] = {}

    def _holder(self, lease: Lease) -> dict:
        return LockHolder.model_validate(lease.info.model_dump(exclude={"expires_at"})).model_dump(
            mode="json"
        )

    def _remove(self, key: str) -> None:
        lease = self.locks.pop(key, None)
        if lease is not None:
            self.by_user.pop(lease.info.user_id, None)
            self.emit("lock.released", self._holder(lease), None)

    def expire(self) -> None:
        now = self.clock()
        for key in [key for key, lease in self.locks.items() if lease.deadline <= now]:
            self._remove(key)

    async def sweep(self) -> None:
        self.expire()

    def snapshot(self) -> list[dict]:
        self.expire()
        return [lease.info.model_dump(mode="json") for _, lease in sorted(self.locks.items())]

    def acquire(self, connection, key: str) -> bool:
        self.expire()
        old = self.by_user.get(connection.user.id)
        if old and old != key:
            self._remove(old)
        lease = self.locks.get(key)
        if lease and lease.info.user_id != connection.user.id:
            self.emit("lock.denied", self._holder(lease), connection.user.id)
            return False
        info = LockInfo(
            booking_key=key,
            display_key=to_display(key),
            user_id=connection.user.id,
            user_name=connection.user.full_name,
            expires_at=self.now() + timedelta(seconds=self.ttl),
        )
        lease = Lease(info, self.clock() + self.ttl, connection.id, connection.user.session_id)
        self.locks[key] = lease
        self.by_user[connection.user.id] = key
        self.emit("lock.acquired", self._holder(lease), None)
        return True

    def heartbeat(self, connection, key: str) -> bool:
        self.expire()
        lease = self.locks.get(key)
        if (
            lease
            and lease.info.user_id == connection.user.id
            and lease.connection_id == connection.id
        ):
            lease.deadline = self.clock() + self.ttl
            lease.info.expires_at = self.now() + timedelta(seconds=self.ttl)
            return True
        if lease:
            self.emit("lock.denied", self._holder(lease), connection.user.id)
        return False

    def release(
        self,
        user_id: int,
        key: str,
        *,
        session_id: str | None = None,
        connection_id: str | None = None,
    ) -> None:
        lease = self.locks.get(key)
        if (
            lease
            and lease.info.user_id == user_id
            and (session_id is None or lease.session_id == session_id)
            and (connection_id is None or lease.connection_id == connection_id)
        ):
            self._remove(key)

    def disconnect(self, connection) -> None:
        key = self.by_user.get(connection.user.id)
        if key:
            self.release(connection.user.id, key, connection_id=connection.id)

    def transfer(self, old_connection, new_connection) -> None:
        key = self.by_user.get(old_connection.user.id)
        lease = self.locks.get(key)
        if lease and lease.connection_id == old_connection.id:
            lease.connection_id = new_connection.id
