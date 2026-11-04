"""Invoice set operations, ownership, clock preservation, reconciliation and real indexes."""

import asyncio
import csv
import io
from uuid import uuid4

import test_booking_database as support
from openpyxl import load_workbook
from sqlalchemy import func, select, text, update

from app.models import AuditLog, Booking, BookingInvoice, BookingNote, Notification, User
from app.services.integrity import batch_query, derive, difference

migrated, password_pair, rig = support.migrated, support.password_pair, support.rig
pytestmark = support.pytestmark
KEY = support.KEY


async def put(rig, body, key=KEY, user="agent"):
    return await rig.client.put(
        "/api/v1/bookings/" + key + "/invoices", json=body, headers=rig.headers[user]
    )


async def test_note_atomic_declaration_invalid_required_and_replay(rig):
    assert (await rig.save(status_code="DONE")).json()["code"] == "INVOICE_REQUIRED"
    response = await rig.save(status_code="DONE", invoices={"add": [" inv-001 ", "INV002"]})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert (
        payload["snapshot"]["invoice_count"] == 2
        and payload["snapshot"]["invoice_state"] == "has_invoice"
        and payload["snapshot"]["version"] == 1
    )
    assert payload["note"]["invoice_change"]["added"] == ["INV-001", "INV002"]
    assert len(payload["invoices"]) == 2 and all(row["id"] > 0 for row in payload["invoices"])
    old = await rig.get("/bookings/lookup", key=KEY)
    assert len(old.json()["invoices"]) == 2
    invalid = await rig.save(
        version=1, status_code="DONE", invoices={"add": ["INV003", "bad@value"]}
    )
    assert invalid.json()["code"] == "INVOICE_INVALID"
    async with rig.app.state.engine.connect() as c:
        assert await c.scalar(select(func.count()).select_from(BookingNote)) == 1
        assert await c.scalar(select(func.count()).select_from(BookingInvoice)) == 2
    again = await put(rig, {"add": ["inv002"]})
    assert again.json()["skipped_duplicates"] == ["INV002"]


async def test_remove_then_add_then_no_invoice_and_permissions(rig):
    await rig.save(invoices={"add": ["INV100"]})
    item = (await rig.get("/bookings/" + KEY + "/invoices")).json()["items"][0]
    forbidden = await put(rig, {"remove_ids": [item["id"]]}, user="other")
    assert forbidden.status_code == 403
    conflict = await put(rig, {"no_invoice": True})
    assert conflict.json()["code"] == "INVOICE_STATE_CONFLICT"
    removed = await put(rig, {"remove_ids": [item["id"], 999999], "no_invoice": True}, user="admin")
    assert removed.status_code == 200, removed.text
    assert removed.json()["snapshot"]["invoice_state"] == "no_invoice"
    assert (await put(rig, {"add": ["INV200"]})).json()["snapshot"][
        "invoice_state"
    ] == "has_invoice"
    current = (await rig.get("/bookings/" + KEY + "/invoices")).json()["items"][0]
    assert (await put(rig, {"remove_ids": [current["id"]]})).json()["snapshot"][
        "invoice_state"
    ] == "unknown"
    assert (await put(rig, {"no_invoice": True})).json()["snapshot"][
        "invoice_state"
    ] == "no_invoice"
    assert (await put(rig, {"no_invoice": False})).json()["snapshot"]["invoice_state"] == "unknown"
    async with rig.app.state.engine.connect() as c:
        actions = (
            await c.scalars(select(AuditLog.action).where(AuditLog.action.like("invoice.%")))
        ).all()
    assert set(actions) == {
        "invoice.add",
        "invoice.remove",
        "invoice.no_invoice_set",
        "invoice.no_invoice_clear",
    }


async def test_standalone_concurrency_clock_no_notification_and_inactive_session(rig):
    await rig.save()
    before = (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]
    a, b = await asyncio.gather(
        put(rig, {"add": ["INV301"]}), put(rig, {"add": ["INV302"]}, user="other")
    )
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    after = (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]
    for field in (
        "last_agent",
        "last_status",
        "last_position",
        "last_note_preview",
        "is_done",
        "done_at",
        "updated_at",
        "is_stale",
    ):
        assert before[field] == after[field], field
    assert after["invoice_count"] == 2 and after["version"] == before["version"] + 2
    async with rig.app.state.engine.connect() as c:
        assert await c.scalar(select(func.count()).select_from(Notification)) == 0
        assert await c.scalar(select(func.count()).select_from(BookingNote)) == 1
    async with rig.app.state.engine.begin() as c:
        await c.execute(update(User).where(User.id == 3).values(current_session_id=str(uuid4())))
    assert (await put(rig, {"add": ["INV303"]})).json()["code"] == "SESSION_REPLACED"


