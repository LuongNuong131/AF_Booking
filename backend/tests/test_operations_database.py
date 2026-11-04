"""Real TLS database operations, daily aggregates/search, and isolated push transport."""

import base64
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import test_booking_database as support
import test_realtime_database as realtime_support
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from openpyxl import load_workbook
from pydantic import SecretStr
from sqlalchemy import event, func, select, text, update

from app.models import Booking, BookingNote, DailyReport, PushSubscription, User
from app.services.note_search import create_note_search
from app.services.push import PushService
from app.services.reports import day_bounds

migrated, password_pair, rig = support.migrated, support.password_pair, support.rig
live = realtime_support.live
pytestmark = support.pytestmark
KEY = support.KEY


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def configure_push(rig):
    key = ec.generate_private_key(ec.SECP256R1())
    settings = rig.app.state.settings.model_copy(
        update={
            "vapid_public_key": b64(
                key.public_key().public_bytes(
                    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
                )
            ),
            "vapid_private_key": SecretStr(
                b64(key.private_numbers().private_value.to_bytes(32, "big"))
            ),
            "vapid_subject": "mailto:tests@example.com",
        }
    )
    service = PushService(
        rig.app.state.engine, settings, rig.app.state.auth, rig.app.state.ws_manager
    )
    rig.app.state.push = service
    rig.app.state.ws_manager.push = service
    return service


def subscription(token="isolated-test-token"):
    key = ec.generate_private_key(ec.SECP256R1())
    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/" + token,
        "keys": {
            "p256dh": b64(
                key.public_key().public_bytes(
                    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
                )
            ),
            "auth": b64(b"0123456789abcdef"),
        },
    }


async def post(rig, path, body, user="agent", method="POST"):
    return await rig.client.request(method, "/api/v1" + path, headers=rig.headers[user], json=body)


async def test_health_acl_counts_slow_fingerprint_and_scheduler(rig):
    assert (await rig.get("/admin/system/health")).status_code == 403
    metrics = rig.app.state.telemetry
    metrics.slow_ms = 1
    async with rig.app.state.engine.connect() as conn:
        await conn.execute(
            text("SELECT SLEEP(:duration), :secret"),
            {"duration": 0.025, "secret": "private-note-parameter"},
        )
    for _ in range(4):
        await rig.client.get("/health")
    await metrics.sample(rig.app.state.engine, rig.app.state.settings)
    response = await rig.get("/admin/system/health", user="admin")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"]["requests"] >= 4 and payload["db_latency_ms"] is not None
    assert any(r["group"] == "health" and r["requests"] >= 4 for r in payload["groups"])
    assert payload["slow_queries"] and payload["points"]
    assert "private-note-parameter" not in response.text and "SELECT SLEEP" not in response.text
    assert all(set(row) == {"fingerprint", "duration_ms", "at"} for row in payload["slow_queries"])
    assert any(job["name"] == "reports.daily" for job in payload["jobs"])


