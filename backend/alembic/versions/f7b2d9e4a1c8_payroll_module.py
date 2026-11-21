"""payroll module — policies, salary structures, periods, lines, adjustments

Revision ID: f7b2d9e4a1c8
Revises: e6a3c9f1b8d4

Mirrored byte-for-byte in the employee backend chain (shared alembic_version).
"""
from alembic import op
import sqlalchemy as sa

revision = "f7b2d9e4a1c8"
down_revision = "e6a3c9f1b8d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payroll_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", sa.Uuid(), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("effective_from", sa.String(10), nullable=False),
        sa.Column("effective_until", sa.String(10), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("effective_until IS NULL OR effective_until >= effective_from", name="ck_payroll_policies_range"),
    )
    op.create_index("ix_payroll_policies_company_id", "payroll_policies", ["company_id"])
    op.create_index("ix_payroll_policies_property_id", "payroll_policies", ["property_id"])

    op.create_table(
        "salary_structures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", sa.Uuid(), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("calc_method", sa.String(16), nullable=False),
        sa.Column("effective_from", sa.String(10), nullable=False),
        sa.Column("effective_until", sa.String(10), nullable=True),
        sa.Column("basic", sa.Numeric(12, 2), nullable=False),
        sa.Column("hra", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("allowances", sa.JSON(), nullable=False),
        sa.Column("incentive", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("overtime_rate", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("deductions", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("calc_method IN ('monthly', 'daily', 'hourly')", name="ck_salary_structures_method"),
        sa.CheckConstraint("effective_until IS NULL OR effective_until >= effective_from", name="ck_salary_structures_range"),
        sa.CheckConstraint("basic >= 0 AND hra >= 0", name="ck_salary_structures_amounts"),
    )
    op.create_index("ix_salary_structures_employee_id", "salary_structures", ["employee_id"])
    op.create_index("ix_salary_structures_property_id", "salary_structures", ["property_id"])
    op.create_index("ix_salary_structures_employee_from", "salary_structures", ["employee_id", "effective_from"])

    op.create_table(
        "payroll_periods",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("property_id", sa.Uuid(), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("policy_id", sa.Uuid(), sa.ForeignKey("payroll_policies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submitted_by_name", sa.String(255), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by_name", sa.String(255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_by_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("property_id", "period", name="uq_payroll_periods_property_period"),
        sa.CheckConstraint("status IN ('open', 'submitted', 'approved', 'paid')", name="ck_payroll_periods_status"),
        sa.CheckConstraint("period LIKE '____-__'", name="ck_payroll_periods_format"),
    )
    op.create_index("ix_payroll_periods_company_id", "payroll_periods", ["company_id"])
    op.create_index("ix_payroll_periods_property_id", "payroll_periods", ["property_id"])

    op.create_table(
        "payroll_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("period_id", sa.Uuid(), sa.ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_name", sa.String(255), nullable=False),
        sa.Column("structure_id", sa.Uuid(), sa.ForeignKey("salary_structures.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="calculated"),
        sa.Column("gross", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_deductions", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("net", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("period_id", "employee_id", name="uq_payroll_lines_period_employee"),
        sa.CheckConstraint("status IN ('calculated', 'needs_review', 'approved', 'paid')", name="ck_payroll_lines_status"),
    )
    op.create_index("ix_payroll_lines_period_id", "payroll_lines", ["period_id"])
    op.create_index("ix_payroll_lines_employee_id", "payroll_lines", ["employee_id"])

    op.create_table(
        "payroll_adjustments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("line_id", sa.Uuid(), sa.ForeignKey("payroll_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount <> 0", name="ck_payroll_adjustments_nonzero"),
    )
    op.create_index("ix_payroll_adjustments_line_id", "payroll_adjustments", ["line_id"])


def downgrade() -> None:
    op.drop_table("payroll_adjustments")
    op.drop_table("payroll_lines")
    op.drop_table("payroll_periods")
    op.drop_table("salary_structures")
    op.drop_table("payroll_policies")
