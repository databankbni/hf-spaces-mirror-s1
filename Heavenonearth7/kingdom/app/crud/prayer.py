"""
Heaven on Earth CMS Backend - Prayer CRUD Operations

Database operations for prayer request management.
"""

from datetime import datetime, timezone
from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prayer import PrayerRequest
from app.schemas.prayer import PrayerRequestCreate, PrayerRequestUpdate


async def get_prayer_request_by_id(db: AsyncSession, prayer_id: UUID) -> Optional[PrayerRequest]:
    """Get a prayer request by its ID."""
    result = await db.execute(select(PrayerRequest).where(PrayerRequest.id == prayer_id))
    return result.scalar_one_or_none()


async def get_prayer_requests(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    status: Optional[str] = None,
    is_anonymous: Optional[bool] = None,
    is_public: Optional[bool] = None,
    search: Optional[str] = None,
) -> Tuple[List[PrayerRequest], int]:
    """
    Get a list of prayer requests with pagination and filtering.
    
    Returns a tuple of (requests, total_count).
    """
    # Base query
    query = select(PrayerRequest)
    count_query = select(func.count(PrayerRequest.id))
    
    # Apply filters
    if status:
        query = query.where(PrayerRequest.status == status)
        count_query = count_query.where(PrayerRequest.status == status)
        
    if is_anonymous is not None:
        query = query.where(PrayerRequest.is_anonymous == is_anonymous)
        count_query = count_query.where(PrayerRequest.is_anonymous == is_anonymous)
        
    if is_public is not None:
        query = query.where(PrayerRequest.is_public == is_public)
        count_query = count_query.where(PrayerRequest.is_public == is_public)
    
    if search:
        search_filter = or_(
            PrayerRequest.name.ilike(f"%{search}%"),
            PrayerRequest.email.ilike(f"%{search}%"),
            PrayerRequest.request.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated results
    query = query.order_by(PrayerRequest.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    requests = list(result.scalars().all())
    
    return requests, total


async def create_prayer_request(
    db: AsyncSession,
    prayer_in: PrayerRequestCreate,
    ip_hash: Optional[str] = None,
) -> PrayerRequest:
    """Create a new prayer request."""
    prayer = PrayerRequest(
        **prayer_in.model_dump(),
        ip_hash=ip_hash,
    )
    db.add(prayer)
    await db.flush()
    await db.refresh(prayer)
    return prayer


async def update_prayer_request(
    db: AsyncSession,
    prayer: PrayerRequest,
    prayer_update: PrayerRequestUpdate,
) -> PrayerRequest:
    """Update a prayer request status or notes."""
    update_data = prayer_update.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(prayer, field, value)
    
    await db.flush()
    await db.refresh(prayer)
    return prayer


async def respond_to_prayer_request(
    db: AsyncSession,
    prayer: PrayerRequest,
    response_message: str,
    admin_id: UUID,
) -> PrayerRequest:
    """Log an admin response to a prayer request."""
    prayer.response_message = response_message
    prayer.responded_at = datetime.now(timezone.utc)
    prayer.responded_by_id = admin_id
    prayer.status = "completed"
    
    await db.flush()
    await db.refresh(prayer)
    return prayer


async def increment_prayer_count(db: AsyncSession, prayer: PrayerRequest) -> PrayerRequest:
    """Increment the 'I prayed' count for a request."""
    prayer.prayer_count += 1
    await db.flush()
    await db.refresh(prayer)
    return prayer


async def delete_prayer_request(db: AsyncSession, prayer: PrayerRequest) -> None:
    """Delete a prayer request."""
    await db.delete(prayer)
    await db.flush()
