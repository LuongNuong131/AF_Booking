"""Administrative CRUD, recycle dependencies, booking classification and scoped reports."""

import io
import os
from datetime import UTC, datetime

import pytest
import test_booking_database as support
from openpyxl import load_workbook
from sqlalchemy import select, update

from app.models import (
    Booking,
    BookingNote,
    Status,
    User,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated management database"
)
migrated, password_pair, rig = support.migrated, support.password_pair, support.rig
KEY = support.KEY


async def mutation(rig, resource, values, identifier=None):
    method = rig.client.post if identifier is None else rig.client.patch
    return await method(
        f"/api/v1/admin/data/{resource}" + (f"/{identifier}" if identifier is not None else ""),
        headers=rig.headers["admin"],
        json={"values": values},
    )


async def recycle(rig, resource, identifier, actor="admin"):
    return await rig.client.request(
        "DELETE",
        f"/api/v1/admin/data/{resource}/{identifier}",
        headers=rig.headers[actor],
        json={"reason": "Remove isolated test data"},
    )


async def entries(rig):
    return (await rig.get("/admin/data/trash", user="admin")).json()["items"]


@pytest.mark.parametrize("role", ["agent", "qc", "admin"])
async def test_booking_classification_is_per_record_preserves_work_and_filters(rig, role):
    await rig.save()
    await rig.save(key="CW2154654-RDU-2610")
    if role == "qc":
        async with rig.app.state.engine.begin() as c:
            await c.execute(update(User).where(User.id == 5).values(role="qc"))
        await rig.app.state.auth.invalidate_user(5)
    actor = "other" if role == "qc" else role
    before = (await rig.get("/bookings/lookup", key=KEY)).json()
    r = await rig.client.patch(
        f"/api/v1/bookings/{KEY}/classification",
        headers=rig.headers[actor],
        json={"supplier_type": "transportation", "expected_type": "hotel"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["supplier_type"] == "transportation"
    after = (await rig.get("/bookings/lookup", key=KEY)).json()
    for f in ("version", "last_agent", "last_status", "updated_at", "invoice_state"):
        assert after["snapshot"][f] == before["snapshot"][f]
    assert after["history"] == before["history"]
    assert (await rig.get("/bookings/lookup", key="CW2154654-RDU-2610")).json()["snapshot"][
        "supplier_type"
    ] == "hotel"
    assert (await rig.get("/bookings", supplier_type="transportation")).json()["total"] == 1
    stale = await rig.client.patch(
        f"/api/v1/bookings/{KEY}/classification",
        headers=rig.headers[actor],
        json={"supplier_type": "hotel", "expected_type": "hotel"},
    )
    assert stale.status_code == 409


async def test_unclassified_import_can_be_classified_without_affecting_siblings(rig):
    r = await rig.client.post(
        "/api/v1/admin/bookings/import",
        headers=rig.headers["admin"],
        json={
            "data": "Booking Number,Suppliers,Station Code\n"
            "CW9876543-YUL-2610,Test imported supplier,YUL\n"
            "CW9876543-YUL-2611,Test imported supplier,YUL\n",
            "apply": True,
        },
    )
    assert r.status_code == 200, r.text
    key = "CW9876543-YUL-2610"
    r = await rig.client.patch(
        f"/api/v1/bookings/{key}/classification",
        headers=rig.headers["agent"],
        json={"supplier_type": "hotel", "expected_type": "unclassified"},
    )
    assert r.status_code == 200, r.text
    assert (await rig.get("/bookings/lookup", key="CW9876543-YUL-2611")).json()["snapshot"][
        "supplier_type"
    ] == "unclassified"
    assert (
        await rig.client.patch(
            f"/api/v1/bookings/{key}/classification", json={"supplier_type": "hotel"}
        )
    ).status_code == 401
    assert (
        await rig.client.patch(
            f"/api/v1/bookings/{key}/classification",
            headers=rig.headers["agent"],
            json={"supplier_type": "unclassified"},
        )
    ).status_code == 422


async def test_admin_user_create_edit_recycle_restore_and_purge(rig):
    r = await mutation(
        rig,
        "users",
        {
            "username": "temporary.test",
            "full_name": "Temporary User",
            "role": "agent",
            "is_active": False,
            "temporary_password": "IsolatedTestingPassword123!",
        },
    )
    assert r.status_code == 200, r.text
    identifier = r.json()["id"]
    assert r.json()["is_active"] is False
    assert (
        await mutation(rig, "users", {"full_name": "Edited Test User"}, identifier)
    ).status_code == 200
    assert (await recycle(rig, "users", identifier, "agent")).status_code == 403
    assert (await recycle(rig, "users", 1)).status_code == 403
    assert (await recycle(rig, "users", identifier)).status_code == 200
    assert (await rig.get("/admin/users", user="admin", q="temporary.test")).json()["total"] == 0
    trash = await entries(rig)
    assert len(trash) == 1 and "payload" not in trash[0]
    assert (
        await rig.client.post(
            f"/api/v1/admin/data/trash/{trash[0]['id']}/restore", headers=rig.headers["admin"]
        )
    ).status_code == 200
    assert (await rig.get("/admin/users", user="admin", q="temporary.test")).json()["total"] == 1
    assert (await recycle(rig, "users", identifier)).status_code == 200
    ids = [r["id"] for r in await entries(rig)]
    plan = await rig.client.post(
        "/api/v1/admin/data/trash/preview", headers=rig.headers["admin"], json=ids
    )
    assert plan.status_code == 200 and not plan.json()["blockers"], plan.text
    body = {"ids": ids, "confirmation": "DELETE", "preview_token": plan.json()["token"]}
    assert (
        await rig.client.post(
            "/api/v1/admin/data/trash/purge", headers=rig.headers["agent"], json=body
        )
    ).status_code == 403
    assert (
        await rig.client.post(
            "/api/v1/admin/data/trash/purge",
            headers=rig.headers["admin"],
            json={**body, "preview_token": "stale"},
        )
    ).status_code == 409
    response = await rig.client.post(
        "/api/v1/admin/data/trash/purge", headers=rig.headers["admin"], json=body
    )
    assert response.status_code == 200, response.text
    async with rig.app.state.engine.connect() as c:
        assert await c.scalar(select(User.id).where(User.id == identifier)) is None


async def test_booking_recycle_hides_all_operational_reads_restores_and_purges_children(rig):
    await rig.save()
    before = (await rig.get("/bookings/lookup", key=KEY)).json()
    assert (await recycle(rig, "bookings", KEY)).status_code == 200
    assert (await rig.get("/bookings")).json()["total"] == 0
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["exists"] is False
    assert (await rig.get("/folders/CW2154654-RDU")).json()["months"] == []
    item = (await entries(rig))[0]
    assert (
        await rig.client.post(
            f"/api/v1/admin/data/trash/{item['id']}/restore", headers=rig.headers["admin"]
        )
    ).status_code == 200
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["history"] == before["history"]
    async with rig.app.state.engine.connect() as c:
        note_id = await c.scalar(select(BookingNote.id))
    assert (await recycle(rig, "notes", note_id)).status_code == 200
    assert (await recycle(rig, "bookings", KEY)).status_code == 200
    ids = [r["id"] for r in await entries(rig) if r["resource"] == "bookings"]
    plan = (
        await rig.client.post(
            "/api/v1/admin/data/trash/preview", headers=rig.headers["admin"], json=ids
        )
    ).json()
    assert plan["counts"]["booking_notes"] == 1
    r = await rig.client.post(
        "/api/v1/admin/data/trash/purge",
        headers=rig.headers["admin"],
        json={"ids": ids, "confirmation": "DELETE", "preview_token": plan["token"]},
    )
    assert r.status_code == 200, r.text
    assert await entries(rig) == []
    async with rig.app.state.engine.connect() as c:
        assert await c.scalar(select(Booking.id).where(Booking.booking_key == KEY)) is None
        assert await c.scalar(select(BookingNote.id)) is None


async def test_status_soft_delete_retains_history_but_purge_checks_dependencies(rig):
    await rig.save()
    identifier = (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]["last_status"][
        "code"
    ]
    async with rig.app.state.engine.connect() as c:
        status_id = await c.scalar(select(Status.id).where(Status.code == identifier))
    assert (await recycle(rig, "statuses", status_id)).status_code == 200
    assert all(s["code"] != identifier for s in (await rig.get("/statuses")).json())
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["history"]["items"][0]["status"][
        "code"
    ] == identifier
    ids = [r["id"] for r in await entries(rig)]
    plan = (
        await rig.client.post(
            "/api/v1/admin/data/trash/preview", headers=rig.headers["admin"], json=ids
        )
    ).json()
    assert plan["blockers"]
    r = await rig.client.post(
        "/api/v1/admin/data/trash/purge",
        headers=rig.headers["admin"],
        json={"ids": ids, "confirmation": "DELETE", "preview_token": plan["token"]},
    )
    assert r.status_code == 409


async def test_admin_note_and_invoice_crud_rebuilds_snapshots(rig):
    await rig.save()
    async with rig.app.state.engine.connect() as c:
        book_id = await c.scalar(select(Booking.id).where(Booking.booking_key == KEY))
        status_id = await c.scalar(select(Status.id).where(Status.code == "PARKING"))
        note_id = await c.scalar(select(BookingNote.id).where(BookingNote.booking_id == book_id))
    r = await mutation(
        rig, "notes", {"status_id": status_id, "note": "Admin corrected test note"}, note_id
    )
    assert r.status_code == 200, r.text
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]["last_status"][
        "code"
    ] == "PARKING"
    r = await mutation(rig, "invoices", {"booking_id": book_id, "invoice_number": "TEST-INV-100"})
    assert r.status_code == 200, r.text
    invoice_id = r.json()["id"]
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]["invoice_count"] == 1
    assert (await recycle(rig, "invoices", invoice_id)).status_code == 200
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]["invoice_count"] == 0
    item = next(r for r in await entries(rig) if r["resource"] == "invoices")
    r = await rig.client.post(
        f"/api/v1/admin/data/trash/{item['id']}/restore", headers=rig.headers["admin"]
    )
    assert r.status_code == 200, r.text
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]["invoice_count"] == 1


