from typing import Annotated, Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.partnership import (
    get_partnerships,
    get_partnership_by_id,
    create_partnership,
    update_partnership,
    log_partnership_contact,
    delete_partnership,
)
from app.database import get_db
from app.dependencies import get_current_active_admin
from app.models.admin import Admin
from app.schemas.partnership import (
    PartnershipResponse, 
    PartnershipCreate, 
    PartnershipUpdate,
    PartnershipContactLog,
)
from app.schemas.common import MessageResponse, PaginatedResponse


router = APIRouter(prefix="/partnerships", tags=["Partnerships"])


@router.get("", response_model=PaginatedResponse[PartnershipResponse])
async def list_partnership_applications(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    partnership_type: Optional[str] = None,
    status: Optional[str] = None,
    assigned_to_id: Optional[UUID] = None,
    search: Optional[str] = None,
):
    """List partnership applications with pagination and filtering (admin only)."""
    skip = (page - 1) * page_size
    
    partnerships, total = await get_partnerships(
        db,
        skip=skip,
        limit=page_size,
        partnership_type=partnership_type,
        status=status,
        assigned_to_id=assigned_to_id,
        search=search,
    )
    
    return PaginatedResponse.create(
        items=partnerships,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=PartnershipResponse, status_code=status.HTTP_201_CREATED)
async def submit_partnership_application(
    partnership_in: PartnershipCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Submit a new partnership application (public endpoint)."""
    return await create_partnership(db, partnership_in=partnership_in)


@router.get("/{partnership_id}", response_model=PartnershipResponse)
async def get_partnership(
    partnership_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """Get partnership application by ID (admin only)."""
    partnership = await get_partnership_by_id(db, partnership_id=partnership_id)
    if not partnership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partnership application not found",
        )
    return partnership


@router.put("/{partnership_id}", response_model=PartnershipResponse)
async def update_partnership_application(
    partnership_id: UUID,
    partnership_update: PartnershipUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Update a partnership application (status, notes, assignment).
    
    Requires admin authentication.
    """
    partnership = await get_partnership_by_id(db, partnership_id=partnership_id)
    if not partnership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partnership application not found",
        )
    
    return await update_partnership(db, partnership=partnership, partnership_update=partnership_update)


@router.post("/{partnership_id}/contact", response_model=PartnershipResponse)
async def log_partner_contact(
    partnership_id: UUID,
    contact_log: PartnershipContactLog,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Log contact with a potential partner.
    
    Requires admin authentication.
    """
    partnership = await get_partnership_by_id(db, partnership_id=partnership_id)
    if not partnership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partnership application not found",
        )
    
    return await log_partnership_contact(
        db, 
        partnership=partnership, 
        admin_id=current_admin.id, 
        notes=contact_log.notes
    )


@router.delete("/{partnership_id}", response_model=MessageResponse)
async def delete_partnership_application(
    partnership_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Delete a partnership application.
    
    Requires admin authentication.
    """
    partnership = await get_partnership_by_id(db, partnership_id=partnership_id)
    if not partnership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Partnership application not found",
        )
    
    await delete_partnership(db, partnership=partnership)
    return MessageResponse(message="Partnership application deleted successfully")
