import asyncio

from sqlalchemy import Connection, MetaData

from alembic import context
from app.core.config import Settings
from app.core.db import create_database_engine

# Business models will register their tables here in the schema implementation step.
target_metadata = MetaData()


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
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
