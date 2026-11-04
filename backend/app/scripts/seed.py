"""Insert missing status rows and an environment-supplied admin without overwriting data."""

import argparse
import asyncio
from dataclasses import dataclass

from argon2 import PasswordHasher
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings
from app.core.db import create_database_engine
from app.models import Status, User


@dataclass(frozen=True)
class StatusSeed:
    code: str
    label: str
    sort_order: int
    is_done: bool = False
    suggest_task: bool = False
    invoice_required: bool = False
    note_required: bool = False
    default_task_days: int | None = None


# Position labels remain provisional; Prompt 4 requires notes for Rejection/Parking.
# Existing Admin-managed values are never changed on a subsequent seed run.
STATUS_SEEDS = (
    StatusSeed("DONE", "Done", 10, is_done=True, invoice_required=True),
    StatusSeed(
        "REJECTION", "Rejection", 20, suggest_task=True, note_required=True, default_task_days=3
    ),
    StatusSeed(
        "PARKING", "Parking", 30, suggest_task=True, note_required=True, default_task_days=2
    ),
    StatusSeed("BUNDLE", "Bundle", 40),
    StatusSeed("HRS_PREVIEW", "HRS Preview", 50),
)


class AdminCredentials(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    admin_username: str = Field(min_length=1, max_length=50)
    admin_password: SecretStr = Field(min_length=10, max_length=128)

    @field_validator("admin_username")
    @classmethod
    def username_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ADMIN_USERNAME must not be blank")
        return value


@dataclass(frozen=True)
class SeedResult:
    statuses_created: int
    admin_created: bool


async def seed_database(
    engine: AsyncEngine,
    credentials: AdminCredentials | None,
    *,
    timezone: str = "Asia/Ho_Chi_Minh",
) -> SeedResult:
    created = 0
    admin_created = False
    async with asyncio.timeout(60), AsyncSession(engine) as session, session.begin():
        existing = set((await session.scalars(select(Status.code))).all())
        for entry in STATUS_SEEDS:
            if entry.code in existing:
                continue
            session.add(
                Status(
                    code=entry.code,
                    label=entry.label,
                    position_label=entry.label,
                    sort_order=entry.sort_order,
                    is_done=entry.is_done,
                    suggest_task=entry.suggest_task,
                    invoice_required=entry.invoice_required,
                    note_required=entry.note_required,
                    is_active=True,
                    stale_after_hours=None,
                    default_task_days=entry.default_task_days,
                )
            )
            created += 1
        if credentials is not None:
            from app.core.security import validate_password

            validate_password(
                credentials.admin_password.get_secret_value(), credentials.admin_username
            )
            admin = await session.scalar(
                select(User).where(User.username == credentials.admin_username)
            )
            if admin is not None and (admin.role != "admin" or not admin.is_active):
                raise ValueError(
                    "The configured username belongs to a non-admin or inactive account"
                )
            if admin is None:
                password_hash = await asyncio.to_thread(
                    PasswordHasher().hash, credentials.admin_password.get_secret_value()
                )
                session.add(
                    User(
                        username=credentials.admin_username,
                        password_hash=password_hash,
                        full_name="Administrator",
                        role="admin",
                        is_active=True,
                        must_change_password=True,
                        settings={"timezone": timezone},
                    )
                )
                admin_created = True
    return SeedResult(created, admin_created)


async def run(statuses_only: bool) -> None:
    # Validate credentials before connecting or modifying anything.
    credentials = None if statuses_only else AdminCredentials()
    settings = Settings()
    engine = create_database_engine(settings)
    if engine is None:
        raise ValueError("DATABASE_URL is required for seeding")
    try:
        result = await seed_database(engine, credentials, timezone=settings.business_timezone)
        print(f"Statuses created: {result.statuses_created}; admin created: {result.admin_created}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--statuses-only", action="store_true", help="Skip admin creation explicitly"
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.statuses_only))
    except Exception:
        # Do not print credentials, validation inputs, driver URLs, or SQL parameters.
        raise SystemExit(
            "Seed failed. Check database connectivity, migrations, ADMIN_USERNAME/ADMIN_PASSWORD "
            "(at least 12 characters), and any existing account with that username."
        ) from None


if __name__ == "__main__":
    main()
