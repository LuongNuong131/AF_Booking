import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_booking_database as support
import test_realtime_database as realtime
from sqlalchemy import event, func, select, update

from app.models import AuditLog, Booking, BookingNote, IntegrityRun, Status
from app.schemas.integrity import IntegrityDetails
from app.services.integrity import IntegrityService

migrated = support.migrated
password_pair = support.password_pair
rig = support.rig
live = realtime.live
KEY = support.KEY
pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated safeguards DB"
)


async def call(rig, path, body=None, user="admin"):
    return await rig.client.post(
        "/api/v1" + path, headers=rig.headers[user], **({"json": body} if body is not None else {})
    )


async def finished(rig, response):
    assert response.status_code == 202, response.text
    await asyncio.wait_for(asyncio.shield(rig.app.state.integrity.task), 10)
    data = (await rig.get("/admin/integrity", user="admin")).json()
    return next(row for row in data["items"] if row["id"] == response.json()["id"])


async def test_typo_suggestions_station_months_and_new_confirmation(rig):
    assert (await rig.save()).status_code == 200
    # One digit, insertion, deletion, and adjacent transposition.
    for key in [
        "CW2154655-RDU-2609",
        "CW21546654-RDU-2609",
        "CW215464-RDU-2609",
        "CW2154564-RDU-2609",
    ]:
        data = (await rig.get("/bookings/lookup", key=key)).json()
        assert not data["exists"]
        assert data["suggestions"][0]["booking_key"] == KEY
        assert data["suggestions"][0]["display_key"] == "CW 2154654-RDU-2609"
        assert data["suggestions"][0]["distance"] == 1
    # A known candidate CW uses its own folder's station, even with different input station.
    assert (await rig.get("/bookings/lookup", key="CW2154655-YUL-2609")).json()["suggestions"][0][
        "booking_key"
    ] == KEY
    missing = (await rig.get("/bookings/lookup", key="CW9999999-RDU-2609")).json()
    assert missing["suggestions"] == []
    partial = (await rig.get("/bookings/lookup", key="CW2154655-2609")).json()
    assert partial["resolution"]["status"] == "needs_station" and partial["suggestions"] == []
    for period, distance in [("2608", 1), ("2610", 1), ("2607", 2), ("2611", 2)]:
        data = (await rig.get("/bookings/lookup", key=f"CW2154654-RDU-{period}")).json()
        assert data["suggestions"][0]["distance"] == distance
    blocked = await rig.save(key="CW2154655-RDU-2609", confirm_new=False)
    assert blocked.status_code == 422 and blocked.json()["code"] == "NEW_BOOKING_NEEDS_CONFIRM"
    assert blocked.json()["details"]["suggestions"][0]["booking_key"] == KEY
    assert (await rig.save(key="CW2154655-RDU-2609", confirm_new=True)).status_code == 200


async def test_fallback_is_one_bounded_statement_and_top_three_rank(rig):
    keys = [KEY, "CW2154655-RDU-2609", "CW2154656-RDU-2609", "CW2154657-RDU-2609"]
    for key in keys:
        assert (await rig.save(key=key)).status_code == 200
    queries = []

    def capture(conn, cursor, statement, params, context, many):
        queries.append(statement)

    engine = rig.app.state.engine
    rig.app.state.key_index.ready = False
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        result = await rig.app.state.bookings.suggestions.find("CW2154658-YUL-2609")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert len(queries) == 1 and " LIKE " not in queries[0]
    assert "booking_key IN" in queries[0] and "suggestion_candidates" in queries[0]
    assert len(result) == 3 and result[0].booking_key == keys[-1]
    rig.app.state.key_index.ready = True
    result2 = await rig.app.state.bookings.suggestions.find("CW2154658-YUL-2609")
    assert result2 == result


async def test_recent_duplicate_normalization_idempotency_override_and_expiry(rig):
    request_id = str(uuid4())
    original = await rig.save(
        note="  Check   Supplier\nMAIL  ", allow_duplicate=False, client_request_id=request_id
    )
    assert original.status_code == 200, original.text
    duplicate = await rig.save(version=1, note="check supplier mail", allow_duplicate=False)
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "DUPLICATE_RECENT_NOTE"
    previous = duplicate.json()["details"]["note"]
    assert previous["id"] == original.json()["note"]["id"] and "save_result" not in previous
    replay = await rig.save(
        note="  Check   Supplier\nMAIL  ", allow_duplicate=False, client_request_id=request_id
    )
    assert replay.status_code == 200 and replay.json() == original.json()
    assert (
        await rig.save(version=1, note="CHECK SUPPLIER MAIL", allow_duplicate=True)
    ).status_code == 200
    assert (
        await rig.save(user="other", version=2, note="check supplier mail", allow_duplicate=False)
    ).status_code == 200
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(BookingNote).values(created_at=datetime.now(UTC) - timedelta(seconds=61))
        )
    assert (
        await rig.save(version=3, note="check supplier mail", allow_duplicate=False)
    ).status_code == 200


