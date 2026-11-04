import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field

from pydantic import JsonValue

from app.models import User
from app.schemas.auth import PublicUser, UserRole


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    full_name: str
    role: UserRole
    is_active: bool
    session_id: str | None = field(repr=False)
    settings: dict[str, JsonValue] | None = field(repr=False)

    must_change_password: bool = False

    @classmethod
    def from_model(cls, user: User) -> "CurrentUser":
        return cls(
            user.id,
            user.username,
            user.full_name,
            user.role,
            user.is_active,
            user.current_session_id,
            deepcopy(user.settings),
            user.must_change_password,
        )

    def public(self) -> PublicUser:
        return PublicUser(
            id=self.id,
            username=self.username,
            full_name=self.full_name,
            role=self.role,
            is_active=self.is_active,
            settings=deepcopy(self.settings),
            must_change_password=self.must_change_password,
        )


class SessionCache:
    def __init__(
        self,
        ttl: float = 12,
        max_entries: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self.clock = clock
        self._entries: OrderedDict[int, tuple[float, CurrentUser | None]] = OrderedDict()
        # Fixed stripes bound lock memory and serialize reads against same-user mutations.
        self._locks = [asyncio.Lock() for _ in range(64)]

    def lock(self, user_id: int) -> asyncio.Lock:
        return self._locks[user_id % len(self._locks)]

    def get(self, user_id: int) -> tuple[bool, CurrentUser | None]:
        cached = self._entries.get(user_id)
        if cached is None:
            return False, None
        expires, principal = cached
        if expires <= self.clock():
            self._entries.pop(user_id, None)
            return False, None
        self._entries.move_to_end(user_id)
        return True, principal

    def set(self, user_id: int, principal: CurrentUser | None) -> None:
        self._entries[user_id] = (self.clock() + self.ttl, principal)
        self._entries.move_to_end(user_id)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def invalidate(self, user_id: int) -> None:
        self._entries.pop(user_id, None)
