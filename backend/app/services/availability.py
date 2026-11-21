"""AvailabilityService — pending work reaches an employee the moment they
come on duty (Start Day / End Break).

Eligibility is decided by the allocation pools (`on_duty` in
models/attendance.py, applied by WorkAllocationService). This module only
finds unassigned zone/area work the employee may take and hands each item to
the same allocator, so rotation, workload and department rules are not
duplicated here.

Best-effort: a failed sweep never fails the attendance transition that
triggered it — unassigned work simply stays pending until the next trigger.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.attendance import AttendanceDay
from app.models.employee import Employee, employee_is_assignable
from app.models.maintenance import MaintenanceTicket, MaintenanceTicketEvent
from app.models.property import Property
from app.models.task import Task, TaskHistoryEvent
from app.services.notifications import NotificationService
from app.services.work_allocation import (
    WorkAllocationService,
    eligible_departments,
    infer_task_work_type,
)

logger = get_logger(__name__)

PENDING_SWEEP_LIMIT = 200


class _EmployeeUnavailable(Exception):
    """The picked employee stopped being on duty before the commit."""


class AvailabilityService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.alloc = WorkAllocationService(session)

    async def sweep_on_duty(self, employee_id: uuid.UUID, *, actor_name: str | None = None) -> int:
        """Assign unassigned zone/area work that this employee is eligible for.

        Returns the number of items assigned. Commits its own transaction.
        """
        try:
            async with self.session.begin_nested():
                assigned = await self._sweep(employee_id, actor_name=actor_name)
        except Exception:
            logger.exception("Pending-work sweep failed for employee %s", employee_id)
            return 0
        await self.session.commit()
        return assigned

    async def _sweep(self, employee_id: uuid.UUID, *, actor_name: str | None) -> int:
        emp = await self.session.get(Employee, employee_id)
        if emp is None or not employee_is_assignable(emp):
            return 0
        if not await self.alloc.is_on_duty(emp.id, emp.property_id):
            return 0
        prop = await self.session.get(Property, emp.property_id)
        if prop is None:
            return 0

        assigned = 0
        tasks = (await self.session.execute(
            select(Task)
            .where(
                Task.property_id == prop.id,
                Task.employee_id.is_(None),
                Task.status == "pending",
            )
            .order_by(Task.created_at, Task.id)
            .limit(PENDING_SWEEP_LIMIT)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        for task in tasks:
            work_type = task.work_type or infer_task_work_type(title=task.title)
            if await self._take(emp, prop, task, kind="task", work_type=work_type, actor_name=actor_name):
                assigned += 1

        tickets = (await self.session.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.property_id == prop.id,
                MaintenanceTicket.assigned_to.is_(None),
                MaintenanceTicket.status == "open",
            )
            .order_by(MaintenanceTicket.created_at, MaintenanceTicket.id)
            .limit(PENDING_SWEEP_LIMIT)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        for ticket in tickets:
            if await self._take(emp, prop, ticket, kind="maintenance", work_type="maintenance", actor_name=actor_name):
                assigned += 1
        return assigned

    async def _take(self, emp: Employee, prop: Property, item, *, kind: str,
                    work_type: str, actor_name: str | None) -> bool:
        """Allocate one pending item if `emp` is in its eligible pool.

        The allocator may pick another eligible employee — that is the fair
        rotation working as designed. The picked employee is re-checked under
        a row lock before anything is written, inside a savepoint so a lost
        race rolls the batch and pointer back cleanly.
        """
        zone_id = item.zone_id
        area_id = getattr(item, "area_id", None)
        pool, _level = await self.alloc.eligible_employees(
            prop.id, zone_id, area_id=area_id,
            manager_employee_id=prop.manager_employee_id,
            departments=eligible_departments(work_type),
        )
        if emp.id not in {candidate.id for candidate in pool}:
            return False
        try:
            async with self.session.begin_nested():
                alloc = await self.alloc.allocate(
                    None, property_id=prop.id, zone_id=zone_id,
                    work_type=work_type,
                    manager_employee_id=prop.manager_employee_id,
                    company_id=prop.company_id, actor_name=actor_name,
                    area_id=area_id,
                )
                picked = alloc.employee
                if picked is None:
                    raise _EmployeeUnavailable()
                await self.confirm_on_duty(picked)
                self._write_assignment(item, kind=kind, picked=picked, alloc=alloc, actor_name=actor_name)
                await self.alloc.record(
                    property_id=prop.id, zone_id=zone_id, batch=alloc.batch,
                    ticket_kind=kind, ticket_id=item.id,
                    ticket_number=item.ticket_number,
                    employee_id=picked.id, employee_name=picked.name,
                    method=alloc.method, actor_name=actor_name,
                )
                await self._notify(item, kind=kind, picked=picked, prop=prop)
        except _EmployeeUnavailable:
            return False
        return True

    async def confirm_on_duty(self, picked: Employee) -> None:
        """Lock the picked employee's open workday row (FOR SHARE) and re-check.

        start_break / end lock the same row FOR UPDATE, so once this passes the
        employee cannot go on break or end the day until this sweep commits —
        and if they already did, the re-check fails before any write.
        """
        await self.session.execute(
            select(AttendanceDay.id)
            .where(AttendanceDay.employee_id == picked.id, AttendanceDay.ended_at.is_(None))
            .with_for_update(read=True)
        )
        if not await self.alloc.is_on_duty(picked.id, picked.property_id):
            raise _EmployeeUnavailable()

    def _write_assignment(self, item, *, kind: str, picked: Employee, alloc, actor_name: str | None) -> None:
        item.allocation_batch_id = alloc.batch.id
        item.allocation_status = "auto_assigned"
        item.allocation_method = alloc.method
        item.allocation_reason = None
        item.status = "assigned"
        if kind == "task":
            item.employee_id = picked.id
            self.session.add(TaskHistoryEvent(
                task_id=item.id, type="assigned", actor_name=actor_name,
                note=f"Assigned to {picked.name} when they came on duty",
            ))
        else:
            item.assigned_to = picked.id
            self.session.add(MaintenanceTicketEvent(
                ticket_id=item.id, action="assigned", actor_name=actor_name,
                comment=f"Assigned to {picked.name} when they came on duty",
            ))
        item.assigned_to_name = picked.name

    async def _notify(self, item, *, kind: str, picked: Employee, prop: Property) -> None:
        if kind == "task":
            await NotificationService(self.session).notify(
                employee_id=picked.id, property_id=prop.id,
                type="task_assigned", title="New Task Assigned",
                body=item.title, task_id=item.id, employee_name=picked.name,
            )
        else:
            await NotificationService(self.session).notify(
                employee_id=picked.id, property_id=prop.id,
                type="ticket_assigned", title="Maintenance Ticket Assigned",
                body=f"Maintenance Ticket {item.ticket_number}",
                ticket_id=item.id, employee_name=picked.name,
            )
