"""Folder/search/station integration and performance checks on isolated TLS databases."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import test_booking_database as booking_support
from sqlalchemy import event, select, update

from app.models import AuditLog, Booking, Station, Status

pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated folder test database"
)
# Reuse the existing disposable DB/auth fixture rather than duplicate its setup.
Rig = booking_support.Rig
migrated = booking_support.migrated
password_pair = booking_support.password_pair
rig = booking_support.rig

CW = "CW2154927"
KEY = CW + "-YUL-2608"


async def seed_folder(
    rig: Rig,
    *,
    cw=CW,
    station="YUL",
    name="Hotellus Double Tree YUL",
    supplier_type="hotel",
    periods=("2607", "2608", "2609"),
):
    for period in periods:
        response = await rig.save(
            key=f"{cw}-{station}-{period}", supplier_name=name, supplier_type=supplier_type
        )
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("query", ["CW2154927", "CW2154927-YUL", "CW 2154927"])
async def test_exact_folder_all_months_and_latest_is_period_not_insert_order(rig, query):
    await seed_folder(rig, periods=("2609", "2607", "2608"))
    await rig.save(key=KEY, version=1, status_code="DONE", invoices={"no_invoice": True})
    result = await rig.get("/search", q=query)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["kind"] == "folder"
    assert [m["period"] for m in data["months"]] == ["2609", "2608", "2607"]
    assert data["folder"]["booking_count"] == 3 and data["folder"]["open_count"] == 2
    assert data["folder"]["latest"]["booking_key"].endswith("2609")
    assert data["folder"]["latest"]["period_label"] == "Sep 2026"
    assert data["months"][1]["period_label"] == "Aug 2026"
    direct = (await rig.get(f"/folders/{CW}")).json()
    assert direct["folder"] == data["folder"] and direct["months"] == data["months"]
    assert (await rig.get("/search", q=CW + "-RDU")).json()["kind"] == "none"


async def test_station_sections_period_and_global_pagination(rig):
    await seed_folder(rig)
    await seed_folder(rig, cw="CW2154928", name="Crew Shuttle YUL", supplier_type="transportation")
    await seed_folder(rig, cw="CW2154929", station="RDU", name="Other Station")
    for query in ("YUL", "yul"):
        result = (await rig.get("/search", q=query)).json()
        assert result["kind"] == "station" and result["station"]["code"] == "YUL"
        assert result["total"] == 2 and [s["type"] for s in result["sections"]] == [
            "hotel",
            "transportation",
            "unclassified",
        ]
        assert all(
            s["items"][0]["cw_number"] and s["items"][0]["supplier_name"]
            for s in result["sections"]
            if s["items"]
        )
    first = (await rig.get("/search", q="YUL", size=1)).json()
    second = (await rig.get("/search", q="YUL", size=1, page=2)).json()
    assert first["total"] == 2

    def keys(data):
        return [f["cw_number"] for section in data["sections"] for f in section["items"]]

    assert len(keys(first)) == len(keys(second)) == 1 and keys(first) != keys(second)
    for query in ("YUL-2608", "yul 2608"):
        result = (await rig.get("/search", q=query)).json()
        assert (
            result["kind"] == "station_period"
            and result["period_label"] == "Aug 2026"
            and result["total"] == 2
        )
        assert all(
            row["station_code"] == "YUL" and row["period"] == "2608" for row in result["items"]
        )
        assert all("supplier_name" in row and "display_key" in row for row in result["items"])
    assert (await rig.get("/search", q="ZZZ-2608")).json()["kind"] == "none"


@pytest.mark.parametrize(
    "query", ["CW2154927-YUL-2608", "cw 2154927 - yul - 2608", "CW 2154927-YUL-2608"]
)
async def test_full_key_search_is_lightweight(rig, query):
    await seed_folder(rig)
    result = (await rig.get("/search", q=query)).json()
    assert result["kind"] == "booking" and result["booking_key"] == KEY and result["exists"]
    assert result["display_key"] == "CW 2154927-YUL-2608"
    assert (
        "history" not in result and result["group"]["supplier_name"] == "Hotellus Double Tree YUL"
    )
    missing = (await rig.get("/search", q="CW9999999-YUL-2608")).json()
    assert missing["kind"] == "booking" and not missing["exists"]


@pytest.mark.parametrize("query", ["CW2154927-2608", "CW 2154927-2608"])
async def test_partial_search_reuses_lookup_resolution(rig, query):
    await seed_folder(rig)
    result = (await rig.get("/search", q=query)).json()
    lookup = (await rig.get("/bookings/lookup", key=query)).json()
    assert result["kind"] == "partial_key" and result["resolution"] == lookup["resolution"]
    missing = (await rig.get("/search", q="CW9999999-2608")).json()
    assert missing["resolution"]["status"] == "needs_station"


@pytest.mark.parametrize("ready", [True, False])
async def test_supplier_accents_multiword_prefixes_order_and_rename(rig, ready):
    await seed_folder(rig, name="Hôtel Double Tree d/b/a & Étoile YUL")
    await seed_folder(rig, cw="CW2154928", name="Unrelated Supplier")
    rig.app.state.key_index.ready = ready
    for query in ("hotel", "hôtel", "double tree", "tree double", "eto hot", "d/b/a etoile"):
        result = (await rig.get("/search", q=query)).json()
        assert result["kind"] == "folders" and result["total"] == 1, (query, result)
        assert result["items"][0]["cw_number"] == CW
    assert (await rig.get("/search", q="double absent")).json()["kind"] == "none"
    denied = await rig.client.patch(
        f"/api/v1/folders/{CW}", headers=rig.headers["agent"], json={"supplier_name": "Changed"}
    )
    assert denied.status_code == 403
    updated = await rig.client.patch(
        f"/api/v1/folders/{CW}",
        headers=rig.headers["admin"],
        json={"supplier_name": "Hilton YUL", "supplier_type": "transportation"},
    )
    assert updated.status_code == 200
    assert (await rig.get("/search", q="etoile")).json()["kind"] == "none"
    result = (await rig.get("/search", q="hilton yul")).json()
    assert result["items"][0]["supplier_type"] == "transportation"
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(
            select(AuditLog.id).where(AuditLog.action == "folder_updated")
        )


@pytest.mark.parametrize("ready", [True, False])
async def test_supplier_ranking_exact_then_starts_then_words_then_activity(rig, ready):
    await seed_folder(rig, name="Double Tree", periods=("2608",))
    await seed_folder(rig, cw="CW2154928", name="Double Tree Hotel", periods=("2608",))
    await seed_folder(rig, cw="CW2154929", name="YUL Double Tree", periods=("2608",))
    rig.app.state.key_index.ready = ready
    result = (await rig.get("/search", q="double tree")).json()
    assert [r["cw_number"] for r in result["items"]] == [CW, "CW2154928", "CW2154929"]
    # Folder list keeps activity ordering instead of search's relevance ordering.
    listed = (await rig.get("/folders", q="double tree")).json()
    assert [r["cw_number"] for r in listed["items"]] == ["CW2154929", "CW2154928", CW]


async def test_folder_prefix_page_limit_and_filters(rig):
    for i in range(22):
        await seed_folder(
            rig,
            cw=f"CW{2154900 + i}",
            supplier_type="hotel" if i % 2 else "transportation",
            periods=("2608",),
        )
    first = (await rig.get("/search", q="CW2154")).json()
    second = (await rig.get("/search", q="CW2154", page=2)).json()
    assert first["kind"] == "folders" and len(first["items"]) == 20 and first["total"] == 22
    assert len(second["items"]) == 2
    assert {r["cw_number"] for r in first["items"]}.isdisjoint(
        {r["cw_number"] for r in second["items"]}
    )
    filtered = (await rig.get("/folders", station_code="yul", supplier_type="hotel", size=3)).json()
    assert filtered["total"] == 11 and len(filtered["items"]) == 3
    assert (await rig.get("/folders", q="CW2154")).json()["total"] == 22
    assert (await rig.get("/folders/CW9999999")).status_code == 404
    assert (await rig.get("/folders/invalid")).status_code == 422


async def test_station_etag_ttl_rename_counts_and_auth(rig):
    await seed_folder(rig)
    response = await rig.get("/stations")
    assert response.status_code == 200 and response.json() == [
        {"code": "YUL", "name": None, "folder_count": 1}
    ]
    etag = response.headers["etag"]
    cached = await rig.client.get(
        "/api/v1/stations", headers={**rig.headers["agent"], "If-None-Match": "W/" + etag}
    )
    assert cached.status_code == 304 and cached.content == b""
    assert response.headers["cache-control"] == "private, max-age=60"
    assert (
        await rig.client.get("/api/v1/stations", headers={"If-None-Match": etag})
    ).status_code == 401
    renamed = await rig.client.patch(
        "/api/v1/admin/stations/YUL", headers=rig.headers["admin"], json={"name": "Montréal"}
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Montréal"
    next_response = await rig.get("/stations", q="montreal")
    assert next_response.headers["etag"] != etag and next_response.json()[0]["name"] == "Montréal"
    assert (await rig.get("/search", q="YUL")).json()["station"]["name"] == "Montréal"
    await seed_folder(rig, cw="CW2154999", periods=("2608",))
    assert (await rig.get("/stations", q="yu")).json()[0]["folder_count"] == 2
    # Read-through cache really expires after 60 s, even for out-of-band station edits.
    cache = rig.app.state.stations
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            update(Station).where(Station.code == "YUL").values(name="New name")
        )
    assert (await rig.get("/stations")).json()[0]["name"] == "Montréal"
    original = cache.clock
    cache.clock = lambda: original() + 61
    assert (await rig.get("/stations")).json()[0]["name"] == "New name"
    denied = await rig.client.patch(
        "/api/v1/admin/stations/YUL", headers=rig.headers["agent"], json={"name": "Denied"}
    )
    assert denied.status_code == 403
    assert (
        await rig.client.patch(
            "/api/v1/admin/stations/ZZZ", headers=rig.headers["admin"], json={"name": "Unknown"}
        )
    ).status_code == 404
    async with rig.app.state.engine.connect() as connection:
        assert await connection.scalar(
            select(AuditLog.id).where(AuditLog.action == "station_updated")
        )


@pytest.mark.parametrize("ready", [True, False])
async def test_key_shaped_search_never_uses_like(rig, ready):
    await seed_folder(rig)
    rig.app.state.key_index.ready = ready
    statements = []

    def track(*args):
        statements.append(args[2].lower())

    event.listen(rig.app.state.engine.sync_engine, "before_cursor_execute", track)
    try:
        for query in (KEY, "CW2154927-2608", "YUL-2608", "YUL-2613", "CW2154927-YUL-2613"):
            assert (await rig.get("/search", q=query)).status_code == 200
    finally:
        event.remove(rig.app.state.engine.sync_engine, "before_cursor_execute", track)
    assert not any(" like " in s for s in statements)


async def test_folder_aggregation_is_one_query_for_whole_page(rig):
    for i in range(3):
        await seed_folder(rig, cw=f"CW{2154900 + i}")
    statements = []

    def track(*args):
        statements.append(args[2].lower())

    event.listen(rig.app.state.engine.sync_engine, "before_cursor_execute", track)
    try:
        response = await rig.get("/search", q="double tree")
        assert response.status_code == 200 and response.json()["total"] == 3
    finally:
        event.remove(rig.app.state.engine.sync_engine, "before_cursor_execute", track)
    queries = [s for s in statements if s.startswith("select ")]
    assert len(queries) == 1 and "group by bookings.group_id" in queries[0]
    assert "booking_notes" not in queries[0]


async def test_folder_stale_count_matches_month_flags_and_status_thresholds(rig):
    await seed_folder(rig)
    await rig.save(key=KEY, version=1, status_code="DONE", invoices={"no_invoice": True})
    now = datetime.now(UTC)
    async with rig.app.state.engine.begin() as connection:
        for period, hours in [("2609", 25), ("2607", 2), ("2608", 100)]:
            await connection.execute(
                update(Booking)
                .where(Booking.booking_key == f"{CW}-YUL-{period}")
                .values(updated_at=now - timedelta(hours=hours))
            )
    result = (await rig.get(f"/folders/{CW}")).json()
    assert result["folder"]["stale_count"] == 1
    assert sum(m["is_stale"] for m in result["months"]) == 1
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            update(Status).where(Status.code == "BUNDLE").values(stale_after_hours=1)
        )
    result = (await rig.get("/search", q=CW)).json()
    assert result["folder"]["stale_count"] == 2
    assert result["folder"]["open_count"] == 2
    assert sum(m["is_stale"] for m in result["months"]) == 2
    assert (await rig.get("/folders")).json()["items"][0]["stale_count"] == 2


async def test_length_rate_limit_and_fallback_timeout(rig, monkeypatch):
    assert (await rig.get("/search", q="x" * 101)).status_code == 422
    assert (await rig.get("/search", q=" ")).json()["kind"] == "none"
    assert (await rig.get("/search", q="CW", size=21)).status_code == 422
    limiter = rig.app.state.search_limiter
    limiter.entries.clear()
    limiter.limit = 1
    assert (await rig.get("/search", q="missing")).status_code == 200
    response = await rig.get("/search", q="missing")
    assert (
        response.status_code == 429
        and response.json()["code"] == "RATE_LIMITED"
        and int(response.headers["retry-after"]) > 0
    )
    assert (await rig.get("/search", user="other", q="missing")).status_code == 200
    limiter.limit = 120
    rig.app.state.settings.search_db_timeout_seconds = 0.05

    async def slow_resolve(*args):
        await asyncio.sleep(0.2)

    monkeypatch.setattr(rig.app.state.bookings, "resolve", slow_resolve)
    response = await rig.get("/search", q=KEY)
    assert response.status_code == 504 and response.json()["code"] == "REQUEST_TIMEOUT"


async def test_cold_and_disabled_index_supplier_fallback(rig):
    await seed_folder(rig, name="Hôtel Étoile YUL")
    rig.app.state.settings.key_index_enabled = False
    result = (await rig.get("/search", q="eto hot")).json()
    assert result["kind"] == "folders" and result["total"] == 1
    assert (await rig.get("/search", q="CW2154927-2608")).json()["resolution"][
        "status"
    ] == "resolved_from_partial"
    assert (await rig.get("/stations")).json()[0]["folder_count"] == 1


async def test_station_exists_without_folders_and_unknown_code_remains_supplier_text(rig):
    await seed_folder(rig, name="ABC Hotel", periods=("2608",))
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(Station.__table__.insert().values(code="RDU", name="Raleigh"))
    rig.app.state.stations.invalidate()
    station = (await rig.get("/search", q="RDU")).json()
    assert station["kind"] == "station" and station["total"] == 0
    assert station["sections"] == [
        {"type": "hotel", "items": []},
        {"type": "transportation", "items": []},
        {"type": "unclassified", "items": []},
    ]
    assert (await rig.get("/search", q="ABC")).json()["items"][0]["cw_number"] == CW
    assert (await rig.get("/folders", q=CW + "-YUL")).json()["total"] == 1
    assert (await rig.get("/folders", q=CW + "-RDU")).json()["total"] == 0