async def test_limit_warnings_search_filter_and_page_preview_budget(rig):
    await rig.save(invoices={"add": ["INV400"]})
    other = "CW7654321-YUL-2609"
    created = await rig.save(key=other, invoices={"add": ["inv400"]})
    assert created.json()["warnings"] == [{"invoice_number": "INV400", "booking_keys": [KEY]}]
    assert (await put(rig, {"add": [f"INV{i:03}" for i in range(20)]})).json()[
        "code"
    ] == "INVOICE_LIMIT_REACHED"
    assert (await put(rig, {"add": ["X"] * 51})).status_code == 422
    for query in ("INV:inv400", "#inv400", "INV400"):
        found = await rig.get("/search", q=query)
        assert found.status_code == 200, found.text
        assert found.json()["kind"] == "invoice" and found.json()["total"] == 2
        assert all(item["matched_invoice"] == "INV400" for item in found.json()["items"])
    filtered = await rig.get("/bookings", invoice="inv400", invoice_state="has_invoice")
    assert filtered.json()["total"] == 2
    await rig.save(key="CW8765432-YUL-2609", status_code="DONE", invoices={"no_invoice": True})
    async with rig.app.state.engine.begin() as c:
        await c.execute(
            update(Booking)
            .where(Booking.booking_key == "CW8765432-YUL-2609")
            .values(invoice_state="unknown")
        )
    filtered = await rig.get("/bookings", invoice_state="unknown", is_done=True)
    assert filtered.json()["total"] == 1


async def test_report_export_rows_formula_safe_and_integrity_repair(rig):
    await rig.save(invoices={"add": ["INV501", "INV502"]}, supplier_name="=1+1")
    await rig.save(key="CW2222222-YUL-2609", invoices={"no_invoice": True})
    await rig.save(key="CW3333333-YUL-2609")
    report = await rig.get("/reports/invoices", user="admin", period="2609")
    assert report.status_code == 200, report.text
    value = report.json()
    assert (
        value["bookings"],
        value["with_invoice"],
        value["no_invoice"],
        value["not_declared"],
        value["invoice_total"],
        value["multi_invoice_bookings"],
    ) == (3, 1, 1, 1, 2, 1)
    assert (await rig.get("/reports/invoices", period="2609")).status_code == 403
    export = await rig.get("/export/invoices", user="admin", period="2609", format="xlsx")
    assert export.status_code == 200, export.text
    book = load_workbook(io.BytesIO(export.content), read_only=True)
    assert book.sheetnames == ["Invoices", "Bookings"]
    invoices = list(book["Invoices"].values)
    bookings = list(book["Bookings"].values)
    assert (
        len(invoices) == 5
        and len(bookings) == 4
        and all(r[1].startswith("CW ") for r in invoices[1:])
    )
    assert any(r[2] == "'=1+1" for r in invoices[1:])
    book.close()
    csvfile = await rig.get("/export/invoices", user="admin", period="2609", format="csv")
    assert len(list(csv.reader(io.StringIO(csvfile.content.decode("utf-8-sig"))))) == 5
    async with rig.app.state.engine.begin() as c:
        await c.execute(
            update(Booking)
            .where(Booking.booking_key == KEY)
            .values(invoice_count=19, invoice_state="unknown")
        )
    async with rig.app.state.engine.connect() as c:
        rows = (await c.execute(batch_query(0, 999999))).all()
        row = next(r for r in rows if r.booking_key == KEY)
        assert difference(row, derive(row))["invoice_count"]["expected"] == 2
    run = await rig.client.post("/api/v1/admin/integrity/run", headers=rig.headers["admin"])
    assert run.status_code == 202
    await rig.app.state.integrity.task
    history = (await rig.get("/admin/integrity", user="admin")).json()
    run_id = history["items"][0]["id"]
    fix = await rig.client.post(
        "/api/v1/admin/integrity/fix", headers=rig.headers["admin"], json={"run_id": run_id}
    )
    assert fix.status_code == 202, fix.text
    await rig.app.state.integrity.task
    fixed = (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]
    assert fixed["invoice_count"] == 2 and fixed["invoice_state"] == "has_invoice"
    async with rig.app.state.engine.connect() as c:
        queries = [
            ("booking invoices", "SELECT * FROM booking_invoices WHERE booking_id=1 ORDER BY id"),
            (
                "invoice lookup",
                "SELECT booking_id FROM booking_invoices WHERE invoice_number_normalized='INV501'",
            ),
            (
                "period state",
                "SELECT invoice_state,COUNT(*) FROM bookings "
                "WHERE period='2609' GROUP BY invoice_state",
            ),
            (
                "Done undeclared",
                "SELECT id FROM bookings WHERE invoice_state='unknown' "
                "AND is_done=1 ORDER BY updated_at",
            ),
        ]
        plans = {}
        for label, sql in queries:
            plan = (await c.execute(text("EXPLAIN " + sql))).mappings().all()
            assert plan, label
            plans[label] = {"sql": sql, "plan": [dict(row) for row in plan]}
        import json
        import os
        from pathlib import Path

        output = os.environ.get("SCHEMA_TEST_REPORT")
        if output:
            Path(output).with_suffix(".plans.json").write_text(
                json.dumps(plans, indent=2, default=str) + "\n"
            )


