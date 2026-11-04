from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from starlette.middleware.gzip import GZipMiddleware

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.collaboration import router as collaboration_router
from app.api.v1.folders import router as folders_router
from app.api.v1.health import HealthResponse, health
from app.api.v1.health import router as health_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.operations import router as operations_router
from app.api.v1.realtime import router as realtime_router
from app.api.v1.tasks import router as tasks_router
from app.core.config import Settings
from app.core.db import create_database_engine
from app.core.errors import ApiCORSMiddleware, ApiErrorMiddleware, register_error_handlers
from app.core.request_context import RequestContextMiddleware, install_websocket_log_redaction
from app.core.timeouts import RequestTimeoutMiddleware
from app.schemas.contracts import ApiError
from app.services.admin import AdminService
from app.services.auth import AuthService
from app.services.booking_reads import BookingReads
from app.services.booking_writes import BookingWrites
from app.services.collaboration import CollaborationService
from app.services.daily_reports import DailyReports
from app.services.exports import ExportService
from app.services.folders import FolderService
from app.services.integrity import IntegrityService
from app.services.key_index import KeyIndex
from app.services.note_search import create_note_search
from app.services.push import PushService
from app.services.reports import ReportService
from app.services.scheduler import Scheduler
from app.services.search_limiter import SearchLimiter
from app.services.session_events import CombinedSessionEvents, SessionEvents
from app.services.snapshot_cache import SnapshotCache
from app.services.stale_reminders import StaleReminders
from app.services.stations import StationService
from app.services.storage import NullStorage
from app.services.tasks import TaskService
from app.services.telemetry import Telemetry
from app.services.ws_manager import WebSocketManager


def create_app(
    settings: Settings | None = None,
    *,
    session_events: SessionEvents | None = None,
) -> FastAPI:
    config = settings or Settings()
    install_websocket_log_redaction()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.telemetry = Telemetry(config.slow_query_threshold_ms)
        application.state.engine = create_database_engine(config)
        if application.state.engine is not None and hasattr(
            application.state.engine, "sync_engine"
        ):
            application.state.engine.sync_engine._booking_telemetry = application.state.telemetry
        ws_manager = WebSocketManager(config)
        events = (
            CombinedSessionEvents(ws_manager, session_events)
            if session_events is not None
            else ws_manager
        )
        application.state.auth = AuthService(application.state.engine, config, events)
        ws_manager.auth = application.state.auth
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
        application.state.warm_limiter = SearchLimiter(limit=10)
        application.state.snapshot_cache = cache
        application.state.key_index = index
        application.state.ws_manager = ws_manager
        ws_manager.health_status = application.state.telemetry.degraded
        application.state.lock_manager = ws_manager.locks
        application.state.storage = NullStorage()
        application.state.bookings = BookingReads(application.state.engine, config, index, cache)
        application.state.booking_writes = BookingWrites(
            application.state.engine, config, index, cache, application.state.ws_manager
        )
        application.state.collaboration = CollaborationService(
            application.state.engine, config, application.state.bookings, ws_manager
        )
        application.state.booking_writes.collaboration = application.state.collaboration
        application.state.folders = FolderService(
            application.state.engine, config, index, application.state.bookings, stations
        )
        application.state.tasks = TaskService(
            application.state.engine, config, application.state.auth, ws_manager
        )
        scheduler = Scheduler()
        application.state.note_search = create_note_search(application.state.engine, config)
        application.state.push = PushService(
            application.state.engine, config, application.state.auth, ws_manager
        )
        scheduler.status["push.delivery"] = application.state.push.job_state
        ws_manager.push = application.state.push
        application.state.push.start()

        last_health_degraded = False

        async def health_sample():
            nonlocal last_health_degraded
            previous = last_health_degraded
            await application.state.telemetry.sample(application.state.engine, config)
            current = application.state.telemetry.degraded()
            last_health_degraded = current
            if current != previous:
                for connection in list(ws_manager.connections.values()):
                    if connection.user.role == "admin":
                        await ws_manager.send_user(
                            connection.user.id, "system.health", {"degraded": current}
                        )

        scheduler.add_job(
            "system.sample",
            health_sample,
            interval=30,
            timeout=config.db_connect_timeout_seconds + 2,
        )
        application.state.reports = ReportService(application.state.engine, config)
        application.state.exports = ExportService(application.state.engine, config)
        application.state.daily_reports = DailyReports(
            application.state.engine, config, application.state.exports
        )
        scheduler.add_job(
            "reports.daily",
            application.state.daily_reports.tick,
            interval=60,
            timeout=config.export_timeout_seconds,
        )
        application.state.admin = AdminService(
            application.state.engine,
            config,
            application.state.auth,
            application.state.booking_writes,
            ws_manager,
            application.state.reports,
        )
        application.state.integrity = IntegrityService(
            application.state.engine, config, application.state.admin
        )
        scheduler.add_job(
            "integrity.nightly",
            application.state.integrity.tick,
            interval=30,
            timeout=config.scheduler_job_timeout_seconds,
        )
        stale_reminders = StaleReminders(application.state.engine, config, ws_manager)
        application.state.scheduler = scheduler
        application.state.stale_reminders = stale_reminders
        scheduler.add_job(
            "locks.expire", ws_manager.locks.sweep, interval=config.lock_sweep_interval_seconds
        )
        scheduler.add_job(
            "bookings.stale",
            stale_reminders.run,
            interval=config.stale_job_interval_seconds,
            timeout=config.scheduler_job_timeout_seconds,
        )
        scheduler.add_job(
            "tasks.due",
            application.state.tasks.due_job,
            interval=config.task_job_interval_seconds,
            timeout=config.scheduler_job_timeout_seconds,
        )
        index.start()
        if config.scheduler_enabled:
            scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()
            await application.state.integrity.stop()
            await application.state.push.stop()
            await ws_manager.stop()
            await index.stop()
            if application.state.engine is not None:
                await application.state.engine.dispose()

    application = FastAPI(
        title="Booking Tracker API",
        version=config.app_version,
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
        docs_url="/docs" if config.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.app_env != "production" else None,
        responses={status: {"model": ApiError} for status in (422, 500, 504)},
    )
    application.state.settings = config
    register_error_handlers(application)
    application.add_middleware(ApiErrorMiddleware)
    application.add_middleware(GZipMiddleware, minimum_size=500)
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
    application.include_router(realtime_router, prefix="/api/v1")
    application.include_router(tasks_router, prefix="/api/v1")
    application.include_router(admin_router, prefix="/api/v1")
    application.include_router(operations_router, prefix="/api/v1")
    application.include_router(collaboration_router, prefix="/api/v1")
    return application


app = create_app()
