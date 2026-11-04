import base64
import json
import time
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, text

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import (
    Attachment,
    Booking,
    BookingGroup,
    BookingInvoice,
    BookingNote,
    BookingTask,
    BookingWatcher,
    Status,
    User,
)
from app.schemas.bookings import BookingItem, BookingLookup, GroupInfo
from app.schemas.contracts import (
    CursorPage,
    ErrorCode,
    KeyCandidate,
    KeyResolution,
    Note,
    Page,
    Task,
)
from app.services.key_index import GroupEntry, KeyEntry
from app.services.suggestions import Suggestions
from app.utils.booking_key import (
    ParsedKey,
    PartialKey,
    build_key,
    normalize,
    parse,
    period_label,
    to_display,
)
from app.utils.supplier import normalize_supplier_name

SNAPSHOT_COLUMNS = [
    Booking.id,
    Booking.group_id,
    Booking.booking_key,
    Booking.cw_number,
    Booking.station_code,
    Booking.period,
    Booking.version,
    Booking.last_position,
    Booking.last_note_preview,
    Booking.is_done,
    Booking.done_at,
    Booking.updated_at,
    Booking.invoice_state,
    Booking.invoice_count,
    BookingGroup.supplier_name,
    BookingGroup.supplier_type,
    Status.code.label("status_code"),
    Status.label.label("status_label"),
    Status.stale_after_hours,
    User.id.label("agent_id"),
    User.full_name.label("agent_name"),
]


def snapshot_query():
    return (
        select(*SNAPSHOT_COLUMNS)
        .join(BookingGroup, BookingGroup.id == Booking.group_id)
        .outerjoin(Status, Status.id == Booking.last_status_id)
        .outerjoin(User, User.id == Booking.last_agent_id)
    )


def snapshot_from_row(row, settings, previews=None) -> BookingItem:
    hours = (datetime.now(UTC) - row.updated_at).total_seconds() / 3600
    threshold = (
        row.stale_after_hours if row.stale_after_hours is not None else settings.stale_hours_default
    )
    stale = not row.is_done and hours >= threshold
    # Legacy malformed periods remain readable; new writes always pass the key parser.
    try:
        label = period_label(row.period)
    except (ValueError, IndexError):
        label = row.period
    return BookingItem(
        booking_key=row.booking_key,
        display_key=to_display(row.booking_key),
        cw_number=row.cw_number,
        station_code=row.station_code,
        period=row.period,
        period_label=label,
        supplier={"name": row.supplier_name, "type": row.supplier_type},
        supplier_name=row.supplier_name,
        supplier_type=row.supplier_type,
        version=row.version,
        last_status={"code": row.status_code, "label": row.status_label}
        if row.status_code
        else None,
        last_position=row.last_position,
        last_agent={"id": row.agent_id, "full_name": row.agent_name} if row.agent_id else None,
        last_note_preview=row.last_note_preview,
        is_done=row.is_done,
        done_at=row.done_at,
        updated_at=row.updated_at,
        is_stale=stale,
        stale_hours=round(hours, 3) if stale else None,
        invoice_state=row.invoice_state,
        invoice_count=row.invoice_count,
        invoices_preview=previews or [],
    )


def cursor_encode(booking_id: int, note: Note) -> str:
    return (
        base64.urlsafe_b64encode(
            json.dumps([booking_id, note.created_at.isoformat(), note.id]).encode()
        )
        .decode()
        .rstrip("=")
    )


def cursor_decode(cursor: str, booking_id: int) -> tuple[datetime, int]:
    try:
        if len(cursor) > 256:
            raise ValueError
        data = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        owner, timestamp, identifier = data
        moment = datetime.fromisoformat(timestamp)
        if (
            owner != booking_id
            or moment.tzinfo is None
            or type(identifier) is not int
            or identifier < 1
        ):
            raise ValueError
        return moment, identifier
    except (ValueError, TypeError, OverflowError):
        raise ApiException(ErrorCode.VALIDATION_ERROR, message="Invalid history cursor.") from None


