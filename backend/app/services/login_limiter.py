import asyncio
import math
import time
import unicodedata
from collections import deque
from collections.abc import Callable
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
    def __init__(self, states, limiter):
        self.states, self.limiter = states, limiter

    def failed(self):
        now = self.limiter.clock()
        for _, state in self.states:
            state.failures.append(now)
            if len(state.failures) >= self.limiter.max_failures:
                state.blocked_until = now + self.limiter.seconds

    def succeeded(self):
        # A successful credential must not erase an attack's per-IP history.
        for kind, state in self.states:
            if kind == "user":
                state.failures.clear()
                state.blocked_until = 0


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

    def check_ip(self, ip):
        state = self._entries.get(("ip", ip))
        if state is not None:
            self._expire(state, self.clock())
            self.check_blocked(state)

    def check_blocked(self, state):
        if state.blocked_until > self.clock():
            raise ApiException(
                ErrorCode.RATE_LIMITED,
                headers={"Retry-After": str(max(1, math.ceil(state.blocked_until - self.clock())))},
            )

    @asynccontextmanager
    async def attempt(self, ip: str, username: str):
        now = self.clock()
        keys = [("ip", ip), ("user", normalized_username(username))]
        missing = sum(key not in self._entries for key in keys)
        if len(self._entries) + missing > self.max_entries * 2:
            for key, state in list(self._entries.items()):
                self._expire(state, now)
                if not state.references and not state.failures and not state.blocked_until:
                    self._entries.pop(key, None)
            if len(self._entries) + missing > self.max_entries * 2:
                raise ApiException(
                    ErrorCode.RATE_LIMITED, headers={"Retry-After": str(self.seconds)}
                )
        states = [
            (kind, self._entries.setdefault((kind, value), AttemptState())) for kind, value in keys
        ]
        for _, state in states:
            state.references += 1
        try:
            async with states[0][1].lock, states[1][1].lock:
                for _, state in states:
                    self._expire(state, self.clock())
                    self.check_blocked(state)
                yield LoginAttempt(states, self)
        finally:
            for key, (_, state) in zip(keys, states, strict=True):
                state.references -= 1
                if not state.references and not state.failures and not state.blocked_until:
                    self._entries.pop(key, None)
