"""AttendanceService — workday lifecycle + day-off request workflow.

Dates are IST operational days ('YYYY-MM-DD'), computed server-side from
the company's configured `operational_day_start` — never trusted from the
client. Instants (started_at/ended_at) are real UTC timestamps; the date
string and the instant can disagree around the IST boundary by design.

Concurrency: the day row is get-or-created inside a savepoint
(uq_attendance_employee_date backstop), then every mutation re-locks it
SELECT … FOR UPDATE. Open-break and open-request invariants are backed by
partial unique indexes — a race that slips past the app-level check still
fails with IntegrityError → 409.
"""

import calendar as cal
import uuid
from datetime import date as date_type, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import Uuid, bindparam, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import (
    AttendanceBreak,
    AttendanceDay,
    AttendanceRequest,
    LEAVE_TYPES,
    REQUEST_TYPES,
)
from app.models.audit import AuditEvent
from app.models.company import Company
from app.models.employee import Employee
from app.models.property import Property
from app.models.user import User, UserRole
from app.repositories.attendance import AttendanceRepository
from app.services.rollover import operational_day_key, parse_day_start
from app.services.structure import ConflictErr, NotFoundErr, ValidationErr

IST = ZoneInfo("Asia/Kolkata")

# Approval authority is exclusive to SUPER_ADMIN — PM/HR get 403 on the
# review queue and on decisions (enforced here AND at the route deps).
REVIEWER_ROLES = (UserRole.SUPER_ADMIN,)


