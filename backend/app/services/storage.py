import asyncio
import hashlib
import hmac
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote, urlsplit

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
    configured = False

    async def save(self, *, file_name: str, mime_type: str, content: bytes) -> str:
        raise HTTPException(501)

    async def get_url(self, key: str) -> str:
        raise HTTPException(501)

    async def delete(self, key: str) -> None:
        raise HTTPException(501)


def signed_request(settings, method, key, content=b"", mime_type=None, now=None):
    """AWS Signature V4 for private S3-compatible PUT/GET; no public image URLs."""
    now = now or datetime.now(UTC)
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    origin = settings.s3_endpoint
    host = urlsplit(origin).netloc
    path = "/" + quote(settings.s3_bucket + "/" + key, safe="/-_.~")
    digest = hashlib.sha256(content).hexdigest()
    headers = {"host": host, "x-amz-content-sha256": digest, "x-amz-date": stamp}
    if mime_type:
        headers["content-type"] = mime_type
    names = ";".join(sorted(headers))
    canonical_headers = "".join(name + ":" + headers[name] + "\n" for name in sorted(headers))
    canonical = "\n".join([method, path, "", canonical_headers, names, digest])
    scope = f"{day}/{settings.s3_region}/s3/aws4_request"
    to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    signing_key = ("AWS4" + settings.s3_secret_access_key.get_secret_value()).encode()
    for part in [day, settings.s3_region, "s3", "aws4_request"]:
        signing_key = hmac.new(signing_key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing_key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={settings.s3_access_key_id.get_secret_value()}/{scope}, "
        f"SignedHeaders={names}, Signature={signature}"
    )
    return urllib.request.Request(
        origin + path, data=content if method == "PUT" else None, headers=headers, method=method
    )


class S3Storage:
    configured = True

    def __init__(self, settings):
        self.settings = settings

    async def put(self, key, content, mime_type):
        request = signed_request(self.settings, "PUT", key, content, mime_type)

        def send():
            with urllib.request.urlopen(request, timeout=5) as response:
                response.read(1024)

        await asyncio.to_thread(send)

    async def read(self, key):
        request = signed_request(self.settings, "GET", key)

        def read():
            with urllib.request.urlopen(request, timeout=5) as response:
                data = response.read(MAX_ATTACHMENT_BYTES + 1)
                if len(data) > MAX_ATTACHMENT_BYTES:
                    raise ValueError("Image exceeds attachment limit.")
                return data

        return await asyncio.to_thread(read)


def create_storage(settings):
    values = [
        settings.s3_endpoint,
        settings.s3_bucket,
        settings.s3_access_key_id,
        settings.s3_secret_access_key,
    ]
    if all(values):
        return S3Storage(settings)
    if any(values):
        raise ValueError("Set all four S3 storage fields, or leave all unset.")
    return NullStorage()
