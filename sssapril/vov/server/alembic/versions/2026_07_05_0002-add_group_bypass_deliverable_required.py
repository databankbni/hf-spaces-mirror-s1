"""add group bypass_deliverable_required

群级开关：true 时, update_task_status(done) 不再强制要求存在 deliverable。
适用场景: 群 description 写了"必出 deliverable", 但实际工作流是写资源到
resources 表 (write_resource), agent 不知道要先调 create_deliverable。
默认 false 保留 P0 强约束, 由项目/模板按需开启。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026_07_05_0002'
down_revision = '2026_07_05_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('groups') as batch_op:
        batch_op.add_column(
            sa.Column(
                'bypass_deliverable_required',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('0'),
                comment='true: 跳过 update_task_status(done) 的 deliverable 存在性检查',
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('groups') as batch_op:
        batch_op.drop_column('bypass_deliverable_required')
