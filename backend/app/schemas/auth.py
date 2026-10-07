"""
Auth DTOs. Response shapes intentionally match the frontend's
`AuthUser` / `Company` TypeScript types (see frontend/src/types.ts):
uid-style keys, snake_case, role as lowercase string.
"""

import re
import uuid
from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.user import UserRole

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PIN_RE = re.compile(r"^\d{6}$")
PHONE_RE = re.compile(r"^\+?[\d\s\-()]{8,20}$")


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    brand_name: str = Field(min_length=1, max_length=255)
    address: str = Field(min_length=1, max_length=500)
    pin_code: str
    email: str
    phone: str = Field(validation_alias=AliasChoices("phone", "phone_number"))
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str | None = Field(default=None, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("pin_code")
    @classmethod
    def _pin(cls, v: str) -> str:
        v = v.strip()
        if not PIN_RE.match(v):
            raise ValueError("Enter a valid 6-digit PIN code.")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if not PHONE_RE.match(v):
            raise ValueError("Enter a valid phone number.")
        return v

    @model_validator(mode="after")
    def _passwords_match(self):
        if self.confirm_password is not None and self.confirm_password != self.password:
            raise ValueError("Passwords do not match.")
        return self


class LoginRequest(BaseModel):
    """`identifier` accepts an email OR a username."""

    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class UpdateProfileRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(
        default=None, validation_alias=AliasChoices("phone", "phone_number")
    )
    email: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v


# ---------------------------------------------------------------------------
# Responses — shaped to the frontend's AuthUser / Company types
# ---------------------------------------------------------------------------

class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_uid: str
    name: str
    legal_name: str | None = None
    brand_name: str
    email: str
    phone: str
    address: str | None = None
    pin_code: str | None = None
    operational_day_start: str = "06:00"
    created_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uid: str
    name: str
    email: str
    username: str
    role: UserRole
    company_uid: str
    property_uid: str | None = None
    employee_uid: str | None = None
    zone_uid: str | None = None
    phone: str | None = None
    job_title: str | None = None
    company_name: str | None = None


class AuthResponse(BaseModel):
    """Login/signup payload consumed by the frontend auth layer."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut
    company: CompanyOut


class MeResponse(BaseModel):
    user: UserOut
    company: CompanyOut


class TokenRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Serialization helpers — ORM → DTO
# ---------------------------------------------------------------------------

def company_to_out(company) -> CompanyOut:
    return CompanyOut(
        company_uid=str(company.id),
        name=company.company_name,
        legal_name=company.legal_name,
        brand_name=company.brand_name,
        email=company.email,
        phone=company.phone_number,
        address=company.address,
        pin_code=company.pin_code,
        operational_day_start=company.operational_day_start or "06:00",
        created_at=company.created_at,
    )


def user_to_out(user) -> UserOut:
    return UserOut(
        uid=str(user.id),
        name=user.name,
        email=user.email,
        username=user.username,
        role=user.role,
        company_uid=str(user.company_id),
        property_uid=str(user.property_id) if user.property_id else None,
        employee_uid=str(user.employee_id) if user.employee_id else None,
        zone_uid=str(user.zone_id) if user.zone_id else None,
        phone=user.phone_number,
        job_title=user.job_title,
        company_name=user.company.company_name if getattr(user, "company", None) else None,
    )


def opt_uuid(v: str | uuid.UUID | None) -> uuid.UUID | None:
    return uuid.UUID(str(v)) if v else None
