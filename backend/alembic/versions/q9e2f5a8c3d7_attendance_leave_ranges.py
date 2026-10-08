"""Attendance requests — single-date filings → inclusive DATE RANGES.

`attendance_requests` gains from_date/to_date/request_category/
leave_type/requested_days, backfilled from (attendance_date,
request_type): week_off rows stay 'week_off', 'holiday' becomes
category 'leave' with leave_type 'other' (historical test rows only).

`attendance_days.status` vocab swaps 'holiday' → 'leave' (existing
rows rewritten first, then the CHECK is recreated).

Overlap of open (pending/approved) ranges gets a PostgreSQL backstop:
a generated `leave_range daterange` + btree_gist EXCLUDE constraint —
gated on the dialect so sqlite test environments stay valid (the
app-level inclusive-overlap check covers correctness there).

Revision ID: q9e2f5a8c3d7
Revises: p8d1f4a7c2e5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q9e2f5a8c3d7"
down_revision: Union[str, Sequence[str], None] = "p8d1f4a7c2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DAYS_CHECK_NEW = (
    "status IN ('present', 'absent', 'week_off', 'leave')"
)
DAYS_CHECK_OLD = (
    "status IN ('present', 'absent', 'week_off', 'holiday')"
)
LEAVE_TYPE_CHECK = (
    "(request_category = 'leave' AND leave_type IS NOT NULL "
    "AND leave_type IN "
    "('casual_leave', 'sick_leave', 'paid_leave', 'unpaid_leave', "
    "'other')) OR "
    "(request_category = 'week_off' AND leave_type IS NULL)"
)


def upgrade() -> None:
    # --- new range columns (nullable until the backfill lands) ---------
    op.add_column(
        "attendance_requests",
        sa.Column("from_date", sa.String(10), nullable=True),
    )
    op.add_column(
        "attendance_requests",
        sa.Column("to_date", sa.String(10), nullable=True),
    )
    op.add_column(
        "attendance_requests",
        sa.Column("request_category", sa.String(16), nullable=True),
    )
    op.add_column(
        "attendance_requests",
        sa.Column("leave_type", sa.String(32), nullable=True),
    )
    op.add_column(
        "attendance_requests",
        sa.Column("requested_days", sa.Integer(), nullable=True),
    )

    # --- backfill: a single-date filing is a one-day range -------------
    op.execute(
        """
        UPDATE attendance_requests SET
            from_date = attendance_date,
            to_date = attendance_date,
            requested_days = 1,
            request_category = CASE
                WHEN request_type = 'week_off' THEN 'week_off'
                ELSE 'leave'
            END,
            leave_type = CASE
                WHEN request_type = 'week_off' THEN NULL
                ELSE 'other'
            END
        """
    )
    for col in ("from_date", "to_date", "request_category",
                "requested_days"):
        op.alter_column("attendance_requests", col, nullable=False)

    # --- drop the single-date shape ------------------------------------
    op.drop_index("uq_request_open", table_name="attendance_requests")
    op.drop_index(
        "ix_request_property_date", table_name="attendance_requests"
    )
    op.drop_constraint(
        "ck_attendance_requests_type", "attendance_requests",
        type_="check",
    )
    op.drop_column("attendance_requests", "attendance_date")
    op.drop_column("attendance_requests", "request_type")

    # --- range-model constraints + indexes ------------------------------
    op.create_check_constraint(
        "ck_attendance_requests_category", "attendance_requests",
        "request_category IN ('leave', 'week_off')",
    )
    op.create_check_constraint(
        "ck_attendance_requests_range", "attendance_requests",
        "from_date <= to_date",
    )
    op.create_check_constraint(
        "ck_attendance_requests_leave_type", "attendance_requests",
        LEAVE_TYPE_CHECK,
    )
    op.create_check_constraint(
        "ck_attendance_requests_days", "attendance_requests",
        "requested_days > 0",
    )
    op.create_index(
        "ix_request_property_from", "attendance_requests",
        ["property_id", "from_date"],
    )
    op.create_index(
        "ix_request_property_to", "attendance_requests",
        ["property_id", "to_date"],
    )

    # --- day-status vocab: 'holiday' → 'leave' ---------------------------
    op.execute(
        "UPDATE attendance_days SET status = 'leave' "
        "WHERE status = 'holiday'"
    )
    op.drop_constraint(
        "ck_attendance_days_status", "attendance_days", type_="check",
    )
    op.create_check_constraint(
        "ck_attendance_days_status", "attendance_days", DAYS_CHECK_NEW,
    )

    # --- PG-only inclusive-overlap backstop ------------------------------
    # Stock text→date casts are STABLE, so a generated column can't call
    # daterange() on the String(10) keys directly. `att_leave_range` is a
    # declared-IMMUTABLE wrapper — safe because the columns are strictly
    # 'YYYY-MM-DD' (ISO parses independent of DateStyle) — that yields
    # the '[)' span [from, to+1) ≡ the inclusive [from..to] range.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        op.execute(
            "CREATE OR REPLACE FUNCTION att_leave_range(text, text) "
            "RETURNS daterange LANGUAGE sql IMMUTABLE PARALLEL SAFE AS "
            "$$ SELECT daterange($1::date, $2::date + 1) $$"
        )
        op.execute(
            "ALTER TABLE attendance_requests "
            "ADD COLUMN leave_range daterange "
            "GENERATED ALWAYS AS "
            "(att_leave_range(from_date, to_date)) STORED"
        )
        op.execute(
            "ALTER TABLE attendance_requests "
            "ADD CONSTRAINT ex_request_no_overlap "
            "EXCLUDE USING gist ("
            "employee_id WITH =, leave_range WITH &&"
            ") WHERE (status IN ('pending', 'approved'))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE attendance_requests "
            "DROP CONSTRAINT IF EXISTS ex_request_no_overlap"
        )
        op.execute(
            "ALTER TABLE attendance_requests "
            "DROP COLUMN IF EXISTS leave_range"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS att_leave_range(text, text)"
        )

    op.drop_index(
        "ix_request_property_to", table_name="attendance_requests"
    )
    op.drop_index(
        "ix_request_property_from", table_name="attendance_requests"
    )
    for name in (
        "ck_attendance_requests_days",
        "ck_attendance_requests_leave_type",
        "ck_attendance_requests_range",
        "ck_attendance_requests_category",
    ):
        op.drop_constraint(name, "attendance_requests", type_="check")

    # --- restore the single-date shape -----------------------------------
    op.add_column(
        "attendance_requests",
        sa.Column("attendance_date", sa.String(10), nullable=True),
    )
    op.add_column(
        "attendance_requests",
        sa.Column("request_type", sa.String(16), nullable=True),
    )
    op.execute(
        """
        UPDATE attendance_requests SET
            attendance_date = from_date,
            request_type = CASE
                WHEN request_category = 'week_off' THEN 'week_off'
                ELSE 'holiday'
            END
        """
    )
    op.alter_column(
        "attendance_requests", "attendance_date", nullable=False
    )
    op.alter_column(
        "attendance_requests", "request_type", nullable=False
    )
    op.drop_column("attendance_requests", "requested_days")
    op.drop_column("attendance_requests", "leave_type")
    op.drop_column("attendance_requests", "request_category")
    op.drop_column("attendance_requests", "to_date")
    op.drop_column("attendance_requests", "from_date")
    op.create_check_constraint(
        "ck_attendance_requests_type", "attendance_requests",
        "request_type IN ('week_off', 'holiday')",
    )
    op.create_index(
        "uq_request_open", "attendance_requests",
        ["employee_id", "attendance_date"], unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
        sqlite_where=sa.text("status IN ('pending', 'approved')"),
    )
    op.create_index(
        "ix_request_property_date", "attendance_requests",
        ["property_id", "attendance_date"],
    )

    op.execute(
        "UPDATE attendance_days SET status = 'holiday' "
        "WHERE status = 'leave'"
    )
    op.drop_constraint(
        "ck_attendance_days_status", "attendance_days", type_="check",
    )
    op.create_check_constraint(
        "ck_attendance_days_status", "attendance_days", DAYS_CHECK_OLD,
    )
