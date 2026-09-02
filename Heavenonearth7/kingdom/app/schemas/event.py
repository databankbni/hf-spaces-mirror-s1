"""
Heaven on Earth CMS Backend - Event Schemas

Pydantic schemas for event management.
"""

from datetime import datetime, date, time
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field


class EventBase(BaseModel):
    """Base schema for event data."""
    
    title: str = Field(min_length=1, max_length=255)
    title_am: Optional[str] = Field(default=None, max_length=255)
    description: str = Field(min_length=1)
    description_am: Optional[str] = None
    event_date: date
    start_time: time
    end_time: Optional[time] = None
    location: str = Field(min_length=1, max_length=255)
    location_am: Optional[str] = Field(default=None, max_length=255)
    category: str = Field(
        default="general",
        pattern="^(worship|prayer|biblestudy|youth|special|general)$"
    )
    is_featured: bool = False
    is_recurring: bool = False
    recurrence_pattern: Optional[str] = Field(
        default=None,
        pattern="^(daily|weekly|monthly|yearly)$"
    )


class EventCreate(EventBase):
    """Schema for creating an event."""
    
    is_published: bool = True
    display_order: int = 0
    image_url: Optional[str] = Field(default=None, max_length=500)


class EventUpdate(BaseModel):
    """Schema for updating an event."""
    
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    title_am: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, min_length=1)
    description_am: Optional[str] = None
    event_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location: Optional[str] = Field(default=None, min_length=1, max_length=255)
    location_am: Optional[str] = Field(default=None, max_length=255)
    category: Optional[str] = Field(
        default=None,
        pattern="^(worship|prayer|biblestudy|youth|special|general)$"
    )
    is_featured: Optional[bool] = None
    is_recurring: Optional[bool] = None
    recurrence_pattern: Optional[str] = Field(
        default=None,
        pattern="^(daily|weekly|monthly|yearly)$"
    )
    is_published: Optional[bool] = None
    display_order: Optional[int] = None
    image_url: Optional[str] = Field(default=None, max_length=500)


class EventResponse(EventBase):
    """Schema for event response."""
    
    id: UUID
    image_url: Optional[str] = None
    is_published: bool
    display_order: int
    created_by_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class EventPublic(EventBase):
    """Public-facing schema for event data."""
    
    id: UUID
    image_url: Optional[str] = None
    
    class Config:
        from_attributes = True


class EventList(BaseModel):
    """Schema for list of events."""
    
    items: List[EventResponse]
    total: int
    page: int
    page_size: int


class EventFilter(BaseModel):
    """Schema for filtering events."""
    
    category: Optional[str] = None
    is_featured: Optional[bool] = None
    is_published: Optional[bool] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    search: Optional[str] = None
