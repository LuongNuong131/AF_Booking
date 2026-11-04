from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from app.core.bounds import KeyPath
from app.core.deps import get_current_user, require_roles
from app.core.timeouts import DeadlineRoute, timeout
from app.schemas.contracts import FolderCard, Page
from app.schemas.folders import (
    FolderDetail,
    SearchResponse,
    StationInfo,
    StationOption,
    StationPatch,
)
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["folders", "search", "stations"])
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
PageNumber = Annotated[int, Query(ge=1, le=100000)]
SearchText = Annotated[str, Query(max_length=100)]


@router.get("/search", response_model=SearchResponse)
@timeout("lookup_timeout_seconds")
async def search(
    request: Request,
    user: UserDep,
    q: SearchText = "",
    page: PageNumber = 1,
    size: Annotated[int, Query(ge=1, le=20)] = 20,
):
    request.app.state.search_limiter.check(user.id)
    return await request.app.state.folders.search(q, page=page, size=size)


@router.get("/folders", response_model=Page[FolderCard])
async def folders(
    request: Request,
    user: UserDep,
    page: PageNumber = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    station_code: Annotated[str | None, Query(max_length=4)] = None,
    supplier_type: Literal["hotel", "transportation"] | None = None,
    q: SearchText = "",
):
    return await request.app.state.folders.listing(
        query=q,
        page=page,
        size=size,
        station_code=station_code.strip().upper() if station_code else None,
        supplier_type=supplier_type,
    )


@router.get("/folders/{cw}", response_model=FolderDetail)
async def folder(cw: KeyPath, request: Request, user: UserDep):
    return await request.app.state.folders.detail(cw)


@router.get("/stations", response_model=list[StationOption])
async def stations(request: Request, response: Response, user: UserDep, q: SearchText = ""):
    items, etag = await request.app.state.stations.autocomplete(q)
    cache_seconds = int(request.app.state.settings.station_cache_ttl_seconds)
    headers = {
        "ETag": etag,
        "Cache-Control": f"private, max-age={cache_seconds}",
        "Vary": "Authorization",
    }
    provided = request.headers.get("if-none-match", "")
    validators = {v.strip().removeprefix("W/") for v in provided.split(",")}
    if "*" in validators or etag in validators:
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return items


@router.patch("/admin/stations/{code}", response_model=StationInfo)
async def rename_station(
    code: KeyPath,
    body: StationPatch,
    request: Request,
    user: Annotated[CurrentUser, Depends(require_roles("admin"))],
):
    return await request.app.state.stations.rename(
        code, body, user, AuditContext.from_request(request)
    )
