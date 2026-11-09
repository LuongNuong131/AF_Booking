from datetime import UTC, datetime

import pytest

from app.services.monthly_bookings import due_period, next_period


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        ("2026-11-24T16:59:59+00:00", "2610"),
        ("2026-11-24T17:00:00+00:00", "2611"),
        ("2026-11-30T20:00:00+00:00", "2611"),
        ("2027-01-01T00:00:00+00:00", "2612"),
        ("2027-01-24T17:00:00+00:00", "2701"),
    ],
)
def test_vietnam_work_cycle(instant, expected):
    assert due_period(datetime.fromisoformat(instant), "Asia/Ho_Chi_Minh") == expected


def test_month_boundaries_and_supported_year_range():
    assert next_period("2612") == "2701"
    assert next_period("2802") == "2803"
    assert due_period(datetime(2026, 11, 25, tzinfo=UTC), "UTC", 28) == "2610"
    with pytest.raises(ValueError):
        next_period("9912")
