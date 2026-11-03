"""Bounded snapshot-only cache. A generation prevents repopulation by stale reads."""

import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime

from app.schemas.bookings import BookingItem


@dataclass
class Entry:
    snapshot: BookingItem
    group_id: int
    stale_after_hours: int
    expires: float


class SnapshotCache:
    def __init__(self, capacity: int = 2000, ttl: float = 30) -> None:
        self.capacity, self.ttl = capacity, ttl
        self.generation = 0
        self.hits = 0
        self.misses = 0
        self.items: OrderedDict[int, Entry] = OrderedDict()

    def get(self, booking_id: int) -> BookingItem | None:
        item = self.items.get(booking_id)
        if item is None:
            self.misses += 1
            return None
        if item.expires <= time.monotonic():
            self.items.pop(booking_id, None)
            self.misses += 1
            return None
        self.hits += 1
        self.items.move_to_end(booking_id)
        result = item.snapshot.model_copy(deep=True)
        age = (datetime.now(UTC) - result.updated_at).total_seconds() / 3600
        result.is_stale = not result.is_done and age >= item.stale_after_hours
        result.stale_hours = round(age, 3) if result.is_stale else None
        return result

    def put(
        self, booking_id: int, snapshot: BookingItem, group_id: int, hours: int, generation: int
    ) -> None:
        if generation != self.generation:
            return
        self.items[booking_id] = Entry(
            snapshot.model_copy(deep=True), group_id, hours, time.monotonic() + self.ttl
        )
        self.items.move_to_end(booking_id)
        while len(self.items) > self.capacity:
            self.items.popitem(last=False)

    def invalidate(self, booking_id: int) -> None:
        self.generation += 1
        self.items.pop(booking_id, None)

    def invalidate_group(self, group_id: int) -> None:
        self.generation += 1
        for key in [key for key, item in self.items.items() if item.group_id == group_id]:
            self.items.pop(key, None)

    def clear(self) -> None:
        self.generation += 1
        self.items.clear()
