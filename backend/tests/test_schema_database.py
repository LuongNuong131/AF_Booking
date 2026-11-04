"""Mutating checks: run only against the isolated database created by the test runner."""

import asyncio
import json
import os
import secrets
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from alembic import command
from app.core.config import Settings
from app.core.db import create_database_engine
from app.models import Base, Booking, BookingGroup, BookingNote, BookingTask, Station, Status, User
from app.scripts.seed import AdminCredentials, seed_database

pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"),
    reason="No isolated schema test database supplied",
)
ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"


@pytest_asyncio.fixture
async def schema_engine() -> AsyncIterator[AsyncEngine]:
    url = os.environ["SCHEMA_TEST_DATABASE_URL"]
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=url,
        database_ssl_ca=os.environ.get("SCHEMA_TEST_SSL_CA"),
    )
    engine = create_database_engine(settings)
    assert engine is not None
    assert engine.url.database.startswith("booking_schema_")
    assert engine.url.database.endswith("_test")
    try:
        yield engine
    finally:
        await engine.dispose()


async def populate_query_fixture(engine: AsyncEngine) -> dict[str, int]:
    """Representative cardinalities matter: an optimizer may scan a tiny test table."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    async with engine.begin() as connection:
        admin_hash = (await connection.execute(select(User.password_hash).limit(1))).scalar_one()
        await connection.execute(
            User.__table__.insert(),
            [
                {
                    "id": i,
                    "username": f"fixture-agent-{i}",
                    "password_hash": admin_hash,
                    "full_name": f"Fixture Agent {i}",
                    "role": "agent",
                }
                for i in range(2, 17)
            ],
        )
        codes = ["RDU", "YUL", "MRU", "LHR", "CDG", "JFK", "SIN", "NRT", "DXB", "SYD"]
        await connection.execute(Station.__table__.insert(), [{"code": code} for code in codes])
        status_id = (
            await connection.execute(select(Status.id).where(Status.code == "PARKING"))
        ).scalar_one()
        groups, bookings, notes = [], [], []
        for group_id in range(1, 2001):
            cw = f"CW{2150000 + group_id}"
            station = codes[(group_id // 2) % len(codes)]
            groups.append(
                {
                    "id": group_id,
                    "cw_number": cw,
                    "station_code": station,
                    "supplier_name": f"Fixture Supplier {group_id}",
                    "supplier_name_normalized": f"fixture supplier {group_id}",
                    "supplier_type": "hotel" if group_id % 2 else "transportation",
                    "booking_count": 12,
                    "created_by": 1,
                    "last_activity_at": now + timedelta(seconds=group_id),
                }
            )
            for month in range(1, 13):
                booking_id = (group_id - 1) * 12 + month
                agent_id = group_id % 16 + 1
                period = f"26{month:02d}"
                timestamp = now + timedelta(seconds=booking_id)
                bookings.append(
                    {
                        "id": booking_id,
                        "booking_key": f"{cw}-{station}-{period}",
                        "group_id": group_id,
                        "cw_number": cw,
                        "station_code": station,
                        "period": period,
                        "last_agent_id": agent_id,
                        "last_status_id": status_id,
                        "last_note_id": booking_id * 2,
                        "last_position": "Parking",
                        "last_note_preview": "Fixture note",
                        "updated_at": timestamp,
                    }
                )
                for offset in (0, 1):
                    notes.append(
                        {
                            "id": (booking_id - 1) * 2 + offset + 1,
                            "booking_id": booking_id,
                            "agent_id": agent_id,
                            "status_id": status_id,
                            "position_label": "Parking",
                            "note": "Fixture note",
                            "created_at": timestamp - timedelta(seconds=1 - offset),
                        }
                    )
        for model, rows in [(BookingGroup, groups), (Booking, bookings), (BookingNote, notes)]:
            for start in range(0, len(rows), 500):
                await connection.execute(model.__table__.insert(), rows[start : start + 500])
    async with engine.connect() as raw_connection:
        connection = await raw_connection.execution_options(isolation_level="AUTOCOMMIT")
        version = str((await connection.execute(text("SELECT VERSION()"))).scalar_one())
        if "tidb" in version.lower():
            # TiDB documents that ANALYZE can miss very recent commits (#16570).
            await asyncio.sleep(1)
        for table in ("booking_groups", "bookings", "booking_notes"):
            suffix = " ALL COLUMNS" if "tidb" in version.lower() else ""
            await connection.execute(text(f"ANALYZE TABLE {table}{suffix}"))
    async with engine.connect() as connection:
        version = str((await connection.execute(text("SELECT VERSION()"))).scalar_one())
        if "tidb" in version.lower():
            # ANALYZE updates TiDB's statistics cache asynchronously; wait for observed row counts.
            async with asyncio.timeout(15):
                while True:
                    stats = (
                        (
                            await connection.execute(
                                text("SHOW STATS_META WHERE Table_name = 'bookings'")
                            )
                        )
                        .mappings()
                        .all()
                    )
                    if stats and int(stats[0]["Row_count"]) == len(bookings):
                        break
                    await asyncio.sleep(0.5)
    return {"groups": len(groups), "bookings": len(bookings), "notes": len(notes)}


QUERIES = {
    "a_mine": (
        "SELECT id, booking_key, updated_at FROM bookings WHERE last_agent_id=1 "
        "ORDER BY updated_at DESC, id DESC LIMIT 20",
        "ix_bookings_agent_updated",
    ),
    "b_history": (
        "SELECT id, note, created_at FROM booking_notes "
        "WHERE booking_id=100 AND deleted_at IS NULL "
        "ORDER BY created_at DESC, id DESC LIMIT 20",
        "ix_booking_notes_booking_created",
    ),
    "c_overall": (
        "SELECT id, booking_key, updated_at FROM bookings "
        "ORDER BY updated_at DESC, id DESC LIMIT 20",
        "ix_bookings_updated_at",
    ),
    "d_station_folders": (
        "SELECT id, supplier_name, last_activity_at FROM booking_groups "
        "WHERE station_code='RDU' AND supplier_type='hotel' "
        "ORDER BY last_activity_at DESC, id DESC LIMIT 20",
        "ix_booking_groups_station_type_activity",
    ),
    "e_folder_months": (
        "SELECT id, booking_key, period FROM bookings WHERE group_id=1 "
        "ORDER BY period DESC, id DESC LIMIT 20",
        "ix_bookings_group_period",
    ),
    "f_station_period": (
        "SELECT id, booking_key FROM bookings WHERE station_code='RDU' AND period='2609' "
        "ORDER BY id DESC LIMIT 20",
        "ix_bookings_station_period",
    ),
    "g_exact": (
        "SELECT * FROM bookings WHERE booking_key='CW2150001-RDU-2609'",
        "booking_key",
    ),
    "h_partial": (
        "SELECT * FROM bookings WHERE cw_number='CW2150001' AND period='2609'",
        "ix_bookings_cw_period",
    ),
    "join_group": (
        "SELECT b.booking_key,g.supplier_name FROM bookings b "
        "JOIN booking_groups g ON g.id=b.group_id "
        "WHERE b.last_agent_id=1 ORDER BY b.updated_at DESC,b.id DESC LIMIT 20",
        "ix_bookings_agent_updated",
    ),
}


async def test_migration_seed_constraints_and_explain(schema_engine: AsyncEngine) -> None:
    engine = schema_engine
    config = Config(str(ALEMBIC_CONFIG_PATH))
    # Alembic owns an event loop; invoke its synchronous API in a thread.
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.check, config)
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
        assert set(tables) == set(Base.metadata.tables) | {"alembic_version"}
        assert not (await connection.execute(select(func.count()).select_from(User))).scalar_one()
        for table in Base.metadata.tables:
            assert not await connection.run_sync(
                lambda c, name=table: inspect(c).get_foreign_keys(name)
            )
        options = (
            (
                await connection.execute(
                    text(
                        "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
                        "WHERE TABLE_SCHEMA=DATABASE()"
                    )
                )
            )
            .mappings()
            .all()
        )
        for option in options:
            if option["TABLE_NAME"] in Base.metadata.tables:
                assert option["ENGINE"] == "InnoDB"
                assert option["TABLE_COLLATION"] == "utf8mb4_unicode_ci"
        columns = (
            (
                await connection.execute(
                    text(
                        "SELECT TABLE_NAME,COLUMN_NAME,COLLATION_NAME,DATETIME_PRECISION,DATA_TYPE "
                        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()"
                    )
                )
            )
            .mappings()
            .all()
        )
        for column in columns:
            if column["DATA_TYPE"] == "datetime":
                assert column["DATETIME_PRECISION"] == 3
            if (column["TABLE_NAME"], column["COLUMN_NAME"]) in {
                ("bookings", "booking_key"),
                ("bookings", "cw_number"),
                ("bookings", "station_code"),
                ("bookings", "period"),
                ("booking_groups", "cw_number"),
                ("booking_groups", "station_code"),
                ("stations", "code"),
            }:
                assert column["COLLATION_NAME"] == "ascii_bin"
        version = (await connection.execute(text("SELECT VERSION()"))).scalar_one()
    password = secrets.token_urlsafe(24)
    credentials = AdminCredentials(
        _env_file=None, admin_username="schema-test-admin", admin_password=password
    )
    first = await seed_database(engine, credentials)
    assert first.statuses_created == 5 and first.admin_created
    async with AsyncSession(engine) as session, session.begin():
        status = await session.scalar(select(Status).where(Status.code == "PARKING"))
        status.position_label = "Admin configured position"
        seeded = await session.scalar(select(User))
        assert seeded.must_change_password is True
        seeded.must_change_password = False
        original_hash = seeded.password_hash
        assert original_hash.startswith("$argon2id$")
        assert PasswordHasher().verify(original_hash, password)
    second = await seed_database(
        engine,
        AdminCredentials(
            _env_file=None,
            admin_username="schema-test-admin",
            admin_password=secrets.token_urlsafe(24),
        ),
    )
    assert second.statuses_created == 0 and not second.admin_created
    cli_env = os.environ.copy()
    cli_env.update({"ADMIN_USERNAME": "schema-test-admin", "ADMIN_PASSWORD": password})
    cli = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "app.scripts.seed"],
        env=cli_env,
        cwd=ALEMBIC_CONFIG_PATH.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert cli.returncode == 0, (
        "The full seed CLI must succeed with environment-supplied credentials"
    )
    assert "Statuses created: 0; admin created: False" in cli.stdout
    assert password not in cli.stdout + cli.stderr
    async with AsyncSession(engine) as session:
        assert await session.scalar(select(func.count()).select_from(Status)) == 5
        seeded = await session.scalar(select(User))
        assert seeded.password_hash == original_hash
        assert seeded.must_change_password is False
        status = await session.scalar(select(Status).where(Status.code == "PARKING"))
        assert status.position_label == "Admin configured position"
    cardinalities = await populate_query_fixture(engine)
    with pytest.raises(ValueError, match="non-admin or inactive"):
        await seed_database(
            engine,
            AdminCredentials(
                _env_file=None, admin_username="fixture-agent-2", admin_password=password
            ),
        )
    plans = {}
    async with engine.connect() as connection:
        tidb = "tidb" in version.lower()
        for name, (query, index_name) in QUERIES.items():
            plan = (await connection.execute(text("EXPLAIN " + query))).mappings().all()
            plans[name] = [dict(row) for row in plan]
            if tidb:
                operators = " ".join(str(row) for row in plan)
                assert "TableFullScan" not in operators, (name, plan)
                if name == "g_exact":
                    assert "Point_Get" in operators, plan
                elif name == "join_group":
                    assert "IndexJoin" in operators or "IndexHashJoin" in operators, plan
                else:
                    assert index_name in operators, (name, plan)
                if name != "join_group":
                    assert not any("TopN" in row["id"] or "Sort" in row["id"] for row in plan), (
                        name,
                        plan,
                    )
            else:
                assert index_name in {row["key"] for row in plan}, (name, plan)
                for row in plan:
                    assert "Using filesort" not in (row["Extra"] or ""), (name, plan)
                    assert "Using temporary" not in (row["Extra"] or ""), (name, plan)
                if name == "g_exact":
                    assert plan[0]["type"] == "const", plan
                if name == "h_partial":
                    assert plan[0]["type"] == "ref", plan
                if name == "join_group":
                    assert next(row for row in plan if row["table"] == "g")["type"] == "eq_ref"
        # Multiple NULL request IDs are allowed, but retries with a UUID are unique.
    request_id = "84f91e80-6688-41a0-8237-8d1f9ab55e01"
    for model in (BookingNote, BookingTask):
        values = {"booking_id": 1, "client_request_id": request_id}
        if model is BookingNote:
            values |= {"agent_id": 1, "status_id": 1, "position_label": "Test"}
        else:
            values |= {"user_id": 1, "message": "Test reminder", "remind_at": datetime.now(UTC)}
        async with engine.begin() as connection:
            await connection.execute(model.__table__.insert().values(**values))
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(model.__table__.insert().values(**values))
    # Verify the ORM storage guard even on TiDB configurations without CHECK enforcement.
    with pytest.raises(ValueError):
        Booking(booking_key="cw2150001-RDU-2609")
    if not tidb:
        with pytest.raises(DBAPIError) as check_error:
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE bookings SET booking_key=LOWER(booking_key) WHERE id=1")
                )
        assert check_error.value.orig.args[0] == 3819
    report = {"database_version": version, "fixture": cardinalities, "plans": plans}
    output = os.environ.get("SCHEMA_TEST_REPORT")
    await engine.dispose()
    await asyncio.to_thread(command.downgrade, config, "base")
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
        assert tables == ["alembic_version"]
    if tidb:
        # This is the runner's disposable server, never a production-wide setting change.
        async with engine.begin() as connection:
            await connection.execute(text("SET GLOBAL tidb_enable_check_constraint=ON"))
    await engine.dispose()
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.check, config)
    if tidb:
        async with engine.connect() as connection:
            checks = await connection.run_sync(
                lambda c: inspect(c).get_check_constraints("bookings")
            )
            assert any(check["name"] == "ck_bookings_canonical_key" for check in checks)
        with pytest.raises(DBAPIError) as check_error:
            async with engine.begin() as connection:
                await connection.execute(
                    Booking.__table__.insert().values(
                        booking_key="cw2154654-RDU-2609",
                        group_id=1,
                        cw_number="CW2154654",
                        station_code="RDU",
                        period="2609",
                    )
                )
        assert check_error.value.orig.args[0] == 3819
    if output:
        report["verified_at_utc"] = datetime.now(UTC).isoformat(timespec="milliseconds")
        await asyncio.to_thread(
            Path(output).write_text, json.dumps(report, indent=2, default=str) + "\n"
        )
