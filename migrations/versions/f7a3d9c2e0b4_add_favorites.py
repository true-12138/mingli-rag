"""favorites: 素材收藏（chunk_id + 笔记）

只存 `chunk_id` 和用户笔记，原文每次回语料取，不复制正文：
- 原文只有一份，导出和引用永远一致；
- 语料重编号后旧收藏会指空，接口返回 410，而不是显示错书。

同一用户同一段只留一条：`(user_id, chunk_id)` 唯一，重复收藏走 UPDATE 笔记。

Revision ID: f7a3d9c2e0b4
Revises: a8f2c6e4d1b9
Create Date: 2026-11-18 20:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f7a3d9c2e0b4"
down_revision: Union[str, None] = "a8f2c6e4d1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "chunk_id", name="uq_favorites_user_chunk"),
    )
    op.create_index("ix_favorites_user_id", "favorites", ["user_id"])
    op.create_index(
        "idx_favorites_user_created", "favorites", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_favorites_user_created", table_name="favorites")
    op.drop_index("ix_favorites_user_id", table_name="favorites")
    op.drop_table("favorites")
