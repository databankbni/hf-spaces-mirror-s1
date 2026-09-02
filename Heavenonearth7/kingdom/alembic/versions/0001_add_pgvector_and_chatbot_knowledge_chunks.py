"""Add pgvector extension and chatbot_knowledge_chunks table

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1.1 Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 1.2 Create chatbot_knowledge_chunks table
    op.execute(
        """
        CREATE TABLE chatbot_knowledge_chunks (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content      TEXT NOT NULL,
            embedding    vector(384),
            source_type  VARCHAR(50),
            source_url   TEXT,
            source_id    TEXT,
            language     VARCHAR(10),
            chunk_index  INTEGER,
            last_updated TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )

    # 1.3 IVFFlat index on the embedding column for cosine similarity search
    op.execute(
        """
        CREATE INDEX ON chatbot_knowledge_chunks
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """
    )

    # 1.4 B-tree index on source_type for fast deletion by content type during refresh
    op.execute(
        """
        CREATE INDEX ON chatbot_knowledge_chunks (source_type)
        """
    )

    # 1.5 Composite index on (source_type, source_id) for targeted deletion
    # of specific records during incremental refresh
    op.execute(
        """
        CREATE INDEX ON chatbot_knowledge_chunks (source_type, source_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chatbot_knowledge_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
