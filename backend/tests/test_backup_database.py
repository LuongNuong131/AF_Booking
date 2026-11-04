"""Restore all typed application data into a new database on the same owned TLS server."""

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import test_booking_database as support
from cryptography.exceptions import InvalidTag
from pydantic import SecretStr
from sqlalchemy import inspect, select
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.backup import BackupError, export_snapshot, restore_snapshot
from app.core.db import create_database_engine
from app.models import Attachment, Booking, BookingNote, DailyReport, IntegrityRun, PushSubscription

migrated, password_pair, rig = support.migrated, support.password_pair, support.rig
pytestmark = support.pytestmark


@asynccontextmanager
async def empty_database(rig):
    name = "booking_restore_" + uuid4().hex[:12] + "_test"
    source = rig.app.state.engine
    assert source.url.database.startswith("booking_schema_")
    async with source.begin() as connection:
        await connection.execute(CreateSchema(name))
    settings = rig.app.state.settings.model_copy(
        update={
            "database_url": SecretStr(
                source.url.set(database=name).render_as_string(hide_password=False)
            ),
        }
    )
    target = create_database_engine(settings)
    try:
        yield target
    finally:
        await target.dispose()
        async with source.begin() as connection:
            await connection.execute(DropSchema(name))


async def test_every_table_encrypted_roundtrip_and_refuse_nonempty_target(rig, tmp_path):
    response = await rig.save(
        note='Khách sạn, "crew"\nLine two', invoices={"add": ["INV-100", "INV/200"]}, assign_to=5
    )
    assert response.status_code == 200, response.text
    note_id = response.json()["note"]["id"]
    await rig.client.put("/api/v1/bookings/" + support.KEY + "/watch", headers=rig.headers["other"])
    async with rig.app.state.engine.begin() as c:
        await c.execute(
            Attachment.__table__.insert().values(
                note_id=note_id,
                file_name="crew.csv",
                mime_type="text/csv",
                size_bytes=3,
                storage_key="private/test-key",
            )
        )
        await c.execute(
            DailyReport.__table__.insert().values(
                report_date=datetime.now(UTC).date(),
                payload={"unicode": "Việt Nam", "empty": "", "null": None, "items": [1, True]},
                generated_at=datetime.now(UTC),
            )
        )
        await c.execute(
            IntegrityRun.__table__.insert().values(
                started_at=datetime.now(UTC),
                status="done",
                checked=1,
                mismatched=0,
                fixed=0,
                details=[],
            )
        )
        await c.execute(
            PushSubscription.__table__.insert().values(
                user_id=3,
                endpoint="https://fcm.googleapis.com/fcm/send/disposable",
                p256dh="test-public",
                auth="test-auth",
                session_id=str(uuid4()),
            )
        )
    output = tmp_path / "backup.enc"
    key = os.urandom(32)
    exported = await export_snapshot(rig.app.state.engine, output, key=key)
    assert "Khách sạn".encode() not in output.read_bytes()
    assert output.stat().st_mode & 0o777 == 0o600
    async with empty_database(rig) as target:
        restored = await restore_snapshot(
            target, output, key=key, prepare=True, preserve_sessions=True
        )
        assert restored["rows"] == {
            n: v for n, v in exported["rows"].items() if n != "alembic_version"
        }
        second = tmp_path / "roundtrip.zip"
        assert await export_snapshot(target, second) == exported
        # Row counts alone cannot detect Unicode/NULL/JSON/generated-column corruption.
        import zipfile

        with zipfile.ZipFile(second) as zipped:
            import json

            target_manifest = json.loads(zipped.read("manifest.json"))
        original = tmp_path / "original.zip"
        await export_snapshot(rig.app.state.engine, original)
        with zipfile.ZipFile(original) as zipped:
            assert json.loads(zipped.read("manifest.json")) == target_manifest
        with pytest.raises(BackupError, match="contains data"):
            await restore_snapshot(target, output, key=key)
    before = output.read_bytes()
    with pytest.raises(BackupError, match="already exists"):
        await export_snapshot(rig.app.state.engine, output, key=key)
    assert output.read_bytes() == before


async def test_tamper_is_authenticated_before_schema_write_and_restore_revokes_sessions(
    rig, tmp_path
):
    assert (await rig.save()).status_code == 200
    key = os.urandom(32)
    output = tmp_path / "backup.enc"
    await export_snapshot(rig.app.state.engine, output, key=key)
    async with empty_database(rig) as target:
        with pytest.raises(InvalidTag):
            await restore_snapshot(target, output, key=os.urandom(32), prepare=True)
        async with target.connect() as c:
            assert await c.run_sync(lambda s: inspect(s).get_table_names()) == []
        result = await restore_snapshot(target, output, key=key, prepare=True)
        assert result["sessions_revoked"]
        from app.models import User

        async with target.connect() as c:
            assert set((await c.execute(select(User.current_session_id))).scalars()) == {None}


async def test_concurrent_note_does_not_tear_consistent_backup(rig, tmp_path):
    assert (await rig.save()).status_code == 200

    async def concurrent_write(name, count):
        if name == "booking_groups":
            assert (await rig.save(version=1, note="Concurrent later update")).status_code == 200

    output = tmp_path / "consistent.zip"
    await export_snapshot(rig.app.state.engine, output, on_table=concurrent_write)
    async with empty_database(rig) as target:
        await restore_snapshot(target, output, prepare=True)
        async with target.connect() as c:
            assert await c.scalar(select(Booking.version)) == 1
            assert len((await c.execute(select(BookingNote.id))).all()) == 1
        async with rig.app.state.engine.connect() as c:
            assert await c.scalar(select(Booking.version)) == 2
            assert len((await c.execute(select(BookingNote.id))).all()) == 2


async def test_actual_backup_and_restore_clis_use_environment_credentials(rig, tmp_path):
    import asyncio
    import base64
    import json
    import sys
    from pathlib import Path

    assert (await rig.save(note="CLI roundtrip")).status_code == 200
    root = await asyncio.to_thread(lambda: Path(__file__).resolve().parents[2])
    key = base64.b64encode(os.urandom(32)).decode()
    environment = {**os.environ, "BACKUP_ENCRYPTION_KEY": key}

    async def run(script, *args, env):
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            str(root / "scripts" / script),
            *map(str, args),
            cwd=root,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(child.communicate(), 60)
        assert child.returncode == 0, stderr.decode()
        assert key.encode() not in stdout + stderr
        return json.loads(stdout)

    archive = tmp_path / "cli.enc"
    exported = await run("export_backup.py", "--encrypt", "--output", archive, env=environment)
    async with empty_database(rig) as target:
        env = {**environment, "DATABASE_URL": target.url.render_as_string(hide_password=False)}
        restored = await run("restore_backup.py", "--input", archive, "--prepare-schema", env=env)
        assert restored["rows"]["booking_notes"] == exported["rows"]["booking_notes"] == 1
        assert restored["sessions_revoked"]
