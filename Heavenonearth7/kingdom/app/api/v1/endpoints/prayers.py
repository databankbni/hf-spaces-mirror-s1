from typing import Annotated, Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.prayer import (
    get_prayer_requests,
    get_prayer_request_by_id,
    create_prayer_request,
    update_prayer_request,
    respond_to_prayer_request,
    increment_prayer_count,
    delete_prayer_request,
)
from app.database import get_db
from app.dependencies import get_current_active_admin, get_optional_current_admin
from app.models.admin import Admin
from app.schemas.prayer import (
    PrayerRequestResponse, 
    PrayerRequestCreate, 
    PrayerRequestUpdate,
    PrayerRequestRespond,
)
from app.schemas.common import MessageResponse, PaginatedResponse


router = APIRouter(prefix="/prayers", tags=["Prayer Requests"])


@router.get("", response_model=PaginatedResponse[PrayerRequestResponse])
async def list_prayer_requests(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Optional[Admin], Depends(get_optional_current_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    is_anonymous: Optional[bool] = None,
    is_public: Optional[bool] = None,
    search: Optional[str] = None,
):
    """
    List all prayer requests with pagination and filtering.
    
    Unauthenticated users only see public prayer requests.
    Admins can see all requests.
    """
    skip = (page - 1) * page_size
    
    # Non-admins can only see public requests
    if not current_admin:
        is_public = True
    
    requests, total = await get_prayer_requests(
        db,
        skip=skip,
        limit=page_size,
        status=status,
        is_anonymous=is_anonymous,
        is_public=is_public,
        search=search,
    )
    
    return PaginatedResponse.create(
        items=requests,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=PrayerRequestResponse, status_code=status.HTTP_201_CREATED)
async def submit_prayer_request(
    prayer_in: PrayerRequestCreate,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Submit a new prayer request.
    
    Public endpoint for website visitors.
    """
    # Simple IP hashing for rate limiting/tracking
    import hashlib
    client_ip = request.client.host if request.client else "unknown"
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()
    
    return await create_prayer_request(db, prayer_in=prayer_in, ip_hash=ip_hash)


@router.get("/{prayer_id}", response_model=PrayerRequestResponse)
async def get_prayer(
    prayer_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Get a prayer request by ID.
    
    Requires admin authentication.
    """
    prayer = await get_prayer_request_by_id(db, prayer_id=prayer_id)
    if not prayer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prayer request not found",
        )
    return prayer


@router.put("/{prayer_id}", response_model=PrayerRequestResponse)
async def update_prayer(
    prayer_id: UUID,
    prayer_update: PrayerRequestUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Update a prayer request (status, notes, etc).
    
    Requires admin authentication.
    """
    prayer = await get_prayer_request_by_id(db, prayer_id=prayer_id)
    if not prayer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prayer request not found",
        )
    
    return await update_prayer_request(db, prayer=prayer, prayer_update=prayer_update)


@router.post("/{prayer_id}/respond", response_model=PrayerRequestResponse)
async def respond_to_prayer(
    prayer_id: UUID,
    respond_in: PrayerRequestRespond,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Log an admin response to a prayer request.
    
    Requires admin authentication.
    """
    prayer = await get_prayer_request_by_id(db, prayer_id=prayer_id)
    if not prayer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prayer request not found",
        )
    
    return await respond_to_prayer_request(
        db, 
        prayer=prayer, 
        response_message=respond_in.response_message,
        admin_id=current_admin.id
    )


@router.post("/{prayer_id}/pray", response_model=PrayerRequestResponse)
async def pray_for_request(
    prayer_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Increment the 'I prayed' count for a request.
    
    Public endpoint for website visitors.
    """
    prayer = await get_prayer_request_by_id(db, prayer_id=prayer_id)
    if not prayer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prayer request not found",
        )
    
    return await increment_prayer_count(db, prayer=prayer)


@router.delete("/{prayer_id}", response_model=MessageResponse)
async def delete_prayer(
    prayer_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Delete a prayer request.
    
    Requires admin authentication.
    """
    prayer = await get_prayer_request_by_id(db, prayer_id=prayer_id)
    if not prayer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prayer request not found",
        )
    
    await delete_prayer_request(db, prayer=prayer)
    return MessageResponse(message="Prayer request deleted successfully")
