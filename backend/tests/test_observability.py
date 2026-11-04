import json
import logging
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.core.monitoring import initialize_monitoring, scrub_event
from app.main import create_app
from app.services.telemetry import Telemetry, fingerprint


def test_json_formatter_keeps_context_and_never_serializes_exception_locals():
    record = logging.LogRecord("app.test", logging.ERROR, "", 0, "Safe error class", (), None)
    record.event = "http.request"
    record.request_id = "test-id"
    record.user_id = 3
    record.duration_ms = 12.5
    result = json.loads(JsonFormatter().format(record))
    assert (
        result["request_id"] == "test-id"
        and result["user_id"] == 3
        and result["duration_ms"] == 12.5
    )
    assert "\n" not in JsonFormatter().format(record)


def test_sentry_is_disabled_by_default_and_scrubs_private_context():
    with patch("sentry_sdk.init") as init:
        assert initialize_monitoring(Settings(_env_file=None)) is None
        init.assert_not_called()
    private = {
        "request": {"data": "private-note", "headers": {"Authorization": "private-token"}},
        "user": {"id": 3},
        "breadcrumbs": {"values": ["private-note"]},
        "extra": {"note": "private-note"},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "private-note",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app.py",
                                "function": "save",
                                "lineno": 12,
                                "vars": {"password": "private-password"},
                                "pre_context": ["private-note"],
                            }
                        ]
                    },
                }
            ]
        },
    }
    cleaned = scrub_event(private)
    assert "private-" not in json.dumps(cleaned)
    assert cleaned["exception"]["values"][0]["type"] == "ValueError"
    assert cleaned["exception"]["values"][0]["stacktrace"]["frames"][0]["function"] == "save"
    with patch("sentry_sdk.init") as init, patch("sentry_sdk.get_client") as client:
        cfg = Settings(_env_file=None, sentry_dsn="https://public@o1.ingest.sentry.io/123")
        assert initialize_monitoring(cfg) is client.return_value
        assert init.call_args.kwargs["before_send"] is scrub_event
        assert init.call_args.kwargs["default_integrations"] is False


def test_operational_error_spikes_are_counted_bounded_and_throttled(caplog):
    metrics = Telemetry(error_threshold=3, error_window=60, error_cooldown=60)
    clock = [1000.0]
    metrics.clock = lambda: clock[0]
    for _ in range(10):
        metrics.record("/api/v1/bookings", 504, 8000)
    assert metrics.error_counts()["REQUEST_TIMEOUT"] == 10
    notices = [r for r in caplog.records if getattr(r, "event", None) == "system.error_spike"]
    assert len(notices) == 1 and notices[0].error_code == "REQUEST_TIMEOUT"
    assert len(metrics.error_buckets["REQUEST_TIMEOUT"]) == 1
    clock[0] += 61
    assert metrics.error_counts() == {"REQUEST_TIMEOUT": 0, "SERVICE_BUSY": 0}
    for _ in range(3):
        metrics.record("/api/v1/bookings", 503, 10)
    assert (
        len([r for r in caplog.records if getattr(r, "event", None) == "system.error_spike"]) == 2
    )


def test_slow_query_warning_is_fingerprint_only_and_coalesced(caplog):
    metrics = Telemetry(slow_ms=200)
    for _ in range(3):
        metrics.query("SELECT * FROM users WHERE password='private-password'", 201)
    warnings = [r for r in caplog.records if getattr(r, "event", None) == "sql.slow"]
    assert len(warnings) == 1 and warnings[0].fingerprint == fingerprint(
        "SELECT * FROM users WHERE password='other'"
    )
    assert "private-password" not in caplog.text
    assert "SELECT" not in caplog.text


def test_root_and_prefixed_db_health_share_rate_limit_and_keep_liveness_free():
    cfg = Settings(_env_file=None, scheduler_enabled=False)
    with (
        patch("app.main.create_database_engine", return_value=AsyncMock()),
        patch("app.api.v1.health.ping_database", new_callable=AsyncMock) as ping,
        TestClient(create_app(cfg)) as client,
    ):
        for i in range(10):
            assert client.get("/health/db" if i % 2 else "/api/v1/health/db").status_code == 200
        limited = client.get("/health/db")
        assert limited.status_code == 429 and limited.headers["retry-after"].isdecimal()
        assert ping.await_count == 10
        assert client.get("/health").status_code == 200
        assert ping.await_count == 10


async def test_large_report_encoding_is_complete_private_and_yields_to_other_tasks():
    import asyncio
    import gzip
    from datetime import UTC, date, datetime

    from app.schemas.operations import DailyBooking, DailyReportDTO
    from app.services.daily_reports import encode_report

    row = DailyBooking(
        booking_key="CW1234567-RDU-2611",
        display_key="CW 1234567-RDU-2611",
        supplier_name="Việt Nam Hotel",
        supplier_type="hotel",
        station_code="RDU",
        status=None,
        agent=None,
        updated_at=datetime.now(UTC),
    )
    report = DailyReportDTO(
        record_rows=[["private note record"]],
        report_date=date(2026, 11, 4),
        timezone="Asia/Ho_Chi_Minh",
        generated_at=datetime.now(UTC),
        cutoff_at=datetime.now(UTC),
        note_count=1,
        new_booking_count=0,
        done_count=0,
        overdue_task_count=0,
        status_distribution=[],
        agents=[],
        stations=[],
        stale=[row] * 450,
        open_rejection_parking=[],
        repeated=[],
        done_not_declared=[],
    )
    ticked = asyncio.Event()

    async def concurrent():
        await asyncio.sleep(0)
        ticked.set()

    task = asyncio.create_task(concurrent())
    encoded = await encode_report(report)
    await task
    assert ticked.is_set()
    decoded = json.loads(gzip.decompress(encoded))
    assert decoded == report.model_dump(mode="json") and len(decoded["stale"]) == 450
    assert "private note record" not in gzip.decompress(encoded).decode()
