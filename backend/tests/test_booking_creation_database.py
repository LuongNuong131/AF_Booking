"""Authenticated insert-only booking creation, including concurrent unique-key races."""

import asyncio
import os

import pytest
import test_booking_database as support
from factories import user_row
from sqlalchemy import func, select, update

from app.models import AuditLog, Booking, BookingGroup, BookingNote, User

migrated = support.migrated
password_pair = support.password_pair
rig = support.rig
KEY = support.KEY
pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated booking creation database"
)


async def create(rig, user="agent", **values):
    body = {
        "booking_key": KEY,
        "supplier_name": "Example Hotel",
        "supplier_type": "hotel",
        "confirm_new": True,
    }
    body.update(values)
    return await rig.client.post("/api/v1/bookings", headers=rig.headers[user], json=body)


@pytest.mark.parametrize("actor", ["agent", "qc", "admin"])
async def test_all_roles_create_an_empty_booking_and_first_note_uses_its_version(
    rig, password_pair, actor
):
    if actor == "qc":
        async with rig.app.state.engine.begin() as connection:
            await connection.execute(
                User.__table__.insert(),
                user_row(7, password_pair[1], username="qc", role="qc"),
            )
        login = await rig.client.post(
            "/api/v1/auth/login", json={"username": "qc", "password": password_pair[0]}
        )
        rig.headers["qc"] = {"Authorization": "Bearer " + login.json()["access_token"]}
    response = await create(rig, user=actor, booking_key="cw 2154654 – rdu – 2609")
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["booking_key"] == KEY and item["display_key"] == "CW 2154654-RDU-2609"
    assert item["version"] == 1
    assert item["last_agent"] is None and item["last_status"] is None
    assert item["invoice_state"] == "unknown" and item["invoice_count"] == 0
    assert not item["is_done"] and not item["is_stale"]
    assert KEY in rig.app.state.key_index.keys
    for indexed in (True, False):
        rig.app.state.key_index.ready = indexed
        found = (await rig.get("/bookings/lookup", key=KEY)).json()
        assert found["exists"] and found["history"]["items"] == []
        assert found["snapshot"]["supplier_name"] == "Example Hotel"
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(select(BookingGroup.booking_count)) == 1
        assert await connection.scalar(select(func.count(BookingNote.id))) == 0
        audit = (
            await connection.execute(
                select(AuditLog.action, AuditLog.meta).where(AuditLog.action == "booking_created")
            )
        ).one()
        assert audit.meta["booking_key"] == KEY
    assert (await rig.get("/bookings/mine", user=actor)).json()["total"] == 0
    saved = await rig.save(user=actor, version=item["version"])
    assert saved.status_code == 200, saved.text
    assert saved.json()["snapshot"]["version"] == 2


async def test_duplicate_canonical_variants_and_deleted_history_cannot_be_added(rig):
    first = await rig.save()
    assert first.status_code == 200, first.text
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            update(BookingNote).values(deleted_at=func.current_timestamp(), deleted_by=1)
        )
    for key in [KEY, "cw 2154654 - rdu - 2609", "CW2154654—RDU—2609"]:
        response = await create(rig, booking_key=key, supplier_name=None, supplier_type=None)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "BOOKING_EXISTS"
        assert response.json()["details"]["booking_key"] == KEY
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(select(func.count(Booking.id))) == 1
        assert await connection.scalar(select(BookingGroup.booking_count)) == 1
        assert (
            await connection.scalar(
                select(func.count(AuditLog.id)).where(AuditLog.action == "booking_created")
            )
            == 0
        )


async def test_new_folder_requires_supplier_but_existing_folder_metadata_is_retained(rig):
    for values in [
        {"supplier_name": None},
        {"supplier_name": "  "},
        {"supplier_type": None},
    ]:
        response = await create(rig, **values)
        assert response.status_code == 422 and response.json()["code"] == "SUPPLIER_REQUIRED"
    assert (await create(rig)).status_code == 201
    response = await create(
        rig,
        booking_key="CW2154654-RDU-2610",
        supplier_name="Must not rename the supplier",
        supplier_type="transportation",
    )
    assert response.status_code == 201, response.text
    assert response.json()["supplier_name"] == "Example Hotel"
    assert response.json()["supplier_type"] == "hotel"
    # A different station is a distinct folder, as in the existing multi-station import.
    response = await create(
        rig, booking_key="CW2154654-YUL-2610", supplier_name=None, supplier_type=None
    )
    assert response.status_code == 422 and response.json()["code"] == "SUPPLIER_REQUIRED"
    assert (await create(rig, booking_key="CW2154654-YUL-2610")).status_code == 201
    async with rig.app.state.engine.connect() as connection:
        counts = (await connection.scalars(select(BookingGroup.booking_count))).all()
        assert sorted(counts) == [1, 2]


@pytest.mark.parametrize(
    "key,code",
    [
        ("CW2154654-2609", "STATION_REQUIRED"),
        ("CW2154654-RDU-2613", "INVALID_BOOKING_KEY"),
        ("CW2154654-12-2609", "INVALID_BOOKING_KEY"),
        ("CW2154654-RDU-2609\n", "INVALID_BOOKING_KEY"),
    ],
)
async def test_partial_and_invalid_keys_do_not_create_rows(rig, key, code):
    response = await create(rig, booking_key=key)
    assert response.status_code == 422 and response.json()["code"] == code
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(select(func.count(Booking.id))) == 0
        assert await connection.scalar(select(func.count(BookingGroup.id))) == 0


async def test_similar_key_requires_confirmation_and_duplicate_stays_blocked(rig):
    assert (await create(rig)).status_code == 201
    response = await create(rig, booking_key="CW2154654-RDU-2610", confirm_new=False)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "NEW_BOOKING_NEEDS_CONFIRM"
    assert response.json()["details"]["suggestions"][0]["booking_key"] == KEY
    assert (await create(rig, booking_key="CW2154654-RDU-2610")).status_code == 201
    duplicate = await create(rig)
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "BOOKING_EXISTS"


async def test_concurrent_normal_users_create_one_booking_and_count_once(rig, monkeypatch):
    barrier = asyncio.Barrier(2)

    async def simultaneous_check(raw, session):
        await barrier.wait()
        return []

    monkeypatch.setattr(rig.app.state.booking_writes.suggestions, "find", simultaneous_check)
    responses = await asyncio.gather(
        create(rig, user="agent", confirm_new=False),
        create(rig, user="other", confirm_new=False),
    )
    assert sorted(response.status_code for response in responses) == [201, 409], [
        response.text for response in responses
    ]
    duplicate = next(response for response in responses if response.status_code == 409)
    assert duplicate.json()["code"] == "BOOKING_EXISTS"
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(select(func.count(Booking.id))) == 1
        assert await connection.scalar(select(func.count(BookingGroup.id))) == 1
        assert await connection.scalar(select(BookingGroup.booking_count)) == 1
        assert (
            await connection.scalar(
                select(func.count(AuditLog.id)).where(AuditLog.action == "booking_created")
            )
            == 1
        )


async def test_creation_requires_authentication_and_keeps_admin_operations_protected(rig):
    response = await rig.client.post("/api/v1/bookings", json={"booking_key": KEY})
    assert response.status_code == 401
    assert (await create(rig)).status_code == 201
    assert (await rig.get("/admin/bookings/monthly", user="agent")).status_code == 403
    response = await rig.client.patch(
        "/api/v1/folders/CW2154654-RDU",
        headers=rig.headers["agent"],
        json={"supplier_name": "Renamed supplier"},
    )
    assert response.status_code == 403
