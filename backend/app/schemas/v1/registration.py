"""Employee self-registration DTOs — public /registration endpoints.

The client NEVER supplies a company identifier: the organization is
resolved server-side from ``organization_code`` alone.
"""
import re
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[\d\s\-()]{8,20}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$")
SALARY_RE = re.compile(r"^\d{1,9}(\.\d{1,2})?$")
ORG_CODE_RE = re.compile(r"^[A-Za-z2-9]{12}$")

EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "intern", "temporary")
GENDERS = ("male", "female", "other", "prefer_not_to_say")
SALARY_FREQUENCIES = ("monthly", "daily", "hourly")


def _date_or_none(v: str | None, field: str) -> str | None:
    if v is None or v.strip() == "":
        return None
    v = v.strip()
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"Enter a valid {field} (YYYY-MM-DD).")
    return v


class VerifyCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class DepartmentOption(BaseModel):
    uid: str
    name: str


class VerifyCodeResponse(BaseModel):
    valid: bool
    organization_name: str | None = None
    property_name: str | None = None
    # Active departments of the resolved property — the registration
    # form's department dropdown options. Empty when none are defined.
    departments: list[DepartmentOption] = []


class RegistrationSubmitRequest(BaseModel):
    """One-shot submission — personal + employment + account details and
    the organization code arrive together; the company is resolved from
    the code server-side."""

    # organization
    organization_code: str = Field(min_length=12, max_length=12)

    # personal
    full_name: str = Field(min_length=1, max_length=255)
    email: str = Field(max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    date_of_birth: str | None = Field(default=None, max_length=10)
    gender: str | None = Field(default=None, max_length=32)

    # employment
    designation: str = Field(min_length=1, max_length=255)
    department: str | None = Field(default=None, max_length=100)
    employment_type: str | None = Field(default=None, max_length=32)
    joining_date: str | None = Field(default=None, max_length=10)
    reporting_manager: str | None = Field(default=None, max_length=255)

    # compensation
    salary: str | None = Field(default=None, max_length=64)
    salary_frequency: str | None = Field(default=None, max_length=16)

    # account
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str | None = Field(default=None, max_length=128)

    @field_validator("organization_code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip().upper()
        if not ORG_CODE_RE.match(v):
            raise ValueError(
                "Organization code must be exactly 12 characters "
                "(uppercase letters and numbers)."
            )
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError(
                "Username must be 3-100 characters: letters, numbers, "
                "dots, dashes or underscores."
            )
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        v = v.strip()
        if not PHONE_RE.match(v):
            raise ValueError("Enter a valid phone number.")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v: str | None) -> str | None:
        return _date_or_none(v, "date of birth")

    @field_validator("joining_date")
    @classmethod
    def _joining(cls, v: str | None) -> str | None:
        return _date_or_none(v, "joining date")

    @field_validator("gender")
    @classmethod
    def _gender(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        v = v.strip().lower()
        if v not in GENDERS:
            raise ValueError("Select a valid gender option.")
        return v

    @field_validator("employment_type")
    @classmethod
    def _employment_type(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        v = v.strip().lower()
        if v not in EMPLOYMENT_TYPES:
            raise ValueError("Select a valid employment type.")
        return v

    @field_validator("salary")
    @classmethod
    def _salary(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        v = v.strip()
        if not SALARY_RE.match(v):
            raise ValueError("Enter a valid salary amount.")
        return v

    @field_validator("salary_frequency")
    @classmethod
    def _frequency(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        v = v.strip().lower()
        if v not in SALARY_FREQUENCIES:
            raise ValueError("Select a valid salary frequency.")
        return v

    @field_validator("full_name", "designation", "department",
                     "reporting_manager")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _cross(self):
        if (
            self.confirm_password is not None
            and self.confirm_password != self.password
        ):
            raise ValueError("Passwords do not match.")
        if not any(c.isalpha() for c in self.password) or not any(
            c.isdigit() for c in self.password
        ):
            raise ValueError(
                "Password must contain at least one letter and one number."
            )
        if self.salary and not self.salary_frequency:
            raise ValueError(
                "Select a salary frequency when a salary is provided."
            )
        return self


class RegistrationSubmitResponse(BaseModel):
    request_uid: str
    status: str
    organization_name: str
    property_name: str | None = None
