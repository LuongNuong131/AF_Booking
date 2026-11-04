"""Bound request bytes before JSON parsing and apply security headers to every response."""

from starlette.datastructures import Headers, MutableHeaders

from app.core.errors import error_response
from app.schemas.contracts import ErrorCode


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes=1048576):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = Headers(scope=scope).get("content-length")
        if length and (
            not length.isascii()
            or not length.isdecimal()
            or len(length) > 12
            or int(length) > self.max_bytes
        ):
            return await error_response(ErrorCode.PAYLOAD_TOO_LARGE)(scope, receive, send)
        messages = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                return await error_response(ErrorCode.PAYLOAD_TOO_LARGE)(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break
        position = 0

        async def replay():
            nonlocal position
            if position < len(messages):
                value = messages[position]
                position += 1
                return value
            return await receive()

        await self.app(scope, replay, send)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def headers(message):
            if message["type"] == "http.response.start":
                h = MutableHeaders(scope=message)
                h["X-Content-Type-Options"] = "nosniff"
                h["X-Frame-Options"] = "DENY"
                h["Referrer-Policy"] = "strict-origin-when-cross-origin"
                if scope["path"].startswith("/api/") and scope["path"] not in {
                    "/api/v1/stations",
                    "/api/v1/statuses",
                }:
                    h["Cache-Control"] = "no-store"
                    h["Pragma"] = "no-cache"
                if "retry-after" in h:
                    value = h["retry-after"]
                    h["Retry-After"] = (
                        str(min(86400, max(1, int(value))))
                        if value.isascii() and value.isdecimal() and len(value) < 7
                        else "5"
                    )
            await send(message)

        await self.app(scope, receive, headers)
