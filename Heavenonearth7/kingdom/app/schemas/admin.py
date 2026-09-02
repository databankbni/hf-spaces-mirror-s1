"""
Heaven on Earth CMS Backend - Admin Schemas

Pydantic schemas for admin authentication and management.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class AdminBase(BaseModel):
    """Base schema for admin data."""
    
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)


class AdminCreate(AdminBase):
    """Schema for creating an admin (used internally)."""
    
    password: str = Field(min_length=8, max_length=128)
    is_superadmin: bool = False


class AdminInvite(BaseModel):
    """Schema for inviting a new admin."""
    
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    is_superadmin: bool = False
    
    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.lower()


class AdminInviteAccept(BaseModel):
    """Schema for accepting an admin invitation."""
    
    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=128)
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain an uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain a lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain a digit")
        return v


class AdminUpdate(BaseModel):
    """Schema for updating admin profile."""
    
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=50)
    avatar_url: Optional[str] = Field(default=None, max_length=500)


class AdminPasswordChange(BaseModel):
    """Schema for changing admin password."""
    
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)
    
    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain an uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain a lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain a digit")
        return v


class AdminResponse(BaseModel):
    """Schema for admin response (public data only)."""
    
    id: UUID
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool
    is_superadmin: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class AdminInDB(AdminResponse):
    """Schema for admin data from database (includes internal fields)."""
    
    invited_by_id: Optional[UUID] = None
    invite_accepted_at: Optional[datetime] = None
    updated_at: datetime


class AdminLogin(BaseModel):
    """Schema for admin login request."""
    
    email: EmailStr
    password: str = Field(min_length=1)
    
    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.lower()


class Token(BaseModel):
    """Schema for JWT token response."""
    
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until access token expires")


class TokenRefresh(BaseModel):
    """Schema for token refresh request."""
    
    refresh_token: str


class AdminList(BaseModel):
    """Schema for list of admins."""
    
    items: List[AdminResponse]
    total: int
    page: int
    page_size: int
