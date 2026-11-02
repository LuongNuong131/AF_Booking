from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router as health_router
from app.core.config import Settings
from app.core.db import create_database_engine
from app.core.timeouts import RequestTimeoutMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.engine = create_database_engine(config)
        try:
            yield
        finally:
            if application.state.engine is not None:
                await application.state.engine.dispose()

    application = FastAPI(
        title="Booking Tracker API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if config.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if config.app_env != "production" else None,
    )
    application.state.settings = config
    application.add_middleware(
        RequestTimeoutMiddleware, timeout_seconds=config.request_timeout_seconds
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    application.include_router(health_router, prefix="/api/v1")
    return application


app = create_app()
