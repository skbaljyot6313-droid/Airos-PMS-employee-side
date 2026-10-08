"""
HTTP middleware — request correlation, access logging, security headers.

RequestIDMiddleware
    Accepts a client/proxy-supplied `X-Request-ID` (validated, bounded) or
    mints one. Stored in `request_id_ctx` so every log record inside the
    request can carry it, and echoed back on the response so support can
    correlate a user's report to a log line.

AccessLogMiddleware
    One structured line per request: method, path, status, duration,
    request_id, user_id/company_id (decoded from the Bearer JWT — no DB hit).
    Replaces the dev-only [PERF] middleware.

SecurityHeadersMiddleware
    Defense-in-depth headers on every response. The API serves JSON (and
    Swagger in non-prod), so CSP stays permissive enough for /docs.
"""

import contextvars
import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import decode_access_token

logger = get_logger("app.access")

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class RequestIDFilter(logging.Filter):
    """logging.Filter — injects the correlation id into every record."""

    def filter(self, record) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        rid = rid if _REQUEST_ID_RE.match(rid) else uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


_SKIP_LOG = {"/health", "/health/db", "/uploads"}


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        path = request.url.path
        if not any(path.startswith(p) for p in _SKIP_LOG):
            user_id = company_id = "-"
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                claims = decode_access_token(auth[7:]) or {}
                user_id = claims.get("sub", "-")
                company_id = claims.get("company_id", "-")
            logger.info(
                "method=%s path=%s status=%d duration_ms=%.0f user=%s company=%s",
                request.method, path, response.status_code, elapsed_ms,
                user_id, company_id,
            )
        response.headers["X-Response-Time"] = f"{elapsed_ms:.0f}ms"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if settings.is_production:
            # HSTS only makes sense once TLS is terminated at the proxy
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
