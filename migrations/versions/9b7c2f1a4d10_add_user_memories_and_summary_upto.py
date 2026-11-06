"""add user_memories and conversations.summary_upto_id

Revision ID: 9b7c2f1a4d10
Revises: 4cfcf24fc214
Create Date: 2026-11-06 20:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9b7c2f1a4d10"
down_revision: Union[str, None] = "4cfcf24fc214"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source_conversation_id", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind in ('preference', 'fact')", name="ck_user_memory_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "kind", "key", name="uq_user_memory_key"),
    )
    op.create_index("ix_user_memories_user_id", "user_memories", ["user_id"])

    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("summary_upto_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.drop_column("summary_upto_id")

    op.drop_index("ix_user_memories_user_id", table_name="user_memories")
    op.drop_table("user_memories")
