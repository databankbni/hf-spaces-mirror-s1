"""
Heaven on Earth CMS Backend - Admin CRUD Operations

Database operations for admin management.
"""

from datetime import datetime, timezone
from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin
from app.schemas.admin import AdminCreate, AdminUpdate, AdminInvite
from app.security import get_password_hash, generate_invite_token
from app.config import settings


async def get_admin_by_id(db: AsyncSession, admin_id: UUID) -> Optional[Admin]:
    """Get an admin by their ID."""
    result = await db.execute(select(Admin).where(Admin.id == admin_id))
    return result.scalar_one_or_none()


async def get_admin_by_email(db: AsyncSession, email: str) -> Optional[Admin]:
    """Get an admin by their email address."""
    result = await db.execute(
        select(Admin).where(Admin.email == email.lower())
    )
    return result.scalar_one_or_none()


async def get_admins(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Tuple[List[Admin], int]:
    """
    Get a list of admins with pagination and filtering.
    
    Returns a tuple of (admins, total_count).
    """
    # Base query
    query = select(Admin)
    count_query = select(func.count(Admin.id))
    
    # Apply filters
    if search:
        search_filter = or_(
            Admin.email.ilike(f"%{search}%"),
            Admin.full_name.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)
    
    if is_active is not None:
        query = query.where(Admin.is_active == is_active)
        count_query = count_query.where(Admin.is_active == is_active)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated results
    query = query.order_by(Admin.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    admins = list(result.scalars().all())
    
    return admins, total


async def create_admin(
    db: AsyncSession,
    admin_in: AdminCreate,
    invited_by_id: Optional[UUID] = None,
) -> Admin:
    """Create a new admin."""
    admin = Admin(
        email=admin_in.email.lower(),
        hashed_password=get_password_hash(admin_in.password),
        full_name=admin_in.full_name,
        phone=admin_in.phone,
        is_superadmin=admin_in.is_superadmin,
        invited_by_id=invited_by_id,
        invite_accepted_at=datetime.now(timezone.utc),
    )
    db.add(admin)
    await db.flush()
    await db.refresh(admin)
    return admin


async def create_admin_invite(
    db: AsyncSession,
    invite: AdminInvite,
    invited_by_id: UUID,
) -> Admin:
    """Create an admin with a pending invite."""
    invite_token = generate_invite_token(invite.email)
    
    admin = Admin(
        email=invite.email.lower(),
        hashed_password="",  # Will be set when invite is accepted
        full_name=invite.full_name,
        is_superadmin=invite.is_superadmin,
        is_active=False,  # Not active until invite is accepted
        invited_by_id=invited_by_id,
        invite_token=invite_token,
    )
    db.add(admin)
    await db.flush()
    await db.refresh(admin)
    return admin


async def accept_admin_invite(
    db: AsyncSession,
    admin: Admin,
    password: str,
) -> Admin:
    """Accept an admin invitation and set password."""
    admin.hashed_password = get_password_hash(password)
    admin.is_active = True
    admin.invite_token = None
    admin.invite_accepted_at = datetime.now(timezone.utc)
    
    await db.flush()
    await db.refresh(admin)
    return admin


async def update_admin(
    db: AsyncSession,
    admin: Admin,
    admin_update: AdminUpdate,
) -> Admin:
    """Update an admin's profile."""
    update_data = admin_update.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(admin, field, value)
    
    await db.flush()
    await db.refresh(admin)
    return admin


async def update_admin_password(
    db: AsyncSession,
    admin: Admin,
    new_password: str,
) -> Admin:
    """Update an admin's password."""
    admin.hashed_password = get_password_hash(new_password)
    await db.flush()
    await db.refresh(admin)
    return admin


async def update_admin_login(
    db: AsyncSession,
    admin: Admin,
) -> Admin:
    """Update admin's last login time."""
    admin.last_login_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(admin)
    return admin


async def delete_admin(
    db: AsyncSession,
    admin: Admin,
    soft_delete: bool = True,
) -> None:
    """
    Delete an admin.
    
    By default performs a soft delete (sets is_active=False).
    """
    if soft_delete:
        admin.is_active = False
        await db.flush()
    else:
        await db.delete(admin)
        await db.flush()


async def create_initial_admin(db: AsyncSession) -> Optional[Admin]:
    """
    Create the initial superadmin from environment variables.
    
    This is called on first startup if no admins exist.
    Returns the created admin or None if admin already exists.
    """
    # Check if any admin exists
    result = await db.execute(select(func.count(Admin.id)))
    count = result.scalar() or 0
    
    if count > 0:
        return None
    
    # Create initial admin from env settings
    admin = Admin(
        email=settings.admin_email.lower(),
        hashed_password=get_password_hash(settings.admin_password),
        full_name=settings.admin_full_name,
        is_superadmin=True,
        is_active=True,
    )
    db.add(admin)
    await db.flush()
    await db.refresh(admin)
    
    return admin


async def get_admin_by_invite_token(
    db: AsyncSession,
    token: str,
) -> Optional[Admin]:
    """Get an admin by their invite token."""
    result = await db.execute(
        select(Admin).where(Admin.invite_token == token)
    )
    return result.scalar_one_or_none()
