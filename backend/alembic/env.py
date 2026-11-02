import asyncio

from alembic.autogenerate.api import AutogenContext
from sqlalchemy import Connection

from alembic import context
from app.core.config import Settings
from app.core.db import create_database_engine
from app.models import Base
from app.models.base import UTCDateTime

target_metadata = Base.metadata


def render_item(kind: str, item: object, autogen_context: AutogenContext) -> str | bool:
    if kind == "type" and isinstance(item, UTCDateTime):
        autogen_context.imports.add("from sqlalchemy.dialects import mysql")
        return "mysql.DATETIME(fsp=3)"
    return False


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_database_engine(Settings())
    if engine is None:
        raise RuntimeError("DATABASE_URL must be configured before running migrations")
    try:
        async with asyncio.timeout(60), engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError(
        "Offline migrations are not enabled; use the verified TLS database connection"
    )
else:
    asyncio.run(run_online())
