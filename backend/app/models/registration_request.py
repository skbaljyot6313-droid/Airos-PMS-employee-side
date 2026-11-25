"""EmployeeRegistrationRequest — pending self-service employee sign-ups.

Written by the employee backend's public registration endpoint (property
org code verified server-side — the client never supplies a company or
property id) and decided by the super-admin backend's approval surface.
The row IS the audit trail: decided requests are never deleted.

``password_hash`` is Argon2id — computed at submission so a plaintext
password never touches the database or the request row. On approval the
hash moves verbatim onto the new ``users`` row.

Status lifecycle: pending → approved | rejected. Decision writes are
conditional UPDATEs (``status='pending'``) so concurrent approvals can
never double-create the employee.

Shared schema — this file is mirrored byte-for-byte in the employee
backend repo (single alembic_version row); edit both together.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

REGISTRATION_STATUSES = ("pending", "approved", "rejected")
SALARY_FREQUENCIES = ("monthly", "daily", "hourly")


class EmployeeRegistrationRequest(Base):
    __tablename__ = "employee_registration_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    # Resolved server-side from the organization code — never trusted
    # from the client payload. The code lives on the PROPERTY, so both
    # scoping columns are known at submission.
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Set at submission — the property the applicant's code belongs to.
    # The admin may still override placement at approval.
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )

    # --- Personal ------------------------------------------------------
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    date_of_birth: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # YYYY-MM-DD
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- Employment ----------------------------------------------------
    designation: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # → employees.job_title on approval
    department: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # free text — linked to departments at approval
    employment_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    joining_date: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # YYYY-MM-DD → employees.start_date
    reporting_manager: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # request metadata only — employees has no manager column

    # --- Compensation (masked to non-privileged readers) ---------------
    salary: Mapped[str | None] = mapped_column(String(64), nullable=True)
    salary_frequency: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )  # → salary_structures.calc_method on approval

    # --- Credentials ---------------------------------------------------
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Snapshot of the property's code used — survives later code
    # rotation so the audit record keeps WHICH code admitted this
    # request.
    organization_code: Mapped[str] = mapped_column(
        String(12), nullable=False
    )

    # --- Review outcome ------------------------------------------------
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    created_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    created_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_employee_reg_requests_status",
        ),
        CheckConstraint(
            "salary_frequency IS NULL OR "
            "salary_frequency IN ('monthly', 'daily', 'hourly')",
            name="ck_employee_reg_requests_salary_frequency",
        ),
        Index("ix_err_company_status", "company_id", "status"),
        Index("ix_err_company_created", "company_id", "created_at"),
        Index("ix_err_email", "email"),
        Index("ix_err_username", "username"),
        # One OPEN request per identifier per company — partial unique
        # indexes on both supported dialects (decided rows stop blocking
        # re-registration with the same email/username).
        Index(
            "uq_err_pending_email",
            "company_id", func.lower(email),
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index(
            "uq_err_pending_username",
            "company_id", func.lower(username),
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )
