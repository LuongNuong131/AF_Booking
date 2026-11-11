"""Real database privacy, daily counting, QC tickets and note-image authorization."""

import base64
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import test_booking_database as support
from factories import user_row
from openpyxl import load_workbook
from sqlalchemy import func, select, update

from app.models import Attachment, BookingNote, BookingWorkTask, User
from app.services.reports import day_bounds

migrated, password_pair, rig = support.migrated, support.password_pair, support.rig
pytestmark = support.pytestmark
KEY = support.KEY
ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jkAAAAABJRU5ErkJggg=="
)


async def ticket(rig, message="Customer follow-up required", actor="agent", request_id=None):
    return await rig.client.post(
        f"/api/v1/bookings/{KEY}/work-tasks",
        headers=rig.headers[actor],
        json={"message": message, "client_request_id": request_id or str(uuid4())},
    )


async def qc_account(rig, password_pair):
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            User.__table__.insert(), user_row(7, password_pair[1], username="qc", role="qc")
        )
    login = await rig.client.post(
        "/api/v1/auth/login", json={"username": "qc", "password": password_pair[0]}
    )
    rig.headers["qc"] = {"Authorization": "Bearer " + login.json()["access_token"]}


async def test_personal_daily_counts_distinct_bookings_and_never_leaks_other_agent(rig):
    await rig.save(note="First update")
    await rig.save(version=1, note="=1+1")
    await rig.save(
        user="other",
        version=2,
        status_code="DONE",
        note="Other private work",
        invoices={"no_invoice": True},
    )
    await rig.save(key="CW9997777-YUL-2610", note="Second booking")
    day = datetime.now(ZoneInfo(rig.app.state.settings.business_timezone)).date() - timedelta(
        days=1
    )
    lo, _ = day_bounds(day, ZoneInfo(rig.app.state.settings.business_timezone))
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(update(BookingNote).values(created_at=lo + timedelta(hours=1)))
    response = await rig.get("/reports/mine/daily", date=str(day), agent_id=5, size=1)
    assert response.status_code == 200, response.text
    report = response.json()
    assert (report["booking_count"], report["note_count"], report["done_count"]) == (2, 3, 0)
    assert len(report["items"]) == 1 and report["total"] == 2
    assert "Other private work" not in response.text and report["agent"]["id"] == 3
    other = (await rig.get("/reports/mine/daily", user="other", date=str(day))).json()
    assert (other["booking_count"], other["note_count"], other["done_count"]) == (1, 1, 1)
    excel = await rig.get("/reports/mine/daily/export", date=str(day))
    assert excel.status_code == 200
    workbook = load_workbook(io.BytesIO(excel.content), read_only=True)
    assert workbook["Overview"]["B4"].value == 2
    rows = list(workbook["Bookings"].values)
    assert len(rows) == 3 and any("'=1+1" in row for row in rows)
    assert "Other private work" not in str(rows)
    assert (await rig.get("/reports/daily", date=str(day))).status_code == 403


async def test_personal_report_business_midnight_and_deleted_note(rig):
    first = (await rig.save()).json()["note"]["id"]
    second = (await rig.save(version=1, note="After midnight")).json()["note"]["id"]
    day = datetime.now(ZoneInfo(rig.app.state.settings.business_timezone)).date()
    lo, _ = day_bounds(day, ZoneInfo(rig.app.state.settings.business_timezone))
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(BookingNote)
            .where(BookingNote.id == first)
            .values(created_at=lo - timedelta(milliseconds=1))
        )
        await conn.execute(
            update(BookingNote).where(BookingNote.id == second).values(created_at=lo)
        )
    report = (await rig.get("/reports/mine/daily", date=str(day))).json()
    assert report["note_count"] == 1 and report["booking_count"] == 1
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(BookingNote).where(BookingNote.id == second).values(deleted_at=datetime.now(UTC))
        )
    assert (await rig.get("/reports/mine/daily", date=str(day))).json()["booking_count"] == 0


