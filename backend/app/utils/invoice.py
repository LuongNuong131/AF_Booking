"""Shared invoice normalization; delimiters belong to input parsing, never storage."""

import re
import unicodedata

DEFAULT_PATTERN = r"^[A-Z0-9][A-Z0-9\-_/.]{2,39}$"


def normalize(value: str) -> str:
    return "".join(c for c in value if unicodedata.category(c) not in {"Cc", "Cf"}).strip().upper()


def split_input(raw: str) -> list[str]:
    return list(
        dict.fromkeys(value for part in re.split(r"[,;\s]+", raw) if (value := normalize(part)))
    )


def validate(value: str, pattern=DEFAULT_PATTERN) -> bool:
    return len(value) <= 40 and re.fullmatch(pattern, value, re.ASCII) is not None


def state_label(value):
    return {
        "has_invoice": "Has invoice",
        "no_invoice": "No invoice Number",
        "unknown": "Not declared",
    }[value]
