"""batches tracker and their remaining-volume log

Revision ID: 20261109_07
Revises: 20260828_06
Create Date: 2026-11-09 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261109_07"
down_revision: str | Sequence[str] | None = "20260828_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("bottled_on", sa.Date(), nullable=False),
        sa.Column("volume_l", sa.Float(), nullable=False),
        sa.Column("carbonation_until", sa.Date(), nullable=False),
        sa.Column("conditioning_until", sa.Date(), nullable=False),
        sa.Column("finished_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_table(
        "batch_volumes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recorded_on", sa.Date(), nullable=False),
        sa.Column("volume_l", sa.Float(), nullable=False),
    )
    op.create_index("ix_batch_volumes_batch_id", "batch_volumes", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_batch_volumes_batch_id", table_name="batch_volumes")
    op.drop_table("batch_volumes")
    op.drop_table("batches")
