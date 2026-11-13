"""Employee preference service — language settings per employee.

Preference reads NEVER break a session: a caller without an employees
link (e.g. a super_admin account) or without a stored row gets the
defaults, not an error. Writes require a real employee identity — the
service derives it from the authenticated user and never trusts a
client-supplied employee id.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.domain.languages import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from app.models.employee_preference import EmployeePreference
from app.models.user import User
from app.repositories.employee_preference import (
    EmployeePreferenceRepository,
)
from app.schemas.employee_preference import (
    EmployeePreferencesOut,
    EmployeePreferencesPatch,
    LanguageMeta,
)


def _languages_meta() -> list[LanguageMeta]:
    return [
        LanguageMeta(
            code=lang.code, name=lang.name, native_name=lang.native_name
        )
        for lang in SUPPORTED_LANGUAGES
    ]


class NoEmployeeIdentity(AppError):
    status_code = 403
    code = "NO_EMPLOYEE_IDENTITY"
    message = "This account is not linked to an employee record."


def _out(pref: EmployeePreference | None) -> EmployeePreferencesOut:
    return EmployeePreferencesOut(
        text_language=(pref.text_language if pref else DEFAULT_LANGUAGE),
        audio_language=(pref.audio_language if pref else DEFAULT_LANGUAGE),
        available_languages=_languages_meta(),
    )


class EmployeePreferenceService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = EmployeePreferenceRepository(session)

    async def get_preferences(
        self, user: User
    ) -> EmployeePreferencesOut:
        if user.employee_id is None:
            return _out(None)
        pref = await self.repo.get_by_employee(user.employee_id)
        return _out(pref)

    async def update_preferences(
        self, user: User, patch: EmployeePreferencesPatch
    ) -> EmployeePreferencesOut:
        if user.employee_id is None:
            raise NoEmployeeIdentity()
        pref = await self.repo.get_or_create(user.employee_id)
        if patch.text_language is not None:
            pref.text_language = patch.text_language
        if patch.audio_language is not None:
            pref.audio_language = patch.audio_language
        await self.session.commit()
        return _out(pref)
