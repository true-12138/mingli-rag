"""add runs.citations_json

会话回放需要知道每条回答引用了哪些原文；消息表只存正文，
引用列表原先只在 Run 的响应里返回、没有落库，刷新页面后引用就丢了。

Revision ID: b1a7d3c05e21
Revises: 9b7c2f1a4d10
Create Date: 2026-11-08 09:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b1a7d3c05e21"
down_revision: Union[str, None] = "9b7c2f1a4d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        # JSON 数组文本：[12, 34]。用 Text 而不是 JSON 类型：SQLite / Postgres
        # 都能存，读的时候反序列化一次即可，和 args_json 的做法保持一致。
        batch_op.add_column(sa.Column("citations_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("citations_json")
