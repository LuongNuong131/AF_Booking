import logging
from collections.abc import Mapping
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import JsonValue
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.schemas.contracts import ApiError, ErrorCode

logger = logging.getLogger(__name__)

ERROR_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.SESSION_REPLACED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOTE_REQUIRED: 422,
    ErrorCode.STATUS_INACTIVE: 422,
    ErrorCode.TASK_LIMIT_REACHED: 422,
    ErrorCode.NEW_BOOKING_NEEDS_CONFIRM: 422,
    ErrorCode.DUPLICATE_RECENT_NOTE: 409,
    ErrorCode.WATCH_LIMIT_REACHED: 422,
    ErrorCode.ASSIGNMENT_INVALID: 422,
    ErrorCode.INVALID_BOOKING_KEY: 422,
    ErrorCode.STATION_REQUIRED: 422,
    ErrorCode.STATION_MISMATCH: 422,
    ErrorCode.SUPPLIER_REQUIRED: 422,
    ErrorCode.VERSION_CONFLICT: 409,
    ErrorCode.INVOICE_REQUIRED: 422,
    ErrorCode.INVOICE_INVALID: 422,
    ErrorCode.INVOICE_STATE_CONFLICT: 422,
    ErrorCode.INVOICE_LIMIT_REACHED: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.REQUEST_TIMEOUT: 504,
    ErrorCode.SERVICE_BUSY: 503,
    ErrorCode.INTERNAL: 500,
}

DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.UNAUTHORIZED: "Please sign in to continue.",
    ErrorCode.SESSION_REPLACED: "Your account was signed in on another device.",
    ErrorCode.FORBIDDEN: "You do not have permission to perform this action.",
    ErrorCode.NOT_FOUND: "The requested resource was not found.",
    ErrorCode.VALIDATION_ERROR: "The request is invalid.",
    ErrorCode.NOTE_REQUIRED: "A note is required for this status.",
    ErrorCode.STATUS_INACTIVE: "This status is no longer active.",
    ErrorCode.TASK_LIMIT_REACHED: "The pending task limit has been reached.",
    ErrorCode.NEW_BOOKING_NEEDS_CONFIRM: "Please confirm that this is a new booking.",
    ErrorCode.DUPLICATE_RECENT_NOTE: "You recently sent an identical note.",
    ErrorCode.WATCH_LIMIT_REACHED: "The watched booking limit has been reached.",
    ErrorCode.ASSIGNMENT_INVALID: "This assignment is invalid.",
    ErrorCode.INVALID_BOOKING_KEY: "Invalid booking number. Expected format: CW 1234567-YUL-2608.",
    ErrorCode.STATION_REQUIRED: (
        "This booking number has no station code. Enter the station (3 letters) to continue."
    ),
    ErrorCode.STATION_MISMATCH: "This CW number belongs to another station.",
    ErrorCode.SUPPLIER_REQUIRED: "Enter the supplier name and type to continue.",
    ErrorCode.VERSION_CONFLICT: (
        "This booking was just updated. Review the latest note, then save again."
    ),
    ErrorCode.INVOICE_REQUIRED: 'Add at least one invoice number or tick "No invoice Number".',
    ErrorCode.INVOICE_INVALID: "One or more invoice numbers are invalid.",
    ErrorCode.INVOICE_STATE_CONFLICT: (
        'Remove the invoice numbers before ticking "No invoice Number".'
    ),
    ErrorCode.INVOICE_LIMIT_REACHED: "The invoice number limit has been reached.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please try again later.",
    ErrorCode.REQUEST_TIMEOUT: "This is taking too long. Please try again.",
    ErrorCode.SERVICE_BUSY: "The server is busy. Retrying in a moment…",
    ErrorCode.INTERNAL: "An unexpected error occurred. Please try again.",
}


def error_response(
    code: ErrorCode,
    *,
    message: str | None = None,
    details: JsonValue = None,
    headers: Mapping[str, str] | None = None,
    status_code: int | None = None,
) -> JSONResponse:
    response_headers = {key.lower(): value for key, value in (headers or {}).items()}
    if code == ErrorCode.SERVICE_BUSY:
        response_headers.setdefault("retry-after", "5")
    return JSONResponse(
        status_code=status_code or ERROR_HTTP_STATUS[code],
        content=ApiError(
            code=code, message=message or DEFAULT_MESSAGES[code], details=details
        ).model_dump(mode="json", exclude_none=True),
        headers=response_headers,
    )


class ApiException(Exception):
    def __init__(
        self,
        code: ErrorCode,
        *,
        message: str | None = None,
        details: JsonValue = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers
        super().__init__(code.value)


def register_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(ApiException)
    async def domain_error(request: Request, exc: ApiException) -> JSONResponse:
        return error_response(
            exc.code, message=exc.message, details=exc.details, headers=exc.headers
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo input values, passwords, or validator context into responses.
        errors = [{"loc": list(item["loc"]), "type": item["type"]} for item in exc.errors()]
        return error_response(
            ErrorCode.VALIDATION_ERROR, details=cast(JsonValue, {"errors": errors})
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        status_codes = {
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            429: ErrorCode.RATE_LIMITED,
            503: ErrorCode.SERVICE_BUSY,
            504: ErrorCode.REQUEST_TIMEOUT,
        }
        code = status_codes.get(
            exc.status_code,
            ErrorCode.INTERNAL if exc.status_code >= 500 else ErrorCode.VALIDATION_ERROR,
        )
        return error_response(code, headers=exc.headers, status_code=exc.status_code)


class ApiErrorMiddleware:
    """Return safe internal errors inside CORS without catching cancellation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def track_response(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response)
        except Exception as exc:
            if started:
                raise
            # Log the exception class only: DB errors can contain credentials or SQL parameters.
            logger.error("Unhandled application error (%s)", type(exc).__name__)
            await error_response(ErrorCode.INTERNAL)(scope, receive, send)


class ApiCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code < 400:
            return response
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-type", "content-length"}
        }
        return error_response(ErrorCode.FORBIDDEN, headers=headers)
