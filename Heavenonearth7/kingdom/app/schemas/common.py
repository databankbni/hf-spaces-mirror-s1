"""
Heaven on Earth CMS Backend - Common Schemas

Shared Pydantic schemas used across the application.
"""

from typing import Generic, List, Optional, TypeVar
from datetime import datetime

from pydantic import BaseModel, Field


# Generic type for paginated responses
T = TypeVar("T")


class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""
    
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(
        default=20, 
        ge=1, 
        le=100, 
        description="Items per page"
    )
    
    @property
    def offset(self) -> int:
        """Calculate offset for database query."""
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""
    
    items: List[T]
    total: int = Field(description="Total number of items")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Items per page")
    total_pages: int = Field(description="Total number of pages")
    has_next: bool = Field(description="Whether there's a next page")
    has_previous: bool = Field(description="Whether there's a previous page")
    
    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        """Factory method to create a paginated response."""
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        )


class MessageResponse(BaseModel):
    """Simple message response."""
    
    message: str
    success: bool = True


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str = "healthy"
    version: str
    environment: str
    timestamp: datetime


class ErrorDetail(BaseModel):
    """Error detail for validation errors."""
    
    field: Optional[str] = None
    message: str
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standardized error response."""
    
    error: str
    message: str
    details: Optional[List[ErrorDetail]] = None
    status_code: int


class BaseTimestampSchema(BaseModel):
    """Base schema with timestamp fields."""
    
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class FilterParams(BaseModel):
    """Common filter parameters."""
    
    search: Optional[str] = Field(
        default=None, 
        description="Search term"
    )
    is_active: Optional[bool] = Field(
        default=None, 
        description="Filter by active status"
    )
    sort_by: Optional[str] = Field(
        default="created_at", 
        description="Field to sort by"
    )
    sort_order: Optional[str] = Field(
        default="desc", 
        pattern="^(asc|desc)$",
        description="Sort order (asc or desc)"
    )
