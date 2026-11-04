"""Folder cards and search: page-wide aggregates, indexed key branches, one shared RAM index."""

import re
from datetime import UTC, datetime

from sqlalchemy import String, and_, case, cast, func, or_, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import aliased

from app.core.errors import ApiException
from app.core.timeouts import request_budget
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, BookingInvoice, Status, User
from app.schemas.contracts import ErrorCode, FolderCard, MonthRow, Page
from app.schemas.folders import (
    FolderDetail,
    SearchBooking,
    SearchFolder,
    SearchFolders,
    SearchInvoice,
    SearchNone,
    SearchPartial,
    SearchStation,
    SearchStationPeriod,
    StationSection,
)
from app.services.booking_reads import invoice_previews, snapshot_from_row, snapshot_query
from app.utils.booking_key import period_label, to_display
from app.utils.invoice import normalize as normalize_invoice
from app.utils.invoice import validate as valid_invoice
from app.utils.search_query import QueryKind, classify_query
from app.utils.supplier import normalize_supplier_name


def folder_card_query(ids: list[int], stale_hours_default=24):
    # Four period characters followed by a zero-padded unsigned BIGINT identify the
    # latest period and break legacy duplicate-period ties by id, even after backfills.
    latest_order = func.max(
        func.concat(Booking.period, func.lpad(cast(Booking.id, String), 20, "0"))
    )
    activity_status = aliased(Status, name="activity_status")
    stale = and_(
        Booking.is_done.is_(False),
        Booking.updated_at
        <= func.timestampadd(
            text("HOUR"),
            -func.coalesce(activity_status.stale_after_hours, stale_hours_default),
            datetime.now(UTC),
        ),
    )
    stats = (
        select(
            Booking.group_id,
            func.count().label("booking_count"),
            func.sum(case((Booking.is_done.is_(False), 1), else_=0)).label("open_count"),
            func.sum(case((stale, 1), else_=0)).label("stale_count"),
            cast(func.substring(latest_order, 5), mysql.BIGINT(unsigned=True)).label("latest_id"),
        )
        .outerjoin(activity_status, activity_status.id == Booking.last_status_id)
        .where(Booking.group_id.in_(ids))
        .group_by(Booking.group_id)
        .subquery("folder_stats")
    )
    latest = aliased(Booking, name="latest")
    return (
        select(
            BookingGroup.id,
            BookingGroup.cw_number,
            BookingGroup.station_code,
            BookingGroup.supplier_name,
            BookingGroup.supplier_type,
            BookingGroup.last_activity_at,
            stats.c.booking_count,
            stats.c.open_count,
            stats.c.stale_count,
            latest.booking_key,
            latest.period,
            Status.code.label("status_code"),
            Status.label.label("status_label"),
            User.id.label("agent_id"),
            User.full_name.label("agent_name"),
        )
        .outerjoin(stats, stats.c.group_id == BookingGroup.id)
        .outerjoin(latest, latest.id == stats.c.latest_id)
        .outerjoin(Status, Status.id == latest.last_status_id)
        .outerjoin(User, User.id == latest.last_agent_id)
        .where(BookingGroup.id.in_(ids))
    )


def safe_period_label(period: str) -> str:
    if not re.fullmatch(r"[0-9]{2}(0[1-9]|1[0-2])", period, re.ASCII):
        return period
    return period_label(period)


async def folder_cards(session, ids: list[int], stale_hours_default=24) -> list[FolderCard]:
    if not ids:
        return []
    rows = (await session.execute(folder_card_query(ids, stale_hours_default))).all()
    cards = {}
    for r in rows:
        latest = None
        if r.booking_key:
            latest = {
                "booking_key": r.booking_key,
                "display_key": to_display(r.booking_key),
                "period_label": safe_period_label(r.period),
                "status": {"code": r.status_code, "label": r.status_label}
                if r.status_code
                else None,
                "agent": {"id": r.agent_id, "full_name": r.agent_name} if r.agent_id else None,
            }
        cards[r.id] = FolderCard(
            cw_number=r.cw_number,
            supplier_name=r.supplier_name,
            supplier_type=r.supplier_type,
            station_code=r.station_code,
            booking_count=r.booking_count or 0,
            open_count=r.open_count or 0,
            stale_count=r.stale_count or 0,
            last_activity_at=r.last_activity_at,
            latest=latest,
        )
    return [cards[identifier] for identifier in ids if identifier in cards]


