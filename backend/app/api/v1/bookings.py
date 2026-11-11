import hashlib
from typing import Annotated, Literal

import orjson
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import AwareDatetime
from sqlalchemy import select

from app.core.bounds import KeyPath
from app.core.deps import get_current_user
from app.core.errors import ApiException
from app.core.timeouts import DeadlineRoute, timeout
from app.core.unit_of_work import transaction
from app.models import Status
from app.schemas.bookings import (
    BookingClassification,
    BookingCreateRequest,
    BookingItem,
    BookingLookup,
    FolderPatch,
    GroupInfo,
    NoteSaveResponse,
)
from app.schemas.contracts import AgentSummary, CursorPage, ErrorCode, Note, NoteSaveRequest, Page
from app.schemas.contracts import Status as StatusDTO
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["bookings"])
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
PageNumber = Annotated[int, Query(ge=1, le=100000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


# Static routes must precede /bookings/{key}.
@router.post("/bookings", response_model=BookingItem, status_code=201)
@timeout("note_save_timeout_seconds")
async def create_booking(body: BookingCreateRequest, request: Request, user: UserDep):
    return await request.app.state.booking_writes.create(
        body, user, AuditContext.from_request(request)
    )


@router.get("/bookings/lookup", response_model=BookingLookup)
@timeout("lookup_timeout_seconds")
async def lookup(
    request: Request, response: Response, user: UserDep, key: Annotated[str, Query(max_length=100)]
):
    request.app.state.search_limiter.check(user.id)
    result, timing = await request.app.state.bookings.lookup(key, user.id)
    response.headers["Server-Timing"] = timing
    return result


@router.get("/bookings/mine", response_model=Page[BookingItem])
async def mine(request: Request, user: UserDep, page: PageNumber = 1, size: PageSize = 10):
    return await request.app.state.bookings.listing(user.id, page=page, size=size, mine=True)


@router.get("/bookings/stale", response_model=Page[BookingItem])
async def stale(
    request: Request,
    user: UserDep,
    scope: Literal["mine", "all"] = "mine",
    page: PageNumber = 1,
    size: PageSize = 20,
):
    return await request.app.state.bookings.listing(
        user.id, page=page, size=size, mine=scope == "mine", stale_only=True
    )


@router.get("/bookings", response_model=Page[BookingItem])
async def listing(
    request: Request,
    user: UserDep,
    page: PageNumber = 1,
    size: PageSize = 20,
    q: Annotated[str | None, Query(max_length=128)] = None,
    cw_number: Annotated[str | None, Query(max_length=12)] = None,
    station_code: Annotated[str | None, Query(max_length=4)] = None,
    period: Annotated[str | None, Query(pattern=r"^[0-9]{2}(0[1-9]|1[0-2])$")] = None,
    supplier: Annotated[str | None, Query(max_length=255)] = None,
    supplier_type: Literal["hotel", "transportation", "unclassified"] | None = None,
    status_code: Annotated[str | None, Query(max_length=40)] = None,
    agent_id: Annotated[int | None, Query(gt=0)] = None,
    is_done: bool | None = None,
    stale: bool | None = None,
    invoice_state: Literal["unknown", "has_invoice", "no_invoice"] | None = None,
    invoice: Annotated[str | None, Query(max_length=40)] = None,
    date_from: AwareDatetime | None = None,
    date_to: AwareDatetime | None = None,
    sort: Literal["updated_at_desc", "updated_at_asc"] = "updated_at_desc",
):
    if date_from and date_to and date_from > date_to:
        raise ApiException(ErrorCode.VALIDATION_ERROR)
    return await request.app.state.bookings.listing(
        user.id,
        page=page,
        size=size,
        q=q,
        cw_number=cw_number,
        station_code=station_code,
        period=period,
        supplier=supplier,
        supplier_type=supplier_type,
        status_code=status_code,
        agent_id=agent_id,
        is_done=is_done,
        stale=stale,
        invoice_state=invoice_state,
        invoice=invoice,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
    )


@router.get("/bookings/{key}", response_model=BookingLookup)
async def detail(key: KeyPath, request: Request, response: Response, user: UserDep):
    request.app.state.search_limiter.check(user.id)
    result, timing = await request.app.state.bookings.lookup(key, user.id)
    if not result.exists:
        raise ApiException(ErrorCode.NOT_FOUND)
    response.headers["Server-Timing"] = timing
    return result


@router.get("/bookings/{key}/notes", response_model=CursorPage[Note])
async def notes(
    key: KeyPath,
    request: Request,
    user: UserDep,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await request.app.state.bookings.history(key, cursor, limit)


@router.post("/bookings/{key}/notes", response_model=NoteSaveResponse)
@timeout("note_save_timeout_seconds")
async def save_note(key: KeyPath, body: NoteSaveRequest, request: Request, user: UserDep):
    return await request.app.state.booking_writes.save(
        key, body, user, AuditContext.from_request(request)
    )


@router.patch("/folders/{cw}", response_model=GroupInfo)
async def patch_folder(
    cw: KeyPath,
    body: FolderPatch,
    request: Request,
    user: UserDep,
):
    return await request.app.state.booking_writes.patch_folder(
        cw, body, user, AuditContext.from_request(request)
    )


@router.get("/statuses", response_model=list[StatusDTO])
async def statuses(request: Request, response: Response, user: UserDep):
    async with transaction(request.app.state.engine, request.app.state.settings) as session:
        rows = (
            await session.scalars(
                select(Status)
                .where(Status.is_active.is_(True), Status.deleted_at.is_(None))
                .order_by(Status.sort_order, Status.id)
            )
        ).all()
        result = [StatusDTO.model_validate(row, from_attributes=True) for row in rows]
        etag = (
            '"'
            + hashlib.sha256(orjson.dumps([s.model_dump(mode="json") for s in result])).hexdigest()
            + '"'
        )
        headers = {"ETag": etag, "Cache-Control": "private, max-age=60", "Vary": "Authorization"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return result


@router.get("/users/lookup", response_model=list[AgentSummary])
async def user_lookup(
    request: Request,
    user: UserDep,
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    request.app.state.collaboration.limiter.check(user.id)
    return await request.app.state.collaboration.lookup_users(q, limit)


@router.patch("/bookings/{key}/classification", response_model=BookingItem)
async def classify_booking(
    key: KeyPath, body: BookingClassification, request: Request, user: UserDep
):
    return await request.app.state.booking_writes.classify(
        key, body, user, AuditContext.from_request(request)
    )
