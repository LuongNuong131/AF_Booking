"""Booking locks serialize collaboration writes; user locks bound subscription counts."""

import time
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.orm import aliased

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import (
    Booking,
    BookingAssignment,
    BookingGroup,
    BookingWatcher,
    FolderFollower,
    Notification,
    User,
)
from app.schemas.collaboration import AssignmentItem, FolderFollowState, WatchState
from app.schemas.contracts import AgentSummary, ErrorCode, Page
from app.schemas.realtime import NotificationNewData
from app.services.audit import record_audit
from app.services.auth import AuthService
from app.services.folders import folder_cards
from app.services.search_limiter import SearchLimiter
from app.utils.booking_key import ParsedKey, parse, to_display
from app.utils.folder_key import folder_parts


def utcnow():
    value = datetime.now(UTC)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


async def insert_notifications(session, rows, key, agent_name):
    if not rows:
        return []
    # Exactly one multi-row INSERT; a generated nullable unique key merges only
    # unread watch_update rows. Read/taken_over/assignment rows never collide.
    statement = insert(Notification).values(rows)
    await session.execute(
        statement.on_duplicate_key_update(
            note_id=statement.inserted.note_id,
            by_agent_id=statement.inserted.by_agent_id,
            created_at=statement.inserted.created_at,
            merged_count=func.least(Notification.merged_count + 1, 65535),
        )
    )
    note_ids = {r["note_id"] for r in rows}
    users = {r["user_id"] for r in rows}
    saved = (
        await session.scalars(
            select(Notification)
            .where(
                Notification.note_id.in_(note_ids),
                Notification.user_id.in_(users),
                Notification.type.in_({r["type"] for r in rows}),
            )
            .execution_options(populate_existing=True)
        )
    ).all()
    return [
        (
            n.user_id,
            NotificationNewData(
                id=n.id,
                booking_key=key,
                display_key=to_display(key),
                by_agent_name=agent_name,
                created_at=n.created_at,
                type=n.type,
                merged_count=n.merged_count,
            ).model_dump(mode="json"),
        )
        for n in saved
    ]