async def month_rows(session, group_id: int, settings) -> list[MonthRow]:
    rows = (
        await session.execute(
            select(
                Booking.booking_key,
                Booking.period,
                Booking.last_position,
                Booking.is_done,
                Booking.updated_at,
                Booking.invoice_state,
                Booking.invoice_count,
                Status.code.label("status_code"),
                Status.label.label("status_label"),
                Status.stale_after_hours,
                User.id.label("agent_id"),
                User.full_name.label("agent_name"),
            )
            .outerjoin(Status, Status.id == Booking.last_status_id)
            .outerjoin(User, User.id == Booking.last_agent_id)
            .where(Booking.group_id == group_id)
            .order_by(Booking.period.desc(), Booking.id.desc())
        )
    ).all()
    now = datetime.now(UTC)
    return [
        MonthRow(
            booking_key=r.booking_key,
            display_key=to_display(r.booking_key),
            period=r.period,
            period_label=safe_period_label(r.period),
            last_status={"code": r.status_code, "label": r.status_label} if r.status_code else None,
            last_position=r.last_position,
            last_agent={"id": r.agent_id, "full_name": r.agent_name} if r.agent_id else None,
            is_done=r.is_done,
            is_stale=not r.is_done
            and (now - r.updated_at).total_seconds()
            >= (
                r.stale_after_hours
                if r.stale_after_hours is not None
                else settings.stale_hours_default
            )
            * 3600,
            updated_at=r.updated_at,
            invoice_state=r.invoice_state,
            invoice_count=r.invoice_count,
        )
        for r in rows
    ]


