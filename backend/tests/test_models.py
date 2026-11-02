from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects.mysql import dialect

from app.core.config import Settings
from app.models import Booking, BookingGroup
from app.models.base import UTCDateTime
from app.scripts.seed import AdminCredentials


@pytest.mark.parametrize(
    "value",
    ["cw2154654-RDU-2609", "CW 2154654-RDU-2609", "CW\t2154654-RDU-2609", "CW2154654–RDU–2609"],
)
def test_orm_rejects_noncanonical_storage_keys(value: str) -> None:
    with pytest.raises(ValueError):
        Booking(booking_key=value)


def test_timestamps_normalize_utc_and_reject_naive_values() -> None:
    timestamp = UTCDateTime()
    value = datetime(2026, 11, 2, 15, 15, 30, 123999, tzinfo=timezone(timedelta(hours=7)))
    stored = timestamp.process_bind_param(value, dialect())
    assert stored == datetime(2026, 11, 2, 8, 15, 30, 123000)
    assert timestamp.process_result_value(stored, dialect()).tzinfo is UTC
    with pytest.raises(ValueError):
        timestamp.process_bind_param(datetime(2026, 11, 2), dialect())


def test_db_ssl_alias_and_conflicts() -> None:
    assert Settings(_env_file=None, db_ssl=False).database_ssl is False
    assert Settings(_env_file=None, db_ssl=True, database_ssl=True).database_ssl is True
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_ssl=False, database_ssl=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", db_ssl=False, cors_origins=[])


def test_seed_requires_real_credentials_and_masks_passwords() -> None:
    with pytest.raises(ValidationError):
        AdminCredentials(_env_file=None, admin_username="admin", admin_password="short")
    credentials = AdminCredentials(
        _env_file=None, admin_username="admin", admin_password="test-only-strong-password"
    )
    assert "test-only-strong-password" not in repr(credentials)


def test_supplier_name_is_normalized_when_assigned() -> None:
    group = BookingGroup(supplier_name="HÔTEL & Đà Nẵng, Inc.")
    assert group.supplier_name_normalized == "hotel da nang inc"
    group.supplier_name = "DOUBLE TREE by HILTON - YUL"
    assert group.supplier_name_normalized == "double tree by hilton yul"
