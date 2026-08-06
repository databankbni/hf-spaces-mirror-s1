"""add subscriptions table

通用事件订阅：群/agent 可以订阅系统事件，事件触发时执行预定义动作。
- 持久化（DB 存储）
- 复杂 filter（递归字段匹配）
- 多种 action（trigger_as_message / task / notification）
- 模板消息渲染
- 一次性/持续订阅
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import JSON


# revision identifiers, used by Alembic.
revision = '2026_07_05_0001'
down_revision = '2026_06_20_0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), nullable=False, index=True),
        sa.Column('subscriber_type', sa.String(20), nullable=False),
        sa.Column('subscriber_id', sa.String(36), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('filter', JSON, nullable=True),
        sa.Column('action', sa.String(30), nullable=False, server_default='trigger_as_message'),
        sa.Column('message_template', sa.String(2000), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('one_shot', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('triggered_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_subscriptions_subscriber', 'subscriptions', ['subscriber_type', 'subscriber_id'])
    op.create_index('ix_subscriptions_project_event', 'subscriptions', ['project_id', 'event_type'])
    op.create_index('ix_subscriptions_enabled', 'subscriptions', ['enabled'])


def downgrade() -> None:
    op.drop_index('ix_subscriptions_enabled', table_name='subscriptions')
    op.drop_index('ix_subscriptions_project_event', table_name='subscriptions')
    op.drop_index('ix_subscriptions_subscriber', table_name='subscriptions')
    op.drop_table('subscriptions')
