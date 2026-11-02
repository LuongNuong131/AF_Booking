"""Auth integration tests run against the Docker runner's isolated TLS database."""

import asyncio
import os
import re
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI
from sqlalchemy import delete, event, select, update

from alembic import command
from app.core.config import Settings
from app.core.deps import require_roles
from app.core.errors import ApiException
from app.core.security import create_access_token, decode_access_token
from app.main import create_app
from app.models import AuditLog, User
from app.schemas.contracts import ErrorCode
from app.services.audit import AuditContext
from app.services.auth import AuthService
from app.services.session_cache import CurrentUser

pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated auth test database supplied"
)
ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"


@dataclass
class RecordingEvents:
    calls: list[tuple[int, str, str]] = field(default_factory=list)
    fail: bool = False

    async def force_logout(self, user_id: int, session_id: str, reason: str) -> None:
        self.calls.append((user_id, session_id, reason))
        if self.fail:
            raise RuntimeError("Test transport failure")


@dataclass
class AuthRig:
    app: FastAPI
    client: httpx.AsyncClient
    password: str = field(repr=False)
    events: RecordingEvents

    @property
    def auth(self) -> AuthService:
        return self.app.state.auth

    async def login(self, username: str = "agent", password: str | None = None) -> httpx.Response:
        return await self.client.post(
            "/api/v1/auth/login",
            json={
                "username": username,
                "password": self.password if password is None else password,
            },
        )

    async def token(self, username: str = "agent") -> str:
        response = await self.login(username)
        assert response.status_code == 200
        return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def passwords() -> tuple[str, str]:
    password = secrets.token_urlsafe(24)
    return password, PasswordHasher().hash(password)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrated_database() -> None:
    from sqlalchemy.engine import make_url

    database = make_url(os.environ["SCHEMA_TEST_DATABASE_URL"]).database
    assert database.startswith("booking_schema_") and database.endswith("_test")
    await asyncio.to_thread(command.upgrade, Config(str(ALEMBIC_CONFIG_PATH)), "head")


@pytest_asyncio.fixture
async def rig(migrated_database: None, passwords: tuple[str, str]) -> AsyncIterator[AuthRig]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=os.environ["SCHEMA_TEST_DATABASE_URL"],
        database_ssl_ca=os.environ["SCHEMA_TEST_SSL_CA"],
        jwt_secret_key=secrets.token_urlsafe(64),
    )
    sink = RecordingEvents()
    app = create_app(settings, session_events=sink)

    @app.get("/test/admin")
    async def admin_only(
        user: Annotated[CurrentUser, Depends(require_roles("admin"))],
    ) -> dict[str, int]:
        return {"id": user.id}

    @app.get("/test/reports")
    async def reports(
        user: Annotated[CurrentUser, Depends(require_roles("admin", "qc"))],
    ) -> dict[str, int]:
        return {"id": user.id}

    async with app.router.lifespan_context(app):
        async with app.state.engine.begin() as connection:
            await connection.execute(delete(AuditLog))
            await connection.execute(delete(User))
            await connection.execute(
                User.__table__.insert(),
                [
                    {
                        "id": identifier,
                        "username": name,
                        "full_name": name.title(),
                        "role": role,
                        "is_active": active,
                        "password_hash": passwords[1],
                        "settings": {"timezone": "Asia/Ho_Chi_Minh"},
                    }
                    for identifier, name, role, active in [
                        (1, "admin", "admin", True),
                        (2, "qc", "qc", True),
                        (3, "agent", "agent", True),
                        (4, "disabled", "agent", False),
                    ]
                ],
            )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 8001)),
            base_url="http://testserver",
        ) as client:
            yield AuthRig(app, client, passwords[0], sink)


async def test_login_and_me_return_only_public_user_fields(rig: AuthRig) -> None:
    response = await rig.login()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 43200
    assert set(body["user"]) == {"id", "username", "full_name", "role", "is_active", "settings"}
    assert body["user"]["role"] == "agent"
    me = await rig.client.get("/api/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json() == body["user"]
    assert "password_hash" not in me.text and "current_session_id" not in me.text
    assert rig.password not in response.text


@pytest.mark.parametrize(
    "username,password_kind",
    [
        ("agent", "wrong"),
        ("missing", "correct"),
        ("disabled", "correct"),
    ],
)
async def test_wrong_unknown_and_disabled_login_use_the_same_error(
    rig: AuthRig,
    username: str,
    password_kind: str,
) -> None:
    response = await rig.login(
        username, rig.password if password_kind == "correct" else "incorrect"
    )
    assert response.status_code == 401
    assert response.json() == {"code": "UNAUTHORIZED", "message": "Invalid username or password."}
    assert response.headers["www-authenticate"] == "Bearer"
    async with rig.auth.transaction() as session:
        audit = await session.scalar(select(AuditLog).where(AuditLog.action == "login_failed"))
        assert audit is not None and audit.meta["username"] == username
        assert audit.user_id is None  # A failed attempt does not establish an authenticated actor.


async def test_second_login_invalidates_a_warm_cached_session(rig: AuthRig) -> None:
    first = await rig.token()
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(first))).status_code == 200
    second = await rig.token()
    assert first != second
    old = await rig.client.get("/api/v1/auth/me", headers=bearer(first))
    assert old.status_code == 401 and old.json()["code"] == "SESSION_REPLACED"
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(second))).status_code == 200
    first_sid = decode_access_token(first, rig.auth.settings).sid
    assert rig.events.calls == [(3, first_sid, "new_login")]
    async with rig.auth.transaction() as session:
        replaced = (
            await session.scalars(select(AuditLog).where(AuditLog.action == "session_replaced"))
        ).all()
        assert len(replaced) == 1


