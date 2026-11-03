from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.exports import safe_cell
from app.services.reports import day_bounds


@pytest.mark.parametrize(
    "value", ["=1+1", "+SUM(A1)", "-5", "@name", "\tvalue", "\nvalue", "\rvalue", "  =1+1"]
)
def test_every_formula_prefix_is_quoted(value):
    assert safe_cell(value) == "'" + value


def test_plain_text_and_dst_business_day_boundaries():
    assert safe_cell("Crew mail") == "Crew mail"
    assert safe_cell(None) == ""
    lo, hi = day_bounds(date(2026, 3, 8), ZoneInfo("America/Toronto"))
    assert lo == datetime(2026, 3, 8, 5, tzinfo=UTC)
    assert (hi - lo).total_seconds() == 23 * 3600
