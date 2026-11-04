"""Shared atomic set operations. Caller holds the booking lock; no note ownership changes."""

import time

from sqlalchemy import case, func, select
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, BookingInvoice, User
from app.schemas.bookings import GroupInfo
from app.schemas.contracts import ErrorCode, Invoice
from app.schemas.invoices import InvoiceList, InvoiceReport, InvoiceResult
from app.schemas.realtime import BookingUpdatedData
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.services.booking_reads import invoice_previews, snapshot_from_row, snapshot_query
from app.services.key_index import GroupEntry, KeyEntry
from app.utils.booking_key import ParsedKey, PartialKey, parse, period_label, to_display
from app.utils.invoice import normalize, validate


async def invoice_items(session, booking_id):
    rows = (
        await session.execute(
            select(BookingInvoice, User.full_name)
            .join(User, User.id == BookingInvoice.added_by)
            .where(BookingInvoice.booking_id == booking_id)
            .order_by(BookingInvoice.id.desc())
        )
    ).all()
    return [
        Invoice(
            id=r.BookingInvoice.id,
            invoice_number=r.BookingInvoice.invoice_number,
            added_by={"id": r.BookingInvoice.added_by, "full_name": r.full_name},
            created_at=r.BookingInvoice.created_at,
        )
        for r in rows
    ]


