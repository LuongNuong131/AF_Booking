"""Bounded, single-process operational counters; no URLs, SQL text or parameters."""

import asyncio
import hashlib
import heapq
import math
import re
import time
from collections import deque
from datetime import UTC, datetime

from app.core.db import ping_database

BOUNDS = (1, 2, 5, 10, 20, 50, 100, 200, 300, 500, 750, 1000, 2000, 5000, 10000, 30000, math.inf)
GROUPS = {
    "auth",
    "bookings",
    "search",
    "folders",
    "stations",
    "tasks",
    "notifications",
    "profile",
    "admin",
    "reports",
    "export",
    "watching",
    "assignments",
    "users",
    "push",
    "health",
    "ready",
}


def stamp(value):
    return (
        datetime.fromtimestamp(value, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def fingerprint(statement):
    # Never retain even the normalized text. Inline literals/comments can contain
    # secrets too, so strip them before hashing; bound pathological SQL input.
    normalized = re.sub(r"/\*.*?\*/|--[^\n]*|#[^\n]*", " ", statement[:65536], flags=re.S)
    normalized = re.sub(
        r"'(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\"|\b\d+(?:\.\d+)?\b", "?", normalized
    )
    return hashlib.sha256(" ".join(normalized.casefold().split()).encode()).hexdigest()


class Telemetry:
    def __init__(self, slow_ms=200):
        self.clock = time.time
        self.started = self.clock()
        self.groups = {}
        self.slow = {}
        self.slow_ms = slow_ms
        self.points = deque(maxlen=120)
        self.last_sample = None
        self.db_latency_ms = None
        self.db_error = None
        self.degraded_since = None

    def record(self, path, status, milliseconds):
        parts = path.removeprefix("/api/v1/").strip("/").split("/")
        group = parts[0] if parts and parts[0] in GROUPS else "other"
        slot = int(self.clock() // 30)
        ring = self.groups.setdefault(group, [None] * 30)
        bucket = ring[slot % 30]
        if bucket is None or bucket[0] != slot:
            bucket = [slot, 0, 0, [0] * len(BOUNDS), 0.0]
            ring[slot % 30] = bucket
        import bisect

        bucket[1] += 1
        bucket[2] += int(status >= 500)
        bucket[3][bisect.bisect_left(BOUNDS, milliseconds)] += 1
        bucket[4] = max(bucket[4], milliseconds)

    def query(self, statement, milliseconds):
        if milliseconds < self.slow_ms:
            return
        moment = self.clock()
        minute = int(moment // 60)
        entry = self.slow.get(minute % 60)
        if entry is None or entry[0] != minute:
            entry = (minute, [])
            self.slow[minute % 60] = entry
        value = (milliseconds, moment, fingerprint(statement))
        if len(entry[1]) < 20:
            heapq.heappush(entry[1], value)
        elif value > entry[1][0]:
            heapq.heapreplace(entry[1], value)

    def aggregate(self, rings):
        slot = int(self.clock() // 30)
        count = errors = 0
        hist = [0] * len(BOUNDS)
        maximum = 0
        for ring in rings:
            for bucket in ring:
                if bucket is None or not slot - 29 <= bucket[0] <= slot:
                    continue
                count += bucket[1]
                errors += bucket[2]
                hist = [a + b for a, b in zip(hist, bucket[3], strict=True)]
                maximum = max(maximum, bucket[4])

        def percentile(q):
            if not count:
                return None
            target, seen = math.ceil(count * q), 0
            for bound, value in zip(BOUNDS, hist, strict=True):
                seen += value
                if seen >= target:
                    return maximum if math.isinf(bound) else bound

        return dict(
            requests=count,
            errors=errors,
            error_rate=errors / count if count else 0,
            p50_ms=percentile(0.5),
            p95_ms=percentile(0.95),
            p99_ms=percentile(0.99),
        )

    async def sample(self, engine, settings):
        start = time.perf_counter()
        try:
            if engine is None:
                raise RuntimeError("not configured")
            await ping_database(engine, settings.db_connect_timeout_seconds)
            self.db_latency_ms = round((time.perf_counter() - start) * 1000, 3)
            self.db_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.db_latency_ms = None
            self.db_error = type(exc).__name__
        summary = self.aggregate(self.groups.values())
        moment = self.clock()
        if summary["p95_ms"] is not None and summary["p95_ms"] > 500:
            self.degraded_since = moment if self.degraded_since is None else self.degraded_since
        else:
            self.degraded_since = None
        slot = int(moment // 30)
        point = {"at": stamp(moment), **summary, "db_latency_ms": self.db_latency_ms}
        if self.last_sample == slot and self.points:
            self.points[-1] = point
        else:
            self.points.append(point)
            self.last_sample = slot

    def degraded(self):
        return self.degraded_since is not None and self.clock() - self.degraded_since >= 300

    def snapshot(self, engine, ws, scheduler, version):
        moment = self.clock()
        pool = engine.pool if engine is not None else None
        slow = sorted(
            (
                entry
                for minute, rows in self.slow.values()
                for entry in rows
                if entry[1] >= moment - 3600
            ),
            reverse=True,
        )[:20]
        return {
            "generated_at": stamp(moment),
            "uptime_seconds": max(0, moment - self.started),
            "version": version,
            "window_seconds": 900,
            "percentiles_approximate": True,
            "total": self.aggregate(self.groups.values()),
            "groups": [
                {"group": name, **self.aggregate([ring])}
                for name, ring in sorted(self.groups.items())
            ],
            "db_latency_ms": self.db_latency_ms,
            "db_error": self.db_error,
            "pool": {
                "size": pool.size() if pool else 0,
                "checked_out": pool.checkedout() if pool else 0,
                "overflow": max(0, pool.overflow()) if pool else 0,
            },
            "websocket_connections": len(ws.connections),
            "soft_locks": len(ws.locks.locks),
            "jobs": list(scheduler.status.values()),
            "slow_queries": [
                {"fingerprint": digest, "duration_ms": round(ms, 3), "at": stamp(at)}
                for ms, at, digest in slow
            ],
            "points": [
                point
                for point in self.points
                if datetime.fromisoformat(point["at"].replace("Z", "+00:00")).timestamp()
                >= moment - 3600
            ],
            "degraded": self.degraded(),
        }