def _aware(dt: datetime) -> datetime:
    """sqlite round-trips timestamptz naive — normalize to aware UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _validate_date(value: str | None, *, field: str = "date") -> str:
    """Strict 'YYYY-MM-DD' — rejects 2026-1-5 and friends."""
    s = (value or "").strip()
    try:
        parsed = datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValidationErr(
            f"{field} must be 'YYYY-MM-DD'.", field=field
        )
    if parsed.strftime("%Y-%m-%d") != s:
        raise ValidationErr(
            f"{field} must be 'YYYY-MM-DD'.", field=field
        )
    return s


def _date_range(from_date: str, to_date: str) -> list[str]:
    """Every 'YYYY-MM-DD' in the inclusive [from..to] range."""
    start = date_type.fromisoformat(from_date)
    end = date_type.fromisoformat(to_date)
    days = (end - start).days
    return [(start + timedelta(days=i)).isoformat() for i in range(days + 1)]


def _validate_month(value: str | None) -> tuple[int, int]:
    """Strict 'YYYY-MM' → (year, month)."""
    s = (value or "").strip()
    try:
        parsed = datetime.strptime(s, "%Y-%m")
    except (ValueError, TypeError):
        raise ValidationErr("month must be 'YYYY-MM'.", field="month")
    if parsed.strftime("%Y-%m") != s:
        raise ValidationErr("month must be 'YYYY-MM'.", field="month")
    return parsed.year, parsed.month


class AttendanceService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = AttendanceRepository(session)

    # ------------------------------------------------------------------
    # Context — who is the caller, which property, which operational day
    # ------------------------------------------------------------------

    async def _employee_context(
        self, user: User
    ) -> tuple[Employee, uuid.UUID, str]:
        """Employee row + property + today's operational-date key.

        A user without a linked employee record can never self-file —
        403, never a widened scope. Property follows user.property_id
        (the login scope) with the employee directory row as fallback —
        resolved in ONE query.
        """
        from app.dependencies.auth import Forbidden

        if user.employee_id is None:
            raise Forbidden(
                "Your account is not linked to an employee record."
            )
        prop_param = bindparam("caller_prop", user.property_id, type_=Uuid)
        res = await self.session.execute(
            select(Employee, Company.operational_day_start)
            .select_from(Employee)
            .join(
                Property,
                Property.id == func.coalesce(prop_param, Employee.property_id),
            )
            .join(Company, Company.id == Property.company_id)
            .where(Employee.id == user.employee_id)
        )
        row = res.first()
        if row is None:
            raise Forbidden(
                "Your account is not linked to an employee record."
            )
        employee, day_start = row
        property_id = user.property_id or employee.property_id
        op_date = operational_day_key(
            datetime.now(IST), parse_day_start(day_start)
        )
        return employee, property_id, op_date

    def _audit(
        self, *, user: User, action: str, entity_type: str,
        entity_id: uuid.UUID | None, property_id: uuid.UUID | None,
        entity_name: str | None = None, detail: dict | None = None,
    ) -> None:
        self.session.add(AuditEvent(
            property_id=property_id,
            actor_user_id=user.id,
            actor_name=user.name,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            action=action,
            detail=detail or {},
        ))

    # ------------------------------------------------------------------
    # Workday
    # ------------------------------------------------------------------

    async def today(
        self, user: User
    ) -> tuple[AttendanceDay | None, str, AttendanceRequest | None]:
        """(day, op_date, open request) — None day means 'not_started'."""
        emp, _prop_id, op_date = await self._employee_context(user)
        day = await self.repo.get_day(emp.id, op_date)
        request = await self.repo.open_request_on(emp.id, op_date)
        return day, op_date, request

    async def start(
        self, user: User, geo=None
    ) -> tuple[AttendanceDay, str]:
        """Open today's workday — get-or-create the row, then stamp it.

        `geo` is the optional location body; it validates BEFORE the day
        is touched and the capture lands in the same commit."""
        from app.services.location import parse_geo

        fix = parse_geo(geo)
        emp, prop_id, op_date = await self._employee_context(user)
        day = await self.repo.get_or_create_day(
            property_id=prop_id,
            employee_id=emp.id,
            employee_name=emp.name,
            attendance_date=op_date,
            status="present",
        )
        if day.status != "present":
            raise ConflictErr(
                f"{op_date} is an approved {day.status.replace('_', ' ')} "
                "day — work cannot be started."
            )
        if day.started_at is not None:
            raise ConflictErr("The workday has already started.")
        day.started_at = datetime.now(timezone.utc)
        day.zone_id = emp.zone_id
        if fix is not None:
            from app.services.location import LocationService
            await LocationService(self.session).record(
                property_id=prop_id, employee_id=emp.id, fix=fix,
                source="attendance_start", attendance_day_id=day.id,
            )
        self._audit(
            user=user, action="attendance_started",
            entity_type="attendance_day", entity_id=day.id,
            entity_name=emp.name, property_id=prop_id,
            detail={"date": op_date, "state": "working"},
        )
        await self.session.commit()
        return day, op_date

    async def _locked_open_day(
        self, user: User, action: str
    ) -> tuple[AttendanceDay, str, uuid.UUID]:
        emp, prop_id, op_date = await self._employee_context(user)
        day = await self.repo.lock_day(emp.id, op_date)
        if day is None or day.started_at is None:
            raise ConflictErr(
                f"Cannot {action} — the workday has not started."
            )
        if day.ended_at is not None:
            raise ConflictErr("The workday has already ended.")
        return day, op_date, prop_id

    async def start_break(self, user: User) -> tuple[AttendanceDay, str]:
        day, op_date, prop_id = await self._locked_open_day(user, "break")
        if await self.repo.open_break(day.id) is not None:
            raise ConflictErr("A break is already in progress.")
        br = AttendanceBreak(
            attendance_day_id=day.id,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(br)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            raise ConflictErr("A break is already in progress.")
        day.breaks.append(br)  # keep the loaded collection authoritative
        self._audit(
            user=user, action="attendance_break_started",
            entity_type="attendance_day", entity_id=day.id,
            entity_name=day.employee_name, property_id=prop_id,
            detail={"date": op_date, "state": "on_break"},
        )
        await self.session.commit()
        return day, op_date

    async def resume(self, user: User) -> tuple[AttendanceDay, str]:
        day, op_date, prop_id = await self._locked_open_day(user, "resume")
        br = await self.repo.open_break(day.id)
        if br is None:
            raise ConflictErr("No break is in progress.")
        now = datetime.now(timezone.utc)
        br.ended_at = now
        br.duration_seconds = max(
            0, int((now - _aware(br.started_at)).total_seconds())
        )
        day.break_seconds = (day.break_seconds or 0) + br.duration_seconds
        self._audit(
            user=user, action="attendance_break_resumed",
            entity_type="attendance_day", entity_id=day.id,
            entity_name=day.employee_name, property_id=prop_id,
            detail={
                "date": op_date, "state": "working",
                "break_seconds": day.break_seconds,
            },
        )
        await self.session.commit()
        return day, op_date

    async def end(self, user: User, geo=None) -> tuple[AttendanceDay, str]:
        from app.services.location import parse_geo

        fix = parse_geo(geo)
        day, op_date, prop_id = await self._locked_open_day(user, "end")
        if await self.repo.open_break(day.id) is not None:
            # Explicit 409 — ending mid-break would silently corrupt
            # work_seconds and strand an open segment.
            raise ConflictErr(
                "Resume the open break before ending the workday."
            )
        now = datetime.now(timezone.utc)
        day.ended_at = now
        day.work_seconds = max(
            0,
            int((now - _aware(day.started_at)).total_seconds())
            - (day.break_seconds or 0),
        )
        if fix is not None:
            from app.services.location import LocationService
            await LocationService(self.session).record(
                property_id=prop_id, employee_id=user.employee_id, fix=fix,
                source="attendance_end", attendance_day_id=day.id,
            )
        self._audit(
            user=user, action="attendance_ended",
            entity_type="attendance_day", entity_id=day.id,
            entity_name=day.employee_name, property_id=prop_id,
            detail={
                "date": op_date, "state": "completed",
                "work_seconds": day.work_seconds,
            },
        )
        await self.session.commit()
        return day, op_date

    async def calendar(
        self, user: User, month: str
    ) -> tuple[list[AttendanceDay], list[AttendanceRequest]]:
        """Actual days + non-cancelled requests for one month — absent
        days are NEVER fabricated (no row = unrecorded)."""
        emp, _prop_id, _op = await self._employee_context(user)
        year, mon = _validate_month(month)
        last = cal.monthrange(year, mon)[1]
        start = f"{year:04d}-{mon:02d}-01"
        end = f"{year:04d}-{mon:02d}-{last:02d}"
        # Inclusive range — 'YYYY-MM-DD' strings compare lexically.
        days = await self.repo.list_days(emp.id, start, end)
        requests = await self.repo.list_requests(emp.id, start, end)
        return days, requests

    # ------------------------------------------------------------------
    # Leave / week-off requests — employee side
    # ------------------------------------------------------------------

    async def create_request(
        self, user: User, *, from_date: str, to_date: str,
        request_type: str, leave_type: str | None = None,
        reason: str | None = None,
    ) -> AttendanceRequest:
        """File a DATE-RANGE request — 'leave' (typed, reason required)
        or 'week_off' (untyped). property/employee are resolved
        server-side from the caller — never from the client payload."""
        emp, prop_id, op_date = await self._employee_context(user)
        from_d = _validate_date(from_date, field="from_date")
        to_d = _validate_date(to_date, field="to_date")
        if to_d < from_d:
            raise ValidationErr(
                "to_date cannot be before from_date.", field="to_date",
            )
        if request_type not in REQUEST_TYPES:
            raise ValidationErr(
                "request_type must be 'leave' or 'week_off'.",
                field="request_type",
            )
        reason_s = (reason or "").strip() or None
        leave_type = (leave_type or "").strip() or None
        if request_type == "leave":
            if leave_type not in LEAVE_TYPES:
                raise ValidationErr(
                    "leave_type must be one of: "
                    + ", ".join(LEAVE_TYPES) + ".",
                    field="leave_type",
                )
            if reason_s is None:
                raise ValidationErr(
                    "A reason is required for leave requests.",
                    field="reason",
                )
        elif leave_type is not None:
            raise ValidationErr(
                "week_off requests do not take a leave_type.",
                field="leave_type",
            )
        if from_d < op_date:
            raise ValidationErr(
                "Cannot request time off starting on a past operational "
                "date.",
                field="from_date",
            )
        requested_days = (
            date_type.fromisoformat(to_d) - date_type.fromisoformat(from_d)
        ).days + 1
        if await self.repo.overlapping_request(
            emp.id, from_d, to_d
        ) is not None:
            raise ConflictErr(
                "A pending or approved request already overlaps these "
                "dates.",
                code="OVERLAPPING_REQUEST",
            )
        req = AttendanceRequest(
            property_id=prop_id,
            employee_id=emp.id,
            employee_name=emp.name,
            from_date=from_d,
            to_date=to_d,
            request_type=request_type,
            leave_type=leave_type,
            reason=reason_s,
            requested_days=requested_days,
            status="pending",
        )
        self.session.add(req)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            # CHECK violation or — on PG — the daterange EXCLUDE
            # backstop firing on a create race.
            raise ConflictErr(
                "A pending or approved request already overlaps these "
                "dates.",
                code="OVERLAPPING_REQUEST",
            )
        self._audit(
            user=user, action=f"{request_type}_requested",
            entity_type="attendance_request", entity_id=req.id,
            entity_name=emp.name, property_id=prop_id,
            detail={
                "from_date": from_d, "to_date": to_d,
                "request_type": request_type,
                "leave_type": leave_type,
                "requested_days": requested_days,
            },
        )
        await self.session.commit()
        return req

    async def cancel_request(
        self, user: User, request_id: uuid.UUID
    ) -> AttendanceRequest:
        """Withdraw a PENDING filing — the employee's own only."""
        from app.dependencies.auth import Forbidden

        if user.role != UserRole.EMPLOYEE:
            raise Forbidden(
                "Only the filing employee can withdraw a request."
            )
        req = await self.repo.lock_request(request_id)
        # Other employees' requests are invisible, not forbidden.
        if req is None or req.employee_id != user.employee_id:
            raise NotFoundErr("Request not found.")
        if req.status != "pending":
            raise ConflictErr(
                f"Only a pending request can be cancelled — this one is "
                f"{req.status}."
            )
        req.status = "cancelled"
        self._audit(
            user=user, action=f"{req.request_type}_cancelled",
            entity_type="attendance_request", entity_id=req.id,
            entity_name=req.employee_name, property_id=req.property_id,
            detail={
                "from_date": req.from_date, "to_date": req.to_date,
                "request_type": req.request_type,
                "state": "cancelled",
            },
        )
        await self.session.commit()
        return req

    # ------------------------------------------------------------------
    # Leave / week-off requests — listing + reviewer side (SUPER_ADMIN)
    # ------------------------------------------------------------------

    async def list_requests(
        self, user: User, *, status: str | None = None,
        attendance_date: str | None = None,
    ) -> list[AttendanceRequest]:
        """Role-dependent GET /requests — employees see their own
        filings; SA gets the company-scoped review queue; PM/HR → 403."""
        from app.dependencies.auth import Forbidden

        if user.role == UserRole.EMPLOYEE:
            if user.employee_id is None:
                raise Forbidden(
                    "Your account is not linked to an employee record."
                )
            return await self.repo.list_requests_for_employee(
                user.employee_id, status=status, date=attendance_date,
            )
        if user.role not in REVIEWER_ROLES:
            raise Forbidden()
        return await self.repo.list_requests_for_review(
            user, status=status, attendance_date=attendance_date,
        )

    async def list_requests_for_review(
        self, user: User, *, status: str | None = None,
        attendance_date: str | None = None,
    ) -> list[AttendanceRequest]:
        if user.role not in REVIEWER_ROLES:
            from app.dependencies.auth import Forbidden
            raise Forbidden()
        return await self.repo.list_requests_for_review(
            user, status=status, attendance_date=attendance_date,
        )

    async def _request_for_review(
        self, user: User, request_id: uuid.UUID
    ) -> AttendanceRequest:
        """FOR UPDATE lock + reviewer scope — SA only, company-wide.
        Any other role → 403 before the lookup (no existence probe);
        cross-company → 404, never a leak."""
        if user.role != UserRole.SUPER_ADMIN:
            from app.dependencies.auth import Forbidden
            raise Forbidden()
        req = await self.repo.lock_request(request_id)
        if req is None:
            raise NotFoundErr("Request not found.")
        prop = await self.session.get(Property, req.property_id)
        if prop is None or prop.company_id != user.company_id:
            raise NotFoundErr("Request not found.")
        return req

    async def _materialize_range(
        self, req: AttendanceRequest
    ) -> None:
        """Stamp every date in [from..to] with the request's day status —
        'leave' or 'week_off'. ONE range SELECT up front (no N+1);
        existing days are updated in place, missing ones inserted.
        A worked/started day anywhere in the range aborts the whole
        approval — naming the offending date."""
        day_status = req.request_type  # 'leave' | 'week_off'
        existing = await self.repo.days_in_range(
            req.employee_id, req.from_date, req.to_date, for_update=True,
        )
        by_date = {d.attendance_date: d for d in existing}
        for dstr in _date_range(req.from_date, req.to_date):
            day = by_date.get(dstr)
            if day is not None and (
                day.started_at is not None or day.status == "present"
            ):
                raise ConflictErr(
                    f"Cannot approve — {dstr} already has a workday on "
                    "record."
                )
        for dstr in _date_range(req.from_date, req.to_date):
            day = by_date.get(dstr)
            if day is None:
                self.session.add(AttendanceDay(
                    property_id=req.property_id,
                    employee_id=req.employee_id,
                    employee_name=req.employee_name,
                    attendance_date=dstr,
                    status=day_status,
                ))
            else:
                day.status = day_status
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            # A concurrent /start or approve won the (employee, date)
            # slot — surface as a conflict, never half-materialize.
            raise ConflictErr(
                "Cannot approve — a workday was recorded inside the "
                "requested range."
            )

    async def review_request(
        self, user: User, request_id: uuid.UUID, *, approve: bool,
        review_comment: str | None = None,
    ) -> AttendanceRequest:
        req = await self._request_for_review(user, request_id)
        if req.status != "pending":
            raise ConflictErr(
                f"Only a pending request can be decided — this one is "
                f"{req.status}."
            )
        if approve:
            if req.employee_id is None:
                raise ConflictErr(
                    "The employee record no longer exists — reject the "
                    "request instead."
                )
            # A second open request overlapping this range would
            # double-book the same dates — refuse rather than merge.
            if await self.repo.overlapping_request(
                req.employee_id, req.from_date, req.to_date,
                exclude_id=req.id,
            ) is not None:
                raise ConflictErr(
                    "Another pending or approved request overlaps these "
                    "dates — decide it first.",
                    code="OVERLAPPING_REQUEST",
                )
            await self._materialize_range(req)
        req.status = "approved" if approve else "rejected"
        req.reviewed_by_id = user.id
        req.reviewed_by_name = user.name
        req.reviewed_at = datetime.now(timezone.utc)
        req.review_comment = (review_comment or "").strip() or None
        self._audit(
            user=user,
            action=(
                f"{req.request_type}_approved" if approve
                else f"{req.request_type}_rejected"
            ),
            entity_type="attendance_request", entity_id=req.id,
            entity_name=req.employee_name, property_id=req.property_id,
            detail={
                "from_date": req.from_date,
                "to_date": req.to_date,
                "request_type": req.request_type,
                "leave_type": req.leave_type,
                "state": req.status,
            },
        )
        await self.session.commit()
        return req
