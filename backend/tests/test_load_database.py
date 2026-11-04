"""Real Locust + 100 WS peers + TLS-preserving latency injection on disposable SQL."""

import asyncio
import json
import math
import os
import secrets
import socket
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import test_booking_database as support
from sqlalchemy import event, text
from websockets.asyncio.client import connect

from app.core.config import Settings
from app.core.db import create_database_engine
from app.models import User
from app.scripts.seed_load import seed_load

migrated = support.migrated
pytestmark = support.pytestmark
ROOT = Path(__file__).resolve().parents[2]


def distribution(values):
    values = sorted(values)
    return {
        "count": len(values),
        **{
            f"p{int(q * 100)}_ms": round(values[max(0, math.ceil(len(values) * q) - 1)], 3)
            if values
            else None
            for q in [0.5, 0.95, 0.99]
        },
    }


def assess(report):
    mixed = report["results"]["mixed"]
    lookups = report["results"]["keys"]["groups"]
    max_key = max(value["server"]["p95_ms"] for value in lookups.values())
    return {
        "rest_p50": {
            "actual_ms": mixed["rest"]["p50_ms"],
            "limit_ms": 100,
            "met": mixed["rest"]["p50_ms"] < 100,
        },
        "rest_p95": {
            "actual_ms": mixed["rest"]["p95_ms"],
            "limit_ms": 300,
            "met": mixed["rest"]["p95_ms"] < 300,
        },
        "key_p95_server": {"actual_ms": max_key, "limit_ms": 50, "met": max_key < 50},
        "broadcast_p95": {
            "actual_ms": report["broadcast"]["p95_ms"],
            "limit_ms": 500,
            "met": report["broadcast"]["p95_ms"] < 500,
        },
        "unexpected_rest_errors": {
            "actual": sum(v["errors"] for v in report["results"].values()),
            "met": not any(v["errors"] for v in report["results"].values()),
        },
        "broadcast_receivers": {
            "actual": report["broadcast"]["probe_receivers"],
            "met": report["broadcast"]["probe_receivers"] == 100,
        },
        "db_recovered": {"met": report["fault"]["recovered"]},
    }