async def test_daily_totals_excel_formula_and_stable_past_report(rig):
    await rig.save(note="Khách sạn xác nhận")
    await rig.save(version=1, status_code="REJECTION", note="Chờ trả lời")
    await rig.save(version=2, status_code="DONE", note="=1+1", invoices={"no_invoice": True})
    await rig.save(
        key="CW9976543-YUL-2609",
        status_code="PARKING",
        note="Still waiting",
        supplier_type="transportation",
    )
    from zoneinfo import ZoneInfo

    day = datetime.now(ZoneInfo(rig.app.state.settings.business_timezone)).date() - timedelta(
        days=1
    )
    lo, hi = day_bounds(day, ZoneInfo(rig.app.state.settings.business_timezone))
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(update(Booking).values(created_at=lo + timedelta(hours=1)))
        await conn.execute(update(BookingNote).values(created_at=lo + timedelta(hours=2)))
    assert (await rig.get("/reports/daily", date=str(day))).status_code == 403
    response = await rig.get("/reports/daily", user="admin", date=str(day))
    assert response.status_code == 200, response.text
    report = response.json()
    assert (report["note_count"], report["new_booking_count"], report["done_count"]) == (4, 2, 1)
    assert sum(s["count"] for s in report["status_distribution"]) == 4
    assert sum(s["note_count"] for s in report["stations"]) == 4
    assert {s["supplier_type"] for s in report["stations"]} == {"hotel", "transportation"}
    assert len(report["repeated"]) == 1 and report["repeated"][0]["note_count"] == 3
    assert len(report["open_rejection_parking"]) == 1
    file = await rig.get("/reports/daily/export", user="admin", date=str(day))
    assert file.status_code == 200, file.text if file.status_code != 200 else ""
    book = load_workbook(io.BytesIO(file.content), read_only=True)
    assert book.sheetnames == ["Overview", "Daily record", "Stale"]
    rows = list(book["Daily record"].values)
    assert rows[0] == (
        "Date",
        "Agent",
        "Booking",
        "Supplier",
        "Station",
        "Type",
        "Status",
        "Position",
        "Note",
        "Invoice State",
        "Invoice Numbers",
    )
    assert len(rows) == 5 and any(row[8] == "'=1+1" for row in rows[1:])
    assert all(row[2].startswith("CW ") and "Asia/Ho_Chi_Minh" in row[0] for row in rows[1:])
    book.close()
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(update(BookingNote).values(deleted_at=datetime.now(UTC)))
    captured = []

    def capture(conn, cursor, statement, parameters, context, many):
        captured.append(statement.lower())

    event.listen(rig.app.state.engine.sync_engine, "before_cursor_execute", capture)
    try:
        again = await rig.get("/reports/daily", user="admin", date=str(day))
    finally:
        event.remove(rig.app.state.engine.sync_engine, "before_cursor_execute", capture)
    assert again.json() == report
    assert not any("booking_notes" in statement for statement in captured)
    # Export source freezes with the old report too, including notes subsequently
    # moderated away. It must not contradict the retained Overview totals.
    frozen = await rig.get("/reports/daily/export", user="admin", date=str(day))
    workbook = load_workbook(io.BytesIO(frozen.content), read_only=True)
    assert len(list(workbook["Daily record"].values)) == 5
    workbook.close()
    assert "record_rows" not in report


async def test_note_search_vietnamese_grouping_date_deleted_and_window(rig):
    await rig.save(note="Khách sạn đã nhận thư")
    await rig.save(version=1, note="Hỏi khách sạn lần hai")
    await rig.save(key="CW8877665-YUL-2609", note="Khách sạn rất cũ")
    async with rig.app.state.engine.begin() as conn:
        book = await conn.scalar(
            select(Booking.id).where(Booking.booking_key == "CW8877665-YUL-2609")
        )
        await conn.execute(
            update(BookingNote)
            .where(BookingNote.booking_id == book)
            .values(created_at=datetime.now(UTC) - timedelta(days=40))
        )
    response = await rig.get("/search/notes", q="khách sạn")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 1 and payload["items"][0]["match_count"] == 2
    assert payload["items"][0]["note"] == "Hỏi khách sạn lần hai"
    assert payload["strategy"] == "like"
    assert (await rig.get("/search/notes", q="xy")).status_code == 422
    assert (
        await rig.get("/search/notes", q="khách", date_from="2025-01-01", date_to="2026-01-01")
    ).status_code == 422
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(BookingNote)
            .where(BookingNote.id == payload["items"][0]["note_id"])
            .values(deleted_at=datetime.now(UTC))
        )
    assert (await rig.get("/search/notes", q="khách sạn")).json()["items"][0]["match_count"] == 1
    rig.app.state.note_search.limiter.limit = 1
    assert (await rig.get("/search/notes", q="khách")).status_code == 429


