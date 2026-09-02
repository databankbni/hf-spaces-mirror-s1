"""
Heaven on Earth CMS Backend - Prayer Request Schemas

Pydantic schemas for prayer request management.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr


class PrayerRequestBase(BaseModel):
    """Base schema for prayer request data."""
    
    name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    request: str = Field(min_length=10, max_length=5000)
    is_anonymous: bool = False
    source: str = Field(default="form", description="Submission source: 'form' or 'chatbot'")


class PrayerRequestCreate(PrayerRequestBase):
    """Schema for creating a prayer request (from website)."""
    
    pass


class PrayerRequestUpdate(BaseModel):
    """Schema for updating a prayer request (admin only)."""
    
    status: Optional[str] = Field(
        default=None,
        pattern="^(pending|praying|completed|archived)$"
    )
    admin_notes: Optional[str] = None
    is_public: Optional[bool] = None


class PrayerRequestRespond(BaseModel):
    """Schema for sending a response to a prayer request."""
    
    response_message: str = Field(min_length=1, max_length=2000)


class PrayerRequestResponse(PrayerRequestBase):
    """Schema for prayer request response (admin view)."""
    
    id: UUID
    status: str
    prayer_count: int
    admin_notes: Optional[str] = None
    response_message: Optional[str] = None
    responded_at: Optional[datetime] = None
    responded_by_id: Optional[UUID] = None
    is_public: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class PrayerRequestList(BaseModel):
    """Schema for list of prayer requests."""
    
    items: List[PrayerRequestResponse]
    total: int
    page: int
    page_size: int


class PrayerRequestPublic(BaseModel):
    """Public prayer request data for prayer wall."""
    
    id: UUID
    name: str  # Will show "Anonymous" if is_anonymous
    request: str
    prayer_count: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class PrayerRequestFilter(BaseModel):
    """Schema for filtering prayer requests."""
    
    status: Optional[str] = None
    is_anonymous: Optional[bool] = None
    is_public: Optional[bool] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search: Optional[str] = None


class PrayerStatsResponse(BaseModel):
    """Statistics about prayer requests."""
    
    total_requests: int
    pending_count: int
    praying_count: int
    completed_count: int
    total_prayers: int  # Sum of all prayer_count
    public_count: int
