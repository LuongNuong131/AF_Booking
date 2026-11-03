import asyncio
import hashlib
import json
import re
import time

from sqlalchemy import func, select

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import BookingGroup, Station, User
from app.schemas.contracts import ErrorCode
from app.schemas.folders import StationInfo, StationOption, StationPatch
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.utils.supplier import normalize_supplier_name
from app.utils.text import clean_note


class StationService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self._rows: tuple[StationOption, ...] | None = None
        self._expires = 0.0
        self._generation = 0
        self._lock = asyncio.Lock()
        self.clock = time.monotonic

    def invalidate(self) -> None:
        self._generation += 1
        self._rows = None
        self._expires = 0

    async def all(self) -> tuple[StationOption, ...]:
        if self._rows is not None and self.clock() < self._expires:
            return self._rows
        async with self._lock:
            if self._rows is not None and self.clock() < self._expires:
                return self._rows
            generation = self._generation
            async with transaction(
                self.engine, self.settings, seconds=self.settings.search_db_timeout_seconds
            ) as session:
                rows = (
                    await session.execute(
                        select(
                            Station.code,
                            Station.name,
                            func.count(BookingGroup.id).label("folder_count"),
                        )
                        .outerjoin(BookingGroup, BookingGroup.station_code == Station.code)
                        .group_by(Station.code, Station.name)
                        .order_by(Station.code)
                    )
                ).all()
            result = tuple(
                StationOption(code=r.code, name=r.name, folder_count=r.folder_count) for r in rows
            )
            if generation == self._generation:
                self._rows, self._expires = (
                    result,
                    self.clock() + self.settings.station_cache_ttl_seconds,
                )
            return result

    async def find(self, code: str) -> StationInfo | None:
        row = next((r for r in await self.all() if r.code == code), None)
        return StationInfo(code=row.code, name=row.name) if row else None

    async def autocomplete(self, query: str) -> tuple[list[StationOption], str]:
        normalized = normalize_supplier_name(query)
        tokens = normalized.split()
        rows = [
            r.model_copy()
            for r in await self.all()
            if r.code.startswith(query.strip().upper())
            or (
                tokens
                and all(
                    any(
                        word.startswith(t) for word in normalize_supplier_name(r.name or "").split()
                    )
                    for t in tokens
                )
            )
        ]
        rows.sort(key=lambda row: (not row.code.startswith(query.strip().upper()), row.code))
        data = json.dumps(
            [r.model_dump(mode="json") for r in rows], sort_keys=True, separators=(",", ":")
        )
        return rows, '"' + hashlib.sha256(data.encode()).hexdigest() + '"'

    async def rename(self, code: str, body: StationPatch, user, context) -> StationInfo:
        if not re.fullmatch(self.settings.station_code_pattern, code, re.ASCII) or len(code) > 4:
            raise ApiException(ErrorCode.VALIDATION_ERROR)
        name = clean_note(body.name)
        if name is not None:
            name = " ".join(name.split())
        async with transaction(self.engine, self.settings, after_commit=self.invalidate) as session:
            live = await session.scalar(select(User).where(User.id == user.id).with_for_update())
            AuthService.require_live_row(live, user)
            if live.role != "admin":
                raise ApiException(ErrorCode.FORBIDDEN)
            station = await session.scalar(
                select(Station).where(Station.code == code).with_for_update()
            )
            if station is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            station.name = name
            record_audit(
                session,
                "station_updated",
                actor_id=user.id,
                context=context,
                meta={"station_code": code},
            )
        return StationInfo(code=code, name=name)
