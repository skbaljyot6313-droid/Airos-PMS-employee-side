"""
Authentication & authorization dependencies.

    get_current_user      — Bearer JWT → User (401 on missing/invalid/expired)
    require_role(*roles)  — 403 when the caller's role isn't allowed
    require_super_admin / require_property_manager / require_employee

The user's company_id is the authoritative tenant scope — services must
filter by current_user.company_id, never trust a client-supplied value.
"""

import enum
import json
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import NamedTuple

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

from app.core import sessions
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AppError, LiveLocationUnavailable
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.models.company import Company
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

    user = await _cached_user(session, user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("Your session has expired. Please sign in again.")
    return user


# ---------------------------------------------------------------------------
# User-row cache — a Redis sidecar copy of the users+company row so every
# authenticated request does not pay a Postgres round trip for a row that
# changes minutes-to-days apart (mt:authctx:user:{uid}).
#
# Reconstruction: ORM instances are rebuilt from cached columns, marked
# detached (identity key) and added to the request session — detached-add
# makes them persistent WITHOUT marking columns dirty, so stale values can
# never be written back on commit, and later edits produce UPDATE, never
# INSERT. (merge(load=False) was rejected: it dirties every copied column.)
# user.company is attached straight into __dict__ (manual eager-load) so
# the joined load survives the round trip.
#
# STALENESS CONTRACT: is_active / role / zone/employee links are written by
# the SA backend against the shared DB — there is no eviction hook here, so
# a deactivation or role change can take up to USER_CACHE_TTL_S (default
# 30s) to take effect on EVERY authenticated endpoint. Sid/session
# revocation is checked before the cache on every request and is NEVER
# cached — logout still kills access instantly. This service's own user
# writes (PATCH /auth/me) evict via evict_user_cache.
# USER_CACHE_TTL_S=0 disables the cache entirely (every request → Postgres).
# ---------------------------------------------------------------------------

_USER_COLS = [c.key for c in sa_inspect(User).mapper.columns]
_COMPANY_COLS = [c.key for c in sa_inspect(Company).mapper.columns]


def _user_ctx_key(user_id: uuid.UUID) -> str:
    return f"mt:authctx:user:{user_id}"


def _dump_columns(obj, cols: list[str]) -> dict:
    out = {}
    for k in cols:
        v = getattr(obj, k)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        elif isinstance(v, enum.Enum):
            v = v.value
        out[k] = v
    return out


def _restore_columns(model, data: dict):
    obj = model()
    mapper = sa_inspect(model).mapper
    for k, v in data.items():
        if v is not None:
            try:
                t = mapper.columns[k].type.python_type
            except Exception:
                t = None
            try:
                if t is uuid.UUID:
                    v = uuid.UUID(str(v))
                elif t is datetime:
                    v = datetime.fromisoformat(str(v))
                elif isinstance(t, type) and issubclass(t, enum.Enum):
                    v = t(v)
            except (ValueError, TypeError):
                pass
        setattr(obj, k, v)
    # Detached (identity key present) so session.add() treats the row as
    # existing — persistent, no INSERT, no dirty columns.
    make_transient_to_detached(obj)
    return obj


async def _cached_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    ttl = settings.USER_CACHE_TTL_S
    client = await get_redis() if ttl > 0 else None
    if client is not None:
        try:
            raw = await client.get(_user_ctx_key(user_id))
            if raw:
                data = json.loads(raw)
                restored = _restore_columns(User, data["user"])
                try:
                    session.add(restored)
                except Exception:
                    # Identity already attached in this session —
                    # use that instance rather than raising.
                    restored = await session.get(User, user_id)
                if restored is not None:
                    company_data = data.get("company")
                    if company_data:
                        restored.__dict__["company"] = (
                            _restore_columns(Company, company_data)
                        )
                return restored
        except Exception as exc:
            logger.warning(
                "user cache read failed: %s", type(exc).__name__
            )
    user = await UserRepository(session).get_by_id(user_id)
    if user is not None and client is not None:
        try:
            data = {"user": _dump_columns(user, _USER_COLS)}
            if user.company is not None:
                data["company"] = _dump_columns(
                    user.company, _COMPANY_COLS
                )
            await client.set(
                _user_ctx_key(user_id),
                json.dumps(data),
                ex=ttl,
            )
        except Exception as exc:
            logger.warning(
                "user cache write failed: %s", type(exc).__name__
            )
    return user


async def evict_user_cache(user_id: uuid.UUID) -> None:
    """Drop the cached user row — called after this service writes user
    fields (PATCH /auth/me). SA-backend writes are TTL-bounded."""
    client = await get_redis()
    if client is None:
        return
    try:
        await client.delete(_user_ctx_key(user_id))
    except Exception as exc:
        logger.warning(
            "user cache eviction failed: %s", type(exc).__name__
        )


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
# Lightweight principal for the location hot path
#
# POST /location/current fires every ~10 s per tracking employee; running
# the full get_current_user (a users-row lookup) per fix was the single
# largest steady-state Postgres consumer. This dependency keeps the same
# guarantees — valid JWT, live Redis session, role gate, employee link —
# but resolves employee/property context from a 60-second Redis cache,
# falling back to Postgres on a miss or outage.
#
# Trade-off (approved): a deactivated employee can keep ingesting for up
# to 60 s — the cache TTL bounds it. Logout still kills the session
# instantly via the sid check, which is NOT cached.
#
# No invalidation hook exists for the cached fields (employee_id,
# property_id): this service never writes them — user.is_active and
# employee links are mutated by the SA backend against the shared DB,
# and PATCH /auth/me only touches name/phone/email. The 60s TTL is the
# sole staleness bound; add an explicit eviction here if this service
# ever gains a write path for those fields.
# ---------------------------------------------------------------------------


class TrackingPrincipal(NamedTuple):
    user_id: uuid.UUID
    employee_id: uuid.UUID | None
    property_id: uuid.UUID | None
    company_id: uuid.UUID | None
    role: str | None


_TRACKING_ROLES = {UserRole.SUPER_ADMIN.value, UserRole.EMPLOYEE.value}
_AUTH_CTX_TTL = 60  # seconds


def _auth_ctx_key(user_id: uuid.UUID) -> str:
    return f"mt:authctx:{user_id}"


async def get_tracking_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> TrackingPrincipal:
    """JWT + session + role gate, with Redis-cached employee context.

    Used ONLY by the location ingest/self-read routes where the handler
    needs employee_id/property_id but nothing else on the User row."""
    if credentials is None:
        raise Unauthenticated()
    claims = decode_access_token(credentials.credentials)
    if claims is None:
        raise Unauthenticated(
            "Your session has expired. Please sign in again."
        )
    sid = claims.get("sid")
    if sid is not None and not await sessions.alive(sid):
        raise Unauthenticated(
            "Your session has expired. Please sign in again."
        )
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError):
        raise Unauthenticated()

    role = claims.get("role")
    if role is not None and role not in _TRACKING_ROLES:
        raise Forbidden()

    # Cache is only trustworthy when the role claim was present (a token
    # without one must take the DB path so the role gate still applies).
    ctx = None
    client = None
    if role is not None:
        try:
            client = await get_redis()
            if client is not None:
                raw = await client.get(_auth_ctx_key(user_id))
                if raw:
                    ctx = json.loads(raw)
        except Exception:
            ctx = None  # cache is an accelerator — miss → DB path

    if ctx is None:
        user = await UserRepository(session).get_by_id(user_id)
        if user is None or not user.is_active:
            raise Unauthenticated(
                "Your session has expired. Please sign in again."
            )
        if user.role.value not in _TRACKING_ROLES:
            raise Forbidden()
        ctx = {
            "employee_id": (
                str(user.employee_id) if user.employee_id else None
            ),
            "property_id": (
                str(user.property_id) if user.property_id else None
            ),
        }
        try:
            if client is not None:
                await client.set(
                    _auth_ctx_key(user_id), json.dumps(ctx),
                    ex=_AUTH_CTX_TTL,
                )
        except Exception:
            pass  # cache write is best-effort

    company_raw = claims.get("company_id")
    return TrackingPrincipal(
        user_id=user_id,
        employee_id=(
            uuid.UUID(ctx["employee_id"]) if ctx.get("employee_id")
            else None
        ),
        property_id=(
            uuid.UUID(ctx["property_id"]) if ctx.get("property_id")
            else None
        ),
        company_id=uuid.UUID(company_raw) if company_raw else None,
        role=role,
    )