async def test_report_scope_filters_exports_and_formula_protection(rig):
    await rig.save(note='=HYPERLINK("http://invalid")')
    await rig.save(key="CW9876543-YUL-2610", user="other")
    day = (
        datetime.now(UTC)
        .astimezone(__import__("zoneinfo").ZoneInfo("Asia/Ho_Chi_Minh"))
        .date()
        .isoformat()
    )
    query = dict(date_from=day, date_to=day, scope="mine")
    report = await rig.get("/reports/center", **query)
    assert report.status_code == 200, report.text
    data = report.json()
    assert data["bookings"] == 1 and data["updates"] == 1 and data["items"][0]["agent"]["id"] == 3
    assert (await rig.get("/reports/center", **{**query, "scope": "team"})).status_code == 403
    assert (await rig.get("/reports/center", **{**query, "agent_id": 5})).status_code == 403
    assert (await rig.get("/reports/center", user="admin", **{**query, "scope": "team"})).json()[
        "bookings"
    ] == 2
    r = await rig.get("/reports/center/export", **query, format="xlsx")
    assert r.status_code == 200, r.text[:100]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == [
        "Executive summary",
        "Booking detail",
        "Agent performance",
        "Status distribution",
        "Station breakdown",
        "Supplier classification",
        "Daily trend",
    ]
    sheet = wb["Booking detail"]
    assert sheet.max_row == 2 and sheet.freeze_panes == "B2"
    assert sheet["J2"].data_type != "f" and sheet["J2"].value.startswith("'")
    assert wb["Executive summary"]["B8"].data_type == "n"
    assert sheet["I2"].data_type == "n"
    assert sheet["A1"].fill.fgColor.rgb.endswith("172F49")
    wb.close()
    csv = await rig.get("/reports/center/export", **query, format="csv")
    assert csv.status_code == 200 and csv.content.startswith(b"\xef\xbb\xbf")


