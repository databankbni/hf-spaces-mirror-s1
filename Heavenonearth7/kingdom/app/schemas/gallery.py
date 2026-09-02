"""
Heaven on Earth CMS Backend - Gallery Schemas

Pydantic schemas for gallery management.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Union, Annotated
from uuid import UUID

from fastapi import UploadFile, File
from pydantic import BaseModel, Field, HttpUrl, field_validator

class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"

class Category(str, Enum):
    WORSHIP = "worship"
    OUTREACH = "outreach"
    YOUTH = "youth"
    EVENTS = "events"
    GENERAL = "general"


class GalleryItemBase(BaseModel):
    """Base schema for gallery item data."""
    
    title: str = Field(min_length=1, max_length=255)
    title_am: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    alt_text: str = Field(min_length=1, max_length=255)
    media_type: MediaType = Field(default=MediaType.IMAGE)
    category: Category = Field(default=Category.GENERAL)
    event_date: Optional[datetime] = None
    is_featured: bool = False
    is_published: bool = True
    display_order: int = 0


class GalleryItemCreateBase(GalleryItemBase):
    """Base schema for creating a gallery item (for direct URL uploads)."""
    
    src_url: HttpUrl
    file_name: Optional[str] = Field(default=None, max_length=255)
    file_size: Optional[int] = Field(default=None, ge=0)
    mime_type: Optional[str] = Field(default=None, max_length=100)
    width: Optional[int] = Field(default=None, ge=0)
    height: Optional[int] = Field(default=None, ge=0)


class GalleryItemFileUpload(GalleryItemBase):
    """Schema for file upload gallery item creation."""
    
    file: UploadFile
    
    @field_validator('file')
    @classmethod
    def validate_file(cls, v: UploadFile) -> UploadFile:
        if not v.content_type:
            raise ValueError("File must have a content type")
        return v


class GalleryItemCreate(GalleryItemCreateBase):
    """Schema for creating a gallery item with direct URLs."""
    pass


class GalleryItemUpdate(BaseModel):
    """Schema for updating a gallery item."""
    
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    title_am: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    alt_text: Optional[str] = Field(default=None, min_length=1, max_length=255)
    category: Optional[str] = Field(
        default=None,
        pattern="^(worship|outreach|youth|events|general)$"
    )
    event_date: Optional[datetime] = None
    is_featured: Optional[bool] = None
    is_published: Optional[bool] = None
    display_order: Optional[int] = None


class GalleryItemResponse(GalleryItemBase):
    """Schema for gallery item response."""
    
    id: UUID
    src_url: str
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    created_by_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class GalleryItemList(BaseModel):
    """Schema for list of gallery items."""
    
    items: List[GalleryItemResponse]
    total: int
    page: int
    page_size: int


class GalleryItemPublic(BaseModel):
    """Public gallery item data for frontend."""
    
    id: UUID
    title: str
    title_am: Optional[str] = None
    description: Optional[str] = None
    alt_text: str
    media_type: MediaType
    src_url: str
    category: Category
    event_date: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class GalleryFilter(BaseModel):
    """Schema for filtering gallery items."""
    
    category: Optional[str] = None
    media_type: Optional[str] = None
    is_featured: Optional[bool] = None
    is_published: Optional[bool] = None
    search: Optional[str] = None
