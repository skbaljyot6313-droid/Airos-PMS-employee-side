"""camera dual-stream + per-camera transcode opt-in

Adds `cameras.sub_rtsp_url` (optional secondary/substream RTSP URL for
low-bitrate grid viewing) and `cameras.transcode` (nullable tri-state —
NULL follows the VA_TRANSCODE_ENABLED global default, explicit true/false
overrides per camera).

Revision ID: e3b7c9f2a4d1
Revises: d8a4b2e9c1f7
"""
from alembic import op
import sqlalchemy as sa

revision = "e3b7c9f2a4d1"
down_revision = "d8a4b2e9c1f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("sub_rtsp_url", sa.String(), nullable=True))
    op.add_column("cameras", sa.Column("transcode", sa.Boolean(), nullable=True))
    # per-quality session tracking — "main" | "sub"
    op.add_column(
        "camera_stream_sessions",
        sa.Column("quality", sa.String(length=8), nullable=False, server_default="main"),
    )


def downgrade() -> None:
    op.drop_column("camera_stream_sessions", "quality")
    op.drop_column("cameras", "transcode")
    op.drop_column("cameras", "sub_rtsp_url")
