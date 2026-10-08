"""Location capture — geo fixes recorded at attendance/task actions.

Policy: RECORD, don't reject. A fix outside the property's configured
geofence is flagged 'outside_geofence'; a fix with absurd reported
accuracy (> LOW_ACCURACY_M) is flagged 'low_accuracy' — the row lands
either way so ops can review; the workday/task never blocks on geo.
Flag precedence: an unusable fix can't establish a geofence violation,
so 'low_accuracy' wins when both apply.

Client timestamps are never trusted — recorded_at is the DB server's
func.now() (model default); nothing here accepts a client clock.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import LOCATION_SOURCES, LocationEvent
from app.models.property import Property
from app.services.structure import ValidationErr

# Above this reported accuracy the fix is meaningless for geofencing.
LOW_ACCURACY_M = 10_000.0
FLAG_LOW_ACCURACY = "low_accuracy"
FLAG_OUTSIDE_GEOFENCE = "outside_geofence"

_EARTH_RADIUS_M = 6_371_000.0


class GeoLike(Protocol):
    latitude: float | None
    longitude: float | None
    accuracy_meters: float | None


@dataclass
class GeoFix:
    latitude: float
    longitude: float
    accuracy_meters: float | None = None


def parse_geo(geo: GeoLike | GeoFix | None) -> GeoFix | None:
    """Validate the optional geo body → GeoFix, or None when absent.

    latitude/longitude must come as a pair; ranges are enforced
    (lat ±90, lon ±180, accuracy > 0). Raises ValidationErr (422) —
    services call this BEFORE mutating state so a bad payload fails
    the request cleanly.
    """
    if geo is None:
        return None
    lat = geo.latitude
    lon = geo.longitude
    acc = geo.accuracy_meters
    if lat is None and lon is None:
        if acc is not None:
            raise ValidationErr(
                "accuracy_meters requires latitude/longitude.",
                field="latitude",
            )
        return None
    if lat is None or lon is None:
        raise ValidationErr(
            "latitude and longitude must be provided together.",
            field="latitude",
        )
    if not (-90.0 <= lat <= 90.0):
        raise ValidationErr(
            "latitude must be between -90 and 90.", field="latitude",
        )
    if not (-180.0 <= lon <= 180.0):
        raise ValidationErr(
            "longitude must be between -180 and 180.", field="longitude",
        )
    if acc is not None and acc <= 0:
        raise ValidationErr(
            "accuracy_meters must be positive.", field="accuracy_meters",
        )
    return GeoFix(latitude=float(lat), longitude=float(lon),
                  accuracy_meters=acc)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


class LocationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _flag(
        self, property_id: uuid.UUID, fix: GeoFix
    ) -> str | None:
        """Decide the capture flag — low_accuracy beats outside_geofence
        (an unusable fix can't establish the violation)."""
        if fix.accuracy_meters is not None \
                and fix.accuracy_meters > LOW_ACCURACY_M:
            return FLAG_LOW_ACCURACY
        prop = await self.session.get(Property, property_id)
        if (
            prop is not None
            and prop.latitude is not None
            and prop.longitude is not None
            and prop.geofence_radius_m
        ):
            dist = haversine_m(
                prop.latitude, prop.longitude,
                fix.latitude, fix.longitude,
            )
            if dist > prop.geofence_radius_m:
                return FLAG_OUTSIDE_GEOFENCE
        return None

    async def record(
        self,
        *,
        property_id: uuid.UUID,
        employee_id: uuid.UUID | None,
        fix: GeoFix,
        source: str,
        task_id: uuid.UUID | None = None,
        attendance_day_id: uuid.UUID | None = None,
    ) -> LocationEvent:
        """Append one capture — flush only; the caller commits so the
        event is atomic with the action that produced it."""
        if source not in LOCATION_SOURCES:
            raise ValidationErr("Invalid location source.", field="source")
        event = LocationEvent(
            property_id=property_id,
            employee_id=employee_id,
            task_id=task_id,
            attendance_day_id=attendance_day_id,
            latitude=fix.latitude,
            longitude=fix.longitude,
            accuracy_meters=fix.accuracy_meters,
            source=source,
            flagged=await self._flag(property_id, fix),
            # recorded_at → server_default func.now()
        )
        self.session.add(event)
        await self.session.flush()
        return event
