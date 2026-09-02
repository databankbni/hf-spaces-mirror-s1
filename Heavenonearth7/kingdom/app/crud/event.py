"""
Heaven on Earth CMS Backend - Event CRUD Operations

Database operations for event management.
"""

from datetime import date
from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.schemas.event import EventCreate, EventUpdate


async def get_event_by_id(db: AsyncSession, event_id: UUID) -> Optional[Event]:
    """Get an event by its ID."""
    result = await db.execute(select(Event).where(Event.id == event_id))
    return result.scalar_one_or_none()


async def get_events(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    category: Optional[str] = None,
    is_featured: Optional[bool] = None,
    is_published: Optional[bool] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    search: Optional[str] = None,
) -> Tuple[List[Event], int]:
    """
    Get a list of events with pagination and filtering.
    
    Returns a tuple of (events, total_count).
    """
    # Base query
    query = select(Event)
    count_query = select(func.count(Event.id))
    
    # Apply filters
    if category:
        query = query.where(Event.category == category)
        count_query = count_query.where(Event.category == category)
    
    if is_featured is not None:
        query = query.where(Event.is_featured == is_featured)
        count_query = count_query.where(Event.is_featured == is_featured)
        
    if is_published is not None:
        query = query.where(Event.is_published == is_published)
        count_query = count_query.where(Event.is_published == is_published)
        
    if date_from:
        query = query.where(Event.event_date >= date_from)
        count_query = count_query.where(Event.event_date >= date_from)
        
    if date_to:
        query = query.where(Event.event_date <= date_to)
        count_query = count_query.where(Event.event_date <= date_to)
    
    if search:
        search_filter = or_(
            Event.title.ilike(f"%{search}%"),
            Event.title_am.ilike(f"%{search}%"),
            Event.description.ilike(f"%{search}%"),
            Event.location.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated results
    query = query.order_by(Event.event_date.asc(), Event.start_time.asc()).offset(skip).limit(limit)
    result = await db.execute(query)
    events = list(result.scalars().all())
    
    return events, total


async def create_event(
    db: AsyncSession,
    event_in: EventCreate,
    created_by_id: UUID,
) -> Event:
    """Create a new event."""
    event = Event(
        **event_in.model_dump(),
        created_by_id=created_by_id,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


async def update_event(
    db: AsyncSession,
    event: Event,
    event_update: EventUpdate,
) -> Event:
    """Update an event."""
    update_data = event_update.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(event, field, value)
    
    await db.flush()
    await db.refresh(event)
    return event


async def delete_event(db: AsyncSession, event: Event) -> None:
    """Delete an event."""
    await db.delete(event)
    await db.flush()
