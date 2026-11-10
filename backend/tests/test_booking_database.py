"""Booking integration checks on disposable TLS MySQL and TiDB."""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from argon2 import PasswordHasher
from factories import user_row
from fastapi import Request
from sqlalchemy import delete, event, select, text, update

from alembic import command
from app.core.config import Settings
from app.core.timeouts import DeadlineRoute, timeout
from app.core.unit_of_work import transaction
from app.main import create_app
from app.models import (
    Attachment,
    AuditLog,
    Booking,
    BookingAssignment,
    BookingGroup,
    BookingInvoice,
    BookingNote,
    BookingTask,
    BookingWatcher,
    BookingWorkTask,
    DailyReport,
    IntegrityRun,
    NoteSnippet,
    Notification,
    PushSubscription,
    RecycleEntry,
    Station,
    Status,
    StorageGarbage,
    User,
)
from app.scripts.seed import seed_database

pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated booking test database"
)
KEY = "CW2154654-RDU-2609"
ALEMBIC_CONFIG = Path(__file__).resolve().parents[1] / "alembic.ini"


async def test_monthly_generation_cutoff_inheritance_pause_and_no_duplicates(rig):
    data = (
        "Booking Number,Suppliers,Station Code,Supplier Type,Recurring\n"
        "CW2143505-JFK-2604,Example Hotel,JFK,hotel,true\n"
        "CW2143505-JFK-2609,Example Hotel,JFK,hotel,true\n"
        "CW2143505-EWR-2609,Example Hotel,EWR,hotel,false\n"
    )
    response = await rig.client.post(
        "/api/v1/admin/bookings/import",
        headers=rig.headers["admin"],
        json={"data": data, "apply": True},
    )
    assert response.status_code == 200, response.text
    saved = await rig.save(key="CW2143505-JFK-2609", version=1, note="September record")
    assert saved.status_code == 200, saved.text
    service = rig.app.state.monthly_bookings
    before = await service.run(datetime(2026, 11, 24, 16, 59, tzinfo=UTC))
    assert before.period == "2610" and before.created == 1
    assert not (await rig.get("/bookings/lookup", key="CW2143505-JFK-2605")).json()["exists"]
    after = await service.run(datetime(2026, 11, 24, 17, 0, tzinfo=UTC))
    assert after.period == "2611" and after.created == 1
    assert (await service.run(datetime(2026, 11, 25, tzinfo=UTC))).created == 0
    found = (await rig.get("/bookings/lookup", key="CW2143505-JFK-2611")).json()
    assert found["exists"] and found["group"]["supplier_type"] == "hotel"
    assert found["snapshot"]["last_status"] is None and found["history"]["items"] == []
    assert found["snapshot"]["invoice_state"] == "unknown"
    assert not (await rig.get("/bookings/lookup", key="CW2143505-EWR-2611")).json()["exists"]
    original = (await rig.get("/bookings/lookup", key="CW2143505-JFK-2609")).json()
    assert original["history"]["items"][0]["note"] == "September record"
    paused = await rig.client.patch(
        "/api/v1/folders/CW2143505-JFK",
        headers=rig.headers["admin"],
        json={"recurring_enabled": False},
    )
    assert paused.status_code == 200 and not paused.json()["recurring_enabled"]
    assert (await service.run(datetime(2026, 12, 25, tzinfo=UTC))).created == 0
    rig.app.state.key_index.ready = False
    assert not (await rig.get("/bookings/lookup", key="CW2143505-JFK-2612")).json()["group"][
        "recurring_enabled"
    ]


