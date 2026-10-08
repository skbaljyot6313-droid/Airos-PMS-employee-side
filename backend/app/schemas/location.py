"""Geo capture contract — optional body on attendance/task actions,
plus the live-location tracking payloads.

GeoCapture fields are all optional; range validation lives in
services/location.py (parse_geo) so service-level callers get the same
422s the routes emit. LocationUpdate is the tracker payload — the
service re-validates it as a belt-and-braces check.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GeoCapture(BaseModel):
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)
    accuracy_meters: float | None = Field(default=None)


class LocationUpdate(BaseModel):
    """One position fix for POST /location/current.

    Timestamps: `captured_at` (ISO-8601, UTC) is preferred; the legacy
    `timestamp` (device epoch seconds) is still accepted. Both are the
    DEVICE clock — stored for analysis, never trusted for ordering;
    `received_at` is always the server clock.

    `tracking_session_id` + `sequence_number` form the idempotency key —
    retried posts dedupe server-side. Identity still comes from the
    bearer token only; a client-supplied employee_id is ignored.
    """

    model_config = ConfigDict(extra="ignore")

    latitude: float = Field(ge=-90.0, le=90.0, allow_inf_nan=False)
    longitude: float = Field(ge=-180.0, le=180.0, allow_inf_nan=False)
    accuracy: float = Field(ge=0.0, allow_inf_nan=False)
    # `speed`/`speed_mps` and `heading`/`bearing_deg` are synonyms —
    # legacy app sends speed/heading; the native tracker sends the
    # canonical names.
    speed: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    speed_mps: float | None = Field(
        default=None, ge=0.0, allow_inf_nan=False
    )
    heading: float | None = Field(
        default=None, ge=0.0, le=360.0, allow_inf_nan=False
    )
    bearing_deg: float | None = Field(
        default=None, ge=0.0, le=360.0, allow_inf_nan=False
    )
    altitude_m: float | None = Field(default=None, allow_inf_nan=False)
    # Device epoch seconds; > 0 rejects epoch-0/garbage.
    timestamp: float | None = Field(
        default=None, gt=0.0, allow_inf_nan=False
    )
    captured_at: datetime | None = Field(default=None)
    tracking_session_id: uuid.UUID | None = Field(default=None)
    sequence_number: int | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _require_a_timestamp(self) -> "LocationUpdate":
        if self.captured_at is None and self.timestamp is None:
            raise ValueError("captured_at or timestamp is required")
        return self


class LocationStartResponse(BaseModel):
    tracking_session_id: uuid.UUID
    started_at: datetime
    tracking_interval_seconds: int


class LocationStopRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tracking_session_id: uuid.UUID


class LocationStopResponse(BaseModel):
    stopped: bool
    stopped_at: datetime


class LocationAck(BaseModel):
    """POST /location/current response — small ack; `recorded`,
    `server_timestamp` and `expires_in` are retained for the legacy app."""

    accepted: bool
    recorded: bool
    received_at: datetime
    location_timestamp: datetime
    server_timestamp: float
    expires_in: int
    duplicate: bool = False
    quality: str = "valid"