async def note_history(
    session, booking_id: int, cursor: str | None = None, limit: int = 20
) -> CursorPage[Note]:
    query = (
        select(
            BookingNote.id,
            BookingNote.position_label,
            BookingNote.note,
            BookingNote.created_at,
            BookingNote.invoice_change,
            User.id.label("agent_id"),
            User.full_name,
            Status.code,
            Status.label,
        )
        .join(User, User.id == BookingNote.agent_id)
        .join(Status, Status.id == BookingNote.status_id)
        .where(BookingNote.booking_id == booking_id, BookingNote.deleted_at.is_(None))
    )
    if cursor:
        created, identifier = cursor_decode(cursor, booking_id)
        query = query.where(
            or_(
                BookingNote.created_at < created,
                and_(BookingNote.created_at == created, BookingNote.id < identifier),
            )
        )
    rows = (
        await session.execute(
            query.order_by(BookingNote.created_at.desc(), BookingNote.id.desc()).limit(limit + 1)
        )
    ).all()
    attachments = {}
    if rows:
        files = (
            await session.execute(
                select(
                    Attachment.note_id,
                    Attachment.id,
                    Attachment.file_name,
                    Attachment.mime_type,
                    Attachment.size_bytes,
                ).where(Attachment.note_id.in_([row.id for row in rows[:limit]]))
            )
        ).all()
        for file in files:
            attachments.setdefault(file.note_id, []).append(
                {
                    "id": file.id,
                    "file_name": file.file_name,
                    "mime_type": file.mime_type,
                    "size_bytes": file.size_bytes,
                }
            )
    items = [
        Note(
            id=row.id,
            agent={"id": row.agent_id, "full_name": row.full_name},
            status={"code": row.code, "label": row.label},
            position=row.position_label,
            note=row.note,
            created_at=row.created_at,
            attachments=attachments.get(row.id, []),
            invoice_change=row.invoice_change,
        )
        for row in rows[:limit]
    ]
    return CursorPage(
        items=items, next_cursor=cursor_encode(booking_id, items[-1]) if len(rows) > limit else None
    )


async def invoice_previews(session, ids: list[int]) -> dict[int, list[str]]:
    if not ids:
        return {}
    ranked = (
        select(
            BookingInvoice.booking_id,
            BookingInvoice.invoice_number,
            func.row_number()
            .over(partition_by=BookingInvoice.booking_id, order_by=BookingInvoice.id)
            .label("rn"),
        )
        .where(BookingInvoice.booking_id.in_(ids))
        .subquery()
    )
    rows = (
        await session.execute(
            select(ranked.c.booking_id, ranked.c.invoice_number)
            .where(ranked.c.rn <= 3)
            .order_by(ranked.c.booking_id, ranked.c.rn)
        )
    ).all()
    result = {}
    for row in rows:
        result.setdefault(row.booking_id, []).append(row.invoice_number)
    return result


def stale_condition(settings):
    return and_(
        Booking.is_done.is_(False),
        Booking.updated_at
        <= func.timestampadd(
            text("HOUR"),
            -func.coalesce(Status.stale_after_hours, settings.stale_hours_default),
            func.utc_timestamp(3),
        ),
    )


