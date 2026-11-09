import re
import unicodedata
from dataclasses import dataclass

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
CW_PATTERN = r"CW(?:[0-9]{5,10}|(?=[A-Z0-9]*[A-Z])[A-Z0-9]{4,10})"
MAX_RAW_KEY_LENGTH = 100
DASHES = str.maketrans({c: "-" for c in "–—−‐‑"})


@dataclass(frozen=True)
class PartialKey:
    cw_number: str
    period: str
    period_label: str
    normalized: str


@dataclass(frozen=True)
class ParsedKey:
    key: str
    display_key: str
    cw_number: str
    station_code: str
    period: str
    period_label: str


def normalize(raw: str) -> str:
    if len(raw) > MAX_RAW_KEY_LENGTH:
        return ""
    cleaned = "".join(c for c in raw if unicodedata.category(c) not in {"Cc", "Cf"})
    cleaned = cleaned.translate(DASHES).strip().upper()
    cleaned = re.sub(r"\s*-\s*", "-", cleaned)
    cleaned = re.sub(r"^CW\s+(?=[A-Z0-9])", "CW", cleaned)
    return re.sub(r"\s+", "-", cleaned)


def period_label(period: str) -> str:
    return f"{MONTHS[int(period[2:]) - 1]} {2000 + int(period[:2])}"


def to_display(key: str) -> str:
    return re.sub(r"^CW\s*(?=[A-Z0-9])", "CW ", key)


def parse(raw: str, station_pattern: str = r"[A-Z]{3}") -> ParsedKey | PartialKey | None:
    # Normalization is independently usable, but control-bearing keys are invalid input.
    if len(raw) > MAX_RAW_KEY_LENGTH or any(unicodedata.category(c) == "Cc" for c in raw):
        return None
    key = normalize(raw)
    partial = re.fullmatch(rf"({CW_PATTERN})-" + r"(\d{2}(?:0[1-9]|1[0-2]))", key, re.ASCII)
    if partial:
        cw, period = partial.groups()
        return PartialKey(cw, period, period_label(period), key)
    full = re.fullmatch(
        rf"({CW_PATTERN})-" + r"([A-Z]{1,4})-(\d{2}(?:0[1-9]|1[0-2]))", key, re.ASCII
    )
    if full:
        cw, station, period = full.groups()
        if re.fullmatch(station_pattern, station, re.ASCII):
            return ParsedKey(key, to_display(key), cw, station, period, period_label(period))
    return None


def build_key(cw_number: str, station: str, period: str, station_pattern: str = r"[A-Z]{3}") -> str:
    parsed = parse(f"{cw_number}-{station}-{period}", station_pattern)
    if not isinstance(parsed, ParsedKey):
        raise ValueError("Invalid booking key components")
    return parsed.key


def require_canonical_storage_key(value: str) -> str:
    """Storage invariant; full/partial parsing and lookup belong to the booking service."""
    if (
        not value
        or not value.isascii()
        or value != value.upper()
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Stored booking keys must be uppercase ASCII without whitespace")
    return value
