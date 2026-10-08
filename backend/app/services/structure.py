"""
StructureService — Areas / Zones / Rooms / Dorms / Beds mutations.

Every operation resolves the entity → its property → the caller's scope:
  super_admin       → entity's property.company_id == user.company_id
  property_manager  → entity's property.id == user.property_id
  employee          → read-only (structure writes rejected upstream)

Client-supplied company/property ids are never trusted for authorization.
"""

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

from sqlalchemy import delete as sa_delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError
from app.models.allocation import AllocationEvent
from app.models.employee import Employee
from app.models.maintenance import MaintenanceTicket, MaintenanceTicketEvent
from app.models.property import Property
from app.models.structure import Area, Bed, Dorm, Room, Washroom, WashroomFixture, Zone
from app.models.task import Task, TaskHistoryEvent
from app.models.user import User, UserRole
from app.models.work_allocation import WorkAllocationBatch
from app.schemas.structure import (
    AreaCreateRequest,
    AreaUpdateRequest,
    BulkUnitStatusRequest,
    DormBulkCreateRequest,
    DormCreateRequest,
    DormUpdateRequest,
    RoomBulkCreateRequest,
    RoomBulkDeleteRequest,
    RoomCreateRequest,
    RoomUpdateRequest,
    WashroomBulkCreateRequest,
    WashroomCreateRequest,
    WashroomUpdateRequest,
    ZoneCreateRequest,
    ZoneUpdateRequest,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class NotFoundErr(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "The requested resource was not found."


class ConflictErr(AppError):
    status_code = 409
    code = "CONFLICT"


class ValidationErr(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


# Canonical status sets live in ONE place — the resource-state domain
# (app.domain.resource_states); this service routes every resource-state
# write through ResourceStateService.

WASHROOM_TYPES = {"male", "female", "unisex"}
STAY_TYPES = {"stay"}


class StructureService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Scope helpers
    # ------------------------------------------------------------------

    async def _property_for_write(self, user: User, property_id: uuid.UUID) -> Property:
        res = await self.session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = res.scalar_one_or_none()
        if prop is None:
            raise NotFoundErr("Property not found.")
        if user.role == UserRole.SUPER_ADMIN:
            if prop.company_id != user.company_id:
                raise NotFoundErr("Property not found.")
        elif user.property_id != prop.id:
            raise NotFoundErr("Property not found.")
        return prop

    async def _get(self, model, entity_id: uuid.UUID, user: User, options=None):
        """Fetch entity + its property in ONE query — halves RTTs vs. the
        previous entity-then-property two-step (each remote query ≈300ms)."""
        q = (
            select(model, Property)
            .join(Property, model.property_id == Property.id)
            .where(model.id == entity_id)
        )
        if options:
            q = q.options(*options)
        res = await self.session.execute(q)
        row = res.first()
        if row is None:
            raise NotFoundErr()
        entity, prop = row
        if user.role == UserRole.SUPER_ADMIN:
            if prop.company_id != user.company_id:
                raise NotFoundErr()
        elif user.property_id != prop.id:
            raise NotFoundErr()
        return entity, prop

    async def _zone_in_property(self, zone_id: uuid.UUID | None, property_id: uuid.UUID):
        if zone_id is None:
            return None
        res = await self.session.execute(
            select(Zone).where(Zone.id == zone_id, Zone.property_id == property_id)
        )
        zone = res.scalar_one_or_none()
        if zone is None:
            raise ValidationErr("Zone not found in this property.", field="zone_uid")
        if zone.zone_type not in STAY_TYPES:
            raise ValidationErr(
                "Units can only be assigned to zones of type 'stay'.",
                field="zone_uid",
            )
        return zone

    async def _zone_for_washroom(
        self, zone_id: uuid.UUID | None, property_id: uuid.UUID
    ):
        """Washrooms are facilities, not guest units — any property zone can
        hold them (unlike rooms/dorms, which are stay-zone only)."""
        if zone_id is None:
            return None
        res = await self.session.execute(
            select(Zone).where(Zone.id == zone_id, Zone.property_id == property_id)
        )
        zone = res.scalar_one_or_none()
        if zone is None:
            raise ValidationErr("Zone not found in this property.", field="zone_uid")
        return zone

    async def _dorm_in_property(self, dorm_id: uuid.UUID | None, property_id: uuid.UUID):
        if dorm_id is None:
            return None
        res = await self.session.execute(
            select(Dorm).where(Dorm.id == dorm_id, Dorm.property_id == property_id)
        )
        dorm = res.scalar_one_or_none()
        if dorm is None:
            raise ValidationErr("Dorm not found in this property.", field="dorm_uid")
        return dorm

    async def _dorm_has_washroom(
        self, property_id: uuid.UUID, dorm_id: uuid.UUID
    ) -> bool:
        res = await self.session.execute(
            select(Washroom.id).where(
                Washroom.property_id == property_id, Washroom.dorm_id == dorm_id
            )
        )
        return res.scalar_one_or_none() is not None

    async def _dorm_has_other_washroom(
        self, property_id: uuid.UUID, dorm_id: uuid.UUID, exclude_id: uuid.UUID
    ) -> bool:
        res = await self.session.execute(
            select(Washroom.id).where(
                Washroom.property_id == property_id,
                Washroom.dorm_id == dorm_id,
                Washroom.id != exclude_id,
            )
        )
        return res.scalar_one_or_none() is not None

    async def _area_in_property(self, area_id: uuid.UUID | None, property_id: uuid.UUID):
        if area_id is None:
            return None
        res = await self.session.execute(
            select(Area).where(Area.id == area_id, Area.property_id == property_id)
        )
        if res.scalar_one_or_none() is None:
            raise ValidationErr("Area not found in this property.", field="area_uid")
        return area_id

    async def _next_code(self, model, property_id: uuid.UUID, prefix: str) -> str:
        res = await self.session.execute(
            select(func.count(model.id)).where(model.property_id == property_id)
        )
        return f"{prefix}-{(res.scalar() or 0) + 1:03d}"

    def _record(
        self,
        user: User,
        entity_type: str,
        entity_id: uuid.UUID,
        property_id: uuid.UUID,
        from_zone=None,
        to_zone=None,
        from_area=None,
        to_area=None,
    ):
        self.session.add(
            AllocationEvent(
                entity_type=entity_type,
                entity_id=entity_id,
                property_id=property_id,
                from_zone_id=from_zone,
                to_zone_id=to_zone,
                from_area_id=from_area,
                to_area_id=to_area,
                actor_user_id=user.id,
                actor_name=user.name,
            )
        )

    # ------------------------------------------------------------------
    # Automation — fire rule-driven tasks on unit status changes
    # ------------------------------------------------------------------

    async def _fire_automation(
        self, user: User, property_id: uuid.UUID, trigger: str, zone_id=None
    ):
        """Generate a task instance for each active automated rule matching
        the trigger (and zone scope) in this property."""
        res = await self.session.execute(
            select(Task).where(
                Task.property_id == property_id,
                Task.task_type == "automated",
                Task.status != "completed",
            )
        )
        generated = []
        for rule_task in res.scalars():
            rule = rule_task.automation_rule or {}
            if rule.get("trigger") != trigger:
                continue
            scope_zone = rule.get("scope_zone_uid")
            if scope_zone and zone_id and str(zone_id) != scope_zone:
                continue
            today = datetime.now(IST).date().isoformat()
            from app.services.task_location import resolve_task_location
            location = await resolve_task_location(
                self.session, property_id=property_id,
                zone_id=zone_id or rule_task.zone_id,
            )
            from app.services.work_allocation import (
                WorkAllocationService,
                infer_task_work_type,
            )
            allocs = WorkAllocationService(self.session)
            work_type = infer_task_work_type(
                title=rule.get("template_title"))
            emp_id = emp_name = None
            if rule.get("assign_to_uid"):
                try:
                    assigned = await allocs.employee_for_assignment(
                        uuid.UUID(rule["assign_to_uid"]), property_id,
                        work_type=work_type,
                    )
                    emp_id, emp_name = assigned.id, assigned.name
                except ValidationErr:
                    # A deactivated/ineligible configured assignee falls back
                    # to the normal pool; the generated work must not land on
                    # the unavailable employee.
                    emp_id = emp_name = None
            status_ = "pending"
            if emp_id is None:
                # no named assignee → zone round-robin, same engine as the
                # cleaning-task path, so generated work still lands allocated
                prop = await self.session.get(Property, property_id)
                alloc = await allocs.allocate(
                    None, property_id=property_id, zone_id=location.zone_id,
                    zone_name=location.zone.name if location.zone else None,
                    work_type=work_type,
                    manager_employee_id=(
                        prop.manager_employee_id if prop else None),
                    company_id=prop.company_id if prop else None,
                    actor_name="Automation", area_id=location.area_id,
                    area_name=location.area.name if location.area else None,
                )
                if alloc.employee:
                    emp_id, emp_name = alloc.employee.id, alloc.employee.name
                    status_ = "assigned"
            else:
                status_ = "assigned"
            task = Task(
                property_id=property_id,
                zone_id=location.zone_id,
                area_id=location.area_id,
                employee_id=emp_id,
                assigned_to_name=emp_name,
                title=rule.get("template_title", "Automation task"),
                description=rule.get("template_description"),
                task_type="fixed",
                work_type=work_type,
                origin="automation",
                status=status_,
                priority="medium",
                due_date=today,
            )
            self.session.add(task)
            await self.session.flush()
            from app.models.task import TaskHistoryEvent

            self.session.add(
                TaskHistoryEvent(
                    task_id=task.id,
                    type="auto_generated",
                    actor_name=rule_task.title,
                    note=f"Automation '{rule_task.title}' triggered by {trigger}",
                )
            )
            generated.append(task)
        return generated

    # ------------------------------------------------------------------
    # Areas
    # ------------------------------------------------------------------

    async def create_area(self, user: User, payload: AreaCreateRequest) -> Area:
        prop = await self._property_for_write(user, payload.property_uid)
        area = Area(
            property_id=prop.id,
            name=payload.name.strip(),
            code=await self._next_code(Area, prop.id, "AREA"),
            level_number=payload.level_number,
            description=payload.description,
        )
        self.session.add(area)
        await self._commit()
        return area

    async def update_area(
        self, user: User, area_id: uuid.UUID, payload: AreaUpdateRequest
    ) -> Area:
        area, _ = await self._get(Area, area_id, user)
        data = payload.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(area, k, v)
        await self._commit()
        return area

    async def delete_area(self, user: User, area_id: uuid.UUID) -> None:
        """Delete an area and its whole owned subtree.

        DB-level cascades remove every zone in the area, and each zone's
        rooms, dorms (with beds) and washrooms. Employees, tasks, tickets
        and allocation history keep their rows via SET NULL references.
        A single transaction — any failure rolls everything back.
        """
        area, _ = await self._get(Area, area_id, user)
        # Cascades reach every room/bed in the area — refuse while any
        # unit inside is occupied (a guest can't be deleted with a room).
        occupied_rooms = (await self.session.execute(
            select(func.count()).select_from(Room).join(
                Zone, Room.zone_id == Zone.id
            ).where(Zone.area_id == area.id, Room.status == "occupied")
        )).scalar_one()
        occupied_beds = (await self.session.execute(
            select(func.count()).select_from(Bed).join(
                Dorm, Bed.dorm_id == Dorm.id
            ).join(Zone, Dorm.zone_id == Zone.id).where(
                Zone.area_id == area.id, Bed.status == "occupied"
            )
        )).scalar_one()
        if occupied_rooms or occupied_beds:
            raise ConflictErr(
                "Cannot delete an area that contains occupied rooms or "
                "beds — check out their guests first."
            )
        await self.session.execute(
            sa_delete(Area).where(Area.id == area.id)
        )
        await self._commit()

    # ------------------------------------------------------------------
    # Zones
    # ------------------------------------------------------------------

    async def create_zone(self, user: User, payload: ZoneCreateRequest) -> Zone:
        prop = await self._property_for_write(user, payload.property_uid)
        await self._area_in_property(payload.area_uid, prop.id)
        zone = Zone(
            property_id=prop.id,
            area_id=payload.area_uid,
            name=payload.name.strip(),
            code=await self._next_code(Zone, prop.id, "ZONE"),
            zone_type=payload.zone_type or "stay",
            floor=payload.floor,
            description=payload.description,
        )
        self.session.add(zone)
        await self._commit()
        return zone

    async def update_zone(
        self, user: User, zone_id: uuid.UUID, payload: ZoneUpdateRequest
    ) -> Zone:
        zone, _ = await self._get(Zone, zone_id, user)
        data = payload.model_dump(exclude_unset=True)
        if "area_uid" in data:
            data["area_id"] = await self._area_in_property(
                data.pop("area_uid"), zone.property_id
            )
        new_type = data.get("zone_type")
        if new_type and new_type != zone.zone_type and new_type not in STAY_TYPES:
            # Moving away from 'stay' — unassign any units inside
            res = await self.session.execute(
                select(Room).where(Room.zone_id == zone_id)
            )
            for room in res.scalars():
                self._record(user, "room", room.id, room.property_id,
                             from_zone=zone_id)
                room.zone_id = None
            res = await self.session.execute(
                select(Dorm).where(Dorm.zone_id == zone_id)
            )
            for dorm in res.scalars():
                self._record(user, "dorm", dorm.id, dorm.property_id,
                             from_zone=zone_id)
                dorm.zone_id = None
        for k, v in data.items():
            setattr(zone, k, v)
        await self._commit()
        return zone

    async def delete_zone(self, user: User, zone_id: uuid.UUID) -> None:
        """Delete a zone and its whole owned subtree.

        DB-level cascades remove rooms, dorms (with beds), washrooms and the
        per-zone allocation state. Employees, tasks, tickets and allocation
        history keep their rows via SET NULL references.
        A single transaction — any failure rolls everything back.
        """
        zone, _ = await self._get(Zone, zone_id, user)
        # The zone cascade deletes its rooms/dorms/beds — refuse while any
        # unit is occupied.
        occupied_rooms = (await self.session.execute(
            select(func.count()).select_from(Room).where(
                Room.zone_id == zone.id, Room.status == "occupied"
            )
        )).scalar_one()
        occupied_beds = (await self.session.execute(
            select(func.count()).select_from(Bed).join(
                Dorm, Bed.dorm_id == Dorm.id
            ).where(Dorm.zone_id == zone.id, Bed.status == "occupied")
        )).scalar_one()
        if occupied_rooms or occupied_beds:
            raise ConflictErr(
                "Cannot delete a zone that contains occupied rooms or "
                "beds — check out their guests first."
            )
        await self.session.execute(
            sa_delete(Zone).where(Zone.id == zone.id)
        )
        await self._commit()

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------

    async def _room_number_exists(self, property_id, room_number: str) -> bool:
        res = await self.session.execute(
            select(Room.id).where(
                Room.property_id == property_id,
                func.lower(Room.room_number) == room_number.strip().lower(),
            )
        )
        return res.scalar_one_or_none() is not None

    async def _dorm_name_exists(self, property_id, name: str) -> bool:
        res = await self.session.execute(
            select(Dorm.id).where(
                Dorm.property_id == property_id,
                func.lower(Dorm.name) == name.strip().lower(),
            )
        )
        return res.scalar_one_or_none() is not None

    async def create_room(self, user: User, payload: RoomCreateRequest) -> Room:
        prop = await self._property_for_write(user, payload.property_uid)
        zone = await self._zone_in_property(payload.zone_uid, prop.id)
        area_id = await self._area_in_property(payload.area_uid, prop.id)
        if area_id is None and zone is not None:
            area_id = zone.area_id  # inherit the zone's area
        if await self._room_number_exists(prop.id, payload.room_number):
            raise ConflictErr(
                f"Room {payload.room_number} already exists in this property.",
                field="room_number",
            )
        room = Room(
            property_id=prop.id,
            zone_id=zone.id if zone else None,
            area_id=area_id,
            room_number=payload.room_number.strip(),
            type=payload.type,
            area_sqft=payload.area_sqft,
            bed_count=payload.bed_count or 1,
            status="available",
        )
        self.session.add(room)
        await self.session.flush()
        if zone:
            self._record(user, "room", room.id, prop.id, to_zone=zone.id,
                         to_area=area_id)
        await self._commit()
        return room

    async def bulk_create_rooms(
        self, user: User, payload: RoomBulkCreateRequest
    ) -> dict:
        prop = await self._property_for_write(user, payload.property_uid)
        if payload.end < payload.start:
            raise ValidationErr("'end' must be ≥ 'start'.", field="end")
        if payload.end - payload.start > 100:
            raise ValidationErr("Cannot create more than 100 rooms at once.", field="end")
        zone = await self._zone_in_property(payload.zone_uid, prop.id)
        area_id = await self._area_in_property(payload.area_uid, prop.id)
        if area_id is None and zone is not None:
            area_id = zone.area_id

        prefix = (payload.prefix or "").strip()

        created, errors = [], []
        for n in range(payload.start, payload.end + 1):
            number = f"{prefix} {n}" if prefix else str(n)
            if len(number) > 32:
                errors.append(f"Room name '{number}' exceeds 32 characters")
                continue
            if await self._room_number_exists(prop.id, number):
                errors.append(f"Room {number} already exists")
                continue
            room = Room(
                property_id=prop.id,
                zone_id=zone.id if zone else None,
                area_id=area_id,
                room_number=number,
                type=payload.type,
                area_sqft=payload.area_sqft,
                status="available",
            )
            self.session.add(room)
            await self.session.flush()
            if zone:
                self._record(user, "room", room.id, prop.id, to_zone=zone.id,
                             to_area=area_id)
            created.append(room)
        await self._commit()
        return {"created": created, "errors": errors}

    async def update_room(
        self, user: User, room_id: uuid.UUID, payload: RoomUpdateRequest
    ) -> Room:
        room, _ = await self._get(Room, room_id, user)
        data = payload.model_dump(exclude_unset=True)

        if "room_number" in data and data["room_number"] != room.room_number:
            if await self._room_number_exists(room.property_id, data["room_number"]):
                raise ConflictErr(
                    f"Room {data['room_number']} already exists in this property.",
                    field="room_number",
                )
        if "zone_uid" in data:
            zone = await self._zone_in_property(data.pop("zone_uid"), room.property_id)
            from_zone, from_area = room.zone_id, room.area_id
            room.zone_id = zone.id if zone else None
            room.area_id = zone.area_id if zone else (room.area_id if "area_uid" not in data else None)
            if room.zone_id:
                room.area_id = zone.area_id
            if from_zone != room.zone_id:
                self._record(user, "room", room.id, room.property_id,
                             from_zone=from_zone, to_zone=room.zone_id,
                             from_area=from_area, to_area=room.area_id)
        if "area_uid" in data:
            room.area_id = await self._area_in_property(
                data.pop("area_uid"), room.property_id
            )
        for k, v in data.items():
            setattr(room, k, v)
        await self._commit()
        return room

    async def delete_room(self, user: User, room_id: uuid.UUID) -> None:
        room, _ = await self._get(Room, room_id, user)
        if room.status == "occupied":
            raise ConflictErr("Cannot delete an occupied room — check out the guest first.")
        await self.session.delete(room)
        await self._commit()

    async def bulk_delete_rooms(
        self, user: User, payload: RoomBulkDeleteRequest
    ) -> dict:
        prop = await self._property_for_write(user, payload.property_uid)
        res = await self.session.execute(
            select(Room).where(
                Room.id.in_(payload.room_uids), Room.property_id == prop.id
            )
        )
        rooms = list(res.scalars())
        occupied = [r.room_number for r in rooms if r.status == "occupied"]
        if occupied:
            raise ConflictErr(
                f"Cannot delete occupied rooms: {', '.join(sorted(occupied))}."
            )
        if len(rooms) != len(payload.room_uids):
            raise NotFoundErr("Some rooms were not found in this property.")
        for room in rooms:
            await self.session.delete(room)
        await self._commit()
        return {"deleted": len(rooms)}

    # ------------------------------------------------------------------
    # Dorms & Beds
    # ------------------------------------------------------------------

    async def create_dorm(self, user: User, payload: DormCreateRequest) -> Dorm:
        prop = await self._property_for_write(user, payload.property_uid)
        zone = await self._zone_in_property(payload.zone_uid, prop.id)
        area_id = await self._area_in_property(payload.area_uid, prop.id)
        if area_id is None and zone is not None:
            area_id = zone.area_id
        if await self._dorm_name_exists(prop.id, payload.name):
            raise ConflictErr(
                f"Dorm '{payload.name.strip()}' already exists in this property.",
                field="name",
            )
        dorm = Dorm(
            property_id=prop.id,
            zone_id=zone.id if zone else None,
            area_id=area_id,
            name=payload.name.strip(),
            dorm_type=payload.dorm_type,
            washroom=payload.washroom,
            floor=payload.floor,
            area_sqft=payload.area_sqft,
            description=payload.description,
        )
        self.session.add(dorm)
        await self.session.flush()
        for i in range(1, payload.bed_count + 1):
            self.session.add(
                Bed(dorm_id=dorm.id, property_id=prop.id, bed_number=f"Bed {i:02d}")
            )
        if zone:
            self._record(user, "dorm", dorm.id, prop.id, to_zone=zone.id,
                         to_area=area_id)
        await self._commit()
        return await self._reload_dorm(dorm.id)

    async def bulk_create_dorms(
        self, user: User, payload: DormBulkCreateRequest
    ) -> dict:
        """All-or-nothing bulk dorm creation. Every row is validated up
        front — names, zones, areas — and any failure aborts the whole
        batch with 422, so the DB can never end up half-populated."""
        prop = await self._property_for_write(user, payload.property_uid)

        # ---- validate every row before inserting anything -----------------
        errors: list[str] = []
        names = [d.name.strip() for d in payload.dorms]
        res = await self.session.execute(
            select(Dorm.name).where(
                Dorm.property_id == prop.id,
                func.lower(Dorm.name).in_([n.lower() for n in names]),
            )
        )
        existing = {n.lower() for n in res.scalars()}

        seen: dict[str, int] = {}                 # lower-name → first row no.
        zones: dict[int, Zone | None] = {}
        areas: dict[int, uuid.UUID | None] = {}
        for i, item in enumerate(payload.dorms, start=1):
            nm = names[i - 1]
            key = nm.lower()
            if key in seen:
                errors.append(f"Row {i}: '{nm}' duplicates row {seen[key]}")
            elif key in existing:
                errors.append(f"Row {i}: '{nm}' already exists in this property")
            else:
                seen[key] = i
            try:
                zones[i] = await self._zone_in_property(item.zone_uid, prop.id)
            except ValidationErr as exc:
                errors.append(f"Row {i} ('{nm}'): {exc.message}")
                zones[i] = None
            try:
                areas[i] = await self._area_in_property(item.area_uid, prop.id)
            except ValidationErr as exc:
                errors.append(f"Row {i} ('{nm}'): {exc.message}")
                areas[i] = None
        if errors:
            raise ValidationErr("; ".join(errors), field="dorms")

        # ---- insert all dorms + beds, single commit -----------------------
        created: list[Dorm] = []
        for i, item in enumerate(payload.dorms, start=1):
            zone = zones[i]
            area_id = areas[i] if areas[i] is not None else (
                zone.area_id if zone else None
            )
            dorm = Dorm(
                property_id=prop.id,
                zone_id=zone.id if zone else None,
                area_id=area_id,
                name=names[i - 1],
                dorm_type=item.dorm_type,
                washroom=item.washroom,
                floor=item.floor,
                area_sqft=item.area_sqft,
                description=item.description,
            )
            self.session.add(dorm)
            await self.session.flush()
            for n in range(1, item.bed_count + 1):
                self.session.add(
                    Bed(dorm_id=dorm.id, property_id=prop.id,
                        bed_number=f"Bed {n:02d}")
                )
            if zone:
                self._record(user, "dorm", dorm.id, prop.id,
                             to_zone=zone.id, to_area=area_id)
            created.append(dorm)
        await self._commit()

        # reload in one query with beds eager-loaded for dorm_out
        res = await self.session.execute(
            select(Dorm)
            .where(Dorm.id.in_([d.id for d in created]))
            .options(selectinload(Dorm.beds))
            .execution_options(populate_existing=True)
        )
        by_id = {d.id: d for d in res.scalars()}
        return {"created": [by_id[d.id] for d in created], "errors": []}

    async def update_dorm(
        self, user: User, dorm_id: uuid.UUID, payload: DormUpdateRequest
    ) -> Dorm:
        dorm, _ = await self._get(
            Dorm, dorm_id, user, options=[selectinload(Dorm.beds)]
        )
        data = payload.model_dump(exclude_unset=True)

        if "zone_uid" in data:
            zone = await self._zone_in_property(data.pop("zone_uid"), dorm.property_id)
            from_zone, from_area = dorm.zone_id, dorm.area_id
            dorm.zone_id = zone.id if zone else None
            if zone:
                dorm.area_id = zone.area_id
            if from_zone != dorm.zone_id:
                self._record(user, "dorm", dorm.id, dorm.property_id,
                             from_zone=from_zone, to_zone=dorm.zone_id,
                             from_area=from_area, to_area=dorm.area_id)
        if "area_uid" in data:
            dorm.area_id = await self._area_in_property(
                data.pop("area_uid"), dorm.property_id
            )
        name_changed = "name" in data and data["name"] != dorm.name
        if name_changed:
            if await self._dorm_name_exists(dorm.property_id, data["name"]):
                raise ConflictErr(
                    f"Dorm '{data['name'].strip()}' already exists in this property.",
                    field="name",
                )
            # The attached washroom's name is derived — "{dorm} - Washroom" —
            # so a new dorm name must not collide on (property, name) either
            derived = f"{data['name'].strip()} - Washroom"
            res = await self.session.execute(
                select(Washroom.name).where(
                    Washroom.property_id == dorm.property_id,
                    Washroom.dorm_id != dorm.id,
                    func.lower(Washroom.name) == derived.lower(),
                )
            )
            if res.scalar_one_or_none() is not None:
                raise ConflictErr(
                    f"A washroom named '{derived}' already exists in this property.",
                    field="name",
                )
        if "bed_count" in data and data["bed_count"] is not None:
            target = data.pop("bed_count")
            await self._resize_beds(user, dorm, target)
        for k, v in data.items():
            setattr(dorm, k, v)
        if name_changed:
            # Re-derive attached washroom names from the new dorm name —
            # same dorm id, same washroom id, only the label changes
            res = await self.session.execute(
                select(Washroom).where(Washroom.dorm_id == dorm.id)
            )
            for w in res.scalars():
                w.name = f"{dorm.name.strip()} - Washroom"
        await self._commit()
        return await self._reload_dorm(dorm.id)

    async def _resize_beds(self, user: User, dorm: Dorm, target: int) -> None:
        """Grow → append new beds. Shrink → remove only 'available' beds from
        the tail; occupied/cleaning/maintenance beds are marked 'inactive'
        instead of destroyed."""
        active_beds = [b for b in dorm.beds if b.status != "inactive"]
        current = len(active_beds)
        if target == current:
            return
        if target > current:
            for i in range(current + 1, target + 1):
                self.session.add(
                    Bed(dorm_id=dorm.id, property_id=dorm.property_id,
                        bed_number=f"Bed {i:02d}")
                )
            await self.session.flush()
            return
        # shrink — drop from the tail. Only 'available' beds can be removed:
        # a resource in use (occupied/cleaning/maintenance) is never retired
        # silently — inactive is an explicit available→inactive transition.
        removable = target
        for bed in sorted(active_beds, key=lambda b: b.bed_number, reverse=True):
            if len(active_beds) <= removable:
                break
            if bed.status != "available":
                continue  # in use — its work/occupancy must close first
            await self.session.delete(bed)
            active_beds.remove(bed)
        await self.session.flush()

    async def delete_dorm(self, user: User, dorm_id: uuid.UUID) -> None:
        dorm, _ = await self._get(
            Dorm, dorm_id, user, options=[selectinload(Dorm.beds)]
        )
        occupied = [b.bed_number for b in dorm.beds if b.status == "occupied"]
        if occupied:
            raise ConflictErr(
                f"Cannot delete dorm with occupied beds: {', '.join(sorted(occupied))}."
            )
        await self.session.delete(dorm)
        await self._commit()

    # ------------------------------------------------------------------
    # Washrooms
    # ------------------------------------------------------------------

    async def _washroom_name_exists(self, property_id, name: str) -> bool:
        res = await self.session.execute(
            select(Washroom.id).where(
                Washroom.property_id == property_id,
                func.lower(Washroom.name) == name.strip().lower(),
            )
        )
        return res.scalar_one_or_none() is not None

    def _washroom_type(self, value: str) -> str:
        washroom_type = (value or "").strip().lower()
        if washroom_type not in WASHROOM_TYPES:
            raise ValidationErr(
                "Invalid washroom type — use male, female or unisex.",
                field="washroom_type",
            )
        return washroom_type

    def _validate_washroom_area(
        self, zone: Zone | None, area_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        if zone is not None:
            if area_id is not None and zone.area_id != area_id:
                raise ValidationErr(
                    "Washroom area must match the selected zone's area.",
                    field="area_uid",
                )
            return zone.area_id
        return area_id

    async def create_washroom(
        self, user: User, payload: WashroomCreateRequest
    ) -> Washroom:
        prop = await self._property_for_write(user, payload.property_uid)
        # dorm-scoped washroom — attached to exactly one dorm; inherits the
        # dorm's zone/area when none is supplied explicitly
        dorm = await self._dorm_in_property(payload.dorm_uid, prop.id)
        zone = await self._zone_for_washroom(payload.zone_uid, prop.id)
        if zone is None and dorm is not None:
            zone = await self._zone_for_washroom(dorm.zone_id, prop.id)
        area_id = await self._area_in_property(payload.area_uid, prop.id)
        if area_id is None and dorm is not None:
            area_id = dorm.area_id
        area_id = self._validate_washroom_area(zone, area_id)
        if dorm is not None:
            # dorm-owned → the name is DERIVED from the dorm; one per dorm
            name = f"{dorm.name} - Washroom"
            if await self._dorm_has_washroom(prop.id, dorm.id):
                raise ConflictErr(
                    f"{dorm.name} already has an attached washroom.",
                    field="dorm_uid",
                )
        else:
            name = payload.name.strip()
        if await self._washroom_name_exists(prop.id, name):
            raise ConflictErr(
                f"Washroom '{name}' already exists in this property.",
                field="name",
            )
        washroom = Washroom(
            property_id=prop.id,
            zone_id=zone.id if zone else None,
            area_id=area_id,
            dorm_id=dorm.id if dorm else None,
            name=name,
            washroom_type=self._washroom_type(payload.washroom_type),
            status="available",
        )
        self.session.add(washroom)
        await self.session.flush()
        await self._sync_fixtures(washroom, self._payload_fixture_counts(payload))
        if zone:
            self._record(
                user, "washroom", washroom.id, prop.id,
                to_zone=zone.id, to_area=area_id,
            )
        await self._commit()
        return await self._reload_washroom(washroom.id)

    async def bulk_create_washrooms(
        self, user: User, payload: WashroomBulkCreateRequest
    ) -> dict:
        """All-or-nothing washroom creation — same batch contract as dorms."""
        prop = await self._property_for_write(user, payload.property_uid)
        errors: list[str] = []
        # Resolve dorms first — dorm-owned rows derive their display name
        # from the dorm ("{dorm} - Washroom"), not from the payload.
        dorms: dict[int, Dorm | None] = {}
        for i, item in enumerate(payload.washrooms, start=1):
            try:
                dorms[i] = await self._dorm_in_property(item.dorm_uid, prop.id)
            except ValidationErr as exc:
                errors.append(f"Row {i} ('{item.name.strip()}'): {exc.message}")
                dorms[i] = None
        names = [
            f"{dorms[i].name} - Washroom" if dorms[i] is not None
            else item.name.strip()
            for i, item in enumerate(payload.washrooms, start=1)
        ]
        res = await self.session.execute(
            select(Washroom.name).where(
                Washroom.property_id == prop.id,
                func.lower(Washroom.name).in_([n.lower() for n in names]),
            )
        )
        existing = {n.lower() for n in res.scalars()}
        seen: dict[str, int] = {}
        seen_dorms: dict[uuid.UUID, int] = {}
        zones: dict[int, Zone | None] = {}
        areas: dict[int, uuid.UUID | None] = {}
        for i, item in enumerate(payload.washrooms, start=1):
            name = names[i - 1]
            key = name.lower()
            if key in seen:
                errors.append(f"Row {i}: '{name}' duplicates row {seen[key]}")
            elif key in existing:
                errors.append(f"Row {i}: '{name}' already exists in this property")
            else:
                seen[key] = i
            # One attached washroom per dorm — enforced at row level AND
            # within the batch (the DB unique constraint is the backstop).
            dorm = dorms[i]
            if dorm is not None:
                if dorm.id in seen_dorms:
                    errors.append(
                        f"Row {i}: '{dorm.name}' already targeted by row "
                        f"{seen_dorms[dorm.id]}"
                    )
                elif await self._dorm_has_washroom(prop.id, dorm.id):
                    errors.append(
                        f"Row {i}: '{dorm.name}' already has an attached washroom"
                    )
                else:
                    seen_dorms[dorm.id] = i
            try:
                self._washroom_type(item.washroom_type)
            except ValidationErr as exc:
                errors.append(f"Row {i} ('{name}'): {exc.message}")
            try:
                zones[i] = await self._zone_for_washroom(item.zone_uid, prop.id)
                if zones[i] is None and dorms[i] is not None:
                    zones[i] = await self._zone_for_washroom(
                        dorms[i].zone_id, prop.id
                    )
            except ValidationErr as exc:
                errors.append(f"Row {i} ('{name}'): {exc.message}")
                zones[i] = None
            try:
                areas[i] = await self._area_in_property(item.area_uid, prop.id)
                if areas[i] is None and dorms[i] is not None:
                    areas[i] = dorms[i].area_id
                self._validate_washroom_area(zones[i], areas[i])
            except ValidationErr as exc:
                errors.append(f"Row {i} ('{name}'): {exc.message}")
                areas[i] = None
        if errors:
            raise ValidationErr("; ".join(errors), field="washrooms")

        created: list[Washroom] = []
        for i, item in enumerate(payload.washrooms, start=1):
            zone = zones[i]
            dorm = dorms[i]
            area_id = self._validate_washroom_area(zone, areas[i])
            washroom = Washroom(
                property_id=prop.id,
                zone_id=zone.id if zone else None,
                area_id=area_id,
                dorm_id=dorm.id if dorm else None,
                name=names[i - 1],
                washroom_type=self._washroom_type(item.washroom_type),
                status="available",
            )
            self.session.add(washroom)
            await self.session.flush()
            await self._sync_fixtures(
                washroom, self._payload_fixture_counts(item)
            )
            if zone:
                self._record(
                    user, "washroom", washroom.id, prop.id,
                    to_zone=zone.id, to_area=area_id,
                )
            created.append(washroom)
        await self._commit()
        return {
            "created": [
                await self._reload_washroom(w.id) for w in created
            ],
            "errors": [],
        }

    async def update_washroom(
        self, user: User, washroom_id: uuid.UUID, payload: WashroomUpdateRequest
    ) -> Washroom:
        washroom, _ = await self._get(Washroom, washroom_id, user)
        data = payload.model_dump(exclude_unset=True)

        # Dorm-owned washrooms derive their name from the parent dorm —
        # manual renames are ignored (name is dropped from the update).
        dorm_owned = washroom.dorm_id is not None or data.get("dorm_uid")
        if "name" in data:
            if dorm_owned:
                data.pop("name")
            elif data["name"] != washroom.name:
                if await self._washroom_name_exists(washroom.property_id, data["name"]):
                    raise ConflictErr(
                        f"Washroom '{data['name'].strip()}' already exists in this property.",
                        field="name",
                    )
                data["name"] = data["name"].strip()
        if "washroom_type" in data:
            data["washroom_type"] = self._washroom_type(data["washroom_type"])

        zone_marker = object()
        zone = zone_marker
        if "zone_uid" in data:
            zone = await self._zone_for_washroom(
                data.pop("zone_uid"), washroom.property_id
            )
        area_marker = object()
        requested_area = area_marker
        if "area_uid" in data:
            requested_area = await self._area_in_property(
                data.pop("area_uid"), washroom.property_id
            )
        dorm_marker = object()
        dorm = dorm_marker
        if "dorm_uid" in data:
            dorm = await self._dorm_in_property(
                data.pop("dorm_uid"), washroom.property_id
            )
        if dorm is not dorm_marker:
            washroom.dorm_id = dorm.id if dorm else None
            if dorm is not None:
                # Re-parent → derived name follows the new dorm; the unique
                # (property, name) + dorm_id constraints must not collide.
                new_name = f"{dorm.name} - Washroom"
                if new_name != washroom.name and await self._washroom_name_exists(
                    washroom.property_id, new_name
                ):
                    raise ConflictErr(
                        f"Washroom '{new_name}' already exists in this property.",
                        field="name",
                    )
                washroom.name = new_name
                if await self._dorm_has_other_washroom(
                    washroom.property_id, dorm.id, washroom.id
                ):
                    raise ConflictErr(
                        f"{dorm.name} already has an attached washroom.",
                        field="dorm_uid",
                    )
                # Attaching to a dorm re-parents the washroom into the dorm's
                # zone/area unless the caller explicitly overrides them
                if zone is zone_marker:
                    washroom.zone_id = dorm.zone_id
                    washroom.area_id = (
                        dorm.area_id
                        if requested_area is area_marker
                        else requested_area
                    )
            elif "name" not in data:
                # Detaching → keep the existing name unless caller supplies one
                pass
        if zone is not zone_marker:
            area_id = (
                washroom.area_id if requested_area is area_marker else requested_area
            )
            area_id = self._validate_washroom_area(zone, area_id)
            from_zone, from_area = washroom.zone_id, washroom.area_id
            washroom.zone_id = zone.id if zone else None
            washroom.area_id = area_id
            if from_zone != washroom.zone_id or from_area != washroom.area_id:
                self._record(
                    user, "washroom", washroom.id, washroom.property_id,
                    from_zone=from_zone, to_zone=washroom.zone_id,
                    from_area=from_area, to_area=washroom.area_id,
                )
        elif requested_area is not area_marker:
            washroom.area_id = requested_area

        # Fixture-count fields are resize directives — translate them into
        # real washroom_fixtures rows rather than attributes on the washroom.
        fixture_counts = self._payload_fixture_counts(payload)
        if "custom_fixtures" in data:
            # The provided map is authoritative for custom types — types on
            # the washroom but absent from the map are removed.
            existing_custom = {
                f.fixture_type
                for f in washroom.fixtures
                if f.fixture_type not in self._FIXTURE_BUILTIN_TYPES
            }
            for t in existing_custom - set(fixture_counts):
                fixture_counts[t] = 0
        if fixture_counts:
            await self._sync_fixtures(washroom, fixture_counts)
        for k, v in data.items():
            if (
                k in {f"{t}_count" for t in self._FIXTURE_BUILTIN_TYPES}
                or k == "custom_fixtures"
            ):
                continue
            setattr(washroom, k, v)
        await self._commit()
        return await self._reload_washroom(washroom.id)

    # ------------------------------------------------------------------
    # Washroom fixtures — real per-fixture records
    # ------------------------------------------------------------------

    _FIXTURE_BUILTIN_TYPES = (
        "stall", "urinal", "shower", "sink", "mirror", "bath_tub", "jacuzzi",
    )

    def _payload_fixture_counts(self, payload) -> dict[str, int]:
        """Builtin count fields (stall_count, …) + custom_fixtures map →
        {fixture_type: target_count}."""
        counts: dict[str, int] = {}
        for t in self._FIXTURE_BUILTIN_TYPES:
            v = getattr(payload, f"{t}_count", None)
            if v is not None:
                counts[t] = int(v)
        for k, v in (getattr(payload, "custom_fixtures", None) or {}).items():
            counts[str(k).strip()] = int(v)
        return counts

    async def _sync_fixtures(
        self, washroom: Washroom, counts: dict[str, int]
    ) -> None:
        """Resize the fixture inventory to match `counts` — grow appends new
        numbered fixtures, shrink removes rows from the tail of that type.
        Custom-type keys not present in `counts` are left untouched unless
        they appear in `counts` explicitly."""
        res = await self.session.execute(
            select(WashroomFixture).where(
                WashroomFixture.washroom_id == washroom.id
            )
        )
        existing = list(res.scalars())
        by_type: dict[str, list[WashroomFixture]] = {}
        for f in existing:
            by_type.setdefault(f.fixture_type, []).append(f)

        for kind, target in counts.items():
            kind = kind.strip()
            if not kind:
                continue
            rows = sorted(
                by_type.get(kind, []), key=lambda f: f.fixture_number
            )
            if target > len(rows):
                for i in range(len(rows) + 1, target + 1):
                    self.session.add(
                        WashroomFixture(
                            property_id=washroom.property_id,
                            washroom_id=washroom.id,
                            fixture_type=kind,
                            fixture_number=i,
                            status="operational",
                        )
                    )
            elif target < len(rows):
                for f in rows[target:]:
                    await self.session.delete(f)
        await self.session.flush()

    async def _get_fixture(
        self, user: User, washroom_id: uuid.UUID, fixture_id: uuid.UUID
    ) -> WashroomFixture:
        washroom, _ = await self._get(Washroom, washroom_id, user)
        res = await self.session.execute(
            select(WashroomFixture).where(
                WashroomFixture.id == fixture_id,
                WashroomFixture.washroom_id == washroom.id,
            )
        )
        fixture = res.scalar_one_or_none()
        if fixture is None:
            raise NotFoundErr("Fixture not found in this washroom.")
        return fixture

    async def update_fixture(
        self,
        user: User,
        washroom_id: uuid.UUID,
        fixture_id: uuid.UUID,
        status: str,
    ) -> Washroom:
        """Fixture state is resource state — committed via the central
        state service as an audited administrative transition (staff —
        super_admin / property_manager — enforced inside transition()).
        Restoring a fixture to 'operational' also acknowledges its open
        maintenance tickets."""
        from app.domain.resource_events import SRC_ADMIN_OVERRIDE
        from app.services.resource_state import ResourceStateService

        status = status.strip().lower()
        fixture = await self._get_fixture(user, washroom_id, fixture_id)
        prev = fixture.status
        await ResourceStateService(self.session).transition(
            "fixture", fixture.id, status, user=user,
            source=SRC_ADMIN_OVERRIDE,
            reason=f"Fixture marked '{status}' from washroom detail",
        )
        if status == "operational" and prev != "operational":
            await self._close_fixture_maintenance(user, fixture)
            # the parent washroom may have been flagged only by this
            # fixture's ticket — re-derive its projection in the same txn
            await ResourceStateService(self.session).derive(
                "washroom", fixture.washroom_id, release_to="available",
                user=user, source=SRC_ADMIN_OVERRIDE,
                reason="Fixture restored to service",
            )
        await self._commit()
        return await self._reload_washroom(washroom_id)

    async def _close_fixture_maintenance(
        self, user: User, fixture: WashroomFixture
    ) -> None:
        """A manager restoring a fixture to service implicitly acknowledges
        its maintenance — every ticket still blocking this fixture is
        resolved (if not already) and closed, keeping the operational board
        and the ticket ledger in sync."""
        from app.domain.resource_states import BLOCKING_MAINTENANCE

        res = await self.session.execute(
            select(MaintenanceTicket).where(
                MaintenanceTicket.washroom_fixture_id == fixture.id,
                MaintenanceTicket.status.in_(BLOCKING_MAINTENANCE),
            ).with_for_update()
        )
        now = datetime.now(timezone.utc)
        for ticket in res.scalars():
            if ticket.status != "resolved":
                ticket.resolved_at = now
                self.session.add(MaintenanceTicketEvent(
                    ticket_id=ticket.id, action="resolved",
                    actor_name=user.name,
                    comment=f"{fixture.label} restored to service",
                ))
            ticket.status = "closed"
            ticket.closed_at = now
            self.session.add(MaintenanceTicketEvent(
                ticket_id=ticket.id, action="closed",
                actor_name=user.name,
                comment=f"{fixture.label} marked operational",
            ))
        await self.session.flush()

    async def allocate_washroom(
        self, user: User, washroom_id: uuid.UUID, area_uid, zone_uid
    ) -> Washroom:
        washroom, _ = await self._get(Washroom, washroom_id, user)
        zone = await self._zone_for_washroom(zone_uid, washroom.property_id)
        area_id = await self._area_in_property(area_uid, washroom.property_id)
        area_id = self._validate_washroom_area(zone, area_id)
        from_zone, from_area = washroom.zone_id, washroom.area_id
        washroom.zone_id = zone.id if zone else None
        washroom.area_id = area_id
        if from_zone != washroom.zone_id or from_area != washroom.area_id:
            self._record(
                user, "washroom", washroom.id, washroom.property_id,
                from_zone=from_zone, to_zone=washroom.zone_id,
                from_area=from_area, to_area=washroom.area_id,
            )
        await self._commit()
        return await self._reload_washroom(washroom.id)

    async def delete_washroom(self, user: User, washroom_id: uuid.UUID) -> None:
        """Delete the resource, not its history — task/ticket rows keep their
        denormalized washroom name while ON DELETE SET NULL on
        tasks.washroom_id / maintenance_tickets.washroom_id releases the
        live link automatically."""
        washroom, _ = await self._get(Washroom, washroom_id, user)
        await self.session.execute(
            sa_delete(Washroom).where(Washroom.id == washroom.id)
        )
        await self._commit()

    async def dorm_checkout(self, user: User, dorm_id: uuid.UUID) -> dict:
        """Check out every occupied bed — delegates to the ONE checkout
        pipeline (OccupancyService.checkout_units): close occupancy →
        create cleaning task → OCCUPIED → CLEANING → re-derive aggregate,
        all inside ONE commit. Beds never pass through 'available'."""
        from app.services.occupancy import OccupancyService

        dorm, _ = await self._get(
            Dorm, dorm_id, user, options=[selectinload(Dorm.beds)]
        )
        res = {"generated": []}
        prop = await self.session.get(Property, dorm.property_id)
        if prop:
            res = await OccupancyService(self.session).checkout_units(
                user, prop, beds=list(dorm.beds),
                reason="Dorm checkout — cleaning required",
            )
            await self._commit()
            await self._fire_automation(
                user, dorm.property_id,
                "bed_available_after_checkout", dorm.zone_id,
            )
        return {
            "dorm": await self._reload_dorm(dorm.id),
            "generated": res["generated"],
        }

    async def dorm_mark_cleaning(self, user: User, dorm_id: uuid.UUID) -> Dorm:
        """Send the dorm's available beds to cleaning — explicit command.

        The command itself flags the beds + dorm through the state engine
        (task_queued); the generated task holds CLEANING until its
        lifecycle releases it."""
        from app.domain.resource_events import SRC_TASK_QUEUED
        from app.services.resource_state import ResourceStateService

        dorm, _ = await self._get(
            Dorm, dorm_id, user, options=[selectinload(Dorm.beds)]
        )
        changed = [b for b in dorm.beds if b.status == "available"]
        if changed:
            prop = await self.session.get(Property, dorm.property_id)
            if prop:
                await self._generate_cleaning_tasks(
                    user, prop, "cleaning", [], changed
                )
                state = ResourceStateService(self.session)
                for b in changed:
                    await state.transition(
                        "bed", b.id, "cleaning", user=user,
                        source=SRC_TASK_QUEUED,
                        reason="Dorm marked for cleaning",
                    )
                if dorm.status in ("available", "occupied"):
                    await state.transition(
                        "dorm", dorm.id, "cleaning", user=user,
                        source=SRC_TASK_QUEUED,
                        reason="Dorm marked for cleaning",
                    )
                await self._commit()
            await self._fire_automation(user, dorm.property_id,
                                        "bed_marked_cleaning", dorm.zone_id)
        return await self._reload_dorm(dorm.id)

    async def dorm_mark_cleaned(self, user: User, dorm_id: uuid.UUID) -> Dorm:
        """Staff release (super_admin / property_manager): honestly close
        blocking work (admin_closed events — never fabricated approvals)
        then derive availability."""
        if user.role not in (UserRole.SUPER_ADMIN, UserRole.PROPERTY_MANAGER):
            from app.dependencies.auth import Forbidden
            raise Forbidden(
                "Releasing resource state requires a staff role "
                "(Super Admin or Property Manager)."
            )
        dorm, _ = await self._get(
            Dorm, dorm_id, user, options=[selectinload(Dorm.beds)]
        )
        changed = [
            b for b in dorm.beds if b.status in ("cleaning", "maintenance")
        ]
        if changed:
            prop = await self.session.get(Property, dorm.property_id)
            if prop:
                await self._mark_cleaning_work_done(user, prop, [], changed)
                await self._close_blocking_maintenance(user, prop, [], changed)
            from app.services.resource_state import ResourceStateService
            await ResourceStateService(self.session).derive(
                "dorm", dorm.id, release_to="available", user=user,
                source="admin_override",
            )
            await self._commit()
        return await self._reload_dorm(dorm.id)

    async def _reload_washroom(self, washroom_id: uuid.UUID) -> Washroom:
        res = await self.session.execute(
            select(Washroom)
            .where(Washroom.id == washroom_id)
            .options(selectinload(Washroom.fixtures))
            .execution_options(populate_existing=True)  # refresh stale collections
        )
        return res.scalar_one()

    async def _reload_dorm(self, dorm_id: uuid.UUID) -> Dorm:
        res = await self.session.execute(
            select(Dorm)
            .where(Dorm.id == dorm_id)
            .options(selectinload(Dorm.beds))
            .execution_options(populate_existing=True)  # refresh stale collections
        )
        return res.scalar_one()

    async def _mark_cleaning_work_done(
        self, user: User, prop: Property,
        rooms: list[Room], beds: list[Bed],
        washrooms: list["Washroom"] | None = None,
    ) -> None:
        """Honestly terminate open tasks on an authorized release action.

        Every open task on the targeted units is admin_closed (not only
        housekeeping — an explicit release terminates all blocking work).
        Room/washroom tasks complete outright. Dorm tasks may cover several
        beds, so a partial bed selection removes those beds from the task
        coverage; the task completes only once every covered bed has been
        released.
        """
        room_ids = {r.id for r in rooms}
        dorm_ids = {b.dorm_id for b in beds}
        washroom_ids = {w.id for w in washrooms or []}
        fixture_ids = {
            f.id for w in washrooms or [] for f in w.fixtures
        }
        if not room_ids and not dorm_ids and not washroom_ids and not fixture_ids:
            return

        scope = []
        if room_ids:
            scope.append(Task.room_id.in_(room_ids))
        if dorm_ids:
            scope.append(Task.dorm_id.in_(dorm_ids))
        if washroom_ids:
            scope.append(Task.washroom_id.in_(washroom_ids))
        if fixture_ids:
            scope.append(Task.washroom_fixture_id.in_(fixture_ids))
        res = await self.session.execute(
            select(Task).where(
                Task.property_id == prop.id,
                or_(*scope),
                Task.status.not_in(("completed", "cancelled", "abandoned")),
            ).with_for_update()
        )
        tasks = list(res.scalars())

        dorms = {}
        if dorm_ids:
            res = await self.session.execute(
                select(Dorm).where(Dorm.id.in_(dorm_ids))
                .options(selectinload(Dorm.beds))
            )
            dorms = {d.id: d for d in res.scalars()}
        selected_bed_ids = {str(b.id) for b in beds}
        now = datetime.now(timezone.utc)

        for task in tasks:
            # admin_close every open task on the targeted units — an explicit
            # release is an authorized termination of ALL blocking work, not
            # only housekeeping
            if task.room_id in room_ids:
                task.status = "completed"
                task.completed_at = now
                self.session.add(TaskHistoryEvent(
                    task_id=task.id, type="admin_closed", actor_name=user.name,
                    note="Closed administratively — room marked cleaned "
                         "by an authorized override (no task approval)",
                ))
                continue
            if (task.washroom_id in washroom_ids
                    or task.washroom_fixture_id in fixture_ids):
                task.status = "completed"
                task.completed_at = now
                self.session.add(TaskHistoryEvent(
                    task_id=task.id, type="admin_closed", actor_name=user.name,
                    note="Closed administratively — washroom marked "
                         "available by an authorized override "
                         "(no task approval)",
                ))
                continue
            if task.dorm_id not in dorm_ids:
                continue
            dorm = dorms.get(task.dorm_id)
            if dorm is None:
                continue
            if task.bed_ids:
                covered_ids = {str(bed_id) for bed_id in task.bed_ids}
            else:
                covered_ids = {
                    str(b.id) for b in dorm.beds if b.status != "inactive"
                }
            remaining = [
                str(b.id) for b in dorm.beds
                if str(b.id) in covered_ids - selected_bed_ids
            ]
            if remaining:
                task.bed_ids = remaining
                self.session.add(TaskHistoryEvent(
                    task_id=task.id, type="updated", actor_name=user.name,
                    note="Selected beds marked cleaned manually; "
                         f"{len(remaining)} bed(s) remain in cleaning",
                ))
            else:
                task.status = "completed"
                task.completed_at = now
                self.session.add(TaskHistoryEvent(
                    task_id=task.id, type="admin_closed", actor_name=user.name,
                    note="Closed administratively — dorm cleaning marked "
                         "complete by an authorized override",
                ))
        await self.session.flush()

    async def _close_blocking_maintenance(
        self, user: User, prop: Property,
        rooms: list[Room], beds: list[Bed],
        washrooms: list["Washroom"] | None = None,
    ) -> None:
        """Acknowledge maintenance blocks for an explicit Mark Cleaned action.

        `closed` is used rather than a bare status write because maintenance
        tickets are the operational source of truth. Bed-level tickets release
        only their selected bed; dorm-wide tickets still require a dorm-level
        acknowledgement.
        """
        from app.domain.resource_states import BLOCKING_MAINTENANCE

        room_ids = {r.id for r in rooms}
        bed_ids = {b.id for b in beds}
        washroom_ids = {w.id for w in washrooms or []}
        fixture_ids = {
            f.id for w in washrooms or [] for f in w.fixtures
        }
        if not room_ids and not bed_ids and not washroom_ids and not fixture_ids:
            return
        scope = []
        if room_ids:
            scope.append(MaintenanceTicket.room_id.in_(room_ids))
        if bed_ids:
            scope.append(MaintenanceTicket.bed_id.in_(bed_ids))
        if washroom_ids:
            scope.append(MaintenanceTicket.washroom_id.in_(washroom_ids))
        if fixture_ids:
            scope.append(MaintenanceTicket.washroom_fixture_id.in_(fixture_ids))
        res = await self.session.execute(
            select(MaintenanceTicket).where(
                MaintenanceTicket.property_id == prop.id,
                or_(*scope),
                MaintenanceTicket.status.in_(BLOCKING_MAINTENANCE),
            ).with_for_update()
        )
        now = datetime.now(timezone.utc)
        for ticket in res.scalars():
            if ticket.status != "resolved":
                ticket.resolved_at = now
                self.session.add(MaintenanceTicketEvent(
                    ticket_id=ticket.id, action="resolved",
                    actor_name=user.name,
                    comment="Marked ready manually",
                ))
            ticket.status = "closed"
            ticket.closed_at = now
            self.session.add(MaintenanceTicketEvent(
                ticket_id=ticket.id, action="closed",
                actor_name=user.name,
                comment="Unit marked cleaned and ready",
            ))
        await self.session.flush()

    # ------------------------------------------------------------------
    # Bulk unit status (rooms + beds in one call)
    # ------------------------------------------------------------------

    async def bulk_unit_status(
        self, user: User, payload: BulkUnitStatusRequest
    ) -> dict:
        """Bulk operations become workflow commands, never raw status writes:

          checkout     — occupancy close + cleaning task + →CLEANING (spec §3)
          cleaning     — queue cleaning tasks only (flag on task START)
          cleaned      — staff: honestly close blocking work + release
          available    — staff: honestly close ALL blocking work —
                           cleaning tasks admin_closed + maintenance tickets
                           resolved/closed under the actor — then derive;
                           only occupancy/inactive still hold the unit
          maintenance  — staff: admin_override →MAINTENANCE (audited)
        """
        from app.dependencies.auth import Forbidden
        from app.domain.resource_events import (
            SRC_ADMIN_OVERRIDE,
            SRC_TASK_QUEUED,
        )
        from app.services.occupancy import OccupancyService
        from app.services.resource_state import ResourceStateService

        prop = await self._property_for_write(user, payload.property_uid)
        action = payload.action
        if action not in {
            "checkout", "cleaning", "available", "cleaned", "maintenance"
        }:
            raise ValidationErr(
                "action must be checkout|cleaning|available|cleaned|maintenance",
                field="action")
        # state-forcing actions are staff authority (spec §13) — the
        # property's own manager may drive the same audited transitions;
        # _property_for_write above already confined the PM to their
        # assigned property
        if action in {"available", "cleaned", "maintenance"} \
                and user.role not in (
                    UserRole.SUPER_ADMIN, UserRole.PROPERTY_MANAGER):
            raise Forbidden(
                "Direct resource transitions require a staff role "
                "(Super Admin or Property Manager)."
            )
        reason = (payload.reason or "").strip() or (
            f"Bulk {action} — {len(payload.room_uids)} room(s), "
            f"{len(payload.bed_uids)} bed(s)"
        )

        state = ResourceStateService(self.session)
        occ_svc = OccupancyService(self.session)
        rooms = dorms = beds = washrooms = []
        skipped_blocked: list[str] = []
        prev_bed_status: dict[uuid.UUID, str] = {}

        if payload.room_uids:
            res = await self.session.execute(
                select(Room).where(
                    Room.id.in_(payload.room_uids), Room.property_id == prop.id
                )
            )
            rooms = list(res.scalars())
        if payload.bed_uids:
            res = await self.session.execute(
                select(Bed)
                .where(Bed.id.in_(payload.bed_uids))
                .options(selectinload(Bed.dorm))
            )
            beds = [b for b in res.scalars() if b.dorm.property_id == prop.id]
            prev_bed_status = {b.id: b.status for b in beds}
            dorm_ids = {b.dorm_id for b in beds}
            res = await self.session.execute(
                select(Dorm).where(Dorm.id.in_(dorm_ids))
                .options(selectinload(Dorm.beds))
            )
            dorms = list(res.scalars())
        if payload.washroom_uids:
            res = await self.session.execute(
                select(Washroom).where(
                    Washroom.id.in_(payload.washroom_uids),
                    Washroom.property_id == prop.id,
                ).options(selectinload(Washroom.fixtures))
            )
            washrooms = list(res.scalars())

        generated: list[Task] = []

        if action == "checkout":
            # the unified checkout pipeline — close occupancy → spawn
            # checkout cleaning → OCCUPIED → CLEANING → re-derive dorm
            # aggregates, all inside one commit (spec §3/§9).
            res = await occ_svc.checkout_units(user, prop, rooms=rooms,
                                               beds=beds)
            out_rooms, out_beds = res["rooms"], res["beds"]
            generated = res["generated"]
            await self._commit()
            for b in out_beds:
                await self._fire_automation(
                    user, prop.id, "bed_available_after_checkout",
                    b.dorm.zone_id)
            for r in out_rooms:
                await self._fire_automation(
                    user, prop.id, "room_checked_out", r.zone_id)

        elif action == "cleaning":
            # Explicit command — the request itself is the flag event:
            # every targeted unit goes CLEANING now and the queued task
            # (BLOCKING_TASK) holds it until its lifecycle releases it.
            # Generated/scheduled work stays flag-on-start in start_task.
            generated = await self._generate_cleaning_tasks(
                user, prop, "cleaning", rooms, beds
            )
            for r in rooms:
                if r.status in ("available", "occupied"):
                    await state.transition(
                        "room", r.id, "cleaning", user=user,
                        source=SRC_TASK_QUEUED, reason=reason,
                    )
            for b in beds:
                if b.status in ("available", "occupied"):
                    await state.transition(
                        "bed", b.id, "cleaning", user=user,
                        source=SRC_TASK_QUEUED, reason=reason,
                    )
            for d in dorms:
                # a flagged bed aggregates the dorm to cleaning —
                # same explicit flag the task-start path applies
                if d.status in ("available", "occupied"):
                    await state.transition(
                        "dorm", d.id, "cleaning", user=user,
                        source=SRC_TASK_QUEUED,
                        reason="Bed cleaning — aggregate flag",
                    )
            await self._commit()
            for b in beds:
                await self._fire_automation(
                    user, prop.id, "bed_marked_cleaning", b.dorm.zone_id)

        elif action in {"available", "cleaned"}:
            # Both release actions honestly terminate blocking work:
            # cleaning tasks get admin_closed history events and tickets
            # resolved+closed events — all under the acting Super Admin,
            # never a silent status flip or a fabricated approval.
            await self._mark_cleaning_work_done(
                user, prop, rooms, beds, washrooms)
            await self._close_blocking_maintenance(
                user, prop, rooms, beds, washrooms)
            released_occupied_dorm_ids: set[uuid.UUID] = set()
            for r in rooms:
                if r.status == "occupied":
                    if action == "available":
                        # Super Admin force-release — the gated admin
                        # transition performs checkout semantics itself:
                        # the open occupancy closes and the guest mirror
                        # clears inside the same audited write.
                        await state.transition(
                            "room", r.id, "available", user=user,
                            source=SRC_ADMIN_OVERRIDE,
                            reason=reason,
                        )
                    continue
                new = await state.derive(
                    "room", r.id, release_to="available", user=user,
                    source="admin_override" if action == "cleaned" else "derive",
                )
                if new is None and r.status in ("cleaning", "maintenance"):
                    skipped_blocked.append(r.room_number)
                elif r.status == "available":
                    r.current_guest = None
            for b in beds:
                if b.status == "occupied":
                    if action == "available":
                        await state.transition(
                            "bed", b.id, "available", user=user,
                            source=SRC_ADMIN_OVERRIDE,
                            reason=reason,
                        )
                        released_occupied_dorm_ids.add(b.dorm_id)
                    continue
                if b.status == "inactive":
                    continue
                new = await state.derive(
                    "bed", b.id, release_to="available", user=user,
                    source="admin_override" if action == "cleaned" else "derive",
                )
                if new is None and b.status in ("cleaning", "maintenance"):
                    skipped_blocked.append(b.bed_number)
                elif b.status == "available":
                    b.guest_name = None
            # dorms aggregate their beds — recompute any dorm whose beds
            # were force-released out of occupied
            for d in dorms:
                if d.id in released_occupied_dorm_ids:
                    await state.derive(
                        "dorm", d.id, release_to="available", user=user,
                        source=SRC_ADMIN_OVERRIDE,
                        reason="Bed release — aggregate recompute",
                    )
            for w in washrooms:
                # fixtures release first — a maintenance fixture is a
                # washroom-level blocker
                for f in w.fixtures:
                    if f.status == "inactive":
                        continue
                    await state.derive(
                        "fixture", f.id, release_to="operational",
                        user=user,
                        source="admin_override" if action == "cleaned" else "derive",
                    )
                if w.status == "inactive":
                    continue
                new = await state.derive(
                    "washroom", w.id, release_to="available", user=user,
                    source="admin_override" if action == "cleaned" else "derive",
                )
                if new is None and w.status in ("cleaning", "maintenance"):
                    skipped_blocked.append(w.name)
            await self._commit()

        else:  # maintenance — audited admin override, not a phantom flag
            for r in rooms:
                if r.status == "occupied":
                    skipped_blocked.append(r.room_number)
                    continue
                try:
                    await state.transition(
                        "room", r.id, "maintenance", user=user,
                        source=SRC_ADMIN_OVERRIDE, reason=reason,
                    )
                except (ConflictErr, ValidationErr):
                    skipped_blocked.append(r.room_number)
            for b in beds:
                if b.status in ("occupied", "inactive"):
                    skipped_blocked.append(b.bed_number)
                    continue
                try:
                    await state.transition(
                        "bed", b.id, "maintenance", user=user,
                        source=SRC_ADMIN_OVERRIDE, reason=reason,
                    )
                except (ConflictErr, ValidationErr):
                    skipped_blocked.append(b.bed_number)
            await self._commit()

        return {"rooms": rooms, "dorms": dorms, "washrooms": washrooms,
                "generated_tasks": generated,
                "skipped_blocked": skipped_blocked}

    async def _generate_cleaning_tasks(
        self, user: User, prop: Property, action: str,
        rooms: list[Room], beds: list[Bed],
    ) -> list[Task]:
        """One cleaning task per room / per dorm — ROUND-ROBIN per unit:
        every unit gets its own allocation step, so the zone pool's
        persistent pointer advances per room (201→A, 202→B, 203→C, 204→A…)
        and repeated bulk operations continue the rotation instead of
        restarting at the first employee. Units already holding an open
        cleaning task are skipped WITHOUT consuming a rotation step."""
        from collections import defaultdict

        from app.services.task import IST
        from app.services.work_allocation import WorkAllocationService

        label = "Checkout cleaning" if action == "checkout" else "Cleaning"
        allocs = WorkAllocationService(self.session)
        today = datetime.now(IST).date().isoformat()
        generated: list[Task] = []
        zone_names: dict[uuid.UUID | None, str | None] = {}

        async def zname(zone_id):
            if zone_id not in zone_names:
                zn = await self.session.get(Zone, zone_id) if zone_id else None
                zone_names[zone_id] = zn.name if zn else None
            return zone_names[zone_id]

        area_names: dict[uuid.UUID | None, str | None] = {}

        async def aname(area_id):
            if area_id not in area_names:
                a = await self.session.get(Area, area_id) if area_id else None
                area_names[area_id] = a.name if a else None
            return area_names[area_id]

        async def alloc_for(zone_id, area_id=None):
            return await allocs.allocate(
                user, property_id=prop.id, zone_id=zone_id,
                zone_name=await zname(zone_id), work_type="cleaning",
                manager_employee_id=prop.manager_employee_id,
                area_id=area_id, area_name=await aname(area_id),
            )

        # One task per room — each room is an independent allocation unit.
        for r in rooms:
            title = f"{label} — {r.room_number}"
            if await self._has_open_cleaning(prop.id, r.id, title):
                continue  # already queued — don't consume a rotation step
            from app.services.task_location import resolve_task_location
            location = await resolve_task_location(
                self.session, property_id=prop.id, room_id=r.id,
            )
            alloc = await alloc_for(location.zone_id, location.area_id)
            t = await self._spawn_cleaning_task(
                user, prop, allocs, title=title, zone_id=location.zone_id,
                area_id=location.area_id, room=r, alloc=alloc, today=today,
                origin="checkout" if action == "checkout" else "manual",
            )
            if t:
                generated.append(t)

        # One task per dorm (its beds covered by the same cleaning task).
        dorms: dict[uuid.UUID, list[Bed]] = defaultdict(list)
        for b in beds:
            dorms[b.dorm_id].append(b)
        for dorm_beds in dorms.values():
            dorm = dorm_beds[0].dorm
            nums = ", ".join(sorted(b.bed_number for b in dorm_beds))
            title = f"{label} — {dorm.name or 'Dorm'} ({nums})"
            if await self._has_open_cleaning(prop.id, None, title,
                                             dorm_id=dorm.id):
                continue
            from app.services.task_location import resolve_task_location
            location = await resolve_task_location(
                self.session, property_id=prop.id, dorm_id=dorm.id,
            )
            alloc = await alloc_for(location.zone_id, location.area_id)
            t = await self._spawn_cleaning_task(
                user, prop, allocs, title=title, zone_id=location.zone_id,
                area_id=location.area_id, room=None, dorm=dorm, beds=dorm_beds,
                alloc=alloc, today=today,
                origin="checkout" if action == "checkout" else "manual",
            )
            if t:
                generated.append(t)
        return generated

    async def _has_open_cleaning(self, property_id, room_id, title,
                                 dorm_id=None) -> bool:
        """Dedupe — an identical OPEN cleaning task means the unit is
        already queued for work; never create a second ticket."""
        dorm_cond = Task.dorm_id.is_(None) if dorm_id is None \
            else Task.dorm_id == dorm_id
        res = await self.session.execute(
            select(Task.id).where(
                Task.property_id == property_id,
                Task.title == title,
                Task.room_id == room_id,
                dorm_cond,
                Task.status.not_in(("completed", "cancelled", "abandoned")),
            )
        )
        return res.scalar_one_or_none() is not None

    async def _spawn_cleaning_task(
        self, user: User, prop: Property, allocs, *,
        title: str, zone_id, area_id, room, alloc, today: str,
        dorm=None, beds=None, origin: str = "manual",
    ) -> Task | None:
        """Create one cleaning task for the allocation result."""
        from sqlalchemy.exc import IntegrityError

        from app.models.task import TaskHistoryEvent
        from app.services.maintenance import next_ticket_number

        emp_id = alloc.employee.id if alloc.employee else None
        emp_name = alloc.employee.name if alloc.employee else None
        t = Task(
            property_id=prop.id,
            ticket_number=await next_ticket_number(self.session, "task"),
            zone_id=zone_id,
            area_id=area_id,
            room_id=room.id if room else None,
            room_number=room.room_number if room else None,
            dorm_id=dorm.id if dorm else None,
            dorm_name=dorm.name if dorm else None,
            # bed links let supervisor approval release exactly the covered
            # beds — the ResourceStateService blocks a bed while its task is open
            bed_ids=[str(b.id) for b in beds] if beds else None,
            employee_id=emp_id,
            assigned_to_name=emp_name,
            title=title,
            task_type="fixed",
            work_type="cleaning",
            origin=origin,
            status="assigned" if emp_id else "pending",
            priority="medium",
            due_date=today,
            created_by_name=user.name,
            allocation_batch_id=alloc.batch.id if alloc else None,
            allocation_status="auto_assigned" if emp_id else "unassigned",
            allocation_method=alloc.method if alloc else None,
            allocation_reason=alloc.reason if alloc else None,
        )
        self.session.add(t)
        t._resolved_area_id = area_id
        # append while transient — avoids a lazy-load hit and keeps the
        # in-memory collection populated for task_out serialization
        t.history.append(TaskHistoryEvent(
            type="auto_generated", actor_name=user.name,
            note=f"Generated — {title} flagged from the zone board",
        ))
        try:
            async with self.session.begin_nested():  # SAVEPOINT — one dup
                await self.session.flush()           # can't kill the batch
        except IntegrityError:
            # uq_tasks_open_room_title — a concurrent request won the same
            # (property, room, title) slot; dedupe instead of duplicating
            return None
        allocs.log_task_allocation(
            alloc, task_id=t.id,
            room=room.room_number if room else None,
            dorm=dorm.name if dorm else None,
            zone=await self.session.scalar(select(Zone.name).where(Zone.id == zone_id)) if zone_id else None,
            area=await self.session.scalar(select(Area.name).where(Area.id == area_id)) if area_id else None,
        )
        await allocs.record(
            property_id=prop.id, zone_id=zone_id,
            batch=alloc.batch if alloc else None,
            ticket_kind="task", ticket_id=t.id,
            ticket_number=t.ticket_number,
            employee_id=emp_id, employee_name=emp_name,
            method=alloc.method if alloc else "manual",
            reason=alloc.reason if alloc else None,
            actor_name=user.name,
        )
        if emp_id:
            from app.services.notifications import NotificationService
            await NotificationService(self.session).notify(
                employee_id=emp_id, property_id=prop.id,
                type="task_assigned", title="New Task Assigned",
                body=t.title, task_id=t.id, employee_name=emp_name,
            )
        return t

    # ------------------------------------------------------------------
    # Dedicated allocation endpoints
    # ------------------------------------------------------------------

    async def allocate_unit(
        self, user: User, model, entity_id: uuid.UUID, area_uid, zone_uid
    ):
        entity, _ = await self._get(model, entity_id, user)
        zone = await self._zone_in_property(zone_uid, entity.property_id)
        area_id = await self._area_in_property(area_uid, entity.property_id)
        if zone is not None and area_uid is None:
            area_id = zone.area_id
        from_zone, from_area = entity.zone_id, entity.area_id
        entity.zone_id = zone.id if zone else None
        entity.area_id = area_id
        if from_zone != entity.zone_id or from_area != entity.area_id:
            self._record(
                user, model.__name__.lower(), entity.id, entity.property_id,
                from_zone=from_zone, to_zone=entity.zone_id,
                from_area=from_area, to_area=entity.area_id,
            )
        await self._commit()
        return entity

    async def _commit(self):
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictErr("A conflicting record already exists.") from exc
