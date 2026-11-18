"""runs: 记录路由档位与模型

把「这一轮是小模型还是大模型答的」落到 runs 表，刷新会话后仍然可查：
- tier: small / large（最终实际产出答案的档位）
- model: 最终模型名（供应商别名可能随时间变化，存原值，不做归一化）
- escalated: 小模型输出不可用后是否升级到大模型
- route_reason: 路由原因，含命中的难度信号 / 升级原因，便于回看为什么多花了钱

Revision ID: d4e8f1a6c2b7
Revises: f7a3d9c2e0b4
Create Date: 2026-11-18 23:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e8f1a6c2b7"
down_revision: Union[str, None] = "f7a3d9c2e0b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("tier", sa.String(length=10), nullable=True))
    op.add_column("runs", sa.Column("model", sa.String(length=80), nullable=True))
    op.add_column(
        "runs",
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("runs", sa.Column("route_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "route_reason")
    op.drop_column("runs", "escalated")
    op.drop_column("runs", "model")
    op.drop_column("runs", "tier")
