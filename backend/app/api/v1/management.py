from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.bounds import Identifier
from app.core.deps import require_roles
from app.core.timeouts import DeadlineRoute, timeout
from app.schemas.contracts import JsonValue, Page
from app.schemas.management import (
    DataBulkDelete,
    DataDelete,
    DataMutation,
    DataResource,
    PurgePreview,
    PurgeRequest,
    TrashItem,
)
from app.services.audit import AuditContext
from app.services.management import SPECS
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["data management"])
Admin = Annotated[CurrentUser, Depends(require_roles("admin"))]


@router.get("/admin/data/resources", response_model=list[DataResource])
async def resources(user: Admin):
    return [DataResource(name=name, fields=entry[2]) for name, entry in SPECS.items()]


@router.get("/admin/data/trash", response_model=Page[TrashItem])
async def trash(
    request: Request,
    user: Admin,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    return await request.app.state.management.trash(q, page, size)


@router.post("/admin/data/trash/preview", response_model=PurgePreview)
@timeout("export_timeout_seconds")
async def preview(ids: list[int], request: Request, user: Admin):
    return await request.app.state.management.preview(ids, user)


@router.post("/admin/data/trash/purge")
@timeout("export_timeout_seconds")
async def purge(body: PurgeRequest, request: Request, user: Admin):
    return await request.app.state.management.purge(body, user, AuditContext.from_request(request))


@router.post("/admin/data/trash/{id}/restore")
async def restore(id: Identifier, request: Request, user: Admin):
    return await request.app.state.management.restore(id, user, AuditContext.from_request(request))


@router.get("/admin/data/{resource}", response_model=Page[dict[str, JsonValue]])
async def rows(
    resource: str,
    request: Request,
    user: Admin,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    return await request.app.state.management.listing(resource, q, page, size)


@router.post("/admin/data/{resource}", response_model=dict[str, JsonValue])
async def create(resource: str, body: DataMutation, request: Request, user: Admin):
    return await request.app.state.management.save(
        resource, None, body, user, AuditContext.from_request(request)
    )


@router.patch("/admin/data/{resource}/{id}", response_model=dict[str, JsonValue])
async def update(resource: str, id: str, body: DataMutation, request: Request, user: Admin):
    return await request.app.state.management.save(
        resource, id, body, user, AuditContext.from_request(request)
    )


@router.delete("/admin/data/{resource}/{id}")
async def remove(resource: str, id: str, body: DataDelete, request: Request, user: Admin):
    return await request.app.state.management.remove(
        resource, id, body.reason, user, AuditContext.from_request(request)
    )


@router.post("/admin/data/{resource}/bulk-delete")
@timeout("export_timeout_seconds")
async def bulk_remove(resource: str, body: DataBulkDelete, request: Request, user: Admin):
    return await request.app.state.management.bulk_remove(
        resource, body.ids, body.reason, user, AuditContext.from_request(request)
    )
