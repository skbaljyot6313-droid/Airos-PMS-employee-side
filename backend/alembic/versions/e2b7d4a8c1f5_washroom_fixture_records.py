"""washroom fixture records — real per-fixture rows

Revises: d8e4b2f1a7c3
Create Date: 2026-09-29

Replaces aggregate fixture counters on `washrooms` with a real
`washroom_fixtures` table (one row per fixture — status, last_cleaned_at,
last_maintenance_at) and adds fixture-level targeting to tasks and
maintenance tickets. Aggregate counts are now derived from fixture rows.

"""
from alembic import op
import sqlalchemy as sa

revision = "e2b7d4a8c1f5"
down_revision = "d8e4b2f1a7c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "washroom_fixtures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("washroom_id", sa.Uuid(), nullable=False),
        sa.Column("fixture_type", sa.String(length=64), nullable=False),
        sa.Column("fixture_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_maintenance_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["washroom_id"], ["washrooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "washroom_id", "fixture_type", "fixture_number",
            name="uq_washroom_fixtures_type_number",
        ),
    )
    op.create_index("ix_washroom_fixtures_property_id", "washroom_fixtures", ["property_id"])
    op.create_index("ix_washroom_fixtures_washroom_id", "washroom_fixtures", ["washroom_id"])
    op.create_index("ix_washroom_fixtures_fixture_type", "washroom_fixtures", ["fixture_type"])

    op.add_column("tasks", sa.Column("washroom_fixture_id", sa.Uuid(), nullable=True))
    op.add_column("tasks", sa.Column("washroom_fixture_label", sa.String(length=64), nullable=True))
    op.create_index("ix_tasks_washroom_fixture_id", "tasks", ["washroom_fixture_id"])
    op.create_foreign_key(
        "fk_tasks_washroom_fixture_id", "tasks", "washroom_fixtures",
        ["washroom_fixture_id"], ["id"], ondelete="SET NULL",
    )

    op.add_column("maintenance_tickets", sa.Column("washroom_fixture_id", sa.Uuid(), nullable=True))
    op.add_column("maintenance_tickets", sa.Column("washroom_fixture_label", sa.String(length=64), nullable=True))
    op.create_index("ix_maintenance_tickets_washroom_fixture_id", "maintenance_tickets", ["washroom_fixture_id"])
    op.create_foreign_key(
        "fk_maintenance_tickets_washroom_fixture_id", "maintenance_tickets",
        "washroom_fixtures", ["washroom_fixture_id"], ["id"], ondelete="SET NULL",
    )

    # Aggregate counters replaced by derived values from washroom_fixtures.
    # No washroom rows exist at this point, so no backfill is needed.
    for col in (
        "sink_count", "mirror_count", "custom_fixtures",
        "stall_count", "urinal_count", "shower_count",
    ):
        op.drop_column("washrooms", col)


def downgrade() -> None:
    op.add_column("washrooms", sa.Column("custom_fixtures", sa.JSON(), nullable=True))
    for col in ("stall_count", "urinal_count", "shower_count", "sink_count", "mirror_count"):
        op.add_column("washrooms", sa.Column(col, sa.Integer(), nullable=False, server_default="0"))

    op.drop_constraint("fk_maintenance_tickets_washroom_fixture_id", "maintenance_tickets", type_="foreignkey")
    op.drop_index("ix_maintenance_tickets_washroom_fixture_id", table_name="maintenance_tickets")
    op.drop_column("maintenance_tickets", "washroom_fixture_label")
    op.drop_column("maintenance_tickets", "washroom_fixture_id")

    op.drop_constraint("fk_tasks_washroom_fixture_id", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_washroom_fixture_id", table_name="tasks")
    op.drop_column("tasks", "washroom_fixture_label")
    op.drop_column("tasks", "washroom_fixture_id")

    op.drop_index("ix_washroom_fixtures_fixture_type", table_name="washroom_fixtures")
    op.drop_index("ix_washroom_fixtures_washroom_id", table_name="washroom_fixtures")
    op.drop_index("ix_washroom_fixtures_property_id", table_name="washroom_fixtures")
    op.drop_table("washroom_fixtures")
