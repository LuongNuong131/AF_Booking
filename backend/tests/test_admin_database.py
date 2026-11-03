import csv
import io
import os
from datetime import UTC, datetime, timedelta

import pytest
import test_booking_database as support
import test_realtime_database as realtime
from openpyxl import load_workbook
from sqlalchemy import select, update

from app.models import Booking, BookingNote, BookingTask
from app.services.exports import COLUMNS

migrated = support.migrated
password_pair = support.password_pair
rig = support.rig
live = realtime.live
KEY = support.KEY
pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated admin database"
)


async def call(rig, method, path, body=None, user="admin", **params):
    return await rig.client.request(
        method,
        "/api/v1" + path,
        headers=rig.headers[user],
        params=params,
        **({"json": body} if body is not None else {}),
    )


async def test_admin_acl_users_self_protection_kick_and_audit(rig):
    for path in ["/admin/users", "/admin/audit", "/admin/trash", "/admin/statuses"]:
        assert (await rig.get(path)).status_code == 403
    for body in [{"is_active": False}, {"role": "qc"}]:
        assert (await call(rig, "patch", "/admin/users/1", body)).status_code == 403
    body = {
        "username": "new.agent",
        "full_name": "New Agent",
        "role": "agent",
        "temporary_password": "A-good-temp-pass-2026",
    }
    created = await call(rig, "post", "/admin/users", body)
    assert created.status_code == 200, created.text
    identifier = created.json()["id"]
    assert "password_hash" not in created.text and "current_session_id" not in created.text
    assert (await call(rig, "post", "/admin/users", body)).status_code == 422
    login = await rig.client.post(
        "/api/v1/auth/login",
        json={"username": body["username"], "password": body["temporary_password"]},
    )
    token = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert (await call(rig, "post", f"/admin/users/{identifier}/kick")).json()["kicked"]
    assert (await rig.client.get("/api/v1/auth/me", headers=token)).status_code == 401
    assert (
        await call(rig, "patch", f"/admin/users/{identifier}", {"is_active": False})
    ).status_code == 200
    assert (
        await rig.client.post(
            "/api/v1/auth/login",
            json={"username": body["username"], "password": body["temporary_password"]},
        )
    ).status_code == 401
    assert (
        await call(
            rig,
            "patch",
            f"/admin/users/{identifier}",
            {"is_active": True, "full_name": "Renamed Agent"},
        )
    ).status_code == 200
    assert (
        await call(
            rig,
            "post",
            f"/admin/users/{identifier}/reset-password",
            {"temporary_password": "New-good-temp-pass-2026"},
        )
    ).status_code == 200
    events = (
        await rig.get("/admin/audit", user="admin", entity="user", entity_id=str(identifier))
    ).json()
    assert events["total"] >= 4 and body["temporary_password"] not in str(events)


