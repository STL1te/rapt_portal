"""ai conversations

Revision ID: 20260723_04
Revises: 20260722_03
Create Date: 2026-07-23 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260723_04"
down_revision: str | Sequence[str] | None = "20260722_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_through_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "subject_type IN ('brew_session', 'fermentation_session', 'recipe')",
            name="ck_ai_conversation_subject_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_type", "subject_id", name="uq_ai_conversation_subject"),
    )
    op.create_index(
        op.f("ix_ai_conversations_subject_type"),
        "ai_conversations",
        ["subject_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_conversations_subject_id"),
        "ai_conversations",
        ["subject_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_conversations_updated_at"),
        "ai_conversations",
        ["updated_at"],
        unique=False,
    )

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_ai_message_role"),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_messages_conversation_id"),
        "ai_messages",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_messages_conversation_id"), table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index(op.f("ix_ai_conversations_updated_at"), table_name="ai_conversations")
    op.drop_index(op.f("ix_ai_conversations_subject_id"), table_name="ai_conversations")
    op.drop_index(op.f("ix_ai_conversations_subject_type"), table_name="ai_conversations")
    op.drop_table("ai_conversations")
