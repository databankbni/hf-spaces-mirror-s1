from fastapi import APIRouter, Depends, HTTPException, status
from schemas import UserHistoryRequest, UserLibraryRequest
import auth as auth_utils
import database as db_mod

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/history")
async def get_history(book_url: str, current_email: str = Depends(auth_utils.get_current_user_email)):
    if not book_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing book_url")

    history = await db_mod.client.readinghistory.find_unique(
        where={"userEmail_book_url": {"userEmail": current_email, "book_url": book_url}}
    )

    return {"success": True, "data": history}


@router.post("/history")
async def save_history(payload: UserHistoryRequest, current_email: str = Depends(auth_utils.get_current_user_email)):
    if not payload.book_url or not payload.chapter_slug or not payload.chapter_title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Thiếu dữ liệu lịch sử đọc")

    await db_mod.client.readinghistory.upsert(
        where={"userEmail_book_url": {"userEmail": current_email, "book_url": payload.book_url}},
        data={
            "create": {
                "userEmail": current_email,
                "book_url": payload.book_url,
                "chapter_slug": payload.chapter_slug,
                "chapter_title": payload.chapter_title,
                "chapter_url": payload.chapter_url,
            },
            "update": {
                "chapter_slug": payload.chapter_slug,
                "chapter_title": payload.chapter_title,
                "chapter_url": payload.chapter_url,
            },
        },
    )

    return {"success": True}


@router.get("/library")
async def get_library_status(book_url: str, current_email: str = Depends(auth_utils.get_current_user_email)):
    if not book_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing book_url")

    item = await db_mod.client.userlibrary.find_unique(
        where={"userEmail_book_url": {"userEmail": current_email, "book_url": book_url}}
    )
    return {"success": True, "isSaved": bool(item)}


@router.post("/library")
async def toggle_library(payload: UserLibraryRequest, current_email: str = Depends(auth_utils.get_current_user_email)):
    if not payload.book_url or not payload.title_vi:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Thiếu dữ liệu tủ sách")

    existing = await db_mod.client.userlibrary.find_unique(
        where={"userEmail_book_url": {"userEmail": current_email, "book_url": payload.book_url}}
    )

    if existing:
        await db_mod.client.userlibrary.delete(where={"id": getattr(existing, "id", None)})
        return {"success": True, "isSaved": False, "message": "Đã xóa khỏi tủ sách"}

    await db_mod.client.userlibrary.create(
        data={
            "userEmail": current_email,
            "book_url": payload.book_url,
            "title_vi": payload.title_vi,
            "cover_url": payload.cover_url,
        }
    )
    return {"success": True, "isSaved": True, "message": "Đã lưu vào tủ sách"}


@router.get("/library/list")
async def get_library_list(current_email: str = Depends(auth_utils.get_current_user_email)):
    library = await db_mod.client.userlibrary.find_many(
        where={"userEmail": current_email},
        order={"createdAt": "desc"},
    )
    return {"success": True, "data": library}
