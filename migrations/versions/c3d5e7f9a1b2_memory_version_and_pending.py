"""memory optimistic version and pending confirmation

两个新边界：

- `version`：每次写入 +1，UPDATE 带 WHERE version = 读到的版本，防止并发
  写入互相覆盖（原来的读-改-写会丢更新）。
- `pending_value` / `pending_confidence`：覆盖已有值时不直接生效，先停在这里
  等用户确认；`value` 始终是生效值，所以 prompt 只用到确认过的记忆。

Revision ID: c3d5e7f9a1b2
Revises: b1a7d3c05e21
Create Date: 2026-11-13 10:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c3d5e7f9a1b2"
down_revision: Union[str, None] = "b1a7d3c05e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_memories", schema=None) as batch_op:
        # 老数据默认版本 1；server_default 让已有行在 ALTER 时直接补齐。
        batch_op.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("pending_value", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("pending_confidence", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("user_memories", schema=None) as batch_op:
        batch_op.drop_column("pending_confidence")
        batch_op.drop_column("pending_value")
        batch_op.drop_column("version")
