"""Resource state as the single source of truth.

Creates the occupancy + resource_state_events tables, backfills open
occupancies for already-occupied rooms/beds, canonicalizes legacy status
values (needs_cleaning/out_of_service → operational/inactive, dorm
active → available + is_active), and adds CHECK constraints enforcing the
canonical status sets at the database level.

Revision ID: i6f1b2d4e8a0
Revises: h5e0a3c4d8f6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'i6f1b2d4e8a0'
down_revision: Union[str, Sequence[str], None] = 'h5e0a3c4d8f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # occupancies — the authoritative record behind `occupied`
    # ------------------------------------------------------------------
    op.create_table(
        "occupancies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("property_id", sa.Uuid(),
                  sa.ForeignKey("properties.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        # no FK on room_id/bed_id — the occupancy row is the permanent
        # stay record; deleting a resource must not rewrite history
        sa.Column("room_id", sa.Uuid(), nullable=True, index=True),
        sa.Column("bed_id", sa.Uuid(), nullable=True, index=True),
        sa.Column("guest_name", sa.String(255), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("checked_out_at", sa.DateTime(timezone=True),
                  nullable=True),
        sa.Column("checked_in_by", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("checked_out_by", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(room_id IS NOT NULL AND bed_id IS NULL)"
            " OR (room_id IS NULL AND bed_id IS NOT NULL)",
            name="ck_occupancies_one_target",
        ),
    )
    op.create_index(
        "uq_occupancies_open_room", "occupancies", ["room_id"], unique=True,
        postgresql_where=sa.text("checked_out_at IS NULL"),
        sqlite_where=sa.text("checked_out_at IS NULL"),
    )
    op.create_index(
        "uq_occupancies_open_bed", "occupancies", ["bed_id"], unique=True,
        postgresql_where=sa.text("checked_out_at IS NULL"),
        sqlite_where=sa.text("checked_out_at IS NULL"),
    )

    # ------------------------------------------------------------------
    # resource_state_events — immutable transition audit
    # ------------------------------------------------------------------
    op.create_table(
        "resource_state_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("resource_type", sa.String(32), nullable=False, index=True),
        sa.Column("resource_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("property_id", sa.Uuid(),
                  sa.ForeignKey("properties.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("previous_state", sa.String(32), nullable=True),
        sa.Column("new_state", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("actor_name", sa.String(255), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("occupancy_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # dorm lifecycle split — is_active flag; status becomes operational
    # ------------------------------------------------------------------
    op.add_column(
        "dorms",
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
    )

    # ------------------------------------------------------------------
    # canonical data remaps
    # ------------------------------------------------------------------
    conn = op.get_bind()

    # fixture: out_of_service → inactive; needs_cleaning → operational
    # (fixture cleanliness is task-driven, not a stored state)
    conn.execute(sa.text(
        "UPDATE washroom_fixtures SET status='inactive'"
        " WHERE status='out_of_service'"
    ))
    conn.execute(sa.text(
        "UPDATE washroom_fixtures SET status='operational'"
        " WHERE status='needs_cleaning'"
    ))
    # washroom: out_of_service → inactive
    conn.execute(sa.text(
        "UPDATE washrooms SET status='inactive' WHERE status='out_of_service'"
    ))
    # dorm: 'active' is lifecycle, not operational → available + is_active
    conn.execute(sa.text(
        "UPDATE dorms SET status='available' WHERE status='active'"
    ))
    conn.execute(sa.text(
        "UPDATE dorms SET is_active=false, status='available'"
        " WHERE status='inactive'"
    ))

    # catch-all: any other non-canonical value normalizes to available
    conn.execute(sa.text(
        "UPDATE rooms SET status='available' WHERE status NOT IN"
        " ('available','occupied','cleaning','maintenance')"
    ))
    conn.execute(sa.text(
        "UPDATE dorms SET status='available' WHERE status NOT IN"
        " ('available','occupied','cleaning','maintenance')"
    ))
    conn.execute(sa.text(
        "UPDATE beds SET status='available' WHERE status NOT IN"
        " ('available','occupied','cleaning','maintenance','inactive')"
    ))
    conn.execute(sa.text(
        "UPDATE washrooms SET status='available' WHERE status NOT IN"
        " ('available','cleaning','maintenance','inactive')"
    ))
    conn.execute(sa.text(
        "UPDATE washroom_fixtures SET status='operational' WHERE status NOT IN"
        " ('operational','maintenance','inactive')"
    ))

    # ------------------------------------------------------------------
    # occupancy backfill — every occupied room/bed needs an open occupancy
    # so the OCCUPIED invariant holds on existing data.
    # ------------------------------------------------------------------
    import uuid as _uuid

    def _as_uuid(v):
        # text() reads return str on some drivers, UUID on others
        return v if isinstance(v, _uuid.UUID) else _uuid.UUID(str(v))

    occupancies = sa.table(
        "occupancies",
        sa.column("id", sa.Uuid()),
        sa.column("property_id", sa.Uuid()),
        sa.column("room_id", sa.Uuid()),
        sa.column("bed_id", sa.Uuid()),
        sa.column("guest_name", sa.String),
        sa.column("checked_in_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = sa.func.now()
    for room_id, property_id, guest in conn.execute(sa.text(
        "SELECT id, property_id, current_guest FROM rooms"
        " WHERE status='occupied'"
    )):
        conn.execute(occupancies.insert().values(
            id=_uuid.uuid4(), property_id=_as_uuid(property_id),
            room_id=_as_uuid(room_id), bed_id=None,
            guest_name=(guest or "").strip() or "Guest",
            checked_in_at=now, created_at=now, updated_at=now,
        ))
    for bed_id, property_id, guest in conn.execute(sa.text(
        "SELECT b.id, d.property_id, b.guest_name"
        " FROM beds b JOIN dorms d ON d.id = b.dorm_id"
        " WHERE b.status='occupied'"
    )):
        conn.execute(occupancies.insert().values(
            id=_uuid.uuid4(), property_id=_as_uuid(property_id),
            room_id=None, bed_id=_as_uuid(bed_id),
            guest_name=(guest or "").strip() or "Guest",
            checked_in_at=now, created_at=now, updated_at=now,
        ))

    # ------------------------------------------------------------------
    # CHECK constraints — the database backstop for canonical states
    # ------------------------------------------------------------------
    checks = {
        "rooms": ("ck_rooms_status",
                  "status IN ('available','occupied','cleaning','maintenance')"),
        "dorms": ("ck_dorms_status",
                  "status IN ('available','occupied','cleaning','maintenance')"),
        "beds": ("ck_beds_status",
                 "status IN ('available','occupied','cleaning',"
                 "'maintenance','inactive')"),
        "washrooms": ("ck_washrooms_status",
                      "status IN ('available','cleaning','maintenance',"
                      "'inactive')"),
        "washroom_fixtures": ("ck_washroom_fixtures_status",
                              "status IN ('operational','maintenance',"
                              "'inactive')"),
    }
    # batch mode is a no-op on PostgreSQL; on SQLite it does the required
    # copy-and-move table rebuild for ALTER-constraint support
    for table, (name, condition) in checks.items():
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(name, sa.text(condition))


def downgrade() -> None:
    for table, name in (
        ("washroom_fixtures", "ck_washroom_fixtures_status"),
        ("washrooms", "ck_washrooms_status"),
        ("beds", "ck_beds_status"),
        ("dorms", "ck_dorms_status"),
        ("rooms", "ck_rooms_status"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
    with op.batch_alter_table("dorms") as batch:
        batch.drop_column("is_active")
    op.drop_table("resource_state_events")
    op.drop_index("uq_occupancies_open_bed", table_name="occupancies")
    op.drop_index("uq_occupancies_open_room", table_name="occupancies")
    op.drop_table("occupancies")