async def test_delete_restore_rebuild_and_null_last_snapshot_realtime(live, rig):
    first = (await rig.save(note="First surviving note")).json()["note"]
    done = (
        await rig.save(
            version=1, status_code="DONE", note="Done note", invoices={"no_invoice": True}
        )
    ).json()["note"]
    result = await call(
        rig, "delete", f"/admin/notes/{done['id']}", {"reason": "Wrong booking update"}
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["version"] == 3 and not data["is_done"] and data["done_at"] is None
    assert (
        data["last_note_preview"] == "First surviving note"
        and data["invoice_state"] == "no_invoice"
    )
    async with realtime.peer(live, rig) as ws:
        await realtime.event(ws, "lock.snapshot")
        result = await call(
            rig, "delete", f"/admin/notes/{first['id']}", {"reason": "Remove remaining note"}
        )
        event = await realtime.event(ws, "booking.updated")
        assert (
            event["last_agent_id"] is None
            and event["status_code"] is None
            and event["snapshot_rebuilt"]
        )
    assert result.json()["last_status"] is None and result.json()["last_agent"] is None
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["history"]["items"] == []
    trash = (await rig.get("/admin/trash", user="admin")).json()
    assert trash["total"] == 2 and all(n["delete_reason"] for n in trash["items"])
    restored = await call(rig, "post", f"/admin/notes/{done['id']}/restore")
    assert restored.json()["is_done"] and restored.json()["done_at"] == done["created_at"]
    assert (await call(rig, "post", f"/admin/notes/{done['id']}/restore")).json()[
        "version"
    ] == restored.json()["version"]
    assert (
        await call(rig, "delete", f"/admin/notes/{done['id']}", {"reason": "ab"})
    ).status_code == 422
    assert (
        await call(
            rig,
            "delete",
            f"/admin/notes/{done['id']}",
            {"reason": "Unauthorized attempt"},
            user="agent",
        )
    ).status_code == 403


async def test_status_changes_are_dynamic_and_rebuild_done_flags(rig):
    await rig.save()
    statuses = (await rig.get("/admin/statuses", user="admin")).json()
    bundle = next(s for s in statuses if s["code"] == "BUNDLE")
    changed = await call(
        rig,
        "patch",
        "/admin/statuses",
        {"id": bundle["id"], "label": "Ready to close", "is_done": True},
    )
    assert changed.status_code == 200, changed.text
    snapshot = (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]
    assert (
        snapshot["is_done"]
        and snapshot["version"] == 2
        and snapshot["last_status"]["label"] == "Ready to close"
    )
    assert (
        await call(rig, "patch", "/admin/statuses", {"id": bundle["id"], "is_active": False})
    ).status_code == 200
    assert all(s["code"] != "BUNDLE" for s in (await rig.get("/statuses")).json())
    denied = await rig.save(version=2)
    assert denied.status_code == 422 and denied.json()["code"] == "STATUS_INACTIVE"
    assert (
        await call(
            rig,
            "post",
            "/admin/statuses",
            {"code": "CUSTOM", "label": "Custom", "position_label": "In queue"},
        )
    ).status_code == 200


async def test_daily_export_timezone_columns_injection_formats_and_acl(rig):
    note = (await rig.save(note="=1+1")).json()["note"]
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            update(BookingNote)
            .where(BookingNote.id == note["id"])
            .values(created_at=datetime(2026, 11, 2, 17, 15, tzinfo=UTC))
        )
    result = await rig.get("/export/daily", user="admin", date="2026-11-03", format="csv")
    assert result.status_code == 200
    rows = list(csv.reader(io.StringIO(result.content.decode("utf-8-sig"))))
    assert tuple(rows[0]) == COLUMNS and len(rows) == 2
    assert (
        rows[1][0].startswith("03 Nov 2026 00:15:00 +0700")
        and rows[1][2] == "CW 2154654-RDU-2609"
        and rows[1][-1] == "'=1+1"
    )
    xlsx = await rig.get("/export/daily", user="admin", date="2026-11-03", format="xlsx")
    workbook = load_workbook(io.BytesIO(xlsx.content), read_only=True)
    excel = list(workbook.active.values)
    workbook.close()
    assert tuple(excel[0]) == COLUMNS and excel[1][-1] == "'=1+1"
    assert (await rig.get("/export/daily", date="2026-11-03", format="csv")).status_code == 403
    assert (
        len(
            list(
                csv.reader(
                    io.StringIO(
                        (
                            await rig.get(
                                "/export/daily", user="admin", date="2026-11-02", format="csv"
                            )
                        ).text
                    )
                )
            )
        )
        == 1
    )
    rig.app.state.settings.export_booking_key_style = "canonical"
    assert (
        KEY in (await rig.get("/export/daily", user="admin", date="2026-11-03", format="csv")).text
    )


async def test_report_aggregate_task_privacy_and_profile_stats(rig):
    await rig.save()
    async with rig.app.state.engine.begin() as connection:
        book = await connection.scalar(select(Booking.id))
        await connection.execute(
            BookingTask.__table__.insert().values(
                booking_id=book,
                user_id=3,
                message="Private supplier task body",
                remind_at=datetime.now(UTC) - timedelta(hours=1),
                status="pending",
            )
        )
    report = await rig.get("/reports/performance", user="admin", period="week")
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["note_count"] == 1 and data["overdue_tasks_by_user"][0]["count"] == 1
    assert "Private supplier task body" not in report.text
    assert (await rig.get("/reports/performance")).status_code == 403
    renamed = await rig.client.patch(
        "/api/v1/profile",
        headers=rig.headers["agent"],
        json={"full_name": "My New Name", "settings": {"timezone": "Asia/Ho_Chi_Minh"}},
    )
    assert renamed.status_code == 200 and renamed.json()["full_name"] == "My New Name"
    await rig.save(version=1, note="Another note today")
    stats = (await rig.get("/profile/stats")).json()
    assert stats["notes_today"] == 2 and stats["notes_week"] == 2
    assert stats["login_history"] and all("meta" not in row for row in stats["login_history"])


async def test_status_etag_auth_and_export_disconnect_releases_connection(rig):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from zoneinfo import ZoneInfo

    from sqlalchemy import event

    response = await rig.get("/statuses")
    assert response.status_code == 200
    etag = response.headers["etag"]
    assert response.headers["cache-control"] == "private, max-age=60"
    response = await rig.client.get(
        "/api/v1/statuses", headers={**rig.headers["agent"], "If-None-Match": etag}
    )
    assert response.status_code == 304 and not response.content
    assert (
        await rig.client.get("/api/v1/statuses", headers={"If-None-Match": etag})
    ).status_code == 401
    status = (await call(rig, "get", "/admin/statuses")).json()[0]
    await call(rig, "patch", "/admin/statuses", {"id": status["id"], "label": "Updated label"})
    assert (await rig.get("/statuses")).headers["etag"] != etag
    assert (await rig.save(note="Disconnect fixture")).status_code == 200
    invalidated = []
    event.listen(
        rig.app.state.engine.sync_engine, "invalidate", lambda *args: invalidated.append(True)
    )
    day = datetime.now(ZoneInfo(rig.app.state.settings.business_timezone)).date()
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=True))
    with pytest.raises(asyncio.CancelledError):
        async for _ in rig.app.state.exports.rows(day, None, None, request):
            pytest.fail("Disconnected export must not emit rows")
    assert invalidated
    assert rig.app.state.engine.pool.checkedout() == 0
