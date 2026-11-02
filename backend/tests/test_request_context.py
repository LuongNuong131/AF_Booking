import logging
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.request_context import request_id
from app.main import create_app


def test_root_health_never_queries_the_database() -> None:
    engine = AsyncMock()
    with (
        patch("app.main.create_database_engine", return_value=engine),
        TestClient(create_app()) as client,
    ):
        assert client.get("/health").json() == {"status": "ok", "service": "booking-tracker-api"}
        engine.connect.assert_not_called()


def test_request_ids_are_returned_logged_and_do_not_log_tokens_or_query_strings(caplog) -> None:
    config = Settings(_env_file=None, app_env="test", jwt_secret_key=None)
    with (
        caplog.at_level(logging.INFO, logger="uvicorn.error"),
        TestClient(create_app(config)) as client,
    ):
        response = client.get(
            "/api/v1/auth/me?token=do-not-log-this",
            headers={
                "X-Request-ID": "auth-check-123",
                "Authorization": "Bearer do-not-log-this-either",
            },
        )
        assert response.status_code == 503
        assert response.headers["x-request-id"] == "auth-check-123"
        assert response.headers["cache-control"] == "no-store"
        assert "request_id=auth-check-123" in caplog.text
        assert "do-not-log-this" not in caplog.text
        generated = client.get("/health", headers={"X-Request-ID": "x" * 100})
        UUID(generated.headers["x-request-id"])
    assert request_id.get() == "-"


def test_auth_requires_configuration_and_has_no_registration_route() -> None:
    config = Settings(_env_file=None, app_env="test", jwt_secret_key=None)
    with TestClient(create_app(config)) as client:
        response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "test"})
        assert response.status_code == 503
        assert response.json()["code"] == "SERVICE_BUSY"
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.post("/api/v1/auth/register", json={}).status_code == 404
        assert client.get("/api/v1/bookings").status_code == 404
