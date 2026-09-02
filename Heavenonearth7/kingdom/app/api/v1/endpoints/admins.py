from typing import Annotated, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.admin import (
    get_admins,
    get_admin_by_id,
    get_admin_by_email,
    create_admin_invite,
    update_admin,
    delete_admin,
    get_admin_by_invite_token,
    accept_admin_invite,
)
from app.database import get_db
from app.dependencies import get_current_active_admin, get_current_superadmin
from app.models.admin import Admin
from app.schemas.admin import (
    AdminResponse,
    AdminUpdate,
    AdminInvite,
    AdminInviteAccept,
    AdminList,
)
from app.schemas.common import MessageResponse, PaginatedResponse
from app.security import verify_invite_token


router = APIRouter(prefix="/admins", tags=["Admins"])


@router.get("", response_model=PaginatedResponse[AdminResponse])
async def list_admins(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_superadmin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
):
    """List all admins with pagination and filtering (superadmin only)."""
    skip = (page - 1) * page_size
    admins, total = await get_admins(
        db, skip=skip, limit=page_size, search=search, is_active=is_active
    )
    
    return PaginatedResponse.create(
        items=admins,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/me", response_model=AdminResponse)
async def get_me(
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """Get current admin's profile."""
    return current_admin


@router.put("/me", response_model=AdminResponse)
async def update_me(
    admin_update: AdminUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """Update current admin's profile."""
    return await update_admin(db, admin=current_admin, admin_update=admin_update)


@router.post("/invite", response_model=AdminResponse, status_code=status.HTTP_201_CREATED)
async def invite_admin(
    invite: AdminInvite,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_superadmin)],
):
    """Invite a new admin (superadmin only)."""
    existing_admin = await get_admin_by_email(db, email=invite.email)
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin with this email already exists",
        )
    
    # Create admin with invite token
    return await create_admin_invite(db, invite=invite, invited_by_id=current_admin.id)


@router.post("/invite/accept", response_model=AdminResponse)
async def accept_invite(
    accept_data: AdminInviteAccept,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Accept an admin invitation.
    
    Validates the invite token and sets the admin's password.
    """
    # Verify token cryptographically
    email = verify_invite_token(accept_data.token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invitation token",
        )
    
    # Get admin by token from DB
    admin = await get_admin_by_invite_token(db, token=accept_data.token)
    if not admin or admin.email != email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation not found",
        )
    
    # Accept invite and set password
    return await accept_admin_invite(db, admin=admin, password=accept_data.password)


@router.get("/{admin_id}", response_model=AdminResponse)
async def get_admin(
    admin_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_superadmin)],
):
    """
    Get an admin by ID.
    
    Requires superadmin privileges.
    """
    admin = await get_admin_by_id(db, admin_id=admin_id)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )
    return admin


@router.delete("/{admin_id}", response_model=MessageResponse)
async def deactivate_admin(
    admin_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_superadmin)],
):
    """
    Deactivate an admin account.
    
    Requires superadmin privileges.
    Cannot deactivate yourself.
    """
    if admin_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )
    
    admin = await get_admin_by_id(db, admin_id=admin_id)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin not found",
        )
    
    await delete_admin(db, admin=admin, soft_delete=True)
    return MessageResponse(message="Admin account deactivated successfully")