async def test_role_dependencies_use_current_database_role_not_a_token_role(rig: AuthRig) -> None:
    agent = await rig.token()
    admin = await rig.token("admin")
    qc = await rig.token("qc")
    assert (await rig.client.get("/test/admin", headers=bearer(agent))).status_code == 403
    assert (await rig.client.get("/test/admin", headers=bearer(qc))).status_code == 403
    assert (await rig.client.get("/test/admin", headers=bearer(admin))).status_code == 200
    assert (await rig.client.get("/test/reports", headers=bearer(qc))).status_code == 200
    claims = decode_access_token(agent, rig.auth.settings)
    misleading = create_access_token(3, "admin", claims.sid, rig.auth.settings)
    assert (await rig.client.get("/test/admin", headers=bearer(misleading))).status_code == 403
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(update(User).where(User.id == 1).values(role="agent"))
    await rig.auth.invalidate_user(1)
    assert (await rig.client.get("/test/admin", headers=bearer(admin))).status_code == 403


async def test_logout_revokes_cached_tokens_and_a_stale_logout_cannot_clear_a_new_login(
    rig: AuthRig,
) -> None:
    first = await rig.token()
    old_caller = await rig.auth.principal(3)
    second = await rig.token()
    with pytest.raises(ApiException) as error:
        await rig.auth.logout(old_caller, AuditContext())
    assert error.value.code == ErrorCode.SESSION_REPLACED
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(second))).status_code == 200
    assert (await rig.client.post("/api/v1/auth/logout", headers=bearer(second))).status_code == 200
    logged_out = await rig.client.get("/api/v1/auth/me", headers=bearer(second))
    assert logged_out.status_code == 401 and logged_out.json()["code"] == "SESSION_REPLACED"
    assert rig.events.calls[-1] == (3, decode_access_token(second, rig.auth.settings).sid, "logout")
    assert first != second


async def test_disabled_user_and_kick_helpers_invalidate_cache_immediately(rig: AuthRig) -> None:
    token = await rig.token()
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 200
    await rig.auth.set_user_active(3, False, actor_id=1)
    rejected = await rig.client.get("/api/v1/auth/me", headers=bearer(token))
    assert rejected.status_code == 401 and rejected.json()["code"] == "UNAUTHORIZED"
    assert (await rig.login()).status_code == 401
    assert rig.events.calls[-1][2] == "user_disabled"
    await rig.auth.set_user_active(3, True, actor_id=1)
    fresh = await rig.token()
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(fresh))).status_code == 200
    assert await rig.auth.kick_session(3, actor_id=1)
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(fresh))).status_code == 401
    assert rig.events.calls[-1] == (
        3,
        decode_access_token(fresh, rig.auth.settings).sid,
        "admin_kick",
    )


async def test_password_change_checks_old_password_and_revokes_the_session(rig: AuthRig) -> None:
    token = await rig.token()
    new_password = secrets.token_urlsafe(24)
    bad = await rig.client.post(
        "/api/v1/auth/change-password",
        headers=bearer(token),
        json={
            "old_password": "incorrect",
            "new_password": new_password,
        },
    )
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_ERROR"
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 200
    good = await rig.client.post(
        "/api/v1/auth/change-password",
        headers=bearer(token),
        json={
            "old_password": rig.password,
            "new_password": new_password,
        },
    )
    assert good.status_code == 200
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 401
    assert (await rig.login()).status_code == 401
    assert (await rig.login(password=new_password)).status_code == 200
    async with rig.auth.transaction() as session:
        user = await session.get(User, 3)
        assert user.password_hash.startswith("$argon2id$")
        assert PasswordHasher().verify(user.password_hash, new_password)
        logs = (await session.scalars(select(AuditLog))).all()
        assert {"password_changed", "session_kicked"} <= {row.action for row in logs}
        assert all(
            rig.password not in str(row.meta) and new_password not in str(row.meta) for row in logs
        )


