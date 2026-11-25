"""RegistrationService — public employee self-registration.

Two surfaces:

* ``verify_code`` / ``submit`` — the unauthenticated mobile flow. The
  company is resolved from the organization code ALONE; a submitted
  request lands in ``employee_registration_requests`` as ``pending``.
  No user account, no tokens, no API access is created here — approval
  in the Super Admin app is what materializes the employee.

* ``login_status`` — called by AuthService.login when credential
  verification fails. When the identifier matches a pending/rejected
  request AND the supplied password verifies against the stored
  Argon2id hash, the caller gets a precise status error instead of
  INVALID_CREDENTIALS. The password check is what makes this safe:
  it tells an applicant "your request is still being reviewed" while
  leaking nothing to someone who merely guesses an email.

Admins are notified of new requests through the shared realtime channel
(``priv:prop:{uid}:employees`` — one event per company property) and the
pending-count endpoint; decided applicants learn the outcome at their
next login attempt (and via the notifications feed once approved).
"""

import asyncio
import uuid

from fastapi import status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.centrifugo import prop_channel, queue_event
from app.core.exceptions import AppError
from app.core.security import (
    generate_organization_code,
    hash_password,
    normalize_organization_code,
    verify_password,
)
from app.models.audit import AuditEvent
from app.models.company import Company
from app.models.property import Property
from app.models.registration_request import EmployeeRegistrationRequest
from app.repositories.company import CompanyRepository
from app.repositories.user import UserRepository
from app.schemas.v1.registration import RegistrationSubmitRequest
from app.services.auth import EmailAlreadyExists, UsernameTaken


class RegistrationError(AppError):
    pass


class InvalidOrganizationCode(RegistrationError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "INVALID_ORGANIZATION_CODE"
    message = (
        "The organization code is invalid. Check the code with your "
        "administrator and try again."
    )


class RegistrationAlreadyPending(RegistrationError):
    status_code = status.HTTP_409_CONFLICT
    code = "REGISTRATION_ALREADY_PENDING"
    message = (
        "A registration request is already pending for these details. "
        "Please wait for your administrator's decision."
    )


class RegistrationPending(RegistrationError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "REGISTRATION_PENDING"
    message = (
        "Your registration is awaiting approval from your organization's "
        "administrator. You'll be able to sign in once it's approved."
    )


class RegistrationRejected(RegistrationError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "REGISTRATION_REJECTED"
    message = "Your registration request was not approved."


async def unique_organization_code(session: AsyncSession) -> str:
    """Generate a code that doesn't collide with any company's."""
    for _ in range(20):
        code = generate_organization_code()
        exists = await session.scalar(
            select(Company.id).where(Company.organization_code == code)
        )
        if exists is None:
            return code
    # 32^12 codes — reaching this means something is deeply wrong.
    raise RuntimeError("Could not allocate a unique organization code.")


class RegistrationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.users = UserRepository(session)
        self.companies = CompanyRepository(session)

    async def _company_for_code(self, code: str) -> Company | None:
        res = await self.session.execute(
            select(Company).where(
                Company.organization_code
                == normalize_organization_code(code),
                Company.is_active.is_(True),
            )
        )
        return res.scalar_one_or_none()

    async def verify_code(self, code: str) -> tuple[bool, str | None]:
        company = await self._company_for_code(code)
        return (company is not None, company.company_name if company else None)

    async def submit(
        self, payload: RegistrationSubmitRequest
    ) -> tuple[EmployeeRegistrationRequest, str]:
        company = await self._company_for_code(payload.organization_code)
        if company is None:
            raise InvalidOrganizationCode()

        email = payload.email.strip().lower()
        username = payload.username.strip().lower()

        # Account-level uniqueness — the eventual users table constraints
        # would reject anyway; report it BEFORE the admin ever sees a
        # request that could never be approved.
        if await self.users.get_by_email(email):
            raise EmailAlreadyExists(field="email")
        if await self.users.username_exists(username):
            raise UsernameTaken(field="username")

        # Request-level uniqueness — one OPEN request per identifier per
        # company (also enforced by the partial unique indexes; the query
        # gives a friendlier error than an IntegrityError).
        dup = await self.session.execute(
            select(EmployeeRegistrationRequest.id).where(
                EmployeeRegistrationRequest.company_id == company.id,
                EmployeeRegistrationRequest.status == "pending",
                or_(
                    func.lower(EmployeeRegistrationRequest.email) == email,
                    func.lower(EmployeeRegistrationRequest.username)
                    == username,
                ),
            )
        )
        if dup.scalar_one_or_none() is not None:
            raise RegistrationAlreadyPending()

        # Argon2id off the event loop — same treatment as login verify.
        password_hash = await asyncio.to_thread(
            hash_password, payload.password
        )

        req = EmployeeRegistrationRequest(
            company_id=company.id,
            status="pending",
            full_name=payload.full_name.strip(),
            username=username,
            email=email,
            phone=payload.phone,
            date_of_birth=payload.date_of_birth,
            gender=payload.gender,
            designation=payload.designation.strip(),
            department=(
                payload.department.strip() if payload.department else None
            ),
            employment_type=payload.employment_type,
            joining_date=payload.joining_date,
            reporting_manager=(
                payload.reporting_manager.strip()
                if payload.reporting_manager
                else None
            ),
            salary=payload.salary,
            salary_frequency=payload.salary_frequency,
            password_hash=password_hash,
            organization_code=company.organization_code,
        )
        self.session.add(req)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise RegistrationAlreadyPending() from exc

        # Admin-facing audit + realtime hint — the request row itself is
        # the durable record; the event just prompts open dashboards.
        self.session.add(AuditEvent(
            property_id=None,
            actor_user_id=None,
            actor_name="self-registration",
            entity_type="employee_registration",
            entity_id=req.id,
            entity_name=req.full_name,
            action="submitted",
            detail={
                "company_uid": str(company.id),
                "email": req.email,
                "username": req.username,
            },
        ))

        prop_ids = list(
            (
                await self.session.execute(
                    select(Property.id).where(
                        Property.company_id == company.id
                    )
                )
            ).scalars()
        )
        for pid in prop_ids:
            queue_event(
                self.session,
                prop_channel(pid, "employees"),
                "employee_request.submitted",
                {
                    "request_uid": str(req.id),
                    "company_uid": str(company.id),
                    "full_name": req.full_name,
                },
            )
        await self.session.commit()
        await self.session.refresh(req)
        return req, company.company_name

    async def login_status(
        self, identifier: str, password: str
    ) -> RegistrationError | None:
        """Decided-request status for a FAILED login attempt.

        Returns a status error ONLY when the supplied password verifies
        against the stored request hash — applicants see exactly what
        happened to their request; everyone else still gets the uniform
        INVALID_CREDENTIALS (no enumeration)."""
        ident = identifier.strip().lower()
        res = await self.session.execute(
            select(EmployeeRegistrationRequest)
            .where(
                or_(
                    func.lower(EmployeeRegistrationRequest.email) == ident,
                    func.lower(EmployeeRegistrationRequest.username) == ident,
                )
            )
            .order_by(EmployeeRegistrationRequest.created_at.desc())
            .limit(1)
        )
        req = res.scalar_one_or_none()
        if req is None or req.status == "approved":
            return None
        verified = await asyncio.to_thread(
            verify_password, password, req.password_hash
        )
        if not verified:
            return None
        if req.status == "pending":
            return RegistrationPending()
        err = RegistrationRejected()
        if req.rejection_reason:
            err = RegistrationRejected(
                f"Your registration request was not approved. "
                f"Reason: {req.rejection_reason}"
            )
        return err
