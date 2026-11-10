import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import Settings
from app.core.errors import ApiException
from app.core.request_context import request_id
from app.core.security import (
    PasswordService,
    TokenClaims,
    create_access_token,
    signing_key,
    unauthorized,
    validate_password,
)
from app.models import User
from app.schemas.auth import LoginResponse
from app.schemas.contracts import ErrorCode
from app.services.audit import AuditContext, record_audit
from app.services.login_limiter import LoginLimiter
from app.services.session_cache import CurrentUser, SessionCache
from app.services.session_events import SessionEvents

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(
        self,
        engine: AsyncEngine | None,
        settings: Settings,
        events: SessionEvents,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.events = events
        self.cache = SessionCache(settings.auth_cache_ttl_seconds, settings.auth_cache_max_entries)
        self.limiter = LoginLimiter(settings.login_max_failures, settings.login_lockout_seconds)
        self.passwords = PasswordService(settings.auth_hash_concurrency)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        if self.engine is None:
            raise ApiException(ErrorCode.SERVICE_BUSY)
        try:
            async with asyncio.timeout(self.settings.db_query_timeout_ms / 1000):
                async with AsyncSession(self.engine, expire_on_commit=False) as session:
                    async with session.begin():
                        yield session
        except (PoolTimeout, DBAPIError):
            raise ApiException(ErrorCode.SERVICE_BUSY) from None
        except TimeoutError:
            raise ApiException(ErrorCode.REQUEST_TIMEOUT) from None

    @asynccontextmanager
    async def user_lock(self, user_id: int) -> AsyncIterator[None]:
        lock = self.cache.lock(user_id)
        try:
            async with asyncio.timeout(self.settings.db_pool_timeout_seconds):
                await lock.acquire()
        except TimeoutError:
            raise ApiException(ErrorCode.SERVICE_BUSY) from None
        try:
            yield
        finally:
            lock.release()

    @asynccontextmanager
    async def mutation(self, user_id: int) -> AsyncIterator[AsyncSession]:
        async with self.user_lock(user_id):
            self.cache.invalidate(user_id)
            try:
                async with self.transaction() as session:
                    yield session
            finally:
                # Also invalidate on cancellation or an uncertain commit outcome.
                self.cache.invalidate(user_id)

    async def principal(self, user_id: int) -> CurrentUser | None:
        async with self.user_lock(user_id):
            hit, user = self.cache.get(user_id)
            if hit:
                return user
            async with self.transaction() as session:
                row = await session.get(User, user_id)
                user = CurrentUser.from_model(row) if row is not None else None
            self.cache.set(user_id, user)
            return user

    async def authenticate(self, claims: TokenClaims) -> CurrentUser:
        user = await self.principal(int(claims.sub))
        if user is None or not user.is_active:
            raise unauthorized()
        if user.session_id != claims.sid:
            raise ApiException(ErrorCode.SESSION_REPLACED, headers={"WWW-Authenticate": "Bearer"})
        return user

    async def invalidate_user(self, user_id: int) -> None:
        """Call after committed external profile/role changes in future admin services."""
        async with self.user_lock(user_id):
            self.cache.invalidate(user_id)

    async def notify_old_session(self, user_id: int, session_id: str | None, reason: str) -> None:
        if session_id is None:
            return
        try:
            async with asyncio.timeout(self.settings.ws_send_timeout_seconds):
                await self.events.force_logout(user_id, session_id, reason)
        except Exception:
            # Notification transport failure must not restore an already revoked session.
            logger.warning("request_id=%s session.force_logout transport failed", request_id.get())

    @staticmethod
    def require_live_row(row: User | None, caller: CurrentUser) -> User:
        if row is None or not row.is_active or row.deleted_at is not None:
            raise unauthorized()
        if caller.session_id is None or row.current_session_id != caller.session_id:
            raise ApiException(ErrorCode.SESSION_REPLACED, headers={"WWW-Authenticate": "Bearer"})
        return row

    async def failed_login(
        self,
        username: str,
        context: AuditContext,
        user_id: int | None,
    ) -> None:
        async with self.transaction() as session:
            record_audit(
                session,
                "login_failed",
                actor_id=None,
                target_user_id=user_id,
                context=context,
                meta={"username": username},
            )

    async def login(
        self,
        username: str,
        password: str,
        ip: str,
        context: AuditContext,
    ) -> LoginResponse:
        signing_key(self.settings)  # Fail closed before any authentication state is changed.
        self.limiter.check_ip(ip)
        async with self.transaction() as session:
            candidate = await session.scalar(select(User).where(User.username == username))
            candidate_id = candidate.id if candidate else None
            encoded = candidate.password_hash if candidate else None
        # The stored username coalesces every alias accepted by the DB collation.
        bucket_username = candidate.username if candidate is not None else username
        async with self.limiter.attempt(ip, bucket_username) as attempt:
            valid = await self.passwords.verify(encoded, password)
            if (
                not valid
                or candidate is None
                or not candidate.is_active
                or candidate.deleted_at is not None
            ):
                attempt.failed()
                await self.failed_login(username, context, candidate_id)
                raise ApiException(
                    ErrorCode.UNAUTHORIZED,
                    message="Invalid username or password.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            old_session: str | None = None
            response: LoginResponse | None = None
            async with self.mutation(candidate.id) as session:
                row = await session.scalar(
                    select(User).where(User.id == candidate.id).with_for_update()
                )
                # Recheck after password verification: a concurrent password reset may have won.
                if (
                    row is not None
                    and row.is_active
                    and row.deleted_at is None
                    and row.password_hash == encoded
                    and row.username == candidate.username
                ):
                    old_session = row.current_session_id
                    row.current_session_id = str(uuid4())
                    row.last_login_at = datetime.now(UTC)
                    record_audit(
                        session,
                        "login_success",
                        actor_id=row.id,
                        target_user_id=row.id,
                        context=context,
                    )
                    if old_session:
                        record_audit(
                            session,
                            "session_replaced",
                            actor_id=row.id,
                            target_user_id=row.id,
                            context=context,
                            meta={"reason": "new_login"},
                        )
                    response = LoginResponse(
                        access_token=create_access_token(
                            row.id, row.role, row.current_session_id, self.settings
                        ),
                        user=CurrentUser.from_model(row).public(),
                        expires_in=self.settings.jwt_expire_minutes * 60,
                    )
            if response is None:
                attempt.failed()
                await self.failed_login(username, context, candidate.id)
                raise ApiException(
                    ErrorCode.UNAUTHORIZED,
                    message="Invalid username or password.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            attempt.succeeded()
        await self.notify_old_session(candidate.id, old_session, "new_login")
        return response

    async def logout(self, caller: CurrentUser, context: AuditContext) -> None:
        async with self.mutation(caller.id) as session:
            row = self.require_live_row(
                await session.scalar(select(User).where(User.id == caller.id).with_for_update()),
                caller,
            )
            row.current_session_id = None
            record_audit(session, "logout", actor_id=row.id, target_user_id=row.id, context=context)
        await self.notify_old_session(caller.id, caller.session_id, "logout")

    async def change_password(
        self,
        caller: CurrentUser,
        old_password: str,
        new_password: str,
        context: AuditContext,
    ) -> None:
        async with self.transaction() as session:
            row = self.require_live_row(await session.get(User, caller.id), caller)
            encoded = row.password_hash
        validate_password(new_password, caller.username)
        if not await self.passwords.verify(encoded, old_password):
            raise ApiException(ErrorCode.VALIDATION_ERROR, message="Current password is incorrect.")
        if old_password == new_password:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR, message="Choose a different new password."
            )
        updated_hash = await self.passwords.hash(new_password)
        async with self.mutation(caller.id) as session:
            row = self.require_live_row(
                await session.scalar(select(User).where(User.id == caller.id).with_for_update()),
                caller,
            )
            if row.password_hash != encoded:
                raise ApiException(
                    ErrorCode.VALIDATION_ERROR, message="The password was already changed."
                )
            row.password_hash = updated_hash
            row.must_change_password = False
            row.current_session_id = None
            record_audit(
                session, "password_changed", actor_id=row.id, target_user_id=row.id, context=context
            )
            record_audit(
                session,
                "session_kicked",
                actor_id=row.id,
                target_user_id=row.id,
                context=context,
                meta={"reason": "password_changed"},
            )
        await self.notify_old_session(caller.id, caller.session_id, "password_changed")

    async def kick_session(self, user_id, *, actor_id=None, context=None, caller=None):
        old_session = None
        async with self.mutation(user_id) as session:
            if caller is not None:
                from app.services.admin import locked_admin

                row = await locked_admin(session, caller, user_id)
            else:
                row = await session.scalar(select(User).where(User.id == user_id).with_for_update())
                if row is None:
                    raise ApiException(ErrorCode.NOT_FOUND)
            old_session = row.current_session_id
            row.current_session_id = None
            record_audit(
                session,
                "session_kicked",
                actor_id=actor_id,
                target_user_id=user_id,
                context=context,
                meta={"reason": "admin_kick", "had_session": old_session is not None},
            )
        await self.notify_old_session(user_id, old_session, "admin_kick")
        return old_session is not None

    async def set_user_active(
        self,
        user_id: int,
        active: bool,
        *,
        actor_id: int | None = None,
        context: AuditContext | None = None,
    ) -> None:
        old_session = None
        async with self.mutation(user_id) as session:
            row = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if row is None:
                raise ApiException(ErrorCode.NOT_FOUND)
            row.is_active = active
            if not active:
                old_session = row.current_session_id
                row.current_session_id = None
            record_audit(
                session,
                "user_enabled" if active else "user_disabled",
                actor_id=actor_id,
                target_user_id=user_id,
                context=context,
            )
            if old_session:
                record_audit(
                    session,
                    "session_kicked",
                    actor_id=actor_id,
                    target_user_id=user_id,
                    context=context,
                    meta={"reason": "user_disabled"},
                )
        await self.notify_old_session(user_id, old_session, "user_disabled")