async def test_integrity_report_fix_max_id_realtime_and_preserve_operational_clock(live, rig):
    first = (await rig.save(note="First")).json()["note"]
    second = (
        await rig.save(
            version=1, status_code="DONE", note="Completed", invoices={"no_invoice": True}
        )
    ).json()["note"]
    old = datetime(2026, 1, 1, tzinfo=UTC)
    async with rig.app.state.engine.begin() as conn:
        # MAX(id), rather than timestamp order, is authoritative even after clock drift/import.
        await conn.execute(
            update(BookingNote).where(BookingNote.id == second["id"]).values(created_at=old)
        )
        await conn.execute(
            update(Booking)
            .where(Booking.booking_key == KEY)
            .values(
                last_note_id=first["id"],
                last_agent_id=5,
                last_position="Broken",
                last_status_id=None,
                last_note_preview="Wrong",
                is_done=False,
                done_at=None,
                updated_at=old,
            )
        )
    report = await finished(rig, await call(rig, "/admin/integrity/run"))
    assert report["status"] == "completed" and (
        report["checked"],
        report["mismatched"],
        report["fixed"],
    ) == (1, 1, 0)
    finding = report["details"]["items"][0]
    assert (
        finding["booking_key"] == KEY
        and finding["fields"]["last_note_id"]["expected"] == second["id"]
    )
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]["version"] == 2
    async with realtime.peer(live, rig) as socket:
        await realtime.event(socket, "lock.snapshot")
        fixed = await finished(
            rig, await call(rig, "/admin/integrity/fix", {"run_id": report["id"]})
        )
        # Earlier note updates can still be in the manager's 100 ms batch when
        # this peer connects. Wait for the repair version rather than assuming
        # the first frame belongs to the operation under test.
        async with asyncio.timeout(3):
            while True:
                frame = await realtime.event(socket, "booking.updated", KEY)
                if frame["version"] >= 3:
                    break
        assert frame["snapshot_rebuilt"] and frame["version"] == 3 and frame["is_done"]
    assert fixed["fixed"] == 1 and fixed["mismatched"] == 1
    snap = (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]
    assert snap["version"] == 3 and snap["is_done"] and snap["invoice_state"] == "no_invoice"
    assert (
        snap["done_at"] == "2026-01-01T00:00:00.000Z"
        and snap["updated_at"] == "2026-01-01T00:00:00.000Z"
    )
    clean = await finished(rig, await call(rig, "/admin/integrity/run"))
    assert clean["mismatched"] == 0 and clean["fixed"] == 0
    again = await finished(rig, await call(rig, "/admin/integrity/fix", {"run_id": report["id"]}))
    assert again["fixed"] == 0
    async with rig.app.state.engine.connect() as conn:
        assert (
            await conn.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "integrity_snapshot_fixed")
            )
            == 1
        )


