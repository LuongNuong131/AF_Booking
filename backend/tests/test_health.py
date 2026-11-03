import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.main import create_app


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, app_env="test", **overrides)


def test_liveness_and_unconfigured_readiness() -> None:
    with TestClient(create_app(settings())) as client:
        assert client.get("/api/v1/health").json() == {
            "status": "ok",
            "service": "booking-tracker-api",
        }
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["code"] == "SERVICE_BUSY"
        assert response.json()["details"] == {"database": "not_configured"}
        assert response.headers["retry-after"] == "5"


def test_readiness_checks_the_database_and_disposes_the_pool() -> None:
    engine = AsyncMock()
    with (
        patch("app.main.create_database_engine", return_value=engine),
        patch("app.api.v1.health.ping_database", new_callable=AsyncMock) as ping,
        TestClient(create_app(settings())) as client,
    ):
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "connected"}
        ping.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize("error", [TimeoutError(), OperationalError("probe", {}, Exception())])
def test_readiness_failure_returns_retryable_error_without_details(error: Exception) -> None:
    with (
        patch("app.main.create_database_engine", return_value=AsyncMock()),
        patch("app.api.v1.health.ping_database", new_callable=AsyncMock, side_effect=error),
        TestClient(create_app(settings())) as client,
    ):
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["code"] == "SERVICE_BUSY"
        assert response.json()["details"] == {"database": "unavailable"}
        assert response.headers["retry-after"] == "5"


def test_cors_allows_only_the_configured_frontend() -> None:
    with TestClient(create_app(settings(cors_origins=["https://tracker.example.com"]))) as client:
        for origin, expected in [
            ("https://tracker.example.com", 200),
            ("https://other.example", 403),
        ]:
            response = client.options(
                "/api/v1/ready", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
            )
            assert response.status_code == expected
            if expected == 403:
                assert response.json()["code"] == "FORBIDDEN"
        response = client.get("/api/v1/ready", headers={"Origin": "https://tracker.example.com"})
        assert response.headers["access-control-allow-origin"] == "https://tracker.example.com"


def test_slow_request_times_out_and_is_cancelled() -> None:
    application = create_app(settings(request_timeout_seconds=0.05))
    cancelled = False

    @application.get("/slow")
    async def slow(request: Request) -> dict[str, str]:
        nonlocal cancelled
        try:
            await asyncio.sleep(5)
        finally:
            cancelled = True
        return {"status": "unexpected"}

    with TestClient(application) as client:
        started = time.monotonic()
        response = client.get("/slow", headers={"Origin": "http://localhost:5173"})
        assert time.monotonic() - started < 1
        assert response.status_code == 504
        assert response.json()["code"] == "REQUEST_TIMEOUT"
        assert "error" not in response.json()
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert cancelled


def test_production_hides_api_documentation() -> None:
    config = Settings(
        _env_file=None, app_env="production", cors_origins=["https://tracker.example"]
    )
    with TestClient(create_app(config)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_warmup_opens_pool_and_rate_limits_ip_without_auth():
    with (
        patch("app.main.create_database_engine", return_value=AsyncMock()),
        patch("app.api.v1.health.ping_database", new_callable=AsyncMock) as ping,
        TestClient(create_app(settings())) as client,
    ):
        for _ in range(10):
            response = client.get("/api/v1/health/warm")
            assert response.status_code == 200
            assert "total;dur=" in response.headers["server-timing"]
            assert "db;dur=" in response.headers["server-timing"]
        assert ping.await_count == 10
        response = client.get("/api/v1/health/warm")
        assert response.status_code == 429
        assert response.json()["code"] == "RATE_LIMITED"
        assert int(response.headers["retry-after"]) > 0
        assert client.get("/health").status_code == 200
