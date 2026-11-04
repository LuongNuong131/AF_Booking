import json
from pathlib import Path

import pytest

from app.utils.invoice import normalize, split_input, validate

DATA = json.loads((Path(__file__).resolve().parents[2] / "fixtures/invoice-input.json").read_text())


@pytest.mark.parametrize("row", DATA)
def test_shared_split(row):
    assert split_input(row["raw"]) == row["expected"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("INV1", True),
        ("INV/123-A.2", True),
        ("_BAD", False),
        ("AB", False),
        ("A" * 41, False),
        ("BAD VALUE", False),
        ("=1+1", False),
    ],
)
def test_validation(value, expected):
    assert validate(value) == expected


def test_normalize_controls_and_custom_pattern():
    assert normalize(" inv\x00a\u200b01 ") == "INVA01"
    assert validate("1234", r"^[0-9]{4}$") and not validate("INV1", r"^[0-9]{4}$")
