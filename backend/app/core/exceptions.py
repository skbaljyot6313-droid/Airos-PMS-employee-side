"""
Centralized exception handling.

Consistent error envelope for API clients — no raw tracebacks leak to
responses in production. Application-specific error types land in the
next phase; this provides the infrastructure convention.

Response shape:
    { "error": { "code": "...", "message": "..." } }

Note: the frontend's api client also understands FastAPI's native
`detail` envelope — both are emitted where appropriate.
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.exceptions")


class AppError(Exception):
    """Base application error — subclasses set status_code/code/message.
    `field` maps the error to a form field for inline display (frontend
    reads detail.field)."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."
    field: str | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        field: str | None = None,
    ):
        if message:
            self.message = message
        if code:
            self.code = code
        if field:
            self.field = field
        super().__init__(self.message)


class LiveLocationUnavailable(AppError):
    """Live-location backend (Redis) is unconfigured or unreachable.

    Deliberately NOT a Postgres fallback — current positions live only in
    Redis, so the honest answer to the client is a clean 503."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "LIVE_LOCATION_UNAVAILABLE"
    message = "Live location is temporarily unavailable. Please try again."


def _error_body(code: str, message: str, **extra) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    body["error"].update(extra)
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        # Emit both envelopes: the frontend reads `detail`; `error` carries
        # the structured code for clients that prefer it.
        content = _error_body(exc.code, exc.message)
        detail = {"message": exc.message, "code": exc.code}
        if exc.field:
            detail["field"] = exc.field
        content["detail"] = detail
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Map FastAPI's error list into field-targeted entries — the frontend
        # reads detail[i].loc[-1] as the offending field name.
        details = [
            {
                "loc": [str(p) for p in e.get("loc", [])],
                "msg": e.get("msg", "Invalid value"),
                "type": e.get("type", "value_error"),
            }
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "detail": details,
                "error": _error_body(
                    "VALIDATION_ERROR", "Request validation failed.", details=details
                )["error"],
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(
        request: Request, exc: SQLAlchemyError
    ) -> JSONResponse:
        # Log the REAL error server-side (type + message, truncated) — a
        # type-only log ("ProgrammingError") is undiagnosable. The client
        # still gets the sanitized 503 — never expose DB internals.
        logger.error(
            "Database error on %s %s: %s",
            request.method, request.url.path, str(exc)[:500],
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error_body(
                "DATABASE_ERROR", "A database error occurred. Please try again."
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        # Detail leaks only in real development — a misconfigured DEBUG=true
        # in production must never expose internals to clients.
        message = (
            str(exc)
            if settings.DEBUG and not settings.is_production
            else "An unexpected error occurred."
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("INTERNAL_ERROR", message),
        )
