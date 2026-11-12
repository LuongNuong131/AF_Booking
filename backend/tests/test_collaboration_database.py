"""Collaboration transactions on real verified-TLS MySQL/TiDB."""

import asyncio

import test_booking_database as support
import test_realtime_database as realtime_support
from sqlalchemy import event, func, select, update

from app.models import Booking, BookingAssignment, BookingWatcher, Notification, User

migrated, password_pair, rig = support.migrated, support.password_pair, support.rig

live = realtime_support.live
pytestmark = support.pytestmark
KEY = support.KEY


async def mutation(rig, method, path, user="agent", body=None):
    return await rig.client.request(method, "/api/v1" + path, headers=rig.headers[user], json=body)


async def test_watch_merge_one_query_batch_and_takeover_dedup(rig):
    assert (await rig.save()).status_code == 200
    assert (await mutation(rig, "PUT", f"/bookings/{KEY}/watch")).json() == {"watching": True}
    assert (await mutation(rig, "PUT", f"/bookings/{KEY}/watch", "admin")).status_code == 200
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lower())

    event.listen(rig.app.state.engine.sync_engine, "before_cursor_execute", capture)
    try:
        for version in range(1, 4):
            assert (await rig.save(user="other", version=version)).status_code == 200
    finally:
        event.remove(rig.app.state.engine.sync_engine, "before_cursor_execute", capture)
    # The previous agent gets one takeover, not takeover + watch for the same note.
    agent = (await rig.get("/notifications")).json()["items"]
    assert [n["type"] for n in agent].count("taken_over") == 1
    assert [n["type"] for n in agent].count("watch_update") == 1
    admin = (await rig.get("/notifications", user="admin")).json()["items"]
    assert len(admin) == 1 and admin[0]["merged_count"] == 3
    assert sum(s.startswith("insert into notifications") for s in statements) == 3
    assert (
        sum(
            "from booking_watchers" in s and "union" in s and s.startswith("select")
            for s in statements
        )
        == 3
    )
    # Reading frees the unique unread slot; next update creates a new row.
    await mutation(rig, "POST", f"/notifications/{admin[0]['id']}/read", "admin")
    await rig.save(user="other", version=4)
    admin = (await rig.get("/notifications", user="admin")).json()["items"]
    assert len(admin) == 2 and admin[0]["merged_count"] == 1
    watched = (await rig.get("/watching")).json()
    assert watched["total"] == 1 and watched["items"][0]["my_watching"] is True
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]["my_watching"]
    assert (await rig.get("/bookings/lookup", user="other", key=KEY)).json()["snapshot"][
        "my_watching"
    ] is False
    await mutation(rig, "DELETE", f"/bookings/{KEY}/watch")
    assert (await rig.get("/watching")).json()["total"] == 0


async def test_assign_note_atomic_auto_complete_uuid_and_access(rig):
    first = await rig.save(assign_to=5, assign_message="Please check supplier")
    assert first.status_code == 200, first.text
    assignment = (await rig.get("/assignments", user="other")).json()["items"][0]
    assert assignment["from_user"]["id"] == 3 and assignment["to_user"]["id"] == 5
    assert (
        await mutation(rig, "POST", f"/assignments/{assignment['id']}/complete", "admin")
    ).status_code == 404
    duplicate = await rig.save(version=1, assign_to=5)
    assert duplicate.status_code == 422 and duplicate.json()["code"] == "ASSIGNMENT_INVALID"
    assert (await rig.get("/bookings/lookup", key=KEY)).json()["version"] == 1
    assert (await rig.save(user="other", version=1)).status_code == 200
    done = (await rig.get("/assignments", status="done", view="from_me")).json()
    assert done["total"] == 1 and done["items"][0]["resolved_at"]
    types = [n["type"] for n in (await rig.get("/notifications")).json()["items"]]
    assert types.count("assignment_done") == 1
    await mutation(rig, "POST", f"/assignments/{assignment['id']}/complete", "other")
    assert [n["type"] for n in (await rig.get("/notifications")).json()["items"]].count(
        "assignment_done"
    ) == 1


async def test_invalid_recipient_and_decline_reason(rig):
    assert (await rig.save(assign_to=3)).json()["code"] == "ASSIGNMENT_INVALID"
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(update(User).where(User.id == 5).values(is_active=False))
    assert (await rig.save(assign_to=5)).json()["code"] == "ASSIGNMENT_INVALID"
    assert (await rig.save(assign_to=99999)).json()["code"] == "ASSIGNMENT_INVALID"
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(update(User).where(User.id == 5).values(is_active=True))
    assert (await rig.save(assign_to=5)).status_code == 200
    row = (await rig.get("/assignments", user="other")).json()["items"][0]
    path = f"/assignments/{row['id']}/decline"
    assert (await mutation(rig, "POST", path, "other", {"reason": " "})).status_code == 422
    result = await mutation(rig, "POST", path, "other", {"reason": "Cannot handle today"})
    assert (
        result.json()["status"] == "declined"
        and result.json()["decline_reason"] == "Cannot handle today"
    )
    assert (await rig.save(version=1, assign_to=5)).status_code == 200