async def test_monthly_external_trigger_needs_its_own_secret(rig):
    from pydantic import SecretStr

    route = "/api/v1/internal/bookings/monthly-rollover"
    assert (await rig.client.post(route)).status_code == 401
    rig.app.state.settings.monthly_booking_token = SecretStr("monthly-test-" + "q" * 40)
    assert (await rig.client.post(route, headers=rig.headers["admin"])).status_code == 401
    assert (await rig.get("/admin/bookings/monthly", user="agent")).status_code == 403
    assert (
        await rig.client.post("/api/v1/admin/bookings/monthly/run", headers=rig.headers["agent"])
    ).status_code == 403
    response = await rig.client.post(
        route, headers={"Authorization": "Bearer monthly-test-" + "q" * 40}
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 0
    status = await rig.get("/admin/bookings/monthly", user="admin")
    assert status.status_code == 200 and status.json()["day"] == 25
    assert status.json()["external_trigger_configured"]


async def test_import_preview_apply_rerun_and_station_month_inheritance(rig):
    data = (
        "Booking Number\tSuppliers\tStation Code\n"
        "CW2143505-JFK-2609\tNew York Marriott Marquis - JFK\tJFK\n"
        "CW2143505-EWR-2609\tNew York Marriott Marquis - EWR\tEWR\n"
    )

    async def send(apply=False, actor="admin"):
        return await rig.client.post(
            "/api/v1/admin/bookings/import",
            headers=rig.headers[actor],
            json={"data": data, "apply": apply},
        )

    assert (await send(actor="agent")).status_code == 403
    preview = await send()
    assert preview.status_code == 200, preview.text
    assert preview.json()["new_bookings"] == 2
    assert not (await rig.get("/bookings/lookup", key="CW2143505-JFK-2609")).json()["exists"]
    imported = await send(True)
    assert imported.status_code == 200, imported.text
    assert imported.json()["new_bookings"] == 2
    for indexed in (True, False):
        rig.app.state.key_index.ready = indexed
        for station in ("JFK", "EWR"):
            found = await rig.get("/bookings/lookup", key=f"CW2143505-{station}-2609")
            assert found.status_code == 200, found.text
            item = found.json()
            assert item["exists"] and item["group"]["station_code"] == station
            assert item["snapshot"]["last_status"] is None
            assert item["snapshot"]["supplier_type"] == "unclassified"
            assert item["history"]["items"] == []
        ambiguous = await rig.get("/bookings/lookup", key="CW2143505-2609")
        assert ambiguous.json()["resolution"]["status"] == "ambiguous"
        assert len(ambiguous.json()["resolution"]["candidates"]) == 2
    classified = await rig.client.patch(
        "/api/v1/folders/CW2143505-JFK",
        headers=rig.headers["admin"],
        json={"supplier_type": "hotel"},
    )
    assert classified.status_code == 200, classified.text
    again = await send(True)
    assert again.status_code == 200, again.text
    assert again.json()["new_bookings"] == 0
    assert again.json()["existing_bookings"] == 2
    month = await rig.get("/bookings/lookup", key="CW2143505-JFK-2610")
    assert month.json()["group"]["supplier_type"] == "hotel"
    assert not month.json()["exists"]
    ewr = await rig.get("/bookings/lookup", key="CW2143505-EWR-2609")
    assert ewr.json()["group"]["supplier_type"] == "unclassified"


async def test_operator_dataset_when_supplied(rig):
    path = os.environ.get("IMPORT_CHECK_FILE")
    if not path:
        pytest.skip("No operator-provided dataset for this run")
    # Browser File.text() preserves CR/LF; Path.read_text() would hide clipboard
    # newline bugs by translating them before the import request is made.
    data = (await asyncio.to_thread(Path(path).read_bytes)).decode("utf-8-sig")
    response = await rig.client.post(
        "/api/v1/admin/bookings/import",
        headers=rig.headers["admin"],
        json={"data": data, "apply": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["unique_bookings"] == 239
    assert response.json()["duplicate_rows"] == 3
    clipboard = data.replace("\r\n", "\n").replace("\n", "\r")
    repeated = await rig.client.post(
        "/api/v1/admin/bookings/import",
        headers=rig.headers["admin"],
        json={"data": clipboard, "apply": True},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["new_bookings"] == 0
    assert repeated.json()["existing_bookings"] == 239
    for key in [
        "CWXXXXXXX1-PTP-2609",
        "CWXXXX-LAS-2609",
        "CW2137352-CPT-2609",
        "CW2137352-JNB-2609",
        "CW2124898-CMN-2609",
        "CW2124898-RAK-2609",
    ]:
        found = await rig.get("/bookings/lookup", key=key)
        assert found.status_code == 200 and found.json()["exists"], found.text
    async with rig.app.state.engine.connect() as connection:
        books = (
            await connection.execute(
                select(Booking.last_status_id, Booking.last_note_id, Booking.is_done)
            )
        ).all()
        assert len(books) == 239 and all(
            r.last_status_id is None and r.last_note_id is None and not r.is_done for r in books
        )


async def test_full_operator_csv_when_supplied(rig):
    path = os.environ.get("FULL_IMPORT_CHECK_FILE")
    if not path:
        pytest.skip("No full operator CSV supplied")
    data = (await asyncio.to_thread(Path(path).read_bytes)).decode("utf-8-sig")
    options = dict(data=data, station_source="station_code", fill_missing_supplier=True)
    preview = await rig.client.post(
        "/api/v1/admin/bookings/import",
        headers=rig.headers["admin"],
        json={**options, "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["source_rows"] == 1425
    assert preview.json()["unique_bookings"] == 1400
    assert preview.json()["duplicate_rows"] == 35
    assert len(preview.json()["adjustments"]) == 14
    imported = await rig.client.post(
        "/api/v1/admin/bookings/import",
        headers=rig.headers["admin"],
        json={**options, "apply": True},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["new_bookings"] == 1400
    repeat = await rig.client.post(
        "/api/v1/admin/bookings/import",
        headers=rig.headers["admin"],
        json={**options, "apply": True},
    )
    assert repeat.status_code == 200 and repeat.json()["new_bookings"] == 0


@dataclass
class Rig:
    app: object
    client: httpx.AsyncClient
    headers: dict[str, dict[str, str]] = field(repr=False)

    async def save(self, key=KEY, user="agent", version=0, **values):
        body = {
            "status_code": "BUNDLE",
            "note": "Checking supplier mail",
            "expected_version": version,
            "client_request_id": str(uuid4()),
            "confirm_new": True,
            "allow_duplicate": True,
            "supplier_name": "Example Hotel",
            "supplier_type": "hotel",
        }
        body.update(values)
        return await self.client.post(
            f"/api/v1/bookings/{key}/notes", headers=self.headers[user], json=body
        )

    async def get(self, path, user="agent", **params):
        return await self.client.get("/api/v1" + path, headers=self.headers[user], params=params)


@pytest.fixture(scope="module")
def password_pair():
    password = secrets.token_urlsafe(24)
    return password, PasswordHasher().hash(password)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrated():
    from sqlalchemy.engine import make_url

    name = make_url(os.environ["SCHEMA_TEST_DATABASE_URL"]).database
    assert name.startswith("booking_schema_") and name.endswith("_test")
    await asyncio.to_thread(command.upgrade, Config(str(ALEMBIC_CONFIG)), "head")


@pytest_asyncio.fixture
async def rig(migrated, password_pair) -> AsyncIterator[Rig]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        scheduler_enabled=False,
        database_url=os.environ["SCHEMA_TEST_DATABASE_URL"],
        database_ssl_ca=os.environ["SCHEMA_TEST_SSL_CA"],
        jwt_secret_key=secrets.token_urlsafe(64),
        db_pool_size=2,
        db_pool_timeout_seconds=0.2,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        await app.state.key_index.stop()
        async with app.state.engine.begin() as connection:
            for model in (
                StorageGarbage,
                RecycleEntry,
                NoteSnippet,
                IntegrityRun,
                DailyReport,
                PushSubscription,
                RecycleEntry,
                BookingAssignment,
                BookingWatcher,
                BookingWorkTask,
                Attachment,
                Notification,
                BookingInvoice,
                BookingTask,
                BookingAssignment,
                BookingWatcher,
                BookingNote,
                Booking,
                BookingGroup,
                Station,
                Status,
                AuditLog,
                User,
            ):
                await connection.execute(delete(model))
            await connection.execute(
                User.__table__.insert(),
                [
                    user_row(identifier, password_pair[1], username=name, role=role)
                    for identifier, name, role in [
                        (1, "admin", "admin"),
                        (3, "agent", "agent"),
                        (5, "other", "agent"),
                    ]
                ],
            )
        await seed_database(app.state.engine, None)
        await app.state.key_index.load()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {}
            for name in ("admin", "agent", "other"):
                response = await client.post(
                    "/api/v1/auth/login", json={"username": name, "password": password_pair[0]}
                )
                assert response.status_code == 200, response.text
                headers[name] = {"Authorization": "Bearer " + response.json()["access_token"]}
                await client.get("/api/v1/auth/me", headers=headers[name])
            yield Rig(app, client, headers)


async def test_first_note_folder_station_canonical_snapshot(rig):
    response = await rig.save()
    assert response.status_code == 200, response.text
    assert response.json()["snapshot"]["version"] == 1
    assert response.json()["snapshot"]["display_key"] == "CW 2154654-RDU-2609"
    async with rig.app.state.engine.connect() as connection:
        group = (await connection.execute(select(BookingGroup))).one()
        assert group.booking_count == 1 and group.supplier_name == "Example Hotel"
        assert await connection.scalar(select(Station.code)) == "RDU"
        assert await connection.scalar(select(Booking.booking_key)) == KEY
        assert await connection.scalar(
            select(AuditLog.action).where(AuditLog.action == "booking_note_created")
        )
    assert KEY in rig.app.state.key_index.keys
    lookup = await rig.get("/bookings/lookup", key="cw 2154654 - rdu - 2609")
    assert (
        lookup.status_code == 200 and lookup.json()["snapshot"]["supplier_name"] == "Example Hotel"
    )
    assert all(
        name in lookup.headers["server-timing"] for name in ["key_index", "snapshot", "notes"]
    )


async def test_takeover_notifications_and_ownership(rig):
    await rig.save()
    second = await rig.save(user="other", version=1)
    assert second.status_code == 200 and second.json()["snapshot"]["version"] == 2
    result = (await rig.get("/notifications")).json()
    assert result["unread_count"] == 1 and result["items"][0]["type"] == "taken_over"
    identifier = result["items"][0]["id"]
    assert (await rig.get("/notifications", user="other")).json()["unread_count"] == 0
    assert (
        await rig.client.post(
            f"/api/v1/notifications/{identifier}/read", headers=rig.headers["other"]
        )
    ).status_code == 404
    assert (
        await rig.client.post(
            f"/api/v1/notifications/{identifier}/read", headers=rig.headers["agent"]
        )
    ).status_code == 200
    assert (await rig.get("/notifications")).json()["unread_count"] == 0
    await rig.save(version=2)
    await rig.client.post("/api/v1/notifications/read-all", headers=rig.headers["other"])
    assert (await rig.get("/notifications", user="other")).json()["unread_count"] == 0


async def test_version_conflict_rolls_back_with_latest_snapshot(rig):
    await rig.save()
    result = await rig.save()
    assert result.status_code == 409 and result.json()["code"] == "VERSION_CONFLICT"
    assert result.json()["details"]["version"] == 1
    async with rig.app.state.engine.connect() as connection:
        assert len((await connection.execute(select(BookingNote.id))).all()) == 1


@pytest.mark.parametrize("status", ["REJECTION", "PARKING"])
async def test_required_note(rig, status):
    for value in (None, " \t\x00\n"):
        result = await rig.save(status_code=status, note=value)
        assert result.status_code == 422 and result.json()["code"] == "NOTE_REQUIRED"
    assert (await rig.save(status_code=status, note="Reason recorded")).status_code == 200


async def test_status_length_and_control_cleaning(rig):
    assert (await rig.save(status_code="MISSING")).json()["code"] == "STATUS_INACTIVE"
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            update(Status).where(Status.code == "BUNDLE").values(is_active=False)
        )
    assert (await rig.save()).json()["code"] == "STATUS_INACTIVE"
    assert (await rig.save(status_code="PARKING", note="a" * 5001)).status_code == 422
    result = await rig.save(status_code="PARKING", note="Before\x00\u200b\r\nafter")
    assert result.json()["note"]["note"] == "Before\nafter"
    assert result.json()["snapshot"]["last_note_preview"] == "Before\nafter"


async def test_done_invoice_warning_and_reopen(rig):
    assert (await rig.save(status_code="DONE")).json()["code"] == "INVOICE_REQUIRED"
    result = await rig.save(status_code="DONE", invoices={"no_invoice": True})
    assert result.status_code == 200, result.text
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["done_warning"] is None
    lookup = (await rig.get("/bookings/lookup", key=KEY, user="other")).json()
    assert "already marked this booking Done" in lookup["done_warning"]
    assert lookup["snapshot"]["done_at"]
    assert (await rig.save(version=1)).json()["snapshot"]["done_at"] is None
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["done_warning"] is None


async def test_supplier_reuse_and_station_write_rules(rig):
    assert (await rig.save(supplier_name=None, supplier_type=None)).json()[
        "code"
    ] == "SUPPLIER_REQUIRED"
    assert (await rig.save(supplier_name="ab")).json()["code"] == "SUPPLIER_REQUIRED"
    await rig.save()
    result = await rig.save(key=KEY[:-4] + "2610", supplier_name=None, supplier_type=None)
    assert (
        result.status_code == 200
        and result.json()["snapshot"]["supplier"]["name"] == "Example Hotel"
    )
    missing = await rig.save(key="CW2154654-2609")
    assert (
        missing.json()["code"] == "STATION_REQUIRED"
        and missing.json()["details"]["suggested_key"] == KEY
    )
    other_station = await rig.save(key=KEY.replace("RDU", "YUL"))
    assert other_station.status_code == 200, other_station.text
    assert other_station.json()["snapshot"]["station_code"] == "YUL"
    ambiguous_write = await rig.save(key="CW2154654-2609")
    assert ambiguous_write.json()["code"] == "STATION_REQUIRED"
    assert not ambiguous_write.json().get("details")

    assert (await rig.save(key="CW9999999-2609")).json()["code"] == "STATION_REQUIRED"
    assert (await rig.save(key="cw2154654-rdu-2609")).json()["code"] == "INVALID_BOOKING_KEY"
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(select(BookingGroup.booking_count)) == 2


async def test_partial_new_month_invalid_and_ambiguous_resolution(rig):
    assert (await rig.get("/bookings/lookup", key="CW2154654-2609")).json()["resolution"][
        "status"
    ] == "needs_station"
    invalid = (await rig.get("/bookings/lookup", key="CW123-RDU-2609")).json()
    assert (
        invalid["resolution"]["status"] == "invalid"
        and invalid["format_warning"]
        and invalid["version"] == 0
    )
    await rig.save()
    for key in ("CW2154654-2609", "CW 2154654-2609"):
        result = (await rig.get("/bookings/lookup", key=key)).json()
        assert (
            result["resolution"]["status"] == "resolved_from_partial"
            and result["booking_key"] == KEY
            and result["exists"]
        )
    result = (await rig.get("/bookings/lookup", key="CW2154654-2610")).json()
    assert (
        result["resolution"]["status"] == "resolved_from_partial"
        and not result["exists"]
        and result["group_exists"]
    )
    async with rig.app.state.engine.begin() as connection:
        group = await connection.scalar(select(Booking.group_id))
        await connection.execute(
            Booking.__table__.insert().values(
                booking_key=KEY.replace("RDU", "YUL"),
                group_id=group,
                cw_number="CW2154654",
                station_code="YUL",
                period="2609",
            )
        )
    await rig.app.state.key_index.load()
    result = (await rig.get("/bookings/lookup", key="CW2154654-2609")).json()
    assert (
        result["resolution"]["status"] == "ambiguous"
        and len(result["resolution"]["candidates"]) == 2
    )


async def test_idempotency_original_response_and_uuid_misuse(rig):
    request_id = str(uuid4())
    first = await rig.save(client_request_id=request_id)
    await rig.save(version=1, note="Later update")
    retry = await rig.save(client_request_id=request_id)
    assert retry.status_code == 200 and retry.json() == first.json()
    assert (await rig.save(client_request_id=request_id, note="Different")).status_code == 422
    assert (await rig.save(user="other", client_request_id=request_id)).status_code == 422
    async with rig.app.state.engine.connect() as connection:
        assert len((await connection.execute(select(BookingNote.id))).all()) == 2


async def test_mine_pagination_tasks_and_filters(rig):
    for month in ("2609", "2610", "2611"):
        assert (await rig.save(key=KEY[:-4] + month)).status_code == 200
    async with rig.app.state.engine.begin() as connection:
        ids = (await connection.execute(select(Booking.id).order_by(Booking.id))).scalars().all()
        await connection.execute(
            BookingTask.__table__.insert(),
            [
                {
                    "booking_id": ids[0],
                    "user_id": user,
                    "message": "Private reminder",
                    "remind_at": datetime.now(UTC),
                }
                for user in (3, 3, 5)
            ],
        )
    first = (await rig.get("/bookings/mine", size=2)).json()
    second = (await rig.get("/bookings/mine", page=2, size=2)).json()
    assert (
        first["total"] == 3
        and len(second["items"]) == 1
        and second["items"][0]["my_pending_tasks"] == 2
    )
    assert {i["booking_key"] for i in first["items"]}.isdisjoint(
        {i["booking_key"] for i in second["items"]}
    )
    assert (await rig.get("/bookings/mine", user="other")).json()["total"] == 0
    assert len((await rig.get("/bookings/lookup", key=KEY)).json()["my_tasks"]) == 2
    assert len((await rig.get("/bookings/lookup", key=KEY, user="other")).json()["my_tasks"]) == 1
    for params in (
        {"q": "cw 2154654"},
        {"supplier": "Example"},
        {"station_code": "RDU"},
        {"supplier_type": "hotel"},
        {"status_code": "BUNDLE"},
        {"agent_id": 3},
    ):
        assert (await rig.get("/bookings", **params)).json()["total"] == 3
    assert (await rig.get("/bookings", period="2610")).json()["total"] == 1
    assert (await rig.get("/bookings", sort="malicious")).status_code == 422


async def test_stale_threshold_and_done_exclusion(rig):
    await rig.save()
    await rig.save(key=KEY[:-4] + "2610", status_code="DONE", invoices={"no_invoice": True})
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            update(Status).where(Status.code == "BUNDLE").values(stale_after_hours=2)
        )
        await connection.execute(
            update(Booking).values(updated_at=datetime.now(UTC) - timedelta(hours=3))
        )
    rig.app.state.snapshot_cache.clear()
    result = (await rig.get("/bookings/stale", scope="all")).json()
    assert (
        result["total"] == 1
        and result["items"][0]["stale_hours"] >= 3
        and result["items"][0]["booking_key"] == KEY
    )
    assert (await rig.get("/bookings/stale", user="other")).json()["total"] == 0
    assert (await rig.get("/bookings", stale=True)).json()["total"] == 1
    assert (await rig.get("/bookings", stale=False)).json()["total"] == 1


async def test_history_cursor_ties_deleted_notes_and_attachments(rig):
    for version in range(4):
        assert (await rig.save(version=version)).status_code == 200
    async with rig.app.state.engine.begin() as connection:
        ids = (
            (await connection.execute(select(BookingNote.id).order_by(BookingNote.id)))
            .scalars()
            .all()
        )
        await connection.execute(
            update(BookingNote).values(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
        await connection.execute(
            update(BookingNote).where(BookingNote.id == ids[1]).values(deleted_at=datetime.now(UTC))
        )
        await connection.execute(
            Attachment.__table__.insert().values(
                note_id=ids[3],
                file_name="invoice.pdf",
                mime_type="application/pdf",
                size_bytes=10,
                storage_key="placeholder",
            )
        )
        await connection.execute(
            Attachment.__table__.insert().values(
                note_id=ids[3],
                file_name="second.pdf",
                mime_type="application/pdf",
                size_bytes=15,
                storage_key="placeholder-2",
            )
        )
    single = (await rig.get(f"/bookings/{KEY}/notes", limit=1)).json()
    assert [item["id"] for item in single["items"]] == [ids[3]]
    assert len(single["items"][0]["attachments"]) == 2
    following = (
        await rig.get(f"/bookings/{KEY}/notes", limit=1, cursor=single["next_cursor"])
    ).json()
    assert [item["id"] for item in following["items"]] == [ids[2]]
    first = (await rig.get(f"/bookings/{KEY}/notes", limit=2)).json()
    assert [i["id"] for i in first["items"]] == [ids[3], ids[2]] and first["items"][0][
        "attachments"
    ][0]["file_name"] == "invoice.pdf"
    second = (await rig.get(f"/bookings/{KEY}/notes", limit=2, cursor=first["next_cursor"])).json()
    assert [i["id"] for i in second["items"]] == [ids[0]] and second["next_cursor"] is None
    assert (await rig.get(f"/bookings/{KEY}/notes", cursor="invalid")).status_code == 422
    assert (await rig.get(f"/bookings/{KEY}")).status_code == 200


async def test_missing_hot_key_zero_queries_and_folder_edit_invalidates(rig):
    statements = []

    def track(*args):
        statements.append(args[2])

    event.listen(rig.app.state.engine.sync_engine, "before_cursor_execute", track)
    try:
        result = await rig.get("/bookings/lookup", key=KEY)
        assert result.status_code == 200 and not result.json()["exists"] and statements == []
    finally:
        event.remove(rig.app.state.engine.sync_engine, "before_cursor_execute", track)
    await rig.save()
    await rig.get("/bookings/lookup", key=KEY)
    result = await rig.client.patch(
        "/api/v1/folders/CW2154654",
        headers=rig.headers["admin"],
        json={"supplier_name": "Updated Supplier", "supplier_type": "transportation"},
    )
    assert result.status_code == 200, result.text
    assert rig.app.state.key_index.groups["CW2154654-RDU"].info.supplier_name == "Updated Supplier"
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"][
        "supplier_name"
    ] == "Updated Supplier"
    assert (await rig.get("/bookings/lookup", key="CW2154654-2610")).json()["group"][
        "supplier_type"
    ] == "transportation"
    assert (
        await rig.client.patch(
            "/api/v1/folders/CW2154654",
            headers=rig.headers["agent"],
            json={"supplier_name": "Forbidden"},
        )
    ).status_code == 403


async def test_fallback_and_unique_lookup_explain(rig):
    await rig.save()
    rig.app.state.key_index.ready = False
    assert (await rig.get("/bookings/lookup", key="CW2154654-2609")).json()["exists"]
    rig.app.state.settings.key_index_enabled = False
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["exists"]
    async with rig.app.state.engine.connect() as connection:
        version = await connection.scalar(text("SELECT VERSION()"))
        plan = (
            (
                await connection.execute(
                    text("EXPLAIN SELECT id FROM bookings WHERE booking_key=:key"), {"key": KEY}
                )
            )
            .mappings()
            .all()
        )
        if "tidb" in version.lower():
            assert any("Point_Get" in str(row) for row in plan)
        else:
            assert plan[0]["type"] == "const" and plan[0]["key"] == "booking_key"


async def test_unconfigured_image_storage_requires_owned_note(rig):
    saved = (await rig.save()).json()
    path = f"/api/v1/notes/{saved['note']['id']}/attachments?file_name=image.png"
    data = b"\x89PNG\r\n\x1a\nimage"
    assert (
        await rig.client.post(
            path, headers={**rig.headers["agent"], "Content-Type": "image/png"}, content=data
        )
    ).status_code == 503
    assert (
        await rig.client.post(
            path, headers={**rig.headers["other"], "Content-Type": "image/png"}, content=data
        )
    ).status_code == 404


async def test_inline_invoices_validate_and_rollback(rig):
    assert (await rig.save(invoices={"add": ["bad!"]})).json()["code"] == "INVOICE_INVALID"
    assert (await rig.save(invoices={"add": ["INV-001"], "no_invoice": True})).json()[
        "code"
    ] == "INVOICE_STATE_CONFLICT"
    result = await rig.save(status_code="DONE", invoices={"add": [" inv-001 ", "INV-001"]})
    assert result.status_code == 200 and result.json()["snapshot"]["invoice_count"] == 1
    assert result.json()["note"]["invoice_change"]["added"] == ["INV-001"]
    assert (await rig.get("/bookings", invoice="INV-001")).json()["total"] == 1


async def test_concurrent_first_note_and_same_uuid(rig):
    responses = await asyncio.gather(rig.save(), rig.save(user="other"))
    assert sorted(r.status_code for r in responses) == [200, 409]
    request_id = str(uuid4())
    responses = await asyncio.gather(
        rig.save(key=KEY[:-4] + "2610", client_request_id=request_id),
        rig.save(key=KEY[:-4] + "2610", client_request_id=request_id),
    )
    assert [r.status_code for r in responses] == [200, 200] and responses[0].json() == responses[
        1
    ].json()
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(select(BookingGroup.booking_count)) == 2


def add_route(rig, path, endpoint, seconds=0.15):
    rig.app.router.routes.append(DeadlineRoute(path, timeout(seconds)(endpoint), methods=["GET"]))


async def test_slow_query_504_discards_connection_and_recovers(rig, caplog):
    identifiers, invalidations = [], []
    event.listen(
        rig.app.state.engine.sync_engine, "invalidate", lambda *args: invalidations.append(True)
    )

    async def slow(request: Request):
        async with transaction(
            request.app.state.engine, request.app.state.settings, seconds=6
        ) as session:
            identifiers.append(await session.scalar(text("SELECT CONNECTION_ID()")))
            # Start the cancellation budget once SQL setup has completed. Under
            # coverage a busy runner can spend the old 500 ms budget in setup,
            # never reaching the sleeping query this test is meant to cancel.
            request.state.request_timeout_seconds = 0.2
            request.state.request_deadline.reschedule(asyncio.get_running_loop().time() + 0.2)
            await session.execute(text("SELECT SLEEP(2)"))
        return {"ok": True}

    add_route(rig, "/test/slow", slow, seconds=5)
    result = await rig.client.get("/test/slow", headers={"X-Request-ID": "slow-test"})
    assert (
        result.status_code == 504
        and result.json()["code"] == "REQUEST_TIMEOUT"
        and identifiers
        and invalidations
    )
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(text("SELECT CONNECTION_ID()")) != identifiers[0]
        assert await connection.scalar(text("SELECT 1")) == 1
    assert "slow-test" in caplog.text and "/test/slow" in caplog.text


async def test_cancelled_write_rolls_back(rig):
    started = asyncio.Event()

    async def work():
        async with transaction(rig.app.state.engine, rig.app.state.settings) as session:
            session.add(Station(code="ZZZ"))
            await session.flush()
            started.set()
            await session.execute(text("SELECT SLEEP(2)"))

    task = asyncio.create_task(work())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # A disconnected MySQL query can finish on the server before its transaction rolls
    # back. A locking read waits for that rollback and proves the write did not commit.
    async with asyncio.timeout(4), rig.app.state.engine.begin() as connection:
        assert (
            await connection.scalar(
                select(Station.code).where(Station.code == "ZZZ").with_for_update()
            )
            is None
        )


async def test_pool_exhaustion_503_retry_after(rig):
    async def pooled(request: Request):
        async with transaction(request.app.state.engine, request.app.state.settings) as session:
            await session.execute(text("SELECT 1"))
        return {"ok": True}

    add_route(rig, "/test/pooled", pooled, 2)
    async with rig.app.state.engine.connect(), rig.app.state.engine.connect():
        result = await rig.client.get("/test/pooled")
    assert result.status_code == 503 and result.json()["code"] == "SERVICE_BUSY"
    assert int(result.headers["retry-after"]) > 0


async def test_retry_after_postcommit_timeout_never_duplicates(rig, monkeypatch):
    started = asyncio.Event()
    captured = {}

    async def capture_request(scope, receive, send):
        captured["scope"] = scope
        await rig.app(scope, receive, send)

    async def slow_broadcast(event_name, payload):
        started.set()
        # Expire the HTTP deadline only after commit, avoiding a flaky 100 ms DB
        # assumption when TLS/container/CPU startup is contended in CI.
        captured["scope"]["state"]["request_deadline"].reschedule(asyncio.get_running_loop().time())
        await asyncio.Event().wait()

    monkeypatch.setattr(rig.app.state.ws_manager, "broadcast", slow_broadcast)
    request_id = str(uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=capture_request), base_url="http://testserver"
    ) as client:
        first = await Rig(rig.app, client, rig.headers).save(client_request_id=request_id)
    assert first.status_code == 504, first.text
    assert started.is_set()
    retry = await rig.save(client_request_id=request_id)
    assert retry.status_code == 200 and retry.json()["snapshot"]["version"] == 1
    async with rig.app.state.engine.connect() as connection:
        assert len((await connection.execute(select(BookingNote.id))).all()) == 1


async def test_row_lock_wait_returns_service_busy(rig):
    await rig.save()
    async with rig.app.state.engine.connect() as connection:
        async with connection.begin():
            await connection.execute(
                select(Booking.id).where(Booking.booking_key == KEY).with_for_update()
            )
            result = await rig.save(user="other", version=1)
            assert result.status_code == 503 and result.json()["code"] == "SERVICE_BUSY"
            assert int(result.headers["retry-after"]) > 0
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["version"] == 1


async def test_legacy_invalid_key_is_readable_but_cannot_be_written(rig):
    await rig.save()
    legacy = "CW2154654-RDU-2613"
    async with rig.app.state.engine.begin() as connection:
        group_id = await connection.scalar(select(Booking.group_id))
        await connection.execute(
            Booking.__table__.insert().values(
                booking_key=legacy,
                group_id=group_id,
                cw_number="CW2154654",
                station_code="RDU",
                period="2613",
            )
        )
    await rig.app.state.key_index.load()
    result = (await rig.get("/bookings/lookup", key=legacy)).json()
    assert (
        result["exists"]
        and result["format_warning"]
        and result["resolution"]["status"] == "invalid"
    )
    assert (await rig.save(key=legacy, version=1)).json()["code"] == "INVALID_BOOKING_KEY"


async def test_list_queries_are_batched_and_never_read_note_table(rig):
    for month in ("2609", "2610", "2611"):
        await rig.save(key=KEY[:-4] + month)
    statements = []

    def track(*args):
        statements.append(args[2].lower())

    event.listen(rig.app.state.engine.sync_engine, "before_cursor_execute", track)
    try:
        assert (await rig.get("/bookings/mine")).status_code == 200
    finally:
        event.remove(rig.app.state.engine.sync_engine, "before_cursor_execute", track)
    assert not any("booking_notes" in statement for statement in statements)
    task_queries = [s for s in statements if "join booking_tasks" in s]
    assert len(task_queries) == 1 and "group by bookings.id" in task_queries[0]
    assert "join booking_watchers" in task_queries[0]
    assert len([s for s in statements if s.startswith("select ")]) == 4


async def test_summary_text_key_station_partial_and_literal_queries(rig):
    assert (await rig.save(supplier_name="Hôtel Example & Airport")).status_code == 200
    assert (await rig.save(key="CW2154654-RDU-2610")).status_code == 200
    for query in ("hotel example", "Airport", "RDU", "rdu"):
        result = (await rig.get("/bookings", q=query)).json()
        assert result["total"] == 2
    for query in ("CW 2154654-rdu-2609", "cw 2154654-2609"):
        result = (await rig.get("/bookings", q=query)).json()
        assert result["total"] == 1 and result["items"][0]["booking_key"] == KEY
    assert (await rig.get("/bookings", q="%_'")).json()["total"] == 0
    assert (
        await rig.get(
            "/bookings",
            cw_number="CW2154654",
            period="2609",
            station_code="RDU",
            supplier_type="hotel",
            supplier="hotel",
        )
    ).json()["total"] == 1


async def test_agent_lookup_is_authenticated_bounded_and_returns_public_active_summaries(rig):
    assert (await rig.client.get("/api/v1/users/lookup")).status_code == 401
    result = await rig.get("/users/lookup", q="other")
    assert result.status_code == 200 and result.json() == [{"id": 5, "full_name": "Other"}]
    assert len((await rig.get("/users/lookup", limit=1)).json()) == 1
    assert (await rig.get("/users/lookup", q="%_")).json() == []
    assert (await rig.get("/users/lookup", limit=51)).status_code == 422
    response = await rig.client.patch(
        "/api/v1/admin/users/5", headers=rig.headers["admin"], json={"is_active": False}
    )
    assert response.status_code == 200
    assert (await rig.get("/users/lookup", q="other")).json() == []
