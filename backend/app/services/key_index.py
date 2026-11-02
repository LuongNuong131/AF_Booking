"""Process-local exact/partial index with keyset bootstrap and periodic reconciliation."""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup
from app.schemas.bookings import GroupInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyEntry:
    id: int
    group_id: int
    key: str
    cw_number: str
    period: str
    station_code: str


@dataclass(frozen=True)
class GroupEntry:
    id: int
    info: GroupInfo


class KeyIndex:
    def __init__(self, engine, settings: Settings, cache) -> None:
        self.engine, self.settings, self.cache = engine, settings, cache
        self.ready = False
        self.keys: dict[str, KeyEntry] = {}
        self.partial: dict[tuple[str, str], dict[str, KeyEntry]] = {}
        self.groups: dict[str, GroupEntry] = {}
        self._pending_keys: dict[str, KeyEntry] = {}
        self._pending_groups: dict[str, GroupEntry] = {}
        self._loading = False
        self._task: asyncio.Task | None = None
        self._signature = None

    @property
    def usable(self) -> bool:
        return self.settings.key_index_enabled and self.ready

    def update(self, entry: KeyEntry | None, group: GroupEntry) -> None:
        if not self.settings.key_index_enabled:
            return
        if entry:
            self.keys[entry.key] = entry
            self.partial.setdefault((entry.cw_number, entry.period), {})[entry.key] = entry
        self.groups[group.info.cw_number] = group
        if self._loading:
            if entry:
                self._pending_keys[entry.key] = entry
            self._pending_groups[group.info.cw_number] = group

    async def signature(self):
        async with transaction(self.engine, self.settings) as session:
            books = (
                await session.execute(select(func.count(Booking.id), func.max(Booking.id)))
            ).one()
            groups = (
                await session.execute(
                    select(
                        func.count(BookingGroup.id),
                        func.max(BookingGroup.id),
                        func.max(BookingGroup.updated_at),
                    )
                )
            ).one()
            return tuple(books) + tuple(groups)

    async def load(self) -> None:
        self._loading = True
        self._pending_keys.clear()
        self._pending_groups.clear()
        try:
            signature = await self.signature()
            keys, groups = {}, {}
            last = 0
            while True:
                async with transaction(self.engine, self.settings) as session:
                    rows = (
                        await session.execute(
                            select(
                                BookingGroup.id,
                                BookingGroup.cw_number,
                                BookingGroup.station_code,
                                BookingGroup.supplier_name,
                                BookingGroup.supplier_type,
                            )
                            .where(BookingGroup.id > last)
                            .order_by(BookingGroup.id)
                            .limit(self.settings.key_index_batch_size)
                        )
                    ).all()
                if not rows:
                    break
                for row in rows:
                    groups[row.cw_number] = GroupEntry(
                        row.id,
                        GroupInfo(
                            **{
                                k: getattr(row, k)
                                for k in (
                                    "cw_number",
                                    "station_code",
                                    "supplier_name",
                                    "supplier_type",
                                )
                            }
                        ),
                    )
                last = rows[-1].id
                await asyncio.sleep(0)
            last = 0
            while True:
                async with transaction(self.engine, self.settings) as session:
                    rows = (
                        await session.execute(
                            select(
                                Booking.id,
                                Booking.group_id,
                                Booking.booking_key,
                                Booking.cw_number,
                                Booking.period,
                                Booking.station_code,
                            )
                            .where(Booking.id > last)
                            .order_by(Booking.id)
                            .limit(self.settings.key_index_batch_size)
                        )
                    ).all()
                if not rows:
                    break
                for row in rows:
                    keys[row.booking_key] = KeyEntry(
                        row.id,
                        row.group_id,
                        row.booking_key,
                        row.cw_number,
                        row.period,
                        row.station_code,
                    )
                last = rows[-1].id
                await asyncio.sleep(0)
            keys.update(self._pending_keys)
            groups.update(self._pending_groups)
            partial: dict[tuple[str, str], dict[str, KeyEntry]] = {}
            for entry in keys.values():
                partial.setdefault((entry.cw_number, entry.period), {})[entry.key] = entry
            self.keys, self.groups, self.partial = keys, groups, partial
            self._signature = signature
            self.cache.clear()
            self.ready = True
        finally:
            self._loading = False
            self._pending_keys.clear()
            self._pending_groups.clear()

    async def run(self) -> None:
        while True:
            try:
                if not self.ready or await self.signature() != self._signature:
                    await self.load()
            except Exception as exc:
                self.ready = False
                logger.warning(
                    "Key index unavailable (%s); using database fallback", type(exc).__name__
                )
            await asyncio.sleep(self.settings.key_index_reconcile_seconds)

    def start(self) -> None:
        if self.settings.key_index_enabled and self.engine is not None:
            self._task = asyncio.create_task(self.run(), name="booking-key-index")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
