from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiException
from app.core.security import decode_access_token, unauthorized
from app.schemas.auth import UserRole
from app.schemas.contracts import ErrorCode
from app.services.auth import AuthService
from app.services.session_cache import CurrentUser

bearer = HTTPBearer(auto_error=False)


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    engine = request.app.state.engine
    if engine is None:
        raise ApiException(ErrorCode.SERVICE_BUSY)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    claims = decode_access_token(credentials.credentials, request.app.state.settings)
    user = await auth.authenticate(claims)
    if user.must_change_password and request.url.path not in {
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/auth/change-password",
    }:
        raise ApiException(ErrorCode.PASSWORD_CHANGE_REQUIRED)
    return user


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[CurrentUser]]:
    if not roles or not set(roles) <= {"admin", "qc", "agent"}:
        raise ValueError("require_roles needs at least one valid role")

    async def authorized(
        user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if user.role not in roles:
            raise ApiException(ErrorCode.FORBIDDEN)
        return user

    return authorized
