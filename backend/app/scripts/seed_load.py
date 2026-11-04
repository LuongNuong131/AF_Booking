"""Synthetic performance data. Refuses non-test or populated databases."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text

from app.core.security import PasswordService, validate_password
from app.models import (
    Base,
    Booking,
    BookingGroup,
    BookingInvoice,
    BookingNote,
    Station,
    Status,
    User,
)
from app.scripts.seed import seed_database


def period_at(year, month, offset):
    absolute = year * 12 + month - 1 + offset
    y, m = divmod(absolute, 12)
    return f"{y % 100:02}{m + 1:02}"


async def seed_load(
    engine, *, password, bookings=50000, notes_per_booking=5, users=50, folders=2000, stations=40
):
    name = engine.url.database or ""
    if not (name.startswith(("booking_load_", "booking_schema_")) and name.endswith("_test")):
        raise ValueError("Synthetic seed requires a dedicated booking_load_*_test database.")
    if (
        bookings % folders
        or not 2 <= stations <= 40
        or not 1 <= users <= 100
        or not 1 <= notes_per_booking <= 20
    ):
        raise ValueError("Invalid synthetic dataset dimensions.")
    async with engine.connect() as c:
        for table in Base.metadata.tables.values():
            if table.name not in {"statuses"} and await c.scalar(
                select(func.count()).select_from(table)
            ):
                raise ValueError("Synthetic seed requires empty application tables.")
    validate_password(password, "load.agent.000")
    encoded = await PasswordService().hash(password)
    await seed_database(engine, None)
    now = datetime.now(UTC).replace(microsecond=0)
    names = ["RDU", "YUL"] + [
        "S" + chr(65 + i // 26) + chr(65 + i % 26) for i in range(stations - 2)
    ]
    per_folder = bookings // folders
    async with engine.begin() as c:
        statuses = (
            await c.execute(
                select(Status.id, Status.code, Status.position_label, Status.is_done).order_by(
                    Status.id
                )
            )
        ).all()
        await c.execute(
            User.__table__.insert(),
            [
                {
                    "id": 1001 + i,
                    "username": f"load.agent.{i:03}",
                    "full_name": f"Load Agent {i:03}",
                    "password_hash": encoded,
                    "role": "admin" if i == 0 else ("qc" if i == 1 else "agent"),
                    "is_active": True,
                    "must_change_password": False,
                    "settings": {"timezone": "Asia/Ho_Chi_Minh"},
                }
                for i in range(users)
            ],
        )
        await c.execute(
            Station.__table__.insert(),
            [{"code": name, "name": f"Test station {name}"} for name in names],
        )
        await c.execute(
            BookingGroup.__table__.insert(),
            [
                {
                    "id": i + 1,
                    "cw_number": f"CW{5000000 + i}",
                    "station_code": names[i % stations],
                    "supplier_name": f"Crew Supplier {i:04}",
                    "supplier_name_normalized": f"CREW SUPPLIER {i:04}",
                    "supplier_type": "hotel" if i % 2 == 0 else "transportation",
                    "booking_count": per_folder,
                    "created_by": 1001,
                    "created_at": now,
                    "last_activity_at": now,
                }
                for i in range(folders)
            ],
        )
    all_keys = []
    for start in range(0, bookings, 500):
        book_rows = []
        note_rows = []
        invoice_rows = []
        for i in range(start, min(start + 500, bookings)):
            group = i // per_folder
            period = period_at(now.year, now.month, i % per_folder - per_folder + 1)
            key = f"CW{5000000 + group}-{names[group % stations]}-{period}"
            all_keys.append(key)
            last = statuses[i % len(statuses)]
            agent = 1001 + i % users
            at = now - timedelta(days=i % 180, seconds=i % 86400)
            invoice = i % 4 == 0
            book_rows.append(
                {
                    "id": i + 1,
                    "booking_key": key,
                    "group_id": group + 1,
                    "cw_number": f"CW{5000000 + group}",
                    "station_code": names[group % stations],
                    "period": period,
                    "last_note_id": (i + 1) * notes_per_booking,
                    "last_agent_id": agent,
                    "last_status_id": last.id,
                    "last_position": last.position_label,
                    "last_note_preview": f"Crew supplier update {notes_per_booking}",
                    "version": notes_per_booking,
                    "is_done": bool(last.is_done),
                    "done_at": at if last.is_done else None,
                    "invoice_state": "has_invoice"
                    if invoice
                    else ("no_invoice" if last.is_done else "unknown"),
                    "invoice_count": int(invoice),
                    "created_at": at - timedelta(minutes=notes_per_booking),
                    "updated_at": at,
                }
            )
            for n in range(notes_per_booking):
                status = last if n == notes_per_booking - 1 else statuses[(i + n) % len(statuses)]
                note_rows.append(
                    {
                        "id": i * notes_per_booking + n + 1,
                        "booking_id": i + 1,
                        "agent_id": agent,
                        "status_id": status.id,
                        "position_label": status.position_label,
                        "note": f"Crew supplier update {n + 1}",
                        "created_at": at - timedelta(minutes=notes_per_booking - 1 - n),
                    }
                )
            if invoice:
                invoice_rows.append(
                    {
                        "booking_id": i + 1,
                        "invoice_number": f"INV-{i + 1:07}",
                        "invoice_number_normalized": f"INV-{i + 1:07}",
                        "added_by": agent,
                        "created_at": at,
                    }
                )
        async with engine.begin() as c:
            await c.execute(Booking.__table__.insert(), book_rows)
            await c.execute(BookingNote.__table__.insert(), note_rows)
            if invoice_rows:
                await c.execute(BookingInvoice.__table__.insert(), invoice_rows)
        await asyncio.sleep(0)
    async with engine.begin() as c:
        await c.execute(
            text(
                "ANALYZE TABLE users, stations, booking_groups, "
                "bookings, booking_notes, booking_invoices"
            )
        )
    return {
        "bookings": bookings,
        "notes": bookings * notes_per_booking,
        "users": users,
        "folders": folders,
        "stations": stations,
        "keys": all_keys,
        "initial_version": notes_per_booking,
        "password_hash": encoded,
    }


async def cli(args):
    from app.core.config import Settings
    from app.core.db import create_database_engine

    settings = Settings(
        _env_file=None, app_env="development", db_pool_size=1, db_query_timeout_ms=30000
    )
    engine = create_database_engine(settings)
    if engine is None or not (engine.url.database or "").startswith("booking_load_"):
        raise ValueError("Use a dedicated booking_load_*_test database, migrated to head.")
    try:
        data = await seed_load(
            engine,
            password=os.environ["LOAD_TEST_PASSWORD"],
            bookings=args.bookings,
            notes_per_booking=args.notes,
            users=args.users,
            folders=args.folders,
            stations=args.stations,
        )
        public = {k: v for k, v in data.items() if k != "password_hash"}
        import json

        await asyncio.to_thread(args.manifest.write_text, json.dumps(public) + "\n")
        print(json.dumps({k: v for k, v in public.items() if k != "keys"}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bookings", type=int, default=50000)
    parser.add_argument("--notes", type=int, default=5)
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--folders", type=int, default=2000)
    parser.add_argument("--stations", type=int, default=40)
    try:
        asyncio.run(cli(parser.parse_args()))
    except Exception as error:
        raise SystemExit("Synthetic seed failed (" + type(error).__name__ + ").") from None
