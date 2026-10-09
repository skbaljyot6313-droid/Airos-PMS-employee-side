"""Mobile release contracts — public version check + release management."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class MobileVersionResponse(BaseModel):
    """Public payload for GET /mobile/version — release metadata only."""

    platform: str
    latest_version: str
    latest_version_code: int
    minimum_version: str
    minimum_version_code: int
    download_url: str
    release_notes: str | None = None
    force_update: bool


class MobileReleaseCreate(BaseModel):
    """Release-management input — gated by the release service key."""

    platform: str = Field("android", pattern=r"^[a-z]+$")
    version: str
    version_code: int = Field(ge=1)
    minimum_version: str
    minimum_version_code: int = Field(ge=1)
    download_url: str = Field(min_length=1, max_length=2048)
    release_notes: str | None = Field(default=None, max_length=4000)
    force_update: bool = False

    @field_validator("version", "minimum_version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not _VERSION_RE.fullmatch(v.strip()):
            raise ValueError("version must look like '1.2.3'")
        return v.strip()

    @field_validator("download_url")
    @classmethod
    def _https_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("download_url must be an https:// URL")
        return v


class MobileReleasePatch(BaseModel):
    """Mutable release fields — repoint a download URL or edit notes
    without a version bump. version/version_code stay immutable: a new
    build is a new release."""

    download_url: str | None = Field(default=None, min_length=1, max_length=2048)
    release_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("download_url")
    @classmethod
    def _https_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v.startswith("https://"):
            raise ValueError("download_url must be an https:// URL")
        return v


class MobileReleaseOut(BaseModel):
    id: uuid.UUID
    platform: str
    version: str
    version_code: int
    minimum_version: str
    minimum_version_code: int
    download_url: str
    release_notes: str | None
    force_update: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