async def test_ticket_qc_notification_retry_privacy_handling_and_excel(rig, password_pair):
    await qc_account(rig, password_pair)
    await rig.save()
    request_id = str(uuid4())
    response = await ticket(rig, message="=Customer issue", request_id=request_id)
    assert response.status_code == 201, response.text
    task = response.json()
    again = await ticket(rig, message="=Customer issue", request_id=request_id)
    assert again.json()["id"] == task["id"]
    assert (await ticket(rig, actor="other", request_id=request_id)).status_code == 422
    assert (await rig.get("/work-tasks", user="other", creator_id=3)).json()["total"] == 0
    assert (await rig.get("/work-tasks", user="qc")).json()["total"] == 1
    notices = (await rig.get("/notifications", user="qc")).json()["items"]
    assert len([n for n in notices if n["type"] == "work_task_created"]) == 1
    workbook = load_workbook(
        io.BytesIO((await rig.get("/work-tasks/export", user="qc")).content), read_only=True
    )
    assert list(workbook.active.values)[1][3] == "'=Customer issue"
    assert (await rig.get("/work-tasks/export", user="agent")).status_code == 403
    endpoint = f"/api/v1/work-tasks/{task['id']}/handle"
    assert (
        await rig.client.post(endpoint, headers=rig.headers["agent"], json={})
    ).status_code == 403
    handled = await rig.client.post(
        endpoint, headers=rig.headers["qc"], json={"handling_note": "Spoke with customer"}
    )
    assert handled.status_code == 200, handled.text
    assert handled.json()["status"] == "handled" and handled.json()["handled_by"]["id"] == 7
    again = await rig.client.post(
        endpoint, headers=rig.headers["admin"], json={"handling_note": "Must not overwrite"}
    )
    assert (
        again.json()["handled_by"]["id"] == 7
        and again.json()["handling_note"] == "Spoke with customer"
    )
    assert (await rig.get("/work-tasks", user="qc")).json()["total"] == 0
    assert (await rig.get("/work-tasks", user="qc", status="handled")).json()["total"] == 1
    assert any(
        n["type"] == "work_task_handled" for n in (await rig.get("/notifications")).json()["items"]
    )
    async with rig.app.state.engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(BookingWorkTask)) == 1


async def test_pending_tickets_survive_across_days_until_handled(rig):
    await rig.save()
    created = await ticket(rig)
    assert created.status_code == 201
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(BookingWorkTask).values(created_at=datetime.now(UTC) - timedelta(days=7))
        )
    assert (await rig.get("/work-tasks", user="admin")).json()["total"] == 1
    assert (await rig.get("/work-tasks", user="admin", date=str(datetime.now(UTC).date()))).json()[
        "total"
    ] == 0


class MemoryStorage:
    configured = True

    def __init__(self):
        self.objects = {}
        self.writes = 0
        self.fail = False

    async def put(self, key, content, mime):
        if self.fail:
            raise OSError("offline")
        self.objects[key] = content
        self.writes += 1

    async def read(self, key):
        return self.objects[key]


async def upload(rig, note, actor="agent", content=PNG, mime="image/png"):
    return await rig.client.post(
        f"/api/v1/notes/{note}/attachments",
        params={"file_name": "Ảnh booking.png"},
        headers={**rig.headers[actor], "Content-Type": mime},
        content=content,
    )


async def test_images_owned_upload_idempotency_authenticated_read_and_soft_delete(rig):
    saved = (await rig.save()).json()
    note = saved["note"]["id"]
    storage = rig.app.state.storage = MemoryStorage()
    assert (await upload(rig, note, actor="other")).status_code == 404
    created = await upload(rig, note)
    assert created.status_code == 201, created.text
    image = created.json()
    assert (await upload(rig, note)).json()["id"] == image["id"] and storage.writes == 1
    response = await rig.get(f"/attachments/{image['id']}/content", user="other")
    assert response.status_code == 200 and response.content == PNG
    assert response.headers["cache-control"] == "no-store"
    assert (await rig.client.get(f"/api/v1/attachments/{image['id']}/content")).status_code == 401
    history = (await rig.get("/bookings/lookup", key=KEY)).json()["history"]["items"]
    assert history[0]["attachments"][0]["id"] == image["id"]
    assert "storage_key" not in str(history)
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(BookingNote).where(BookingNote.id == note).values(deleted_at=datetime.now(UTC))
        )
    assert (await rig.get(f"/attachments/{image['id']}/content")).status_code == 404


async def test_image_types_limit_failed_storage_and_large_image_body(rig):
    note = (await rig.save()).json()["note"]["id"]
    storage = rig.app.state.storage = MemoryStorage()
    assert (await upload(rig, note, content=b"<html>not image</html>")).status_code == 422
    assert (await upload(rig, note, mime="image/jpeg")).status_code == 422
    storage.fail = True
    assert (await upload(rig, note)).status_code == 503
    async with rig.app.state.engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(Attachment)) == 0
    storage.fail = False
    assert (await upload(rig, note, content=PNG + b"0" * (2 * 1024 * 1024))).status_code == 201
    for n in range(4):
        assert (await upload(rig, note, content=PNG + bytes([n]))).status_code == 201
    assert (await upload(rig, note, content=PNG + b"new")).status_code == 422
    assert (await upload(rig, note, content=PNG + b"0" * (5 * 1024 * 1024))).status_code == 413


