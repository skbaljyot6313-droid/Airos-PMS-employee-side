"""Canonical location resolution for generated tasks and tickets."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.structure import Area, Bed, Dorm, Room, Washroom, Zone


@dataclass
class TaskLocation:
    property_id: uuid.UUID
    area_id: uuid.UUID | None = None
    zone_id: uuid.UUID | None = None
    room_id: uuid.UUID | None = None
    dorm_id: uuid.UUID | None = None
    washroom_id: uuid.UUID | None = None
    room: Room | None = None
    dorm: Dorm | None = None
    washroom: Washroom | None = None
    zone: Zone | None = None
    area: Area | None = None

    @property
    def room_label(self) -> str | None:
        return self.room.room_number if self.room else None

    @property
    def dorm_label(self) -> str | None:
        return self.dorm.name if self.dorm else None

    @property
    def washroom_label(self) -> str | None:
        return self.washroom.name if self.washroom else None


async def resolve_task_location(
    session: AsyncSession,
    *,
    property_id: uuid.UUID,
    room_id: uuid.UUID | None = None,
    dorm_id: uuid.UUID | None = None,
    bed_id: uuid.UUID | None = None,
    washroom_id: uuid.UUID | None = None,
    zone_id: uuid.UUID | None = None,
    area_id: uuid.UUID | None = None,
) -> TaskLocation:
    room = await session.get(Room, room_id) if room_id else None
    dorm = await session.get(Dorm, dorm_id) if dorm_id else None
    washroom = await session.get(Washroom, washroom_id) if washroom_id else None
    if bed_id and dorm is None:
        bed = await session.get(Bed, bed_id)
        dorm = await session.get(Dorm, bed.dorm_id) if bed else None

    for unit in (room, dorm, washroom):
        if unit is not None and unit.property_id != property_id:
            raise ValueError("Task location belongs to a different property")

    resolved_zone_id = (
        room.zone_id if room is not None
        else dorm.zone_id if dorm is not None
        else washroom.zone_id if washroom is not None
        else zone_id
    )
    zone = await session.get(Zone, resolved_zone_id) if resolved_zone_id else None
    if zone is not None and zone.property_id != property_id:
        raise ValueError("Task zone belongs to a different property")

    unit_area_id = (
        room.area_id if room is not None
        else dorm.area_id if dorm is not None
        else washroom.area_id if washroom is not None
        else area_id
    )
    resolved_area_id = zone.area_id if zone and zone.area_id else unit_area_id
    area = await session.get(Area, resolved_area_id) if resolved_area_id else None
    if area is not None and area.property_id != property_id:
        raise ValueError("Task area belongs to a different property")

    return TaskLocation(
        property_id=property_id,
        area_id=resolved_area_id,
        zone_id=resolved_zone_id,
        room_id=room.id if room else room_id,
        dorm_id=dorm.id if dorm else dorm_id,
        washroom_id=washroom.id if washroom else washroom_id,
        room=room,
        dorm=dorm,
        washroom=washroom,
        zone=zone,
        area=area,
    )
