"""add_slug_to_memories_and_task_id_to_resources

Revision ID: a8b9c0d1e2f3
Revises: f2a3b4c5d6e7
Create Date: 2026-06-07 11:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Memory: 去掉 (agent_id, project_id) 唯一约束，加上 slug 字段，改为 (agent_id, project_id, slug)
    with op.batch_alter_table('memories') as batch_op:
        batch_op.drop_constraint('memories_unique', type_='unique')
        batch_op.add_column(sa.Column('slug', sa.String(length=64), nullable=False, server_default='default', comment='分类标识'))
        batch_op.create_index('ix_memories_slug', ['slug'])
        batch_op.create_unique_constraint('memories_unique', ['agent_id', 'project_id', 'slug'])

    # Resource: 加 task_id 字段（追溯到具体任务）
    with op.batch_alter_table('resources') as batch_op:
        batch_op.add_column(sa.Column('task_id', sa.String(length=36), nullable=True, comment='产出该资源的任务ID'))
        batch_op.create_foreign_key('resources_task_id_fkey', 'tasks', ['task_id'], ['id'], ondelete='SET NULL')
        batch_op.create_index('ix_resources_task_id', ['task_id'])


def downgrade() -> None:
    with op.batch_alter_table('resources') as batch_op:
        batch_op.drop_index('ix_resources_task_id')
        batch_op.drop_constraint('resources_task_id_fkey', type_='foreignkey')
        batch_op.drop_column('task_id')

    with op.batch_alter_table('memories') as batch_op:
        batch_op.drop_constraint('memories_unique', type_='unique')
        batch_op.drop_index('ix_memories_slug')
        batch_op.drop_column('slug')
        batch_op.create_unique_constraint('memories_unique', ['agent_id', 'project_id'])