class InvoiceService:
    def __init__(self, engine, settings, index, cache, ws):
        self.engine, self.settings, self.index, self.cache, self.ws = (
            engine,
            settings,
            index,
            cache,
            ws,
        )
        self.report_cache = {}

    async def apply_changes(self, session, booking, user, change, note_id=None, context=None):
        rows = list(
            (
                await session.scalars(
                    select(BookingInvoice)
                    .where(BookingInvoice.booking_id == booking.id)
                    .order_by(BookingInvoice.id)
                )
            ).all()
        )
        values = list(dict.fromkeys(normalize(value) for value in change.add))
        invalid = [
            value for value in values if not validate(value, self.settings.invoice_number_pattern)
        ]
        if invalid:
            raise ApiException(ErrorCode.INVOICE_INVALID, details={"invalid": invalid})
        removed = [row for row in rows if row.id in set(change.remove_ids)]
        if any(row.added_by != user.id for row in removed) and user.role not in {"admin", "qc"}:
            raise ApiException(ErrorCode.FORBIDDEN)
        remaining = [row for row in rows if row not in removed]
        existing = {row.invoice_number_normalized for row in remaining}
        skipped = [value for value in values if value in existing]
        added = [value for value in values if value not in existing]
        count = len(remaining) + len(added)
        if change.no_invoice and count:
            raise ApiException(ErrorCode.INVOICE_STATE_CONFLICT)
        if count > self.settings.invoice_max_per_booking:
            raise ApiException(ErrorCode.INVOICE_LIMIT_REACHED)
        warnings = []
        if added:
            # One indexed query for all new numbers, at most five booking keys per number.
            ranked = (
                select(
                    BookingInvoice.invoice_number_normalized.label("number"),
                    Booking.booking_key,
                    func.row_number()
                    .over(
                        partition_by=BookingInvoice.invoice_number_normalized,
                        order_by=BookingInvoice.id.desc(),
                    )
                    .label("rank"),
                )
                .join(Booking, Booking.id == BookingInvoice.booking_id)
                .where(
                    BookingInvoice.invoice_number_normalized.in_(added), Booking.id != booking.id
                )
                .subquery()
            )
            for number, key in (
                await session.execute(
                    select(ranked.c.number, ranked.c.booking_key).where(ranked.c.rank <= 5)
                )
            ).all():
                item = next((item for item in warnings if item["invoice_number"] == number), None)
                if item is None:
                    item = {"invoice_number": number, "booking_keys": []}
                    warnings.append(item)
                item["booking_keys"].append(key)
        for row in removed:
            await session.delete(row)
        await session.flush()  # Allow removing/re-adding the same normalized number.
        for value in added:
            session.add(
                BookingInvoice(
                    booking_id=booking.id,
                    invoice_number=value,
                    invoice_number_normalized=value,
                    added_by=user.id,
                )
            )
        before = booking.invoice_state
        booking.invoice_count = count
        booking.invoice_state = (
            "has_invoice" if count else "no_invoice" if change.no_invoice else "unknown"
        )
        declared = (
            True
            if booking.invoice_state == "no_invoice" and before != "no_invoice"
            else False
            if before == "no_invoice" and booking.invoice_state != "no_invoice"
            else None
        )
        for action, items in (
            ("invoice.add", [{"invoice_number": n, "added_by": user.id} for n in added]),
            (
                "invoice.remove",
                [{"invoice_number": r.invoice_number, "added_by": r.added_by} for r in removed],
            ),
        ):
            if items:
                record_audit(
                    session,
                    action,
                    actor_id=user.id,
                    entity_type="booking",
                    entity_id=booking.booking_key,
                    context=context,
                    meta={"items": items, "note_id": note_id},
                )
        if declared is not None:
            record_audit(
                session,
                "invoice.no_invoice_set" if declared else "invoice.no_invoice_clear",
                actor_id=user.id,
                entity_type="booking",
                entity_id=booking.booking_key,
                context=context,
                meta={
                    "invoice_numbers": [r.invoice_number for r in remaining] + added,
                    "added_by": user.id,
                    "note_id": note_id,
                },
            )
        return {
            "added": added,
            "removed": [r.invoice_number for r in removed],
            "no_invoice": declared,
            "skipped_duplicates": skipped,
            "warnings": warnings,
        }

    def canonical(self, raw):
        parsed = parse(raw, self.settings.station_code_pattern)
        if isinstance(parsed, PartialKey):
            raise ApiException(ErrorCode.STATION_REQUIRED)
        if not isinstance(parsed, ParsedKey) or raw != parsed.key:
            raise ApiException(ErrorCode.INVALID_BOOKING_KEY)
        return parsed.key

    async def listing(self, key):
        key = self.canonical(key)
        async with transaction(self.engine, self.settings) as session:
            booking = await session.scalar(select(Booking).where(Booking.booking_key == key))
            if booking is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            return InvoiceList(
                invoice_state=booking.invoice_state,
                items=await invoice_items(session, booking.id),
                number_pattern=self.settings.invoice_number_pattern,
                max_per_booking=self.settings.invoice_max_per_booking,
            )

    async def put(self, key, change, actor, context):
        key = self.canonical(key)
        identifier = None

        def committed():
            self.report_cache.clear()
            self.cache.invalidate(identifier)
            self.index.update(entry, group)
            self.ws.spawn(self.ws.broadcast("booking.updated", event))

        try:
            async with transaction(self.engine, self.settings, after_commit=committed) as session:
                user = AuthService.require_live_row(
                    await session.scalar(select(User).where(User.id == actor.id).with_for_update()),
                    actor,
                )
                gid = await session.scalar(
                    select(Booking.group_id).where(Booking.booking_key == key)
                )
                if gid is None:
                    raise ApiException(ErrorCode.NOT_FOUND)
                folder = await session.scalar(
                    select(BookingGroup).where(BookingGroup.id == gid).with_for_update()
                )
                booking = await session.scalar(
                    select(Booking).where(Booking.booking_key == key).with_for_update()
                )
                identifier = booking.id
                result = await self.apply_changes(session, booking, user, change, context=context)
                booking.version += 1
                flag_modified(booking, "updated_at")  # Explicit unchanged value defeats ON UPDATE.
                await session.flush()
                row = (
                    await session.execute(snapshot_query().where(Booking.id == identifier))
                ).one()
                snapshot = snapshot_from_row(
                    row,
                    self.settings,
                    (await invoice_previews(session, [identifier])).get(identifier),
                )
                event = BookingUpdatedData(
                    booking_key=key,
                    display_key=to_display(key),
                    cw_number=booking.cw_number,
                    station_code=booking.station_code,
                    version=booking.version,
                    last_agent_id=booking.last_agent_id,
                    last_agent_name=snapshot.last_agent.full_name if snapshot.last_agent else None,
                    status_code=snapshot.last_status.code if snapshot.last_status else None,
                    position=booking.last_position,
                    updated_at=booking.updated_at,
                    is_done=booking.is_done,
                    invoice_state=booking.invoice_state,
                    invoice_count=booking.invoice_count,
                    change_kind="invoice",
                ).model_dump(mode="json")
                entry = KeyEntry(
                    identifier, gid, key, booking.cw_number, booking.period, booking.station_code
                )
                group = GroupEntry(
                    gid,
                    GroupInfo(
                        cw_number=folder.cw_number,
                        supplier_name=folder.supplier_name,
                        supplier_type=folder.supplier_type,
                        station_code=folder.station_code,
                    ),
                    folder.last_activity_at,
                )
                return InvoiceResult(
                    snapshot=snapshot.model_dump(
                        exclude={
                            "supplier_name",
                            "supplier_type",
                            "my_pending_tasks",
                            "my_watching",
                            "stale_hours",
                        }
                    ),
                    invoices=await invoice_items(session, identifier),
                    skipped_duplicates=result["skipped_duplicates"],
                    warnings=result["warnings"],
                )
        finally:
            if identifier is not None:
                self.cache.invalidate(identifier)

    async def report(self, period):
        label = period_label(period)
        cached = self.report_cache.get(period)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        def count(condition):
            return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

        async with transaction(self.engine, self.settings) as session:
            row = (
                await session.execute(
                    select(
                        func.count().label("bookings"),
                        count(Booking.invoice_state == "has_invoice").label("with_invoice"),
                        count(Booking.invoice_state == "no_invoice").label("no_invoice"),
                        count(Booking.invoice_state == "unknown").label("not_declared"),
                        func.coalesce(func.sum(Booking.invoice_count), 0).label("invoice_total"),
                        count(Booking.invoice_count >= 2).label("multi_invoice_bookings"),
                        func.coalesce(func.max(Booking.invoice_count), 0).label("max_per_booking"),
                        *[count(Booking.invoice_count == n).label("d" + str(n)) for n in range(3)],
                        count(Booking.invoice_count >= 3).label("d3"),
                    ).where(Booking.period == period)
                )
            ).one()
        result = InvoiceReport(
            period=period,
            period_label=label,
            **{
                name: getattr(row, name)
                for name in (
                    "bookings",
                    "with_invoice",
                    "no_invoice",
                    "not_declared",
                    "invoice_total",
                    "multi_invoice_bookings",
                    "max_per_booking",
                )
            },
            avg_per_booking=float(row.invoice_total / row.bookings) if row.bookings else 0,
            distribution=[
                {"invoices": str(n) if n < 3 else "3+", "bookings": getattr(row, "d" + str(n))}
                for n in range(4)
            ],
        )
        if len(self.report_cache) >= 120:
            self.report_cache.clear()
        self.report_cache[period] = (time.monotonic() + 45, result)
        return result
