"""MaintenanceService — ticket lifecycle with room-status side effects.

Rules:
  create  → ticket OPEN + room.status='maintenance' in ONE transaction
  assign  → ASSIGNED, records event
  start   → IN_PROGRESS, records event
  resolve → RESOLVED + notes/photos — the resource stays blocked until
            the supervisor acknowledges (close)
  close   → CLOSED + resource → 'available' when nothing else blocks it
  cancel  → CANCELLED + room → 'available' (nothing happened)

Every transition appends a MaintenanceTicketEvent — the timeline is the
permanent record; the room status is derived state.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.maintenance import (
    MaintenanceTicket,
    MaintenanceTicketAttachment,
    MaintenanceTicketEvent,
)
from app.models.structure import Bed, Dorm, Room, Washroom, WashroomFixture
from app.models.user import User, UserRole
from app.services.work_allocation import AllocationResult, WorkAllocationService
from app.schemas.maintenance import (
    MaintenanceCreateRequest,
    MaintenanceResolveRequest,
    MaintenanceUpdateRequest,
)
from app.services.structure import (
    ConflictErr,
    NotFoundErr,
    StructureService,
    ValidationErr,
)

ACTIVE_STATUSES = {"open", "assigned", "in_progress", "on_hold"}
PRIORITIES = {"low", "medium", "high", "critical"}


async def next_ticket_number(session: AsyncSession, kind: str) -> str:
    """Server-side ticket number via a PostgreSQL sequence.

    kind='maintenance' → MT-YYYY-NNNNN · kind='task' → TASK-YYYY-NNNNN
    SQLite (tests) falls back to a max-scan since sequences don't exist.
    """
    seq = "maintenance_ticket_seq" if kind == "maintenance" else "task_ticket_seq"
    prefix = "MT" if kind == "maintenance" else "TASK"
    year = datetime.now(timezone.utc).year
    try:
        res = await session.execute(text(f"SELECT nextval('{seq}')"))
        n = int(res.scalar_one())
    except Exception:
        from app.models.task import Task

        model = MaintenanceTicket if kind == "maintenance" else Task
        res = await session.execute(select(func.count()).select_from(model))
        n = int(res.scalar_one()) + 1
    return f"{prefix}-{year}-{n:05d}"


class MaintenanceService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.structure = StructureService(session)
        self.alloc = WorkAllocationService(session)

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------

    async def _get_ticket(self, user: User, ticket_id: uuid.UUID) -> MaintenanceTicket:
        res = await self.session.execute(
            select(MaintenanceTicket)
            .where(MaintenanceTicket.id == ticket_id)
            .options(
                selectinload(MaintenanceTicket.events),
                selectinload(MaintenanceTicket.attachments),
            )
        )
        ticket = res.scalar_one_or_none()
        if ticket is None:
            raise NotFoundErr("Maintenance ticket not found.")
        await self.structure._property_for_write(user, ticket.property_id)
        return ticket

    def _event(self, ticket, action, user, comment=None):
        ev = MaintenanceTicketEvent(
            ticket_id=ticket.id, action=action,
            actor_name=user.name, comment=comment,
        )
        self.session.add(ev)
        # also populate the in-memory collection when it's already loaded —
        # fresh batch tickets serialize their timeline without a reload,
        # but never force a lazy load on unfetched relationships
        from sqlalchemy import inspect as sa_inspect
        if "events" not in sa_inspect(ticket).unloaded:
            ticket.events.append(ev)

    async def flag_ticket_resource(
        self, ticket, *, user: User | None, dorm: Dorm | None = None
    ) -> None:
        """Flag a blocking ticket's target via the central state engine.

        This is the ONLY flagging path — manual creation, batch creation
        and template-scheduler generation all route here so a blocking
        ticket always produces a `maintenance` projection. Illegal flags
        (e.g. inactive) are skipped; a higher-priority state wins."""
        from app.domain.resource_events import SRC_TICKET_CREATED
        from app.services.resource_state import ResourceStateService
        state = ResourceStateService(self.session)
        flag_reason = f"{ticket.maintenance_type}: {ticket.issue}"

        async def _flag(rtype: str, rid: uuid.UUID) -> None:
            try:
                await state.transition(
                    rtype, rid, "maintenance", user=user,
                    source=SRC_TICKET_CREATED, ticket_id=ticket.id,
                    reason=flag_reason,
                )
            except (ConflictErr, ValidationErr, NotFoundErr):
                pass  # a higher-priority state (e.g. inactive) wins

        if ticket.room_id is not None:
            await _flag("room", ticket.room_id)
        elif ticket.bed_id is not None:
            await _flag("bed", ticket.bed_id)
        elif ticket.washroom_id is not None:
            await _flag("washroom", ticket.washroom_id)
            # A fixture-scoped ticket flags the fixture, not just the room
            if ticket.washroom_fixture_id is not None:
                await _flag("fixture", ticket.washroom_fixture_id)
        elif ticket.dorm_id is not None:
            await _flag("dorm", ticket.dorm_id)
            if dorm is None or dorm.id != ticket.dorm_id:
                res = await self.session.execute(
                    select(Dorm)
                    .where(Dorm.id == ticket.dorm_id)
                    .options(selectinload(Dorm.beds))
                )
                dorm = res.scalar_one_or_none()
            for b in (dorm.beds if dorm else []):
                # occupied beds keep their guest; inactive bunks are retired
                # inventory — a dorm ticket doesn't resurrect them
                if b.status not in ("occupied", "inactive"):
                    await _flag("bed", b.id)

    # ------------------------------------------------------------------
    # Create — ticket + room status in ONE transaction
    # ------------------------------------------------------------------

    async def _employee_coverage(self, user: User) -> tuple[set, uuid.UUID | None]:
        """(zone_ids, area_id) the EMPLOYEE may raise tickets for.

        Zone assignment → that zone's targets. Area assignment → every
        zone inside the area plus targets attached to the area directly.
        Either or both may exist — the union defines coverage."""
        zone_ids: set[uuid.UUID] = set()
        area_id = None
        if user.role == UserRole.EMPLOYEE:
            emp = await self.session.get(Employee, user.employee_id)
            if emp is None:
                return zone_ids, area_id
            if emp.zone_id:
                zone_ids.add(emp.zone_id)
            if emp.area_id:
                area_id = emp.area_id
                from app.models.structure import Zone
                res = await self.session.execute(
                    select(Zone.id).where(Zone.area_id == emp.area_id)
                )
                zone_ids |= set(res.scalars())
        return zone_ids, area_id

    async def _enforce_employee_coverage(self, user: User, room=None,
                                       dorm=None, washroom=None) -> None:
        """Employees may only raise tickets inside their zone/area
        coverage — backend enforcement, never trust the submitted UID."""
        zone_ids, area_id = await self._employee_coverage(user)
        target = room or dorm or washroom
        t_zone = getattr(target, "zone_id", None)
        t_area = getattr(target, "area_id", None)
        if (t_zone is not None and t_zone in zone_ids) or (
                area_id is not None and t_area == area_id):
            return
        from app.dependencies.auth import Forbidden
        raise Forbidden(
            "This location is outside your assigned area. "
            "You can only raise maintenance for rooms and dorms "
            "assigned to your zone or floor."
        )

    async def eligible_locations(self, user: User) -> dict:
        """Rooms + dorms the EMPLOYEE may raise tickets against — the
        selector's authoritative source, scoped by zone/area coverage."""
        if user.role != UserRole.EMPLOYEE or user.employee_id is None:
            from app.dependencies.auth import Forbidden
            raise Forbidden()
        zone_ids, area_id = await self._employee_coverage(user)
        if not zone_ids and area_id is None:
            return {"rooms": [], "dorms": []}

        scope = Room.zone_id.in_(zone_ids) if zone_ids else None
        scope_d = Dorm.zone_id.in_(zone_ids) if zone_ids else None
        if area_id is not None:
            scope = or_(scope, Room.area_id == area_id) if scope is not None \
                else Room.area_id == area_id
            scope_d = or_(scope_d, Dorm.area_id == area_id) if scope_d \
                is not None else Dorm.area_id == area_id

        from app.models.structure import Zone
        res = await self.session.execute(
            select(Room).where(Room.property_id == user.property_id, scope)
            .order_by(Room.room_number)
        )
        rooms = list(res.scalars())
        res = await self.session.execute(
            select(Dorm)
            .options(selectinload(Dorm.beds))
            .where(Dorm.property_id == user.property_id, scope_d)
            .order_by(Dorm.name)
        )
        dorms = list(res.scalars())
        zmap = {}
        if zone_ids:
            res = await self.session.execute(
                select(Zone).where(Zone.id.in_(zone_ids))
            )
            zmap = {z.id: z.name for z in res.scalars()}
        return {
            "rooms": [{
                "room_uid": str(r.id), "room_number": r.room_number,
                "type": r.type, "zone_name": zmap.get(r.zone_id),
            } for r in rooms],
            "dorms": [{
                "dorm_uid": str(d.id), "name": d.name,
                "dorm_type": d.dorm_type, "zone_name": zmap.get(d.zone_id),
                "bed_count": len(d.beds),
            } for d in dorms],
        }

    async def _resolve_target(self, prop, payload: MaintenanceCreateRequest):
        """Validate + load the target — exactly one resource is set."""
        targets = [
            t for t in (
                payload.room_uid, payload.dorm_uid, payload.bed_uid,
                payload.washroom_uid,
            ) if t
        ]
        if len(targets) != 1:
            raise ValidationErr(
                "Provide exactly one of room_uid, dorm_uid, bed_uid or "
                "washroom_uid.",
                field="room_uid",
            )
        room = dorm = bed = washroom = fixture = None
        if payload.room_uid:
            res = await self.session.execute(
                select(Room).where(
                    Room.id == payload.room_uid, Room.property_id == prop.id
                )
            )
            room = res.scalar_one_or_none()
            if room is None:
                raise ValidationErr("Room not found in this property.", field="room_uid")
        elif payload.dorm_uid:
            res = await self.session.execute(
                select(Dorm)
                .options(selectinload(Dorm.beds))
                .where(Dorm.id == payload.dorm_uid, Dorm.property_id == prop.id)
            )
            dorm = res.scalar_one_or_none()
            if dorm is None:
                raise ValidationErr("Dorm not found in this property.", field="dorm_uid")
        elif payload.washroom_uid:
            res = await self.session.execute(
                select(Washroom).where(
                    Washroom.id == payload.washroom_uid,
                    Washroom.property_id == prop.id,
                )
            )
            washroom = res.scalar_one_or_none()
            if washroom is None:
                raise ValidationErr(
                    "Washroom not found in this property.", field="washroom_uid"
                )
            if payload.washroom_fixture_uid:
                res = await self.session.execute(
                    select(WashroomFixture).where(
                        WashroomFixture.id == payload.washroom_fixture_uid,
                        WashroomFixture.washroom_id == washroom.id,
                    )
                )
                fixture = res.scalar_one_or_none()
                if fixture is None:
                    raise ValidationErr(
                        "Fixture not found in this washroom.",
                        field="washroom_fixture_uid",
                    )
        elif payload.washroom_fixture_uid:
            raise ValidationErr(
                "A fixture target requires washroom_uid.",
                field="washroom_fixture_uid",
            )
        else:
            res = await self.session.execute(
                select(Bed).where(Bed.id == payload.bed_uid)
            )
            bed = res.scalar_one_or_none()
            if bed is None or bed.property_id != prop.id:
                raise ValidationErr("Bed not found in this property.", field="bed_uid")
            res = await self.session.execute(
                select(Dorm).options(selectinload(Dorm.beds)).where(Dorm.id == bed.dorm_id)
            )
            dorm = res.scalar_one_or_none()
        return room, dorm, bed, washroom, fixture

    async def create_ticket(
        self, user: User, payload: MaintenanceCreateRequest,
        allocation: AllocationResult | None = None, commit: bool = True,
    ) -> MaintenanceTicket:
        if user.role not in (
            UserRole.SUPER_ADMIN, UserRole.PROPERTY_MANAGER, UserRole.EMPLOYEE
        ):
            # Defense-in-depth (route also gates) — HR/department roles
            # cannot raise maintenance tickets or flag resources.
            from app.dependencies.auth import Forbidden
            raise Forbidden()
        prop = await self.structure._property_for_write(user, payload.property_uid)
        room, dorm, bed, washroom, fixture = await self._resolve_target(prop, payload)

        if user.role == UserRole.EMPLOYEE:
            # Employees raise tickets only inside their assigned coverage —
            # bed targets resolve through their dorm; fixtures through the
            # washroom.
            await self._enforce_employee_coverage(
                user, room=room, dorm=dorm, washroom=washroom)

        if payload.priority not in PRIORITIES:
            raise ValidationErr("Invalid priority.", field="priority")

        from app.services.task_location import resolve_task_location
        location = await resolve_task_location(
            self.session, property_id=prop.id,
            room_id=room.id if room else None,
            dorm_id=dorm.id if dorm else None,
            bed_id=bed.id if bed else None,
            washroom_id=washroom.id if washroom else None,
        )
        zone_id = location.zone_id
        area_id = location.area_id
        if allocation is None:
            from app.models.structure import Area, Zone
            zname = aname = None
            if zone_id:
                res = await self.session.execute(select(Zone).where(Zone.id == zone_id))
                z = res.scalar_one_or_none()
                zname = z.name if z else None
            if area_id:
                res = await self.session.execute(select(Area).where(Area.id == area_id))
                a = res.scalar_one_or_none()
                aname = a.name if a else None
            allocation = await self.alloc.allocate(
                user,
                property_id=prop.id,
                zone_id=zone_id,
                zone_name=zname,
                work_type="maintenance",
                manager_employee_id=prop.manager_employee_id,
                area_id=area_id,
                area_name=aname,
            )
        emp = allocation.employee

        ticket = MaintenanceTicket(
            ticket_number=await next_ticket_number(self.session, "maintenance"),
            company_id=prop.company_id,
            property_id=prop.id,
            room_id=room.id if room else None,
            room_number=room.room_number if room else None,
            dorm_id=dorm.id if dorm else None,
            dorm_name=dorm.name if dorm else None,
            bed_id=bed.id if bed else None,
            bed_number=bed.bed_number if bed else None,
            washroom_id=washroom.id if washroom else None,
            washroom_name=washroom.name if washroom else None,
            washroom_fixture_id=fixture.id if fixture else None,
            washroom_fixture_label=(
                f"{fixture.fixture_type.replace('_', ' ').title()}"
                f" {fixture.fixture_number:02d}"
                if fixture else None
            ),
            reported_by=user.id,
            reported_by_name=user.name,
            assigned_to=emp.id if emp else None,
            assigned_to_name=emp.name if emp else None,
            status="assigned" if emp else "open",
            zone_id=zone_id,
            allocation_batch_id=allocation.batch.id,
            allocation_status=allocation.batch.allocation_status,
            allocation_method=allocation.method,
            allocation_reason=allocation.reason,
            maintenance_type=payload.maintenance_type.strip().lower(),
            issue=payload.issue.strip(),
            description=(payload.description or "").strip() or None,
            priority=payload.priority,
            due_date=payload.due_date,
        )
        self.session.add(ticket)
        await self.session.flush()  # ticket.id available for children
        # mark the collections loaded-empty so ticket_out() can serialize a
        # fresh ticket without triggering async lazy loads (plain assignment
        # would emit a SELECT for delete-orphan bookkeeping)
        from sqlalchemy.orm import attributes as orm_attrs
        orm_attrs.set_committed_value(ticket, "events", [])
        orm_attrs.set_committed_value(ticket, "attachments", [])

        for url in payload.attachment_urls:
            ticket.attachments.append(MaintenanceTicketAttachment(
                ticket_id=ticket.id, url=url, kind="issue",
                file_name=url.rsplit("/", 1)[-1],
                uploaded_by_name=user.name,
            ))
        self._event(ticket, "created", user,
                    comment=f"{ticket.maintenance_type}: {ticket.issue}")
        if emp:
            self._event(ticket, "assigned", user,
                        comment=f"Auto-assigned to {emp.name} (zone round-robin)")
        await self.alloc.record(
            property_id=prop.id, zone_id=zone_id, batch=allocation.batch,
            ticket_kind="maintenance", ticket_id=ticket.id,
            ticket_number=ticket.ticket_number,
            employee_id=emp.id if emp else None,
            employee_name=emp.name if emp else None,
            method=allocation.method, reason=allocation.reason,
            actor_name=user.name,
        )
        if emp:
            from app.services.notifications import NotificationService
            await NotificationService(self.session).notify(
                employee_id=emp.id, property_id=prop.id,
                type="ticket_assigned", title="Maintenance Ticket Assigned",
                body=f"Maintenance Ticket {ticket.ticket_number}",
                ticket_id=ticket.id, employee_name=emp.name,
            )
        # populate server_default timestamps (events' created_at) so
        # commit=False callers serialize real times, not nulls
        await self.session.flush()

        # Flag the target through the central ResourceStateService — the
        # ticket and the resource state are committed in ONE transaction.

        await self.flag_ticket_resource(ticket, user=user, dorm=dorm)
        if commit:
            await self.session.commit()
            return await self._get_ticket(user, ticket.id)
        return ticket

    # ------------------------------------------------------------------
    # List / get
    # ------------------------------------------------------------------

    async def list_tickets(
        self, user: User, *, property_id=None, room_id=None, washroom_id=None,
        status_=None, priority=None, assigned_to=None, search=None,
    ) -> list[MaintenanceTicket]:
        q = (
            select(MaintenanceTicket)
            .options(
                selectinload(MaintenanceTicket.events),
                selectinload(MaintenanceTicket.attachments),
            )
            .order_by(MaintenanceTicket.created_at.desc())
        )
        if user.role == UserRole.SUPER_ADMIN:
            q = q.where(MaintenanceTicket.company_id == user.company_id)
            if property_id:
                q = q.where(MaintenanceTicket.property_id == property_id)
        else:
            if not user.property_id:
                return []
            q = q.where(MaintenanceTicket.property_id == user.property_id)
            if user.role == UserRole.EMPLOYEE:
                # Employees see tickets assigned to them OR tickets they
                # reported (raising a ticket must stay trackable) — mirrors
                # the get_ticket detail scope.
                q = q.where(or_(
                    MaintenanceTicket.assigned_to == user.employee_id,
                    MaintenanceTicket.reported_by == user.id,
                ))
        if room_id:
            q = q.where(MaintenanceTicket.room_id == room_id)
        if washroom_id:
            q = q.where(MaintenanceTicket.washroom_id == washroom_id)
        if status_:
            q = q.where(MaintenanceTicket.status == status_)
        if priority:
            q = q.where(MaintenanceTicket.priority == priority)
        if assigned_to:
            q = q.where(MaintenanceTicket.assigned_to == assigned_to)
        if search:
            like = f"%{search}%"
            q = q.where(
                MaintenanceTicket.ticket_number.ilike(like)
                | MaintenanceTicket.issue.ilike(like)
                | MaintenanceTicket.room_number.ilike(like)
                | MaintenanceTicket.washroom_name.ilike(like)
            )
        res = await self.session.execute(q)
        return list(res.scalars())

    async def get_ticket(self, user: User, ticket_id: uuid.UUID):
        ticket = await self._get_ticket(user, ticket_id)
        # Mirror list scoping: employees read only tickets assigned to them
        # or tickets they reported — property membership alone is not enough.
        if user.role == UserRole.EMPLOYEE and (
            user.employee_id is None
            or ticket.assigned_to != user.employee_id
        ) and ticket.reported_by != user.id:
            from app.dependencies.auth import Forbidden

            raise Forbidden()
        return ticket

    async def room_history(self, user: User, room_id: uuid.UUID):
        res = await self.session.execute(select(Room).where(Room.id == room_id))
        room = res.scalar_one_or_none()
        if room is None:
            raise NotFoundErr("Room not found.")
        await self.structure._property_for_write(user, room.property_id)
        res = await self.session.execute(
            select(MaintenanceTicket)
            .where(MaintenanceTicket.room_id == room_id)
            .options(
                selectinload(MaintenanceTicket.events),
                selectinload(MaintenanceTicket.attachments),
            )
            .order_by(MaintenanceTicket.created_at.desc())
        )
        return list(res.scalars())

    async def active_ticket_for_room(self, user: User, room_id: uuid.UUID):
        res = await self.session.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.room_id == room_id,
                MaintenanceTicket.status.in_(ACTIVE_STATUSES),
            )
            .options(
                selectinload(MaintenanceTicket.events),
                selectinload(MaintenanceTicket.attachments),
            )
            .order_by(MaintenanceTicket.created_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def washroom_history(self, user: User, washroom_id: uuid.UUID):
        res = await self.session.execute(
            select(Washroom).where(Washroom.id == washroom_id)
        )
        washroom = res.scalar_one_or_none()
        if washroom is None:
            raise NotFoundErr("Washroom not found.")
        await self.structure._property_for_write(user, washroom.property_id)
        res = await self.session.execute(
            select(MaintenanceTicket)
            .where(MaintenanceTicket.washroom_id == washroom_id)
            .options(
                selectinload(MaintenanceTicket.events),
                selectinload(MaintenanceTicket.attachments),
            )
            .order_by(MaintenanceTicket.created_at.desc())
        )
        return list(res.scalars())

    async def active_ticket_for_washroom(
        self, user: User, washroom_id: uuid.UUID
    ):
        res = await self.session.execute(
            select(MaintenanceTicket)
            .where(
                MaintenanceTicket.washroom_id == washroom_id,
                MaintenanceTicket.status.in_(ACTIVE_STATUSES),
            )
            .options(
                selectinload(MaintenanceTicket.events),
                selectinload(MaintenanceTicket.attachments),
            )
            .order_by(MaintenanceTicket.created_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Update (fields) + status transitions
    # ------------------------------------------------------------------

    async def update_ticket(
        self, user: User, ticket_id: uuid.UUID, payload: MaintenanceUpdateRequest
    ) -> MaintenanceTicket:
        ticket = await self._get_ticket(user, ticket_id)
        if ticket.status in {"closed", "cancelled"}:
            raise ConflictErr("Closed or cancelled tickets cannot be edited.")

        data = payload.model_dump(exclude_unset=True)
        if "assigned_to" in data:
            emp_uid = data.pop("assigned_to")
            await self._assign_employee(user, ticket, emp_uid)
        if "priority" in data and data["priority"] not in PRIORITIES:
            raise ValidationErr("Invalid priority.", field="priority")

        new_status = data.pop("status", None)
        if new_status == "cancelled":
            # cancelling releases the resource — Super Admin authority
            self._require_release_authority(user)
            ticket.status = "cancelled"
            self._event(ticket, "cancelled", user)
            await self._refresh_target(user, ticket, release_to="available")
        elif new_status is not None:
            raise ValidationErr(
                "Use the dedicated action endpoints to change ticket status.",
                field="status",
            )

        for k, v in data.items():
            setattr(ticket, k, v)
        self._event(ticket, "edited", user)
        await self.session.commit()
        return await self._get_ticket(user, ticket.id)

    async def delete_ticket(self, user: User, ticket_id: uuid.UUID) -> None:
        """Delete a ticket after releasing its derived unit status.

        Active tickets still block a room/bed/dorm, so the ticket is marked
        cancelled before the status refresh; the row and its event/attachment
        graph are then removed by the ORM cascade.
        """
        ticket = await self._get_ticket(user, ticket_id)
        # deleting an active ticket releases its resource — SA authority
        if ticket.status not in {"closed", "cancelled"}:
            self._require_release_authority(user)
        if ticket.status not in {"closed", "cancelled"}:
            ticket.status = "cancelled"
            self._event(ticket, "cancelled", user, comment="Ticket deleted")
            await self.session.flush()
            await self._refresh_target(user, ticket, release_to="available")
        await self.session.delete(ticket)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------

    async def _assign_employee(self, user, ticket, employee_uid):
        # Manual reassignment — audited, but never touches the round-robin
        # pointer (manual overrides don't corrupt the sequence). Terminal
        # tickets cannot be re-opened by assignment — that would resurrect
        # a blocking ticket without re-flagging the resource.
        if ticket.status in {"closed", "cancelled"}:
            raise ConflictErr(
                f"Cannot assign a {ticket.status} ticket — reopen it first."
            )
        prev_id, prev_name = ticket.assigned_to, ticket.assigned_to_name
        if employee_uid is None:
            ticket.assigned_to = None
            ticket.assigned_to_name = None
            ticket.status = "open"
            ticket.allocation_status = "unassigned"
            ticket.allocation_method = "manual"
            self._event(ticket, "assigned", user, comment="Unassigned")
            await self.alloc.record(
                property_id=ticket.property_id, zone_id=ticket.zone_id, batch=None,
                ticket_kind="maintenance", ticket_id=ticket.id,
                ticket_number=ticket.ticket_number,
                employee_id=None, employee_name=None,
                previous_employee_id=prev_id, previous_employee_name=prev_name,
                method="manual", reason="unassigned", actor_name=user.name,
            )
            return
        emp = await self.alloc.employee_for_assignment(
            employee_uid, ticket.property_id, work_type="maintenance"
        )
        ticket.assigned_to = emp.id
        ticket.assigned_to_name = emp.name
        ticket.status = "assigned"
        ticket.allocation_status = "manually_assigned"
        ticket.allocation_method = "reassign" if prev_id else "manual"
        ticket.allocation_reason = None
        self._event(ticket, "assigned", user, comment=f"Assigned to {emp.name}")
        await self.alloc.record(
            property_id=ticket.property_id, zone_id=ticket.zone_id, batch=None,
            ticket_kind="maintenance", ticket_id=ticket.id,
            ticket_number=ticket.ticket_number,
            employee_id=emp.id, employee_name=emp.name,
            previous_employee_id=prev_id, previous_employee_name=prev_name,
            method=ticket.allocation_method, actor_name=user.name,
        )
        from app.services.notifications import NotificationService
        await NotificationService(self.session).notify(
            employee_id=emp.id, property_id=ticket.property_id,
            type="ticket_assigned", title="Maintenance Ticket Assigned",
            body=f"Maintenance Ticket {ticket.ticket_number}",
            ticket_id=ticket.id, employee_name=emp.name,
        )

    async def assign(self, user: User, ticket_id: uuid.UUID, employee_uid):
        ticket = await self._get_ticket(user, ticket_id)
        if ticket.status in {"resolved", "closed", "cancelled"}:
            raise ConflictErr(f"Cannot assign a {ticket.status} ticket.")
        await self._assign_employee(user, ticket, employee_uid)
        await self.session.commit()
        return await self._get_ticket(user, ticket.id)

    def _require_ticket_assignee(self, user: User, ticket) -> None:
        """Employees may only execute tickets assigned to them. Staff
        (manager/super-admin) may act on any ticket in their property.
        HR and department managers are NOT ticket actors."""
        if user.role in (UserRole.SUPER_ADMIN, UserRole.PROPERTY_MANAGER):
            return
        if user.role != UserRole.EMPLOYEE \
                or ticket.assigned_to != user.employee_id:
            from app.dependencies.auth import Forbidden
            raise Forbidden(
                "Only the assigned employee can perform this action."
            )

    def _require_release_authority(self, user: User) -> None:
        """Review/closure decisions that release a resource are Super
        Admin authority (spec §13)."""
        if user.role != UserRole.SUPER_ADMIN:
            from app.dependencies.auth import Forbidden
            raise Forbidden(
                "Closing or disapproving resource work requires the "
                "Super Admin role."
            )

    async def start(self, user: User, ticket_id: uuid.UUID):
        ticket = await self._get_ticket(user, ticket_id)
        self._require_ticket_assignee(user, ticket)
        if ticket.status not in {"open", "assigned", "on_hold"}:
            raise ConflictErr(f"Cannot start work on a {ticket.status} ticket.")
        ticket.status = "in_progress"
        self._event(ticket, "started", user)
        await self.session.commit()
        return await self._get_ticket(user, ticket.id)

    async def hold(self, user: User, ticket_id: uuid.UUID, note=None):
        ticket = await self._get_ticket(user, ticket_id)
        if ticket.status not in {"open", "assigned", "in_progress"}:
            raise ConflictErr(f"Cannot put a {ticket.status} ticket on hold.")
        ticket.status = "on_hold"
        self._event(ticket, "held", user, comment=note)
        await self.session.commit()
        return await self._get_ticket(user, ticket.id)

    async def _refresh_target(self, user, ticket, *, release_to: str):
        """Supervisor acknowledgement → re-derive the ticket's target status
        via the central ResourceStateService. Other blocking work on the
        same target keeps it unavailable; the transition is audited on this
        ticket's event stream AND in resource_state_events."""
        from app.domain.resource_events import SRC_TICKET_CLOSED
        from app.services.resource_state import ResourceStateService
        state = ResourceStateService(self.session)

        def _audit(note: str) -> None:
            self._event(ticket, "room_status_changed", user, comment=note)

        trigger = f"maintenance {ticket.status} ({ticket.ticket_number})"
        for rtype, rid, rel in (
            ("room", ticket.room_id, release_to),
            ("bed", ticket.bed_id, release_to),
            ("dorm", ticket.dorm_id, release_to),
            ("washroom", ticket.washroom_id, release_to),
            # fixtures release at the SAME authoritative point as their
            # parent ticket — 'resolved' never frees them early
            ("fixture", ticket.washroom_fixture_id, "operational"),
        ):
            if rid:
                await state.derive(
                    rtype, rid, release_to=rel, user=user,
                    source=SRC_TICKET_CLOSED, reason=trigger,
                    ticket_id=ticket.id, audit=_audit,
                )

    async def resolve(
        self, user: User, ticket_id: uuid.UUID, payload: MaintenanceResolveRequest
    ) -> MaintenanceTicket:
        ticket = await self._get_ticket(user, ticket_id)
        self._require_ticket_assignee(user, ticket)
        if ticket.status in {"resolved", "closed", "cancelled"}:
            raise ConflictErr(f"Ticket is already {ticket.status}.")
        # Evidence gate — template-generated tickets follow the template's
        # verification config; manual tickets keep notes-only resolution.
        if ticket.template_id:
            from app.models.template import WorkTemplate
            tpl = await self.session.get(WorkTemplate, ticket.template_id)
            v = (tpl.verification or {}) if tpl else {}
            required = v.get("min_photos", 1) if v.get("photo_required") else 0
            if len(payload.photo_urls or []) < required:
                raise ValidationErr(
                    f"At least {required} resolution photo"
                    f"{'s are' if required > 1 else ' is'} required.",
                    field="photo_urls",
                )
        ticket.status = "resolved"
        ticket.resolved_at = datetime.now(timezone.utc)
        ticket.resolution_notes = payload.resolution_notes.strip()
        # Fixture-level maintenance completion records on the fixture
        # itself — but the fixture stays `maintenance` while the ticket is
        # still blocking. Release happens only at close/cancel, through
        # `_refresh_target` (the same authoritative point as the parent).
        if ticket.washroom_fixture_id:
            fixture = await self.session.get(
                WashroomFixture, ticket.washroom_fixture_id
            )
            if fixture is not None:
                fixture.last_maintenance_at = ticket.resolved_at
        # Resolution iteration — count prior "resolved" events so evidence
        # from a disapproved→resubmitted round is tagged separately.
        res = await self.session.execute(
            select(func.count()).select_from(MaintenanceTicketEvent).where(
                MaintenanceTicketEvent.ticket_id == ticket.id,
                MaintenanceTicketEvent.action == "resolved",
            )
        )
        attempt = (res.scalar_one() or 0) + 1
        for url in payload.photo_urls:
            self.session.add(MaintenanceTicketAttachment(
                ticket_id=ticket.id, url=url, kind="resolution",
                attempt=attempt,
                file_name=url.rsplit("/", 1)[-1],
                uploaded_by_name=user.name,
            ))
        self._event(ticket, "resolved", user, comment=payload.resolution_notes.strip())
        # Employee completion does NOT release the resource — a "resolved"
        # ticket still blocks until the supervisor closes (acknowledges) it.
        await self.session.commit()
        return await self._get_ticket(user, ticket.id)

    async def disapprove(self, user: User, ticket_id: uuid.UUID, reason: str):
        """Super Admin disapproves a submitted resolution — returns the
        ticket to the employee for rework. The ticket stays blocking."""
        ticket = await self._get_ticket(user, ticket_id)
        self._require_release_authority(user)
        if ticket.status != "resolved":
            raise ConflictErr(
                "Only resolved (pending-check) tickets can be disapproved."
            )
        ticket.status = "in_progress"
        ticket.resolved_at = None
        self._event(ticket, "disapproved", user, comment=reason)
        if ticket.assigned_to:
            from app.services.notifications import NotificationService
            body = f"Resolution for ticket {ticket.ticket_number} was disapproved."
            if reason:
                body = f"{body} Reason: {reason}"
            await NotificationService(self.session).notify(
                employee_id=ticket.assigned_to,
                property_id=ticket.property_id,
                type="ticket_disapproved",
                title="Ticket Resolution Disapproved",
                body=body, ticket_id=ticket.id,
                employee_name=ticket.assigned_to_name,
            )
        # The ticket is blocking again — re-flag any target whose
        # projection drifted (e.g. a fixture released by legacy resolve).
        await self.flag_ticket_resource(ticket, user=user)
        await self.session.commit()
        return await self._get_ticket(user, ticket.id)

    async def close(self, user: User, ticket_id: uuid.UUID):
        ticket = await self._get_ticket(user, ticket_id)
        self._require_release_authority(user)
        if ticket.status == "closed":
            return ticket
        if ticket.status != "resolved":
            raise ConflictErr("Only resolved tickets can be closed.")
        ticket.status = "closed"
        ticket.closed_at = datetime.now(timezone.utc)
        self._event(ticket, "closed", user)
        # Supervisor acknowledgement — derive the target's status from any
        # remaining blocking work; a free target goes straight back to
        # 'available' once the PM approves the work.
        await self._refresh_target(user, ticket, release_to="available")
        await self.session.commit()
        return await self._get_ticket(user, ticket.id)
