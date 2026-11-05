from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.deps import get_current_user
from app.core.timeouts import DeadlineRoute
from app.schemas.snippets import NoteSnippet, NoteSnippetCreate, NoteSnippetPatch
from app.services.audit import AuditContext
from app.services.session_cache import CurrentUser

router = APIRouter(route_class=DeadlineRoute, tags=["snippets"])
Actor = Annotated[CurrentUser, Depends(get_current_user)]


@router.get("/snippets", response_model=list[NoteSnippet])
async def listing(
    request: Request,
    user: Actor,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
):
    return await request.app.state.snippets.listing(user.id, q, limit)


@router.post("/snippets", response_model=NoteSnippet)
async def create(body: NoteSnippetCreate, request: Request, user: Actor):
    return await request.app.state.snippets.create(
        user.id, body, AuditContext.from_request(request)
    )


@router.patch("/snippets/{snippet_id}", response_model=NoteSnippet)
async def update(snippet_id: int, body: NoteSnippetPatch, request: Request, user: Actor):
    return await request.app.state.snippets.update(
        snippet_id, user.id, body, AuditContext.from_request(request)
    )


@router.post("/snippets/{snippet_id}/use", response_model=NoteSnippet)
async def use(snippet_id: int, request: Request, user: Actor):
    return await request.app.state.snippets.use(
        snippet_id, user.id, AuditContext.from_request(request)
    )


@router.delete("/snippets/{snippet_id}")
async def delete(snippet_id: int, request: Request, user: Actor):
    return await request.app.state.snippets.delete(
        snippet_id, user.id, AuditContext.from_request(request)
    )
