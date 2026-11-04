from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.core.bounds import Identifier, KeyPath
from app.core.deps import get_current_user
from app.core.timeouts import DeadlineRoute
from app.models import User
from app.schemas.auth import PublicUser
from app.schemas.contracts import Page, Task
from app.schemas.tasks import DueTasks, ProfilePatch, TaskCreate, TaskEdit
from app.services.audit import AuditContext, record_audit
from app.services.auth import AuthService
from app.services.session_cache import CurrentUser
from app.services.tasks import effective_settings

router = APIRouter(route_class=DeadlineRoute, tags=["tasks"])
Actor = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("/tasks/due", response_model=DueTasks)
async def due(request: Request, user: Actor):
    page = await request.app.state.tasks.listing(user.id, "due", size=100)
    return DueTasks(items=page.items, total=page.total)


@router.get("/tasks", response_model=Page[Task])
async def tasks(
    request: Request,
    user: Actor,
    view: Literal["pending", "due", "done"] = "pending",
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 10,
):
    return await request.app.state.tasks.listing(user.id, view, page, size)


@router.get("/bookings/{key}/tasks", response_model=list[Task])
async def booking_tasks(key: KeyPath, request: Request, user: Actor):
    return (await request.app.state.tasks.listing(user.id, key=key, size=5)).items


@router.post("/bookings/{key}/tasks", response_model=Task)
async def create(key: KeyPath, body: TaskCreate, request: Request, user: Actor):
    return await request.app.state.tasks.create(key, body, user, AuditContext.from_request(request))


@router.patch("/tasks/{task_id}", response_model=Task)
async def edit(task_id: Identifier, body: TaskEdit, request: Request, user: Actor):
    return await request.app.state.tasks.change(
        task_id, "edit", body, user, AuditContext.from_request(request)
    )


@router.post("/tasks/{task_id}/complete", response_model=Task)
async def complete(task_id: Identifier, request: Request, user: Actor):
    return await request.app.state.tasks.change(
        task_id, "complete", None, user, AuditContext.from_request(request)
    )


@router.post("/tasks/{task_id}/snooze", response_model=Task)
async def snooze(task_id: Identifier, body: TaskEdit, request: Request, user: Actor):
    return await request.app.state.tasks.change(
        task_id, "snooze", body, user, AuditContext.from_request(request)
    )


@router.delete("/tasks/{task_id}", response_model=Task)
async def cancel(task_id: Identifier, request: Request, user: Actor):
    return await request.app.state.tasks.change(
        task_id, "cancel", None, user, AuditContext.from_request(request)
    )


@router.patch("/profile", response_model=PublicUser)
async def profile(body: ProfilePatch, request: Request, user: Actor):
    auth = request.app.state.auth
    async with auth.mutation(user.id) as session:
        live = AuthService.require_live_row(
            await session.scalar(select(User).where(User.id == user.id).with_for_update()), user
        )
        values = effective_settings(live.settings, request.app.state.settings.business_timezone)
        if body.settings:
            values.update(body.settings.model_dump(exclude_unset=True, exclude_none=True))
        live.settings = values
        if body.full_name is not None:
            live.full_name = body.full_name
        record_audit(
            session,
            "profile_updated",
            actor_id=user.id,
            target_user_id=user.id,
            context=AuditContext.from_request(request),
            meta={"fields": list(body.model_fields_set)},
        )
        result = CurrentUser.from_model(live).public()
    if body.full_name is not None:
        request.app.state.admin.catalog("users")
    return result
