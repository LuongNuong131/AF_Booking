from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.core.bounds import Identifier
from app.core.deps import get_current_user, require_roles
from app.core.timeouts import DeadlineRoute, timeout
from app.schemas.contracts import Page
from app.schemas.folder_assignments import (
    AssignmentImport,
    AssignmentImportResult,
    FolderAssignmentItem,
    FolderAssignmentPatch,
)
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["folder assignments"])
Actor = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("/folder-assignments", response_model=Page[FolderAssignmentItem])
async def listing(
    request: Request,
    user: Actor,
    scope: Literal["mine", "all", "unassigned", "review"] = "mine",
    agent_id: Annotated[int | None, Query(gt=0)] = None,
    region: Annotated[str | None, Query(max_length=100)] = None,
    q: Annotated[str, Query(max_length=100)] = "",
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await request.app.state.folder_assignments.listing(
        user, scope, agent_id, region, q, page, size
    )


@router.get("/folder-assignments/options")
async def options(request: Request, user: Actor):
    return await request.app.state.folder_assignments.options()


@router.patch("/folder-assignments/{id}")
async def patch(id: Identifier, body: FolderAssignmentPatch, request: Request, user: Actor):
    return await request.app.state.folder_assignments.patch(
        id, body, user, AuditContext.from_request(request)
    )


@router.post("/admin/folder-assignments/import", response_model=AssignmentImportResult)
@timeout(60)
async def import_workbook(
    body: AssignmentImport,
    request: Request,
    user: Annotated[CurrentUser, Depends(require_roles("admin"))],
):
    return await request.app.state.folder_assignments.import_workbook(
        body, user, AuditContext.from_request(request)
    )
