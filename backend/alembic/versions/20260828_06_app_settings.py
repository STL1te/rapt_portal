"""app_settings key/value table (holds the RAPT OAuth refresh token)

Revision ID: 20260828_06
Revises: 20260727_05
Create Date: 2026-08-28 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260828_06"
down_revision: str | Sequence[str] | None = "20260727_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
