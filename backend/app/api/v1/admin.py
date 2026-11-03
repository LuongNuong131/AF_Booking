from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import get_current_user, require_roles
from app.core.errors import ApiException
from app.core.timeouts import DeadlineRoute, timeout
from app.schemas.admin import (
    AdminNote,
    AdminStatus,
    AdminUser,
    AuditEntry,
    DeleteNote,
    PerformanceReport,
    ProfileStats,
    ResetPassword,
    StatusCreate,
    StatusUpdate,
    UserCreate,
    UserUpdate,
)
from app.schemas.bookings import BookingItem
from app.schemas.contracts import ErrorCode, Page
from app.schemas.folders import StationOption
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["administration"])
Admin = Annotated[CurrentUser, Depends(require_roles("admin"))]
QC = Annotated[CurrentUser, Depends(require_roles("admin", "qc"))]
Actor = Annotated[CurrentUser, Depends(get_current_user)]
PageNumber = Annotated[int, Query(ge=1, le=100000)]
Size = Annotated[int, Query(ge=1, le=100)]
Search = Annotated[str, Query(max_length=100)]


@router.get("/admin/users", response_model=Page[AdminUser])
async def users(
    request: Request, user: Admin, q: Search = "", page: PageNumber = 1, size: Size = 20
):
    return await request.app.state.admin.users(q, page, size)


@router.post("/admin/users", response_model=AdminUser)
async def create_user(body: UserCreate, request: Request, user: Admin):
    return await request.app.state.admin.create_user(body, user, AuditContext.from_request(request))


@router.patch("/admin/users/{identifier}", response_model=AdminUser)
async def update_user(identifier: int, body: UserUpdate, request: Request, user: Admin):
    return await request.app.state.admin.update_user(
        identifier, body, user, AuditContext.from_request(request)
    )


@router.post("/admin/users/{identifier}/reset-password", response_model=AdminUser)
async def reset_password(identifier: int, body: ResetPassword, request: Request, user: Admin):
    return await request.app.state.admin.update_user(
        identifier,
        None,
        user,
        AuditContext.from_request(request),
        body.temporary_password.get_secret_value(),
    )


@router.post("/admin/users/{identifier}/kick")
async def kick(identifier: int, request: Request, user: Admin):
    kicked = await request.app.state.auth.kick_session(
        identifier, actor_id=user.id, caller=user, context=AuditContext.from_request(request)
    )
    return {"kicked": kicked}


@router.get("/admin/audit", response_model=Page[AuditEntry])
async def audit(
    request: Request,
    user: Admin,
    page: PageNumber = 1,
    size: Size = 20,
    user_id: int | None = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    entity: Annotated[str | None, Query(max_length=40)] = None,
    entity_id: Annotated[str | None, Query(max_length=60)] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    if any(value is not None and value.tzinfo is None for value in [date_from, date_to]) or (
        date_from and date_to and date_from > date_to
    ):
        raise ApiException(
            ErrorCode.VALIDATION_ERROR, message="Use an ordered range of timezone-aware timestamps."
        )
    return await request.app.state.admin.audit(
        page, size, user_id, action, date_from, date_to, entity, entity_id
    )


@router.get("/admin/bookings/{key}/notes", response_model=Page[AdminNote])
async def history(key: str, request: Request, user: Admin, page: PageNumber = 1, size: Size = 20):
    return await request.app.state.admin.notes(page, size, key=key)


@router.get("/admin/trash", response_model=Page[AdminNote])
async def trash(
    request: Request, user: Admin, page: PageNumber = 1, size: Size = 20, q: Search = ""
):
    return await request.app.state.admin.notes(page, size, trash=True, q=q)


@router.delete("/admin/notes/{identifier}", response_model=BookingItem)
async def delete_note(identifier: int, body: DeleteNote, request: Request, user: Admin):
    return await request.app.state.admin.change_note(
        identifier, False, body.reason, user, AuditContext.from_request(request)
    )


@router.post("/admin/notes/{identifier}/restore", response_model=BookingItem)
async def restore(identifier: int, request: Request, user: Admin):
    return await request.app.state.admin.change_note(
        identifier, True, None, user, AuditContext.from_request(request)
    )


@router.get("/admin/statuses", response_model=list[AdminStatus])
async def statuses(request: Request, user: Admin):
    return await request.app.state.admin.statuses()


@router.get("/admin/stations", response_model=Page[StationOption])
async def stations(
    request: Request, user: Admin, q: Search = "", page: PageNumber = 1, size: Size = 20
):
    return await request.app.state.admin.stations(q, page, size)


@router.post("/admin/statuses", response_model=AdminStatus)
async def create_status(body: StatusCreate, request: Request, user: Admin):
    return await request.app.state.admin.save_status(body, user, AuditContext.from_request(request))


@router.patch("/admin/statuses", response_model=AdminStatus)
async def update_status(body: StatusUpdate, request: Request, user: Admin):
    return await request.app.state.admin.save_status(body, user, AuditContext.from_request(request))


@router.get("/profile/stats", response_model=ProfileStats)
async def profile_stats(request: Request, user: Actor):
    return await request.app.state.admin.profile_stats(user)


@router.get("/reports/performance", response_model=PerformanceReport)
async def performance(
    request: Request,
    user: QC,
    period: Literal["day", "week", "month"] = "day",
    date_from: date | None = None,
    date_to: date | None = None,
):
    return await request.app.state.reports.performance(period, date_from, date_to)


@router.get("/export/daily")
@timeout("export_timeout_seconds")
async def export(
    request: Request,
    user: QC,
    date: date | None = None,
    format: Literal["xlsx", "csv"] = "xlsx",
    agent_id: int | None = None,
    status_code: Annotated[str | None, Query(max_length=40)] = None,
):
    day = date or datetime.now(ZoneInfo(request.app.state.settings.business_timezone)).date()
    return await request.app.state.exports.daily(
        day, format, agent_id, status_code, request, user, AuditContext.from_request(request)
    )