class BookingReads:
    def __init__(self, engine, settings, index, cache):
        self.engine, self.settings, self.index, self.cache = engine, settings, index, cache
        self._totals = {}
        self.suggestions = Suggestions(engine, settings, index)

    def tx(self):
        return transaction(self.engine, self.settings)

    async def resolve(self, raw: str):
        parsed = parse(raw, self.settings.station_code_pattern)
        key = parsed.key if isinstance(parsed, ParsedKey) else normalize(raw)
        if self.index.usable:
            entry = self.index.keys.get(key)
            group = (
                self.index.groups.get(parsed.cw_number)
                if parsed
                else (self.index.groups.get(entry.cw_number) if entry else None)
            )
            matches = (
                list(self.index.partial.get((parsed.cw_number, parsed.period), {}).values())
                if isinstance(parsed, PartialKey)
                else []
            )
            # Candidates use their own folder, including legacy multi-station data.
            candidate_groups = self.index.groups
        else:
            async with self.tx() as session:
                row = (
                    (
                        await session.execute(
                            select(
                                Booking.id,
                                Booking.group_id,
                                Booking.booking_key,
                                Booking.cw_number,
                                Booking.period,
                                Booking.station_code,
                            ).where(Booking.booking_key == key)
                        )
                    ).first()
                    if key and len(key) <= 32 and key.isascii()
                    else None
                )
                entry = KeyEntry(*row) if row else None
                cw = parsed.cw_number if parsed else (entry.cw_number if entry else None)
                folder = (
                    (
                        await session.execute(
                            select(
                                BookingGroup.id,
                                BookingGroup.cw_number,
                                BookingGroup.station_code,
                                BookingGroup.supplier_name,
                                BookingGroup.supplier_type,
                            ).where(BookingGroup.cw_number == cw)
                        )
                    ).first()
                    if cw
                    else None
                )
                group = (
                    GroupEntry(
                        folder.id,
                        GroupInfo(
                            cw_number=folder.cw_number,
                            station_code=folder.station_code,
                            supplier_name=folder.supplier_name,
                            supplier_type=folder.supplier_type,
                        ),
                    )
                    if folder
                    else None
                )
                rows = (
                    (
                        await session.execute(
                            select(
                                Booking.id,
                                Booking.group_id,
                                Booking.booking_key,
                                Booking.cw_number,
                                Booking.period,
                                Booking.station_code,
                            ).where(
                                Booking.cw_number == parsed.cw_number,
                                Booking.period == parsed.period,
                            )
                        )
                    ).all()
                    if isinstance(parsed, PartialKey)
                    else []
                )
                matches = [KeyEntry(*row) for row in rows]
                candidate_groups = {cw: group} if group else {}
        if isinstance(parsed, PartialKey):
            if len(matches) > 1:
                candidates = [
                    KeyCandidate(
                        key=e.key,
                        display_key=to_display(e.key),
                        station_code=e.station_code,
                        supplier_name=candidate_groups[e.cw_number].info.supplier_name
                        if e.cw_number in candidate_groups
                        else "",
                    )
                    for e in sorted(matches, key=lambda e: e.key)
                ]
                return (
                    KeyResolution(
                        status="ambiguous",
                        input_kind="partial",
                        key=None,
                        display_key=None,
                        candidates=candidates,
                    ),
                    None,
                    group,
                    None,
                )
            if matches:
                entry = matches[0]
                key = entry.key
            elif group:
                key = build_key(
                    parsed.cw_number,
                    group.info.station_code,
                    parsed.period,
                    self.settings.station_code_pattern,
                )
                entry = None
            else:
                return (
                    KeyResolution(
                        status="needs_station", input_kind="partial", key=None, display_key=None
                    ),
                    None,
                    None,
                    None,
                )
            return (
                KeyResolution(
                    status="resolved_from_partial",
                    input_kind="partial",
                    key=key,
                    display_key=to_display(key),
                ),
                entry,
                group,
                None,
            )
        warning = (
            None
            if isinstance(parsed, ParsedKey)
            else "Invalid booking number. Expected format: CW 1234567-YUL-2608."
        )
        resolution = KeyResolution(
            status="exact" if parsed else "invalid",
            input_kind="full" if parsed else "invalid",
            key=key if parsed or entry else None,
            display_key=to_display(key) if parsed or entry else None,
        )
        return resolution, entry, group, warning

    async def snapshot(self, identifier: int) -> BookingItem:
        cached = self.cache.get(identifier)
        if cached:
            return cached
        generation = self.cache.generation
        async with self.tx() as session:
            row = (await session.execute(snapshot_query().where(Booking.id == identifier))).first()
            if row is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            previews = await invoice_previews(session, [identifier]) if row.invoice_count else {}
            snapshot = snapshot_from_row(row, self.settings, previews.get(identifier))
        hours = (
            row.stale_after_hours
            if row.stale_after_hours is not None
            else self.settings.stale_hours_default
        )
        self.cache.put(identifier, snapshot, row.group_id, hours, generation)
        return snapshot

    async def lookup(self, raw: str, user_id: int) -> tuple[BookingLookup, str]:
        start = time.perf_counter()
        resolution, entry, group, warning = await self.resolve(raw)
        resolved = time.perf_counter()
        result = BookingLookup(
            booking_key=resolution.key,
            display_key=resolution.display_key,
            exists=bool(entry),
            version=0,
            resolution=resolution,
            format_warning=warning,
            group=group.info if group else None,
            group_exists=group is not None,
            history=CursorPage(items=[], next_cursor=None),
        )
        if entry:
            result.snapshot = await self.snapshot(entry.id)
            result.version = result.snapshot.version
        elif resolution.key:
            result.suggestions = await self.suggestions.find(resolution.key)
        snapped = time.perf_counter()
        if entry:
            async with self.tx() as session:
                result.snapshot = result.snapshot.model_copy(
                    update={
                        "my_watching": await session.get(BookingWatcher, (entry.id, user_id))
                        is not None
                    }
                )
                result.history = await note_history(session, entry.id)
                tasks = (
                    await session.scalars(
                        select(BookingTask)
                        .where(
                            BookingTask.booking_id == entry.id,
                            BookingTask.user_id == user_id,
                            BookingTask.status == "pending",
                        )
                        .order_by(BookingTask.remind_at, BookingTask.id)
                    )
                ).all()
            now = datetime.now(UTC)
            snap = result.snapshot
            result.my_tasks = [
                Task(
                    id=t.id,
                    booking_key=entry.key,
                    display_key=to_display(entry.key),
                    message=t.message,
                    remind_at=t.remind_at,
                    status=t.status,
                    is_due=t.remind_at <= now,
                    is_overdue=t.remind_at < now,
                    snooze_count=t.snooze_count,
                    created_at=t.created_at,
                    completed_at=t.completed_at,
                    booking_changed_since=snap.updated_at > t.created_at,
                    booking={
                        "last_status": snap.last_status,
                        "last_agent": snap.last_agent,
                        "is_done": snap.is_done,
                        "updated_at": snap.updated_at,
                    },
                )
                for t in tasks
            ]
            if snap.is_done and snap.last_agent and snap.last_agent.id != user_id:
                agent = snap.last_agent.full_name if snap.last_agent else "Someone"
                when = (
                    snap.done_at.strftime("%d %b %Y %H:%M:%S UTC")
                    if snap.done_at
                    else "an earlier time"
                )
                result.done_warning = (
                    f"{agent} already marked this booking Done on {when}. "
                    "Please review the Activity."
                )
        end = time.perf_counter()
        return (
            result,
            f"key_index;dur={(resolved - start) * 1000:.2f}, "
            f"snapshot;dur={(snapped - resolved) * 1000:.2f}, "
            f"notes;dur={(end - snapped) * 1000:.2f}",
        )

    async def history(self, key: str, cursor: str | None, limit: int):
        _, entry, _, _ = await self.resolve(key)
        if entry is None:
            raise ApiException(ErrorCode.NOT_FOUND)
        async with self.tx() as session:
            return await note_history(session, entry.id, cursor, limit)

    async def listing(
        self,
        user_id: int,
        *,
        page: int,
        size: int,
        mine=False,
        stale_only=False,
        watching=False,
        **filters,
    ):
        conditions = []
        if watching:
            conditions.append(
                Booking.id.in_(
                    select(BookingWatcher.booking_id).where(BookingWatcher.user_id == user_id)
                )
            )
        if mine:
            conditions.append(Booking.last_agent_id == user_id)
        mapping = {
            "cw_number": Booking.cw_number,
            "station_code": Booking.station_code,
            "period": Booking.period,
            "supplier_type": BookingGroup.supplier_type,
            "status_code": Status.code,
            "agent_id": Booking.last_agent_id,
            "is_done": Booking.is_done,
            "invoice_state": Booking.invoice_state,
        }
        for key, column in mapping.items():
            if filters.get(key) is not None:
                value = filters[key]
                if key in {"cw_number", "station_code"}:
                    value = value.strip().upper()
                conditions.append(column == value)
        if filters.get("q"):
            query = filters["q"]
            parsed = parse(query, self.settings.station_code_pattern)
            if isinstance(parsed, ParsedKey):
                conditions.append(Booking.booking_key == parsed.key)
            elif isinstance(parsed, PartialKey):
                conditions.extend(
                    [Booking.cw_number == parsed.cw_number, Booking.period == parsed.period]
                )
            else:
                supplier_query = normalize_supplier_name(query)
                text_conditions = [
                    Booking.booking_key.startswith(normalize(query), autoescape=True),
                    Booking.station_code.startswith(normalize(query), autoescape=True),
                ]
                if supplier_query:
                    text_conditions.append(
                        BookingGroup.supplier_name_normalized.contains(
                            supplier_query, autoescape=True
                        )
                    )
                conditions.append(or_(*text_conditions))
        if filters.get("supplier"):
            conditions.append(
                BookingGroup.supplier_name_normalized.startswith(
                    normalize_supplier_name(filters["supplier"]), autoescape=True
                )
            )
        if filters.get("invoice"):
            conditions.append(
                Booking.id.in_(
                    select(BookingInvoice.booking_id).where(
                        BookingInvoice.invoice_number == filters["invoice"].strip().upper()
                    )
                )
            )
        for key, comparison in (
            ("date_from", Booking.updated_at.__ge__),
            ("date_to", Booking.updated_at.__le__),
        ):
            if filters.get(key):
                conditions.append(comparison(filters[key]))
        stale_expr = stale_condition(self.settings)
        if stale_only or filters.get("stale") is True:
            conditions.append(stale_expr)
        elif filters.get("stale") is False:
            conditions.append(~stale_expr)
        order = filters.get("sort", "updated_at_desc")
        orders = {
            "updated_at_desc": (Booking.updated_at.desc(), Booking.id.desc()),
            "updated_at_asc": (Booking.updated_at.asc(), Booking.id.asc()),
        }
        if order not in orders:
            raise ApiException(ErrorCode.VALIDATION_ERROR, message="Invalid sort order.")
        if stale_only:
            order = "updated_at_asc"
        query = snapshot_query().where(*conditions)
        count_key = (
            self.cache.generation,
            user_id if mine or watching else None,
            watching,
            mine,
            stale_only,
            repr(sorted(filters.items())),
        )
        saved_total = self._totals.get(count_key)
        async with self.tx() as session:
            if saved_total and saved_total[0] > time.monotonic():
                total = saved_total[1]
            else:
                total = await session.scalar(
                    select(func.count()).select_from(query.order_by(None).subquery())
                )
                self._totals[count_key] = (time.monotonic() + 15, total)
                if len(self._totals) > 512:
                    self._totals.pop(next(iter(self._totals)))
            rows = (
                await session.execute(
                    query.order_by(*orders[order]).offset((page - 1) * size).limit(size)
                )
            ).all()
            ids = [row.id for row in rows]
            previews = await invoice_previews(session, ids)
            private_rows = (
                (
                    await session.execute(
                        select(
                            Booking.id,
                            func.count(BookingTask.id).label("pending"),
                            func.max(BookingWatcher.user_id).label("watcher"),
                        )
                        .outerjoin(
                            BookingTask,
                            and_(
                                BookingTask.booking_id == Booking.id,
                                BookingTask.user_id == user_id,
                                BookingTask.status == "pending",
                            ),
                        )
                        .outerjoin(
                            BookingWatcher,
                            and_(
                                BookingWatcher.booking_id == Booking.id,
                                BookingWatcher.user_id == user_id,
                            ),
                        )
                        .where(Booking.id.in_(ids))
                        .group_by(Booking.id)
                    )
                ).all()
                if ids
                else []
            )
            counts = {r.id: r.pending for r in private_rows}
            watched = {r.id for r in private_rows if r.watcher is not None}
        items = []
        for row in rows:
            item = snapshot_from_row(row, self.settings, previews.get(row.id))
            item.my_pending_tasks = counts.get(row.id, 0)
            item.my_watching = row.id in watched
            items.append(item)
        return Page(items=items, total=total, page=page, size=size)
