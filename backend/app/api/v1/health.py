from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import ping_database
from app.core.errors import error_response
from app.schemas.contracts import ApiError, ErrorCode

router = APIRouter(tags=["health"])


@router.get("/health/warm")
async def warm(request: Request):
    request.app.state.warm_limiter.check(request.client.host if request.client else "unknown")
    return await ready(request)


@router.get("/health/db")
async def database_health(request: Request):
    request.app.state.db_health_limiter.check(request.client.host if request.client else "unknown")
    return await ready(request)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "booking-tracker-api"


class ReadinessResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["connected"]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Process liveness: does not require a configured or available database."""
    return HealthResponse()


@router.get("/ready", response_model=ReadinessResponse, responses={503: {"model": ApiError}})
async def ready(request: Request) -> ReadinessResponse | JSONResponse:
    engine = request.app.state.engine
    if engine is None:
        return error_response(ErrorCode.SERVICE_BUSY, details={"database": "not_configured"})
    settings = request.app.state.settings
    timeout = min(settings.db_query_timeout_ms / 1000, settings.request_timeout_seconds * 0.75)
    try:
        await ping_database(engine, timeout_seconds=timeout)
    except (TimeoutError, SQLAlchemyError, OSError):
        return error_response(ErrorCode.SERVICE_BUSY, details={"database": "unavailable"})
    return ReadinessResponse(status="ok", database="connected")
