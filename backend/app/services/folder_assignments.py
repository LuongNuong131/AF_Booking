"""Recurring responsibility is folder metadata; it never grants/restricts booking access."""

import base64
import binascii
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.etree.ElementTree import ParseError

from openpyxl import load_workbook
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, BookingGroup, Station, User
from app.schemas.contracts import ErrorCode, Page
from app.schemas.folder_assignments import (
    AssignmentImportResult,
    AssignmentImportRow,
    FolderAssignmentItem,
)
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.services.booking_import import supplier_identity
from app.services.booking_writes import group_entry
from app.services.folders import folder_cards
from app.services.key_index import KeyEntry
from app.utils.booking_key import ParsedKey, PartialKey, parse

DEFAULT_AGENT_MAP = {
    "Tran": "HuyenTran",
    "Luong": "LuNu",
    "Binh": "HuongBinh",
    "Quynh": "DiemQuynh",
    "Thang": "XuanThang",
    "Khang": "TanKhang",
    "Linh": "PhuongLinh",
    "Kha": "NguyenKha",
    "Phuong": "ThuPhuong",
    "Kiet": "TuanKiet",
    "Tri": "ThaiTri",
    "Duong": "MinhDuong",
    "Khoa": "DangKhoa",
    "Luan": "VanLuan",
}


def invalid(message):
    raise ApiException(ErrorCode.VALIDATION_ERROR, message=message)


@dataclass
class SourceRow:
    key: ParsedKey
    supplier: str
    kind: str
    agent: str | None
    region: str | None
    review: str | None
    metadata: dict[str, str]


def parse_workbook(encoded: str):
    """Read values only, bound expansion, reject conflicts; never evaluate workbook instructions."""
    try:
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 500000:
            invalid("Workbook must be smaller than 500 KB.")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if (
                len(archive.infolist()) > 200
                or sum(entry.file_size for entry in archive.infolist()) > 8_000_000
            ):
                invalid("Workbook expands beyond the import limit.")
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        try:
            if "Merged" not in workbook.sheetnames:
                invalid("The workbook must contain a Merged sheet.")
            sheet = workbook["Merged"]
            if sheet.max_row > 2001 or sheet.max_column > 40:
                invalid("Import supports at most 2000 rows and 40 columns.")
            values = iter(sheet.values)
            headers = [str(v or "").strip() for v in next(values)]
            required = {
                "Booking Number",
                "Station Code (Booking)",
                "Supplier (Booking)",
                "Agent",
                "Type",
            }
            if not required.issubset(headers):
                invalid("Missing required columns in the Merged sheet.")
            result, source_rows, duplicates = {}, 0, 0
            for number, cells in enumerate(values, 2):
                row = {
                    k: str(v).strip() if v is not None else ""
                    for k, v in zip(headers, cells, strict=False)
                }
                if not any(row.values()):
                    continue
                source_rows += 1
                if (
                    source_rows > 2000
                    or len(row["Station Code (Booking)"]) > 100
                    or len(row["Agent"]) > 100
                    or len(row.get("Region", "")) > 100
                ):
                    invalid(f"Import limits exceeded at row {number}.")
                key = parse(row["Booking Number"])
                supplier = row["Supplier (Booking)"]
                station = row["Station Code (Booking)"].upper()
                if isinstance(key, PartialKey) and re.fullmatch(
                    r"[A-Z]{3}(?:\s*-\s*[A-Z]{3})+", station
                ):
                    keys = [
                        parse(f"{key.cw_number}-{code}-{key.period}")
                        for code in dict.fromkeys(re.split(r"\s*-\s*", station))
                    ]
                else:
                    keys = (
                        [key] if isinstance(key, ParsedKey) and key.station_code == station else []
                    )
                if not keys or not 3 <= len(supplier) <= 255:
                    invalid(f"Invalid booking, station or supplier at row {number}.")
                raw_kind = row["Type"].upper()
                kind = {"HOTEL": "hotel", "HT": "hotel", "GT": "transportation"}.get(
                    raw_kind, "unclassified"
                )
                review = []
                if row.get("Match Status") == "Cần check":
                    review.append(row.get("Ghi chú") or "Source assignment needs review")
                if kind == "unclassified":
                    review.append(f"Confirm service type: {raw_kind or 'missing'}")
                metadata = {
                    k: row[k][:1000]
                    for k in (
                        "Country",
                        "City",
                        "AF Zone",
                        "Type",
                        "Matched Supplier",
                        "Payment Terms",
                        "Level",
                        "Legal Invoice",
                        "Match Status",
                        "Ghi chú",
                    )
                    if row.get(k)
                }
                for key in keys:
                    value = SourceRow(
                        key,
                        supplier,
                        kind,
                        row["Agent"] or None,
                        row.get("Region") or None,
                        "; ".join(review) or None,
                        metadata,
                    )
                    if key.key in result:
                        previous = result[key.key]
                        if (
                            supplier_identity(previous.supplier),
                            previous.kind,
                            previous.agent,
                            previous.region,
                        ) != (
                            supplier_identity(value.supplier),
                            value.kind,
                            value.agent,
                            value.region,
                        ):
                            invalid(f"Conflicting duplicate booking at row {number}: {key.key}.")
                        duplicates += 1
                    else:
                        result[key.key] = value
            folders = {}
            for value in result.values():
                identity = (value.key.cw_number, value.key.station_code)
                signature = (
                    supplier_identity(value.supplier),
                    value.kind,
                    value.agent,
                    value.region,
                )
                if identity in folders and folders[identity] != signature:
                    invalid("Conflicting recurring assignment for the same CW/station.")
                folders[identity] = signature
            if len(result) > 2000:
                invalid("Import supports at most 2000 expanded station bookings.")
            if not result:
                invalid("No booking rows supplied.")
            return list(result.values()), source_rows, duplicates
        finally:
            workbook.close()
    except ApiException:
        raise
    except (
        binascii.Error,
        ValueError,
        KeyError,
        StopIteration,
        OSError,
        zipfile.BadZipFile,
        ParseError,
    ):
        invalid("Could not read the XLSX workbook.")


