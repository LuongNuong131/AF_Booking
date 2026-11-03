"""Bounded process-local sliding window for authenticated search requests."""

import math
import time
from collections import deque

from app.core.errors import ApiException
from app.schemas.contracts import ErrorCode


class SearchLimiter:
    def __init__(self, limit: int = 120, window: float = 60, capacity: int = 10000):
        self.limit, self.window, self.capacity = limit, window, capacity
        self.clock = time.monotonic
        self.entries: dict[int, deque[float]] = {}

    def check(self, user_id: int) -> None:
        now = self.clock()
        if user_id not in self.entries and len(self.entries) >= self.capacity:
            for key, times in list(self.entries.items()):
                if not times or times[-1] <= now - self.window:
                    self.entries.pop(key)
            if len(self.entries) >= self.capacity:
                raise ApiException(
                    ErrorCode.RATE_LIMITED, headers={"Retry-After": str(math.ceil(self.window))}
                )
        times = self.entries.setdefault(user_id, deque())
        while times and times[0] <= now - self.window:
            times.popleft()
        if len(times) >= self.limit:
            raise ApiException(
                ErrorCode.RATE_LIMITED,
                headers={"Retry-After": str(max(1, math.ceil(times[0] + self.window - now)))},
            )
        times.append(now)
