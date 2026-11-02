import asyncio

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response
from app.schemas.contracts import ErrorCode


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

        async def track_response(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            async with asyncio.timeout(self.timeout_seconds):
                await self.app(scope, receive, track_response)
        except TimeoutError:
            if response_started:
                # A streaming response cannot be replaced after its headers were sent.
                raise
            response = error_response(ErrorCode.REQUEST_TIMEOUT)
            await response(scope, receive, send)
