from app.services.telemetry import Telemetry, fingerprint


def test_bounded_request_windows_histogram_and_parameter_free_fingerprint():
    metrics = Telemetry(slow_ms=0)
    clock = [1000.0]
    metrics.clock = lambda: clock[0]
    for i in range(1000):
        metrics.record("/api/v1/bookings/CW1234567-RDU-2609", 500 if i % 10 == 0 else 200, 600)
    total = metrics.aggregate(metrics.groups.values())
    assert total["requests"] == 1000 and total["errors"] == 100 and total["p95_ms"] == 750
    for i in range(100):
        metrics.query(f"SELECT {i}, 'private literal'", i)
    assert sum(len(rows) for _, rows in metrics.slow.values()) == 20
    assert fingerprint("SELECT 123, 'private literal'") == fingerprint(
        "SELECT 456, 'another secret'"
    )
    assert "private" not in str(metrics.slow)
    clock[0] += 901
    assert metrics.aggregate(metrics.groups.values())["requests"] == 0


async def test_ring_points_and_five_minutes_degraded_threshold():
    from app.core.config import Settings

    metrics = Telemetry()
    clock = [1000.0]
    metrics.clock = lambda: clock[0]
    for _ in range(121):
        metrics.record("/api/v1/search", 200, 700)
        await metrics.sample(None, Settings(_env_file=None))
        clock[0] += 30
    assert len(metrics.points) == 120 and metrics.degraded_since == 1000
    assert clock[0] - metrics.degraded_since >= 300
    metrics.groups.clear()
    await metrics.sample(None, Settings(_env_file=None))
    assert metrics.degraded_since is None


def test_large_daily_payload_roundtrips_in_json_storage_without_truncation():
    from app.services.daily_reports import pack_report, unpack_report

    payload = {
        "provisional": False,
        "stale": [
            {"booking_key": f"CW1234567-RDU-{i:04}", "supplier": "Example supplier" * 20}
            for i in range(3000)
        ],
    }
    packed = pack_report(payload)
    assert packed["encoding"] == "zlib-base64-v1"
    assert len(packed["data"]) < 512 * 1024
    assert unpack_report(packed) == payload