class LatencyProxy:
    """Copies encrypted TCP bytes; no TLS termination or certificate bypass."""

    def __init__(self, port):
        self.upstream = port
        self.delay = 0
        self.tasks = set()

    async def start(self):
        self.server = await asyncio.start_server(self.accept, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        copies = []
        try:
            peer, upstream = await asyncio.open_connection("127.0.0.1", self.upstream)

            async def copy(source, target):
                while chunk := await source.read(65536):
                    if self.delay:
                        await asyncio.sleep(self.delay)
                    target.write(chunk)
                    await target.drain()

            copies = [
                asyncio.create_task(copy(reader, upstream)),
                asyncio.create_task(copy(peer, writer)),
            ]
            await asyncio.wait(copies, return_when=asyncio.FIRST_COMPLETED)
        except (ConnectionError, OSError):
            pass
        finally:
            for copy in copies:
                copy.cancel()
            await asyncio.gather(*copies, return_exceptions=True)
            writer.close()
            if upstream:
                upstream.close()
            self.tasks.discard(task)

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def run_process(*args, env, log, seconds):
    with log.open("wb") as stream:
        process = await asyncio.create_subprocess_exec(
            *args, env=env, cwd=ROOT / "backend", stdout=stream, stderr=stream
        )
        try:
            return await asyncio.wait_for(process.wait(), seconds)
        finally:
            if process.returncode is None:
                process.terminate()
                await asyncio.wait_for(process.wait(), 10)


async def note_search_plans(engine, settings):
    """Explain synthetic ORM queries without retaining SQL parameters in telemetry."""
    from app.services.note_search import create_note_search
    from app.services.telemetry import fingerprint

    captured = []

    def capture(conn, cursor, statement, params, context, executemany):
        if statement.startswith("SELECT"):
            captured.append((statement, params))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        today = datetime.now(ZoneInfo(settings.business_timezone)).date()
        await create_note_search(engine, settings).search(
            "supplier", today, today, None, None, 1, 20
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    plans = []
    async with engine.connect() as connection:
        for statement, params in captured:
            rows = (
                (await connection.exec_driver_sql("EXPLAIN " + statement, params)).mappings().all()
            )
            plans.append({"fingerprint": fingerprint(statement), "plan": list(map(dict, rows))})
    return plans


async def test_real_load_dataset_rest_lookup_broadcast_and_slow_db(migrated, tmp_path):
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=os.environ["SCHEMA_TEST_DATABASE_URL"],
        database_ssl_ca=os.environ["SCHEMA_TEST_SSL_CA"],
    )
    engine = create_database_engine(settings)
    duration = int(os.environ.get("LOAD_DURATION_SECONDS", "60"))
    assert duration >= 20, "Load runs require a warmup plus a measurable interval."
    password = secrets.token_urlsafe(24)
    started = time.perf_counter()
    dataset = await seed_load(engine, password=password)
    seed_seconds = time.perf_counter() - started
    # One socket/account: 50 acting users plus 50 observation-only test accounts.
    async with engine.begin() as c:
        await c.execute(
            User.__table__.insert(),
            [
                {
                    "id": 2001 + i,
                    "username": f"load.observer.{i:03}",
                    "full_name": f"Load Observer {i:03}",
                    "role": "agent",
                    "password_hash": dataset["password_hash"],
                    "is_active": True,
                    "must_change_password": False,
                }
                for i in range(50)
            ],
        )
    proxy = LatencyProxy(engine.url.port)
    await proxy.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": engine.url.set(port=proxy.port).render_as_string(hide_password=False),
            "JWT_SECRET_KEY": secrets.token_urlsafe(64),
            "APP_ENV": "test",
            "SCHEDULER_ENABLED": "false",
            "RETENTION_ENABLED": "false",
            "CORS_ORIGINS": '["http://localhost:5173"]',
        }
    )
    backend_log = tmp_path / "backend.jsonl"
    log = backend_log.open("wb")
    server = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workers",
        "1",
        "--no-access-log",
        "--ws",
        "websockets-sansio",
        "--ws-max-size",
        "4096",
        cwd=ROOT / "backend",
        env=environment,
        stdout=log,
        stderr=log,
    )
    all_seen = asyncio.Event()
    peers = []
    readers = []
    latencies = []
    seen_by = set()
    probe_key = dataset["keys"][500]
    try:
        async with httpx.AsyncClient(base_url=origin, timeout=30, trust_env=False) as client:
            async with asyncio.timeout(30):
                while True:
                    try:
                        if (await client.get("/api/v1/ready")).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.1)
            tokens = []
            for prefix in ["agent", "observer"]:
                for i in range(50):
                    response = await client.post(
                        "/api/v1/auth/login",
                        json={"username": f"load.{prefix}.{i:03}", "password": password},
                    )
                    assert response.status_code == 200, "Synthetic account login failed"
                    tokens.append(response.json()["access_token"])
            admin = {"Authorization": "Bearer " + tokens[0]}
            # Readiness belongs to the separate API process.
            async with asyncio.timeout(30):
                for _ in range(300):
                    state = (await client.get("/api/v1/admin/system/health", headers=admin)).json()
                    if state["key_index"]["ready"]:
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise AssertionError("Index bootstrap did not finish")
            private = tmp_path / "sessions.json"
            with os.fdopen(
                os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
            ) as stream:
                json.dump(
                    {
                        "tokens": tokens[:50],
                        "keys": dataset["keys"],
                        "initial_version": dataset["initial_version"],
                        "today": datetime.now(UTC).astimezone().date().isoformat(),
                    },
                    stream,
                )

            async def read_peer(index, ws):
                async for raw in ws:
                    frame = json.loads(raw)
                    if frame["event"] == "ping":
                        await ws.send(json.dumps({"event": "pong", "data": {}}))
                    elif frame["event"] == "booking.updated":
                        data = frame["data"]
                        at = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
                        latencies.append((datetime.now(UTC) - at).total_seconds() * 1000)
                        if data["booking_key"] == probe_key:
                            seen_by.add(index)
                            if len(seen_by) == 100:
                                all_seen.set()

            for i, token in enumerate(tokens):
                ws = await connect(
                    origin.replace("http", "ws") + "/api/v1/ws?token=" + token,
                    origin="http://localhost:5173",
                    proxy=None,
                    max_size=65536,
                )
                first = json.loads(await ws.recv())
                assert first["event"] == "lock.snapshot"
                peers.append(ws)
                readers.append(asyncio.create_task(read_peer(i, ws)))
            results = {}
            exit_codes = {}
            for mode in ["mixed", "keys"]:
                result = tmp_path / f"{mode}.json"
                load_env = {
                    **environment,
                    "LOAD_TOKEN_FILE": str(private),
                    "LOAD_MODE": mode,
                    "LOAD_RESULT_FILE": str(result),
                    "LOAD_WARMUP_SECONDS": "10",
                }
                code = await run_process(
                    str(ROOT / "backend/.venv/bin/locust"),
                    "-f",
                    str(ROOT / "scripts/locustfile.py"),
                    "--headless",
                    "--users",
                    "50",
                    "--spawn-rate",
                    "50",
                    "--run-time",
                    f"{duration}s",
                    "--host",
                    origin,
                    "--only-summary",
                    "--stop-timeout",
                    "20",
                    env=load_env,
                    log=tmp_path / f"{mode}.log",
                    seconds=duration + 40,
                )
                results[mode] = json.loads(result.read_text())
                exit_codes[mode] = code
            response = await client.post(
                "/api/v1/bookings/" + probe_key + "/notes",
                headers=admin,
                json={
                    "status_code": "BUNDLE",
                    "note": "Broadcast latency probe",
                    "expected_version": dataset["initial_version"],
                    "client_request_id": secrets.token_hex(16),
                },
            )
            assert response.status_code == 200, response.status_code
            async with asyncio.timeout(5):
                await all_seen.wait()
            healthy = (await client.get("/api/v1/admin/system/health", headers=admin)).json()
            assert healthy["websocket_connections"] == 100
            proxy.delay = 2
            fault_start = time.perf_counter()
            fault = await asyncio.gather(
                *(
                    client.get(
                        "/api/v1/bookings/" + dataset["keys"][49000 + i] + "/notes",
                        headers={"Authorization": "Bearer " + tokens[i]},
                    )
                    for i in range(12)
                )
            )
            proxy.delay = 0
            assert all(r.status_code in [503, 504] for r in fault), [r.status_code for r in fault]
            assert all(r.json()["code"] in ["REQUEST_TIMEOUT", "SERVICE_BUSY"] for r in fault)
            assert all(r.status_code != 503 or r.headers["retry-after"].isdecimal() for r in fault)
            assert (await client.get("/health")).status_code == 200
            async with asyncio.timeout(20):
                while (await client.get("/api/v1/health/db")).status_code != 200:  # noqa: ASYNC110 - remote readiness probe
                    await asyncio.sleep(1)
            recovered = await client.get(
                "/api/v1/bookings/lookup", params={"key": dataset["keys"][49999]}, headers=admin
            )
            assert recovered.status_code == 200
            report = {
                "label": os.environ.get("LOAD_RUN_LABEL", "prompt10-current"),
                "dataset": {k: v for k, v in dataset.items() if k not in ["keys", "password_hash"]},
                "seed_seconds": round(seed_seconds, 3),
                "users": 50,
                "observer_accounts": 50,
                "websockets": 100,
                "duration_seconds_per_phase": duration,
                "think_time_seconds": [0.4, 0.8],
                "network": (
                    "Loopback HTTP; SQL end-to-end verified TLS through a byte-forwarding proxy; "
                    "load generator and API in separate processes."
                ),
                "scheduler_enabled": False,
                "results": results,
                "exit_codes": exit_codes,
                "broadcast": {**distribution(latencies), "probe_receivers": len(seen_by)},
                "fault": {
                    "latency_seconds_per_direction": 2,
                    "statuses": [r.status_code for r in fault],
                    "codes": [r.json()["code"] for r in fault],
                    "elapsed_seconds": round(time.perf_counter() - fault_start, 3),
                    "recovered": True,
                },
                "cache": healthy["snapshot_cache"],
                "index": healthy["key_index"],
                "slow_queries": healthy["slow_queries"],
            }
            # Fingerprint-only telemetry is paired with explicit public-fixture EXPLAINs.
            async with engine.connect() as c:
                report["database_version"] = str(await c.scalar(text("SELECT VERSION()")))
                plans = {}
                for label, sql, params in [
                    (
                        "lookup",
                        "SELECT * FROM bookings WHERE booking_key=:key",
                        {"key": dataset["keys"][0]},
                    ),
                    (
                        "mine",
                        (
                            "SELECT * FROM bookings WHERE last_agent_id=:agent "
                            "ORDER BY updated_at DESC,id DESC LIMIT 10"
                        ),
                        {"agent": 1001},
                    ),
                    (
                        "latest_before",
                        (
                            "SELECT booking_id,MAX(id) FROM booking_notes "
                            "IGNORE INDEX (ix_booking_notes_live_booking_created) "
                            "WHERE deleted_at IS NULL AND created_at<:cutoff GROUP BY booking_id"
                        ),
                        {"cutoff": datetime.now(UTC).replace(tzinfo=None)},
                    ),
                    (
                        "latest_after",
                        (
                            "SELECT booking_id,MAX(id) FROM booking_notes "
                            "WHERE deleted_at IS NULL AND created_at<:cutoff GROUP BY booking_id"
                        ),
                        {"cutoff": datetime.now(UTC).replace(tzinfo=None)},
                    ),
                    (
                        "note_window",
                        (
                            "SELECT booking_id,MAX(id),COUNT(*) FROM booking_notes "
                            "WHERE created_at>=:start AND note LIKE :q GROUP BY booking_id"
                        ),
                        {
                            "start": datetime.now(UTC).replace(
                                hour=0, minute=0, second=0, tzinfo=None
                            ),
                            "q": "%supplier%",
                        },
                    ),
                ]:
                    plans[label] = [
                        dict(row)
                        for row in (await c.execute(text("EXPLAIN " + sql), params)).mappings()
                    ]
            report["explain_note_search"] = await note_search_plans(engine, settings)
            report["explain"] = plans
            report["thresholds"] = assess(report)

            def hardware():
                cpu = Path("/sys/fs/cgroup/cpu.max")
                memory = Path("/sys/fs/cgroup/memory.max")
                quota = cpu.read_text().strip() if cpu.exists() else None
                limit = memory.read_text().strip() if memory.exists() else None
                return {
                    "logical_cpus": os.cpu_count(),
                    "cpu_max": quota,
                    "memory_max_bytes": int(limit) if limit and limit != "max" else None,
                    "api_workers": 1,
                    "db_pool_size": settings.db_pool_size,
                }

            report["hardware"] = await asyncio.to_thread(hardware)
            await asyncio.to_thread(
                Path(os.environ["SCHEMA_TEST_REPORT"]).write_text,
                json.dumps(report, indent=2, default=str) + "\n",
            )
            assert all(row["met"] for row in report["thresholds"].values()), (
                "Load targets missed; measured evidence is saved."
            )
            assert not any(exit_codes.values()), (
                "Load reported failures; aggregate evidence is saved."
            )
    finally:
        for ws in peers:
            await ws.close()
        for task in readers:
            task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        server.terminate()
        await asyncio.wait_for(server.wait(), 10)
        log.close()
        await proxy.stop()
        await engine.dispose()
