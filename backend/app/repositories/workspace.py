"""
Workspace list queries — all reads are scoped to the caller's company.

    current_user.company_id  →  authoritative tenant scope
    current_user.property_id →  property managers/employees see only
                                their own property's data

Never trust a client-supplied company id for authorization.
"""

import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.property import Property
from app.models.structure import Area, Dorm, Room, Washroom, Zone
from app.models.task import Task, TaskCompletionSubmission
from app.models.user import User, UserRole


def _company_scope(query, model, user: User, company_fk=None):
    """Restrict a query to rows inside the caller's company/property scope."""
    if user.role == UserRole.SUPER_ADMIN:
        if company_fk is not None:
            return query.where(company_fk == user.company_id)
        # Property-scoped entities: join through Property → company_id
        return query.join(Property, model.property_id == Property.id).where(
            Property.company_id == user.company_id
        )
    # property_manager / employee → locked to their assigned property
    return query.where(model.property_id == user.property_id)


def _paged(items, page: int, limit: int) -> dict[str, Any]:
    return {"items": items, "total": len(items), "page": page, "limit": limit}


class WorkspaceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_properties(
        self, user: User, *, search=None, status=None, page=1, limit=20
    ) -> dict:
        q = select(Property)
        if user.role == UserRole.SUPER_ADMIN:
            q = q.where(Property.company_id == user.company_id)
        else:
            q = q.where(Property.id == user.property_id)
        if search:
            like = f"%{search}%"
            q = q.where(
                or_(
                    Property.name.ilike(like),
                    Property.code.ilike(like),
                    Property.city.ilike(like),
                )
            )
        if status:
            q = q.where(Property.status == status)
        res = await self.session.execute(q.order_by(Property.created_at.desc()))
        return _paged(list(res.scalars()), page, limit)

    async def get_property(self, user: User, property_id: uuid.UUID) -> Property | None:
        q = select(Property).where(Property.id == property_id)
        if user.role == UserRole.SUPER_ADMIN:
            q = q.where(Property.company_id == user.company_id)
        else:
            q = q.where(Property.id == user.property_id)
        res = await self.session.execute(q)
        return res.scalar_one_or_none()

    async def list_areas(self, user: User, *, property_id=None, page=1, limit=20) -> dict:
        q = _company_scope(select(Area), Area, user)
        if property_id:
            q = q.where(Area.property_id == property_id)
        res = await self.session.execute(q.order_by(Area.level_number, Area.created_at))
        return _paged(list(res.scalars()), page, limit)

    async def list_zones(self, user: User, *, property_id=None, page=1, limit=20) -> dict:
        q = _company_scope(select(Zone), Zone, user)
        if property_id:
            q = q.where(Zone.property_id == property_id)
        res = await self.session.execute(q.order_by(Zone.created_at))
        return _paged(list(res.scalars()), page, limit)

    async def list_rooms(
        self, user: User, *, property_id=None, zone_id=None, status=None, search=None, page=1, limit=20
    ) -> dict:
        q = _company_scope(select(Room), Room, user)
        if property_id:
            q = q.where(Room.property_id == property_id)
        if zone_id:
            q = q.where(Room.zone_id == zone_id)
        if status:
            q = q.where(Room.status == status)
        if search:
            q = q.where(Room.room_number.ilike(f"%{search}%"))
        res = await self.session.execute(q.order_by(Room.room_number))
        return _paged(list(res.scalars()), page, limit)

    async def list_dorms(
        self, user: User, *, property_id=None, zone_id=None, page=1, limit=20
    ) -> dict:
        q = _company_scope(
            select(Dorm).options(selectinload(Dorm.beds)), Dorm, user
        )
        if property_id:
            q = q.where(Dorm.property_id == property_id)
        if zone_id:
            q = q.where(Dorm.zone_id == zone_id)
        res = await self.session.execute(q.order_by(Dorm.name))
        return _paged(list(res.unique().scalars()), page, limit)

    async def list_washrooms(
        self, user: User, *, property_id=None, zone_id=None, status=None,
        search=None, page=1, limit=20
    ) -> dict:
        q = _company_scope(
            select(Washroom).options(selectinload(Washroom.fixtures)),
            Washroom, user,
        )
        if property_id:
            q = q.where(Washroom.property_id == property_id)
        if zone_id:
            q = q.where(Washroom.zone_id == zone_id)
        if status:
            q = q.where(Washroom.status == status)
        if search:
            q = q.where(Washroom.name.ilike(f"%{search}%"))
        res = await self.session.execute(q.order_by(Washroom.name))
        return _paged(list(res.scalars()), page, limit)

    async def list_employees(
        self,
        user: User,
        *,
        property_id=None,
        zone_id=None,
        department=None,
        status=None,
        search=None,
        page=1,
        limit=20,
    ) -> dict:
        q = select(Employee)
        if user.role == UserRole.SUPER_ADMIN:
            q = q.where(Employee.company_id == user.company_id)
        else:
            q = q.where(Employee.property_id == user.property_id)
        if property_id:
            q = q.where(Employee.property_id == property_id)
        if zone_id:
            q = q.where(Employee.zone_id == zone_id)
        if department:
            q = q.where(Employee.department == department)
        if status:
            q = q.where(func.lower(Employee.status) == status.lower())
        if search:
            like = f"%{search}%"
            q = q.where(
                or_(
                    Employee.name.ilike(like),
                    Employee.email.ilike(like),
                    Employee.username.ilike(like),
                    Employee.job_title.ilike(like),
                )
            )
        res = await self.session.execute(q.order_by(Employee.created_at.desc()))
        return _paged(list(res.scalars()), page, limit)

    async def list_tasks(
        self,
        user: User,
        *,
        property_id=None,
        zone_id=None,
        employee_id=None,
        status=None,
        task_type=None,
        search=None,
        page=1,
        limit=20,
    ) -> dict:
        # List payloads don't need evidence/history — task_out emits empty
        # collections for unloaded relations, and the Task Detail Drawer
        # fetches the full record via GET /tasks/{id} on open. Skipping the
        # eager loads saves ~3 remote round-trips and most of the payload.
        q = _company_scope(select(Task), Task, user)
        if property_id:
            q = q.where(Task.property_id == property_id)
        if zone_id:
            q = q.where(Task.zone_id == zone_id)
        if employee_id:
            q = q.where(Task.employee_id == employee_id)
        if user.role == UserRole.EMPLOYEE and user.employee_id:
            # Employees only see their own tasks
            q = q.where(Task.employee_id == user.employee_id)
        if status:
            q = q.where(Task.status == status)
        if task_type:
            q = q.where(Task.task_type == task_type)
        if search:
            like = f"%{search}%"
            q = q.where(or_(Task.title.ilike(like), Task.description.ilike(like)))
        res = await self.session.execute(q.order_by(Task.created_at.desc()))
        return _paged(list(res.unique().scalars()), page, limit)
