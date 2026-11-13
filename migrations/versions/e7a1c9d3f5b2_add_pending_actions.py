"""pending actions for one-time tool authorization

用户确认一次有副作用工具调用的持久化载体：

- 模型运行中被权限层拦下的调用落成一行 `pending`；
- 用户确认后状态变 `approved`，同时写入只存 sha256 的一次性令牌和过期时间；
- 令牌在真正重放时用条件 UPDATE 从 `approved` 原子切到 `consumed`；
- 拒绝是 `rejected`。

`args_hash` 是参数 canonical JSON 的 sha256，令牌只对同一工具 + 同一组参数有效。

Revision ID: e7a1c9d3f5b2
Revises: c3d5e7f9a1b2
Create Date: 2026-11-14 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7a1c9d3f5b2"
down_revision: Union[str, None] = "c3d5e7f9a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=True),
        sa.Column("tool", sa.String(length=200), nullable=False),
        sa.Column("args_json", sa.Text(), nullable=False),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pending_actions_user_id", "pending_actions", ["user_id"])
    op.create_index("ix_pending_actions_args_hash", "pending_actions", ["args_hash"])
    op.create_index("ix_pending_actions_status", "pending_actions", ["status"])
    op.create_index("ix_pending_actions_token_hash", "pending_actions", ["token_hash"])
    op.create_index("ix_pending_actions_created_at", "pending_actions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_pending_actions_created_at", table_name="pending_actions")
    op.drop_index("ix_pending_actions_token_hash", table_name="pending_actions")
    op.drop_index("ix_pending_actions_status", table_name="pending_actions")
    op.drop_index("ix_pending_actions_args_hash", table_name="pending_actions")
    op.drop_index("ix_pending_actions_user_id", table_name="pending_actions")
    op.drop_table("pending_actions")
