"""v2_p2_add_chain_status_paused_archived
v2 P2: Chain.status 枚举扩展 —— 增加 paused / archived
- paused: 主链被任务接管时挂起（任务接管主链核心机制）
- archived: task chain 折叠归档（任务 done 后折叠到主链）

按 v2 设计哲学：status 仍是数据模型，不锁死流程；agent 通过工具调 update_task_status 触发状态切换。

Revision ID: 2026_06_19_0001
Revises: 2026_06_07_0002
Create Date: 2026-06-19 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2026_06_19_0001'
down_revision: Union[str, None] = '2026_06_07_0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 删旧 CheckConstraint
    op.drop_constraint('chains_status_check', 'chains', type_='check')

    # 2) 加新 CheckConstraint（含 pending / paused / archived）
    op.create_check_constraint(
        'chains_status_check',
        'chains',
        "status IN ('pending', 'active', 'paused', 'completed', 'archived', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint('chains_status_check', 'chains', type_='check')
    op.create_check_constraint(
        'chains_status_check',
        'chains',
        "status IN ('active', 'completed', 'failed')",
    )
