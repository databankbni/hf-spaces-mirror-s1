"""
Heaven on Earth CMS Backend - Testimonial CRUD Operations

Database operations for testimonial management.
"""

from datetime import datetime, timezone
from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.testimonial import Testimonial
from app.schemas.testimonial import TestimonialCreate, TestimonialUpdate


async def get_testimonial_by_id(db: AsyncSession, testimonial_id: UUID) -> Optional[Testimonial]:
    """Get a testimonial by its ID."""
    result = await db.execute(select(Testimonial).where(Testimonial.id == testimonial_id))
    return result.scalar_one_or_none()


async def get_testimonials(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    category: Optional[str] = None,
    is_featured: Optional[bool] = None,
    search: Optional[str] = None,
    published_only: Optional[bool] = None, # New parameter
) -> Tuple[List[Testimonial], int]:
    """
    Get a list of testimonials with pagination and filtering.
    
    Returns a tuple of (testimonials, total_count).
    """
    # Base query
    query = select(Testimonial)
    count_query = select(func.count(Testimonial.id))
    
    # Apply filters
    if status:
        query = query.where(Testimonial.status == status)
        count_query = count_query.where(Testimonial.status == status)
        
    if category:
        query = query.where(Testimonial.category == category)
        count_query = count_query.where(Testimonial.category == category)
        
    if is_featured is not None:
        query = query.where(Testimonial.is_featured == is_featured)
        count_query = count_query.where(Testimonial.is_featured == is_featured)
    
    if search:
        search_filter = or_(
            Testimonial.name.ilike(f"%{search}%"),
            Testimonial.title.ilike(f"%{search}%"),
            Testimonial.content.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
        
    if published_only: # Apply published_only filter
        query = query.where(Testimonial.published_at.isnot(None))
        count_query = count_query.where(Testimonial.published_at.isnot(None))

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated results
    query = query.order_by(Testimonial.display_order.asc(), Testimonial.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    testimonials = list(result.scalars().all())

    return testimonials, total


async def create_testimonial(
    db: AsyncSession,
    testimonial_in: TestimonialCreate,
) -> Testimonial:
    """Create a new testimonial (usually from website)."""
    testimonial = Testimonial(
        **testimonial_in.model_dump(),
    )
    db.add(testimonial)
    await db.flush()
    await db.refresh(testimonial)
    return testimonial


async def update_testimonial(
    db: AsyncSession,
    testimonial: Testimonial,
    testimonial_update: TestimonialUpdate,
) -> Testimonial:
    """Update a testimonial."""
    update_data = testimonial_update.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(testimonial, field, value)
    
    await db.flush()
    await db.refresh(testimonial)
    return testimonial


async def approve_testimonial(
    db: AsyncSession,
    testimonial: Testimonial,
    admin_id: UUID,
    status: str = "approved",
    review_notes: Optional[str] = None,
    edited_content: Optional[str] = None,
    is_featured: bool = False,
) -> Testimonial:
    """Approve or reject a testimonial."""
    testimonial.status = status
    testimonial.is_featured = is_featured
    testimonial.reviewed_by_id = admin_id
    testimonial.reviewed_at = datetime.now(timezone.utc)
    testimonial.review_notes = review_notes
    
    if edited_content:
        testimonial.edited_content = edited_content
        
    if status == "approved":
        testimonial.published_at = datetime.now(timezone.utc)
    
    await db.flush()
    await db.refresh(testimonial)
    return testimonial


async def delete_testimonial(db: AsyncSession, testimonial: Testimonial) -> None:
    """Delete a testimonial."""
    await db.delete(testimonial)
    await db.flush()
