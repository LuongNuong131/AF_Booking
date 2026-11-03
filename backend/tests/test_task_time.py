from datetime import UTC, date, datetime, time

import pytest

from app.core.errors import ApiException
from app.services.tasks import effective_settings, remind_instant


def test_dst_gap_overlap_and_calendar_horizon():
    prefs = effective_settings({"timezone": "America/Toronto"}, "Asia/Ho_Chi_Minh")
    with pytest.raises(ApiException):
        remind_instant(date(2026, 3, 8), time(2, 30), prefs, datetime(2026, 3, 6, tzinfo=UTC))
    assert remind_instant(
        date(2026, 11, 1), time(1, 30), prefs, datetime(2026, 10, 31, tzinfo=UTC)
    ) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    with pytest.raises(ApiException):
        remind_instant(date(2027, 3, 1), time(9), prefs, datetime(2026, 10, 31, tzinfo=UTC))


def test_default_preferences_are_explicit_and_do_not_enable_alerts():
    prefs = effective_settings(None, "Asia/Ho_Chi_Minh")
    assert prefs["default_remind_time"] == "09:00"
    assert prefs["skip_weekends"] is True
    assert prefs["task_sound"] is False and prefs["web_notifications"] is False
