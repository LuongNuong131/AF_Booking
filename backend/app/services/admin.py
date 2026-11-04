"""Admin writes recheck role/SID under row locks; snapshot publication follows commit."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.core.errors import ApiException
from app.core.unit_of_work import error_number, transaction
from app.models import AuditLog, Booking, BookingGroup, BookingNote, Station, Status, User
from app.schemas.admin import AdminNote, AdminStatus, AdminUser, AuditEntry, ProfileStats
from app.schemas.contracts import ErrorCode, Page
from app.schemas.realtime import BookingUpdatedData
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.services.booking_reads import invoice_previews, snapshot_from_row, snapshot_query
from app.services.booking_writes import group_entry
from app.services.key_index import KeyEntry
from app.services.session_cache import CurrentUser
from app.services.snapshot_values import apply_snapshot, note_snapshot
from app.services.tasks import effective_settings, now_utc
from app.utils.booking_key import to_display


def admin_status(row):
    return AdminStatus(**{field: getattr(row, field) for field in AdminStatus.model_fields})


def admin_user(row):
    return AdminUser(
        **CurrentUser.from_model(row).public().model_dump(exclude={"settings"}),
        created_at=row.created_at,
        last_login_at=row.last_login_at,
        has_session=row.current_session_id is not None,
    )


def require_admin(row, caller):
    AuthService.require_live_row(row, caller)
    if row.role != "admin":
        raise ApiException(ErrorCode.FORBIDDEN)
    return row


async def locked_admin(session, caller, target=None):
    ids = sorted({caller.id, target or caller.id})
    rows = {
        r.id: r
        for r in (
            await session.scalars(
                select(User).where(User.id.in_(ids)).order_by(User.id).with_for_update()
            )
        ).all()
    }
    require_admin(rows.get(caller.id), caller)
    if target and target not in rows:
        raise ApiException(ErrorCode.NOT_FOUND)
    return rows.get(target or caller.id)


class AdminService:
    def __init__(self, engine, settings, auth, writes, ws, reports):
        self.engine, self.settings, self.auth = engine, settings, auth
        self.writes, self.ws, self.reports = writes, ws, reports

    def tx(self, **kwargs):
        return transaction(self.engine, self.settings, **kwargs)

    def catalog(self, resource, snapshots=False):
        if resource == "users":
            self.writes.collaboration.directory.clear()
        self.writes.cache.clear()
        self.reports.invalidate()
        self.ws.spawn(
            self.ws.broadcast(
                "catalog.updated", {"resource": resource, "snapshots_changed": snapshots}
            )
        )

    async def users(self, q, page, size):
        condition = or_(
            User.username.contains(q, autoescape=True), User.full_name.contains(q, autoescape=True)
        )
        async with self.tx() as session:
            total = await session.scalar(select(func.count()).select_from(User).where(condition))
            rows = (
                await session.scalars(
                    select(User)
                    .where(condition)
                    .order_by(User.id)
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
        return Page(items=[admin_user(r) for r in rows], total=total, page=page, size=size)

    async def create_user(self, body, actor, context):
        from app.core.security import validate_password

        validate_password(body.temporary_password.get_secret_value(), body.username)
        encoded = await self.auth.passwords.hash(body.temporary_password.get_secret_value())
        try:
            async with self.tx(after_commit=lambda: self.catalog("users")) as session:
                await locked_admin(session, actor)
                row = User(
                    username=body.username,
                    full_name=body.full_name,
                    role=body.role,
                    password_hash=encoded,
                    must_change_password=True,
                    settings=effective_settings(None, self.settings.business_timezone),
                )
                session.add(row)
                await session.flush()
                await session.refresh(row)
                record_audit(
                    session,
                    "user_created",
                    actor_id=actor.id,
                    target_user_id=row.id,
                    context=context,
                    meta={"username": row.username, "role": row.role},
                )
                result = admin_user(row)
            return result
        except IntegrityError as error:
            if error_number(error) == 1062:
                raise ApiException(
                    ErrorCode.VALIDATION_ERROR, message="This username is already in use."
                ) from None
            raise

    async def update_user(self, identifier, body, actor, context, password=None):
        encoded = await self.auth.passwords.hash(password) if password is not None else None
        old = None
        reason = "admin_role_changed"
        async with self.auth.mutation(identifier) as session:
            row = await locked_admin(session, actor, identifier)
            values = body.model_dump(exclude_unset=True) if body else {}
            if identifier == actor.id and (
                values.get("is_active") is False or values.get("role", "admin") != "admin"
            ):
                raise ApiException(
                    ErrorCode.FORBIDDEN, message="You cannot disable or demote your own account."
                )
            if (
                encoded is not None
                or values.get("is_active") is False
                or ("role" in values and values["role"] != row.role)
            ):
                old = row.current_session_id
                row.current_session_id = None
                reason = (
                    "password_reset"
                    if encoded
                    else "user_disabled"
                    if values.get("is_active") is False
                    else reason
                )
            for field, value in values.items():
                setattr(row, field, value)
            if encoded is not None:
                from app.core.security import validate_password

                validate_password(password, row.username)
                row.password_hash = encoded
                row.must_change_password = True
            record_audit(
                session,
                "user_password_reset"
                if encoded
                else "user_disabled"
                if values.get("is_active") is False
                else "user_enabled"
                if values.get("is_active") is True
                else "user_updated",
                actor_id=actor.id,
                target_user_id=identifier,
                context=context,
                meta={"changes": values, "session_revoked": old is not None},
            )
            if old:
                record_audit(
                    session,
                    "session_kicked",
                    actor_id=actor.id,
                    target_user_id=identifier,
                    context=context,
                    meta={"reason": reason},
                )
            result = admin_user(row)
        self.catalog("users")
        await self.auth.notify_old_session(identifier, old, reason)
        return result

    async def audit(
        self,
        page,
        size,
        user_id=None,
        action=None,
        start=None,
        end=None,
        entity=None,
        entity_id=None,
    ):
        where = []
        for value, column in [
            (user_id, AuditLog.user_id),
            (action, AuditLog.action),
            (entity, AuditLog.entity_type),
            (entity_id, AuditLog.entity_id),
        ]:
            if value is not None:
                where.append(column == value)
        if start:
            where.append(AuditLog.created_at >= start)
        if end:
            where.append(AuditLog.created_at <= end)
        async with self.tx() as session:
            total = await session.scalar(select(func.count()).select_from(AuditLog).where(*where))
            rows = (
                await session.execute(
                    select(AuditLog, User.full_name)
                    .outerjoin(User, User.id == AuditLog.user_id)
                    .where(*where)
                    .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
        items = [
            AuditEntry(
                id=r.AuditLog.id,
                user={"id": r.AuditLog.user_id, "full_name": r.full_name} if r.full_name else None,
                action=r.AuditLog.action,
                entity_type=r.AuditLog.entity_type,
                entity_id=r.AuditLog.entity_id,
                meta=r.AuditLog.meta,
                ip=r.AuditLog.ip,
                created_at=r.AuditLog.created_at,
            )
            for r in rows
        ]
        return Page(items=items, total=total, page=page, size=size)

    async def notes(self, page, size, key=None, trash=False, q=""):
        deleter = aliased(User)
        where = []
        if key:
            where.append(Booking.booking_key == key)
        if trash:
            where.append(BookingNote.deleted_at.is_not(None))
        if q:
            where.append(
                Booking.booking_key.contains(
                    q.strip().upper().replace("CW ", "CW"), autoescape=True
                )
            )
        query = (
            select(
                BookingNote,
                Booking.booking_key,
                User.full_name,
                Status.code,
                Status.label,
                deleter.full_name.label("deleted_name"),
            )
            .join(Booking, Booking.id == BookingNote.booking_id)
            .join(User, User.id == BookingNote.agent_id)
            .join(Status, Status.id == BookingNote.status_id)
            .outerjoin(deleter, deleter.id == BookingNote.deleted_by)
            .where(*where)
        )
        async with self.tx() as session:
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            rows = (
                await session.execute(
                    query.order_by(BookingNote.id.desc()).offset((page - 1) * size).limit(size)
                )
            ).all()
        items = [
            AdminNote(
                id=r.BookingNote.id,
                booking_key=r.booking_key,
                display_key=to_display(r.booking_key),
                agent={"id": r.BookingNote.agent_id, "full_name": r.full_name},
                status={"code": r.code, "label": r.label},
                position=r.BookingNote.position_label,
                note=r.BookingNote.note,
                created_at=r.BookingNote.created_at,
                deleted_at=r.BookingNote.deleted_at,
                deleted_by={"id": r.BookingNote.deleted_by, "full_name": r.deleted_name}
                if r.deleted_name
                else None,
                delete_reason=r.BookingNote.delete_reason,
            )
            for r in rows
        ]
        return Page(items=items, total=total, page=page, size=size)

    async def change_note(self, identifier, restore, reason, actor, context):
        event = None
        folder = None
        entry = None
        snapshot = None

        def committed():
            if event:
                self.writes.cache.invalidate(entry.id)
                self.writes.index.update(entry, folder)
                self.reports.invalidate()
                self.ws.spawn(self.ws.broadcast("booking.updated", event))

        async with self.tx(after_commit=committed) as session:
            await locked_admin(session, actor)
            source = (
                await session.execute(
                    select(BookingNote.booking_id, Booking.group_id)
                    .join(Booking, Booking.id == BookingNote.booking_id)
                    .where(BookingNote.id == identifier)
                )
            ).first()
            if not source:
                raise ApiException(ErrorCode.NOT_FOUND)
            group = await session.scalar(
                select(BookingGroup).where(BookingGroup.id == source.group_id).with_for_update()
            )
            book = await session.scalar(
                select(Booking).where(Booking.id == source.booking_id).with_for_update()
            )
            note = await session.scalar(
                select(BookingNote).where(BookingNote.id == identifier).with_for_update()
            )
            changed = (note.deleted_at is not None) if restore else (note.deleted_at is None)
            if changed:
                note.deleted_at = None if restore else now_utc()
                note.deleted_by = None if restore else actor.id
                note.delete_reason = None if restore else reason
                await session.flush()
                latest = (
                    await session.execute(
                        select(BookingNote, Status.is_done)
                        .join(Status, Status.id == BookingNote.status_id)
                        .where(BookingNote.booking_id == book.id, BookingNote.deleted_at.is_(None))
                        .order_by(BookingNote.id.desc())
                        .limit(1)
                    )
                ).first()
                n = latest.BookingNote if latest else None
                apply_snapshot(
                    book,
                    note_snapshot(
                        n.id if n else None,
                        n.agent_id if n else None,
                        n.status_id if n else None,
                        n.position_label if n else None,
                        n.created_at if n else None,
                        n.note if n else None,
                        latest.is_done if latest else False,
                    ),
                )
                book.updated_at = now_utc()
                book.version += 1
                book.stale_notified_at = None
                group.last_activity_at = book.updated_at
                record_audit(
                    session,
                    "note_restored" if restore else "note_deleted",
                    actor_id=actor.id,
                    entity_type="note",
                    entity_id=str(identifier),
                    context=context,
                    meta={
                        "booking_key": book.booking_key,
                        "reason": reason,
                        "version": book.version,
                    },
                )
                await session.flush()
            row = (await session.execute(snapshot_query().where(Booking.id == book.id))).one()
            snapshot = snapshot_from_row(
                row, self.settings, (await invoice_previews(session, [book.id])).get(book.id)
            )
            if changed:
                event = BookingUpdatedData(
                    booking_key=book.booking_key,
                    display_key=to_display(book.booking_key),
                    cw_number=book.cw_number,
                    station_code=book.station_code,
                    version=book.version,
                    last_agent_id=book.last_agent_id,
                    last_agent_name=snapshot.last_agent.full_name if snapshot.last_agent else None,
                    status_code=snapshot.last_status.code if snapshot.last_status else None,
                    position=book.last_position,
                    updated_at=book.updated_at,
                    is_done=book.is_done,
                    snapshot_rebuilt=True,
                    invoice_state=book.invoice_state,
                    invoice_count=book.invoice_count,
                ).model_dump(mode="json")
                folder = group_entry(group)
                entry = KeyEntry(
                    book.id,
                    book.group_id,
                    book.booking_key,
                    book.cw_number,
                    book.period,
                    book.station_code,
                )
        return snapshot

    async def statuses(self):
        async with self.tx() as session:
            rows = (
                await session.scalars(select(Status).order_by(Status.sort_order, Status.id))
            ).all()
        return [admin_status(row) for row in rows]

    async def stations(self, q, page, size):
        from app.schemas.folders import StationOption

        condition = or_(
            Station.code.contains(q.upper(), autoescape=True),
            Station.name.contains(q, autoescape=True),
        )
        async with self.tx() as session:
            total = await session.scalar(select(func.count()).select_from(Station).where(condition))
            rows = (
                await session.execute(
                    select(Station.code, Station.name, func.count(BookingGroup.id).label("n"))
                    .outerjoin(BookingGroup, BookingGroup.station_code == Station.code)
                    .where(condition)
                    .group_by(Station.code, Station.name)
                    .order_by(Station.code)
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
        return Page(
            items=[StationOption(code=r.code, name=r.name, folder_count=r.n) for r in rows],
            total=total,
            page=page,
            size=size,
        )

    async def save_status(self, body, actor, context):
        changed = False

        def committed():
            self.writes.cache.clear()
            self.catalog("statuses", changed)

        try:
            async with self.tx(after_commit=committed) as session:
                await locked_admin(session, actor)
                identifier = getattr(body, "id", None)
                row = (
                    await session.scalar(
                        select(Status).where(Status.id == identifier).with_for_update()
                    )
                    if identifier
                    else Status()
                )
                if row is None:
                    raise ApiException(ErrorCode.NOT_FOUND)
                values = body.model_dump(exclude={"id"}, exclude_unset=bool(identifier))
                changed = bool(
                    identifier and ("is_done" in values and row.is_done != values["is_done"])
                )
                for key, value in values.items():
                    setattr(row, key, value)
                if not identifier:
                    session.add(row)
                await session.flush()
                if changed:
                    done_time = (
                        select(BookingNote.created_at)
                        .where(BookingNote.id == Booking.last_note_id)
                        .scalar_subquery()
                    )
                    await session.execute(
                        update(Booking)
                        .where(Booking.last_status_id == row.id)
                        .values(
                            is_done=row.is_done,
                            done_at=done_time if row.is_done else None,
                            version=Booking.version + 1,
                            updated_at=Booking.updated_at,
                            stale_notified_at=None,
                        )
                    )
                record_audit(
                    session,
                    "status_updated" if identifier else "status_created",
                    actor_id=actor.id,
                    entity_type="status",
                    entity_id=str(row.id),
                    context=context,
                    meta={"fields": list(values), "code": row.code},
                )
                result = admin_status(row)
            return result
        except IntegrityError as error:
            if error_number(error) == 1062:
                raise ApiException(
                    ErrorCode.VALIDATION_ERROR, message="This status code is already in use."
                ) from None
            raise

    async def profile_stats(self, user):
        from zoneinfo import ZoneInfo

        prefs = effective_settings(user.settings, self.settings.business_timezone)
        zone = ZoneInfo(prefs["timezone"])
        today = datetime.now(zone).date()
        monday = today - timedelta(days=today.weekday())
        start = datetime.combine(today, datetime.min.time(), zone).astimezone(UTC)
        week = datetime.combine(monday, datetime.min.time(), zone).astimezone(UTC)
        async with self.tx() as session:
            counts = (
                await session.execute(
                    select(
                        func.count().label("week"),
                        func.sum(case((BookingNote.created_at >= start, 1), else_=0)).label(
                            "today"
                        ),
                    ).where(
                        BookingNote.agent_id == user.id,
                        BookingNote.deleted_at.is_(None),
                        BookingNote.created_at >= week,
                    )
                )
            ).one()
            rows = (
                await session.scalars(
                    select(AuditLog)
                    .where(
                        or_(
                            AuditLog.user_id == user.id,
                            (AuditLog.entity_type == "user") & (AuditLog.entity_id == str(user.id)),
                        ),
                        AuditLog.action.in_(["login_success", "login_failed", "session_replaced"]),
                    )
                    .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                    .limit(10)
                )
            ).all()
        return ProfileStats(
            notes_today=counts.today or 0,
            notes_week=counts.week,
            timezone=prefs["timezone"],
            login_history=[
                {"action": r.action, "created_at": r.created_at, "ip": r.ip} for r in rows
            ],
        )
