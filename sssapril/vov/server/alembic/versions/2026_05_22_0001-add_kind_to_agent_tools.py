"""add_kind_to_agent_tools

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-05-22 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a1b2'
down_revision: Union[str, None] = 'b2c3d4e5f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 添加 kind 列（nullable，允许旧数据兼容）
    op.add_column('agent_tools', sa.Column(
        'kind', sa.String(length=100), nullable=True,
        comment='工具处理器标识，对应 agentflow processor kind'
    ))

    # 从 config JSON 中提取 kind 值回填到新列（兼容 json 和 jsonb 类型）
    op.execute("""
        UPDATE agent_tools
        SET kind = config->>'kind'
        WHERE config->>'kind' IS NOT NULL
    """)

    # 如果没有 config.kind，用 name 作为 fallback
    op.execute("""
        UPDATE agent_tools
        SET kind = name
        WHERE kind IS NULL
    """)


def downgrade() -> None:
    op.drop_column('agent_tools', 'kind')