class CollaborationService:
    def __init__(self, engine, settings, reads, ws):
        self.engine, self.settings, self.reads, self.ws = engine, settings, reads, ws
        self.directory = {}
        self.limiter = SearchLimiter(limit=120)

    def tx(self, **kwargs):
        return transaction(self.engine, self.settings, **kwargs)

    async def watch(self, key, user, enabled):
        parsed = parse(key, self.settings.station_code_pattern)
        if not isinstance(parsed, ParsedKey) or parsed.key != key:
            raise ApiException(ErrorCode.INVALID_BOOKING_KEY)

        def committed():
            self.reads._totals.clear()
            # Advance the count-cache generation too: an older concurrent read
            # cannot repopulate a newly invalidated watching total.
            self.reads.cache.invalidate(book.id)

        async with self.tx(after_commit=committed) as session:
            live = await session.scalar(select(User).where(User.id == user.id).with_for_update())
            AuthService.require_live_row(live, user)
            book = await session.scalar(
                select(Booking).where(Booking.booking_key == key).with_for_update()
            )
            if book is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            existing = await session.get(BookingWatcher, (book.id, user.id))
            if enabled and not existing:
                count = await session.scalar(
                    select(func.count())
                    .select_from(BookingWatcher)
                    .where(BookingWatcher.user_id == user.id)
                )
                if count >= 200:
                    raise ApiException(ErrorCode.WATCH_LIMIT_REACHED)
                session.add(BookingWatcher(booking_id=book.id, user_id=user.id))
            elif not enabled and existing:
                await session.delete(existing)
        return WatchState(watching=enabled)

    async def folder(self, session, key, *, lock=False):
        cw, station = folder_parts(key)
        query = select(BookingGroup).where(BookingGroup.cw_number == cw)
        if station:
            query = query.where(BookingGroup.station_code == station)
        query = query.order_by(BookingGroup.id).limit(2)
        if lock:
            query = query.with_for_update()
        groups = (await session.scalars(query)).all()
        if not groups:
            raise ApiException(ErrorCode.NOT_FOUND)
        if len(groups) > 1:
            raise ApiException(ErrorCode.VALIDATION_ERROR, message="Choose a station folder.")
        return groups[0]

    async def follow_folder(self, key, user, enabled=None):
        async with self.tx() as session:
            if enabled is not None:
                live = await session.scalar(
                    select(User).where(User.id == user.id).with_for_update()
                )
                AuthService.require_live_row(live, user)
            group = await self.folder(session, key, lock=enabled is not None)
            existing = await session.get(FolderFollower, (group.id, user.id))
            if enabled is None:
                return FolderFollowState(following=existing is not None)
            if enabled and existing is None:
                count = await session.scalar(
                    select(func.count())
                    .select_from(FolderFollower)
                    .where(FolderFollower.user_id == user.id)
                )
                if count >= 200:
                    raise ApiException(
                        ErrorCode.WATCH_LIMIT_REACHED, message="You can follow up to 200 folders."
                    )
                session.add(FolderFollower(group_id=group.id, user_id=user.id))
            elif not enabled and existing is not None:
                await session.delete(existing)
            if (enabled and existing is None) or (not enabled and existing is not None):
                record_audit(
                    session,
                    "folder_followed" if enabled else "folder_unfollowed",
                    actor_id=user.id,
                    entity_type="booking_group",
                    entity_id=str(group.id),
                )
        return FolderFollowState(following=enabled)

    async def following_folders(self, user, page, size):
        async with self.tx() as session:
            query = (
                select(FolderFollower.group_id)
                .join(BookingGroup, BookingGroup.id == FolderFollower.group_id)
                .where(FolderFollower.user_id == user.id)
            )
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            ids = list(
                (
                    await session.scalars(
                        query.order_by(
                            FolderFollower.created_at.desc(), FolderFollower.group_id.desc()
                        )
                        .offset((page - 1) * size)
                        .limit(size)
                    )
                ).all()
            )
            return Page(
                items=await folder_cards(session, ids, self.settings.stale_hours_default),
                total=total,
                page=page,
                size=size,
            )

    async def note_effects(self, session, book, note, live, body, previous_agent, now):
        """Called while the actor and booking are locked, in the note transaction."""
        assignment = None
        if body.assign_to is not None:
            existing = await session.scalar(
                select(BookingAssignment.id).where(
                    BookingAssignment.booking_id == book.id,
                    BookingAssignment.to_user_id == body.assign_to,
                    BookingAssignment.status == "open",
                )
            )
            if existing:
                raise ApiException(
                    ErrorCode.ASSIGNMENT_INVALID,
                    message="This user already has an open assignment for this booking.",
                )
            assignment = BookingAssignment(
                booking_id=book.id,
                note_id=note.id,
                from_user_id=live.id,
                to_user_id=body.assign_to,
                message=body.assign_message.strip() if body.assign_message else None,
                status="open",
                created_at=now,
            )
            session.add(assignment)
        completed = (
            await session.scalars(
                select(BookingAssignment)
                .where(
                    BookingAssignment.booking_id == book.id,
                    BookingAssignment.to_user_id == live.id,
                    BookingAssignment.status == "open",
                )
                .with_for_update()
            )
        ).all()
        for item in completed:
            item.status, item.resolved_at = "done", now
            record_audit(
                session,
                "assignment_completed",
                actor_id=live.id,
                entity_type="assignment",
                entity_id=str(item.id),
                meta={"via": "note"},
            )
        if (live.settings or {}).get("auto_watch_on_note", False):
            existing = await session.get(BookingWatcher, (book.id, live.id))
            if not existing:
                count = await session.scalar(
                    select(func.count())
                    .select_from(BookingWatcher)
                    .where(BookingWatcher.user_id == live.id)
                )
                # Auto-watch is best effort at the cap; a personal preference must
                # never prevent an otherwise valid operational note from committing.
                if count < 200:
                    session.add(BookingWatcher(booking_id=book.id, user_id=live.id, created_at=now))
        subscribers = (
            select(BookingWatcher.user_id.label("user_id"))
            .where(BookingWatcher.booking_id == book.id)
            .union(select(FolderFollower.user_id).where(FolderFollower.group_id == book.group_id))
            .subquery()
        )
        watchers = (
            await session.scalars(
                select(subscribers.c.user_id).where(subscribers.c.user_id != live.id)
            )
        ).all()
        recipient_types = {}
        if previous_agent and previous_agent != live.id:
            recipient_types[previous_agent] = "taken_over"
        for identifier in watchers:
            recipient_types.setdefault(identifier, "watch_update")
        rows = [
            dict(
                user_id=identifier,
                booking_id=book.id,
                type=kind,
                task_id=None,
                note_id=note.id,
                by_agent_id=live.id,
                created_at=now,
                merged_count=1,
            )
            for identifier, kind in recipient_types.items()
        ]
        # Assignment notifications are distinct workflow events, not watch duplicates.
        if assignment:
            await session.flush()
            record_audit(
                session,
                "assignment_created",
                actor_id=live.id,
                entity_type="assignment",
                entity_id=str(assignment.id),
                meta={"booking_key": book.booking_key, "to_user_id": assignment.to_user_id},
            )
            rows.append(
                dict(
                    user_id=assignment.to_user_id,
                    booking_id=book.id,
                    type="assigned",
                    task_id=None,
                    note_id=note.id,
                    by_agent_id=live.id,
                    created_at=now,
                    merged_count=1,
                )
            )
        for item in completed:
            rows.append(
                dict(
                    user_id=item.from_user_id,
                    booking_id=book.id,
                    type="assignment_done",
                    task_id=None,
                    note_id=note.id,
                    by_agent_id=live.id,
                    created_at=now,
                    merged_count=1,
                )
            )
        await session.flush()
        return await insert_notifications(session, rows, book.booking_key, live.full_name)

    async def lookup_users(self, query, limit):
        cache_key = (query.casefold().strip(), limit)
        cached = self.directory.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        async with self.tx() as session:
            statement = select(User.id, User.full_name).where(User.is_active.is_(True))
            if query.strip():
                statement = statement.where(
                    User.full_name.contains(query.strip(), autoescape=True)
                    | User.username.contains(query.strip(), autoescape=True)
                )
            rows = (
                await session.execute(statement.order_by(User.full_name, User.id).limit(limit))
            ).all()
        result = [AgentSummary(id=r.id, full_name=r.full_name) for r in rows]
        if len(self.directory) >= 256:
            self.directory.pop(next(iter(self.directory)))
        self.directory[cache_key] = (time.monotonic() + 10, result)
        return result

    async def assignments(self, user, view, status, page, size):
        origin, target = aliased(User), aliased(User)
        condition = (
            BookingAssignment.to_user_id if view == "to_me" else BookingAssignment.from_user_id
        ) == user.id
        if status:
            condition &= BookingAssignment.status == status
        async with self.tx() as session:
            total = await session.scalar(
                select(func.count()).select_from(BookingAssignment).where(condition)
            )
            rows = (
                await session.execute(
                    select(
                        BookingAssignment,
                        Booking.booking_key,
                        origin.full_name.label("from_name"),
                        target.full_name.label("to_name"),
                    )
                    .join(Booking, Booking.id == BookingAssignment.booking_id)
                    .join(origin, origin.id == BookingAssignment.from_user_id)
                    .join(target, target.id == BookingAssignment.to_user_id)
                    .where(condition)
                    .order_by(BookingAssignment.created_at.desc(), BookingAssignment.id.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ).all()
            return Page(
                items=[
                    self.assignment_dto(r.BookingAssignment, r.booking_key, r.from_name, r.to_name)
                    for r in rows
                ],
                total=total,
                page=page,
                size=size,
            )

    @staticmethod
    def assignment_dto(row, key, origin, target):
        return AssignmentItem(
            id=row.id,
            booking_key=key,
            display_key=to_display(key),
            note_id=row.note_id,
            from_user={"id": row.from_user_id, "full_name": origin},
            to_user={"id": row.to_user_id, "full_name": target},
            message=row.message,
            status=row.status,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            decline_reason=row.decline_reason,
        )

    async def resolve(self, identifier, user, reason, context):
        events = []

        def committed():
            for recipient, payload in events:
                self.ws.spawn(self.ws.send_user(recipient, "notification.new", payload))

        async with self.tx(after_commit=committed) as session:
            live = await session.scalar(select(User).where(User.id == user.id).with_for_update())
            AuthService.require_live_row(live, user)
            booking_id = await session.scalar(
                select(BookingAssignment.booking_id).where(
                    BookingAssignment.id == identifier, BookingAssignment.to_user_id == user.id
                )
            )
            if booking_id is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            book = await session.scalar(
                select(Booking).where(Booking.id == booking_id).with_for_update()
            )
            row = await session.scalar(
                select(BookingAssignment)
                .where(BookingAssignment.id == identifier)
                .with_for_update()
            )
            desired = "declined" if reason is not None else "done"
            if row.status != "open" and row.status != desired:
                raise ApiException(
                    ErrorCode.ASSIGNMENT_INVALID, message="This assignment is already resolved."
                )
            if row.status == "open":
                row.status, row.resolved_at, row.decline_reason = desired, utcnow(), reason
                record_audit(
                    session,
                    "assignment_" + ("declined" if reason is not None else "completed"),
                    actor_id=user.id,
                    entity_type="assignment",
                    entity_id=str(row.id),
                    context=context,
                )
                if reason is None:
                    events = await insert_notifications(
                        session,
                        [
                            dict(
                                user_id=row.from_user_id,
                                booking_id=book.id,
                                type="assignment_done",
                                note_id=row.note_id,
                                task_id=None,
                                by_agent_id=user.id,
                                created_at=row.resolved_at,
                                merged_count=1,
                            )
                        ],
                        book.booking_key,
                        live.full_name,
                    )
            origin = await session.get(User, row.from_user_id)
            return self.assignment_dto(row, book.booking_key, origin.full_name, live.full_name)
