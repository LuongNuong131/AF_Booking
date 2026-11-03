import logging
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id: ContextVar[str] = ContextVar("request_id", default="-")
request_path: ContextVar[str] = ContextVar("request_path", default="-")
logger = logging.getLogger("uvicorn.error")


@dataclass
class QueryTiming:
    milliseconds: float = 0


query_timing: ContextVar[QueryTiming | None] = ContextVar("query_timing", default=None)
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = Headers(scope=scope).get("x-request-id", "")
        identifier = supplied if SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = identifier
        context_token = request_id.set(identifier)
        path_token = request_path.set(scope["path"])
        started = time.monotonic()
        timing = QueryTiming()
        timing_token = query_timing.set(timing)
        status = 500

        async def add_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = identifier
                headers["Server-Timing"] = (
                    (
                        headers.get("Server-Timing", "") + ", "
                        if headers.get("Server-Timing")
                        else ""
                    )
                    + f"total;dur={(time.monotonic() - started) * 1000:.2f}, "
                    f"db;dur={timing.milliseconds:.2f}"
                )
                if scope["path"].startswith("/api/v1/"):
                    headers.setdefault("Cache-Control", "no-store")
            await send(message)

        try:
            await self.app(scope, receive, add_headers)
        finally:
            logger.info(
                "request_id=%s method=%s path=%r status=%s duration_ms=%.2f",
                identifier,
                scope["method"],
                scope["path"],
                status,
                (time.monotonic() - started) * 1000,
            )
            request_id.reset(context_token)
            request_path.reset(path_token)
            query_timing.reset(timing_token)


class WebSocketTokenRedaction(logging.Filter):
    """Uvicorn logs WebSocket handshake paths even with --no-access-log."""

    pattern = re.compile(r"([?&]token=)[^&\s\"']*", re.IGNORECASE)
    query_pattern = re.compile(r"\?[^\s\"']*")

    def filter(self, record: logging.LogRecord) -> bool:
        handshake = isinstance(record.msg, str) and "websocket" in record.msg.casefold()

        def redact(value):
            if not isinstance(value, str):
                return value
            if handshake or "/api/v1/ws" in value:
                # Remove the entire raw query, including percent-encoded parameter names.
                return self.query_pattern.sub("?[REDACTED]", value)
            return self.pattern.sub(r"\1[REDACTED]", value)

        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) for k, v in record.args.items()}
        return True


def install_websocket_log_redaction() -> None:
    for name in ("uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        if not any(isinstance(f, WebSocketTokenRedaction) for f in target.filters):
            target.addFilter(WebSocketTokenRedaction())
