"""
Heaven on Earth CMS Backend - Prayer Request Model

Database model for prayer requests submitted by website visitors.
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import Boolean, DateTime, String, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PrayerRequest(Base):
    """
    Prayer request model for submissions from the website.
    
    Supports anonymous submissions and admin responses.
    """
    
    __tablename__ = "prayer_requests"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Submitter information
    name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    
    # Request content
    request: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    
    # Flags
    is_anonymous: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    
    # Status tracking
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )  # pending, praying, completed, archived
    
    # Prayer count (from website "I prayed" button)
    prayer_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    
    # Admin response/notes (internal only)
    admin_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Internal notes from admin",
    )
    
    # Response sent to submitter
    response_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    responded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    responded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    # Submission source
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="form",
        server_default="form",
    )  # form, chatbot

    # Feature on prayer wall
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Show on public prayer wall (with consent)",
    )
    
    # IP tracking for rate limiting (hashed for privacy)
    ip_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    
    # Audit fields
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        name_display = "Anonymous" if self.is_anonymous else self.name
        return f"<PrayerRequest(id={self.id}, name={name_display}, status={self.status})>"
