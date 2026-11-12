"""Folder follows cover current/future months without changing explicit booking follows."""

import asyncio
from datetime import UTC, datetime

import test_booking_database as support
from sqlalchemy import func, select, update

from app.models import BookingGroup, FolderFollower

migrated, password_pair, rig = support.migrated, support.password_pair, support.rig
pytestmark = support.pytestmark
KEY = support.KEY
FOLDER = KEY[:-5]


async def follow(rig, method="PUT", actor="admin", key=FOLDER):
    return await rig.client.request(
        method, f"/api/v1/folders/{key}/follow", headers=rig.headers[actor]
    )


async def test_follow_current_and_future_months_deduplicates_and_keeps_booking_follows(rig):
    assert (await rig.save()).status_code == 200
    assert (await follow(rig)).json() == {"following": True}
    assert (await follow(rig, "GET")).json() == {"following": True}
    assert (await follow(rig, "GET", "agent")).json() == {"following": False}
    assert (await rig.get("/following/folders", user="admin")).json()["total"] == 1
    assert (await rig.get("/following/folders")).json()["total"] == 0
    assert (
        await rig.client.put(f"/api/v1/bookings/{KEY}/watch", headers=rig.headers["admin"])
    ).status_code == 200
    assert (await rig.save(user="other", version=1)).status_code == 200
    notices = (await rig.get("/notifications", user="admin")).json()["items"]
    assert (
        len(notices) == 1
        and notices[0]["type"] == "watch_update"
        and notices[0]["merged_count"] == 1
    )
    assert (await rig.save(user="other", version=2, note="Another update")).status_code == 200
    notices = (await rig.get("/notifications", user="admin")).json()["items"]
    assert len(notices) == 1 and notices[0]["merged_count"] == 2
    month_key = KEY.replace("2609", "2610")
    assert (await rig.save(key=month_key, note="Future month")).status_code == 200
    notices = (await rig.get("/notifications", user="admin")).json()["items"]
    assert {n["booking_key"] for n in notices} == {KEY, month_key}
    assert not (await rig.get("/bookings/lookup", key=month_key, user="admin")).json()["snapshot"][
        "my_watching"
    ]
    listing = (await rig.get("/following/folders", user="admin")).json()
    assert listing["total"] == 1 and listing["items"][0]["booking_count"] == 2
    # A different station with the same CW is a different folder.
    assert (await rig.save(key=KEY.replace("RDU", "YUL"))).status_code == 200
    assert len((await rig.get("/notifications", user="admin")).json()["items"]) == 2
    assert (await follow(rig, "DELETE")).json() == {"following": False}
    assert (await rig.get("/following/folders", user="admin")).json()["total"] == 0
    assert (await rig.get("/watching", user="admin")).json()["total"] == 1
    assert (await rig.save(key=month_key, version=1, user="other")).status_code == 200
    assert len((await rig.get("/notifications", user="admin")).json()["items"]) == 2
    assert (
        await rig.save(version=3, user="other", note="Still explicitly followed")
    ).status_code == 200
    notices = (await rig.get("/notifications", user="admin")).json()["items"]
    assert next(n for n in notices if n["booking_key"] == KEY)["merged_count"] == 3


async def test_folder_follow_monthly_generation_self_suppression_and_takeover(rig):
    await rig.save()
    assert (await follow(rig, actor="agent")).status_code == 200
    assert (await rig.save(version=1, note="Own follow")).status_code == 200
    assert (await rig.get("/notifications")).json()["items"] == []
    assert (await rig.save(version=2, user="other")).status_code == 200
    assert [n["type"] for n in (await rig.get("/notifications")).json()["items"]] == ["taken_over"]
    await rig.app.state.monthly_bookings.run(datetime(2026, 11, 25, tzinfo=UTC))
    future = KEY.replace("2609", "2611")
    assert (await rig.save(key=future, version=1, user="other")).status_code == 200
    notices = (await rig.get("/notifications")).json()["items"]
    assert any(n["booking_key"] == future and n["type"] == "watch_update" for n in notices)
    assert (await rig.get("/following/folders")).json()["items"][0]["booking_count"] == 3


async def test_follow_auth_private_idempotency_concurrent_and_deleted_folder(rig):
    await rig.save()
    assert (await rig.client.put(f"/api/v1/folders/{FOLDER}/follow")).status_code == 401
    assert (await follow(rig, key="invalid")).status_code == 422
    assert (await follow(rig, key="CW9999999-RDU")).status_code == 404
    responses = await asyncio.gather(*(follow(rig) for _ in range(3)))
    assert all(r.status_code == 200 for r in responses)
    assert (await rig.get("/following/folders", user="admin", page=1, size=1)).json()["total"] == 1
    assert (await rig.get("/following/folders", user="other")).json()["total"] == 0
    async with rig.app.state.engine.begin() as conn:
        assert await conn.scalar(select(func.count()).select_from(FolderFollower)) == 1
        await conn.execute(update(BookingGroup).values(deleted_at=datetime.now(UTC)))
    assert (await rig.get("/following/folders", user="admin")).json()["total"] == 0
    assert (await follow(rig, "GET")).status_code == 404


async def test_folder_follow_limits_and_idempotent_follow_at_limit(rig):
    await rig.save()
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            BookingGroup.__table__.insert(),
            [
                {
                    "id": i,
                    "cw_number": f"CW{i:07}",
                    "station_code": "RDU",
                    "supplier_name": f"Follow Supplier {i}",
                    "supplier_name_normalized": f"follow supplier {i}",
                    "supplier_type": "hotel",
                    "created_by": 1,
                }
                for i in range(10000, 10200)
            ],
        )
        await conn.execute(
            FolderFollower.__table__.insert(),
            [{"group_id": i, "user_id": 1} for i in range(10000, 10200)],
        )
    assert (await follow(rig)).json()["code"] == "WATCH_LIMIT_REACHED"
    assert (await follow(rig, key="CW0010000-RDU")).json() == {"following": True}
    assert (await follow(rig, "DELETE", key="CW0010000-RDU")).status_code == 200
    assert (await follow(rig)).status_code == 200
    assert (await follow(rig, "DELETE")).status_code == 200
    assert (await follow(rig, "DELETE")).status_code == 200
