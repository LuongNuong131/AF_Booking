import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.core.config import Settings
from app.core.errors import ApiException
from app.core.request_context import request_id, request_path
from app.schemas.contracts import ErrorCode
from app.services import visibility  # noqa: F401

logger = logging.getLogger(__name__)


def error_number(error: DBAPIError) -> int | None:
    args = getattr(error.orig, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


async def cleanup(
    session: AsyncSession, connection: AsyncConnection | None, invalidate: bool
) -> None:
    try:
        if invalidate and connection is not None and not connection.closed:
            await connection.invalidate()
    finally:
        try:
            await session.rollback()
        finally:
            await session.close()


def consume_cleanup(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Database cleanup failed; connection was discarded")


@asynccontextmanager
async def transaction(
    engine: AsyncEngine | None,
    settings: Settings,
    *,
    seconds: float | None = None,
    retryable: bool = False,
    after_commit: Callable[[], None] | None = None,
    isolation_level: str = "READ COMMITTED",
) -> AsyncIterator[AsyncSession]:
    if engine is None:
        raise ApiException(ErrorCode.SERVICE_BUSY)
    session = AsyncSession(engine, expire_on_commit=False)
    connection = None
    error: BaseException | None = None
    budget = seconds if seconds is not None else settings.db_query_timeout_ms / 1000
    try:
        async with asyncio.timeout(budget):
            await session.begin()
            # A locking read may see a just-committed row after waiting. Subsequent snapshot
            # reads must see the same row, rather than an earlier REPEATABLE READ snapshot.
            # The owned pool already uses READ COMMITTED. Avoid setting/resetting the
            # same session isolation on every request; explicit snapshot reads still override it.
            default = getattr(engine.sync_engine, "_booking_default_isolation", None)
            connection = await session.connection(
                execution_options={}
                if default == isolation_level
                else {"isolation_level": isolation_level}
            )
            yield session
            await session.commit()
            if after_commit is not None:
                after_commit()
    except BaseException as caught:
        error = caught
        raise
    finally:
        code = error_number(error) if isinstance(error, DBAPIError) else None
        timed_out = isinstance(error, (TimeoutError, asyncio.CancelledError)) or code in {
            3024,
            1969,
            1317,
        }
        work = asyncio.create_task(cleanup(session, connection, timed_out))
        try:
            await asyncio.wait_for(asyncio.shield(work), 2)
        except (asyncio.CancelledError, TimeoutError):
            # Keep ownership until cleanup completes; never return this connection for reuse.
            work.add_done_callback(consume_cleanup)
            raise
        if timed_out:
            logger.warning(
                "request_id=%s database timeout route=%r seconds=%.3f",
                request_id.get(),
                request_path.get(),
                budget,
            )
        locking_select_expired = (
            isinstance(error, DBAPIError)
            and code in {3024, 1969, 1317}
            and "FOR UPDATE" in (error.statement or "").upper()
        )
        # MySQL can expire max_execution_time just before an equal lock-wait deadline.
        # A timed-out locking SELECT is also contention and should be retried as 503.
        if (
            isinstance(error, PoolTimeout)
            or locking_select_expired
            or (code in {1205, 1213} and not retryable)
        ):
            raise ApiException(ErrorCode.SERVICE_BUSY) from None
        if isinstance(error, TimeoutError) or code in {3024, 1969, 1317}:
            raise ApiException(ErrorCode.REQUEST_TIMEOUT) from None
        if isinstance(error, DBAPIError) and code not in {1062, 1205, 1213}:
            raise ApiException(ErrorCode.SERVICE_BUSY) from None
