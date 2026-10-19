"""GET /bootstrap — consolidated cold-start payload.

One request replaces the serial `/auth/me` → `/zones` → `/attendance/shift`
→ `/notifications/unread-count` startup chain — Phase-2 query reduction.

Contracts:
  * unread_count is a PLAIN count query — it must never invoke
    sync_assignment_notifications (the ledger sync stays on the feed
    read, which is the SA-integration backstop).
  * Sections fail independently: a failed section is `null` and records
    its code in `errors` — the client falls back to the legacy endpoint
    for just that section.
  * zones + company config are company-scoped reference data served
    read-through from Redis (45s TTL) with eviction on this service's
    zone mutations; SA-backend writes are bounded by the TTL.
  * ref_version is a deterministic content hash over the sections —
    a client compares it to detect a stale snapshot cheaply.
  * The whole endpoint is behind settings.BOOTSTRAP_ENABLED — off → 404.
"""

import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models.user import User
from app.repositories.workspace import WorkspaceRepository
from app.schemas.attendance import my_shift_out
from app.schemas.auth import company_to_out, user_to_out
from app.schemas.v1.resources.resource import zone_out
from app.services.employee_shift import resolve_my_shift, shift_applies_on
from app.services.notifications import NotificationService
from app.services.rollover import operational_day_key, parse_day_start

logger = get_logger("app.bootstrap")

IST = ZoneInfo("Asia/Kolkata")

_SCOPE_TTL_SECONDS = 45  # zones + company config cache TTL


class BootstrapDisabled(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "Not found."


def _scope_key(user: User) -> str:
    scope = user.property_id or "all"
    return f"mt:boot:scope:{user.company_id}:{scope}"


def scope_keys(company_id, property_id) -> list[str]:
    """Both cache keys a property mutation can dirty — its own scope and
    the company-wide 'all' scope used by super-admins."""
    return [
        f"mt:boot:scope:{company_id}:{property_id}",
        f"mt:boot:scope:{company_id}:all",
    ]


async def evict_scope_cache(company_id, property_id) -> None:
    """Best-effort eviction after this service mutates zones. SA-backend
    writes are NOT evictable from here — the TTL bounds their staleness."""
    client = await get_redis()
    if client is None:
        return
    try:
        await client.delete(*scope_keys(company_id, property_id))
    except Exception as exc:
        logger.warning(
            "bootstrap scope eviction failed: %s", type(exc).__name__
        )


async def _scope_block(user: User, session: AsyncSession, client) -> dict:
    """{company, zones} — read-through cached; a cache hit costs zero DB
    queries and one Redis round trip."""
    key = _scope_key(user)
    if client is not None:
        try:
            raw = await client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning(
                "bootstrap scope cache read failed: %s", type(exc).__name__
            )
    result = await WorkspaceRepository(session).list_zones(user)
    block = jsonable_encoder(
        {
            "company": company_to_out(user.company).model_dump(mode="json"),
            "zones": [zone_out(zone) for zone in result["items"]],
        }
    )
    if client is not None:
        try:
            await client.set(
                key, json.dumps(block), ex=_SCOPE_TTL_SECONDS
            )
        except Exception as exc:
            logger.warning(
                "bootstrap scope cache write failed: %s",
                type(exc).__name__,
            )
    return block


async def _shift_section(user: User, session: AsyncSession) -> dict:
    """Identical output to GET /attendance/shift, minus the
    employee-existence lookup — op_date comes from the caller's own
    company, which is identical for employee-scoped users."""
    if user.employee_id is None:
        from app.dependencies.auth import Forbidden
        raise Forbidden("Your account is not linked to an employee record.")
    day_start = parse_day_start(user.company.operational_day_start)
    op_date = operational_day_key(datetime.now(IST), day_start)
    assignment, shift, op_date = await resolve_my_shift(
        user, session, op_date=op_date
    )
    return my_shift_out(
        assignment, shift,
        op_date=op_date,
        is_working_today=(
            shift_applies_on(shift.working_days, op_date)
            if shift else False
        ),
    )


def _ref_version(sections: dict) -> str:
    blob = json.dumps(
        sections, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


async def get_bootstrap(user: User, session: AsyncSession) -> dict:
    """{ref_version, user, company, zones, shift, unread_count, errors}."""
    if not settings.BOOTSTRAP_ENABLED:
        raise BootstrapDisabled()

    errors: dict[str, str] = {}
    client = await get_redis()

    # ---- company-scoped block (zones + company config) ----------------
    try:
        scope = await _scope_block(user, session, client)
        company_payload = scope["company"]
        zones_payload = {
            "items": scope["zones"],
            "total": len(scope["zones"]),
            "page": 1,
            "limit": len(scope["zones"]),
        }
    except Exception as exc:
        logger.warning("bootstrap scope section failed: %s", exc)
        company_payload = None
        zones_payload = None
        errors["zones"] = (
            exc.code if isinstance(exc, AppError) else "INTERNAL_ERROR"
        )

    # ---- shift --------------------------------------------------------
    try:
        shift_payload = await _shift_section(user, session)
    except Exception as exc:
        logger.warning("bootstrap shift section failed: %s", exc)
        shift_payload = None
        errors["shift"] = (
            exc.code if isinstance(exc, AppError) else "INTERNAL_ERROR"
        )

    # ---- unread count (PLAIN count — no ledger sync) ------------------
    try:
        unread = await NotificationService(session).unread_count(user)
        unread_payload = {"unread": unread}
    except Exception as exc:
        logger.warning("bootstrap unread section failed: %s", exc)
        unread_payload = None
        errors["unread_count"] = (
            exc.code if isinstance(exc, AppError) else "INTERNAL_ERROR"
        )

    sections = {
        "user": user_to_out(user).model_dump(mode="json"),
        "company": company_payload,
        "zones": zones_payload,
        "shift": shift_payload,
        "unread_count": unread_payload,
    }
    sections["ref_version"] = _ref_version(sections)
    sections["errors"] = errors
    return sections
