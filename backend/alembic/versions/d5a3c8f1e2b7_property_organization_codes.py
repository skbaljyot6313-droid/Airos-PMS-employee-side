"""organization codes move to properties

One company (organization) can run many properties, and an employee
joins a PROPERTY — not the company abstractly. The 12-char registration
code therefore moves from ``companies`` to ``properties``:

* ``properties.organization_code`` — unique, backfilled per property,
  NOT NULL. Verifying a code now resolves the exact property (and its
  company transitively); approval no longer has to guess where the
  employee belongs.
* ``companies.organization_code`` — dropped (superseded by the
  property-level code).

``employee_registration_requests`` is unchanged: it already carries
``company_id`` (tenant scope) and ``property_id`` (now populated at
submission rather than approval).

Shared schema: this revision must be mirrored verbatim in the employee
backend repo's chain — do NOT stamp over it.

Revision ID: d5a3c8f1e2b7
Revises: c9e7f2a4b8d1
"""
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd5a3c8f1e2b7'
down_revision: Union[str, Sequence[str], None] = 'c9e7f2a4b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 32-char alphabet: A-Z + 2-9 (no O/0/I/1 — visually ambiguous).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_code(used: set) -> str:
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
    while code in used:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(12))
    used.add(code)
    return code


def _backfill(table: str) -> None:
    bind = op.get_bind()
    used = set()
    ids = [
        row[0]
        for row in bind.execute(
            sa.text(
                f"SELECT id FROM {table} WHERE organization_code IS NULL"
            )
        )
    ]
    for row_id in ids:
        bind.execute(
            sa.text(
                f"UPDATE {table} SET organization_code = :code "
                f"WHERE id = :id"
            ),
            {"code": _new_code(used), "id": row_id},
        )


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("organization_code", sa.String(12), nullable=True),
    )
    _backfill("properties")
    op.alter_column("properties", "organization_code", nullable=False)
    op.create_unique_constraint(
        "uq_properties_organization_code",
        "properties",
        ["organization_code"],
    )

    op.drop_constraint(
        "uq_companies_organization_code", "companies", type_="unique"
    )
    op.drop_column("companies", "organization_code")


def downgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("organization_code", sa.String(12), nullable=True),
    )
    _backfill("companies")
    op.alter_column("companies", "organization_code", nullable=False)
    op.create_unique_constraint(
        "uq_companies_organization_code",
        "companies",
        ["organization_code"],
    )

    op.drop_constraint(
        "uq_properties_organization_code", "properties", type_="unique"
    )
    op.drop_column("properties", "organization_code")
