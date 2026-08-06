"""v2 P3: 移除 agent.role 字段

设计反思: role 原本是"职业分类"枚举 (writer/critic/...), 但实际**没有代码依赖
它做逻辑**——只用作显示标签. 这是把"分类标签"硬编码为"枚举类型"的反模式.
- agent 的"职业身份"由 system_prompt + tools + skill_refs 表达
- "分类/标签"留给项目层通过 capabilities 描述
- 不再有数据库层硬编码的白名单

注意: 这里删的是 agents.role (agent 的职业枚举), 不是 group_members.role
(群成员在群里的角色 lead/participant/observer/admin)——后者是另一套概念, 保留.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026_06_19_0003'
down_revision = '2026_06_19_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 删 CHECK 约束
    op.drop_constraint('agents_role_check', 'agents', type_='check')

    # 2. 删 role 索引
    op.drop_index('ix_agents_role', table_name='agents')

    # 3. 删 role 列
    op.drop_column('agents', 'role')


def downgrade() -> None:
    # 回滚: 加回 role 列 + 索引 + CHECK 约束
    # 注意: 数据已丢失, role 列里全是 None. 旧逻辑默认 'custom' 的语义无法恢复
    # 这里用 server_default='custom' 让历史数据不破坏 CHECK 约束
    op.add_column(
        'agents',
        sa.Column('role', sa.String(length=50), nullable=False, server_default='custom',
                  comment='角色类型'),
    )
    op.create_index('ix_agents_role', 'agents', ['role'], unique=False)
    op.create_check_constraint(
        'agents_role_check',
        'agents',
        "role IN ('writer', 'critic', 'researcher', 'planner', 'editor', 'coder', 'designer', 'custom')",
    )
