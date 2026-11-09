"""Process-local exact/partial index with keyset bootstrap and periodic reconciliation."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup
from app.schemas.bookings import GroupInfo
from app.utils.folder_key import folder_key
from app.utils.supplier import normalize_supplier_name

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
    last_activity_at: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=UTC))
    normalized_name: str = field(init=False)
    words: tuple[str, ...] = field(init=False)
    activity_order: float = field(init=False)

    def __post_init__(self) -> None:
        normalized = normalize_supplier_name(self.info.supplier_name)
        object.__setattr__(self, "normalized_name", normalized)
        object.__setattr__(self, "words", tuple(normalized.split()))
        object.__setattr__(self, "activity_order", -self.last_activity_at.timestamp())


class KeyIndex:
    def __init__(
        self, engine, settings: Settings, cache, on_group_created: Callable[[], None] | None = None
    ) -> None:
        self.engine, self.settings, self.cache = engine, settings, cache
        self.on_group_created = on_group_created
        self.ready = False
        self.keys: dict[str, KeyEntry] = {}
        self.partial: dict[tuple[str, str], dict[str, KeyEntry]] = {}
        self.groups: dict[str, GroupEntry] = {}
        self.cw_groups: dict[str, dict[str, GroupEntry]] = {}
        self._pending_keys: dict[str, KeyEntry] = {}
        self._pending_groups: dict[str, GroupEntry] = {}
        self._loading = False
        self._task: asyncio.Task | None = None
        self._signature = None

    @property
    def usable(self) -> bool:
        return self.settings.key_index_enabled and self.ready

    def update(self, entry: KeyEntry | None, group: GroupEntry) -> None:
        identity = folder_key(group.info.cw_number, group.info.station_code)
        if identity not in self.groups and self.on_group_created is not None:
            self.on_group_created()
        if not self.settings.key_index_enabled:
            return
        if entry:
            self.keys[entry.key] = entry
            self.partial.setdefault((entry.cw_number, entry.period), {})[entry.key] = entry
        self.groups[identity] = group
        self.cw_groups.setdefault(group.info.cw_number, {})[group.info.station_code] = group
        if self._loading:
            if entry:
                self._pending_keys[entry.key] = entry
            self._pending_groups[identity] = group

    def group(self, cw: str, station: str | None = None) -> GroupEntry | None:
        if station:
            exact = self.groups.get(folder_key(cw, station))
            if exact:
                return exact
        matches = list(self.cw_groups.get(cw, {}).values())
        return matches[0] if len(matches) == 1 else None

    def matching_groups(
        self,
        query: str = "",
        *,
        station_code: str | None = None,
        supplier_type: str | None = None,
        cw_prefix: str | None = None,
        rank: bool = True,
    ) -> list[GroupEntry]:
        normalized = normalize_supplier_name(query)
        tokens = tuple(set(normalized.split()))
        matches = []
        for group in self.groups.values():
            if station_code is not None and group.info.station_code != station_code:
                continue
            if supplier_type is not None and group.info.supplier_type != supplier_type:
                continue
            if cw_prefix is not None and not group.info.cw_number.startswith(cw_prefix):
                continue
            if any(not any(word.startswith(token) for word in group.words) for token in tokens):
                continue
            score = (
                0
                if not rank or not tokens or group.normalized_name == normalized
                else (1 if group.normalized_name.startswith(normalized) else 2)
            )
            matches.append((score, group.activity_order, -group.id, group))
        matches.sort(key=lambda entry: entry[:3])
        return [entry[3] for entry in matches]

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
                                BookingGroup.last_activity_at,
                            )
                            .where(BookingGroup.id > last)
                            .order_by(BookingGroup.id)
                            .limit(self.settings.key_index_batch_size)
                        )
                    ).all()
                if not rows:
                    break
                for row in rows:
                    groups[folder_key(row.cw_number, row.station_code)] = GroupEntry(
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
                        row.last_activity_at,
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
            self.cw_groups = {}
            for group in groups.values():
                self.cw_groups.setdefault(group.info.cw_number, {})[group.info.station_code] = group
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
