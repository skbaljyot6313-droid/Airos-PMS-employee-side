"""Employee preference endpoints.

Mounted under /mobile/employee — employee-facing settings for the staff
app. Identity always comes from the JWT (get_current_user →
user.employee_id); there is deliberately no employee-id parameter, so an
employee can never address another employee's preferences.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.employee_preference import (
    EmployeePreferencesOut,
    EmployeePreferencesPatch,
)
from app.services.employee_preference import EmployeePreferenceService

router = APIRouter(prefix="/mobile/employee", tags=["mobile"])


@router.get("/preferences", response_model=EmployeePreferencesOut)
async def get_preferences(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await EmployeePreferenceService(session).get_preferences(user)


@router.patch("/preferences", response_model=EmployeePreferencesOut)
async def update_preferences(
    data: EmployeePreferencesPatch,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await EmployeePreferenceService(session).update_preferences(
        user, data
    )


@router.get(
    "/preferences/languages", response_model=list
)
async def list_languages(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Supported-language metadata from the centralized registry."""
    prefs = await EmployeePreferenceService(session).get_preferences(user)
    return prefs.available_languages
