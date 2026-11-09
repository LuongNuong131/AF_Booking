"""Atomic, insert-only import. No notes, statuses or historical updates are invented."""

import csv
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.mysql import insert

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, Station, User
from app.schemas.admin import BookingImportResult
from app.schemas.contracts import ErrorCode, SupplierType
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.services.booking_writes import group_entry
from app.services.key_index import KeyEntry
from app.utils.booking_key import ParsedKey, PartialKey, parse
from app.utils.supplier import normalize_supplier_name


@dataclass(frozen=True)
class ImportRow:
    key: ParsedKey
    supplier: str
    kind: str
    recurring: bool = True


def supplier_identity(value: str) -> str:
    # Station tags are stored separately. Preserve the first original display name.
    return normalize_supplier_name(
        re.sub(r"(?:\s*-\s*[A-Z]{3})+$", "", value).replace("&", " and ")
    )


def import_rows(
    data: str,
    statistics: dict | None = None,
    *,
    station_source="strict",
    fill_missing_supplier=False,
) -> tuple[list[ImportRow], int]:
    try:
        return _import_rows(data, statistics, station_source, fill_missing_supplier)
    except csv.Error:
        raise ApiException(
            ErrorCode.VALIDATION_ERROR,
            message="Could not read CSV/TSV. Check the column separators and quoted fields.",
            details={"reason": "invalid_delimited_text"},
        ) from None


def _import_rows(
    data: str, statistics: dict | None, station_source: str, fill_missing_supplier: bool
) -> tuple[list[ImportRow], int]:
    data = data.lstrip("\ufeff")
    if not data.strip():
        raise ApiException(ErrorCode.VALIDATION_ERROR, message="No booking rows supplied.")
    delimiter = "\t" if "\t" in data.splitlines()[0] else ","
    # Match files opened with newline='': clipboard text can use bare CR, and
    # quoted supplier cells may contain embedded CR/LF characters.
    reader = csv.DictReader(io.StringIO(data, newline=""), delimiter=delimiter, strict=True)
    if not {"Booking Number", "Suppliers", "Station Code"}.issubset(reader.fieldnames or []):
        raise ApiException(
            ErrorCode.VALIDATION_ERROR,
            message="Required columns: Booking Number, Suppliers, Station Code.",
        )
    unique, folders = {}, {}
    source = list(reader)
    if len(source) > 2000:
        raise ApiException(
            ErrorCode.VALIDATION_ERROR,
            message="Import supports up to 2000 source rows.",
            details={"max_rows": 2000},
        )
    suppliers = {}
    for row in source:
        parsed = parse((row.get("Booking Number") or "").strip())
        name = (row.get("Suppliers") or "").strip()
        if parsed and name:
            suppliers.setdefault(parsed.cw_number, {})[supplier_identity(name)] = name
    adjustments = []
    source_rows, duplicates = 0, 0
    for number, row in enumerate(source, 2):
        if not any(value.strip() for value in row.values() if isinstance(value, str)):
            continue
        source_rows += 1
        parsed = parse((row.get("Booking Number") or "").strip())
        supplier = (row.get("Suppliers") or "").strip()
        station = (row.get("Station Code") or "").strip().upper()
        if isinstance(parsed, ParsedKey) and not station:
            station = parsed.station_code
            adjustments.append(dict(row=number, field="Station Code", before="", after=station))
        if parsed and not supplier and fill_missing_supplier:
            matches = suppliers.get(parsed.cw_number, {})
            if len(matches) == 1:
                supplier = next(iter(matches.values()))
                adjustments.append(dict(row=number, field="Suppliers", before="", after=supplier))
        if (
            isinstance(parsed, ParsedKey)
            and station_source == "booking_number"
            and station != parsed.station_code
        ):
            adjustments.append(
                dict(row=number, field="Station Code", before=station, after=parsed.station_code)
            )
            station = parsed.station_code
        kind = (row.get("Supplier Type") or "").strip().lower() or "unclassified"
        recurrence = (row.get("Recurring") or "true").strip().lower()
        recurring = recurrence == "true"
        multiple = re.fullmatch(r"[A-Z]{3}(?:\s*-\s*[A-Z]{3})+", station)
        if (
            parsed
            and multiple
            and (
                isinstance(parsed, PartialKey)
                or parsed.station_code in re.split(r"\s*-\s*", station)
                or station_source == "station_code"
            )
        ):
            stations = list(dict.fromkeys(re.split(r"\s*-\s*", station)))
            keys = [parse(f"{parsed.cw_number}-{code}-{parsed.period}") for code in stations]
            adjustments.append(
                dict(
                    row=number,
                    field="Booking Number",
                    before=row.get("Booking Number", ""),
                    after=", ".join(k.key for k in keys),
                )
            )
        else:
            if (
                isinstance(parsed, ParsedKey)
                and station_source == "station_code"
                and re.fullmatch(r"[A-Z]{3}", station)
                and station != parsed.station_code
            ):
                replacement = parse(f"{parsed.cw_number}-{station}-{parsed.period}")
                adjustments.append(
                    dict(
                        row=number, field="Booking Number", before=parsed.key, after=replacement.key
                    )
                )
                parsed = replacement
            keys = (
                [parsed] if isinstance(parsed, ParsedKey) and parsed.station_code == station else []
            )
        if (
            None in row
            or not keys
            or not 3 <= len(supplier) <= 255
            or recurrence not in {"true", "false"}
            or kind not in set(SupplierType)
            or source_rows > 2000
        ):
            raise ApiException(
                ErrorCode.VALIDATION_ERROR,
                message=f"Invalid import row {number}.",
                details={"row": number},
            )
        for key in keys:
            value = ImportRow(key, supplier, kind, recurring)
            if key.key in unique:
                prior = unique[key.key]
                if (
                    prior.kind != kind
                    or prior.recurring != recurring
                    or supplier_identity(prior.supplier) != supplier_identity(supplier)
                ):
                    raise ApiException(
                        ErrorCode.VALIDATION_ERROR,
                        message=f"Conflicting duplicate booking at row {number}.",
                        details={"row": number, "booking_key": key.key},
                    )
                duplicates += 1
                continue
            identity = (key.cw_number, key.station_code)
            if identity in folders and (
                supplier_identity(folders[identity][0]) != supplier_identity(supplier)
                or folders[identity][1] != kind
                or folders[identity][2] != recurring
            ):
                raise ApiException(
                    ErrorCode.VALIDATION_ERROR,
                    message=f"Conflicting supplier for the same CW/station at row {number}.",
                    details={"row": number},
                )
            folders[identity] = (supplier, kind, recurring)
            unique[key.key] = value
    if not unique:
        raise ApiException(ErrorCode.VALIDATION_ERROR, message="No booking rows supplied.")
    if statistics is not None:
        statistics["duplicate_rows"] = duplicates
        statistics["adjustments"] = adjustments
    return list(unique.values()), source_rows