async def test_notification_enum_migration_preserves_existing_watch_feed_and_uniqueness(rig):
    import asyncio

    import pytest
    from alembic.config import Config
    from sqlalchemy.exc import IntegrityError

    from alembic import command
    from app.models import Booking, Notification

    assert (await rig.save()).status_code == 200
    async with rig.app.state.engine.begin() as connection:
        booking_id = await connection.scalar(select(Booking.id).where(Booking.booking_key == KEY))
        await connection.execute(
            Notification.__table__.insert(),
            {
                "user_id": 3,
                "booking_id": booking_id,
                "type": "watch_update",
                "merged_count": 2,
            },
        )
    config = Config(str(ALEMBIC_CONFIG_PATH))
    await asyncio.to_thread(command.downgrade, config, "0013")
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.check, config)
    async with rig.app.state.engine.connect() as connection:
        row = (await connection.execute(select(Notification.__table__))).mappings().one()
        assert row["type"] == "watch_update" and row["merged_count"] == 2
        assert row["unread_watch_booking"] == booking_id
    with pytest.raises(IntegrityError):
        async with rig.app.state.engine.begin() as connection:
            await connection.execute(
                Notification.__table__.insert(),
                {"user_id": 3, "booking_id": booking_id, "type": "watch_update"},
            )


async def structured_ticket(rig, key=KEY, issue="cannot_send_rejection_letters", request_id=None):
    return await rig.client.post(
        f"/api/v1/bookings/{key}/work-tasks",
        headers=rig.headers["agent"],
        json={
            "issue_type": issue,
            "message": "The rejection letter could not be sent on TIM Tool.",
            "client_request_id": request_id or str(uuid4()),
        },
    )


async def test_structured_titles_images_details_privacy_and_exact_merge(rig):
    from app.utils.ticket_text import REJECTION_MESSAGE, TITLES

    await rig.save()
    key2 = "CW9997777-YUL-2610"
    await rig.save(key=key2, note="Second booking")
    first = (await structured_ticket(rig)).json()
    second = (await structured_ticket(rig, key=key2)).json()
    contract = (await structured_ticket(rig, issue="contract")).json()
    assert first["title"] == f"{TITLES['cannot_send_rejection_letters']} - {KEY}"
    assert contract["title"] == f"{TITLES['contract']} - {KEY}"
    rig.app.state.storage = MemoryStorage()
    endpoint = f"/api/v1/work-tasks/{first['id']}/attachments"
    image_ids = []
    for number in range(2):
        response = await rig.client.post(
            endpoint,
            headers={**rig.headers["agent"], "Content-Type": "image/png"},
            params={"file_name": f"evidence-{number}.png"},
            content=PNG + bytes([number]),
        )
        assert response.status_code == 201, response.text
        image_ids.append(response.json()["id"])
    again = await rig.client.post(
        endpoint,
        headers={**rig.headers["agent"], "Content-Type": "image/png"},
        params={"file_name": "evidence-0.png"},
        content=PNG + b"\x00",
    )
    assert again.json()["id"] == image_ids[0]
    assert rig.app.state.storage.writes == 2
    assert (await rig.get(f"/work-tasks/{first['id']}", user="other")).status_code == 404
    assert (await rig.get(f"/attachments/{image_ids[0]}/content", user="other")).status_code == 404
    assert (
        await rig.get(f"/attachments/{image_ids[0]}/content", user="admin")
    ).content == PNG + b"\x00"
    detail = (await rig.get(f"/work-tasks/{first['id']}", user="admin")).json()
    assert [f["id"] for f in detail["attachments"]] == image_ids
    assert "storage_key" not in str(detail)
    # Repeated IDs/bookings appear only once; selection order is preserved.
    merge = await rig.client.post(
        "/api/v1/work-tasks/merge",
        headers=rig.headers["admin"],
        json={"ids": [second["id"], first["id"], first["id"]]},
    )
    assert merge.status_code == 200, merge.text
    assert merge.json()["title"] == TITLES["cannot_send_rejection_letters"]
    assert merge.json()["message"] == REJECTION_MESSAGE + f"\n\n{key2}\n{KEY}"
    assert len(merge.json()["attachments"]) == 2
    assert (await rig.get("/work-tasks", user="admin")).json()["total"] == 3
    for ids, actor, expected in [
        ([first["id"], contract["id"]], "admin", 422),
        ([first["id"], 999999], "admin", 404),
        ([first["id"], second["id"]], "agent", 403),
        ([first["id"], first["id"]], "admin", 422),
    ]:
        assert (
            await rig.client.post(
                "/api/v1/work-tasks/merge", headers=rig.headers[actor], json={"ids": ids}
            )
        ).status_code == expected


