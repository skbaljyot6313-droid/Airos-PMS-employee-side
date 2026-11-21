"""Payroll — policies, salary structures, periods, lines and adjustments.

Shared schema: the employee backend mirrors this module (read-only use) and
carries an identical migration revision. Money is NUMERIC(12,2). Operational
dates are IST 'YYYY-MM-DD' strings like attendance_days.

Immutability: a payroll_line snapshots the structure, policy and metrics it was
calculated from. Once its period is approved, lines are never recalculated;
corrections are rows in payroll_adjustments.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

CALC_METHODS = ("monthly", "daily", "hourly")
PERIOD_STATUSES = ("open", "submitted", "approved", "paid")
LINE_STATUSES = ("calculated", "needs_review")
FINAL_PERIOD_STATUSES = ("approved", "paid")
GROUP_DECISIONS = ("cl", "lop")


class PayrollPolicy(Base):
    __tablename__ = "payroll_policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    effective_from: Mapped[str] = mapped_column(String(10), nullable=False)
    effective_until: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Every rule lives here. Validated by services/payroll.py::validate_policy;
    # nothing is assumed when a key is absent.
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_payroll_policies_range",
        ),
    )


class SalaryStructure(Base):
    """One revision of an employee's pay. History = all rows, by effective_from.
    Rows are never edited after creation; a revision ends the previous one."""

    __tablename__ = "salary_structures"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    calc_method: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_from: Mapped[str] = mapped_column(String(10), nullable=False)
    effective_until: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # monthly: amounts per month. daily: amounts per paid day.
    # hourly: amounts per paid hour.
    basic: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    hra: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    allowances: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    incentive: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    overtime_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # [{code: PF|ESI|TDS|other, mode: percent|fixed, value, ceiling?, basis: basic|gross}]
    # Opt-in only: an empty list means no statutory deduction applies.
    deductions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "calc_method IN ('monthly', 'daily', 'hourly')",
            name="ck_salary_structures_method",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_salary_structures_range",
        ),
        CheckConstraint("basic >= 0 AND hra >= 0", name="ck_salary_structures_amounts"),
        Index("ix_salary_structures_employee_from", "employee_id", "effective_from"),
    )


class PayrollPeriod(Base):
    __tablename__ = "payroll_periods"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("payroll_policies.id", ondelete="SET NULL"), nullable=True
    )
    submitted_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approved_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("property_id", "period", name="uq_payroll_periods_property_period"),
        CheckConstraint(
            "status IN ('open', 'submitted', 'approved', 'paid')",
            name="ck_payroll_periods_status",
        ),
        CheckConstraint("period LIKE '____-__'", name="ck_payroll_periods_format"),
    )


class PayrollLine(Base):
    __tablename__ = "payroll_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True, index=True
    )
    employee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    structure_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("salary_structures.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="calculated")
    gross: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    net: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # Full calculation trace: metrics, earnings and deduction components with
    # their basis, anomalies, and the structure/policy snapshot.
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Per-line payment record (set by mark_paid or an individual pay call).
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    paid_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("period_id", "employee_id", name="uq_payroll_lines_period_employee"),
        CheckConstraint(
            "status IN ('calculated', 'needs_review', 'approved', 'paid')",
            name="ck_payroll_lines_status",
        ),
    )


class PayrollHalfDayGroup(Base):
    """One group of 3 half-day dates awaiting or holding an admin decision.

    'cl' consumes one Casual Leave; 'lop' deducts one full working day.
    Dates are recorded so a group can never be processed twice and every
    deduction traces back to its attendance days."""

    __tablename__ = "payroll_half_day_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_index: Mapped[int] = mapped_column(Integer, nullable=False)
    dates: Mapped[list] = mapped_column(JSON, nullable=False)  # exactly 3 'YYYY-MM-DD'
    # NULL = pending; 'cl' decided CL; 'lop' decided LOP;
    # 'cl_short' = CL chosen but balance insufficient (flagged).
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cl_balance_at_decision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("period_id", "employee_id", "group_index",
                         name="uq_half_day_groups_emp_index"),
        CheckConstraint(
            "decision IS NULL OR decision IN ('cl', 'lop', 'cl_short')",
            name="ck_half_day_groups_decision",
        ),
    )


class LeaveLedger(Base):
    """Append-only leave balance ledger. CL consumed by the half-day rule and
    opening balances live here; balance = employees.leave_balance_days (opening)
    + SUM(delta). A consumed entry references its half-day group."""

    __tablename__ = "leave_ledger"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    leave_type: Mapped[str] = mapped_column(String(16), nullable=False)  # CL|SL|EL|LWP|other
    delta: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("delta <> 0", name="ck_leave_ledger_nonzero"),
    )


class Holiday(Base):
    """Company-declared holiday per property — used by payroll day
    classification and shown in the payroll table."""

    __tablename__ = "holidays"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("property_id", "date", name="uq_holidays_property_date"),
    )


class PayrollAdjustment(Base):
    """Append-only correction to an approved line. Never edits the snapshot."""

    __tablename__ = "payroll_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payroll_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_payroll_adjustments_nonzero"),
    )
