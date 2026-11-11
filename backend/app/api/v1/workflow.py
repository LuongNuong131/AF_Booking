from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request

from app.core.bounds import Identifier, KeyPath
from app.core.deps import get_current_user, require_roles
from app.core.timeouts import DeadlineRoute, timeout
from app.schemas.contracts import Page
from app.schemas.workflow import (
    PersonalDailyReport,
    TranslationConfig,
    TranslationRequest,
    TranslationResult,
    WorkTaskBundle,
    WorkTaskCreate,
    WorkTaskHandle,
    WorkTaskItem,
    WorkTaskMerge,
)
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["workflows"])
Actor = Annotated[CurrentUser, Depends(get_current_user)]
Supervisor = Annotated[CurrentUser, Depends(require_roles("qc", "admin"))]


@router.get("/reports/mine/daily", response_model=PersonalDailyReport)
async def personal_daily(
    request: Request,
    user: Actor,
    date: date | None = None,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    day = date or datetime.now(ZoneInfo(request.app.state.settings.business_timezone)).date()
    return await request.app.state.personal_reports.get(day, user, page, size)


@router.get("/reports/mine/daily/export")
@timeout("export_timeout_seconds")
async def personal_export(request: Request, user: Actor, date: date):
    return await request.app.state.personal_reports.export(
        date, user, AuditContext.from_request(request)
    )


@router.get("/work-tasks", response_model=Page[WorkTaskItem])
async def work_tasks(
    request: Request,
    user: Actor,
    status: Literal["pending", "handled", "all"] = "pending",
    date: date | None = None,
    booking_key: Annotated[str | None, Query(max_length=32)] = None,
    creator_id: Annotated[int | None, Query(gt=0)] = None,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await request.app.state.work_tasks.listing(
        user, status, date, booking_key, creator_id, page, size
    )


@router.get("/work-tasks/export")
@timeout("export_timeout_seconds")
async def work_tasks_export(
    request: Request,
    user: Supervisor,
    status: Literal["pending", "handled", "all"] = "pending",
    date: date | None = None,
    booking_key: Annotated[str | None, Query(max_length=32)] = None,
    creator_id: Annotated[int | None, Query(gt=0)] = None,
):
    return await request.app.state.work_tasks.export(
        user, status, date, booking_key, creator_id, AuditContext.from_request(request)
    )


@router.post("/bookings/{key}/work-tasks", response_model=WorkTaskItem, status_code=201)
async def create_work_task(key: KeyPath, body: WorkTaskCreate, request: Request, user: Actor):
    return await request.app.state.work_tasks.create(
        key, body, user, AuditContext.from_request(request)
    )


@router.post("/work-tasks/{id}/handle", response_model=WorkTaskItem)
async def handle_work_task(
    id: Identifier, body: WorkTaskHandle, request: Request, user: Supervisor
):
    return await request.app.state.work_tasks.handle(
        id, body, user, AuditContext.from_request(request)
    )


@router.get("/work-tasks/translation/config", response_model=TranslationConfig)
async def translation_config(request: Request, user: Actor):
    return TranslationConfig(enabled=bool(request.app.state.settings.google_translate_api_key))


@router.post("/work-tasks/translate", response_model=TranslationResult)
@timeout(15)
async def translate_ticket(body: TranslationRequest, request: Request, user: Actor):
    from app.services.ticket_translation import translate

    return TranslationResult(text=await translate(body.text, request.app.state.settings))


@router.post("/work-tasks/merge", response_model=WorkTaskBundle)
async def merge_work_tasks(body: WorkTaskMerge, request: Request, user: Supervisor):
    return await request.app.state.work_tasks.merge(body, user)


@router.get("/work-tasks/{id}", response_model=WorkTaskItem)
async def work_task_detail(id: Identifier, request: Request, user: Actor):
    return await request.app.state.work_tasks.detail(id, user)
