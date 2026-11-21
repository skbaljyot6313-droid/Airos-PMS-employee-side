"""payroll phase 2 — line payment fields, half-day groups, leave ledger, holidays

Revision ID: g8c3e0f5b2d9
Revises: f7b2d9e4a1c8

Mirrored byte-for-byte in the employee backend chain (shared alembic_version).
"""
from alembic import op
import sqlalchemy as sa

revision = "g8c3e0f5b2d9"
down_revision = "f7b2d9e4a1c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payroll_lines", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payroll_lines", sa.Column("payment_method", sa.String(32), nullable=True))
    op.add_column("payroll_lines", sa.Column("payment_reference", sa.String(120), nullable=True))
    op.add_column("payroll_lines", sa.Column("paid_by_name", sa.String(255), nullable=True))

    op.create_table(
        "payroll_half_day_groups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("period_id", sa.Uuid(), sa.ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_index", sa.Integer(), nullable=False),
        sa.Column("dates", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=True),
        sa.Column("cl_balance_at_decision", sa.Integer(), nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_name", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("period_id", "employee_id", "group_index", name="uq_half_day_groups_emp_index"),
        sa.CheckConstraint("decision IS NULL OR decision IN ('cl', 'lop', 'cl_short')", name="ck_half_day_groups_decision"),
    )
    op.create_index("ix_payroll_half_day_groups_period_id", "payroll_half_day_groups", ["period_id"])
    op.create_index("ix_payroll_half_day_groups_employee_id", "payroll_half_day_groups", ["employee_id"])

    op.create_table(
        "leave_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("leave_type", sa.String(16), nullable=False),
        sa.Column("delta", sa.Numeric(6, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reference_type", sa.String(32), nullable=True),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("delta <> 0", name="ck_leave_ledger_nonzero"),
    )
    op.create_index("ix_leave_ledger_employee_id", "leave_ledger", ["employee_id"])

    op.create_table(
        "holidays",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("property_id", sa.Uuid(), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_by_name", sa.String(255), nullable=True),
        sa.UniqueConstraint("property_id", "date", name="uq_holidays_property_date"),
    )
    op.create_index("ix_holidays_property_id", "holidays", ["property_id"])


def downgrade() -> None:
    op.drop_table("holidays")
    op.drop_table("leave_ledger")
    op.drop_table("payroll_half_day_groups")
    for col in ("paid_by_name", "payment_reference", "payment_method", "paid_at"):
        op.drop_column("payroll_lines", col)
