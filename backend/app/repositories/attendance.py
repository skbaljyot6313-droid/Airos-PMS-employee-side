"""AttendanceRepository — queries behind AttendanceService.

All reads/writes take the already-resolved employee_id / property_id —
the service owns scoping; this layer owns the SQL shapes (get-or-create
with savepoint retry, FOR UPDATE day locks, month-range scans).
"""

import uuid

from sqlalchemy import bindparam, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attendance import (
    AttendanceBreak,
    AttendanceDay,
    AttendanceRequest,
    OPEN_REQUEST_STATUSES,
)
from app.models.property import Property
from app.models.user import User, UserRole


class AttendanceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Range predicates — PostgreSQL gets the GiST formulation over the
    # generated leave_range column (ex_request_no_overlap's index serves
    # employee_id WITH = plus leave_range WITH && inside one Index Cond);
    # sqlite (tests) has no such column, so it keeps the equivalent
    # lexical inclusive-overlap on the 'YYYY-MM-DD' strings.
    # ------------------------------------------------------------------

    def _on_postgres(self) -> bool:
        return self.session.sync_session.get_bind().dialect.name == (
            "postgresql"
        )

    @staticmethod
    def _open_range_overlaps(from_date: str, to_date: str, on_pg: bool):
        """Predicate list: open requests overlapping inclusive [from..to]."""
        if on_pg:
            return [
                text(
                    "attendance_requests.leave_range && "
                    "att_leave_range(:ovf, :ovt)"
                ).bindparams(
                    bindparam("ovf", value=from_date),
                    bindparam("ovt", value=to_date),
                ),
                AttendanceRequest.status.in_(OPEN_REQUEST_STATUSES),
            ]
        return [
            AttendanceRequest.from_date <= to_date,
            AttendanceRequest.to_date >= from_date,
            AttendanceRequest.status.in_(OPEN_REQUEST_STATUSES),
        ]

    # ------------------------------------------------------------------
    # attendance_days
    # ------------------------------------------------------------------

    async def get_day(
        self, employee_id: uuid.UUID, attendance_date: str
    ) -> AttendanceDay | None:
        res = await self.session.execute(
            select(AttendanceDay)
            .where(
                AttendanceDay.employee_id == employee_id,
                AttendanceDay.attendance_date == attendance_date,
            )
            .options(selectinload(AttendanceDay.breaks))
        )
        return res.scalar_one_or_none()

    async def lock_day(
        self, employee_id: uuid.UUID, attendance_date: str
    ) -> AttendanceDay | None:
        """SELECT … FOR UPDATE the day row — serializes break/resume/end."""
        await self.session.flush()
        res = await self.session.execute(
            select(AttendanceDay)
            .where(
                AttendanceDay.employee_id == employee_id,
                AttendanceDay.attendance_date == attendance_date,
            )
            .options(selectinload(AttendanceDay.breaks))
            .with_for_update()
        )
        return res.scalar_one_or_none()

    async def get_or_create_day(self, **fields) -> AttendanceDay:
        """Create-or-lock the (employee, date) row — the start/approve
        race resolves to a FOR UPDATE re-select of the winner's row."""
        employee_id = fields["employee_id"]
        attendance_date = fields["attendance_date"]
        day = await self.lock_day(employee_id, attendance_date)
        if day is not None:
            return day
        day = AttendanceDay(**fields)
        self.session.add(day)
        day.breaks = []  # mark loaded — callers serialize it without a refetch
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            # If the loser's object is still pending it would re-fire (and
            # re-fail) on lock_day's flush — drop it first. A savepoint
            # rollback may already have detached it, so guard the expunge.
            if day in self.session:
                self.session.expunge(day)
            day = await self.lock_day(employee_id, attendance_date)
            if day is None:  # pragma: no cover — winner rolled back
                raise
        return day

    async def list_days(
        self, employee_id: uuid.UUID, start_date: str, end_date: str
    ) -> list[AttendanceDay]:
        """Month-range scan — 'YYYY-MM-DD' strings compare lexically."""
        res = await self.session.execute(
            select(AttendanceDay)
            .where(
                AttendanceDay.employee_id == employee_id,
                AttendanceDay.attendance_date >= start_date,
                AttendanceDay.attendance_date <= end_date,
            )
            .options(selectinload(AttendanceDay.breaks))
            .order_by(AttendanceDay.attendance_date)
        )
        return list(res.scalars())

    async def days_in_range(
        self, employee_id: uuid.UUID, from_date: str, to_date: str,
        *, for_update: bool = False,
    ) -> list[AttendanceDay]:
        """ONE SELECT over a request's date range — the approve path
        batches this instead of get_or_create per date (no N+1)."""
        await self.session.flush()
        q = select(AttendanceDay).where(
            AttendanceDay.employee_id == employee_id,
            AttendanceDay.attendance_date >= from_date,
            AttendanceDay.attendance_date <= to_date,
        )
        if for_update:
            q = q.with_for_update()
        res = await self.session.execute(q)
        return list(res.scalars())

    # ------------------------------------------------------------------
    # attendance_breaks
    # ------------------------------------------------------------------

    async def open_break(
        self, attendance_day_id: uuid.UUID
    ) -> AttendanceBreak | None:
        res = await self.session.execute(
            select(AttendanceBreak).where(
                AttendanceBreak.attendance_day_id == attendance_day_id,
                AttendanceBreak.ended_at.is_(None),
            )
        )
        return res.scalar_one_or_none()

    # ------------------------------------------------------------------
    # attendance_requests
    # ------------------------------------------------------------------

    async def get_request(
        self, request_id: uuid.UUID
    ) -> AttendanceRequest | None:
        return await self.session.get(AttendanceRequest, request_id)

    async def lock_request(
        self, request_id: uuid.UUID
    ) -> AttendanceRequest | None:
        res = await self.session.execute(
            select(AttendanceRequest)
            .where(AttendanceRequest.id == request_id)
            .with_for_update()
        )
        return res.scalar_one_or_none()

    async def open_request_on(
        self, employee_id: uuid.UUID, date: str
    ) -> AttendanceRequest | None:
        """The live (pending or approved) filing covering `date` — feeds
        workday_out's embedded request for the current op-day."""
        res = await self.session.execute(
            select(AttendanceRequest).where(
                AttendanceRequest.employee_id == employee_id,
                *self._open_range_overlaps(
                    date, date, self._on_postgres()
                ),
            )
        )
        return res.scalars().first()

    async def overlapping_request(
        self,
        employee_id: uuid.UUID,
        from_date: str,
        to_date: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> AttendanceRequest | None:
        """First open (pending/approved) range overlapping [from..to] —
        the app-level dup check; the PG daterange EXCLUDE constraint is
        the concurrency backstop. On PostgreSQL the predicate runs
        against the generated leave_range column so the GiST index
        answers it inside the Index Cond. Boundaries are inclusive."""
        q = select(AttendanceRequest).where(
            AttendanceRequest.employee_id == employee_id,
            *self._open_range_overlaps(
                from_date, to_date, self._on_postgres()
            ),
        )
        if exclude_id is not None:
            q = q.where(AttendanceRequest.id != exclude_id)
        res = await self.session.execute(q)
        return res.scalars().first()

    async def list_requests(
        self,
        employee_id: uuid.UUID,
        start_date: str,
        end_date: str,
        statuses: tuple[str, ...] = (
            "pending", "approved", "rejected", "cancelled",
        ),
    ) -> list[AttendanceRequest]:
        """Requests whose range intersects [start..end] — the calendar
        ships the full request history (incl. rejected/cancelled) for
        the month; the frontend lists them below the grid."""
        res = await self.session.execute(
            select(AttendanceRequest)
            .where(
                AttendanceRequest.employee_id == employee_id,
                AttendanceRequest.from_date <= end_date,
                AttendanceRequest.to_date >= start_date,
                AttendanceRequest.status.in_(statuses),
            )
            .order_by(
                AttendanceRequest.from_date,
                AttendanceRequest.created_at,
            )
        )
        return list(res.scalars())

    async def list_requests_for_employee(
        self,
        employee_id: uuid.UUID,
        *,
        status: str | None = None,
        date: str | None = None,
    ) -> list[AttendanceRequest]:
        """The employee's own filings (GET /requests as an employee) —
        non-cancelled by default; ?date= filters ranges covering it."""
        q = select(AttendanceRequest).where(
            AttendanceRequest.employee_id == employee_id,
        )
        if status:
            q = q.where(AttendanceRequest.status == status)
        else:
            q = q.where(
                AttendanceRequest.status.in_(
                    ("pending", "approved", "rejected")
                )
            )
        if date:
            q = q.where(
                AttendanceRequest.from_date <= date,
                AttendanceRequest.to_date >= date,
            )
        res = await self.session.execute(
            q.order_by(AttendanceRequest.created_at.desc())
        )
        return list(res.scalars())

    async def list_requests_for_review(
        self,
        user: User,
        *,
        status: str | None = None,
        attendance_date: str | None = None,
    ) -> list[AttendanceRequest]:
        """Reviewer queue — SUPER_ADMIN only, company-scoped via the
        Property join (the service gates PM/HR with 403 before reaching
        here; the property fallback stays as defense in depth).
        ?date= filters ranges covering that date."""
        q = select(AttendanceRequest)
        if user.role == UserRole.SUPER_ADMIN:
            q = q.join(
                Property,
                AttendanceRequest.property_id == Property.id,
            ).where(Property.company_id == user.company_id)
        else:
            q = q.where(AttendanceRequest.property_id == user.property_id)
        if status:
            q = q.where(AttendanceRequest.status == status)
        if attendance_date:
            q = q.where(
                AttendanceRequest.from_date <= attendance_date,
                AttendanceRequest.to_date >= attendance_date,
            )
        res = await self.session.execute(
            q.order_by(AttendanceRequest.created_at.desc())
        )
        return list(res.scalars())
