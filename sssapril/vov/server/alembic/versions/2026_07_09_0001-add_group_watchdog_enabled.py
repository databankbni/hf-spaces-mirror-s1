"""add group watchdog_enabled

群级空闲 Watchdog 开关: false 时, EventDispatcher 的 idle watchdog 跳过该群,
避免用户暂时不关心的群被反复激活 lead agent。

默认 true 保持现有行为, 群/项目/模板可按需关闭。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026_07_09_0001'
down_revision = '2026_07_05_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('groups') as batch_op:
        batch_op.add_column(
            sa.Column(
                'watchdog_enabled',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('1'),
                comment='true: 空闲 watchdog 监控该群; false: 跳过',
            )
        )


def downgrade() -> None:
    with op.batch_alter_table('groups') as batch_op:
        batch_op.drop_column('watchdog_enabled')
