"""organization codes + employee registration requests

Adds:

* ``companies.organization_code`` — a unique 12-character public code the
  employee mobile app uses to attach a registration request to a company.
  Backfilled for every existing company with a cryptographically random
  code (uppercase letters + digits, ambiguous O/0/I/1 excluded), then
  made NOT NULL + UNIQUE.
* ``employee_registration_requests`` — pending self-service employee
  registrations. The row stores an Argon2id password hash (never a
  plaintext password), the applicant's requested details, the review
  outcome, and the employee/user ids created on approval. Pending
  (company_id, email) and (company_id, username) pairs are unique via
  partial indexes — one open request per identifier per company.
* ``ck_notifications_type`` widened with ``registration_approved`` and
  ``registration_rejected`` so the shared feed can carry the decision.

Additive/backward-compatible. Shared schema: this revision must be
mirrored verbatim in the employee backend repo's chain — do NOT stamp
over it.

Revision ID: c9e7f2a4b8d1
Revises: b6e4f2a8d1c5
"""
import secrets
import string
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c9e7f2a4b8d1'
down_revision: Union[str, Sequence[str], None] = 'b6e4f2a8d1c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 32-char alphabet: A-Z + 2-9 (no O/0/I/1 — visually ambiguous).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

_TYPES_NEW = (
    "'task_assigned', 'task_reassigned', 'task_cancelled', "
    "'task_rescheduled', 'task_due_soon', 'task_overdue', "
    "'submission_approved', 'submission_disapproved', "
    "'ticket_assigned', 'ticket_disapproved', "
    "'registration_approved', 'registration_rejected'"
)
_TYPES_OLD = (
    "'task_assigned', 'task_reassigned', 'task_cancelled', "
    "'task_rescheduled', 'task_due_soon', 'task_overdue', "
    "'submission_approved', 'submission_disapproved', "
    "'ticket_assigned', 'ticket_disapproved'"
)


def _backfill_org_codes() -> None:
    """Give every existing company a unique code. The unique index is
    created AFTER this fill, so a collision here retries in Python."""
    bind = op.get_bind()
    used = set()
    ids = [
        row[0]
        for row in bind.execute(
            sa.text("SELECT id FROM companies WHERE organization_code IS NULL")
        )
    ]
    for company_id in ids:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
        while code in used:
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
        used.add(code)
        bind.execute(
            sa.text(
                "UPDATE companies SET organization_code = :code WHERE id = :id"
            ),
            {"code": code, "id": company_id},
        )


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("organization_code", sa.String(12), nullable=True),
    )
    _backfill_org_codes()
    op.alter_column("companies", "organization_code", nullable=False)
    op.create_unique_constraint(
        "uq_companies_organization_code", "companies", ["organization_code"]
    )

    op.create_table(
        "employee_registration_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            sa.Uuid(),
            sa.ForeignKey("properties.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("date_of_birth", sa.String(10), nullable=True),
        sa.Column("gender", sa.String(32), nullable=True),
        sa.Column("designation", sa.String(255), nullable=True),
        sa.Column("department", sa.String(100), nullable=True),
        sa.Column("employment_type", sa.String(32), nullable=True),
        sa.Column("joining_date", sa.String(10), nullable=True),
        sa.Column("reporting_manager", sa.String(255), nullable=True),
        sa.Column("salary", sa.String(64), nullable=True),
        sa.Column("salary_frequency", sa.String(16), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("organization_code", sa.String(12), nullable=False),
        sa.Column(
            "reviewed_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_by_name", sa.String(255), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column(
            "created_employee_id",
            sa.Uuid(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_employee_reg_requests_status",
        ),
        sa.CheckConstraint(
            "salary_frequency IS NULL OR "
            "salary_frequency IN ('monthly', 'daily', 'hourly')",
            name="ck_employee_reg_requests_salary_frequency",
        ),
    )
    op.create_index(
        "ix_err_company_status",
        "employee_registration_requests",
        ["company_id", "status"],
    )
    op.create_index(
        "ix_err_company_created",
        "employee_registration_requests",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_err_email", "employee_registration_requests", ["email"]
    )
    op.create_index(
        "ix_err_username", "employee_registration_requests", ["username"]
    )
    # One OPEN request per identifier per company — decided requests keep
    # history without blocking a future application. Partial indexes are
    # Postgres-only; the local SQLite dev schema simply skips them.
    op.create_index(
        "uq_err_pending_email",
        "employee_registration_requests",
        ["company_id", sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "uq_err_pending_username",
        "employee_registration_requests",
        ["company_id", sa.text("lower(username)")],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.drop_constraint("ck_notifications_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_type",
        "notifications",
        f"type IN ({_TYPES_NEW})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_notifications_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_type",
        "notifications",
        f"type IN ({_TYPES_OLD})",
    )

    op.drop_table("employee_registration_requests")

    op.drop_constraint(
        "uq_companies_organization_code", "companies", type_="unique"
    )
    op.drop_column("companies", "organization_code")
