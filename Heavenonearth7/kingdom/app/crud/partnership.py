"""
Heaven on Earth CMS Backend - Partnership CRUD Operations

Database operations for partnership management.
"""

from datetime import datetime, timezone
from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.partnership import Partnership
from app.schemas.partnership import PartnershipCreate, PartnershipUpdate


async def get_partnership_by_id(db: AsyncSession, partnership_id: UUID) -> Optional[Partnership]:
    """Get a partnership application by its ID."""
    result = await db.execute(select(Partnership).where(Partnership.id == partnership_id))
    return result.scalar_one_or_none()


async def get_partnerships(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    partnership_type: Optional[str] = None,
    status: Optional[str] = None,
    assigned_to_id: Optional[UUID] = None,
    search: Optional[str] = None,
) -> Tuple[List[Partnership], int]:
    """
    Get a list of partnership applications with pagination and filtering.
    
    Returns a tuple of (partnerships, total_count).
    """
    # Base query
    query = select(Partnership)
    count_query = select(func.count(Partnership.id))
    
    # Apply filters
    if partnership_type:
        query = query.where(Partnership.partnership_type == partnership_type)
        count_query = count_query.where(Partnership.partnership_type == partnership_type)
        
    if status:
        query = query.where(Partnership.status == status)
        count_query = count_query.where(Partnership.status == status)
        
    if assigned_to_id:
        query = query.where(Partnership.assigned_to_id == assigned_to_id)
        count_query = count_query.where(Partnership.assigned_to_id == assigned_to_id)
    
    if search:
        search_filter = or_(
            Partnership.name.ilike(f"%{search}%"),
            Partnership.email.ilike(f"%{search}%"),
            Partnership.message.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated results
    query = query.order_by(Partnership.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    partnerships = list(result.scalars().all())
    
    return partnerships, total


async def create_partnership(
    db: AsyncSession,
    partnership_in: PartnershipCreate,
) -> Partnership:
    """Create a new partnership application."""
    partnership = Partnership(
        **partnership_in.model_dump(),
    )
    db.add(partnership)
    await db.flush()
    await db.refresh(partnership)
    return partnership


async def update_partnership(
    db: AsyncSession,
    partnership: Partnership,
    partnership_update: PartnershipUpdate,
) -> Partnership:
    """Update a partnership application."""
    update_data = partnership_update.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(partnership, field, value)
    
    await db.flush()
    await db.refresh(partnership)
    return partnership


async def log_partnership_contact(
    db: AsyncSession,
    partnership: Partnership,
    admin_id: UUID,
    notes: Optional[str] = None,
) -> Partnership:
    """Log that a partner was contacted."""
    partnership.last_contacted_at = datetime.now(timezone.utc)
    partnership.contact_count += 1
    partnership.assigned_to_id = admin_id
    
    if notes:
        existing_notes = partnership.admin_notes or ""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        partnership.admin_notes = f"{existing_notes}\n[{timestamp}] {notes}".strip()
    
    await db.flush()
    await db.refresh(partnership)
    return partnership


async def delete_partnership(db: AsyncSession, partnership: Partnership) -> None:
    """Delete a partnership application."""
    await db.delete(partnership)
    await db.flush()
