"""Security properties which do not require a database."""

import ast
import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApiException
from app.core.http_security import BodyLimitMiddleware
from app.core.security import validate_password
from app.main import create_app
from app.services.login_limiter import LoginLimiter
from app.utils.booking_key import normalize, parse
from app.utils.search_query import classify_query
from app.utils.text import clean_note


@pytest.mark.parametrize(
    "secret",
    [
        " " * 32,
        "short",
        "change-me-" * 5,
        "your-super-secret-signing-key-for-development",
        "0" * 32,
    ],
)
def test_rejects_weak_or_default_jwt_at_configuration(secret):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret_key=secret)


def test_password_policy_and_control_normalization():
    for password in ("short", "USERACCOUNT123"):
        with pytest.raises(ApiException):
            validate_password(password, "UserAccount123")
    validate_password("Valid-pass-123", "UserAccount123")
    assert clean_note("A\x00\u202eB\r\nC") == "AB\nC"
    assert parse("CW1234567-\x00RDU-2609") is None


@pytest.mark.parametrize(
    "value", ["X" * 101, "<script>alert(1)</script>" * 10000, "' OR 1=1 --" * 10000]
)
def test_key_and_search_reject_before_normalization(value):
    with patch(
        "app.utils.booking_key.unicodedata.category",
        side_effect=AssertionError("Must not normalize"),
    ):
        assert parse(value) is None and normalize(value) == ""
    with patch(
        "app.utils.search_query.normalize_search", side_effect=AssertionError("Must not normalize")
    ):
        assert classify_query(value).kind == "none"


async def test_independent_ip_and_username_limits_and_numeric_retry():
    clock = [100.0]
    limiter = LoginLimiter(clock=lambda: clock[0])
    for n in range(5):
        async with limiter.attempt(f"192.0.2.{n}", "shared-name") as attempt:
            attempt.failed()
    with pytest.raises(ApiException) as error:
        async with limiter.attempt("192.0.2.99", "SHARED-NAME"):
            pass
    assert (
        error.value.code.value == "RATE_LIMITED" and error.value.headers["Retry-After"].isdecimal()
    )
    limiter = LoginLimiter(clock=lambda: clock[0])
    for n in range(5):
        async with limiter.attempt("192.0.2.1", f"name-{n}") as attempt:
            attempt.failed()
    with pytest.raises(ApiException):
        limiter.check_ip("192.0.2.1")
    clock[0] += 301
    async with limiter.attempt("192.0.2.1", "next-user") as attempt:
        attempt.succeeded()


def test_body_limit_and_headers_cover_unauthorized_and_not_found():
    settings = Settings(
        _env_file=None, app_env="test", scheduler_enabled=False, max_request_body_bytes=64
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/auth/login", content=b"x" * 65, headers={"Origin": "http://localhost:5173"}
        )
        assert response.status_code == 413 and response.json()["code"] == "PAYLOAD_TOO_LARGE"
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        for checked in (
            response,
            client.get("/api/v1/auth/me"),
            client.get("/api/v1/not-a-route"),
        ):
            assert checked.headers["x-frame-options"] == "DENY"
            assert checked.headers["x-content-type-options"] == "nosniff"
            assert checked.headers["cache-control"] == "no-store"


def test_runtime_sql_never_interpolates_text_or_execution_arguments():
    root = Path(__file__).resolve().parents[1] / "app"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if name in {"text", "execute", "executemany"}:
                    assert not isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)), str(path)


@pytest.mark.parametrize("declared", [None, b"1"])
async def test_chunked_body_cannot_bypass_limit_with_missing_or_false_content_length(declared):
    reached = False

    async def downstream(scope, receive, send):
        nonlocal reached
        reached = True

    messages = iter(
        [
            {"type": "http.request", "body": b"a" * 32, "more_body": True},
            {"type": "http.request", "body": b"b" * 33, "more_body": False},
        ]
    )
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    headers = [] if declared is None else [(b"content-length", declared)]
    scope = {"type": "http", "method": "POST", "path": "/api/v1/auth/login", "headers": headers}
    async with asyncio.timeout(1):
        await BodyLimitMiddleware(downstream, max_bytes=64)(scope, receive, send)
    assert not reached and sent[0]["status"] == 413


def test_jwt_secret_alias_is_accepted_without_exposing_value(monkeypatch):
    import secrets

    value = secrets.token_urlsafe(48)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET", value)
    settings = Settings(_env_file=None)
    assert settings.jwt_secret_key.get_secret_value() == value
    assert value not in repr(settings)