async def test_stale_password_change_cannot_overwrite_a_concurrent_login(
    rig: AuthRig, monkeypatch
) -> None:
    token = await rig.token()
    ready, release = asyncio.Event(), asyncio.Event()
    original_hash = rig.auth.passwords.hash

    async def paused_hash(password: str) -> str:
        result = await original_hash(password)
        ready.set()
        await release.wait()
        return result

    monkeypatch.setattr(rig.auth.passwords, "hash", paused_hash)
    changing = asyncio.create_task(
        rig.client.post(
            "/api/v1/auth/change-password",
            headers=bearer(token),
            json={"old_password": rig.password, "new_password": secrets.token_urlsafe(24)},
        )
    )
    try:
        await asyncio.wait_for(ready.wait(), 3)
        fresh = await rig.token()
    finally:
        release.set()
    response = await changing
    assert response.status_code == 401 and response.json()["code"] == "SESSION_REPLACED"
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(fresh))).status_code == 200
    async with rig.auth.transaction() as session:
        assert PasswordHasher().verify((await session.get(User, 3)).password_hash, rig.password)


async def test_login_limit_is_five_failures_then_five_minutes_and_handles_aliases(
    rig: AuthRig,
) -> None:
    for username in ("agent", "AGENT", "ágent", "agent", "agent"):
        assert (await rig.login(username, "incorrect")).status_code == 401
    blocked = await rig.login("AGENT")
    assert blocked.status_code == 429 and blocked.json()["code"] == "RATE_LIMITED"
    assert 1 <= int(blocked.headers["retry-after"]) <= 300
    assert (await rig.login("admin")).status_code == 200
    now = time.monotonic() + 301
    rig.auth.limiter.clock = lambda: now
    assert (await rig.login()).status_code == 200


async def test_cached_me_does_not_query_db_on_every_request_and_expires(rig: AuthRig) -> None:
    token = await rig.token()
    clock = [100.0]
    rig.auth.cache.clock = lambda: clock[0]
    selects = []

    def track(connection, cursor, statement, parameters, context, executemany) -> None:
        if re.search(r"\bfrom\s+users\b", statement.lower()):
            selects.append(statement)

    event.listen(rig.app.state.engine.sync_engine, "before_cursor_execute", track)
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 200
    first = len(selects)
    assert first == 1
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(token))).status_code == 200
    assert len(selects) == first
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(update(User).where(User.id == 3).values(full_name="Updated Agent"))
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(token))).json()[
        "full_name"
    ] == "Agent"
    clock[0] += 13
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(token))).json()[
        "full_name"
    ] == "Updated Agent"
    assert len(selects) == first + 1


async def test_audit_context_records_login_failure_logout_and_request_id(rig: AuthRig) -> None:
    response = await rig.client.post(
        "/api/v1/auth/login",
        headers={"X-Request-ID": "audit-login-123"},
        json={"username": "agent", "password": rig.password},
    )
    token = response.json()["access_token"]
    await rig.login(password="incorrect")
    await rig.client.post("/api/v1/auth/logout", headers=bearer(token))
    async with rig.auth.transaction() as session:
        rows = (await session.scalars(select(AuditLog).order_by(AuditLog.id))).all()
        assert [row.action for row in rows] == ["login_success", "login_failed", "logout"]
        assert rows[0].meta["request_id"] == "audit-login-123"
        assert all(row.ip == "127.0.0.1" for row in rows)
        assert all(rig.password not in str(row.meta) and token not in str(row.meta) for row in rows)


async def test_concurrent_logins_leave_exactly_one_valid_session(rig: AuthRig) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=rig.app, client=("127.0.0.2", 8002)),
        base_url="http://testserver",
    ) as other:
        responses = await asyncio.gather(
            rig.login(),
            other.post("/api/v1/auth/login", json={"username": "agent", "password": rig.password}),
        )
    assert all(response.status_code == 200 for response in responses)
    checks = [
        await rig.client.get("/api/v1/auth/me", headers=bearer(r.json()["access_token"]))
        for r in responses
    ]
    assert sorted(check.status_code for check in checks) == [200, 401]
    assert (
        next(check for check in checks if check.status_code == 401).json()["code"]
        == "SESSION_REPLACED"
    )


async def test_transport_failure_does_not_restore_a_revoked_session(rig: AuthRig) -> None:
    first = await rig.token()
    rig.events.fail = True
    second = await rig.token()
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(first))).status_code == 401
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(second))).status_code == 200


async def test_login_audit_failure_rolls_back_the_session_change(rig: AuthRig, monkeypatch) -> None:
    first = await rig.token()
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(first))).status_code == 200

    def unavailable_audit(*args, **kwargs) -> None:
        raise RuntimeError("Simulated audit failure")

    monkeypatch.setattr("app.services.auth.record_audit", unavailable_audit)
    response = await rig.login()
    assert response.status_code == 500 and response.json()["code"] == "INTERNAL"
    assert (await rig.client.get("/api/v1/auth/me", headers=bearer(first))).status_code == 200
    assert not rig.events.calls
