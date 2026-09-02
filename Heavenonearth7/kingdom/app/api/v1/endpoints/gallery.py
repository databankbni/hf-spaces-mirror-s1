from typing import Annotated, Optional, List, Union
import os
import uuid
from datetime import datetime
from typing import Annotated, Optional, List, Union
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
import magic
from PIL import Image
import io

from app.crud.gallery import (
    get_gallery_items,
    get_gallery_item_by_id,
    create_gallery_item,
    update_gallery_item,
    delete_gallery_item,
)
from app.database import get_db
from app.dependencies import get_current_active_admin, get_optional_current_admin
from app.models.admin import Admin
from app.models.gallery import GalleryItem
from app.schemas.gallery import (
    GalleryItemResponse, 
    GalleryItemCreate, 
    GalleryItemUpdate,
    GalleryItemFileUpload,
    GalleryItemPublic,
    MediaType,
    Category
)
from app.schemas.common import MessageResponse, PaginatedResponse
from app.utils.supabase import supabase_storage
from app.config import settings


router = APIRouter(prefix="/gallery", tags=["Gallery"])



@router.get("", response_model=PaginatedResponse[GalleryItemPublic])
async def list_gallery_items(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Optional[Admin], Depends(get_optional_current_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    media_type: Optional[str] = None,
    is_featured: Optional[bool] = None,
    search: Optional[str] = None,
):
    """
    List all gallery items with pagination and filtering.
    
    Unauthenticated users only see published items.
    Admins can see all items.
    """
    skip = (page - 1) * page_size
    
    # Only admins can see unpublished items
    is_published = True if not current_admin else None
    
    items, total = await get_gallery_items(
        db,
        skip=skip,
        limit=page_size,
        category=category,
        media_type=media_type,
        is_featured=is_featured,
        is_published=is_published,
        search=search,
    )
    
    return PaginatedResponse.create(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{item_id}", response_model=GalleryItemResponse)
async def get_gallery_item(
    item_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Optional[Admin], Depends(get_optional_current_admin)],
):
    """
    Get a gallery item by ID.
    """
    item = await get_gallery_item_by_id(db, item_id=item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gallery item not found",
        )
    
    # Only admins can see unpublished items
    if not item.is_published and not current_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gallery item not found",
        )
        
    return item




async def process_uploaded_file(
    file: UploadFile,
    bucket: str = "folders",
    is_thumbnail: bool = False
) -> dict:
    """Process an uploaded file and upload to Supabase storage."""
    try:
        # Read file content
        content = await file.read()
        
        # Detect MIME type
        mime_type = magic.from_buffer(content, mime=True)
        
        # For thumbnails, ensure it's an image
        if is_thumbnail and not mime_type.startswith('image/'):
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_thumbnail", "message": "Thumbnail must be an image file"}
            )
        
        # Validate file type for non-thumbnails
        if not is_thumbnail and not (mime_type.startswith('image/') or mime_type.startswith('video/')):
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_file_type", "message": "Unsupported file type. Please upload an image or video file."}
            )
        
        # Generate a unique filename
        file_extension = os.path.splitext(file.filename or '')[1].lower() or '.bin'
        file_name = f"{uuid.uuid4()}{file_extension}"
        
        # Reset file cursor before uploading since we read it above
        await file.seek(0)
        
        # Upload to Supabase
        public_url, file_path = await supabase_storage.upload_file(
            file=file,
            bucket=bucket,
            path=""
        )
        
        # Get file size
        file_size = len(content)
        
        # For images, get dimensions
        width = None
        height = None
        
        if mime_type.startswith('image/'):
            try:
                with Image.open(io.BytesIO(content)) as img:
                    width, height = img.size
            except Exception as e:
                print(f"Warning: Could not get image dimensions: {e}")
        
        return {
            "file_name": file_name,
            "file_path": file_path,
            "src_url": public_url,
            "mime_type": mime_type,
            "file_size": file_size,
            "width": width,
            "height": height
        }
        
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        # Clean up any partially uploaded files
        try:
            await supabase_storage.delete_file(file_path)
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing file: {str(e)}"
        )


