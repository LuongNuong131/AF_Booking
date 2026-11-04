from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.deps import get_auth_service, get_current_user
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    PublicUser,
)
from app.schemas.contracts import ApiError
from app.services.audit import AuditContext
from app.services.auth import AuthService
from app.services.session_cache import CurrentUser
from app.services.tasks import effective_settings

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses={status: {"model": ApiError} for status in (401, 403, 429, 503)},
)
Auth = Annotated[AuthService, Depends(get_auth_service)]
Authenticated = Annotated[CurrentUser, Depends(get_current_user)]


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, auth: Auth) -> LoginResponse:
    ip = request.client.host if request.client else "unknown"
    result = await auth.login(
        body.username,
        body.password.get_secret_value(),
        ip,
        AuditContext.from_request(request),
    )
    result.user.settings = effective_settings(
        result.user.settings, request.app.state.settings.business_timezone
    )
    request.scope.setdefault("state", {})["authenticated_user_id"] = result.user.id
    return result


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, auth: Auth, user: Authenticated) -> MessageResponse:
    await auth.logout(user, AuditContext.from_request(request))
    return MessageResponse(message="Signed out.")


@router.get("/me", response_model=PublicUser)
async def me(request: Request, user: Authenticated) -> PublicUser:
    result = user.public()
    result.settings = effective_settings(
        result.settings, request.app.state.settings.business_timezone
    )
    return result


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    auth: Auth,
    user: Authenticated,
) -> MessageResponse:
    await auth.change_password(
        user,
        body.old_password.get_secret_value(),
        body.new_password.get_secret_value(),
        AuditContext.from_request(request),
    )
    return MessageResponse(message="Password changed. Please sign in again.")
