"""50k snapshot scan with real notes and concurrent lookup latency measurement."""

import asyncio
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
import test_booking_database as support
from sqlalchemy import event, select, text

from app.models import Booking, BookingGroup, BookingNote, IntegrityRun, Station, Status
from app.services.integrity import batch_query

migrated = support.migrated
password_pair = support.password_pair
rig = support.rig
pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated integrity benchmark DB"
)


def stats(samples):
    ordered = sorted(samples)
    return {
        "samples": len(ordered),
        "p50_ms": round(ordered[len(ordered) // 2], 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "p99_ms": round(ordered[math.ceil(len(ordered) * 0.99) - 1], 3),
    }


async def test_scan_50000_bookings_and_fix_beyond_sample_cap_without_blocking_lookup(rig):
    now = datetime.now(UTC)
    now = now.replace(microsecond=now.microsecond // 1000 * 1000)
    async with rig.app.state.engine.begin() as conn:
        status = (
            await conn.execute(
                select(Status.id, Status.position_label).where(Status.code == "BUNDLE")
            )
        ).one()
        await conn.execute(Station.__table__.insert(), {"code": "RDU"})
        await conn.execute(
            BookingGroup.__table__.insert(),
            [
                {
                    "id": 10000 + i,
                    "cw_number": f"CW{5000000 + i}",
                    "station_code": "RDU",
                    "supplier_name": f"Crew Hotel {i}",
                    "supplier_name_normalized": f"CREW HOTEL {i}",
                    "supplier_type": "hotel",
                    "created_by": 3,
                    "booking_count": 25,
                    "last_activity_at": now,
                }
                for i in range(2000)
            ],
        )
        for start in range(0, 50000, 1000):
            bookings = []
            notes = []
            for i in range(start, start + 1000):
                period = f"{24 + (i % 25) // 12:02d}{1 + (i % 25) % 12:02d}"
                bookings.append(
                    {
                        "id": 100000 + i,
                        "booking_key": f"CW{5000000 + i // 25}-RDU-{period}",
                        "group_id": 10000 + i // 25,
                        "cw_number": f"CW{5000000 + i // 25}",
                        "station_code": "RDU",
                        "period": period,
                        "last_note_id": 1000000 + i,
                        "last_agent_id": 3,
                        "last_status_id": status.id,
                        "last_position": "Drift" if i % 200 == 0 else status.position_label,
                        "last_note_preview": f"Integrity fixture {i}",
                        "is_done": False,
                        "version": 1,
                        "updated_at": now,
                    }
                )
                notes.append(
                    {
                        "id": 1000000 + i,
                        "booking_id": 100000 + i,
                        "agent_id": 3,
                        "status_id": status.id,
                        "position_label": status.position_label,
                        "note": f"Integrity fixture {i}",
                        "created_at": now,
                    }
                )
            await conn.execute(Booking.__table__.insert(), bookings)
            await conn.execute(BookingNote.__table__.insert(), notes)
    await rig.app.state.key_index.load()
    key = "CW5000000-RDU-2401"

    async def sample():
        started = time.perf_counter()
        response = await rig.get("/bookings/lookup", key=key)
        assert response.status_code == 200, response.text
        return (time.perf_counter() - started) * 1000

    for _ in range(3):
        await sample()
    baseline = [await sample() for _ in range(30)]
    response = await rig.client.post("/api/v1/admin/integrity/run", headers=rig.headers["admin"])
    assert response.status_code == 202, response.text
    task = rig.app.state.integrity.task
    during = []
    started = time.perf_counter()
    while not task.done():
        during.append(await sample())
        await asyncio.sleep(0.02)
    await task
    duration = time.perf_counter() - started
    async with rig.app.state.engine.connect() as conn:
        run = (
            await conn.execute(select(IntegrityRun).where(IntegrityRun.id == response.json()["id"]))
        ).one()
        assert run.status == "completed" and (run.checked, run.mismatched, run.fixed) == (
            50000,
            250,
            0,
        )
        assert len(run.details["items"]) == 200 and run.details["truncated"]
        sql = str(
            batch_query(0, 149999).compile(
                dialect=conn.dialect, compile_kwargs={"literal_binds": True}
            )
        )
        plan = [dict(row) for row in (await conn.execute(text("EXPLAIN " + sql))).mappings()]
        version = await conn.scalar(text("SELECT VERSION()"))
    assert duration < 180
    assert len(during) >= 30
    assert stats(during)["p95_ms"] < max(100, stats(baseline)["p95_ms"] + 50)
    fix_started = time.perf_counter()
    fix = await rig.client.post(
        "/api/v1/admin/integrity/fix", headers=rig.headers["admin"], json={"run_id": run.id}
    )
    assert fix.status_code == 202, fix.text
    await asyncio.wait_for(asyncio.shield(rig.app.state.integrity.task), 180)
    async with rig.app.state.engine.connect() as conn:
        repaired = (
            await conn.execute(select(IntegrityRun).where(IntegrityRun.id == fix.json()["id"]))
        ).one()
        assert repaired.status == "completed" and repaired.fixed == 250
        assert (
            await conn.scalar(select(Booking.last_position).where(Booking.id == 149800))
            == status.position_label
        )
    captured = []

    def capture(conn, cursor, statement, parameters, context, many):
        if "suggestion_candidates" in statement:
            captured.append((statement, parameters))

    engine = rig.app.state.engine
    rig.app.state.key_index.ready = False
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    fallback_started = time.perf_counter()
    try:
        suggestions = await rig.app.state.bookings.suggestions.find("CW7000000-XPL-2401")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        rig.app.state.key_index.ready = True
    fallback_ms = (time.perf_counter() - fallback_started) * 1000
    assert len(captured) == 1 and suggestions[0].booking_key == key
    async with engine.connect() as conn:
        statement, params = captured[0]
        fallback_plan = [
            dict(row)
            for row in (await conn.exec_driver_sql("EXPLAIN " + statement, params)).mappings()
        ]
    if "tidb" in version.lower():
        assert any(
            "index:booking_key" in str(row.get("access object", "")) for row in fallback_plan
        ), fallback_plan
    else:
        assert any(
            row.get("table") == "bookings" and row.get("key") == "booking_key"
            for row in fallback_plan
        ), fallback_plan
    report = {
        "database_version": version,
        "fixture": {"bookings": 50000, "notes": 50000, "folders": 2000, "mismatches": 250},
        "method": (
            "Sequential authenticated ASGI/TLS-loopback lookups before and during a "
            "1000-row keyset scan, 50ms yield between batches. "
            "Excludes public hosting/network latency."
        ),
        "report_seconds": round(duration, 3),
        "fix_scan_seconds": round(time.perf_counter() - fix_started, 3),
        "baseline_lookup": stats(baseline),
        "during_scan_lookup": stats(during),
        "checked": 50000,
        "mismatched": 250,
        "fixed": 250,
        "sample_limit": 200,
        "batch_size": 1000,
        "pause_ms": 50,
        "plan": plan,
        "suggestion_fallback_ms": round(fallback_ms, 3),
        "suggestion_fallback_plan": fallback_plan,
    }
    output = os.environ.get("SCHEMA_TEST_REPORT")
    if output:
        await asyncio.to_thread(Path(output).write_text, json.dumps(report, indent=2) + "\n")
