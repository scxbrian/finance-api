"""One error shape for the whole API, as specified in the contract:
{"error": {"code": "...", "message": "...", "fields": {...}}}"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app")


class AppError(Exception):
    """Base for errors we raise on purpose. Subclasses set status_code and code."""

    status_code = 400
    code = "error"

    def __init__(self, message: str, *, fields: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields


class NotFound(AppError):
    status_code, code = 404, "not_found"


class Unauthorized(AppError):
    status_code, code = 401, "unauthorized"


class Forbidden(AppError):
    status_code, code = 403, "forbidden"


class Conflict(AppError):
    status_code, code = 409, "conflict"


class ServiceUnavailable(AppError):
    status_code, code = 503, "unavailable"


def _body(code: str, message: str, fields: dict[str, str] | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return {"error": error}


_HTTP_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, exc.fields), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for err in exc.errors():
            # Drop the "body"/"query"/"path" prefix; the client only needs the field name.
            parts = [str(p) for p in err["loc"] if p not in ("body", "query", "path")]
            fields[".".join(parts) or "request"] = err["msg"]
        return JSONResponse(
            _body("validation_error", "Some fields are invalid.", fields), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            _body(_HTTP_CODES.get(exc.status_code, "http_error"), message),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Details go to the server log only. The client never sees a stack trace.
        log.exception("Unhandled error")
        # This response is built outside our middleware, so it sets no-store itself.
        return JSONResponse(
            _body("internal_error", "Something went wrong on the server."),
            status_code=500,
            headers={"Cache-Control": "no-store"},
        )