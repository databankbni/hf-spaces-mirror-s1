"""add chain rollover fields

Revision ID: a1b2c3d4e5f6
Revises: 25a080f739da
Create Date: 2026-05-16 00:01:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '25a080f739da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chains', sa.Column('rollover_from_chain_id', sa.String(length=36), nullable=True, comment='交接来源链ID'))
    op.add_column('chains', sa.Column('rollover_summary', sa.Text(), nullable=True, comment='交接时的总结内容'))


def downgrade() -> None:
    op.drop_column('chains', 'rollover_summary')
    op.drop_column('chains', 'rollover_from_chain_id')