async def test_system_detail_exposes_observed_capacity_and_no_secrets(rig):
    assert (await rig.get("/admin/system/detail")).status_code == 403
    r = await rig.get("/admin/system/detail", user="admin")
    assert r.status_code == 200, r.text
    value = r.json()
    assert "runtime" in value and "inventory" in value and value["database_available"]
    for key in ["password_hash", "jwt_secret", "DATABASE_URL", "s3_secret"]:
        assert key not in r.text


async def test_team_report_counts_every_agent_and_actual_daily_update_dates(rig):
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from app.services.reports import day_bounds

    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    yesterday = today - timedelta(days=1)
    await rig.save(note="First day work")
    async with rig.app.state.engine.begin() as c:
        identifier = await c.scalar(select(Booking.id).where(Booking.booking_key == KEY))
        await c.execute(
            update(BookingNote)
            .where(BookingNote.booking_id == identifier)
            .values(
                created_at=day_bounds(yesterday, ZoneInfo("Asia/Ho_Chi_Minh"))[0]
                + timedelta(hours=12)
            )
        )
    await rig.save(user="other", version=1, note="Next day follow-up")
    r = await rig.get(
        "/reports/center",
        user="admin",
        date_from=yesterday.isoformat(),
        date_to=today.isoformat(),
        scope="team",
    )
    assert r.status_code == 200, r.text
    value = r.json()
    assert value["bookings"] == 1 and value["updates"] == 2
    assert {row["key"]: row["updates"] for row in value["agents"]} == {"3": 1, "5": 1}
    assert [row["updates"] for row in value["trend"]] == [1, 1]


