"""
Heaven on Earth CMS Backend - Chatbot Knowledge Chunk Model

Database model for the AI chatbot RAG knowledge base.
Stores text chunks and their vector embeddings produced by
sentence-transformers/all-MiniLM-L6-v2 (384 dimensions).
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.database import Base


class ChatbotKnowledgeChunk(Base):
    """
    Knowledge chunk model for the chatbot RAG pipeline.

    Each row stores a single text chunk (~500 tokens) along with
    its 384-dimensional embedding vector and metadata that identifies
    its origin (web crawl, DB events, DB ministries, etc.).

    The ``source_id`` column holds the string representation of the
    primary key of the originating record (e.g. an event UUID or
    ministry UUID) so that only the affected chunks are replaced
    during incremental refresh — not the entire content type.
    """

    __tablename__ = "chatbot_knowledge_chunks"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Text content of the chunk (~500 tokens)
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # 384-dimensional embedding vector (all-MiniLM-L6-v2)
    embedding: Mapped[Optional[list]] = mapped_column(
        Vector(384),
        nullable=True,
    )

    # Content origin: 'web_crawl' | 'db_events' | 'db_ministries'
    source_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )

    # URL for web-crawled content; NULL for DB-sourced content
    source_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Record identifier for DB-sourced content (e.g. event UUID or ministry UUID)
    # Used during incremental refresh to delete/replace only changed records
    source_id: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Language of the content: 'en' | 'am' | 'both'
    language: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
    )

    # Position of this chunk within the source document (0-based)
    chunk_index: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    # Timestamp of last embedding / insert
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<ChatbotKnowledgeChunk("
            f"id={self.id}, "
            f"source_type={self.source_type}, "
            f"source_id={self.source_id}, "
            f"chunk_index={self.chunk_index}"
            f")>"
        )
