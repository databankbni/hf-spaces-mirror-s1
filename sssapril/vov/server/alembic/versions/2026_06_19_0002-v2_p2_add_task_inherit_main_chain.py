"""v2_p2_add_task_inherit_main_chain

v2 P2: Task.inherit_main_chain 字段 —— 任务级开关, 决定 task chain 是否继承主链截至分支点的历史
- 1 (默认, 兼容狼人杀): 玩家能看到法官之前的公告
- 0: task chain 完全隔离, 适合身份下发等高敏感场景

Revision ID: 2026_06_19_0002
Revises: 2026_06_19_0001
Create Date: 2026-06-19 13:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2026_06_19_0002'
down_revision: Union[str, None] = '2026_06_19_0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column(
            'inherit_main_chain',
            sa.Integer(),
            nullable=False,
            server_default='1',
            comment='任务链是否继承主链截至分支点的历史. 1=继承(默认), 0=完全隔离',
        ),
    )


def downgrade() -> None:
    op.drop_column('tasks', 'inherit_main_chain')
