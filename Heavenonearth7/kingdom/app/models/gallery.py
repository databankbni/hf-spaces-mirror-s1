"""
Heaven on Earth CMS Backend - Gallery Model

Database model for gallery items (images and videos).
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import Boolean, DateTime, String, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GalleryItem(Base):
    """
    Gallery item model for images and videos.
    
    Supports multiple categories and both images and embedded videos.
    """
    
    __tablename__ = "gallery_items"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Item details
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    title_am: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Amharic title",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    alt_text: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Alt text for accessibility",
    )
    
    # Media type
    media_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="image",
        index=True,
    )  # image, video
    
    # Media URLs
    src_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    thumbnail_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # For images: file metadata
    file_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    file_size: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="File size in bytes",
    )
    mime_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    width: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    height: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    
    # Categorization
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="general",
        index=True,
    )  # worship, outreach, youth, events, general
    
    # Event/date association
    event_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Date when the photo/video was taken",
    )
    
    # Flags
    is_featured: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    
    # Display order
    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    
    # Audit fields
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<GalleryItem(id={self.id}, title={self.title}, type={self.media_type})>"
