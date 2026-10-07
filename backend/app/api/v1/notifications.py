"""Notifications feed + push-device registration.

RBAC (deliberately minimal per the RBAC caution): employees read their
OWN feed only — there is no cross-employee or SA GET yet (reviewer/SA
visibility can land later when its scope rules are specified). Any
authenticated user with a linked employee record may register devices
(PM accounts carry employee_ids too); the service enforces the link.
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import (
    get_current_user,
    require_attendance_participant,
)
from app.models.user import User
from app.schemas.notifications import (
    DeviceRegisterRequest,
    DeviceUnregisterRequest,
    device_out,
    notification_out,
)
from app.services.notifications import DeviceRegistry, NotificationService

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    unread_only: bool = Query(default=False),
    user: User = Depends(require_attendance_participant),
    session: AsyncSession = Depends(get_db),
):
    items = await NotificationService(session).list_notifications(
        user, limit=limit, unread_only=unread_only,
    )
    return {"items": [notification_out(n) for n in items]}


@router.get("/notifications/unread-count")
async def unread_count(
    user: User = Depends(require_attendance_participant),
    session: AsyncSession = Depends(get_db),
):
    return {
        "unread": await NotificationService(session).unread_count(user)
    }


@router.post("/notifications/{notification_uid}/read")
async def mark_read(
    notification_uid: uuid.UUID,
    user: User = Depends(require_attendance_participant),
    session: AsyncSession = Depends(get_db),
):
    return notification_out(
        await NotificationService(session).mark_read(user, notification_uid)
    )


@router.post("/devices/register")
async def register_device(
    payload: DeviceRegisterRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    device = await DeviceRegistry(session).register(
        user,
        device_id=payload.device_id,
        push_token=payload.push_token,
        platform=payload.platform,
        app_version=payload.app_version,
    )
    return device_out(device)


@router.post("/devices/unregister")
async def unregister_device(
    payload: DeviceUnregisterRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    device = await DeviceRegistry(session).unregister(
        user, device_id=payload.device_id,
    )
    return {"device": device_out(device) if device else None}
