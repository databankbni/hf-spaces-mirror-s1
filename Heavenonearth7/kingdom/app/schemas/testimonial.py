"""
Heaven on Earth CMS Backend - Testimonial Schemas

Pydantic schemas for testimonial management.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr


class TestimonialBase(BaseModel):
    """Base schema for testimonial data."""
    
    name: str = Field(min_length=2, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    location: Optional[str] = Field(default=None, max_length=255)
    title: Optional[str] = Field(default=None, max_length=255)
    content: str = Field(min_length=5, max_length=5000)
    category: str = Field(
        default="general",
        pattern="^(healing|salvation|provision|deliverance|general|Prayer|General)$"
    )
    source: str = Field(default="form", description="Submission source: 'form' or 'chatbot'")


class TestimonialCreate(TestimonialBase):
    """Schema for creating a testimonial (from website)."""
    
    pass


class TestimonialUpdate(BaseModel):
    """Schema for updating a testimonial (admin only)."""
    
    title: Optional[str] = Field(default=None, max_length=255)
    edited_content: Optional[str] = Field(default=None, max_length=5000)
    category: Optional[str] = Field(
        default=None,
        pattern="^(healing|salvation|provision|deliverance|general|Prayer|General)$"
    )
    is_featured: Optional[bool] = None
    display_order: Optional[int] = None


class TestimonialReview(BaseModel):
    """Schema for reviewing a testimonial."""
    
    status: str = Field(pattern="^(approved|rejected)$")
    review_notes: Optional[str] = Field(default=None, max_length=1000)
    edited_content: Optional[str] = Field(default=None, max_length=5000)
    is_featured: bool = False


class TestimonialResponse(TestimonialBase):
    """Schema for testimonial response (admin view)."""
    
    id: UUID
    photo_url: Optional[str] = None
    status: str
    reviewed_by_id: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    edited_content: Optional[str] = None
    published_at: Optional[datetime] = None
    is_featured: bool
    display_order: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class TestimonialList(BaseModel):
    """Schema for list of testimonials."""
    
    items: List[TestimonialResponse]
    total: int
    page: int
    page_size: int


class TestimonialPublic(BaseModel):
    """Public testimonial data for frontend."""
    
    id: UUID
    name: str
    location: Optional[str] = None
    title: Optional[str] = None
    content: str  # Will show edited_content if available
    photo_url: Optional[str] = None
    category: str
    published_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class TestimonialFilter(BaseModel):
    """Schema for filtering testimonials."""
    
    status: Optional[str] = None
    category: Optional[str] = None
    is_featured: Optional[bool] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search: Optional[str] = None


class TestimonialStatsResponse(BaseModel):
    """Statistics about testimonials."""
    
    total_count: int
    pending_count: int
    approved_count: int
    published_count: int
    rejected_count: int
    featured_count: int
