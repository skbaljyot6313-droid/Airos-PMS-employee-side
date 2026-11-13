"""Employee preference service tests — language settings per employee."""

import pytest
from pydantic import ValidationError

from app.domain.languages import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGE_CODES,
    tts_locale,
)
from app.models.user import User, UserRole
from app.schemas.employee_preference import EmployeePreferencesPatch
from app.services.employee_preference import (
    EmployeePreferenceService,
    NoEmployeeIdentity,
)


async def test_defaults_for_employee_without_row(session, seed):
    svc = EmployeePreferenceService(session)
    out = await svc.get_preferences(seed["emp_user"])
    assert out.text_language == DEFAULT_LANGUAGE == "en"
    assert out.audio_language == "en"
    codes = [l.code for l in out.available_languages]
    assert codes == ["en", "hi", "mr"]
    assert {l.native_name for l in out.available_languages} == {
        "English", "हिन्दी", "मराठी"
    }


async def test_user_without_employee_link_gets_defaults(session, seed):
    """Reads never break a session — admins have no employees row."""
    svc = EmployeePreferenceService(session)
    out = await svc.get_preferences(seed["admin"])
    assert out.text_language == "en" and out.audio_language == "en"


async def test_user_without_employee_link_cannot_write(session, seed):
    svc = EmployeePreferenceService(session)
    with pytest.raises(NoEmployeeIdentity):
        await svc.update_preferences(
            seed["admin"], EmployeePreferencesPatch(text_language="hi")
        )


async def test_update_both_languages_persists(session, seed):
    svc = EmployeePreferenceService(session)
    out = await svc.update_preferences(
        seed["emp_user"],
        EmployeePreferencesPatch(text_language="hi", audio_language="mr"),
    )
    assert out.text_language == "hi" and out.audio_language == "mr"
    # Fresh service/session read sees the stored row, not defaults.
    again = await EmployeePreferenceService(session).get_preferences(
        seed["emp_user"]
    )
    assert (again.text_language, again.audio_language) == ("hi", "mr")


async def test_partial_updates_are_independent(session, seed):
    svc = EmployeePreferenceService(session)
    await svc.update_preferences(
        seed["emp_user"], EmployeePreferencesPatch(text_language="mr")
    )
    out = await svc.update_preferences(
        seed["emp_user"], EmployeePreferencesPatch(audio_language="hi")
    )
    assert out.text_language == "mr"  # untouched by the audio patch
    assert out.audio_language == "hi"


async def test_upsert_creates_one_row_per_employee(session, seed):
    svc = EmployeePreferenceService(session)
    await svc.update_preferences(
        seed["emp_user"], EmployeePreferencesPatch(text_language="hi")
    )
    await svc.update_preferences(
        seed["emp_user"], EmployeePreferencesPatch(text_language="mr")
    )
    from sqlalchemy import func, select
    from app.models.employee_preference import EmployeePreference

    count = (
        await session.execute(
            select(func.count()).select_from(EmployeePreference).where(
                EmployeePreference.employee_id
                == seed["employee"].id
            )
        )
    ).scalar_one()
    assert count == 1


async def test_second_employee_isolated(session, seed):
    """Updating employee A never leaks into employee B's row."""
    # emp_user2 has no employee link in seed — give it one.
    emp2 = seed["emp_user2"]
    emp2.employee_id = seed["employee"].id
    await session.flush()

    svc = EmployeePreferenceService(session)
    other = User(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name="Worker Two", email="w2@acme.test", username="w2",
        password_hash="x", role=UserRole.EMPLOYEE,
        employee_id=seed["emp_user2"].employee_id,
    )
    session.add(other)
    await session.flush()

    await svc.update_preferences(
        seed["emp_user"], EmployeePreferencesPatch(audio_language="mr")
    )
    out = await svc.get_preferences(other)
    # Same employee link → same row; distinct employees stay separate —
    # create a second employees row to prove isolation.
    assert out.audio_language == "mr"

    from app.models.employee import Employee
    e2 = Employee(
        company_id=seed["company"].id, property_id=seed["prop"].id,
        name="Worker Three", email="w3@acme.test", status="active",
    )
    session.add(e2)
    await session.flush()
    other.employee_id = e2.id
    await session.flush()
    out = await svc.get_preferences(other)
    assert out.audio_language == "en"


def test_schema_rejects_unsupported_language():
    with pytest.raises(ValidationError):
        EmployeePreferencesPatch(text_language="fr")
    with pytest.raises(ValidationError):
        EmployeePreferencesPatch(audio_language="xx")


def test_schema_normalizes_case_and_whitespace():
    p = EmployeePreferencesPatch(text_language=" HI ")
    assert p.text_language == "hi"
    p2 = EmployeePreferencesPatch(audio_language=None)
    assert p2.audio_language is None


def test_registry_contract():
    assert SUPPORTED_LANGUAGE_CODES == {"en", "hi", "mr"}
    assert tts_locale("en") == "en-IN"
    assert tts_locale("hi") == "hi-IN"
    assert tts_locale("mr") == "mr-IN"
    assert tts_locale("bogus") == "en-IN"  # safe fallback
