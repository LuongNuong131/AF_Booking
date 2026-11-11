"""Import, recurring assignment, shared access and metadata preservation on a real TLS DB."""

import asyncio
import base64
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import test_booking_database as support
from sqlalchemy import func, select, update
from test_folder_assignments import source_row, workbook_data

from app.models import Booking, BookingGroup, BookingNote, User

migrated, password_pair, rig = support.migrated, support.password_pair, support.rig
pytestmark = support.pytestmark


async def send(rig, data, apply=False, actor="admin", mapping=None):
    return await rig.client.post(
        "/api/v1/admin/folder-assignments/import",
        headers=rig.headers[actor],
        json={
            "workbook": data,
            "apply": apply,
            "agent_map": mapping or {"Luong": "agent", "Tran": "other"},
        },
    )


async def patch(rig, item, actor="admin", **fields):
    return await rig.client.patch(
        f"/api/v1/folder-assignments/{item['group_id']}",
        headers=rig.headers[actor],
        json={"expected_version": item["version"], **fields},
    )


async def test_preview_import_dedup_qc_role_unknown_review_and_reimport(rig):
    data = workbook_data(
        source_row(),
        source_row(),
        source_row(key="CW9997777-YUL-2609", station="YUL", agent="Tran", kind="HOTEL/GT"),
        source_row(key="CW9997778-LAS-2609", station="LAS", agent="Unknown"),
        source_row(key="CW9997779-YYZ-2609", station="YYZ", status="Cần check"),
    )
    assert (await send(rig, data, actor="agent")).status_code == 403
    preview = await send(rig, data)
    assert preview.status_code == 200, preview.text
    assert preview.json()["duplicate_rows"] == 1 and preview.json()["new_bookings"] == 4
    assert (await rig.get("/folder-assignments", scope="all")).json()["total"] == 0
    imported = await send(rig, data, True)
    assert imported.status_code == 200, imported.text
    mine = (await rig.get("/folder-assignments")).json()
    assert mine["total"] == 1
    assert mine["items"][0]["assigned_to"]["id"] == 3
    assert (await rig.get("/folder-assignments", scope="unassigned")).json()["total"] == 2
    assert (await rig.get("/folder-assignments", scope="review")).json()["total"] == 3
    assert (await rig.get("/folder-assignments", scope="all", size=1, page=2)).json()["total"] == 4
    assert (await rig.get("/folder-assignments", scope="all", q="%_")).json()["total"] == 0
    assert (await rig.get("/folder-assignments", scope="all", region="Europe")).json()["total"] == 0
    assert (
        await patch(rig, mine["items"][0], assigned_to=5, region="Europe", review=None)
    ).status_code == 200
    repeated = await send(rig, data, True)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["new_bookings"] == 0 and repeated.json()["preserved_folders"] == 4
    assert (await rig.get("/folder-assignments")).json()["total"] == 0
    other = (await rig.get("/folder-assignments", user="other", region="Europe")).json()
    assert other["total"] == 1
    async with rig.app.state.engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(BookingNote)) == 0


async def test_assignment_survives_takeover_rollover_and_classification_preserves_overrides(rig):
    assert (await rig.save()).status_code == 200
    assert (await send(rig, workbook_data(source_row()), True)).status_code == 200
    item = (await rig.get("/folder-assignments")).json()["items"][0]
    before = (await rig.get("/bookings/lookup", key=support.KEY)).json()["snapshot"]
    classified = await patch(rig, item, actor="agent", supplier_type="transportation")
    assert classified.status_code == 200, classified.text
    assert (await patch(rig, item, supplier_type="hotel")).status_code == 409
    assert (await patch(rig, item, actor="agent", assigned_to=5)).status_code == 403
    after = (await rig.get("/bookings/lookup", key=support.KEY)).json()["snapshot"]
    assert after["supplier_type"] == "transportation"
    assert after["updated_at"] == before["updated_at"]
    assert after["last_agent"] == before["last_agent"] and after["version"] == before["version"]
    assert (
        await rig.save(user="other", version=1, note="Helping another agent")
    ).status_code == 200
    assert (await rig.get("/folder-assignments")).json()["total"] == 1
    assert (await rig.get("/folder-assignments", user="other")).json()["total"] == 0
    assert (await rig.get("/folder-assignments", user="other", scope="all")).json()["total"] == 1
    result = await rig.app.state.monthly_bookings.run(datetime(2026, 11, 25, tzinfo=UTC))
    assert result.created == 2
    item = (await rig.get("/folder-assignments")).json()["items"][0]
    assert item["folder"]["booking_count"] == 3
    assert item["assigned_to"]["id"] == 3 and item["folder"]["supplier_type"] == "transportation"
    new_key = support.KEY.replace("2609", "2611")
    # Booking overrides stay independent of the folder default.
    response = await rig.client.patch(
        f"/api/v1/bookings/{new_key}/classification",
        headers=rig.headers["other"],
        json={"supplier_type": "hotel"},
    )
    assert response.status_code == 200, response.text
    assert (await patch(rig, item, actor="agent", supplier_type="unclassified")).status_code == 200
    assert (await rig.get("/bookings/lookup", key=new_key)).json()["snapshot"][
        "supplier_type"
    ] == "hotel"


