"""Warm sequential ASGI search benchmark; SQL uses real disposable verified-TLS DBs."""

import asyncio
import json
import math
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_booking_database as booking_support
from sqlalchemy import select, text

from app.models import Booking, BookingGroup, Station, Status
from app.services.folders import folder_card_query
from app.utils.supplier import normalize_supplier_name

Rig = booking_support.Rig
migrated = booking_support.migrated
password_pair = booking_support.password_pair
rig = booking_support.rig
pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated benchmark database"
)


def write_report(path: str, report: dict) -> None:
    Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


async def test_search_p95_and_index_plans_with_2000_folders_50000_bookings(rig: Rig):
    now = datetime.now(UTC).replace(microsecond=0)
    stations = ("YUL", "RDU", "JFK", "CDG")
    groups = []
    for i in range(2000):
        station = stations[i % 4]
        hotel = (i // 4) % 2 == 0
        name = f"Hôtel Double Tree {station} {i}" if hotel else f"Crew Shuttle {station} {i}"
        groups.append(
            {
                "id": 10000 + i,
                "cw_number": f"CW{5000000 + i}",
                "station_code": station,
                "supplier_name": name,
                "supplier_name_normalized": normalize_supplier_name(name),
                "supplier_type": "hotel" if hotel else "transportation",
                "booking_count": 25,
                "last_activity_at": now - timedelta(seconds=i),
                "created_by": 3,
            }
        )
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(Station.__table__.insert(), [{"code": s} for s in stations])
        await connection.execute(BookingGroup.__table__.insert(), groups)
        status = await connection.scalar(select(Status.id).where(Status.code == "BUNDLE"))
        for start in range(0, 2000, 100):
            rows = []
            for i in range(start, start + 100):
                for month in range(25):
                    period = f"{24 + month // 12:02d}{1 + month % 12:02d}"
                    station = stations[i % 4]
                    rows.append(
                        {
                            "booking_key": f"CW{5000000 + i}-{station}-{period}",
                            "group_id": 10000 + i,
                            "cw_number": f"CW{5000000 + i}",
                            "station_code": station,
                            "period": period,
                            "last_status_id": status,
                            "last_agent_id": 3,
                            "last_position": "Bundle",
                            "last_note_preview": "Search benchmark fixture",
                            "version": 1,
                            "updated_at": now - timedelta(seconds=i),
                        }
                    )
            await connection.execute(Booking.__table__.insert(), rows)
    # Analyze after commit; TiDB requires its documented one-second recent-commit delay.
    async with rig.app.state.engine.connect() as connection:
        version = await connection.scalar(text("SELECT VERSION()"))
        tidb = "tidb" in version.lower()
    if tidb:
        await asyncio.sleep(1.1)
    async with rig.app.state.engine.connect() as connection:
        for table in ("bookings", "booking_groups", "users", "statuses"):
            await connection.execute(
                text(f"ANALYZE TABLE {table}" + (" ALL COLUMNS" if tidb else ""))
            )
    start = time.perf_counter()
    await rig.app.state.key_index.load()
    index_load_ms = (time.perf_counter() - start) * 1000
    rig.app.state.stations.invalidate()
    rig.app.state.search_limiter.limit = 10000
    queries = [
        "CW5000000-YUL-2501",
        "CW9999999-YUL-2501",
        "CW5000000-2501",
        "CW5000000",
        "CW500",
        "YUL",
        "YUL-2501",
        "double tree",
        "tree doub",
        "hotel yul",
    ]
    expected = {
        "CW5000000-YUL-2501": ("booking", True),
        "CW9999999-YUL-2501": ("booking", False),
        "CW5000000-2501": ("partial_key", None),
        "CW5000000": ("folder", None),
        "CW500": ("folders", 2000),
        "YUL": ("station", 500),
        "YUL-2501": ("station_period", 500),
        "double tree": ("folders", 1000),
        "tree doub": ("folders", 1000),
        "hotel yul": ("folders", 250),
    }
    measurements = []
    for query in queries:
        for _ in range(3):
            response = await rig.get("/search", q=query)
            assert response.status_code == 200, response.text
            data = response.json()
            kind, count = expected[query]
            assert data["kind"] == kind, (query, data)
            if kind == "booking":
                assert data["exists"] is count
            elif count is not None:
                assert data["total"] == count
            elif kind == "partial_key":
                assert data["resolution"]["status"] == "resolved_from_partial"
            elif kind == "folder":
                assert len(data["months"]) == 25
        samples = []
        for _ in range(60):
            start = time.perf_counter()
            response = await rig.get("/search", q=query)
            samples.append((time.perf_counter() - start) * 1000)
            assert response.status_code == 200, response.text
        samples.sort()
        measurements.append(
            {
                "query": query,
                "samples": len(samples),
                "p50_ms": round(samples[29], 3),
                "p95_ms": round(samples[math.ceil(len(samples) * 0.95) - 1], 3),
                "max_ms": round(samples[-1], 3),
            }
        )
    ids = list(range(10000, 10020))
    plans = {}
    async with rig.app.state.engine.connect() as connection:
        queries_to_explain = {
            "folder_aggregate": str(
                folder_card_query(ids).compile(
                    dialect=connection.dialect, compile_kwargs={"literal_binds": True}
                )
            ),
            "station_folders": (
                "SELECT id FROM booking_groups WHERE station_code='YUL' AND supplier_type='hotel' "
                "ORDER BY last_activity_at DESC,id DESC LIMIT 20"
            ),
            "station_period": (
                "SELECT id,booking_key FROM bookings WHERE station_code='YUL' AND period='2501' "
                "ORDER BY id DESC LIMIT 20"
            ),
        }
        for name, query in queries_to_explain.items():
            plans[name] = [
                dict(row) for row in (await connection.execute(text("EXPLAIN " + query))).mappings()
            ]
    for name, index in (
        ("folder_aggregate", "ix_bookings_group_period"),
        ("station_folders", "ix_booking_groups_station_type_activity"),
        ("station_period", "ix_bookings_station_period"),
    ):
        assert index in str(plans[name]), (name, plans[name])

    async def measure(source):
        worker = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("measure_lookup.py")),
            str(source),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        private = json.dumps(
            {
                "signing_key": rig.app.state.settings.jwt_secret_key.get_secret_value(),
                "headers": rig.headers["agent"],
            }
        ).encode()
        output, _ = await worker.communicate(private)
        assert worker.returncode == 0, "Lookup benchmark worker failed"
        return json.loads(output)

    lookup_after = await measure(Path(booking_support.__file__).parent.parent)
    assert "booking_key" in str(lookup_after["plans"]["full_key"])
    assert "ix_bookings_cw_period" in str(lookup_after["plans"]["partial_key"])
    if tidb:
        assert "Point_Get" in str(lookup_after["plans"]["full_key"])
    else:
        assert lookup_after["plans"]["full_key"][0]["type"] == "const"
        assert lookup_after["plans"]["partial_key"][0]["type"] == "ref"
    baseline = os.environ.get("BOOKING_LOOKUP_BASELINE_ROOT")
    lookup_before = await measure(Path(baseline)) if baseline else None
    report = {
        "database_version": version,
        "fixture": {"folders": 2000, "bookings": 50000},
        "method": (
            "Warm sequential in-process ASGI requests, one worker, real verified-TLS loopback DB. "
            "Includes auth cache, classification, SQL and serialization; excludes public "
            "HTTP/hosting latency. Three warmups and 60 samples per query."
        ),
        "target_p95_ms": 100,
        "index_load_ms": round(index_load_ms, 3),
        "measurements": measurements,
        "plans": plans,
        "lookup_after": lookup_after,
        "lookup_before": lookup_before,
        "lookup_baseline_commit": "d640d851a6221a8e7ccef92215b0a11e0efb7096" if baseline else None,
    }
    output = os.environ.get("SCHEMA_TEST_REPORT")
    if output:
        await asyncio.to_thread(write_report, output, report)
    assert all(row["p95_ms"] < 100 for row in measurements), measurements
