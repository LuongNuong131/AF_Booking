from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.exc import IntegrityError

from app.core.deps import get_current_user, require_roles
from app.core.errors import ApiException
from app.core.timeouts import DeadlineRoute, timeout
from app.schemas.bookings import MutationResult
from app.schemas.contracts import ErrorCode
from app.schemas.operations import (
    DailyReportDTO,
    NoteSearchPage,
    PushPublicKey,
    PushSubscribe,
    PushUnsubscribe,
    SystemHealth,
)
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["operations"])
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
AdminDep = Annotated[CurrentUser, Depends(require_roles("admin"))]
ReportDep = Annotated[CurrentUser, Depends(require_roles("admin", "qc"))]


@router.get("/admin/system/health", response_model=SystemHealth)
async def system_health(request: Request, user: AdminDep):
    state = request.app.state
    return state.telemetry.snapshot(
        state.engine,
        state.ws_manager,
        state.scheduler,
        state.settings.app_version,
        state.key_index,
        state.snapshot_cache,
    )


@router.get("/reports/daily", response_model=DailyReportDTO)
@timeout("export_timeout_seconds")
async def daily(request: Request, user: ReportDep, date: date | None = None):
    day = date or datetime.now(ZoneInfo(request.app.state.settings.business_timezone)).date()
    compressed = "gzip" in request.headers.get("accept-encoding", "")
    body = await request.app.state.daily_reports.wire(day, compressed)
    headers = {"Vary": "Accept-Encoding"}
    if compressed:
        headers["Content-Encoding"] = "gzip"
    return Response(body, media_type="application/json", headers=headers)


@router.get("/reports/daily/export")
@timeout("export_timeout_seconds")
async def daily_export(request: Request, user: ReportDep, date: date):
    return await request.app.state.daily_reports.export(
        date, request, user, AuditContext.from_request(request)
    )


@router.get("/search/notes", response_model=NoteSearchPage)
async def search_notes(
    request: Request,
    user: UserDep,
    q: Annotated[str, Query(min_length=3, max_length=100)],
    date_from: date | None = None,
    date_to: date | None = None,
    agent_id: Annotated[int | None, Query(gt=0)] = None,
    status_code: Annotated[str | None, Query(max_length=40)] = None,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    service = request.app.state.note_search
    service.limiter.check(user.id)
    return await service.search(q, date_from, date_to, agent_id, status_code, page, size)


@router.get("/push/public-key", response_model=PushPublicKey)
async def push_key(request: Request, user: UserDep):
    service = request.app.state.push
    return PushPublicKey(
        enabled=service.configured,
        public_key=service.settings.vapid_public_key if service.configured else None,
    )


@router.post("/push/subscribe", response_model=MutationResult)
async def subscribe(body: PushSubscribe, request: Request, user: UserDep):
    request.app.state.push.limiter.check(user.id)
    try:
        await request.app.state.push.subscribe(body, user, request.headers.get("user-agent"))
    except IntegrityError:
        # Two accounts cannot claim an endpoint through simultaneous insertions.
        raise ApiException(ErrorCode.NOT_FOUND) from None
    return MutationResult()


@router.delete("/push/subscribe", response_model=MutationResult)
async def unsubscribe(body: PushUnsubscribe, request: Request, user: UserDep):
    request.app.state.push.limiter.check(user.id)
    await request.app.state.push.unsubscribe(body.endpoint, user)
    return MutationResult()
