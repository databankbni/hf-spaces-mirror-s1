"""
Heaven on Earth CMS Backend - Event Model

Database model for church events.
"""

from datetime import datetime, timezone, date, time
from typing import Optional
import uuid

from sqlalchemy import Boolean, Date, DateTime, String, Text, Time, Integer
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Event(Base):
    """
    Event model for church events and services.
    
    Includes support for recurring events, featured events,
    and event categorization.
    """
    
    __tablename__ = "events"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    
    # Event details
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
    
    # Date and time
    event_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    start_time: Mapped[time] = mapped_column(
        Time,
        nullable=False,
    )
    end_time: Mapped[Optional[time]] = mapped_column(
        Time,
        nullable=True,
    )
    
    # Location
    location: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    location_am: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    
    # Categorization
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="general",
        index=True,
    )  # worship, prayer, biblestudy, youth, special, general
    
    # Media
    image_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    
    # Flags
    is_featured: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    is_recurring: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    recurrence_pattern: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="daily, weekly, monthly, yearly",
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
        return f"<Event(id={self.id}, title={self.title}, date={self.event_date})>"
