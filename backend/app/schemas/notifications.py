"""Notification / device contracts + serializers.

Push tokens are credentials: they enter via DeviceRegisterRequest and
NEVER appear in any GET response — device_out emits identifiers and
metadata only.
"""

from pydantic import BaseModel, Field

from app.models.notifications import DeviceRegistration, Notification


class DeviceRegisterRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    push_token: str = Field(min_length=1, max_length=255)
    platform: str = Field(min_length=1, max_length=16)
    app_version: str | None = Field(default=None, max_length=32)


class DeviceUnregisterRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)


def notification_out(n: Notification) -> dict:
    return {
        "notification_uid": str(n.id),
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "task_uid": str(n.task_id) if n.task_id else None,
        "ticket_uid": str(n.ticket_id) if n.ticket_id else None,
        "is_read": n.is_read,
        "read_at": n.read_at,
        "created_at": n.created_at,
    }


def device_out(d: DeviceRegistration) -> dict:
    """No push_token — it's a credential, not display data."""
    return {
        "device_uid": str(d.id),
        "device_id": d.device_id,
        "platform": d.platform,
        "app_version": d.app_version,
        "is_active": d.is_active,
        "last_seen_at": d.last_seen_at,
    }
