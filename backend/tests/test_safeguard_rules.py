import pytest

from app.core.config import Settings
from app.services.suggestions import candidates
from app.utils.booking_key import parse


@pytest.mark.parametrize(
    "digits", ["12345", "123456", "1234567", "12345678", "123456789", "1234567890"]
)
def test_bounded_candidates_are_valid_and_single_edit(digits):
    key = parse(f"CW{digits}-RDU-2601")
    values = candidates(key)
    assert len(values) <= 250
    assert (key.cw_number, key.period) not in values
    assert (key.cw_number, "2512") in values and values[(key.cw_number, "2603")] == 2
    assert all(parse(f"{cw}-RDU-{period}") for cw, period in values)


def test_period_bounds_do_not_wrap_the_century():
    assert ("CW12345", "9912") not in candidates(parse("CW12345-RDU-0001"))
    assert ("CW12345", "0001") not in candidates(parse("CW12345-RDU-9912"))


def test_integrity_schedule_configuration():
    assert Settings(_env_file=None).integrity_run_time == "02:00"
    with pytest.raises(ValueError):
        Settings(_env_file=None, integrity_run_time="24:00")