async def test_invalid_owner_and_bad_workbook_roll_back_and_qc_can_manage(rig):
    # Existing accounts can have QC responsibilities as well as Agents.
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(update(User).where(User.id == 5).values(role="qc"))
    await rig.app.state.auth.invalidate_user(5)
    response = await send(rig, workbook_data(source_row(agent="Tran")), True)
    assert response.status_code == 200, response.text
    item = (await rig.get("/folder-assignments", user="other")).json()["items"][0]
    assert (await patch(rig, item, actor="other", assigned_to=3)).status_code == 200
    item = (await rig.get("/folder-assignments")).json()["items"][0]
    assert (await patch(rig, item, assigned_to=99999)).status_code == 422
    assert (await send(rig, "invalid", True)).status_code == 422
    assert (await rig.get("/folder-assignments")).json()["items"][0]["assigned_to"]["id"] == 3


async def test_operator_workbook_when_supplied(rig, password_pair):
    path = os.environ.get("ASSIGNMENT_CHECK_FILE")
    if not path:
        pytest.skip("No operator workbook supplied")
    from factories import user_row

    from app.services.folder_assignments import DEFAULT_AGENT_MAP

    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            User.__table__.insert(),
            [
                user_row(
                    i,
                    password_pair[1],
                    username=username,
                    role="qc" if username in {"NguyenKha", "ThuPhuong"} else "agent",
                )
                for i, username in enumerate(DEFAULT_AGENT_MAP.values(), 20)
            ],
        )
    encoded = base64.b64encode(await asyncio.to_thread(Path(path).read_bytes)).decode()
    response = await send(rig, encoded, True, mapping={"Luong": "LuNu", "Tran": "HuyenTran"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["source_rows"], result["duplicate_rows"], result["new_bookings"]) == (
        240,
        3,
        239,
    )
    assert {r["username"] for r in result["rows"] if r["source_agent"] == "Tran"} == {"HuyenTran"}
    assert {r["username"] for r in result["rows"] if r["source_agent"] == "Thang"} == {"XuanThang"}
    all_items = (await rig.get("/folder-assignments", scope="all", size=100)).json()
    assert all_items["total"] == 239
    async with rig.app.state.engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(Booking)) == 239
        assert await conn.scalar(select(func.count()).select_from(BookingNote)) == 0
        assert (
            await conn.scalar(
                select(func.count())
                .select_from(BookingGroup)
                .where(BookingGroup.assigned_to.is_(None))
            )
            == 6
        )


async def test_deleted_folder_requires_restore_and_external_type_edits_conflict(rig):
    response = await send(rig, workbook_data(source_row()), True)
    assert response.status_code == 200
    item = (await rig.get("/folder-assignments")).json()["items"][0]
    changed = await rig.client.patch(
        "/api/v1/folders/CW2154654-RDU",
        headers=rig.headers["admin"],
        json={"supplier_type": "transportation"},
    )
    assert changed.status_code == 200
    stale = await patch(
        rig, item, actor="agent", supplier_type="hotel", expected_supplier_type="hotel"
    )
    assert stale.status_code == 409
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(BookingGroup)
            .where(BookingGroup.id == item["group_id"])
            .values(deleted_at=datetime.now(UTC))
        )
    rejected = await send(rig, workbook_data(source_row()), True)
    assert rejected.status_code == 422 and "Trash" in rejected.json()["message"]
