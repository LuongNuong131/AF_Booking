from typing import Protocol

from starlette.exceptions import HTTPException

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_NOTE = 5
ALLOWED_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}
)


class FileStorage(Protocol):
    async def save(self, *, file_name: str, mime_type: str, content: bytes) -> str: ...
    async def get_url(self, key: str) -> str: ...
    async def delete(self, key: str) -> None: ...


class NullStorage:
    async def save(self, *, file_name: str, mime_type: str, content: bytes) -> str:
        raise HTTPException(501)

    async def get_url(self, key: str) -> str:
        raise HTTPException(501)

    async def delete(self, key: str) -> None:
        raise HTTPException(501)
