import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ApiException
from app.main import create_app
from app.schemas.contracts import ErrorCode, NoteSaveRequest


def application() -> FastAPI:
    return create_app(Settings(_env_file=None, app_env="test"))


def test_not_found_and_wrong_method_use_the_contract() -> None:
    with TestClient(application()) as client:
        missing = client.get("/api/v1/not-a-route")
        assert missing.status_code == 404
        assert missing.json() == {
            "code": "NOT_FOUND",
            "message": "The requested resource was not found.",
        }
        wrong_method = client.post("/api/v1/health")
        assert wrong_method.status_code == 405
        assert wrong_method.json()["code"] == "VALIDATION_ERROR"
        assert "GET" in wrong_method.headers["allow"]


def test_validation_errors_do_not_echo_request_secrets() -> None:
    app = application()

    @app.post("/contract-test/note")
    async def validate_note(body: NoteSaveRequest) -> NoteSaveRequest:
        return body

    with TestClient(app) as client:
        response = client.post(
            "/contract-test/note",
            json={
                "status_code": "DYNAMIC_STATUS",
                "note": "private note text",
                "expected_version": "private-input-value",
                "client_request_id": "private-invalid-uuid",
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert len(body["details"]["errors"]) == 2
        assert all(set(error) == {"loc", "type"} for error in body["details"]["errors"])
        assert "private" not in response.text
        schema = client.get("/openapi.json").json()
        model = schema["paths"]["/contract-test/note"]["post"]["responses"]["422"]
        assert model["content"]["application/json"]["schema"]["$ref"].endswith("/ApiError")


@pytest.mark.parametrize(
    "code,status",
    [
        (ErrorCode.SESSION_REPLACED, 401),
        (ErrorCode.FORBIDDEN, 403),
        (ErrorCode.VERSION_CONFLICT, 409),
        (ErrorCode.INVOICE_INVALID, 422),
        (ErrorCode.RATE_LIMITED, 429),
        (ErrorCode.SERVICE_BUSY, 503),
    ],
)
def test_domain_errors_preserve_their_code_status_and_details(code: ErrorCode, status: int) -> None:
    app = application()

    @app.get("/contract-test/error")
    async def domain_error() -> None:
        raise ApiException(code, details={"last_note_preview": None, "version": 2})

    with TestClient(app) as client:
        response = client.get("/contract-test/error")
        assert response.status_code == status
        assert response.json()["code"] == code.value
        assert response.json()["details"] == {"last_note_preview": None, "version": 2}
        if code == ErrorCode.SERVICE_BUSY:
            assert response.headers["retry-after"] == "5"


def test_authentication_headers_survive_http_error_conversion() -> None:
    app = application()

    @app.get("/contract-test/auth")
    async def auth_error() -> None:
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})

    with TestClient(app) as client:
        response = client.get("/contract-test/auth")
        assert response.json()["code"] == "UNAUTHORIZED"
        assert response.headers["www-authenticate"] == "Bearer"


def test_explicit_retry_after_is_preserved_case_insensitively() -> None:
    app = application()

    @app.get("/contract-test/busy")
    async def busy() -> None:
        raise ApiException(ErrorCode.SERVICE_BUSY, headers={"retry-after": "7"})

    with TestClient(app) as client:
        response = client.get("/contract-test/busy")
        assert response.status_code == 503
        assert response.headers.get_list("retry-after") == ["7"]


def test_internal_errors_are_safe_and_have_cors_headers() -> None:
    app = application()

    @app.get("/contract-test/crash")
    async def crash() -> None:
        raise RuntimeError("database-password-and-private-sql")

    with TestClient(app) as client:
        response = client.get("/contract-test/crash", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 500
        assert response.json() == {
            "code": "INTERNAL",
            "message": "An unexpected error occurred. Please try again.",
        }
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert "database-password" not in response.text