async def run_import(state, body, user, context) -> BookingImportResult:
    statistics = {}
    rows, count = import_rows(
        body.data,
        statistics,
        station_source=body.station_source,
        fill_missing_supplier=body.fill_missing_supplier,
    )
    identities = {(r.key.cw_number, r.key.station_code) for r in rows}
    created = []
    changed_groups = []

    def committed():
        if body.apply:
            for book in created:
                group = next(g for g in changed_groups if g.id == book.group_id)
                state.key_index.update(
                    KeyEntry(
                        book.id,
                        book.group_id,
                        book.booking_key,
                        book.cw_number,
                        book.period,
                        book.station_code,
                    ),
                    group_entry(group),
                )
            state.stations.invalidate()

    async with transaction(
        state.engine, state.settings, seconds=55, after_commit=committed
    ) as session:
        live = await session.scalar(select(User).where(User.id == user.id).with_for_update())
        AuthService.require_live_row(live, user)
        if live.role != "admin":
            raise ApiException(ErrorCode.FORBIDDEN)
        existing = set(
            (
                await session.scalars(
                    select(Booking.booking_key).where(
                        Booking.booking_key.in_([r.key.key for r in rows])
                    )
                )
            ).all()
        )
        groups = {
            (g.cw_number, g.station_code): g
            for g in (
                await session.scalars(
                    select(BookingGroup)
                    .where(
                        tuple_(BookingGroup.cw_number, BookingGroup.station_code).in_(identities)
                    )
                    .with_for_update()
                )
            ).all()
        }
        new_folders = identities - groups.keys()
        result = BookingImportResult(
            source_rows=count,
            unique_bookings=len(rows),
            duplicate_rows=statistics["duplicate_rows"],
            new_bookings=len(rows) - len(existing),
            existing_bookings=len(existing),
            new_folders=len(new_folders),
            applied=body.apply,
            sample_keys=[r.key.key for r in rows[:10]],
            adjustments=statistics["adjustments"],
        )
        if not body.apply:
            return result
        for row in rows:
            identity = (row.key.cw_number, row.key.station_code)
            if identity not in groups:
                group = BookingGroup(
                    cw_number=row.key.cw_number,
                    station_code=row.key.station_code,
                    supplier_name=row.supplier,
                    supplier_type=row.kind,
                    recurring_enabled=row.recurring,
                    created_by=user.id,
                    booking_count=0,
                    last_activity_at=datetime.now(UTC),
                )
                session.add(group)
                groups[identity] = group
        await session.flush()
        station_insert = insert(Station).values(
            [{"code": code} for code in sorted({r.key.station_code for r in rows})]
        )
        await session.execute(
            station_insert.on_duplicate_key_update(code=station_insert.inserted.code)
        )
        for row in rows:
            if row.key.key in existing:
                continue
            group = groups[(row.key.cw_number, row.key.station_code)]
            group.booking_count += 1
            booking = Booking(
                booking_key=row.key.key,
                group_id=group.id,
                cw_number=row.key.cw_number,
                station_code=row.key.station_code,
                period=row.key.period,
            )
            session.add(booking)
            created.append(booking)
        await session.flush()
        changed_groups.extend(groups.values())
        record_audit(
            session,
            "bookings_imported",
            actor_id=user.id,
            entity_type="booking_import",
            entity_id=None,
            context=context,
            meta={"source_rows": count, "created": len(created), "skipped": len(existing)},
        )
    return result
