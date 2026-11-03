"""Internal benchmark worker; reads disposable auth on stdin, prints metrics only."""

import asyncio
import json
import os
import sys
import time
from dataclasses import fields, is_dataclass
from pathlib import Path


def retained_bytes(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if isinstance(value, dict):
        return size + sum(
            retained_bytes(k, seen) + retained_bytes(v, seen) for k, v in value.items()
        )
    if isinstance(value, (tuple, list, set)):
        return size + sum(retained_bytes(v, seen) for v in value)
    if is_dataclass(value):
        return size + sum(retained_bytes(getattr(value, f.name), seen) for f in fields(value))
    if hasattr(type(value), "model_fields"):
        return size + retained_bytes(vars(value), seen)
    return size


async def main():
    source = await asyncio.to_thread(lambda: Path(sys.argv[1]).resolve())
    sys.path.insert(0, str(source))
    import httpx
    from sqlalchemy import text

    from app.core.config import Settings
    from app.main import create_app

    private = json.loads(sys.stdin.read())
    settings = Settings(
        _env_file=None,
        app_env="test",
        scheduler_enabled=False,
        database_url=os.environ["SCHEMA_TEST_DATABASE_URL"],
        database_ssl_ca=os.environ["SCHEMA_TEST_SSL_CA"],
        jwt_secret_key=private["signing_key"],
        db_pool_size=2,
        db_pool_timeout_seconds=0.2,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        await app.state.key_index.stop()
        started = time.perf_counter()
        await app.state.key_index.load()
        load_ms = (time.perf_counter() - started) * 1000
        index = app.state.key_index
        memory = retained_bytes(
            {"keys": index.keys, "partial": index.partial, "groups": index.groups}
        )
        hits = misses = 0
        original_get = app.state.snapshot_cache.get

        def counted(identifier):
            nonlocal hits, misses
            result = original_get(identifier)
            if result is None:
                misses += 1
            else:
                hits += 1
            return result

        app.state.snapshot_cache.get = counted
        cases = [
            "CW5000000-YUL-2501",
            "CW9999999-YUL-2501",
            "CW5000000-2501",
            "cw 5000000 - yul - 2501",
        ]
        results = []
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://benchmark"
        ) as client:
            for key in cases:
                for _ in range(3):
                    response = await client.get(
                        "/api/v1/bookings/lookup", params={"key": key}, headers=private["headers"]
                    )
                    assert response.status_code == 200, response.status_code
                samples = []
                for _ in range(60):
                    started = time.perf_counter()
                    response = await client.get(
                        "/api/v1/bookings/lookup", params={"key": key}, headers=private["headers"]
                    )
                    assert response.status_code == 200, response.status_code
                    samples.append((time.perf_counter() - started) * 1000)
                samples.sort()
                results.append(
                    {
                        "query": key,
                        "samples": 60,
                        "p50_ms": round(samples[29], 3),
                        "p95_ms": round(samples[56], 3),
                        "p99_ms": round(samples[59], 3),
                    }
                )
        plans = {}
        async with app.state.engine.connect() as connection:
            queries = {
                "full_key": "SELECT id FROM bookings WHERE booking_key='CW5000000-YUL-2501'",
                "partial_key": (
                    "SELECT id,booking_key,station_code FROM bookings "
                    "WHERE cw_number='CW5000000' AND period='2501'"
                ),
                "summary_recent": (
                    "SELECT id,booking_key,last_note_preview FROM bookings "
                    "ORDER BY updated_at DESC,id DESC LIMIT 20"
                ),
                "summary_mine": (
                    "SELECT id,booking_key,last_note_preview FROM bookings "
                    "WHERE last_agent_id=3 ORDER BY updated_at DESC,id DESC LIMIT 10"
                ),
            }
            for name, query in queries.items():
                plans[name] = [
                    dict(row)
                    for row in (await connection.execute(text("EXPLAIN " + query))).mappings()
                ]
        print(
            json.dumps(
                {
                    "measurements": results,
                    "index_load_ms": round(load_ms, 3),
                    "index_retained_bytes_estimate": memory,
                    "snapshot_cache": {
                        "hits": hits,
                        "misses": misses,
                        "hit_ratio": round(hits / (hits + misses), 4),
                        "ttl_seconds": app.state.snapshot_cache.ttl,
                        "capacity": app.state.snapshot_cache.capacity,
                    },
                    "plans": plans,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
