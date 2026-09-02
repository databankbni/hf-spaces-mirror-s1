"""
Heaven on Earth CMS Backend - Ministry Model

Database model for church ministries.
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import Boolean, DateTime, String, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Ministry(Base):
    """
    Ministry model for church ministries and departments.
    
    Each ministry can have its own leader, description,
    schedule, and activities.
    """
    
    __tablename__ = "ministries"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Ministry details
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
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    description_am: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Amharic description",
    )
    
    # Icon (Lucide icon name)
    icon_name: Mapped[str] = mapped_column(
        String(50),
        default="Heart",
        nullable=False,
    )
    
    # Ministry key for frontend reference
    ministry_key: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )  # prayer, outreach, discipleship, youth, children, worship, women, missions
    
    # Leader information
    leader_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    leader_email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    leader_phone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    # Media
    image_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Activities/Details stored as JSON
    activities: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="List of ministry activities and programs",
    )
    
    # Meeting schedule stored as JSON
    schedule: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Meeting days and times",
    )
    
    # Flags
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    is_featured: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
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
        return f"<Ministry(id={self.id}, title={self.title}, key={self.ministry_key})>"
