"""hierarchical cascade delete — areas/zones own their structural children

Revision ID: c5f7a9b1d3e2
Revises: f3a8c1d5e7b9
Create Date: 2026-09-29 08:00:00.000000

Ownership classification:
  areas  -> zones     : strong ownership      -> ON DELETE CASCADE
  zones  -> rooms     : strong ownership      -> ON DELETE CASCADE
  areas  -> rooms     : strong ownership      -> ON DELETE CASCADE
  zones  -> dorms     : strong ownership      -> ON DELETE CASCADE
  areas  -> dorms     : strong ownership      -> ON DELETE CASCADE
  zones  -> washrooms : strong ownership      -> ON DELETE CASCADE
  areas  -> washrooms : strong ownership      -> ON DELETE CASCADE

Already enforced elsewhere (no change needed):
  zones  -> zone_allocation_state   CASCADE
  areas  -> area_allocation_state   CASCADE
  dorms  -> beds                    CASCADE
  tasks  -> task_history_events /
            task_completion_submissions /
            task_completion_images   CASCADE

Deliberately left as SET NULL (reference / historical / audit rows):
  employees.zone_id / employees.area_id      — staff are shared entities
  tasks.*                                    — task records survive units
  maintenance_tickets.*                      — ticket history survives units
  work_allocation_batches.zone_id /
  work_allocation_history.batch_id           — allocation audit trail

Only the seven SET NULL ownership FKs are recreated here; all data and
other constraints are preserved.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c5f7a9b1d3e2"
down_revision: Union[str, Sequence[str], None] = "f3a8c1d5e7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (constraint_name, child_table, parent_table, column)
_OWNERSHIP_FKS = [
    ("zones_area_id_fkey", "zones", "areas", "area_id"),
    ("rooms_zone_id_fkey", "rooms", "zones", "zone_id"),
    ("fk_rooms_area_id", "rooms", "areas", "area_id"),
    ("dorms_zone_id_fkey", "dorms", "zones", "zone_id"),
    ("fk_dorms_area_id", "dorms", "areas", "area_id"),
    ("washrooms_zone_id_fkey", "washrooms", "zones", "zone_id"),
    ("washrooms_area_id_fkey", "washrooms", "areas", "area_id"),
]


def upgrade() -> None:
    # Fail fast if any pre-existing orphan would violate the new cascade
    # ownership FKs — report rather than silently delete.
    for name, table, parent, col in _OWNERSHIP_FKS:
        op.execute(f"""
            DO $$
            DECLARE missing bigint;
            BEGIN
                SELECT count(*) INTO missing FROM {table} t
                WHERE t.{col} IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.id = t.{col});
                IF missing > 0 THEN
                    RAISE EXCEPTION 'orphan rows in % (%): % rows reference missing %.id',
                        '{table}', '{col}', missing, '{parent}';
                END IF;
            END $$;
        """)
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name, table, parent, [col], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    for name, table, parent, col in _OWNERSHIP_FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name, table, parent, [col], ["id"], ondelete="SET NULL"
        )
