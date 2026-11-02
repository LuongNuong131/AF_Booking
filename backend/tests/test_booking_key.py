import json
from pathlib import Path

import pytest

from app.utils.booking_key import ParsedKey, PartialKey, build_key, normalize, parse, to_display
from app.utils.text import clean_note

CASES = json.loads((Path(__file__).resolve().parents[2] / "fixtures/booking-keys.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["raw"] for case in CASES])
def test_shared_keys(case):
    result = parse(case["raw"])
    if case["kind"] == "invalid":
        assert result is None
    elif case["kind"] == "partial":
        assert isinstance(result, PartialKey) and result.normalized == case["key"]
    else:
        assert isinstance(result, ParsedKey) and result.key == case["key"]
        assert to_display(result.key) == "CW 2154654-RDU-2609"
        assert result.period_label == "Sep 2026"


def test_limits_components_and_cleaning():
    assert parse("x" * 129) is None
    assert normalize("CW\x002154654-RDU-2609") == "CW2154654-RDU-2609"
    assert build_key("CW2154654", "RDU", "2609") == "CW2154654-RDU-2609"
    assert isinstance(parse("CW2154654-RD-2609", r"[A-Z]{2}"), ParsedKey)
    with pytest.raises(ValueError):
        build_key("CW123", "RDU", "2609")
    assert clean_note("Hi\x00\u200b\r\nthere\t!") == "Hi\nthere\t!"
    assert clean_note(" \x00\t\n") is None
