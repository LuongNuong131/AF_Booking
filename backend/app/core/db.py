import asyncio
import ssl
import time

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings
from app.core.request_context import query_timing


def create_database_engine(settings: Settings, telemetry=None) -> AsyncEngine | None:
    if settings.database_url is None:
        return None
    connect_args: dict[str, object] = {
        "connect_timeout": settings.db_connect_timeout_seconds,
        "charset": "utf8mb4",
        "init_command": "SET time_zone = '+00:00'",
    }
    if settings.database_ssl:
        # The default context validates both the certificate chain and hostname.
        connect_args["ssl"] = ssl.create_default_context(cafile=settings.database_ssl_ca)
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        connect_args=connect_args,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_timeout=settings.db_pool_timeout_seconds,
        hide_parameters=True,
        isolation_level="READ COMMITTED",
    )

    engine.sync_engine._booking_default_isolation = "READ COMMITTED"

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_query(conn, cursor, statement, parameters, context, executemany):
        context._booking_started = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after_query(conn, cursor, statement, parameters, context, executemany):
        elapsed = (time.perf_counter() - context._booking_started) * 1000
        collector = telemetry or getattr(engine.sync_engine, "_booking_telemetry", None)
        if collector is not None:
            collector.query(statement, elapsed)
        timing = query_timing.get()
        if timing is not None:
            timing.milliseconds += elapsed

    @event.listens_for(engine.sync_engine, "connect")
    def set_select_timeout(connection, record) -> None:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT VERSION()")
            version = str(cursor.fetchone()[0]).lower()
            cursor.execute(
                "SET SESSION innodb_lock_wait_timeout = %s",
                (settings.db_lock_wait_timeout_seconds,),
            )
            value = (
                settings.db_query_timeout_ms / 1000
                if "mariadb" in version
                else settings.db_query_timeout_ms
            )
            try:
                if "mariadb" in version:
                    cursor.execute("SET SESSION max_statement_time = %s", (value,))
                else:
                    cursor.execute("SET SESSION max_execution_time = %s", (value,))
            except Exception as exc:
                # TiDB may lack this variable; access/network errors must still propagate.
                if not getattr(exc, "args", ()) or exc.args[0] not in {1193, 1235}:
                    raise
        finally:
            cursor.close()

    return engine


async def ping_database(engine: AsyncEngine, timeout_seconds: float) -> None:
    # SQLAlchemy invalidates an async connection when a driver operation is cancelled.
    async with asyncio.timeout(timeout_seconds), engine.connect() as connection:
        result = await connection.execute(text("SELECT 1"))
        if result.scalar_one() != 1:
            raise RuntimeError("Unexpected database probe result")
