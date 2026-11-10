"""Durable, bounded object-storage cleanup after committed permanent deletions."""

from sqlalchemy import delete, select, update

from app.core.unit_of_work import transaction
from app.models import StorageGarbage


async def cleanup_storage(state):
    async with transaction(state.engine, state.settings) as session:
        rows = (
            await session.execute(
                select(StorageGarbage.id, StorageGarbage.storage_key)
                .order_by(StorageGarbage.id)
                .limit(20)
            )
        ).all()
    failed = False
    for row in rows:
        try:
            await state.storage.delete(row.storage_key)
        except Exception as error:
            failed = True
            async with transaction(state.engine, state.settings) as session:
                await session.execute(
                    update(StorageGarbage)
                    .where(StorageGarbage.id == row.id)
                    .values(attempts=StorageGarbage.attempts + 1, last_error=type(error).__name__)
                )
        else:
            async with transaction(state.engine, state.settings) as session:
                await session.execute(delete(StorageGarbage).where(StorageGarbage.id == row.id))
    if failed:
        raise RuntimeError("Some object deletions remain queued for retry")
