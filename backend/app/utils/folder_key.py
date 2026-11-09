import re

from app.core.errors import ApiException
from app.schemas.contracts import ErrorCode
from app.utils.booking_key import CW_PATTERN


def folder_parts(value: str) -> tuple[str, str | None]:
    match = re.fullmatch(rf"({CW_PATTERN})(?:-([A-Z]{{3}}))?", value, re.ASCII)
    if not match:
        raise ApiException(ErrorCode.INVALID_BOOKING_KEY)
    return match[1], match[2]


def folder_key(cw: str, station: str) -> str:
    return f"{cw}-{station}"
