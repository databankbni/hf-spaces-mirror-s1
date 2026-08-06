"""add_context_data_to_tasks

Revision ID: e1f2a3b4c5d6
Revises: 3b9a317d2689
Create Date: 2026-05-24 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = '3b9a317d2689'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('context_data', sa.JSON(), nullable=False, server_default='{}', comment='任务上下文数据'))


def downgrade() -> None:
    op.drop_column('tasks', 'context_data')
