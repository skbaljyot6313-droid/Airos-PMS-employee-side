"""Employee self-registration — service-layer tests on in-memory SQLite.

Covers code verification, request submission (pending only — never an
account), duplicate/identity guards, and the credential-gated login
status lookup.
"""
import pytest
from sqlalchemy import func, select

from app.models.employee import Employee
from app.models.registration_request import EmployeeRegistrationRequest
from app.models.user import User
from app.schemas.v1.registration import RegistrationSubmitRequest
from app.services.auth import EmailAlreadyExists, UsernameTaken
from app.services.registration import (
    InvalidOrganizationCode,
    RegistrationAlreadyPending,
    RegistrationPending,
    RegistrationRejected,
    RegistrationService,
    unique_organization_code,
)


def _payload(code: str, **over) -> RegistrationSubmitRequest:
    base = dict(
        organization_code=code,
        full_name="New Joiner",
        username="joiner1",
        email="joiner@acme.test",
        designation="Housekeeper",
        password="Passw0rd1",
    )
    base.update(over)
    return RegistrationSubmitRequest(**base)


async def test_verify_code_valid(session, seed):
    svc = RegistrationService(session)
    code = seed["company"].organization_code
    assert code and len(code) == 12  # model default generated it
    valid, name = await svc.verify_code(code)
    assert valid is True
    assert name == "Acme"


async def test_verify_code_case_insensitive(session, seed):
    svc = RegistrationService(session)
    valid, _ = await svc.verify_code(
        seed["company"].organization_code.lower()
    )
    assert valid is True


async def test_verify_code_invalid(session, seed):
    valid, name = await RegistrationService(session).verify_code(
        "ZZZZZZZZZZZZ"
    )
    assert valid is False
    assert name is None


async def test_submit_creates_pending_request_only(session, seed):
    code = seed["company"].organization_code
    req, org_name = await RegistrationService(session).submit(
        _payload(code)
    )
    assert org_name == "Acme"
    assert req.status == "pending"
    assert req.company_id == seed["company"].id
    assert req.password_hash.startswith("$argon2")
    assert "Passw0rd1" not in req.password_hash
    # No account artifacts — the request row is all that exists.
    assert await session.scalar(
        select(func.count(User.id)).where(User.username == "joiner1")
    ) == 0
    assert await session.scalar(
        select(func.count(Employee.id)).where(Employee.name == "New Joiner")
    ) == 0


async def test_submit_invalid_code_rejected(session, seed):
    with pytest.raises(InvalidOrganizationCode):
        await RegistrationService(session).submit(
            _payload("ZZZZZZZZZZZZ")
        )


async def test_submit_duplicate_pending_blocked(session, seed):
    code = seed["company"].organization_code
    svc = RegistrationService(session)
    await svc.submit(_payload(code))
    with pytest.raises(RegistrationAlreadyPending):
        await svc.submit(_payload(code))


async def test_submit_after_rejection_allowed(session, seed):
    code = seed["company"].organization_code
    svc = RegistrationService(session)
    req, _ = await svc.submit(_payload(code))
    req.status = "rejected"
    await session.commit()
    req2, _ = await svc.submit(_payload(code))
    assert req2.status == "pending" and req2.id != req.id


async def test_submit_existing_account_email_blocked(session, seed):
    with pytest.raises(EmailAlreadyExists):
        await RegistrationService(session).submit(
            _payload(
                seed["company"].organization_code, email="admin@acme.test"
            )
        )


async def test_submit_existing_username_blocked(session, seed):
    with pytest.raises(UsernameTaken):
        await RegistrationService(session).submit(
            _payload(seed["company"].organization_code, username="admin")
        )


async def test_login_status_pending_with_correct_password(session, seed):
    svc = RegistrationService(session)
    await svc.submit(_payload(seed["company"].organization_code))
    err = await svc.login_status("joiner@acme.test", "Passw0rd1")
    assert isinstance(err, RegistrationPending)
    # Same lookup by username works too.
    err = await svc.login_status("joiner1", "Passw0rd1")
    assert isinstance(err, RegistrationPending)


async def test_login_status_wrong_password_leaks_nothing(session, seed):
    svc = RegistrationService(session)
    await svc.submit(_payload(seed["company"].organization_code))
    assert await svc.login_status("joiner@acme.test", "wrong-pass") is None
    # Unknown identifier entirely → same nothing.
    assert await svc.login_status("nobody@x.test", "Passw0rd1") is None


async def test_login_status_rejected_includes_reason(session, seed):
    svc = RegistrationService(session)
    req, _ = await svc.submit(_payload(seed["company"].organization_code))
    req.status = "rejected"
    req.rejection_reason = "Position filled"
    await session.commit()
    err = await svc.login_status("joiner@acme.test", "Passw0rd1")
    assert isinstance(err, RegistrationRejected)
    assert "Position filled" in err.message


async def test_login_status_approved_returns_none(session, seed):
    svc = RegistrationService(session)
    req, _ = await svc.submit(_payload(seed["company"].organization_code))
    req.status = "approved"
    await session.commit()
    assert await svc.login_status("joiner@acme.test", "Passw0rd1") is None


async def test_unique_organization_code_never_collides(session, seed):
    c1 = await unique_organization_code(session)
    c2 = await unique_organization_code(session)
    assert c1 != c2 and c1 != seed["company"].organization_code
