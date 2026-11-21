"""ReassignmentService — what happens to an employee's open work at End Day.

Rules (never silently discard work):
- Terminal work (completed / cancelled / scheduled / abandoned tasks and
  resolved / closed / cancelled tickets) is left untouched.
- Only work still in `assigned` (not yet started) is moved. Work already in
  progress, submitted for review, reopened, overdue or on hold stays with the
  employee and is reported as preserved — a handover needs a human decision.
- A moved item goes to an eligible on-duty replacement picked by the normal
  allocator (zone/area coverage, department, workload, rotation). If nobody is
  eligible the item returns to the unallocated pool (`pending` task / `open`
  ticket), where the existing Start Day / End Break sweep picks it up.
- Each item runs in its own savepoint. A failure leaves that item assigned to
  the ending employee and reports it; the End Day itself still succeeds.
- Every move writes WorkAllocationHistory (previous owner, new owner, method,
  reason, timestamp) plus the item's own history event.

Called from AttendanceService.end() inside the same transaction, after the
employee's day is flushed as ended, so the replacement pool already excludes
them.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.employee import Employee
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

TERMINAL_TASK_STATUSES = ("completed", "cancelled", "scheduled", "abandoned")
TERMINAL_TICKET_STATUSES = ("resolved", "closed", "cancelled")
MOVABLE_STATUS = "assigned"
METHOD_REASSIGN = "end_of_day_reassign"
METHOD_RELEASE = "end_of_day_release"
REASON = "employee_ended_day"


class ReassignmentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.alloc = WorkAllocationService(session)

    async def release_for_end_of_day(self, emp: Employee, *, actor_name: str | None) -> dict:
        prop = await self.session.get(Property, emp.property_id)
        tasks = (await self.session.execute(
            select(Task)
            .where(Task.employee_id == emp.id, Task.status.notin_(TERMINAL_TASK_STATUSES))
            .order_by(Task.created_at, Task.id)
            .with_for_update()
        )).scalars().all()
        tickets = (await self.session.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.assigned_to == emp.id,
                MaintenanceTicket.status.notin_(TERMINAL_TICKET_STATUSES),
            )
            .order_by(MaintenanceTicket.created_at, MaintenanceTicket.id)
            .with_for_update()
        )).scalars().all()

        summary = {"reassigned": [], "released": [], "preserved": [], "failed": []}
        for kind, items in (("task", tasks), ("maintenance", tickets)):
            for item in items:
                ref = {"kind": kind, "id": str(item.id), "status": item.status}
                if item.status != MOVABLE_STATUS:
                    summary["preserved"].append(ref)
                    continue
                try:
                    async with self.session.begin_nested():
                        outcome, new_owner = await self._move(emp, prop, item, kind, actor_name)
                except Exception:
                    logger.exception("End-of-day reassignment failed for %s %s", kind, item.id)
                    summary["failed"].append(ref)
                    continue
                summary[outcome].append({**ref, "new_owner": new_owner})
        return summary

    async def _move(self, emp: Employee, prop: Property, item, kind: str,
                    actor_name: str | None) -> tuple[str, str | None]:
        from app.services.availability import AvailabilityService

        work_type = (
            item.work_type or infer_task_work_type(title=item.title)
            if kind == "task" else "maintenance"
        )
        alloc = await self.alloc.allocate(
            None, property_id=prop.id, zone_id=item.zone_id, work_type=work_type,
            manager_employee_id=prop.manager_employee_id, company_id=prop.company_id,
            actor_name=actor_name, area_id=getattr(item, "area_id", None),
        )
        picked = alloc.employee
        if picked is not None and picked.id == emp.id:
            picked = None  # the ending employee is never their own replacement
        previous_name = emp.name
        ticket_kind = "task" if kind == "task" else "maintenance"

        if picked is None:
            self._release(item, kind, actor_name)
            await self.alloc.record(
                property_id=prop.id, zone_id=item.zone_id, batch=alloc.batch,
                ticket_kind=ticket_kind, ticket_id=item.id,
                ticket_number=item.ticket_number, employee_id=None, employee_name=None,
                method=METHOD_RELEASE, reason="no_eligible_employee",
                actor_name=actor_name, previous_employee_id=emp.id,
                previous_employee_name=previous_name,
            )
            return "released", None

        await AvailabilityService(self.session).confirm_on_duty(picked)
        note = f"Reassigned from {previous_name} (ended day) to {picked.name}"
        if kind == "task":
            item.employee_id = picked.id
            self.session.add(TaskHistoryEvent(
                task_id=item.id, type="reassigned", actor_name=actor_name, note=note,
            ))
        else:
            item.assigned_to = picked.id
            self.session.add(MaintenanceTicketEvent(
                ticket_id=item.id, action="assigned", actor_name=actor_name, comment=note,
            ))
        item.assigned_to_name = picked.name
        item.allocation_batch_id = alloc.batch.id
        item.allocation_status = "auto_assigned"
        item.allocation_method = METHOD_REASSIGN
        item.allocation_reason = REASON
        await self.alloc.record(
            property_id=prop.id, zone_id=item.zone_id, batch=alloc.batch,
            ticket_kind=ticket_kind, ticket_id=item.id,
            ticket_number=item.ticket_number, employee_id=picked.id,
            employee_name=picked.name, method=METHOD_REASSIGN, reason=REASON,
            actor_name=actor_name, previous_employee_id=emp.id,
            previous_employee_name=previous_name,
        )
        await self._notify(item, kind, picked, prop)
        return "reassigned", str(picked.id)

    def _release(self, item, kind: str, actor_name: str | None) -> None:
        note = "Returned to the unallocated pool — no eligible on-duty employee at End Day"
        if kind == "task":
            item.employee_id = None
            item.status = "pending"
            self.session.add(TaskHistoryEvent(
                task_id=item.id, type="released", actor_name=actor_name, note=note,
            ))
        else:
            item.assigned_to = None
            item.status = "open"
            self.session.add(MaintenanceTicketEvent(
                ticket_id=item.id, action="unassigned", actor_name=actor_name, comment=note,
            ))
        item.assigned_to_name = None
        item.allocation_status = "unassigned"
        item.allocation_method = METHOD_RELEASE
        item.allocation_reason = "no_eligible_employee"

    async def _notify(self, item, kind: str, picked: Employee, prop: Property) -> None:
        notifier = NotificationService(self.session)
        if kind == "task":
            await notifier.notify(
                employee_id=picked.id, property_id=prop.id, type="task_reassigned",
                title="Task Reassigned", body=item.title, task_id=item.id,
                employee_name=picked.name,
            )
        else:
            await notifier.notify(
                employee_id=picked.id, property_id=prop.id, type="ticket_assigned",
                title="Maintenance Ticket Assigned",
                body=f"Maintenance Ticket {item.ticket_number}",
                ticket_id=item.id, employee_name=picked.name,
            )