async def test_integrity_empty_history_acl_single_job_and_restart_recovery(rig, monkeypatch):
    saved = (await rig.save()).json()
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(update(BookingNote).values(deleted_at=datetime.now(UTC)))
        abandoned = IntegrityRun(
            status="running",
            checked=0,
            mismatched=0,
            fixed=0,
            details=IntegrityDetails(mode="report", trigger="scheduled").model_dump(mode="json"),
        )
        conn_stmt = IntegrityRun.__table__.insert().values(
            status="running", checked=0, mismatched=0, fixed=0, details=abandoned.details
        )
        await conn.execute(conn_stmt)
    assert (await rig.get("/admin/integrity")).status_code == 403
    assert (await call(rig, "/admin/integrity/run", user="agent")).status_code == 403
    assert (
        await call(rig, "/admin/integrity/fix", {"run_id": 999}, user="agent")
    ).status_code == 403
    service = rig.app.state.integrity
    release = asyncio.Event()
    entered = asyncio.Event()
    original = service.progress

    async def pause(*args):
        await original(*args)
        if args[-1] == "running":
            entered.set()
            await release.wait()

    monkeypatch.setattr(service, "progress", pause)
    response = await call(rig, "/admin/integrity/run")
    await asyncio.wait_for(entered.wait(), 5)
    try:
        busy = await call(rig, "/admin/integrity/run")
        assert busy.status_code == 503 and "retry-after" in busy.headers
    finally:
        release.set()
    report = await finished(rig, response)
    assert report["mismatched"] == 1
    history = (await rig.get("/admin/integrity", user="admin")).json()
    assert any(row["status"] == "interrupted" for row in history["items"])
    fixed = await finished(rig, await call(rig, "/admin/integrity/fix", {"run_id": report["id"]}))
    assert fixed["fixed"] == 1
    snap = (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]
    assert snap["last_status"] is None and snap["last_agent"] is None and not snap["is_done"]
    assert snap["version"] == saved["snapshot"]["version"] + 1


async def test_nightly_catchup_once_per_business_day_and_opt_in_autofix(rig):
    await rig.save()
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(Booking).values(last_position="Broken", updated_at=Booking.updated_at)
        )
    service = rig.app.state.integrity
    service.clock = lambda: datetime(2026, 11, 3, 18, tzinfo=UTC)  # Nov 4 01:00 in business zone
    await service.tick()
    assert service.task is None
    rig.app.state.settings.integrity_autofix = True
    service.clock = lambda: datetime(
        2026, 11, 3, 20, tzinfo=UTC
    )  # Nov 4 03:00; catch up missed 02:00
    await service.tick()
    await asyncio.wait_for(asyncio.shield(service.task), 10)
    await service.tick()
    restarted = IntegrityService(service.engine, service.settings, service.admin)
    restarted.clock = service.clock
    await restarted.tick()
    assert restarted.task is None
    rows = (await rig.get("/admin/integrity", user="admin")).json()["items"]
    assert len(rows) == 1 and rows[0]["details"]["scheduled_day"] == "2026-11-04"
    assert rows[0]["fixed"] == 1


async def test_new_migration_refines_existing_column_and_preserves_custom_days(rig):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from alembic import command

    config = Config(str(support.ALEMBIC_CONFIG))
    await asyncio.to_thread(command.downgrade, config, "0003")
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(Status).where(Status.code == "REJECTION").values(default_task_days=None)
        )
        await conn.execute(
            update(Status).where(Status.code == "PARKING").values(default_task_days=7)
        )
    await asyncio.to_thread(command.upgrade, config, "head")
    async with rig.app.state.engine.connect() as conn:
        values = dict((await conn.execute(select(Status.code, Status.default_task_days))).all())
        assert values["REJECTION"] == 3 and values["PARKING"] == 7
        column = await conn.scalar(
            text(
                "SELECT COLUMN_TYPE FROM information_schema.columns "
                "WHERE table_schema=DATABASE() AND table_name='statuses' "
                "AND column_name='default_task_days'"
            )
        )
        assert column.lower().startswith("smallint")
        assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == (
            ScriptDirectory.from_config(config).get_current_head()
        )


async def test_cancelled_check_finishes_as_interrupted_and_source_errors_are_not_autofixed(
    rig, monkeypatch
):
    await rig.save()
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(update(BookingNote).values(status_id=99999))
    service = rig.app.state.integrity
    entered = asyncio.Event()
    hold = asyncio.Event()
    original = service.progress

    async def pause(*args):
        await original(*args)
        if args[-1] == "running":
            entered.set()
            await hold.wait()

    monkeypatch.setattr(service, "progress", pause)
    started = await call(rig, "/admin/integrity/run")
    await asyncio.wait_for(entered.wait(), 5)
    await asyncio.wait_for(service.stop(), 5)
    row = (await rig.get("/admin/integrity", user="admin")).json()["items"][0]
    assert (
        row["id"] == started.json()["id"] and row["status"] == "interrupted" and row["fixed"] == 0
    )
    assert row["details"]["items"][0]["repairable"] is False
    monkeypatch.setattr(service, "progress", original)
    fixed = await finished(rig, await call(rig, "/admin/integrity/fix", {"run_id": row["id"]}))
    assert fixed["fixed"] == 0 and fixed["mismatched"] == 1 and fixed["status"] == "completed"
