"""
Heaven on Earth CMS Backend - Partnership Schemas

Pydantic schemas for partnership management.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr


class PartnershipBase(BaseModel):
    """Base schema for partnership data."""
    
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=50)
    partnership_type: str = Field(
        pattern="^(financial|volunteer|material)$"
    )
    message: Optional[str] = Field(default=None, max_length=2000)
    source: str = Field(default="form", description="Submission source: 'form' or 'chatbot'")


class PartnershipCreate(PartnershipBase):
    """Schema for creating a partnership application (from website)."""
    
    volunteer_areas: Optional[List[str]] = Field(
        default=None,
        description="Selected volunteer areas"
    )
    financial_commitment: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Financial commitment details"
    )
    material_items: Optional[List[str]] = Field(
        default=None,
        description="List of material items offered"
    )


class PartnershipUpdate(BaseModel):
    """Schema for updating a partnership application (admin only)."""
    
    status: Optional[str] = Field(
        default=None,
        pattern="^(pending|contacted|active|inactive|declined)$"
    )
    admin_notes: Optional[str] = Field(default=None, max_length=2000)
    follow_up_date: Optional[datetime] = None
    assigned_to_id: Optional[UUID] = None


class PartnershipContactLog(BaseModel):
    """Schema for logging contact with a partner."""
    
    notes: str = Field(min_length=1, max_length=1000)
    next_follow_up: Optional[datetime] = None


class PartnershipResponse(PartnershipBase):
    """Schema for partnership response (admin view)."""
    
    id: UUID
    volunteer_areas: Optional[List[str]] = None
    financial_commitment: Optional[Dict[str, Any]] = None
    material_items: Optional[List[str]] = None
    status: str
    assigned_to_id: Optional[UUID] = None
    admin_notes: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    contact_count: int
    follow_up_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class PartnershipList(BaseModel):
    """Schema for list of partnerships."""
    
    items: List[PartnershipResponse]
    total: int
    page: int
    page_size: int


class PartnershipFilter(BaseModel):
    """Schema for filtering partnerships."""
    
    partnership_type: Optional[str] = None
    status: Optional[str] = None
    assigned_to_id: Optional[UUID] = None
    has_follow_up: Optional[bool] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search: Optional[str] = None


class PartnershipStatsResponse(BaseModel):
    """Statistics about partnerships."""
    
    total_count: int
    pending_count: int
    active_count: int
    by_type: Dict[str, int]
    needs_follow_up: int
