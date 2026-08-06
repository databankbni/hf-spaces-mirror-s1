"""add_map_to_resource_type

Revision ID: d4e5f6a2b3c4
Revises: c3d4e5f6a1b2
Create Date: 2026-05-23 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a2b3c4'
down_revision: Union[str, None] = 'c3d4e5f6a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE resources DROP CONSTRAINT resources_type_check")
    op.execute("ALTER TABLE resources ADD CONSTRAINT resources_type_check CHECK (type IN ('note', 'reference', 'guideline', 'rule', 'custom', 'map'))")


def downgrade() -> None:
    op.execute("ALTER TABLE resources DROP CONSTRAINT resources_type_check")
    op.execute("ALTER TABLE resources ADD CONSTRAINT resources_type_check CHECK (type IN ('note', 'reference', 'guideline', 'rule', 'custom'))")