async def test_bulk_cleanup_reports_failures_and_legacy_note_deletions_reach_trash(rig):
    r = await rig.get("/admin/data/resources", user="admin")
    assert r.status_code == 200, r.text
    assert all(isinstance(row["fields"], list) for row in r.json())
    r = await rig.client.post(
        "/api/v1/admin/data/users/bulk-delete",
        headers=rig.headers["admin"],
        json={"ids": ["1", "999999"], "reason": "Testing partial cleanup"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == [] and len(r.json()["failed"]) == 2
    await rig.save()
    await rig.save(version=1, status_code="DONE", invoices={"no_invoice": True})
    async with rig.app.state.engine.connect() as c:
        note_id = await c.scalar(select(BookingNote.id).order_by(BookingNote.id.desc()).limit(1))
    r = await rig.client.request(
        "DELETE",
        f"/api/v1/admin/notes/{note_id}",
        headers=rig.headers["admin"],
        json={"reason": "Legacy delete must be recoverable"},
    )
    assert r.status_code == 200, r.text
    item = next(row for row in await entries(rig) if row["resource"] == "notes")
    restored = await rig.client.post(
        f"/api/v1/admin/data/trash/{item['id']}/restore", headers=rig.headers["admin"]
    )
    assert restored.status_code == 200, restored.text
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]["last_status"][
        "code"
    ] == "DONE"


async def test_crud_suppliers_stations_and_managed_child_records(rig):
    station = await mutation(rig, "stations", {"code": "ZZZ", "name": "Temporary test station"})
    assert station.status_code == 200, station.text
    supplier = await mutation(
        rig,
        "suppliers",
        {
            "cw_number": "CW9876543",
            "station_code": "ZZZ",
            "supplier_name": "Temporary test supplier",
            "supplier_type": "unclassified",
            "recurring_enabled": False,
        },
    )
    assert supplier.status_code == 200, supplier.text
    await rig.save()
    async with rig.app.state.engine.connect() as c:
        book_id = await c.scalar(select(Booking.id).where(Booking.booking_key == KEY))
        note_id = await c.scalar(select(BookingNote.id).where(BookingNote.booking_id == book_id))
    examples = [
        (
            "notifications",
            {"booking_id": book_id, "user_id": 3, "type": "stale"},
            {"type": "task_due"},
        ),
        (
            "assignments",
            {
                "booking_id": book_id,
                "note_id": note_id,
                "from_user_id": 3,
                "to_user_id": 5,
                "message": "Review test booking",
                "status": "open",
            },
            {"status": "done"},
        ),
        (
            "tickets",
            {"booking_id": book_id, "message": "Test QC ticket", "status": "pending"},
            {"status": "handled", "handling_note": "Reviewed"},
        ),
        (
            "reminders",
            {
                "booking_id": book_id,
                "user_id": 3,
                "message": "Test reminder",
                "remind_at": "2026-11-20T08:00:00Z",
                "status": "pending",
            },
            {"message": "Updated reminder"},
        ),
        (
            "snippets",
            {"user_id": 3, "title": "Temporary snippet", "text": "Temporary note text"},
            {"text": "Updated note text"},
        ),
    ]
    for resource, values, changes in examples:
        created = await mutation(rig, resource, values)
        assert created.status_code == 200, created.text
        identifier = created.json()["id"]
        assert (await mutation(rig, resource, changes, identifier)).status_code == 200
        assert (await recycle(rig, resource, identifier)).status_code == 200
        entry = next(e for e in await entries(rig) if e["resource"] == resource)
        restored = await rig.client.post(
            f"/api/v1/admin/data/trash/{entry['id']}/restore", headers=rig.headers["admin"]
        )
        assert restored.status_code == 200, restored.text


async def test_purge_queues_private_files_for_durable_cleanup(rig):
    from app.models import Attachment, StorageGarbage

    await rig.save()
    async with rig.app.state.engine.begin() as c:
        note_id = await c.scalar(select(BookingNote.id))
        await c.execute(
            Attachment.__table__.insert().values(
                note_id=note_id,
                file_name="test.png",
                mime_type="image/png",
                size_bytes=100,
                storage_key="isolated/test.png",
            )
        )
    assert (await recycle(rig, "bookings", KEY)).status_code == 200
    ids = [r["id"] for r in await entries(rig)]
    plan = (
        await rig.client.post(
            "/api/v1/admin/data/trash/preview", headers=rig.headers["admin"], json=ids
        )
    ).json()
    r = await rig.client.post(
        "/api/v1/admin/data/trash/purge",
        headers=rig.headers["admin"],
        json={"ids": ids, "confirmation": "DELETE", "preview_token": plan["token"]},
    )
    assert r.status_code == 200, r.text
    async with rig.app.state.engine.connect() as c:
        assert await c.scalar(select(StorageGarbage.storage_key)) == "isolated/test.png"


async def test_private_file_cleanup_retries_and_removes_completed_queue_rows(rig):
    from app.models import StorageGarbage
    from app.services.storage_cleanup import cleanup_storage

    class TestStorage:
        def __init__(self):
            self.fail = True

        async def delete(self, key):
            if self.fail:
                raise RuntimeError("Synthetic storage failure")

    storage = TestStorage()
    rig.app.state.storage = storage
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            StorageGarbage.__table__.insert().values(storage_key="isolated/retry.png")
        )
    with pytest.raises(RuntimeError):
        await cleanup_storage(rig.app.state)
    async with rig.app.state.engine.connect() as connection:
        row = (await connection.execute(select(StorageGarbage))).one()
        assert row.attempts == 1 and row.last_error == "RuntimeError"
    storage.fail = False
    await cleanup_storage(rig.app.state)
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(select(StorageGarbage.id)) is None
