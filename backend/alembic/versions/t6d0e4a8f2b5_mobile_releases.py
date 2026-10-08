"""Mobile release registry + seed of the 1.0.0 production APK.

mobile_releases tracks every published employee-app build; exactly one row
per platform is active and answers the public GET /api/v1/mobile/version
check. Rows are never deleted — rollback re-activates an older release.

Seeds the first real production artifact (EAS build
822219f1-9009-41ff-ab1d-3fd1e08408d0, signed APK) as active so the
already-shipped 1.0.0 app has a baseline to compare against.

Revision ID: t6d0e4a8f2b5
Revises: s5c9e3a7d1f4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "t6d0e4a8f2b5"
down_revision: Union[str, Sequence[str], None] = "s5c9e3a7d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FIRST_RELEASE_URL = (
    "https://expo.dev/artifacts/eas/"
    "32jToVc6RP2daX5w0WVez4b50Zp6cfUo_1DpyxO0-ho.apk"
)


def upgrade() -> None:
    op.create_table(
        "mobile_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("version_code", sa.Integer(), nullable=False),
        sa.Column("minimum_version", sa.String(length=32), nullable=False),
        sa.Column("minimum_version_code", sa.Integer(), nullable=False),
        sa.Column("download_url", sa.String(length=2048), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("force_update", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mobile_releases_platform", "mobile_releases", ["platform"])
    op.create_index("ix_mobile_releases_is_active", "mobile_releases", ["is_active"])

    op.execute(
        sa.text(
            "INSERT INTO mobile_releases (id, platform, version, version_code,"
            " minimum_version, minimum_version_code, download_url,"
            " release_notes, force_update, is_active)"
            " VALUES (gen_random_uuid(), 'android', '1.0.0', 1, '1.0.0', 1,"
            " :url, 'Initial production release.', false, true)"
        ).bindparams(url=FIRST_RELEASE_URL)
    )


def downgrade() -> None:
    op.drop_index("ix_mobile_releases_is_active", table_name="mobile_releases")
    op.drop_index("ix_mobile_releases_platform", table_name="mobile_releases")
    op.drop_table("mobile_releases")