async def test_daily_invoice_columns_and_done_not_declared(rig):
    from app.services.exports import invoice_numbers_query

    await rig.save(status_code="DONE", invoices={"add": ["DAILY001", "DAILY002"]})
    async with rig.app.state.engine.connect() as conn:
        row = (await conn.execute(select(Booking.id, invoice_numbers_query()))).one()
        assert "DAILY001" in str(row.invoice_numbers)
    async with rig.app.state.engine.begin() as conn:
        await conn.execute(update(Booking).values(invoice_state="unknown"))
    report = await rig.get("/reports/daily", user="admin")
    assert report.status_code == 200, report.text
    assert len(report.json()["done_not_declared"]) == 1
    day = report.json()["report_date"]
    file = await rig.get("/export/daily", user="admin", date=day, format="csv")
    rows = list(csv.reader(io.StringIO(file.content.decode("utf-8-sig"))))
    assert rows[0][-2:] == ["Invoice State", "Invoice Numbers"]
    assert rows[1][-2] == "Not declared" and set(rows[1][-1].split("; ")) == {
        "DAILY001",
        "DAILY002",
    }


async def test_note_delete_restore_never_changes_invoice_rows(rig):
    saved = await rig.save(status_code="DONE", invoices={"add": ["KEEP001", "KEEP002"]})
    note_id = saved.json()["note"]["id"]
    before = (await rig.get(f"/bookings/{KEY}/invoices")).json()
    response = await rig.client.request(
        "DELETE",
        f"/api/v1/admin/notes/{note_id}",
        headers=rig.headers["admin"],
        json={"reason": "Check independent invoice ownership"},
    )
    assert response.status_code == 200, response.text
    assert (await rig.get(f"/bookings/{KEY}/invoices")).json() == before
    response = await rig.client.post(
        f"/api/v1/admin/notes/{note_id}/restore", headers=rig.headers["admin"]
    )
    assert response.status_code == 200, response.text
    assert (await rig.get(f"/bookings/{KEY}/invoices")).json() == before


async def test_twenty_row_preview_and_report_query_budgets(rig):
    from sqlalchemy import event

    for n in range(20):
        response = await rig.save(
            key=f"CW{4000000 + n}-YUL-2609", invoices={"add": [f"BATCH{n:03}"]}
        )
        assert response.status_code == 200, response.text
    sql = []

    def capture(conn, cursor, statement, parameters, context, many):
        sql.append(statement.lower())

    event.listen(rig.app.state.engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await rig.get("/bookings", size=20)
        assert response.json()["total"] == 20 and all(
            row["invoices_preview"] for row in response.json()["items"]
        )
        assert sum("from booking_invoices" in statement for statement in sql) == 1
        sql.clear()
        response = await rig.get("/reports/invoices", user="admin", period="2609")
        assert response.json()["bookings"] == 20 and response.json()["invoice_total"] == 20
        reads = [statement for statement in sql if "from bookings" in statement]
        assert len(reads) == 1 and "join" not in reads[0] and "booking_invoices" not in reads[0]
    finally:
        event.remove(rig.app.state.engine.sync_engine, "before_cursor_execute", capture)


async def test_invoice_only_event_has_new_snapshot_without_note_or_notification(rig):
    await rig.save()
    before = (await rig.get("/bookings/lookup", key=KEY)).json()["snapshot"]
    events = []

    async def broadcast(event, payload):
        events.append((event, payload))

    rig.app.state.invoices.ws.broadcast = broadcast
    response = await put(rig, {"add": ["EVENT001"]}, user="other")
    assert response.status_code == 200, response.text
    for _ in range(20):
        if events:
            break
        await asyncio.sleep(0.01)
    assert len(events) == 1 and events[0][0] == "booking.updated"
    payload = events[0][1]
    assert (
        payload["change_kind"] == "invoice"
        and payload["invoice_count"] == 1
        and payload["invoice_state"] == "has_invoice"
    )
    assert (
        payload["last_agent_id"] == before["last_agent"]["id"]
        and payload["updated_at"] == before["updated_at"]
    )