class FolderAssignments:
    def __init__(self, state):
        self.state = state

    def committed(self, groups, books=()):
        for group in groups:
            self.state.snapshot_cache.invalidate_group(group.id)
            self.state.key_index.update(None, group_entry(group))
        for book in books:
            group = next(g for g in groups if g.id == book.group_id)
            self.state.key_index.update(
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
        self.state.stations.invalidate()
        self.state.ws_manager.spawn(
            self.state.ws_manager.broadcast(
                "catalog.updated", {"resource": "suppliers", "snapshots_changed": True}
            )
        )

    async def listing(self, user, scope, agent_id, region, q, page, size):
        query = select(BookingGroup).where(
            or_(
                BookingGroup.assignment_source_agent.is_not(None),
                BookingGroup.assignment_metadata.is_not(None),
                BookingGroup.assigned_to.is_not(None),
            )
        )
        if scope == "mine":
            query = query.where(BookingGroup.assigned_to == user.id)
        elif scope == "unassigned":
            query = query.where(BookingGroup.assigned_to.is_(None))
        elif scope == "review":
            query = query.where(BookingGroup.assignment_review.is_not(None))
        if agent_id:
            query = query.where(BookingGroup.assigned_to == agent_id)
        if region:
            query = query.where(BookingGroup.assignment_region == region)
        if q.strip():
            value = "%" + q.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            query = query.where(
                or_(
                    BookingGroup.supplier_name.ilike(value, escape="!"),
                    BookingGroup.station_code.ilike(value, escape="!"),
                    BookingGroup.cw_number.ilike(value, escape="!"),
                )
            )
        async with transaction(self.state.engine, self.state.settings) as session:
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            groups = list(
                (
                    await session.scalars(
                        query.order_by(
                            BookingGroup.assignment_region,
                            BookingGroup.station_code,
                            BookingGroup.supplier_type,
                            BookingGroup.id,
                        )
                        .offset((page - 1) * size)
                        .limit(size)
                    )
                ).all()
            )
            cards = await folder_cards(
                session, [g.id for g in groups], self.state.settings.stale_hours_default
            )
            owners = (
                {
                    u.id: u
                    for u in (
                        await session.scalars(
                            select(User).where(
                                User.id.in_([g.assigned_to for g in groups if g.assigned_to])
                            )
                        )
                    ).all()
                }
                if groups
                else {}
            )
            return Page[FolderAssignmentItem](
                total=total,
                page=page,
                size=size,
                items=[
                    FolderAssignmentItem(
                        group_id=g.id,
                        folder=card,
                        assigned_to={
                            "id": owners[g.assigned_to].id,
                            "full_name": owners[g.assigned_to].full_name,
                        }
                        if g.assigned_to in owners
                        else None,
                        region=g.assignment_region,
                        source_agent=g.assignment_source_agent,
                        review=g.assignment_review,
                        metadata=g.assignment_metadata or {},
                        version=g.assignment_version,
                    )
                    for g, card in zip(groups, cards, strict=True)
                ],
            )

    async def options(self):
        async with transaction(self.state.engine, self.state.settings) as session:
            users = (
                await session.scalars(
                    select(User)
                    .where(
                        User.deleted_at.is_(None),
                        User.is_active.is_(True),
                    )
                    .order_by(User.full_name)
                )
            ).all()
            regions = (
                await session.scalars(
                    select(BookingGroup.assignment_region)
                    .where(BookingGroup.assignment_region.is_not(None))
                    .distinct()
                    .order_by(BookingGroup.assignment_region)
                )
            ).all()
            return {
                "users": [
                    {"id": u.id, "username": u.username, "full_name": u.full_name} for u in users
                ],
                "regions": regions,
                "agent_map": DEFAULT_AGENT_MAP,
            }

    async def patch(self, identifier, body, user, context):
        changed = []
        async with transaction(
            self.state.engine, self.state.settings, after_commit=lambda: self.committed(changed)
        ) as session:
            live = await session.scalar(select(User).where(User.id == user.id).with_for_update())
            AuthService.require_live_row(live, user)
            # Everyone may classify a folder; responsibility changes belong to supervisors.
            if live.role not in {"qc", "admin"} and body.model_fields_set - {
                "supplier_type",
                "expected_version",
                "expected_supplier_type",
            }:
                raise ApiException(ErrorCode.FORBIDDEN)
            group = await session.scalar(
                select(BookingGroup).where(BookingGroup.id == identifier).with_for_update()
            )
            if group is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            if not body.model_fields_set - {"expected_version", "expected_supplier_type"}:
                invalid("Choose assignment fields to update.")
            if (
                body.expected_supplier_type is not None
                and group.supplier_type != body.expected_supplier_type
            ):
                raise ApiException(ErrorCode.VERSION_CONFLICT)
            if group.assignment_version != body.expected_version:
                raise ApiException(ErrorCode.VERSION_CONFLICT)
            before = {
                k: getattr(group, k)
                for k in ("assigned_to", "assignment_region", "assignment_review", "supplier_type")
            }
            if "assigned_to" in body.model_fields_set:
                if body.assigned_to is not None:
                    owner = await session.scalar(
                        select(User)
                        .where(
                            User.id == body.assigned_to,
                            User.is_active.is_(True),
                            User.deleted_at.is_(None),
                        )
                        .with_for_update()
                    )
                    if owner is None:
                        invalid("Choose an active user.")
                group.assigned_to = body.assigned_to
            for field, attribute in (
                ("region", "assignment_region"),
                ("review", "assignment_review"),
            ):
                if field in body.model_fields_set:
                    setattr(group, attribute, (getattr(body, field) or "").strip() or None)
            if "supplier_type" in body.model_fields_set:
                if body.supplier_type is None:
                    invalid("Select a service type.")
                group.supplier_type = body.supplier_type.value
            group.assignment_version += 1
            # Metadata edits must not reset stale clocks, status, or last handling agent.
            flag_modified(group, "updated_at")
            changed.append(group)
            record_audit(
                session,
                "folder_assignment_updated",
                actor_id=user.id,
                context=context,
                entity_type="booking_group",
                entity_id=str(group.id),
                meta={"before": before, "after": {k: getattr(group, k) for k in before}},
            )
        return {"version": group.assignment_version}

    async def import_workbook(self, body, user, context):
        from starlette.concurrency import run_in_threadpool

        rows, count, duplicates = await run_in_threadpool(parse_workbook, body.workbook)
        mapping = DEFAULT_AGENT_MAP | body.agent_map
        changed, created = [], []
        async with transaction(
            self.state.engine,
            self.state.settings,
            seconds=55,
            after_commit=lambda: self.committed(changed, created) if body.apply else None,
        ) as session:
            live = await session.scalar(select(User).where(User.id == user.id).with_for_update())
            AuthService.require_live_row(live, user)
            if live.role != "admin":
                raise ApiException(ErrorCode.FORBIDDEN)
            users = {
                u.username.casefold(): u
                for u in (
                    await session.scalars(
                        select(User).where(User.deleted_at.is_(None), User.is_active.is_(True))
                    )
                ).all()
            }
            session.info["include_deleted"] = True
            groups = {
                (g.cw_number, g.station_code): g
                for g in (
                    await session.scalars(
                        select(BookingGroup)
                        .where(
                            tuple_(BookingGroup.cw_number, BookingGroup.station_code).in_(
                                {(r.key.cw_number, r.key.station_code) for r in rows}
                            )
                        )
                        .order_by(BookingGroup.id)
                        .with_for_update()
                    )
                ).all()
            }
            existing_books = (
                await session.scalars(
                    select(Booking).where(Booking.booking_key.in_([r.key.key for r in rows]))
                )
            ).all()
            deleted_station = await session.scalar(
                select(Station.code)
                .where(
                    Station.code.in_({r.key.station_code for r in rows}),
                    Station.deleted_at.is_not(None),
                )
                .limit(1)
            )
            if (
                any(g.deleted_at for g in groups.values())
                or any(b.deleted_at for b in existing_books)
                or deleted_station
            ):
                invalid(
                    "Some bookings, folders or stations are in Trash. "
                    "Restore them before importing."
                )
            session.info.pop("include_deleted")
            existing = {book.booking_key for book in existing_books}
            identities = {(r.key.cw_number, r.key.station_code) for r in rows}
            new_groups = identities - groups.keys()
            preserved = {
                identity
                for identity, group in groups.items()
                if group.assignment_metadata is not None or group.assigned_to is not None
            }
            updates = groups.keys() - preserved
            preview = []
            for row in rows:
                identity = (row.key.cw_number, row.key.station_code)
                group = groups.get(identity)
                owner = users.get(mapping.get(row.agent, "").casefold())
                review = [row.review] if row.review else []
                if owner is None:
                    review.append(f"No active username mapped for {row.agent or 'missing agent'}")
                # Suggested owners in Cần check stay unassigned until a supervisor resolves them.
                if row.metadata.get("Match Status") == "Cần check":
                    owner = None
                review_text = "; ".join(review)[:1000] or None
                preview.append(
                    AssignmentImportRow(
                        booking_key=row.key.key,
                        supplier_name=row.supplier,
                        station_code=row.key.station_code,
                        supplier_type=row.kind,
                        source_agent=row.agent,
                        username=owner.username if owner else None,
                        region=row.region,
                        review=review_text,
                    )
                )
                if not body.apply:
                    continue
                if group is None:
                    group = BookingGroup(
                        cw_number=row.key.cw_number,
                        station_code=row.key.station_code,
                        supplier_name=row.supplier,
                        supplier_type=row.kind,
                        created_by=user.id,
                        booking_count=0,
                        recurring_enabled=True,
                        last_activity_at=datetime.now(UTC),
                    )
                    session.add(group)
                    groups[identity] = group
                if identity not in preserved:
                    group.assigned_to, group.assignment_region = (
                        owner.id if owner else None,
                        row.region,
                    )
                    group.assignment_source_agent, group.assignment_review = row.agent, review_text
                    group.assignment_metadata = row.metadata
                    if group.supplier_type == "unclassified":
                        group.supplier_type = row.kind
                    group.assignment_version = (group.assignment_version or 1) + 1
                    if group.id is not None:
                        flag_modified(group, "updated_at")
                if group not in changed:
                    changed.append(group)
            if body.apply:
                await session.flush()
                codes = sorted({row.key.station_code for row in rows})
                statement = insert(Station).values([{"code": code} for code in codes])
                await session.execute(
                    statement.on_duplicate_key_update(code=statement.inserted.code)
                )
                for row in rows:
                    if row.key.key not in existing:
                        group = groups[(row.key.cw_number, row.key.station_code)]
                        book = Booking(
                            booking_key=row.key.key,
                            group_id=group.id,
                            cw_number=row.key.cw_number,
                            station_code=row.key.station_code,
                            period=row.key.period,
                        )
                        session.add(book)
                        group.booking_count += 1
                        created.append(book)
                await session.flush()
                record_audit(
                    session,
                    "folder_assignments_imported",
                    actor_id=user.id,
                    context=context,
                    entity_type="booking_import",
                    meta={
                        "source_rows": count,
                        "bookings_created": len(created),
                        "folders_assigned": len(new_groups | updates),
                        "folders_preserved": len(preserved),
                    },
                )
            return AssignmentImportResult(
                source_rows=count,
                duplicate_rows=duplicates,
                new_bookings=len(rows) - len(existing),
                new_folders=len(new_groups),
                updated_folders=len(updates),
                preserved_folders=len(preserved),
                applied=body.apply,
                agent_map={
                    label: mapping.get(label, "")
                    for label in sorted({r.agent for r in rows if r.agent})
                },
                rows=preview,
            )
