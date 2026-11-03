"""Search classification, independent of the HTTP and database layers."""

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from app.utils.booking_key import DASHES, ParsedKey, PartialKey, normalize, parse


class QueryKind(StrEnum):
    FULL_KEY = "full_key"
    PARTIAL_KEY = "partial_key"
    CW_NUMBER = "cw_number"
    CW_PREFIX = "cw_prefix"
    STATION_PERIOD = "station_period"
    STATION = "station"
    TEXT = "text"
    NONE = "none"


@dataclass(frozen=True)
class ClassifiedQuery:
    kind: QueryKind
    query: str
    cw_number: str | None = None
    station_code: str | None = None
    period: str | None = None


def normalize_search(raw: str) -> str:
    raw = "".join(
        c if c.isspace() else "" if unicodedata.category(c) in {"Cc", "Cf"} else c for c in raw
    )
    return re.sub(r"\s+", " ", raw.translate(DASHES).strip()).upper()


def classify_query(
    raw: str, station_codes: Collection[str] = (), station_pattern: str = r"[A-Z]{3}"
) -> ClassifiedQuery:
    query = normalize_search(raw)
    if not query or len(raw) > 100:
        return ClassifiedQuery(QueryKind.NONE, query)
    parsed = parse(raw, station_pattern)
    if isinstance(parsed, ParsedKey):
        return ClassifiedQuery(
            QueryKind.FULL_KEY, parsed.key, parsed.cw_number, parsed.station_code, parsed.period
        )
    if isinstance(parsed, PartialKey):
        return ClassifiedQuery(
            QueryKind.PARTIAL_KEY, parsed.normalized, parsed.cw_number, period=parsed.period
        )
    key_form = normalize(raw)
    cw = re.fullmatch(r"(CW[0-9]{0,10})(?:-([A-Z]{1,4}))?", key_form, re.ASCII)
    if cw and (cw[2] is None or re.fullmatch(station_pattern, cw[2], re.ASCII)):
        kind = QueryKind.CW_NUMBER if len(cw[1]) >= 7 else QueryKind.CW_PREFIX
        return ClassifiedQuery(kind, key_form, cw[1], cw[2])
    station_period = re.fullmatch(r"([A-Z]{1,4})-([0-9]{2}(?:0[1-9]|1[0-2]))", key_form, re.ASCII)
    if station_period and re.fullmatch(station_pattern, station_period[1], re.ASCII):
        return ClassifiedQuery(
            QueryKind.STATION_PERIOD,
            key_form,
            station_code=station_period[1],
            period=station_period[2],
        )
    if re.fullmatch(station_pattern, query, re.ASCII) and query in station_codes:
        return ClassifiedQuery(QueryKind.STATION, query, station_code=query)
    # Malformed key-shaped input must never fall through to a supplier LIKE scan.
    if re.match(r"^CW(?:[0-9]|-|$)", key_form, re.ASCII) or re.fullmatch(
        r"[A-Z]{1,4}-[0-9]{4}", key_form, re.ASCII
    ):
        return ClassifiedQuery(QueryKind.NONE, key_form)
    return ClassifiedQuery(QueryKind.TEXT, query)
