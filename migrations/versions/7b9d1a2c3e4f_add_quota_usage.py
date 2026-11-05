"""add quota_usage

Revision ID: 7b9d1a2c3e4f
Revises: 4cfcf24fc214
Create Date: 2026-11-05 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b9d1a2c3e4f'
down_revision: Union[str, None] = '4cfcf24fc214'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'quota_usage',
        sa.Column('bucket', sa.String(length=160), nullable=False),
        sa.Column('day', sa.String(length=10), nullable=False),
        sa.Column('used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.PrimaryKeyConstraint('bucket', 'day'),
    )


def downgrade() -> None:
    op.drop_table('quota_usage')