class FolderService:
    def __init__(self, engine, settings, index, bookings, stations):
        self.engine, self.settings, self.index = engine, settings, index
        self.bookings, self.stations = bookings, stations

    def tx(self):
        return transaction(
            self.engine, self.settings, seconds=self.settings.search_db_timeout_seconds
        )

    async def detail(self, cw: str, station_code: str | None = None) -> FolderDetail:
        if not re.fullmatch(r"CW[0-9]{5,10}", cw, re.ASCII):
            raise ApiException(ErrorCode.INVALID_BOOKING_KEY)
        async with self.tx() as session:
            if self.index.usable:
                entry = self.index.groups.get(cw)
                identifier = (
                    entry.id
                    if entry and (station_code is None or entry.info.station_code == station_code)
                    else None
                )
            else:
                conditions = [BookingGroup.cw_number == cw]
                if station_code is not None:
                    conditions.append(BookingGroup.station_code == station_code)
                identifier = await session.scalar(select(BookingGroup.id).where(*conditions))
            if identifier is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            cards = await folder_cards(session, [identifier], self.settings.stale_hours_default)
            if not cards:
                raise ApiException(ErrorCode.NOT_FOUND)
            months = await month_rows(session, identifier, self.settings)
        return FolderDetail(folder=cards[0], months=months)

    async def page(
        self,
        *,
        page=1,
        size=20,
        station_code=None,
        supplier_type=None,
        supplier_query: str | None = None,
        cw_prefix=None,
        exact_cw=None,
        rank=False,
    ):
        if supplier_query is not None and not normalize_supplier_name(supplier_query):
            return Page(items=[], total=0, page=page, size=size)
        if self.index.usable and (
            supplier_query is not None or cw_prefix is not None or exact_cw is not None
        ):
            matches = self.index.matching_groups(
                supplier_query or "",
                station_code=station_code,
                supplier_type=supplier_type,
                cw_prefix=exact_cw or cw_prefix,
                rank=rank,
            )
            if exact_cw:
                matches = [entry for entry in matches if entry.info.cw_number == exact_cw]
            total = len(matches)
            ids = [e.id for e in matches[(page - 1) * size : page * size]]
            if not ids:
                return Page(items=[], total=total, page=page, size=size)
            async with self.tx() as session:
                items = await folder_cards(session, ids, self.settings.stale_hours_default)
            return Page(items=items, total=total, page=page, size=size)
        conditions = []
        if station_code is not None:
            conditions.append(BookingGroup.station_code == station_code)
        if supplier_type is not None:
            conditions.append(BookingGroup.supplier_type == supplier_type)
        if exact_cw is not None:
            conditions.append(BookingGroup.cw_number == exact_cw)
        elif cw_prefix is not None:
            conditions.append(BookingGroup.cw_number.startswith(cw_prefix, autoescape=True))
        order = []
        if supplier_query is not None:
            normalized = normalize_supplier_name(supplier_query)
            name = BookingGroup.supplier_name_normalized
            for token in set(normalized.split()):
                conditions.append(
                    or_(
                        name.startswith(token, autoescape=True),
                        name.contains(" " + token, autoescape=True),
                    )
                )
            if rank:
                order.append(
                    case(
                        (name == normalized, 0),
                        (name.startswith(normalized, autoescape=True), 1),
                        else_=2,
                    )
                )
        order.extend([BookingGroup.last_activity_at.desc(), BookingGroup.id.desc()])
        async with self.tx() as session:
            total = await session.scalar(
                select(func.count()).select_from(BookingGroup).where(*conditions)
            )
            ids = list(
                (
                    await session.scalars(
                        select(BookingGroup.id)
                        .where(*conditions)
                        .order_by(*order)
                        .offset((page - 1) * size)
                        .limit(size)
                    )
                ).all()
            )
            items = await folder_cards(session, ids, self.settings.stale_hours_default)
        return Page(items=items, total=total, page=page, size=size)

    async def listing(self, query: str = "", **filters):
        if not query.strip():
            return await self.page(**filters)
        classified = classify_query(query, station_pattern=self.settings.station_code_pattern)
        if classified.kind in {QueryKind.CW_NUMBER, QueryKind.CW_PREFIX}:
            if classified.station_code:
                if filters.get("station_code") not in {None, classified.station_code}:
                    return Page(items=[], total=0, page=filters["page"], size=filters["size"])
                filters["station_code"] = classified.station_code
            return await self.page(
                **filters,
                **{
                    "exact_cw"
                    if classified.kind == QueryKind.CW_NUMBER
                    else "cw_prefix": classified.cw_number
                },
            )
        if classified.kind != QueryKind.TEXT:
            return Page(items=[], total=0, page=filters["page"], size=filters["size"])
        return await self.page(**filters, supplier_query=classified.query)

    async def station_period(self, station_code: str, period: str, page: int, size: int):
        station = await self.stations.find(station_code)
        if station is None:
            return None
        where = and_(Booking.station_code == station_code, Booking.period == period)
        async with self.tx() as session:
            total = await session.scalar(select(func.count()).select_from(Booking).where(where))
            rows = (
                await session.execute(
                    snapshot_query()
                    .where(where)
                    .order_by(Booking.id.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
            previews = await invoice_previews(session, [r.id for r in rows])
        return SearchStationPeriod(
            query=f"{station_code}-{period}",
            station=station,
            period=period,
            period_label=period_label(period),
            items=[snapshot_from_row(r, self.settings, previews.get(r.id)) for r in rows],
            total=total,
            page=page,
            size=size,
        )

    async def invoice_search(self, raw, page, size):
        value = normalize_invoice(raw)
        if not valid_invoice(value, self.settings.invoice_number_pattern):
            raise ApiException(ErrorCode.INVOICE_INVALID, details={"invalid": [value]})
        where = Booking.id.in_(
            select(BookingInvoice.booking_id).where(
                BookingInvoice.invoice_number_normalized == value
            )
        )
        async with self.tx() as session:
            total = await session.scalar(select(func.count()).select_from(Booking).where(where))
            rows = (
                await session.execute(
                    snapshot_query()
                    .where(where)
                    .order_by(Booking.updated_at.desc(), Booking.id.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
            previews = await invoice_previews(session, [r.id for r in rows])
        return SearchInvoice(
            query=raw,
            items=[
                {
                    **snapshot_from_row(r, self.settings, previews.get(r.id)).model_dump(),
                    "matched_invoice": value,
                }
                for r in rows
            ],
            total=total,
            page=page,
            size=size,
        )

    async def search(self, raw: str, *, page: int, size: int):
        # A separate 3 s budget bounds the entire DB fallback, not just one statement.
        async with request_budget(self.settings.search_db_timeout_seconds):
            classified = classify_query(raw, station_pattern=self.settings.station_code_pattern)
            if classified.kind == QueryKind.TEXT and re.fullmatch(
                self.settings.station_code_pattern, classified.query, re.ASCII
            ):
                classified = classify_query(
                    raw,
                    {r.code for r in await self.stations.all()},
                    self.settings.station_code_pattern,
                )
            match classified.kind:
                case QueryKind.INVOICE:
                    return await self.invoice_search(
                        classified.query[4:]
                        if classified.query.startswith("INV:")
                        else classified.query[1:],
                        page,
                        size,
                    )
                case QueryKind.FULL_KEY:
                    resolution, entry, group, _ = await self.bookings.resolve(classified.query)
                    return SearchBooking(
                        query=classified.query,
                        booking_key=resolution.key,
                        display_key=resolution.display_key,
                        exists=entry is not None,
                        group=group.info if group else None,
                    )
                case QueryKind.PARTIAL_KEY:
                    resolution, _, _, _ = await self.bookings.resolve(classified.query)
                    return SearchPartial(query=classified.query, resolution=resolution)
                case QueryKind.CW_NUMBER:
                    try:
                        folder = await self.detail(classified.cw_number, classified.station_code)
                    except ApiException as exc:
                        if exc.code != ErrorCode.NOT_FOUND:
                            raise
                        return SearchNone(query=classified.query)
                    return SearchFolder(query=classified.query, **folder.model_dump())
                case QueryKind.CW_PREFIX | QueryKind.TEXT:
                    result = await self.page(
                        page=page,
                        size=size,
                        supplier_query=classified.query
                        if classified.kind == QueryKind.TEXT
                        else None,
                        cw_prefix=classified.cw_number,
                        station_code=classified.station_code,
                        rank=True,
                    )
                    if not result.total:
                        if classified.kind == QueryKind.TEXT and valid_invoice(
                            normalize_invoice(classified.query),
                            self.settings.invoice_number_pattern,
                        ):
                            invoices = await self.invoice_search(classified.query, page, size)
                            return (
                                invoices if invoices.total else SearchNone(query=classified.query)
                            )
                        return SearchNone(query=classified.query)
                    return SearchFolders(query=classified.query, **result.model_dump())
                case QueryKind.STATION:
                    station = await self.stations.find(classified.station_code)
                    result = await self.page(
                        page=page, size=size, station_code=classified.station_code
                    )
                    sections = [
                        StationSection(
                            type=kind,
                            items=[item for item in result.items if item.supplier_type == kind],
                        )
                        for kind in ("hotel", "transportation")
                    ]
                    return SearchStation(
                        query=classified.query,
                        station=station,
                        sections=sections,
                        total=result.total,
                        page=page,
                        size=size,
                    )
                case QueryKind.STATION_PERIOD:
                    return await self.station_period(
                        classified.station_code, classified.period, page, size
                    ) or SearchNone(query=classified.query)
                case _:
                    return SearchNone(query=classified.query)