# ---------------------------------------------------------------------------
# Service-to-service auth (NOT user auth)
# ---------------------------------------------------------------------------

_location_key_warned = False


async def require_location_service(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    """Shared-key gate for server-to-server endpoints (admin/*).

    This is deliberately NOT get_current_user: the caller is another
    backend (the SA service), not a person — no JWT is decoded, no User
    is loaded, no DB session is touched. The key is accepted as either
    `X-Location-Service-Key: <key>` (canonical contract) or
    `Authorization: Bearer <key>` (legacy); either way it must equal
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
    provided = request.headers.get("x-location-service-key") or (
        credentials.credentials if credentials is not None else None
    )
    if provided is None or not secrets.compare_digest(provided, expected):
        raise Unauthenticated()


_release_key_warned = False


async def require_release_service(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    """Shared-key gate for release management (POST /mobile/releases*).

    Same contract as require_location_service: a deployment pipeline or
    operator holds RELEASE_MANAGEMENT_API_KEY — no JWT, no User, no DB
    session on the auth path. Fails closed with 503 when unconfigured.
    """
    global _release_key_warned
    expected = settings.RELEASE_MANAGEMENT_API_KEY
    if not expected:
        if not _release_key_warned:
            logger.warning(
                "RELEASE_MANAGEMENT_API_KEY is unset — release-management "
                "endpoints are disabled (failing closed with 503)"
            )
            _release_key_warned = True
        raise LiveLocationUnavailable(
            "Release management API is not configured on this server."
        )
    if credentials is None or not secrets.compare_digest(
        credentials.credentials, expected
    ):
        raise Unauthenticated()
