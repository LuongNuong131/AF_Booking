import asyncio
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.errors import ApiException
from app.schemas.auth import UserRole
from app.schemas.contracts import ErrorCode

T = TypeVar("T")


def unauthorized() -> ApiException:
    return ApiException(ErrorCode.UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})


def signing_key(settings: Settings) -> str:
    if settings.jwt_secret_key is None:
        raise ApiException(ErrorCode.SERVICE_BUSY, message="Authentication is not configured.")
    return settings.jwt_secret_key.get_secret_value()


class TokenClaims(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    sub: str
    role: UserRole
    sid: str
    iat: StrictInt
    exp: StrictInt

    @field_validator("sub")
    @classmethod
    def valid_subject(cls, value: str) -> str:
        if not value.isascii() or not value.isdecimal() or not 0 < int(value) < 2**64:
            raise ValueError("Invalid subject")
        return value

    @field_validator("sid")
    @classmethod
    def valid_session(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("Invalid session")
        return value


def create_access_token(user_id: int, role: UserRole, session_id: str, settings: Settings) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "role": role,
            "sid": session_id,
            "iat": now,
            "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        signing_key(settings),
        algorithm="HS256",
    )


def decode_access_token(token: str, settings: Settings) -> TokenClaims:
    if len(token) > 4096:
        raise unauthorized()
    key = signing_key(settings)
    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "role", "sid", "iat", "exp", "iss", "aud"]},
        )
        claims = TokenClaims.model_validate(payload)
        if claims.exp <= claims.iat:
            raise unauthorized()
        return claims
    except (jwt.InvalidTokenError, ValidationError, ValueError):
        raise unauthorized() from None


class PasswordService:
    def __init__(self, concurrency: int = 2) -> None:
        self.hasher = PasswordHasher()
        self._slots = asyncio.Semaphore(concurrency)
        self._dummy_lock = asyncio.Lock()
        self._dummy_hash: str | None = None

    async def _run(self, function: Callable[[], T]) -> T:
        await self._slots.acquire()
        work = asyncio.create_task(run_in_threadpool(function))

        def completed(task: asyncio.Task[T]) -> None:
            self._slots.release()
            if not task.cancelled():
                task.exception()  # Consume exceptions even if the request was cancelled.

        work.add_done_callback(completed)
        # Cancellation must not free the slot while the thread is still hashing.
        return await asyncio.shield(work)

    async def hash(self, password: str) -> str:
        return await self._run(lambda: self.hasher.hash(password))

    async def verify(self, encoded: str | None, password: str) -> bool:
        if encoded is None:
            async with self._dummy_lock:
                if self._dummy_hash is None:
                    self._dummy_hash = await self.hash(secrets.token_urlsafe(32))
            encoded = self._dummy_hash

        def verify() -> bool:
            try:
                return self.hasher.verify(encoded, password)
            except (VerificationError, InvalidHashError):
                return False

        return await self._run(verify)
