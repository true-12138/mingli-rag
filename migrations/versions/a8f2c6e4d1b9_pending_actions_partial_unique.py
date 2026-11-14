"""one pending action per user/tool/args

`create_pending_action` 原来是「先查后插」：两个并发请求可能都查不到已有行，
然后各插一条 `pending`。应用层的检查保留（同参数幂等的快路径），但把
「同一 user_id + tool + args_hash 最多一条 pending」交给数据库保证。

部分唯一索引只约束 `status = 'pending'` 的行：确认/拒绝/消费后状态离开
pending，不会阻塞以后对同一动作的新提议。SQLite 与 Postgres 都支持 partial
index，两边都显式给 where 子句。

升级前先清理历史上可能已经插入的重复 pending 行：每组只保留 id 最小的一条。
这条 DELETE 在 SQLite 和 Postgres 上都可执行。

Revision ID: a8f2c6e4d1b9
Revises: e7a1c9d3f5b2
Create Date: 2026-11-14 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a8f2c6e4d1b9"
down_revision: Union[str, None] = "e7a1c9d3f5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_pending_actions_pending_args"


def upgrade() -> None:
    # 先去掉历史重复行，否则唯一索引建不起来。
    # 外层只处理 pending 行；子查询按 (user_id, tool, args_hash) 取每组最小 id。
    op.execute(
        "DELETE FROM pending_actions "
        "WHERE status = 'pending' AND id NOT IN ("
        "SELECT MIN(id) FROM pending_actions "
        "WHERE status = 'pending' "
        "GROUP BY user_id, tool, args_hash)"
    )

    op.create_index(
        INDEX_NAME,
        "pending_actions",
        ["user_id", "tool", "args_hash"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="pending_actions")
