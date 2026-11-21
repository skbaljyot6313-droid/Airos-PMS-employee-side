"""departments + employee department_id + transfer history

Adds property-scoped departments (with optional head employee),
`employees.department_id` (dual-written alongside the legacy free-text
`department` column), and the append-only `department_transfers` log.

Revision ID: d4f1b8a3e7c2
Revises: b7e4f9a1c5d3
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f1b8a3e7c2"
down_revision = "b7e4f9a1c5d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "departments",
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
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("code", sa.String(32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "head_employee_id",
            sa.Uuid(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "property_id", "name", name="uq_departments_property_name"
        ),
        sa.Index("ix_departments_property_status", "property_id", "status"),
        sa.Index("ix_departments_property_id", "property_id"),
    )

    op.add_column(
        "employees",
        sa.Column("department_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_employees_department_id",
        "employees",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_employees_department_id", "employees", ["department_id"])

    op.create_table(
        "department_transfers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            sa.Uuid(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_department_id",
            sa.Uuid(),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_department_name", sa.String(120), nullable=True),
        sa.Column(
            "to_department_id",
            sa.Uuid(),
            sa.ForeignKey("departments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("to_department_name", sa.String(120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "changed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("changed_by_name", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Index("ix_dept_transfers_property_time", "property_id", "created_at"),
        sa.Index("ix_department_transfers_employee", "employee_id"),
        sa.Index("ix_department_transfers_property", "property_id"),
    )


def downgrade() -> None:
    op.drop_table("department_transfers")
    op.drop_index("ix_employees_department_id", table_name="employees")
    op.drop_constraint(
        "fk_employees_department_id", "employees", type_="foreignkey"
    )
    op.drop_column("employees", "department_id")
    op.drop_table("departments")
