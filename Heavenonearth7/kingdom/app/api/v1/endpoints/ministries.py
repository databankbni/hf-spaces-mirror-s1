from typing import Annotated, Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.ministry import (
    get_ministries,
    get_ministry_by_id,
    get_ministry_by_key,
    create_ministry,
    update_ministry,
    delete_ministry,
)
from app.database import get_db
from app.dependencies import get_current_active_admin, get_optional_current_admin
from app.models.admin import Admin
from app.schemas.ministry import (
    MinistryResponse,
    MinistryCreate,
    MinistryUpdate,
    MinistryPublic,
)
from app.schemas.common import MessageResponse, PaginatedResponse


router = APIRouter(prefix="/ministries", tags=["Ministries"])


@router.get("", response_model=PaginatedResponse[MinistryPublic])
async def list_ministries(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Optional[Admin], Depends(get_optional_current_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_featured: Optional[bool] = None,
    search: Optional[str] = None,
):
    """List ministries with pagination. Admins see all, others see only active."""
    skip = (page - 1) * page_size
    is_active = None if current_admin else True
    
    ministries, total = await get_ministries(
        db,
        skip=skip,
        limit=page_size,
        is_active=is_active,
        is_featured=is_featured,
        search=search,
    )
    
    return PaginatedResponse.create(
        items=ministries,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{ministry_id_or_key}", response_model=MinistryResponse)
async def get_ministry(
    ministry_id_or_key: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Optional[Admin], Depends(get_optional_current_admin)],
):
    """Get ministry by ID or key. Admins can see inactive ministries."""
    try:
        ministry_id = UUID(ministry_id_or_key)
        ministry = await get_ministry_by_id(db, ministry_id=ministry_id)
    except ValueError:
        ministry = await get_ministry_by_key(db, ministry_key=ministry_id_or_key)
        
    if not ministry or (not ministry.is_active and not current_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ministry not found",
        )
        
    return ministry


@router.post("", response_model=MinistryResponse, status_code=status.HTTP_201_CREATED)
async def create_new_ministry(
    ministry_in: MinistryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """Create a new ministry (admin only)."""
    existing = await get_ministry_by_key(db, ministry_key=ministry_in.ministry_key)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A ministry with this key already exists",
        )
    
    return await create_ministry(db, ministry_in=ministry_in, created_by_id=current_admin.id)


@router.put("/{ministry_id}", response_model=MinistryResponse)
async def update_existing_ministry(
    ministry_id: UUID,
    ministry_update: MinistryUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Update an existing ministry.
    
    Requires admin authentication.
    """
    ministry = await get_ministry_by_id(db, ministry_id=ministry_id)
    if not ministry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ministry not found",
        )
    
    return await update_ministry(db, ministry=ministry, ministry_update=ministry_update)


@router.delete("/{ministry_id}", response_model=MessageResponse)
async def delete_existing_ministry(
    ministry_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Delete a ministry.
    
    Requires admin authentication.
    """
    ministry = await get_ministry_by_id(db, ministry_id=ministry_id)
    if not ministry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ministry not found",
        )
    
    await delete_ministry(db, ministry=ministry)
    return MessageResponse(message="Ministry deleted successfully")
