import asyncio
import math
import time
import unicodedata
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from app.core.errors import ApiException
from app.schemas.contracts import ErrorCode


def normalized_username(value: str) -> str:
    # Coalesce common case/accent aliases accepted by utf8mb4_unicode_ci.
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


@dataclass
class AttemptState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    failures: deque[float] = field(default_factory=deque)
    blocked_until: float = 0
    references: int = 0


class LoginAttempt:
    def __init__(self, state: AttemptState, limiter: "LoginLimiter") -> None:
        self.state = state
        self.limiter = limiter

    def failed(self) -> None:
        now = self.limiter.clock()
        self.state.failures.append(now)
        if len(self.state.failures) >= self.limiter.max_failures:
            self.state.blocked_until = now + self.limiter.seconds

    def succeeded(self) -> None:
        self.state.failures.clear()
        self.state.blocked_until = 0


class LoginLimiter:
    def __init__(
        self,
        max_failures: int = 5,
        seconds: int = 300,
        max_entries: int = 10000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.seconds = seconds
        self.max_entries = max_entries
        self.clock = clock
        self._entries: dict[tuple[str, str], AttemptState] = {}

    def _expire(self, state: AttemptState, now: float) -> None:
        while state.failures and state.failures[0] <= now - self.seconds:
            state.failures.popleft()
        if state.blocked_until and state.blocked_until <= now:
            state.blocked_until = 0
            state.failures.clear()

    @asynccontextmanager
    async def attempt(self, ip: str, username: str) -> AsyncIterator[LoginAttempt]:
        now = self.clock()
        key = (ip, normalized_username(username))
        if key not in self._entries and len(self._entries) >= self.max_entries:
            for existing, state in list(self._entries.items()):
                self._expire(state, now)
                if not state.references and not state.failures and not state.blocked_until:
                    del self._entries[existing]
            # Do not evict a live blocked entry: eviction would permit a lockout bypass.
            if len(self._entries) >= self.max_entries:
                raise ApiException(
                    ErrorCode.RATE_LIMITED, headers={"Retry-After": str(self.seconds)}
                )
        state = self._entries.setdefault(key, AttemptState())
        state.references += 1
        try:
            async with state.lock:
                now = self.clock()
                self._expire(state, now)
                if state.blocked_until > now:
                    retry = max(1, math.ceil(state.blocked_until - now))
                    raise ApiException(ErrorCode.RATE_LIMITED, headers={"Retry-After": str(retry)})
                yield LoginAttempt(state, self)
        finally:
            state.references -= 1
            if not state.references and not state.failures and not state.blocked_until:
                self._entries.pop(key, None)
