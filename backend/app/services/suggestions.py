"""Bounded one-edit CW/month candidates. Never scan bookings or run supplier LIKE."""

from sqlalchemy import cast, func, literal, select, union_all
from sqlalchemy.dialects.mysql import CHAR

from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, Status, User
from app.schemas.contracts import Suggestion
from app.utils.booking_key import ParsedKey, parse, to_display


def candidates(key: ParsedKey) -> dict[tuple[str, str], int]:
    digits = key.cw_number[2:]
    result = {}

    def add(value, period=key.period, distance=1):
        if 5 <= len(value) <= 10 and (value != digits or period != key.period):
            pair = ("CW" + value, period)
            result[pair] = min(distance, result.get(pair, distance))

    # Neighbouring months are independent of digit edits; never combine two mistakes.
    month = int(key.period[:2]) * 12 + int(key.period[2:]) - 1
    for delta in (-1, 1, -2, 2):
        target = month + delta
        if 0 <= target < 1200:
            add(digits, f"{target // 12:02d}{target % 12 + 1:02d}", abs(delta))
    for i in range(len(digits)):
        for value in "0123456789":
            add(digits[:i] + value + digits[i + 1 :])
        add(digits[:i] + digits[i + 1 :])
        if i + 1 < len(digits):
            add(digits[:i] + digits[i + 1] + digits[i] + digits[i + 2 :])
    for i in range(len(digits) + 1):
        for value in "0123456789":
            add(digits[:i] + value + digits[i:])
    assert len(result) <= 250
    return result


class Suggestions:
    def __init__(self, engine, settings, index):
        self.engine, self.settings, self.index = engine, settings, index

    async def find(self, raw, session=None):
        parsed = parse(raw, self.settings.station_code_pattern)
        if not isinstance(parsed, ParsedKey) or not parsed.cw_number[2:].isdigit():
            return []  # New partial CWs must acquire an explicit station first.
        variants = candidates(parsed)
        if self.index.usable:
            keys = []
            for cw, period in variants:
                for folder in self.index.cw_groups.get(cw, {}).values():
                    key = f"{cw}-{folder.info.station_code}-{period}"
                    if key in self.index.keys:
                        keys.append(key)
            if not keys:
                return []
        else:
            # A small derived candidate set resolves each folder's station via its
            # unique CW index, then probes the unique booking key in ONE statement.
            values = union_all(
                *[
                    select(
                        cast(literal(cw), CHAR(charset="ascii")).collate("ascii_bin").label("cw"),
                        cast(literal(period), CHAR(charset="ascii"))
                        .collate("ascii_bin")
                        .label("period"),
                    )
                    for cw, period in variants
                ]
            ).subquery("suggestion_candidates")
            keys = select(
                func.concat(
                    values.c.cw,
                    "-",
                    func.coalesce(BookingGroup.station_code, parsed.station_code),
                    "-",
                    values.c.period,
                )
            ).select_from(values.outerjoin(BookingGroup, BookingGroup.cw_number == values.c.cw))
        query = (
            select(
                Booking.booking_key,
                Booking.cw_number,
                Booking.period,
                Booking.updated_at,
                User.id.label("agent_id"),
                User.full_name,
                Status.code,
                Status.label,
            )
            .outerjoin(User, User.id == Booking.last_agent_id)
            .outerjoin(Status, Status.id == Booking.last_status_id)
            .where(Booking.booking_key.in_(keys))
        )

        async def read(connection):
            rows = (await connection.execute(query)).all()
            rows.sort(
                key=lambda row: (
                    variants[(row.cw_number, row.period)],
                    -row.updated_at.timestamp(),
                    row.booking_key,
                )
            )
            return [
                Suggestion(
                    booking_key=row.booking_key,
                    display_key=to_display(row.booking_key),
                    last_status={"code": row.code, "label": row.label} if row.code else None,
                    last_agent={"id": row.agent_id, "full_name": row.full_name}
                    if row.agent_id
                    else None,
                    updated_at=row.updated_at,
                    distance=variants[(row.cw_number, row.period)],
                )
                for row in rows[:3]
            ]

        if session is not None:
            return await read(session)
        async with transaction(
            self.engine, self.settings, seconds=self.settings.search_db_timeout_seconds
        ) as connection:
            return await read(connection)
