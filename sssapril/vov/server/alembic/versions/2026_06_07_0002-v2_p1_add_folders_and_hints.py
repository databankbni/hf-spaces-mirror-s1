"""v2_p1_add_folders_and_hints
v2 P1 数据模型迁移:
- Resource: 加 parent_id (自引用 FK, 树形文件夹) + is_folder
- Task: 加 verify_hint / max_revisions_hint / suggested_reviewer_id (全部 Optional hint)
- Project: 加 autonomy_hint / review_mode_hint / idle_threshold_seconds

按 v2 §0.5 原则: 所有 hint 字段都是 Optional, 不锁死流程, agent 自由决定用不用。

Revision ID: 2026_06_07_0002
Revises: a8b9c0d1e2f3
Create Date: 2026-06-07 14:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2026_06_07_0002'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Resource: 加 parent_id + is_folder 支持树形文件夹
    with op.batch_alter_table('resources') as batch_op:
        batch_op.add_column(sa.Column('parent_id', sa.String(length=36), nullable=True, comment='父资源ID（实现文件夹树形结构），NULL表示根级'))
        batch_op.add_column(sa.Column('is_folder', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='是否为文件夹'))
        batch_op.create_foreign_key('resources_parent_id_fkey', 'resources', ['parent_id'], ['id'], ondelete='CASCADE')
        batch_op.create_index('ix_resources_parent_id', ['parent_id'])
        batch_op.create_index('ix_resources_is_folder', ['is_folder'])

    # Task: 加 verify_hint / max_revisions_hint / suggested_reviewer_id (全部 Optional hint)
    with op.batch_alter_table('tasks') as batch_op:
        batch_op.add_column(sa.Column('verify_hint', sa.Text(), nullable=True, comment='验证方式 hint（自然语言描述）, agent 可忽略'))
        batch_op.add_column(sa.Column('max_revisions_hint', sa.Integer(), nullable=True, comment='建议重做次数 hint, agent 可自行决定'))
        batch_op.add_column(sa.Column('suggested_reviewer_id', sa.String(length=36), nullable=True, comment='建议的 reviewer agent id (hint), agent 可自行决定换人'))
        batch_op.create_foreign_key('tasks_suggested_reviewer_id_fkey', 'project_agents', ['suggested_reviewer_id'], ['id'])

    # Project: 加 autonomy_hint / review_mode_hint / idle_threshold_seconds
    with op.batch_alter_table('projects') as batch_op:
        batch_op.add_column(sa.Column('autonomy_hint', sa.Text(), nullable=True, comment='自动化级别 hint（自然语言描述）, agent 自己解读'))
        batch_op.add_column(sa.Column('review_mode_hint', sa.Text(), nullable=True, comment='review 模式 hint（自然语言描述）, agent 自由选择'))
        batch_op.add_column(sa.Column('idle_threshold_seconds', sa.Integer(), nullable=False, server_default=sa.text('60'), comment='agent 多久无活动视为卡住'))


def downgrade() -> None:
    # Project
    with op.batch_alter_table('projects') as batch_op:
        batch_op.drop_column('idle_threshold_seconds')
        batch_op.drop_column('review_mode_hint')
        batch_op.drop_column('autonomy_hint')

    # Task
    with op.batch_alter_table('tasks') as batch_op:
        batch_op.drop_constraint('tasks_suggested_reviewer_id_fkey', type_='foreignkey')
        batch_op.drop_column('suggested_reviewer_id')
        batch_op.drop_column('max_revisions_hint')
        batch_op.drop_column('verify_hint')

    # Resource
    with op.batch_alter_table('resources') as batch_op:
        batch_op.drop_index('ix_resources_is_folder')
        batch_op.drop_index('ix_resources_parent_id')
        batch_op.drop_constraint('resources_parent_id_fkey', type_='foreignkey')
        batch_op.drop_column('is_folder')
        batch_op.drop_column('parent_id')