async def test_fulltext_configuration_is_explicit_and_optional_mysql_index(rig):
    await rig.save(note="Khách sạn Montreal xác nhận")
    config = rig.app.state.settings.model_copy(update={"note_search_strategy": "fulltext"})
    rig.app.state.note_search = create_note_search(rig.app.state.engine, config)
    response = await rig.get("/search/notes", q="Montreal")
    assert response.status_code == 503 and response.json()["code"] == "SERVICE_BUSY"
    async with rig.app.state.engine.connect() as conn:
        version = str(await conn.scalar(text("SELECT VERSION()"))).lower()
    if "tidb" in version:
        return
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE FULLTEXT INDEX ft_booking_notes_note "
                "ON booking_notes(note) WITH PARSER ngram"
            )
        )
    try:
        response = await rig.get("/search/notes", q="Montreal")
        assert response.status_code == 200 and response.json()["total"] == 1, response.text
        vietnamese = await rig.get("/search/notes", q="khách sạn")
        assert vietnamese.status_code == 200 and vietnamese.json()["total"] == 1
        import asyncio

        from alembic.config import Config

        from alembic import command

        await asyncio.to_thread(command.check, Config(str(support.ALEMBIC_CONFIG)))
    finally:
        async with rig.app.state.engine.begin() as conn:
            await conn.execute(text("DROP INDEX ft_booking_notes_note ON booking_notes"))


async def test_push_ownership_online_gate_minimal_body_and_dead_cleanup(rig):
    service = configure_push(rig)
    body = subscription()
    assert (await rig.get("/push/public-key")).json()["enabled"] is True
    assert (await post(rig, "/push/subscribe", body)).status_code == 200
    assert (await post(rig, "/push/subscribe", body, user="other")).status_code == 404
    assert (
        await post(
            rig, "/push/subscribe", {"endpoint": body["endpoint"]}, user="other", method="DELETE"
        )
    ).status_code == 404
    calls = []
    service.sender = lambda info, payload: calls.append((info, payload)) or 201
    notice = {
        "id": 1,
        "type": "watch_update",
        "booking_key": KEY,
        "display_key": KEY.replace("CW", "CW "),
        "note": "must not be delivered",
    }
    await service.send(3, notice)
    assert len(calls) == 1 and set(calls[0][1]) == {"title", "body", "booking_key", "tag"}
    assert "must not be delivered" not in str(calls[0][1])
    connection = SimpleNamespace(user=SimpleNamespace(id=3), closing=False)
    rig.app.state.ws_manager.connections[3] = connection
    try:
        await service.send(3, notice)
        service.enqueue(3, notice)
        assert len(calls) == 1 and service.queue.empty()
    finally:
        rig.app.state.ws_manager.connections.pop(3)
    service.sender = lambda info, payload: 410
    await service.send(3, notice)
    async with rig.app.state.engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(PushSubscription)) == 0
    assert (await post(rig, "/push/subscribe", body)).status_code == 200
    assert (
        await post(rig, "/push/subscribe", {"endpoint": body["endpoint"]}, method="DELETE")
    ).status_code == 200


async def test_push_rejects_nonprovider_and_revoked_session(rig):
    service = configure_push(rig)
    body = subscription()
    for endpoint in (
        "http://fcm.googleapis.com/x",
        "https://127.0.0.1/x",
        "https://fcm.googleapis.com.evil.test/x",
        "https://user@fcm.googleapis.com/x",
    ):
        result = await post(rig, "/push/subscribe", {**body, "endpoint": endpoint})
        assert result.status_code == 422
    assert (await post(rig, "/push/subscribe", body)).status_code == 200
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(User)
            .where(User.id == 3)
            .values(current_session_id="00000000-0000-4000-8000-000000000001")
        )
    calls = []
    service.sender = lambda info, payload: calls.append(payload) or 201
    await service.send(
        3,
        {"id": 1, "type": "assigned", "booking_key": KEY, "display_key": KEY.replace("CW", "CW ")},
    )
    assert not calls
    async with rig.app.state.engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(PushSubscription)) == 0


