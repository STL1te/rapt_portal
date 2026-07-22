"""profiles table

Revision ID: 20260722_02
Revises: 20260722_01
Create Date: 2026-07-22 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260722_02"
down_revision: str | Sequence[str] | None = "20260722_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("public", sa.Boolean(), nullable=False),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("profile_type_id", sa.String(), nullable=True),
        sa.Column("profile_type_name", sa.String(), nullable=True),
        sa.Column("steps_json", sa.Text(), nullable=True),
        sa.Column("alerts_json", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_profiles_name"), "profiles", ["name"])
    op.create_index(op.f("ix_profiles_profile_type_id"), "profiles", ["profile_type_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_profiles_profile_type_id"), table_name="profiles")
    op.drop_index(op.f("ix_profiles_name"), table_name="profiles")
    op.drop_table("profiles")
