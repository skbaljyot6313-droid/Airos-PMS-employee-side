"""GET /bootstrap — consolidated cold-start payload (Phase-2).

Replaces the serial startup chain (/auth/me → /zones →
/attendance/shift → /notifications/unread-count) with a single call.
Sections fail independently — errors[section] tells the client which
legacy endpoint to fall back to. Behind BOOTSTRAP_ENABLED (404 off).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.bootstrap import get_bootstrap

router = APIRouter(tags=["bootstrap"])


@router.get("/bootstrap")
async def bootstrap(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await get_bootstrap(user, session)
