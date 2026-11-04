from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, update

from app.core.deps import get_current_user
from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import Booking, Notification, User
from app.schemas.bookings import MutationResult, NotificationItem, NotificationList
from app.schemas.contracts import ErrorCode
from app.services.session_cache import CurrentUser
from app.utils.booking_key import to_display

router = APIRouter(tags=["notifications"])
UserDep = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("/notifications", response_model=NotificationList)
async def notifications(
    request: Request, user: UserDep, limit: Annotated[int, Query(ge=1, le=100)] = 20
):
    async with transaction(request.app.state.engine, request.app.state.settings) as session:
        rows = (
            await session.execute(
                select(
                    Notification.id,
                    Notification.type,
                    Notification.merged_count,
                    Notification.note_id,
                    Notification.task_id,
                    Notification.created_at,
                    Notification.read_at,
                    Booking.booking_key,
                    User.id.label("agent_id"),
                    User.full_name,
                )
                .join(Booking, Booking.id == Notification.booking_id)
                .outerjoin(User, User.id == Notification.by_agent_id)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(limit)
            )
        ).all()
        count = await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
    return NotificationList(
        unread_count=count,
        items=[
            NotificationItem(
                id=row.id,
                type=row.type,
                merged_count=row.merged_count,
                booking_key=row.booking_key,
                display_key=to_display(row.booking_key),
                note_id=row.note_id,
                task_id=row.task_id,
                created_at=row.created_at,
                read_at=row.read_at,
                by_agent={"id": row.agent_id, "full_name": row.full_name} if row.agent_id else None,
            )
            for row in rows
        ],
    )


@router.post("/notifications/read-all", response_model=MutationResult)
async def read_all(request: Request, user: UserDep):
    async with transaction(request.app.state.engine, request.app.state.settings) as session:
        await session.execute(
            update(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
            .values(read_at=datetime.now(UTC))
        )
    return MutationResult()


@router.post("/notifications/{id}/read", response_model=MutationResult)
async def read_notification(id: int, request: Request, user: UserDep):
    async with transaction(request.app.state.engine, request.app.state.settings) as session:
        row = await session.scalar(
            select(Notification)
            .where(Notification.id == id, Notification.user_id == user.id)
            .with_for_update()
        )
        if row is None:
            raise ApiException(ErrorCode.NOT_FOUND)
        if row.read_at is None:
            row.read_at = datetime.now(UTC)
    return MutationResult()