async def test_auto_watch_and_cap_under_concurrency(rig):
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(
            update(User).where(User.id == 3).values(settings={"auto_watch_on_note": True})
        )
    assert (await rig.save()).status_code == 200
    async with rig.app.state.engine.begin() as conn:
        book = (await conn.execute(select(Booking))).first()
        # Fill 199 further synthetic subscriptions; no FK schema by design.
        await conn.execute(
            BookingWatcher.__table__.insert(),
            [{"booking_id": book.id + 1000 + i, "user_id": 3} for i in range(199)],
        )
    # Existing watch is idempotent at limit; auto-watch never blocks a note.
    assert (await mutation(rig, "PUT", f"/bookings/{KEY}/watch")).status_code == 200
    assert (await rig.save(version=1)).status_code == 200
    key2 = "CW9954321-YUL-2610"
    assert (await rig.save(key=key2, user="other")).status_code == 200
    results = await asyncio.gather(
        *[mutation(rig, "PUT", f"/bookings/{key2}/watch") for _ in range(2)]
    )
    assert all(r.status_code == 422 and r.json()["code"] == "WATCH_LIMIT_REACHED" for r in results)
    async with rig.app.state.engine.connect() as conn:
        assert (
            await conn.scalar(
                select(func.count()).select_from(BookingWatcher).where(BookingWatcher.user_id == 3)
            )
            == 200
        )


async def test_user_directory_cache_and_rate_limit(rig):
    assert (await rig.get("/users/lookup", q="Agent")).json() == [{"id": 3, "full_name": "Agent"}]
    assert (await rig.get("/users/lookup", q="Agent")).status_code == 200
    assert rig.app.state.collaboration.directory
    rig.app.state.collaboration.limiter.limit = 2
    assert (await rig.get("/users/lookup")).status_code == 429


async def test_profile_auto_watch_and_manual_completion(rig):
    profile = await mutation(
        rig, "PATCH", "/profile", body={"settings": {"auto_watch_on_note": True}}
    )
    assert profile.status_code == 200 and profile.json()["settings"]["auto_watch_on_note"] is True
    saved = await rig.save(assign_to=5)
    assert saved.status_code == 200 and saved.json()["my_watching"] is True
    assert (await rig.get("/watching")).json()["total"] == 1
    item = (await rig.get("/assignments", user="other")).json()["items"][0]
    result = await mutation(rig, "POST", f"/assignments/{item['id']}/complete", "other")
    assert result.status_code == 200 and result.json()["status"] == "done"
    assert (await rig.get("/assignments", user="other")).json()["total"] == 0
    assert (await rig.get("/assignments", view="from_me", status="done")).json()["total"] == 1
    invalid = await rig.save(version=1, assign_to=5, assign_message="x" * 256)
    assert invalid.status_code == 422


async def test_private_websocket_merge_and_assignment_delivery(rig, live):
    from test_realtime_database import event as receive
    from test_realtime_database import peer

    await rig.save()
    await mutation(rig, "PUT", f"/bookings/{KEY}/watch", "admin")
    async with peer(live, rig, "admin") as admin, peer(live, rig, "other") as other:
        await receive(admin, "lock.snapshot")
        await receive(other, "lock.snapshot")
        ids = []
        for version in range(1, 4):
            result = await rig.save(version=version, assign_to=5 if version == 3 else None)
            assert result.status_code == 200, result.text
            frame = await receive(admin, "notification.new")
            assert frame["type"] == "watch_update" and frame["merged_count"] == version
            ids.append(frame["id"])
        assert len(set(ids)) == 1
        assigned = await receive(other, "notification.new")
        assert assigned["type"] == "assigned"
        await rig.save(user="other", version=4)
        # The assigner's durable notification is also emitted privately; the
        # Admin watcher must receive watch_update rather than assignment_done.
        frame = await receive(admin, "notification.new")
        assert frame["type"] == "watch_update" and frame["merged_count"] == 4
        completed = (await rig.get("/notifications")).json()["items"]
        assert any(n["type"] == "assignment_done" for n in completed)


async def test_uuid_replay_does_not_duplicate_assignment_or_notifications(rig):
    from uuid import uuid4

    identifier = str(uuid4())
    first = await rig.save(assign_to=5, client_request_id=identifier)
    second = await rig.save(assign_to=5, client_request_id=identifier)
    assert first.json() == second.json() and second.status_code == 200
    async with rig.app.state.engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(BookingAssignment)) == 1
        assert await conn.scalar(select(func.count()).select_from(Notification)) == 1
