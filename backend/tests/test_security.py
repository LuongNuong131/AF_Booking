import asyncio
import secrets
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApiException
from app.core.security import PasswordService, create_access_token, decode_access_token
from app.schemas.contracts import ErrorCode
from app.services.login_limiter import LoginLimiter
from app.services.session_cache import SessionCache


@pytest.fixture
def token_settings() -> Settings:
    return Settings(_env_file=None, app_env="test", jwt_secret_key=secrets.token_urlsafe(64))


def test_token_round_trip_and_expiry_budget(token_settings: Settings) -> None:
    sid = str(uuid4())
    token = create_access_token(42, "qc", sid, token_settings)
    claims = decode_access_token(token, token_settings)
    assert (claims.sub, claims.role, claims.sid) == ("42", "qc", sid)
    assert claims.exp - claims.iat == 12 * 60 * 60


@pytest.mark.parametrize(
    "case",
    [
        "expired",
        "wrong_issuer",
        "wrong_audience",
        "missing_sid",
        "missing_exp",
        "numeric_sub",
        "invalid_role",
        "invalid_sid",
        "future_iat",
        "wrong_algorithm",
        "unsigned",
        "bad_signature",
    ],
)
def test_untrusted_or_incomplete_tokens_are_rejected(token_settings: Settings, case: str) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": "42",
        "role": "agent",
        "sid": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(hours=12),
        "iss": token_settings.jwt_issuer,
        "aud": token_settings.jwt_audience,
    }
    algorithm = "HS256"
    key = token_settings.jwt_secret_key.get_secret_value()
    if case == "expired":
        payload.update(iat=now - timedelta(days=2), exp=now - timedelta(days=1))
    elif case == "wrong_issuer":
        payload["iss"] = "other-application"
    elif case == "wrong_audience":
        payload["aud"] = "other-client"
    elif case == "missing_sid":
        del payload["sid"]
    elif case == "missing_exp":
        del payload["exp"]
    elif case == "numeric_sub":
        payload["sub"] = 42
    elif case == "invalid_role":
        payload["role"] = "superuser"
    elif case == "invalid_sid":
        payload["sid"] = "not-a-uuid"
    elif case == "future_iat":
        payload["iat"] = now + timedelta(hours=1)
    elif case == "wrong_algorithm":
        algorithm = "HS512"
    elif case == "unsigned":
        algorithm, key = "none", ""
    elif case == "bad_signature":
        key = secrets.token_urlsafe(64)
    token = jwt.encode(payload, key, algorithm=algorithm)
    with pytest.raises(ApiException) as error:
        decode_access_token(token, token_settings)
    assert error.value.code == ErrorCode.UNAUTHORIZED


def test_signing_key_is_required_and_weak_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret_key="short")
    with pytest.raises(ApiException) as error:
        create_access_token(1, "admin", str(uuid4()), Settings(_env_file=None, jwt_secret_key=None))
    assert error.value.code == ErrorCode.SERVICE_BUSY


async def test_limiter_expires_and_does_not_evict_an_active_lockout() -> None:
    clock = [100.0]
    limiter = LoginLimiter(max_entries=1, clock=lambda: clock[0])
    for _ in range(5):
        async with limiter.attempt("127.0.0.1", "admin") as attempt:
            attempt.failed()
    for username in ("admin", "another-user"):
        with pytest.raises(ApiException) as error:
            async with limiter.attempt("127.0.0.1", username):
                pytest.fail("Active lockouts must not be evicted or bypassed")
        assert error.value.code == ErrorCode.RATE_LIMITED
    clock[0] += 301
    async with limiter.attempt("127.0.0.1", "another-user") as attempt:
        attempt.succeeded()


async def test_parallel_failed_attempts_cannot_race_past_the_limit() -> None:
    limiter = LoginLimiter()
    verified = []

    async def fail_login() -> None:
        try:
            async with limiter.attempt("127.0.0.1", "admin") as attempt:
                await asyncio.sleep(0)
                verified.append(1)
                attempt.failed()
        except ApiException as error:
            assert error.code == ErrorCode.RATE_LIMITED

    await asyncio.gather(*(fail_login() for _ in range(10)))
    assert len(verified) == 5


def test_cache_ttl_and_explicit_invalidation() -> None:
    clock = [100.0]
    cache = SessionCache(clock=lambda: clock[0])
    cache.set(1, None)
    assert cache.get(1) == (True, None)
    clock[0] += 13
    assert cache.get(1) == (False, None)
    cache.set(1, None)
    cache.invalidate(1)
    assert cache.get(1) == (False, None)


async def test_cancelled_hashing_keeps_its_concurrency_slot_until_the_thread_finishes() -> None:
    passwords = PasswordService(concurrency=1)
    started, release = threading.Event(), threading.Event()

    def slow_work() -> str:
        started.set()
        release.wait(timeout=2)
        return "finished"

    first = asyncio.create_task(passwords._run(slow_work))
    assert await asyncio.to_thread(started.wait, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(passwords._run(lambda: "second"))
    try:
        await asyncio.sleep(0.01)
        assert not second.done()
    finally:
        release.set()
    assert await asyncio.wait_for(second, 1) == "second"
