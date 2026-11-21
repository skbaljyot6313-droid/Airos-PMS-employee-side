"""Employee salary — read-only, own records only.

Every route resolves the caller's employee_id from the bearer token. Lines are
returned only for finalized periods (approved or paid); drafts and periods
under review are never exposed. Nothing here writes to payroll tables.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import Forbidden, require_attendance_participant
from app.models.payroll import (
    FINAL_PERIOD_STATUSES,
    PayrollLine,
    PayrollPeriod,
    SalaryStructure,
)
from app.models.user import User

router = APIRouter(prefix="/salary", tags=["salary"])


def _caller_employee(user: User):
    if user.employee_id is None:
        raise Forbidden("Your account is not linked to an employee record.")
    return user.employee_id


def _line_out(line: PayrollLine, period: PayrollPeriod, *, estimate: bool = False) -> dict:
    snap = line.snapshot or {}
    return {
        "period": period.period,
        "status": line.status,
        "is_estimate": estimate,
        "gross": str(line.gross),
        "total_deductions": str(line.total_deductions),
        "net": str(line.net),
        "earnings": snap.get("earnings", []),
        "deductions": snap.get("deductions", []),
        "metrics": snap.get("metrics", {}),
        "notes": snap.get("notes", []),
        "payment_method": line.payment_method,
        "paid_at": (line.paid_at or period.paid_at).isoformat()
        if (line.paid_at or period.paid_at) else None,
        "approved_at": period.approved_at.isoformat() if period.approved_at else None,
    }


@router.get("/me")
async def my_salary(user: User = Depends(require_attendance_participant),
                    session: AsyncSession = Depends(get_db)):
    employee_id = _caller_employee(user)
    structure = await session.scalar(
        select(SalaryStructure).where(SalaryStructure.employee_id == employee_id)
        .order_by(SalaryStructure.effective_from.desc())
    )
    latest = await session.execute(
        select(PayrollLine, PayrollPeriod)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollLine.period_id)
        .where(PayrollLine.employee_id == employee_id,
               PayrollPeriod.status.in_(FINAL_PERIOD_STATUSES))
        .order_by(PayrollPeriod.period.desc()).limit(1)
    )
    row = latest.first()
    draft = (await session.execute(
        select(PayrollLine, PayrollPeriod)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollLine.period_id)
        .where(PayrollLine.employee_id == employee_id,
               PayrollPeriod.status.in_(("open", "submitted")))
        .order_by(PayrollPeriod.period.desc()).limit(1)
    )).first()
    return {
        "structure": None if structure is None else {
            "calc_method": structure.calc_method,
            "effective_from": structure.effective_from,
            "basic": str(structure.basic),
            "hra": str(structure.hra),
            "allowances": structure.allowances,
            "incentive": str(structure.incentive),
            "overtime_rate": str(structure.overtime_rate),
        },
        "last_paid": None if row is None or row[1].status != "paid" else _line_out(*row),
        "last_finalized": None if row is None else _line_out(*row),
        "draft_estimate": None if draft is None else _line_out(*draft, estimate=True),
    }


@router.get("/me/history")
async def my_history(user: User = Depends(require_attendance_participant),
                     session: AsyncSession = Depends(get_db)):
    employee_id = _caller_employee(user)
    rows = (await session.execute(
        select(PayrollLine, PayrollPeriod)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollLine.period_id)
        .where(PayrollLine.employee_id == employee_id,
               PayrollPeriod.status.in_(FINAL_PERIOD_STATUSES))
        .order_by(PayrollPeriod.period.desc())
    )).all()
    return {"items": [_line_out(line, period) for line, period in rows]}


@router.get("/me/periods/{period}/slip.pdf")
async def my_slip(period: str, user: User = Depends(require_attendance_participant),
                  session: AsyncSession = Depends(get_db)):
    from fastapi import Response
    from sqlalchemy import select as _select

    from app.models.company import Company
    from app.models.employee import Employee
    from app.models.payroll import PayrollAdjustment
    from app.services.payroll_slip import render_slip

    employee_id = _caller_employee(user)
    row = (await session.execute(
        _select(PayrollLine, PayrollPeriod)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollLine.period_id)
        .where(PayrollLine.employee_id == employee_id, PayrollPeriod.period == period,
               PayrollPeriod.status.in_(FINAL_PERIOD_STATUSES))
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": "No finalized salary for that period.",
                                                       "code": "NOT_FOUND"})
    line, pr = row
    emp = await session.get(Employee, employee_id)
    company = await session.get(Company, emp.company_id)
    adjustments = (await session.execute(_select(PayrollAdjustment).where(
        PayrollAdjustment.line_id == line.id).order_by(PayrollAdjustment.created_at))).scalars().all()
    pdf = render_slip(
        company_name=company.brand_name or company.company_name, employee_name=emp.name,
        employee_uid=str(emp.id), department=emp.department, designation=emp.job_title,
        period=pr.period, line_snapshot=line.snapshot, line_status=line.status,
        payment_date=pr.paid_at.date().isoformat() if pr.paid_at else None,
        adjustments=adjustments, net=str(line.net),
    )
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="salary-slip-{pr.period}.pdf"'})


@router.get("/me/periods/{period}")
async def my_period(period: str, user: User = Depends(require_attendance_participant),
                    session: AsyncSession = Depends(get_db)):
    employee_id = _caller_employee(user)
    row = (await session.execute(
        select(PayrollLine, PayrollPeriod)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollLine.period_id)
        .where(PayrollLine.employee_id == employee_id,
               PayrollPeriod.period == period,
               PayrollPeriod.status.in_(FINAL_PERIOD_STATUSES))
    )).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"message": "No finalized salary for that period.",
                                                       "code": "NOT_FOUND"})
    return _line_out(*row)
