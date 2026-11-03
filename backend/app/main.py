from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.auth import router as auth_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.folders import router as folders_router
from app.api.v1.health import HealthResponse, health
from app.api.v1.health import router as health_router
from app.api.v1.notifications import router as notifications_router
from app.core.config import Settings
from app.core.db import create_database_engine
from app.core.errors import ApiCORSMiddleware, ApiErrorMiddleware, register_error_handlers
from app.core.request_context import RequestContextMiddleware
from app.core.timeouts import RequestTimeoutMiddleware
from app.schemas.contracts import ApiError
from app.services.auth import AuthService
from app.services.booking_reads import BookingReads
from app.services.booking_writes import BookingWrites
from app.services.folders import FolderService
from app.services.key_index import KeyIndex
from app.services.search_limiter import SearchLimiter
from app.services.session_events import SessionEvents
from app.services.snapshot_cache import SnapshotCache
from app.services.stations import StationService
from app.services.storage import NullStorage
from app.services.ws_manager import WebSocketManager


def create_app(
    settings: Settings | None = None,
    *,
    session_events: SessionEvents | None = None,
) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.engine = create_database_engine(config)
        application.state.auth = AuthService(application.state.engine, config, session_events)
        cache = SnapshotCache(config.snapshot_cache_max_entries, config.snapshot_cache_ttl_seconds)
        stations = StationService(application.state.engine, config)
        index = KeyIndex(
            application.state.engine, config, cache, on_group_created=stations.invalidate
        )
        application.state.stations = stations
        application.state.search_limiter = SearchLimiter(
            config.search_max_requests,
            config.search_rate_window_seconds,
            config.search_rate_max_entries,
        )
        application.state.snapshot_cache = cache
        application.state.key_index = index
        application.state.ws_manager = WebSocketManager()
        application.state.storage = NullStorage()
        application.state.bookings = BookingReads(application.state.engine, config, index, cache)
        application.state.booking_writes = BookingWrites(
            application.state.engine, config, index, cache, application.state.ws_manager
        )
        application.state.folders = FolderService(
            application.state.engine, config, index, application.state.bookings, stations
        )
        index.start()
        try:
            yield
        finally:
            await index.stop()
            if application.state.engine is not None:
                await application.state.engine.dispose()

    application = FastAPI(
        title="Booking Tracker API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if config.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.app_env != "production" else None,
        responses={status: {"model": ApiError} for status in (422, 500, 504)},
    )
    application.state.settings = config
    register_error_handlers(application)
    application.add_middleware(ApiErrorMiddleware)
    application.add_middleware(
        RequestTimeoutMiddleware, timeout_seconds=config.request_timeout_seconds
    )
    application.add_middleware(
        ApiCORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "If-None-Match"],
        expose_headers=["X-Request-ID", "Retry-After", "Server-Timing", "ETag"],
    )
    application.add_middleware(RequestContextMiddleware)

    application.add_api_route(
        "/health", health, methods=["GET"], response_model=HealthResponse, tags=["health"]
    )
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(bookings_router, prefix="/api/v1")
    application.include_router(notifications_router, prefix="/api/v1")
    application.include_router(folders_router, prefix="/api/v1")
    return application


app = create_app()
