"""Booking work requests shared with QC; personal reminders stay private."""

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Attachment, Booking, BookingGroup, BookingWorkTask, Notification, User
from app.schemas.contracts import Attachment as AttachmentDTO
from app.schemas.contracts import ErrorCode, Page
from app.schemas.realtime import NotificationNewData
from app.schemas.workflow import WorkTaskBundle, WorkTaskItem
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.services.exports import date_text, safe_cell
from app.services.reports import day_bounds
from app.services.workflow_xlsx import WorkflowWorkbook
from app.utils.booking_key import ParsedKey, parse, to_display
from app.utils.text import clean_note
from app.utils.ticket_text import REJECTION_MESSAGE, TITLES, edit_token, ticket_title


class WorkTasks:
    def __init__(self, engine, settings, ws):
        self.engine, self.settings, self.ws = engine, settings, ws

    def query(self, user, status="pending", day=None, booking_key=None, creator_id=None):
        creator, handler = aliased(User), aliased(User)
        query = (
            select(
                BookingWorkTask,
                Booking.booking_key,
                BookingGroup.supplier_name,
                creator.full_name.label("creator_name"),
                handler.full_name.label("handler_name"),
            )
            .join(Booking, Booking.id == BookingWorkTask.booking_id)
            .join(BookingGroup, BookingGroup.id == Booking.group_id)
            .join(creator, creator.id == BookingWorkTask.created_by)
            .outerjoin(handler, handler.id == BookingWorkTask.handled_by)
            .where(Booking.deleted_at.is_(None), BookingGroup.deleted_at.is_(None))
        )
        if user.role not in {"qc", "admin"}:
            query = query.where(BookingWorkTask.created_by == user.id)
        elif creator_id:
            query = query.where(BookingWorkTask.created_by == creator_id)
        if status != "all":
            query = query.where(BookingWorkTask.status == status)
        if booking_key:
            query = query.where(Booking.booking_key == booking_key)
        if day:
            lo, hi = day_bounds(day, ZoneInfo(self.settings.business_timezone))
            query = query.where(BookingWorkTask.created_at >= lo, BookingWorkTask.created_at < hi)
        return query

    @staticmethod
    def dto(row):
        task, key, supplier, creator, handler = row
        return WorkTaskItem(
            id=task.id,
            booking_key=key,
            display_key=to_display(key),
            supplier_name=supplier,
            creator={"id": task.created_by, "full_name": creator},
            message=task.message,
            title=task.title or ticket_title(task.issue_type, key),
            issue_type=task.issue_type,
            edit_token=edit_token(task),
            status=task.status,
            created_at=task.created_at,
            handled_by={"id": task.handled_by, "full_name": handler} if task.handled_by else None,
            handled_at=task.handled_at,
            handling_note=task.handling_note,
        )

    async def with_images(self, session, items):
        if items:
            by_id = {item.id: item for item in items}
            images = await session.scalars(
                select(Attachment).where(Attachment.work_task_id.in_(by_id)).order_by(Attachment.id)
            )
            for image in images:
                by_id[image.work_task_id].attachments.append(
                    AttachmentDTO.model_validate(image, from_attributes=True)
                )
        return items

    async def detail(self, identifier, user):
        async with transaction(self.engine, self.settings) as session:
            row = (
                await session.execute(
                    self.query(user, "all").where(BookingWorkTask.id == identifier)
                )
            ).one_or_none()
            if row is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            return (await self.with_images(session, [self.dto(row)]))[0]

    async def update(self, identifier, body, user, context):
        async with transaction(self.engine, self.settings) as session:
            live = await session.scalar(select(User).where(User.id == user.id).with_for_update())
            AuthService.require_live_row(live, user)
            if live.role != "admin":
                raise ApiException(ErrorCode.FORBIDDEN)
            task = await session.scalar(
                select(BookingWorkTask)
                .join(Booking, Booking.id == BookingWorkTask.booking_id)
                .join(BookingGroup, BookingGroup.id == Booking.group_id)
                .where(
                    BookingWorkTask.id == identifier,
                    Booking.deleted_at.is_(None),
                    BookingGroup.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if task is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            if edit_token(task) != body.expected_token:
                raise ApiException(
                    ErrorCode.VERSION_CONFLICT,
                    message=(
                        "This ticket changed. Reopen it to review the latest version before saving."
                    ),
                )
            before = {
                name: getattr(task, name)
                for name in ("title", "message", "issue_type", "status", "handling_note")
            }
            previous_status = task.status
            task.title, task.message, task.issue_type = body.title, body.message, body.issue_type
            task.status = body.status
            if task.status == "handled":
                if previous_status != "handled":
                    task.handled_by, task.handled_at = user.id, datetime.now(UTC)
                task.handling_note = clean_note(body.handling_note)
            else:
                task.handled_by = task.handled_at = task.handling_note = None
            record_audit(
                session,
                "admin_ticket_updated",
                actor_id=user.id,
                context=context,
                entity_type="work_task",
                entity_id=str(task.id),
                meta={"before": before, "after": {name: getattr(task, name) for name in before}},
            )
            await session.flush()
            row = (
                await session.execute(
                    self.query(user, "all").where(BookingWorkTask.id == identifier)
                )
            ).one()
            return (await self.with_images(session, [self.dto(row)]))[0]

    async def merge(self, body, user):
        if user.role not in {"qc", "admin"}:
            raise ApiException(ErrorCode.FORBIDDEN)
        ids = list(dict.fromkeys(body.ids))
        if len(ids) < 2:
            raise ApiException(ErrorCode.VALIDATION_ERROR)
        async with transaction(self.engine, self.settings) as session:
            rows = (
                await session.execute(self.query(user, "all").where(BookingWorkTask.id.in_(ids)))
            ).all()
            if len(rows) != len(ids):
                raise ApiException(ErrorCode.NOT_FOUND)
            items = await self.with_images(session, [self.dto(row) for row in rows])
            if any(item.issue_type != "cannot_send_rejection_letters" for item in items):
                raise ApiException(
                    ErrorCode.VALIDATION_ERROR,
                    message="Only Cannot send rejection letters tickets can be combined.",
                )
            by_id = {item.id: item for item in items}
            keys = list(dict.fromkeys(by_id[i].booking_key for i in ids))
            return WorkTaskBundle(
                title=TITLES["cannot_send_rejection_letters"],
                message=REJECTION_MESSAGE + "\n\n" + "\n".join(keys),
                booking_keys=keys,
                attachments=[image for i in ids for image in by_id[i].attachments],
            )

    async def listing(
        self, user, status="pending", day=None, booking_key=None, creator_id=None, page=1, size=20
    ):
        query = self.query(user, status, day, booking_key, creator_id)
        async with transaction(self.engine, self.settings) as session:
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            rows = (
                await session.execute(
                    query.order_by(BookingWorkTask.created_at.desc(), BookingWorkTask.id.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
            return Page[WorkTaskItem](
                items=await self.with_images(session, [self.dto(r) for r in rows]),
                total=total,
                page=page,
                size=size,
            )

    async def notify(self, session, task, key, actor, kind, targets):
        events = []
        for target in sorted(set(targets) - {actor.id}):
            entry = Notification(
                user_id=target,
                booking_id=task.booking_id,
                type=kind,
                by_agent_id=actor.id,
                created_at=datetime.now(UTC),
            )
            session.add(entry)
            await session.flush()
            events.append(
                (
                    target,
                    NotificationNewData(
                        id=entry.id,
                        type=kind,
                        booking_key=key,
                        display_key=to_display(key),
                        by_agent_name=actor.full_name,
                        created_at=entry.created_at,
                    ).model_dump(mode="json"),
                )
            )
        return events

    async def dispatch(self, events):
        await asyncio.gather(
            *(self.ws.send_user(user_id, "notification.new", data) for user_id, data in events)
        )

    async def create(self, key, body, user, context):
        parsed = parse(key, self.settings.station_code_pattern)
        if not isinstance(parsed, ParsedKey):
            raise ApiException(ErrorCode.INVALID_BOOKING_KEY)
        events = []

        def committed():
            if events:
                self.ws.spawn(self.dispatch(events))

        for attempt in range(2):
            events = []
            try:
                async with transaction(
                    self.engine, self.settings, after_commit=committed
                ) as session:
                    live = await session.scalar(
                        select(User).where(User.id == user.id).with_for_update()
                    )
                    AuthService.require_live_row(live, user)
                    existing = await session.scalar(
                        select(BookingWorkTask).where(
                            BookingWorkTask.client_request_id == str(body.client_request_id)
                        )
                    )
                    booking = await session.scalar(
                        select(Booking)
                        .join(BookingGroup, BookingGroup.id == Booking.group_id)
                        .where(
                            Booking.booking_key == parsed.key,
                            Booking.deleted_at.is_(None),
                            BookingGroup.deleted_at.is_(None),
                        )
                    )
                    if booking is None:
                        raise ApiException(ErrorCode.NOT_FOUND)
                    if existing:
                        if (
                            existing.created_by != user.id
                            or existing.booking_id != booking.id
                            or existing.message != body.message
                            or existing.issue_type != body.issue_type
                        ):
                            raise ApiException(ErrorCode.VALIDATION_ERROR)
                        task = existing
                    else:
                        task = BookingWorkTask(
                            booking_id=booking.id,
                            created_by=user.id,
                            message=body.message,
                            issue_type=body.issue_type,
                            title=ticket_title(body.issue_type, parsed.key),
                            client_request_id=str(body.client_request_id),
                            created_at=datetime.now(UTC),
                        )
                        session.add(task)
                        await session.flush()
                        targets = (
                            await session.scalars(
                                select(User.id).where(
                                    User.is_active.is_(True), User.role.in_(["qc", "admin"])
                                )
                            )
                        ).all()
                        events = await self.notify(
                            session, task, parsed.key, live, "work_task_created", targets
                        )
                        record_audit(
                            session,
                            "work_task_created",
                            actor_id=user.id,
                            context=context,
                            entity_type="work_task",
                            entity_id=str(task.id),
                            meta={"booking_key": parsed.key},
                        )
                    row = (
                        await session.execute(
                            self.query(user, "all").where(BookingWorkTask.id == task.id)
                        )
                    ).one()
                    result = (await self.with_images(session, [self.dto(row)]))[0]
                return result
            except IntegrityError:
                if attempt:
                    raise ApiException(ErrorCode.SERVICE_BUSY) from None

    async def handle(self, identifier, body, user, context):
        events = []

        def committed():
            if events:
                self.ws.spawn(self.dispatch(events))

        async with transaction(self.engine, self.settings, after_commit=committed) as session:
            live = await session.scalar(select(User).where(User.id == user.id).with_for_update())
            AuthService.require_live_row(live, user)
            if live.role not in {"qc", "admin"}:
                raise ApiException(ErrorCode.FORBIDDEN)
            task = await session.scalar(
                select(BookingWorkTask)
                .join(Booking, Booking.id == BookingWorkTask.booking_id)
                .join(BookingGroup, BookingGroup.id == Booking.group_id)
                .where(
                    BookingWorkTask.id == identifier,
                    Booking.deleted_at.is_(None),
                    BookingGroup.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if task is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            if task.status == "pending":
                task.status, task.handled_by, task.handled_at = (
                    "handled",
                    user.id,
                    datetime.now(UTC),
                )
                task.handling_note = clean_note(body.handling_note)
                key = await session.scalar(
                    select(Booking.booking_key).where(Booking.id == task.booking_id)
                )
                targets = (
                    await session.scalars(
                        select(User.id).where(
                            User.is_active.is_(True), User.role.in_(["qc", "admin"])
                        )
                    )
                ).all()
                events = await self.notify(
                    session, task, key, live, "work_task_handled", [task.created_by, *targets]
                )
                record_audit(
                    session,
                    "work_task_handled",
                    actor_id=user.id,
                    context=context,
                    entity_type="work_task",
                    entity_id=str(task.id),
                )
                await session.flush()
            row = (
                await session.execute(
                    self.query(user, "all").where(BookingWorkTask.id == identifier)
                )
            ).one()
            return (await self.with_images(session, [self.dto(row)]))[0]

    async def export(self, user, status, day, booking_key, creator_id, context):
        with WorkflowWorkbook() as document:
            workbook = document.workbook
            sheet = workbook.create_sheet("QC work tasks")
            sheet.append(
                [
                    "Booking",
                    "Supplier",
                    "Created by",
                    "Request",
                    "Status",
                    "Created at",
                    "Handled by",
                    "Handled at",
                    "Handling note",
                    "Title",
                ]
            )
            async with transaction(
                self.engine, self.settings, seconds=self.settings.export_timeout_seconds
            ) as session:
                rows = await session.stream(
                    self.query(user, status, day, booking_key, creator_id)
                    .order_by(BookingWorkTask.created_at, BookingWorkTask.id)
                    .execution_options(yield_per=200)
                )
                try:
                    async for row in rows:
                        r = self.dto(row)
                        zone = ZoneInfo(self.settings.business_timezone)
                        sheet.append(
                            [
                                safe_cell(v)
                                for v in (
                                    r.display_key,
                                    r.supplier_name,
                                    r.creator.full_name,
                                    r.message,
                                    r.status,
                                    date_text(r.created_at, zone),
                                    r.handled_by.full_name if r.handled_by else "",
                                    date_text(r.handled_at, zone) if r.handled_at else "",
                                    r.handling_note,
                                    r.title,
                                )
                            ]
                        )
                        await asyncio.sleep(0)
                finally:
                    await rows.close()
                record_audit(
                    session,
                    "work_tasks_export",
                    actor_id=user.id,
                    context=context,
                    entity_type="export",
                )
            return await document.response("qc-tickets.xlsx")
