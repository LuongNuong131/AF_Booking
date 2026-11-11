"""Two explicit search strategies; LIKE always has a bounded indexed date window."""

import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, BookingNote, Status, User
from app.schemas.contracts import ErrorCode
from app.schemas.operations import NoteSearchHit, NoteSearchPage
from app.services.reports import day_bounds
from app.services.search_limiter import SearchLimiter
from app.utils.booking_key import to_display


class NoteSearch(ABC):
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self.limiter = SearchLimiter(limit=60)

    async def validate(self, session):
        return None

    @abstractmethod
    def match(self, query):
        raise NotImplementedError

    async def search(self, query, date_from, date_to, agent_id, status_code, page, size):
        query = query.strip()
        if not 3 <= len(query) <= 100:
            raise ApiException(ErrorCode.VALIDATION_ERROR, message="Enter 3–100 characters.")
        zone = ZoneInfo(self.settings.business_timezone)
        today = datetime.now(zone).date()
        end = date_to or today
        start = date_from or end - timedelta(days=29)
        if start > end or (end - start).days >= 180:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR, message="Choose a date window of at most 180 days."
            )
        lo, _ = day_bounds(start, zone)
        _, hi = day_bounds(end, zone)
        filtered = select(
            BookingNote.booking_id,
            func.max(BookingNote.id).label("note_id"),
            func.count().label("match_count"),
        ).where(
            BookingNote.created_at >= lo,
            BookingNote.created_at < hi,
            BookingNote.deleted_at.is_(None),
            self.match(query),
        )
        # The index is required by both supported schema migrations. Date-bounded
        # LIKE cannot drift into a whole-history text scan on a compatible optimizer.
        if self.settings.note_search_strategy == "like":
            filtered = filtered.with_hint(
                BookingNote, "FORCE INDEX (ix_booking_notes_created_at)", "mysql"
            )
        if agent_id:
            filtered = filtered.where(BookingNote.agent_id == agent_id)
        if status_code:
            filtered = filtered.where(
                BookingNote.status_id.in_(select(Status.id).where(Status.code == status_code))
            )
        matches = filtered.group_by(BookingNote.booking_id).subquery()
        async with transaction(
            self.engine, self.settings, seconds=self.settings.search_db_timeout_seconds
        ) as session:
            await self.validate(session)
            total = await session.scalar(select(func.count()).select_from(matches))
            # Materialize the small ordered page before joining display tables.
            # Otherwise TiDB can hash-join every historical note before LIMIT.
            page_matches = (
                select(matches.c.note_id, matches.c.match_count)
                .join(BookingNote, BookingNote.id == matches.c.note_id)
                .order_by(BookingNote.created_at.desc(), BookingNote.id.desc())
                .offset((page - 1) * size)
                .limit(size)
                .subquery("note_search_page")
            )
            selected = (await session.execute(select(page_matches))).all()
            counts = {row.note_id: row.match_count for row in selected}
            rows = (
                await session.execute(
                    select(
                        Booking.booking_key,
                        Booking.station_code,
                        BookingGroup.supplier_name,
                        func.coalesce(Booking.classification, BookingGroup.supplier_type).label(
                            "supplier_type"
                        ),
                        BookingNote.id,
                        BookingNote.note,
                        BookingNote.position_label,
                        BookingNote.created_at,
                        User.id.label("agent_id"),
                        User.full_name,
                        Status.code,
                        Status.label,
                    )
                    .select_from(BookingNote)
                    .join(Booking, Booking.id == BookingNote.booking_id)
                    .join(BookingGroup, BookingGroup.id == Booking.group_id)
                    .join(User, User.id == BookingNote.agent_id)
                    .join(Status, Status.id == BookingNote.status_id)
                    .where(BookingNote.id.in_(counts))
                    .order_by(BookingNote.created_at.desc(), BookingNote.id.desc())
                )
            ).all()
        return NoteSearchPage(
            items=[
                NoteSearchHit(
                    booking_key=r.booking_key,
                    display_key=to_display(r.booking_key),
                    note_id=r.id,
                    note=r.note,
                    agent={"id": r.agent_id, "full_name": r.full_name},
                    status={"code": r.code, "label": r.label},
                    position=r.position_label,
                    created_at=r.created_at,
                    match_count=counts[r.id],
                    supplier_name=r.supplier_name,
                    station_code=r.station_code,
                    supplier_type=r.supplier_type,
                )
                for r in rows
            ],
            total=total,
            page=page,
            size=size,
            date_from=start,
            date_to=end,
            timezone=self.settings.business_timezone,
            strategy=self.settings.note_search_strategy,
        )


class LikeNoteSearch(NoteSearch):
    def match(self, query):
        return BookingNote.note.contains(query, autoescape=True)


class FulltextNoteSearch(NoteSearch):
    ready = False

    async def validate(self, session):
        if self.ready:
            return
        version = str(await session.scalar(text("SELECT VERSION()"))).lower()
        index = await session.scalar(
            text(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='booking_notes' "
                "AND INDEX_NAME='ft_booking_notes_note' AND INDEX_TYPE='FULLTEXT'"
            )
        )
        if "tidb" in version or not index:
            raise ApiException(
                ErrorCode.SERVICE_BUSY,
                message=(
                    "Full-text search is unavailable. Configure LIKE search "
                    "or install the optional MySQL ngram index."
                ),
            )
        definition = (await session.execute(text("SHOW CREATE TABLE booking_notes"))).first()[1]
        if re.search(r"WITH\s+PARSER\s+`?ngram`?", definition, re.IGNORECASE) is None:
            raise ApiException(
                ErrorCode.SERVICE_BUSY,
                message="Install the optional MySQL ngram index before enabling full-text search.",
            )
        self.ready = True

    def match(self, query):
        # All user text stays a bound parameter, including Vietnamese characters.
        return text(
            "MATCH(booking_notes.note) AGAINST (:note_query IN NATURAL LANGUAGE MODE)"
        ).bindparams(note_query=query)


def create_note_search(engine, settings):
    return (FulltextNoteSearch if settings.note_search_strategy == "fulltext" else LikeNoteSearch)(
        engine, settings
    )
