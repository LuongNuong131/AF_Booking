"""Export every application table into a typed ZIP snapshot, optionally AES-256-GCM encrypted."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.backup import BackupError, encryption_key, export_snapshot  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.db import create_database_engine  # noqa: E402


async def run(args):
    settings = Settings(
        _env_file=None, app_env="development", db_pool_size=1, db_query_timeout_ms=30000
    )
    engine = create_database_engine(settings)
    if engine is None:
        raise BackupError("Provide DATABASE_URL through the protected process environment.")
    key = encryption_key(os.environ.get("BACKUP_ENCRYPTION_KEY")) if args.encrypt else None
    try:
        async with asyncio.timeout(args.timeout):
            result = await export_snapshot(engine, args.output, key=key)
        print(json.dumps(result))
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--encrypt", action="store_true")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as error:
        # DBAPI exception strings can contain credentials, SQL and private row values.
        print(
            str(error)
            if isinstance(error, BackupError)
            else f"Backup failed ({type(error).__name__}).",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
