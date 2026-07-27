"""rename ai conversation subject_type 'recipe' to 'profile'

Revision ID: 20260727_05
Revises: 20260723_04
Create Date: 2026-07-27 12:00:00
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260727_05"
down_revision: str | Sequence[str] | None = "20260723_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_ai_conversation_subject_type"


def upgrade() -> None:
    op.drop_constraint(_CHECK, "ai_conversations", type_="check")
    op.execute("UPDATE ai_conversations SET subject_type = 'profile' WHERE subject_type = 'recipe'")
    op.create_check_constraint(
        _CHECK,
        "ai_conversations",
        "subject_type IN ('brew_session', 'fermentation_session', 'profile')",
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK, "ai_conversations", type_="check")
    op.execute("UPDATE ai_conversations SET subject_type = 'recipe' WHERE subject_type = 'profile'")
    op.create_check_constraint(
        _CHECK,
        "ai_conversations",
        "subject_type IN ('brew_session', 'fermentation_session', 'recipe')",
    )
