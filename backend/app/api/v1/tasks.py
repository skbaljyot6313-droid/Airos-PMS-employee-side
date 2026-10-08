"""Employee-assigned task read and lifecycle endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.structure import Dorm, Room, Washroom, Zone
from app.models.user import User
from app.repositories.workspace import WorkspaceRepository
from app.schemas.location import GeoCapture
from app.schemas.v1.tasks.task import TaskSubmitRequest, task_out
from app.services.task import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(limit: int = Query(default=20, ge=1, le=500), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    res = await WorkspaceRepository(session).list_tasks(user, limit=limit)
    tasks = res["items"]
    zone_ids = {task.zone_id for task in tasks if task.zone_id}
    room_ids = {task.room_id for task in tasks if task.room_id}
    dorm_ids = {task.dorm_id for task in tasks if task.dorm_id}
    washroom_ids = {task.washroom_id for task in tasks if task.washroom_id}
    zones = {item.id: item for item in (await session.execute(select(Zone).where(Zone.id.in_(zone_ids)))).scalars()} if zone_ids else {}
    rooms = {item.id: item for item in (await session.execute(select(Room).where(Room.id.in_(room_ids)))).scalars()} if room_ids else {}
    dorms = {item.id: item for item in (await session.execute(select(Dorm).where(Dorm.id.in_(dorm_ids)))).scalars()} if dorm_ids else {}
    washrooms = {item.id: item for item in (await session.execute(select(Washroom).where(Washroom.id.in_(washroom_ids)))).scalars()} if washroom_ids else {}
    for task in tasks:
        zone = zones.get(task.zone_id)
        unit = rooms.get(task.room_id) or dorms.get(task.dorm_id) or washrooms.get(task.washroom_id)
        task._resolved_area_id = zone.area_id if zone and zone.area_id else (unit.area_id if unit else None)
    res["items"] = [task_out(task) for task in tasks]
    return res


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    return task_out(await TaskService(session).get_task(user, task_id))


@router.post("/{task_id}/start")
async def start_task(task_id: uuid.UUID, payload: GeoCapture | None = None, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    return task_out(await TaskService(session).start_task(user, task_id, geo=payload))


@router.post("/{task_id}/submit")
async def submit_task(task_id: uuid.UUID, payload: TaskSubmitRequest, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)):
    return task_out(await TaskService(session).submit_task(user, task_id, payload))