@router.post("", response_model=GalleryItemResponse, status_code=status.HTTP_201_CREATED)
async def create_new_gallery_item(
    title: str = Form(...),
    title_am: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    alt_text: str = Form(...),
    media_type: MediaType = Form(...),
    category: Category = Form(...),
    event_date: Optional[datetime] = Form(None),
    is_featured: bool = Form(False),
    is_published: bool = Form(True),
    display_order: int = Form(0),
    file: UploadFile = File(..., description="Media file (image or video)"),
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_active_admin)
):
    """
    Create a new gallery item with file upload.
    
    Requires admin authentication.
    Supports multipart form data for file uploads.
    """
    try:
        # Process the main file
        file_info = await process_uploaded_file(file)
        
        
        # Convert HttpUrl to string for database storage
        src_url = str(file_info["src_url"]) if file_info["src_url"] else None
        
        # Create gallery item
        gallery_item = GalleryItemCreate(
            title=title,
            title_am=title_am,
            description=description,
            alt_text=alt_text,
            media_type=media_type.value if hasattr(media_type, 'value') else str(media_type),
            category=category.value if hasattr(category, 'value') else str(category),
            src_url=src_url,
            file_name=file_info["file_name"],
            file_size=file_info["file_size"],
            mime_type=file_info["mime_type"],
            width=file_info["width"],
            height=file_info["height"],
            event_date=event_date,
            is_featured=is_featured,
            is_published=is_published,
            display_order=display_order
        )
        
        # Save to database
        return await create_gallery_item(
            db, 
            item_in=gallery_item, 
            created_by_id=current_admin.id
        )
        
    except Exception as e:
        # Log the full error details
        import traceback
        error_details = traceback.format_exc()
        print(f"Error creating gallery item: {error_details}")
        
        # Clean up uploaded files if there was an error
        if 'file_info' in locals() and file_info and file_info.get('file_path'):
            try:
                await supabase_storage.delete_file(file_info['file_path'])
            except Exception as cleanup_error:
                print(f"Error cleaning up file: {str(cleanup_error)}")
        
        if 'thumb_info' in locals() and thumb_info and thumb_info.get('file_path'):
            try:
                await supabase_storage.delete_file(thumb_info['file_path'])
            except Exception as cleanup_error:
                print(f"Error cleaning up thumbnail: {str(cleanup_error)}")
                
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating gallery item: {str(e)}\n{error_details}"
        )


@router.post("/url", response_model=GalleryItemResponse, status_code=status.HTTP_201_CREATED)
async def create_new_gallery_item_with_url(
    item_in: GalleryItemCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_active_admin)
):
    """
    Create a new gallery item with a direct URL.
    
    Requires admin authentication.
    Use this when you already have the file hosted elsewhere.
    """
    try:
        return await create_gallery_item(
            db, 
            item_in=item_in, 
            created_by_id=current_admin.id
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating gallery item: {str(e)}"
        )


@router.put("/{item_id}", response_model=GalleryItemResponse)
async def update_existing_gallery_item(
    item_id: UUID,
    item_update: GalleryItemUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_admin: Annotated[Admin, Depends(get_current_active_admin)],
):
    """
    Update an existing gallery item.
    
    Requires admin authentication.
    """
    item = await get_gallery_item_by_id(db, item_id=item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gallery item not found",
        )
    
    return await update_gallery_item(db, item=item, item_update=item_update)


@router.delete("/{item_id}", response_model=MessageResponse)
async def delete_existing_gallery_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(get_current_active_admin),
):
    """
    Delete a gallery item and its associated files from storage.
    
    Requires admin authentication.
    """
    item = await get_gallery_item_by_id(db, item_id=item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gallery item not found",
        )
    
    try:
        # Delete file from storage if it's in our Supabase bucket
        if item.src_url and settings.supabase_url in item.src_url:
            try:
                # Extract the file path from the URL
                file_path = "/".join(item.src_url.split("/")[3:])
                await supabase_storage.delete_file(file_path)
            except Exception as e:
                # Log the error but don't fail the request
                print(f"Error deleting file from storage: {str(e)}")
        
        # Delete thumbnail if it exists and is in our storage
        if item.thumbnail_url and settings.supabase_url in (item.thumbnail_url or ""):
            try:
                thumb_path = "/".join(item.thumbnail_url.split("/")[3:])
                await supabase_storage.delete_file(thumb_path)
            except Exception as e:
                # Log the error but don't fail the request
                print(f"Error deleting thumbnail from storage: {str(e)}")
        
        # Delete from database
        await delete_gallery_item(db, item=item)
        
        return MessageResponse(message="Gallery item deleted successfully")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting gallery item: {str(e)}"
        )
