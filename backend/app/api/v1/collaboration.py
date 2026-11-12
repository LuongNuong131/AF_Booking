from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.core.bounds import Identifier, KeyPath
from app.core.deps import get_current_user
from app.core.timeouts import DeadlineRoute
from app.schemas.bookings import BookingItem
from app.schemas.collaboration import (
    AssignmentDecline,
    AssignmentItem,
    FolderFollowState,
    WatchState,
)
from app.schemas.contracts import FolderCard, Page
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["collaboration"])
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
PageNumber = Annotated[int, Query(ge=1, le=100000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.put("/bookings/{key}/watch", response_model=WatchState)
async def watch(key: KeyPath, request: Request, user: UserDep):
    return await request.app.state.collaboration.watch(key, user, True)


@router.delete("/bookings/{key}/watch", response_model=WatchState)
async def unwatch(key: KeyPath, request: Request, user: UserDep):
    return await request.app.state.collaboration.watch(key, user, False)


@router.get("/watching", response_model=Page[BookingItem])
async def watching(request: Request, user: UserDep, page: PageNumber = 1, size: PageSize = 10):
    return await request.app.state.bookings.listing(user.id, page=page, size=size, watching=True)


@router.get("/assignments", response_model=Page[AssignmentItem])
async def assignments(
    request: Request,
    user: UserDep,
    view: Literal["to_me", "from_me"] = "to_me",
    status: Literal["open", "done", "declined"] | None = "open",
    page: PageNumber = 1,
    size: PageSize = 10,
):
    return await request.app.state.collaboration.assignments(user, view, status, page, size)


@router.post("/assignments/{id}/complete", response_model=AssignmentItem)
async def complete(id: Identifier, request: Request, user: UserDep):
    return await request.app.state.collaboration.resolve(
        id, user, None, AuditContext.from_request(request)
    )


@router.post("/assignments/{id}/decline", response_model=AssignmentItem)
async def decline(id: Identifier, body: AssignmentDecline, request: Request, user: UserDep):
    return await request.app.state.collaboration.resolve(
        id, user, body.reason, AuditContext.from_request(request)
    )


@router.get("/folders/{cw}/follow", response_model=FolderFollowState)
async def folder_follow_state(cw: KeyPath, request: Request, user: UserDep):
    return await request.app.state.collaboration.follow_folder(cw, user)


@router.put("/folders/{cw}/follow", response_model=FolderFollowState)
async def follow_folder(cw: KeyPath, request: Request, user: UserDep):
    return await request.app.state.collaboration.follow_folder(cw, user, True)


@router.delete("/folders/{cw}/follow", response_model=FolderFollowState)
async def unfollow_folder(cw: KeyPath, request: Request, user: UserDep):
    return await request.app.state.collaboration.follow_folder(cw, user, False)


@router.get("/following/folders", response_model=Page[FolderCard])
async def following_folders(
    request: Request, user: UserDep, page: PageNumber = 1, size: PageSize = 10
):
    return await request.app.state.collaboration.following_folders(user, page, size)
