"""
Heaven on Earth CMS Backend - Testimonial Endpoints

Handles testimonial submissions and management.
"""

from typing import Annotated, Optional, List, Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.testimonial import (
    get_testimonials,
    get_testimonial_by_id,
    create_testimonial,
    update_testimonial,
    approve_testimonial,
    delete_testimonial,
)
from app.database import get_db
from app.dependencies import get_current_active_admin, get_optional_current_admin
from app.models.admin import Admin
from app.schemas.testimonial import (
    TestimonialResponse, 
    TestimonialCreate, 
    TestimonialUpdate,
    TestimonialReview,
    TestimonialPublic,
)
from app.schemas.common import MessageResponse, PaginatedResponse

router = APIRouter(prefix="/testimonials", tags=["Testimonials"])


@router.get("", response_model=PaginatedResponse[Union[TestimonialResponse, TestimonialPublic]]) # Use Union
async def list_testimonials(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Optional[Admin], Depends(get_optional_current_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = None,
    is_featured: Optional[bool] = None,
    search: Optional[str] = None,
):
    """
    List all testimonials with pagination and filtering.
    
    Unauthenticated users only see approved/published testimonials.
    Admins can see all testimonials.
    """
    skip = (page - 1) * page_size
    
    # Determine which response model to use for items
    response_item_model = TestimonialResponse if current_admin else TestimonialPublic
    
    # For public access, always filter by published status
    published_only_filter = True
    
    # Admins can optionally filter by status and see all testimonials
    if current_admin:
        published_only_filter = None # Admins can see unpublished/unapproved
        # If an admin explicitly requests a status, use it
        if status_filter:
            # If status_filter is provided, we don't want to override it with "approved"
            # The CRUD function will handle filtering by this status.
            pass
        else:
            # If no status filter is provided by admin, default to all for admin view
            status_filter = None
    else:
        # For unauthenticated users, always show only approved and published
        status_filter = "approved"
    
    testimonials, total = await get_testimonials(
        db,
        skip=skip,
        limit=page_size,
        status=status_filter,
        category=category,
        is_featured=is_featured,
        search=search,
        published_only=published_only_filter, # Pass the new filter
    )
    
    # Create PaginatedResponse with the appropriate item model
    return PaginatedResponse.create(
        items=testimonials,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=TestimonialResponse, status_code=status.HTTP_201_CREATED)
async def submit_testimonial(
    testimonial_in: TestimonialCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Submit a new testimonial.
    
    Public endpoint for website visitors.
    Testimonials are 'pending' by default.
    """
    return await create_testimonial(db, testimonial_in=testimonial_in)


@router.get("/{testimonial_id}", response_model=TestimonialResponse)
async def get_testimonial(
    testimonial_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Optional[Admin], Depends(get_optional_current_admin)],
):
    """
    Get a testimonial by ID.
    """
    testimonial = await get_testimonial_by_id(db, testimonial_id=testimonial_id)
    if not testimonial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testimonial not found",
        )
    
    # Only admins can see non-approved testimonials
    if testimonial.status != "approved" and not current_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testimonial not found",
        )
        
    return testimonial


@router.put("/{testimonial_id}", response_model=TestimonialResponse)
async def update_existing_testimonial(
    testimonial_id: UUID,
    testimonial_update: TestimonialUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Update a testimonial (content, category, featured status).
    
    Requires admin authentication.
    """
    testimonial = await get_testimonial_by_id(db, testimonial_id=testimonial_id)
    if not testimonial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testimonial not found",
        )
    
    return await update_testimonial(db, testimonial=testimonial, testimonial_update=testimonial_update)


@router.post("/{testimonial_id}/review", response_model=TestimonialResponse)
async def review_testimonial_submission(
    testimonial_id: UUID,
    review_in: TestimonialReview,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Approve or reject a testimonial.
    
    Requires admin authentication.
    """
    testimonial = await get_testimonial_by_id(db, testimonial_id=testimonial_id)
    if not testimonial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testimonial not found",
        )
    
    return await approve_testimonial(
        db,
        testimonial=testimonial,
        admin_id=current_admin.id,
        status=review_in.status,
        review_notes=review_in.review_notes,
        edited_content=review_in.edited_content,
        is_featured=review_in.is_featured,
    )


@router.delete("/{testimonial_id}", response_model=MessageResponse)
async def delete_existing_testimonial(
    testimonial_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Delete a testimonial.
    
    Requires admin authentication.
    """
    testimonial = await get_testimonial_by_id(db, testimonial_id=testimonial_id)
    if not testimonial:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testimonial not found",
        )
    
    await delete_testimonial(db, testimonial=testimonial)
    return MessageResponse(message="Testimonial deleted successfully")