async def test_daily_today_cache_and_evening_finalization(rig, monkeypatch):
    from zoneinfo import ZoneInfo

    service = rig.app.state.daily_reports
    zone = ZoneInfo(service.settings.business_timezone)
    today = datetime.now(zone).date()
    await rig.save(note="First note")
    first = (await rig.get("/reports/daily", user="admin")).json()
    assert first["provisional"] is True and first["note_count"] == 1
    await rig.save(version=1, note="Second note")
    assert (await rig.get("/reports/daily", user="admin")).json()["note_count"] == 1
    service.cache = (today, 0, service.cache[2])
    assert (await rig.get("/reports/daily", user="admin")).json()["note_count"] == 2
    service.clock = lambda: (
        datetime.combine(today, datetime.min.time(), zone)
        .replace(hour=18, minute=31)
        .astimezone(UTC)
    )
    await service.tick()
    async with rig.app.state.engine.connect() as conn:
        saved = (
            await conn.execute(select(DailyReport).where(DailyReport.report_date == today))
        ).first()
        assert saved.payload["provisional"] is True
    await rig.save(version=2, note="Late evening note")
    service.clock = lambda: (
        datetime.combine(today + timedelta(days=1), datetime.min.time(), zone)
        .replace(hour=1)
        .astimezone(UTC)
    )
    final = await service.get(today)
    assert final.provisional is False and final.note_count == 3

    async def must_not_recalculate(day):
        raise AssertionError("A finalized past day was recalculated")

    monkeypatch.setattr(service, "calculate", must_not_recalculate)
    await service.tick()
    assert (await service.get(today)).note_count == 3


async def test_real_push_encryption_uses_verified_nonredirecting_transport(rig, monkeypatch):
    import requests

    service = configure_push(rig)
    body = subscription("crypto-fixture")
    captured = []

    def transport(client, method, url, **kwargs):
        assert client.verify is True and client.trust_env is True
        captured.append((method, url, kwargs))
        response = requests.Response()
        response.status_code = 201
        response._content = b""
        return response

    monkeypatch.setattr(requests.Session, "request", transport)
    result = service.deliver(
        body, {"title": "Task due", "booking_key": KEY, "body": "CW 2154654-RDU-2609"}
    )
    assert result == 201 and len(captured) == 1
    method, url, kwargs = captured[0]
    assert method.lower() == "post" and kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 5 and b"CW 2154654" not in kwargs["data"]
    assert any(
        key.lower() == "authorization" and "vapid" in value.lower()
        for key, value in kwargs["headers"].items()
    )


async def test_degraded_health_event_only_reaches_admin(rig, live):
    import asyncio

    from test_realtime_database import event as receive
    from test_realtime_database import peer

    metrics = rig.app.state.telemetry
    clock = [1000.0]
    metrics.clock = lambda: clock[0]
    metrics.groups.clear()
    async with peer(live, rig, "admin") as admin, peer(live, rig, "other") as other:
        await receive(admin, "lock.snapshot")
        await receive(other, "lock.snapshot")
        assert (await receive(admin, "system.health"))["degraded"] is False
        metrics.record("/api/v1/bookings", 200, 700)
        await rig.app.state.scheduler.jobs["system.sample"].callback()
        clock[0] += 301
        metrics.record("/api/v1/bookings", 200, 700)
        await rig.app.state.scheduler.jobs["system.sample"].callback()
        assert (await receive(admin, "system.health"))["degraded"] is True
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(other.recv(), 0.05)


async def test_daily_export_cancels_query_when_client_disconnects(rig, monkeypatch):
    import asyncio
    from zoneinfo import ZoneInfo

    from app.core.unit_of_work import transaction

    started = asyncio.Event()

    async def slow(day):
        async with transaction(rig.app.state.engine, rig.app.state.settings) as session:
            started.set()
            await session.execute(text("SELECT SLEEP(2)"))

    async def disconnected():
        return started.is_set()

    monkeypatch.setattr(rig.app.state.daily_reports, "calculate", slow)
    day = datetime.now(ZoneInfo(rig.app.state.settings.business_timezone)).date()
    async with asyncio.timeout(3):
        with pytest.raises(asyncio.CancelledError):
            await rig.app.state.daily_reports.export(
                day, SimpleNamespace(is_disconnected=disconnected), None, None
            )
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(text("SELECT 1")) == 1


async def test_push_queue_deduplicates_without_dropping_the_first_event_after_boot(
    rig, monkeypatch
):
    service = configure_push(rig)
    monkeypatch.setattr(service, "clock", lambda: 10)
    payload = {
        "id": 7,
        "type": "assigned",
        "booking_key": KEY,
        "display_key": KEY.replace("CW", "CW "),
    }
    service.enqueue(3, payload)
    service.enqueue(3, payload)
    assert service.queue.qsize() == 1
    _, queued = service.queue.get_nowait()
    assert set(queued) == {"id", "type", "booking_key", "display_key"}
