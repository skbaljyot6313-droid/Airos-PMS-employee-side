"""VA camera module — camera sections, cameras, stream sessions.

Adds the Video Analytics tables owned by the Super Admin backend:

- ``camera_sections`` — named camera groupings within a property.
- ``cameras`` — registered IP cameras (soft-deleted via ``deleted_at``;
  ``password`` is a Fernet token, never plaintext).
- ``camera_stream_sessions`` — per-viewer stream leases for audit +
  concurrency limits.

The Employee Backend shares this database and maps the tables read-only,
so this revision must be mirrored verbatim in the employee repo's chain —
do NOT stamp over it.

Revision ID: c7f3a8b1d9e4
Revises: b4e9f2a7c3d6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7f3a8b1d9e4"
down_revision: Union[str, Sequence[str], None] = "b4e9f2a7c3d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "camera_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("property_id", "name", name="uq_camera_sections_property_name"),
    )
    op.create_index("ix_camera_sections_property_id", "camera_sections", ["property_id"])

    op.create_table(
        "cameras",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("rtsp_url", sa.String(length=1024), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("password", sa.String(length=1024), nullable=True),
        sa.Column("transport", sa.String(length=8), server_default="tcp", nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.Column("fps", sa.Integer(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "connection_status",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["section_id"], ["camera_sections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cameras_property_id", "cameras", ["property_id"])
    op.create_index("ix_cameras_section_id", "cameras", ["section_id"])

    op.create_table(
        "camera_stream_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("camera_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("protocol", sa.String(length=16), nullable=False, server_default="webrtc"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_camera_stream_sessions_camera_id",
        "camera_stream_sessions",
        ["camera_id"],
    )
    op.create_index(
        "ix_camera_stream_sessions_user_id",
        "camera_stream_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_camera_stream_sessions_property_id",
        "camera_stream_sessions",
        ["property_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_camera_stream_sessions_property_id", table_name="camera_stream_sessions")
    op.drop_index("ix_camera_stream_sessions_user_id", table_name="camera_stream_sessions")
    op.drop_index("ix_camera_stream_sessions_camera_id", table_name="camera_stream_sessions")
    op.drop_table("camera_stream_sessions")
    op.drop_index("ix_cameras_section_id", table_name="cameras")
    op.drop_index("ix_cameras_property_id", table_name="cameras")
    op.drop_table("cameras")
    op.drop_index("ix_camera_sections_property_id", table_name="camera_sections")
    op.drop_table("camera_sections")
