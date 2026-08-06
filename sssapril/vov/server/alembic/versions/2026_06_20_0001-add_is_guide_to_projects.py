"""add is_guide to projects

为 project 表加 is_guide 布尔字段，用于标记"引导 project"。

引导 project 是每用户一个的特殊 project，承载引导 agent（L0 需求 agent 等）。
它本质是普通 project（有 agent/group/chain/资源），只是：
- is_guide=True 标记用途
- 不展示在"我的项目"列表（前端查询时过滤 is_guide=True）
- 引导 agent 在其中工作，通过系统级工具跨 project 操作真实项目

这样设计的好处：最大化复用现有 project/group/chain 机制，引导 agent 有完整上下文
（提示词/工具/记忆都在 project 里配置），useChatStream/chain 表等完全不用改。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026_06_20_0001'
down_revision = '2026_06_19_0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'projects',
        sa.Column(
            'is_guide',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('0'),
            comment='是否为引导 project（引导 agent 工作容器，不在项目列表展示）',
        ),
    )
    op.create_index('ix_projects_is_guide', 'projects', ['is_guide'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_projects_is_guide', table_name='projects')
    op.drop_column('projects', 'is_guide')
