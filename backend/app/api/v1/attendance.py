"""Attendance — workday lifecycle, month calendar, day-off requests."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import (
    require_attendance_participant,
    require_employee,
    require_super_admin,
)
from app.models.user import User
from app.schemas.attendance import (
    AttendanceRequestCreate,
    AttendanceReviewRequest,
    day_out,
    request_out,
    workday_out,
)
from app.schemas.location import GeoCapture
from app.services.attendance import AttendanceService

router = APIRouter(prefix="/attendance", tags=["attendance"])


# ---------------------------------------------------------------------------
# Workday — self-service (any caller with a linked employee record)
# ---------------------------------------------------------------------------

@router.get("/today")
async def get_today(
    user: User = Depends(require_employee),
    session: AsyncSession = Depends(get_db),
):
    day, op_date, request = await AttendanceService(session).today(user)
    return workday_out(day, date=op_date, request=request)


@router.post("/start")
async def start_workday(
    payload: GeoCapture | None = None,
    user: User = Depends(require_employee),
    session: AsyncSession = Depends(get_db),
):
    day, op_date = await AttendanceService(session).start(user, geo=payload)
    return workday_out(day, date=op_date)


@router.post("/break")
async def start_break(
    user: User = Depends(require_employee),
    session: AsyncSession = Depends(get_db),
):
    day, op_date = await AttendanceService(session).start_break(user)
    return workday_out(day, date=op_date)


@router.post("/resume")
async def resume_work(
    user: User = Depends(require_employee),
    session: AsyncSession = Depends(get_db),
):
    day, op_date = await AttendanceService(session).resume(user)
    return workday_out(day, date=op_date)


@router.post("/end")
async def end_workday(
    payload: GeoCapture | None = None,
    user: User = Depends(require_employee),
    session: AsyncSession = Depends(get_db),
):
    day, op_date = await AttendanceService(session).end(user, geo=payload)
    return workday_out(day, date=op_date)


@router.get("/calendar")
async def get_calendar(
    month: str = Query(...),
    user: User = Depends(require_employee),
    session: AsyncSession = Depends(get_db),
):
    days, requests = await AttendanceService(session).calendar(user, month)
    return {
        "days": [day_out(d) for d in days],
        "requests": [request_out(r) for r in requests],
    }


# ---------------------------------------------------------------------------
# Day-off requests — filing + self-withdrawal
# ---------------------------------------------------------------------------

@router.post("/requests")
async def create_request(
    payload: AttendanceRequestCreate,
    user: User = Depends(require_employee),
    session: AsyncSession = Depends(get_db),
):
    req = await AttendanceService(session).create_request(
        user,
        from_date=payload.from_date,
        to_date=payload.to_date,
        request_type=payload.request_type,
        leave_type=payload.leave_type,
        reason=payload.reason,
    )
    return request_out(req)


@router.post("/requests/{request_uid}/cancel")
async def cancel_request(
    request_uid: uuid.UUID,
    user: User = Depends(require_employee),
    session: AsyncSession = Depends(get_db),
):
    return request_out(
        await AttendanceService(session).cancel_request(user, request_uid)
    )


# ---------------------------------------------------------------------------
# Requests — role-dependent list (employee → own; SA → company queue;
# PM/HR → 403) + approval decisions EXCLUSIVE to SUPER_ADMIN
# ---------------------------------------------------------------------------

@router.get("/requests")
async def list_requests(
    status: str | None = Query(default=None),
    date: str | None = Query(default=None),
    user: User = Depends(require_attendance_participant),
    session: AsyncSession = Depends(get_db),
):
    requests = await AttendanceService(session).list_requests(
        user, status=status, attendance_date=date,
    )
    return {"items": [request_out(r) for r in requests]}


@router.post("/requests/{request_uid}/approve")
async def approve_request(
    request_uid: uuid.UUID,
    payload: AttendanceReviewRequest | None = None,
    user: User = Depends(require_super_admin),
    session: AsyncSession = Depends(get_db),
):
    return request_out(
        await AttendanceService(session).review_request(
            user, request_uid, approve=True,
            review_comment=payload.review_comment if payload else None,
        )
    )


@router.post("/requests/{request_uid}/reject")
async def reject_request(
    request_uid: uuid.UUID,
    payload: AttendanceReviewRequest | None = None,
    user: User = Depends(require_super_admin),
    session: AsyncSession = Depends(get_db),
):
    return request_out(
        await AttendanceService(session).review_request(
            user, request_uid, approve=False,
            review_comment=payload.review_comment if payload else None,
        )
    )
