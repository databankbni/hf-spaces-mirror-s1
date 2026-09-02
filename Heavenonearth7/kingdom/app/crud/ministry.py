"""
Heaven on Earth CMS Backend - Ministry CRUD Operations

Database operations for ministry management.
"""

from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ministry import Ministry
from app.schemas.ministry import MinistryCreate, MinistryUpdate


async def get_ministry_by_id(db: AsyncSession, ministry_id: UUID) -> Optional[Ministry]:
    """Get a ministry by its ID."""
    result = await db.execute(select(Ministry).where(Ministry.id == ministry_id))
    return result.scalar_one_or_none()


async def get_ministry_by_key(db: AsyncSession, ministry_key: str) -> Optional[Ministry]:
    """Get a ministry by its unique key."""
    result = await db.execute(select(Ministry).where(Ministry.ministry_key == ministry_key))
    return result.scalar_one_or_none()


async def get_ministries(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    is_active: Optional[bool] = None,
    is_featured: Optional[bool] = None,
    search: Optional[str] = None,
) -> Tuple[List[Ministry], int]:
    """
    Get a list of ministries with pagination and filtering.
    
    Returns a tuple of (ministries, total_count).
    """
    # Base query
    query = select(Ministry)
    count_query = select(func.count(Ministry.id))
    
    # Apply filters
    if is_active is not None:
        query = query.where(Ministry.is_active == is_active)
        count_query = count_query.where(Ministry.is_active == is_active)
    
    if is_featured is not None:
        query = query.where(Ministry.is_featured == is_featured)
        count_query = count_query.where(Ministry.is_featured == is_featured)
    
    if search:
        search_filter = or_(
            Ministry.title.ilike(f"%{search}%"),
            Ministry.title_am.ilike(f"%{search}%"),
            Ministry.description.ilike(f"%{search}%"),
            Ministry.leader_name.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated results
    query = query.order_by(Ministry.display_order.asc(), Ministry.title.asc()).offset(skip).limit(limit)
    result = await db.execute(query)
    ministries = list(result.scalars().all())
    
    return ministries, total


async def create_ministry(
    db: AsyncSession,
    ministry_in: MinistryCreate,
    created_by_id: UUID,
) -> Ministry:
    """Create a new ministry."""
    ministry = Ministry(
        **ministry_in.model_dump(),
        created_by_id=created_by_id,
    )
    db.add(ministry)
    await db.flush()
    await db.refresh(ministry)
    return ministry


async def update_ministry(
    db: AsyncSession,
    ministry: Ministry,
    ministry_update: MinistryUpdate,
) -> Ministry:
    """Update a ministry."""
    update_data = ministry_update.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(ministry, field, value)
    
    await db.flush()
    await db.refresh(ministry)
    return ministry


async def delete_ministry(db: AsyncSession, ministry: Ministry) -> None:
    """Delete a ministry."""
    await db.delete(ministry)
    await db.flush()
