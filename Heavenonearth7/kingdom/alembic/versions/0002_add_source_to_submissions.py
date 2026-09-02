"""add source column to testimonials, prayer_requests, partnerships

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "testimonials",
        sa.Column("source", sa.String(20), nullable=False, server_default="form"),
    )
    op.add_column(
        "prayer_requests",
        sa.Column("source", sa.String(20), nullable=False, server_default="form"),
    )
    op.add_column(
        "partnerships",
        sa.Column("source", sa.String(20), nullable=False, server_default="form"),
    )


def downgrade() -> None:
    op.drop_column("testimonials", "source")
    op.drop_column("prayer_requests", "source")
    op.drop_column("partnerships", "source")
