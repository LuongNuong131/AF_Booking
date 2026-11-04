import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ApiException, error_response
from app.core.request_context import request_id, request_path, safe_route
from app.schemas.contracts import ErrorCode

logger = logging.getLogger(__name__)


@asynccontextmanager
async def request_budget(seconds: float) -> AsyncIterator[None]:
    try:
        async with asyncio.timeout(seconds):
            yield
    except TimeoutError:
        logger.warning(
            "request_id=%s timeout route=%r seconds=%.3f",
            request_id.get(),
            request_path.get(),
            seconds,
        )
        raise ApiException(ErrorCode.REQUEST_TIMEOUT) from None


def timeout[T: Callable[..., Any]](seconds: float | str) -> Callable[[T], T]:
    """Attach a budget that DeadlineRoute applies before resolving dependencies."""

    def decorate(endpoint: T) -> T:
        endpoint.__request_timeout__ = seconds
        return endpoint

    return decorate


class DeadlineRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            request_path.set(safe_route(request.scope))
            override = getattr(self.endpoint, "__request_timeout__", None)
            if override is not None and "request_deadline" in request.scope.get("state", {}):
                seconds = (
                    getattr(request.app.state.settings, override)
                    if isinstance(override, str)
                    else override
                )
                state = request.scope["state"]
                state["request_timeout_seconds"] = float(seconds)
                state["request_deadline"].reschedule(state["request_started"] + seconds)
            return await handler(request)

        return handle


class RequestTimeoutMiddleware:
    """Cancel overdue HTTP work; leave WebSocket and lifespan scopes untouched."""

    def __init__(self, app: ASGIApp, timeout_seconds: float) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False
        state = scope.setdefault("state", {})
        state["request_started"] = asyncio.get_running_loop().time()
        state["request_timeout_seconds"] = self.timeout_seconds

        async def track_response(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            async with asyncio.timeout(self.timeout_seconds) as deadline:
                state["request_deadline"] = deadline
                await self.app(scope, receive, track_response)
        except TimeoutError:
            logger.warning(
                "request_id=%s timeout route=%r seconds=%.3f",
                request_id.get(),
                safe_route(scope),
                state["request_timeout_seconds"],
            )
            if response_started:
                # A streaming response cannot be replaced after its headers were sent.
                raise
            response = error_response(ErrorCode.REQUEST_TIMEOUT)
            await response(scope, receive, send)
