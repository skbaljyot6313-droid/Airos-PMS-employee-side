"""Attendance API contracts + serializers.

Wire shape follows the *_uid convention; instants serialize as ISO via
FastAPI's encoder (raw datetimes, same as workspace.py serializers).
The WorkdayWire contract the frontend consumes:
    { state, date, started_at, break_started_at, ended_at }
plus the richer backend fields (status, break_seconds, work_seconds,
open_break) it ignores harmlessly.
"""

from pydantic import BaseModel, Field

from app.models.attendance import (
    AttendanceBreak,
    AttendanceDay,
    AttendanceRequest,
)


class AttendanceRequestCreate(BaseModel):
    from_date: str = Field(min_length=10, max_length=10)
    to_date: str = Field(min_length=10, max_length=10)
    request_type: str = Field(min_length=1, max_length=16)
    leave_type: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=2000)


class AttendanceReviewRequest(BaseModel):
    review_comment: str | None = Field(default=None, max_length=2000)


def _open_break(day: AttendanceDay) -> AttendanceBreak | None:
    return next(
        (b for b in day.breaks if b.ended_at is None), None
    )


def _workday_state(day: AttendanceDay | None) -> str:
    """not_started | working | on_break | completed — the frontend enum."""
    if day is None or day.started_at is None:
        return "not_started"
    if day.ended_at is not None:
        return "completed"
    if _open_break(day) is not None:
        return "on_break"
    return "working"


def workday_out(
    day: AttendanceDay | None,
    *,
    date: str,
    request: AttendanceRequest | None = None,
) -> dict:
    open_break = _open_break(day) if day is not None else None
    return {
        "attendance_uid": str(day.id) if day else None,
        "date": date,
        "status": day.status if day else None,
        "state": _workday_state(day),
        "started_at": day.started_at if day else None,
        "ended_at": day.ended_at if day else None,
        "break_seconds": day.break_seconds if day else 0,
        "work_seconds": day.work_seconds if day else None,
        # Frontend wire field — the live open break's start stamp.
        "break_started_at": open_break.started_at if open_break else None,
        "open_break": (
            {"started_at": open_break.started_at} if open_break else None
        ),
        "request": request_out(request) if request else None,
    }


def day_out(d: AttendanceDay) -> dict:
    return {
        "date": d.attendance_date,
        "status": d.status,
    }


def request_out(r: AttendanceRequest) -> dict:
    return {
        "request_uid": str(r.id),
        "from_date": r.from_date,
        "to_date": r.to_date,
        "request_type": r.request_type,
        "leave_type": r.leave_type,
        "requested_days": r.requested_days,
        "status": r.status,
        "reason": r.reason,
        "created_at": r.created_at,
        "review_comment": r.review_comment,
        "reviewed_by_name": r.reviewed_by_name,
        "reviewed_at": r.reviewed_at,
        "employee_uid": str(r.employee_id) if r.employee_id else None,
        "employee_name": r.employee_name,
    }