async def test_ticket_english_validation_retry_mismatch_and_image_limits(rig):
    await rig.save()
    request_id = str(uuid4())
    first = await structured_ticket(rig, request_id=request_id)
    assert first.status_code == 201
    assert (await structured_ticket(rig, request_id=request_id)).json()["id"] == first.json()["id"]
    assert (
        await structured_ticket(rig, request_id=request_id, issue="contract")
    ).status_code == 422
    invalid = await rig.client.post(
        f"/api/v1/bookings/{KEY}/work-tasks",
        headers=rig.headers["agent"],
        json={
            "issue_type": "contract",
            "message": "Không thể gửi thư từ chối",
            "client_request_id": str(uuid4()),
        },
    )
    assert invalid.status_code == 422
    rig.app.state.storage = storage = MemoryStorage()
    endpoint = f"/api/v1/work-tasks/{first.json()['id']}/attachments"

    async def send(content=PNG, mime="image/png", actor="agent"):
        return await rig.client.post(
            endpoint,
            headers={**rig.headers[actor], "Content-Type": mime},
            params={"file_name": "image.png"},
            content=content,
        )

    assert (await send(actor="other")).status_code == 404
    assert (await send(content=b"not an image")).status_code == 422
    storage.fail = True
    assert (await send()).status_code == 503
    storage.fail = False
    # Verify the middleware permits images over the normal JSON body limit.
    assert (await send(content=PNG + b"0" * (2 * 1024 * 1024))).status_code == 201
    for n in range(4):
        assert (await send(content=PNG + bytes([n]))).status_code == 201
    assert (await send()).status_code == 422
    assert (await send(content=PNG + b"0" * (5 * 1024 * 1024))).status_code == 413
    assert (await rig.get("/work-tasks/translation/config")).json() == {"enabled": False}
    assert (
        await rig.client.post(
            "/api/v1/work-tasks/translate",
            headers=rig.headers["agent"],
            json={"text": "Không thể gửi thư"},
        )
    ).status_code == 503


async def test_ticket_recycle_restore_and_purge_preserve_then_queue_images(rig):
    from test_management_database import entries, recycle

    from app.models import StorageGarbage

    await rig.save()
    task = (await structured_ticket(rig)).json()
    rig.app.state.storage = MemoryStorage()
    image = await rig.client.post(
        f"/api/v1/work-tasks/{task['id']}/attachments",
        headers={**rig.headers["agent"], "Content-Type": "image/png"},
        params={"file_name": "evidence.png"},
        content=PNG,
    )
    assert image.status_code == 201
    image_id = image.json()["id"]
    assert (await recycle(rig, "tickets", task["id"])).status_code == 200
    assert (await rig.get(f"/attachments/{image_id}/content")).status_code == 404
    trash = (await entries(rig))[0]
    assert (
        await rig.client.post(
            f"/api/v1/admin/data/trash/{trash['id']}/restore", headers=rig.headers["admin"]
        )
    ).status_code == 200
    assert (await rig.get(f"/attachments/{image_id}/content")).status_code == 200
    assert (await recycle(rig, "tickets", task["id"])).status_code == 200
    ids = [item["id"] for item in await entries(rig)]
    preview = (
        await rig.client.post(
            "/api/v1/admin/data/trash/preview", headers=rig.headers["admin"], json=ids
        )
    ).json()
    purged = await rig.client.post(
        "/api/v1/admin/data/trash/purge",
        headers=rig.headers["admin"],
        json={"ids": ids, "confirmation": "DELETE", "preview_token": preview["token"]},
    )
    assert purged.status_code == 200, purged.text
    async with rig.app.state.engine.connect() as connection:
        assert (
            await connection.scalar(select(Attachment.id).where(Attachment.id == image_id)) is None
        )
        assert (await connection.scalar(select(StorageGarbage.storage_key))).startswith("tickets/")
