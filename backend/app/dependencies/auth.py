"""
Authentication & authorization dependencies.

    get_current_user      — Bearer JWT → User (401 on missing/invalid/expired)
    require_role(*roles)  — 403 when the caller's role isn't allowed
    require_super_admin / require_property_manager / require_employee

The user's company_id is the authoritative tenant scope — services must
filter by current_user.company_id, never trust a client-supplied value.
"""

import secrets
import uuid
from collections.abc import Callable

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import sessions
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AppError, LiveLocationUnavailable
from app.core.logging import get_logger
from app.core.security import decode_access_token
from app.models.user import User, UserRole
from app.repositories.user import UserRepository

logger = get_logger("app.auth")

bearer_scheme = HTTPBearer(auto_error=False)


class Unauthenticated(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"
    message = "Authentication required."


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise Unauthenticated()
    claims = decode_access_token(credentials.credentials)
    if claims is None:
        raise Unauthenticated("Your session has expired. Please sign in again.")
    # Redis session registry — a token whose sid was revoked (logout)
    # dies here, not at JWT expiry. Fails open when Redis is down.
    sid = claims.get("sid")
    if sid is not None and not await sessions.alive(sid):
        raise Unauthenticated("Your session has expired. Please sign in again.")
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError):
        raise Unauthenticated()

    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("Your session has expired. Please sign in again.")
    return user


def require_role(*roles: UserRole) -> Callable:
    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise Forbidden()
        return user

    return _checker


require_super_admin = require_role(UserRole.SUPER_ADMIN)
require_property_manager = require_role(UserRole.SUPER_ADMIN, UserRole.PROPERTY_MANAGER)
require_employee = require_role(
    UserRole.SUPER_ADMIN, UserRole.PROPERTY_MANAGER, UserRole.EMPLOYEE
)
# Attendance approval authority is EXCLUSIVE to SUPER_ADMIN — approve /
# reject routes depend on require_super_admin directly; the service
# re-checks scope (SA's company) before deciding.
# GET /attendance/requests is role-dependent: employees read their own
# filings, SA reads the company-scoped review queue. PM/HR get 403 —
# they never see the pending-request queue (dispatch in the service).
require_attendance_participant = require_role(
    UserRole.SUPER_ADMIN, UserRole.EMPLOYEE,
)


# ---------------------------------------------------------------------------
# Service-to-service auth (NOT user auth)
# ---------------------------------------------------------------------------

_location_key_warned = False


async def require_location_service(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    """Shared-key gate for server-to-server endpoints (admin/*).

    This is deliberately NOT get_current_user: the caller is another
    backend (the SA service), not a person — no JWT is decoded, no User
    is loaded, no DB session is touched. The bearer token must equal
    LOCATION_SERVICE_API_KEY exactly, compared in constant time via
    secrets.compare_digest (a JWT minted for an employee is simply a
    wrong key → 401).

    Fails CLOSED: when the key is unconfigured the endpoint answers 503
    (like LiveLocationUnavailable) rather than silently opening or
    pretending auth exists — the misconfiguration is loud, once.
    """
    global _location_key_warned
    expected = settings.LOCATION_SERVICE_API_KEY
    if not expected:
        if not _location_key_warned:
            logger.warning(
                "LOCATION_SERVICE_API_KEY is unset — service-to-service "
                "location endpoints are disabled (failing closed with 503)"
            )
            _location_key_warned = True
        raise LiveLocationUnavailable(
            "Live-location service API is not configured on this server."
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, expected
    ):
        raise Unauthenticated()
