"""Employee work-calendar feed — timeline data for day/week/month views."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.work_calendar import WorkCalendarService

router = APIRouter(prefix="/work-calendar", tags=["work-calendar"])


@router.get("")
async def work_calendar(
    date_from: str = Query(..., min_length=10, max_length=10),
    date_to: str = Query(..., min_length=10, max_length=10),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await WorkCalendarService(session).range(user, date_from, date_to)
