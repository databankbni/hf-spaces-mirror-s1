"""
Heaven on Earth CMS Backend - Ministry Schemas

Pydantic schemas for ministry management.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr


class MinistryBase(BaseModel):
    """Base schema for ministry data."""
    
    title: str = Field(min_length=1, max_length=255)
    title_am: Optional[str] = Field(default=None, max_length=255)
    description: str = Field(min_length=1)
    description_am: Optional[str] = None
    icon_name: str = Field(default="Heart", max_length=50)
    ministry_key: str = Field(
        min_length=1, 
        max_length=50,
        pattern="^[a-z_]+$",
        description="Unique key for frontend reference (lowercase with underscores)"
    )


class MinistryCreate(MinistryBase):
    """Schema for creating a ministry."""
    
    leader_name: Optional[str] = Field(default=None, max_length=255)
    leader_email: Optional[EmailStr] = None
    leader_phone: Optional[str] = Field(default=None, max_length=50)
    image_url: Optional[str] = Field(default=None, max_length=500)
    activities: Optional[Any] = Field(
        default=None,
        description="List of ministry activities"
    )
    schedule: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Meeting schedule (day, time, location)"
    )
    is_active: bool = True
    is_featured: bool = False
    display_order: int = 0


class MinistryUpdate(BaseModel):
    """Schema for updating a ministry."""
    
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    title_am: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, min_length=1)
    description_am: Optional[str] = None
    icon_name: Optional[str] = Field(default=None, max_length=50)
    leader_name: Optional[str] = Field(default=None, max_length=255)
    leader_email: Optional[EmailStr] = None
    leader_phone: Optional[str] = Field(default=None, max_length=50)
    image_url: Optional[str] = Field(default=None, max_length=500)
    activities: Optional[Any] = None
    schedule: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None
    display_order: Optional[int] = None


class MinistryResponse(MinistryBase):
    """Schema for ministry response."""
    
    id: UUID
    leader_name: Optional[str] = None
    leader_email: Optional[str] = None
    leader_phone: Optional[str] = None
    image_url: Optional[str] = None
    activities: Optional[Dict[str, Any]] = None
    schedule: Optional[Dict[str, Any]] = None
    is_active: bool
    is_featured: bool
    display_order: int
    created_by_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class MinistryList(BaseModel):
    """Schema for list of ministries."""
    
    items: List[MinistryResponse]
    total: int
    page: int
    page_size: int


class MinistryPublic(BaseModel):
    """Public ministry data for frontend."""
    
    id: UUID
    title: str
    title_am: Optional[str] = None
    description: str
    description_am: Optional[str] = None
    icon_name: str
    ministry_key: str
    image_url: Optional[str] = None
    activities: Optional[Dict[str, Any]] = None
    schedule: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True
