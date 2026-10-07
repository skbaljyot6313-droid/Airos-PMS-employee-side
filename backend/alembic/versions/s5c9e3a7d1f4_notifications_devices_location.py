"""Notifications, device registrations, location events + property geofence.

Three new tables for the employee-app notification stack:

  * notifications — the in-app feed; task_id/ticket_id are PLAIN uuids
    (no FK) so deleting a task never destroys notification history.
  * device_registrations — push tokens keyed by (employee, device);
    user_id scopes logout teardown.
  * location_events — append-only, server-stamped geo captures;
    `flagged` is app-set only.

properties gains latitude/longitude/geofence_radius_m — all NULLable,
so the geofence feature is OFF until configured per property.

Revision ID: s5c9e3a7d1f4
Revises: r4b8d2f6a0c3e
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s5c9e3a7d1f4"
down_revision: Union[str, Sequence[str], None] = "r4b8d2f6a0c3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("employee_name", sa.String(255), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column(
            "is_read", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "type IN ("
            "'task_assigned', 'task_reassigned', 'task_cancelled', "
            "'task_due_soon', 'task_overdue', 'submission_approved', "
            "'submission_disapproved', 'ticket_assigned', "
            "'ticket_disapproved')",
            name="ck_notifications_type",
        ),
    )
    op.create_index(
        "ix_notifications_property_id", "notifications", ["property_id"],
    )
    op.create_index("ix_notifications_type", "notifications", ["type"])
    op.create_index(
        "ix_notif_employee_read", "notifications",
        ["employee_id", "is_read"],
    )
    op.create_index(
        "ix_notif_employee_created", "notifications",
        ["employee_id", "created_at"],
    )
    op.create_index(
        "ix_notif_property_created", "notifications",
        ["property_id", "created_at"],
    )

    op.create_table(
        "device_registrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.String(128), nullable=False),
        sa.Column("push_token", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("app_version", sa.String(32), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id", "device_id", name="uq_device_employee_device",
        ),
        sa.CheckConstraint(
            "platform IN ('android', 'ios', 'web')",
            name="ck_device_platform",
        ),
    )
    op.create_index(
        "ix_device_employee_active", "device_registrations",
        ["employee_id", "is_active"],
    )

    op.create_table(
        "location_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("attendance_day_id", sa.Uuid(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("accuracy_meters", sa.Float(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("flagged", sa.String(64), nullable=True),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["property_id"], ["properties.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"], ["employees.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "source IN ('attendance_start', 'attendance_end', "
            "'task_start', 'task_submit')",
            name="ck_location_events_source",
        ),
    )
    op.create_index(
        "ix_location_events_property_id", "location_events",
        ["property_id"],
    )
    op.create_index(
        "ix_location_employee_time", "location_events",
        ["employee_id", "recorded_at"],
    )
    op.create_index(
        "ix_location_property_time", "location_events",
        ["property_id", "recorded_at"],
    )

    # Geofence anchor — NULL = feature off until configured.
    op.add_column("properties", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("properties", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column(
        "properties", sa.Column("geofence_radius_m", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("properties", "geofence_radius_m")
    op.drop_column("properties", "longitude")
    op.drop_column("properties", "latitude")
    op.drop_index("ix_location_property_time", table_name="location_events")
    op.drop_index("ix_location_employee_time", table_name="location_events")
    op.drop_index("ix_location_events_property_id", table_name="location_events")
    op.drop_table("location_events")
    op.drop_index("ix_device_employee_active", table_name="device_registrations")
    op.drop_table("device_registrations")
    op.drop_index("ix_notif_property_created", table_name="notifications")
    op.drop_index("ix_notif_employee_created", table_name="notifications")
    op.drop_index("ix_notif_employee_read", table_name="notifications")
    op.drop_index("ix_notifications_type", table_name="notifications")
    op.drop_index("ix_notifications_property_id", table_name="notifications")
    op.drop_table("notifications")
