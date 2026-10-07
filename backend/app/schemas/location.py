"""Geo capture contract — optional body on attendance/task actions,
plus the live-location update body for POST /location/current.

GeoCapture fields are all optional; range validation lives in
services/location.py (parse_geo) so service-level callers get the same
422s the routes emit. LocationUpdate is the foreground tracker payload —
the service re-validates it as a belt-and-braces check.
"""

from pydantic import BaseModel, ConfigDict, Field


class GeoCapture(BaseModel):
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    accuracy_meters: float | None = Field(default=None)


class LocationUpdate(BaseModel):
    """Live-position fix for POST /location/current.

    `timestamp` is the DEVICE clock (epoch seconds) — it is stored as
    `device_timestamp` for staleness display but never trusted for
    ordering; the server stamps `server_timestamp` on every write.
    Extra fields (e.g. a client-supplied employee_id) are ignored —
    identity comes from the bearer token only.
    """

    model_config = ConfigDict(extra="ignore")

    latitude: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)
    longitude: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    accuracy: float = Field(ge=0.0, allow_inf_nan=False)
    speed: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    heading: float | None = Field(
        default=None, ge=0.0, le=360.0, allow_inf_nan=False
    )
    # Device epoch seconds; > 0 rejects epoch-0/garbage while staying
    # tolerant of reasonable clock skew — no staleness rejection here.
    timestamp: float = Field(gt=0.0, allow_inf_nan=False)
