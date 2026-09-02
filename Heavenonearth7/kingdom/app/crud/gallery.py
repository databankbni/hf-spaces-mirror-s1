"""
Heaven on Earth CMS Backend - Gallery CRUD Operations

Database operations for gallery management.
"""

from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gallery import GalleryItem
from app.schemas.gallery import GalleryItemCreate, GalleryItemUpdate


async def get_gallery_item_by_id(db: AsyncSession, item_id: UUID) -> Optional[GalleryItem]:
    """Get a gallery item by its ID."""
    result = await db.execute(select(GalleryItem).where(GalleryItem.id == item_id))
    return result.scalar_one_or_none()


async def get_gallery_items(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    category: Optional[str] = None,
    media_type: Optional[str] = None,
    is_featured: Optional[bool] = None,
    is_published: Optional[bool] = None,
    search: Optional[str] = None,
) -> Tuple[List[GalleryItem], int]:
    """
    Get a list of gallery items with pagination and filtering.
    
    Returns a tuple of (items, total_count).
    """
    # Base query
    query = select(GalleryItem)
    count_query = select(func.count(GalleryItem.id))
    
    # Apply filters
    if category:
        query = query.where(GalleryItem.category == category)
        count_query = count_query.where(GalleryItem.category == category)
        
    if media_type:
        query = query.where(GalleryItem.media_type == media_type)
        count_query = count_query.where(GalleryItem.media_type == media_type)
    
    if is_featured is not None:
        query = query.where(GalleryItem.is_featured == is_featured)
        count_query = count_query.where(GalleryItem.is_featured == is_featured)
        
    if is_published is not None:
        query = query.where(GalleryItem.is_published == is_published)
        count_query = count_query.where(GalleryItem.is_published == is_published)
    
    if search:
        search_filter = or_(
            GalleryItem.title.ilike(f"%{search}%"),
            GalleryItem.title_am.ilike(f"%{search}%"),
            GalleryItem.description.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated results
    query = query.order_by(GalleryItem.display_order.asc(), GalleryItem.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    items = list(result.scalars().all())
    
    return items, total


async def create_gallery_item(
    db: AsyncSession,
    item_in: GalleryItemCreate,
    created_by_id: UUID,
) -> GalleryItem:
    """Create a new gallery item."""
    # Convert model to dict and ensure all URLs are strings
    item_data = item_in.model_dump()
    
    # Convert HttpUrl objects to strings
    for field in ['src_url', 'thumbnail_url']:
        if field in item_data and item_data[field] is not None:
            item_data[field] = str(item_data[field])
    
    # Convert enum values to strings if needed
    for field in ['media_type', 'category']:
        if field in item_data and item_data[field] is not None and hasattr(item_data[field], 'value'):
            item_data[field] = item_data[field].value
    
    # Create the item
    item = GalleryItem(
        **item_data,
        created_by_id=created_by_id,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


async def update_gallery_item(
    db: AsyncSession,
    item: GalleryItem,
    item_update: GalleryItemUpdate,
) -> GalleryItem:
    """Update a gallery item."""
    update_data = item_update.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(item, field, value)
    
    await db.flush()
    await db.refresh(item)
    return item


async def delete_gallery_item(db: AsyncSession, item: GalleryItem) -> None:
    """Delete a gallery item."""
    await db.delete(item)
    await db.flush()
