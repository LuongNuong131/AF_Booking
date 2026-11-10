from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApiException, error_response
from app.main import create_app
from app.schemas.bookings import BookingCreateRequest
from app.schemas.contracts import ErrorCode
from app.services.booking_writes import BookingWrites


@pytest.mark.parametrize(
    "key,code",
    [
        ("CW2154654-2609", ErrorCode.STATION_REQUIRED),
        ("CW2154654-RDU-2613", ErrorCode.INVALID_BOOKING_KEY),
        ("CW2154654-RDU-2609\n", ErrorCode.INVALID_BOOKING_KEY),
    ],
)
async def test_invalid_creation_keys_are_rejected_before_database_access(key, code):
    settings = Settings(_env_file=None, app_env="test")
    service = BookingWrites(None, settings, None, None, None)
    with pytest.raises(ApiException) as error:
        await service.create(BookingCreateRequest(booking_key=key), SimpleNamespace(id=1), None)
    assert error.value.code == code


@pytest.mark.parametrize(
    "values",
    [
        {"booking_key": ""},
        {"booking_key": "x" * 101},
        {"booking_key": "CW2154654-RDU-2609", "supplier_name": "x" * 256},
        {"booking_key": "CW2154654-RDU-2609", "supplier_type": "unclassified"},
        {"booking_key": "CW2154654-RDU-2609", "role": "admin"},
    ],
)
def test_creation_input_is_bounded_and_does_not_accept_extra_fields(values):
    with pytest.raises(ValidationError):
        BookingCreateRequest.model_validate(values)


def test_duplicate_code_is_a_conflict_and_creation_requires_authentication():
    assert error_response(ErrorCode.BOOKING_EXISTS).status_code == 409
    app = create_app(Settings(_env_file=None, app_env="test"))
    with TestClient(app) as client:
        assert (
            client.post("/api/v1/bookings", json={"booking_key": "CW2154654-RDU-2609"}).status_code
            == 401
        )
