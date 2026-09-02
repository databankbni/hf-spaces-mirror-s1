from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException, Depends
from typing import Optional
from uuid import uuid4
import logging

import database as db_mod
from services.video_service import create_video_from_source_url
from services.video_download import download_remote_video
from services.youtube_token_store import get_refresh_token
from services.youtube_video_upload import upload_video_to_youtube
from services.youtube_uploader import build_oauth_authorization_url, refresh_access_token
from supabase_storage import delete_file_from_supabase_storage
from utils import normalize_source_url
import auth as auth_utils

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/videos",
    tags=["video"],
)


def _serialize_video_row(row: dict) -> dict:
    if isinstance(row, dict):
        return {
            "id": row.get("id"),
            "book_url": row.get("book_url"),
            "video_url": row.get("video_url"),
            "chapter_start": row.get("chapter_start"),
            "chapter_count": row.get("chapter_count"),
            "voice": row.get("voice"),
            "rate": row.get("rate"),
            "job_id": row.get("job_id"),
            "thumbnail_url": row.get("thumbnail_url"),
            "book_title": row.get("book_title"),
            "author_name": row.get("author_name"),
            "video_title": row.get("video_title"),
            "video_description": row.get("video_description"),
            "video_tags": row.get("video_tags"),
            "createdAt": row.get("createdAt") or row.get("created_at"),
            "updatedAt": row.get("updatedAt") or row.get("updated_at"),
        }

    return {
        "id": getattr(row, "id", None),
        "book_url": getattr(row, "book_url", None),
        "video_url": getattr(row, "video_url", None),
        "chapter_start": getattr(row, "chapter_start", None),
        "chapter_count": getattr(row, "chapter_count", None),
        "voice": getattr(row, "voice", None),
        "rate": getattr(row, "rate", None),
        "job_id": getattr(row, "job_id", None),
        "thumbnail_url": getattr(row, "thumbnail_url", None),
        "book_title": getattr(row, "book_title", None),
        "author_name": getattr(row, "author_name", None),
        "video_title": getattr(row, "video_title", None),
        "video_description": getattr(row, "video_description", None),
        "video_tags": getattr(row, "video_tags", None),
        "createdAt": getattr(row, "createdAt", None) or getattr(row, "created_at", None),
        "updatedAt": getattr(row, "updatedAt", None) or getattr(row, "updated_at", None),
    }


@router.post("", include_in_schema=False, dependencies=[Depends(auth_utils.get_current_admin_user)])
@router.post("/", dependencies=[Depends(auth_utils.get_current_admin_user)])
async def create_video(
    request: Request,
    book_id: Optional[str] = Form(None),
    chapter_start: int = Form(...),
    chapter_count: int = Form(...),
    cover_image: Optional[UploadFile] = File(None),
    cover_image_url: Optional[str] = Form(None),
    voice: str = Form("vi-VN-NamMinhNeural"),
    rate: str = Form("+0%"),
):
    if not book_id:
        raise HTTPException(status_code=400, detail="Missing book_id")
    book = await db_mod.client.book.find_unique(where={"id": book_id})
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    source_url = normalize_source_url(getattr(book, "source_url", "") or "")
    token = str(uuid4())
    cancel_event = __import__("asyncio").Event()
    return await create_video_from_source_url(
        request=request,
        token=token,
        book_url=source_url,
        chapter_start=chapter_start,
        chapter_count=chapter_count,
        cover_image=cover_image,
        cover_image_url=cover_image_url,
        voice=voice,
        rate=rate,
        cancel_event=cancel_event,
    )


@router.get("")
@router.get("/")
async def list_videos(book_url: Optional[str] = None):
    if book_url:
        normalized_book_url = normalize_source_url(book_url)
        rows = await db_mod.get_videos_by_book_url(normalized_book_url)
    else:
        rows = await db_mod.get_all_videos()

    videos = [_serialize_video_row(row) for row in rows or []]
    return {"success": True, "data": videos}


@router.delete("/{video_id}", dependencies=[Depends(auth_utils.get_current_admin_user)])
async def delete_video(video_id: str):
    row = await db_mod.get_video_by_id(video_id)
    if not row:
        raise HTTPException(status_code=404, detail="Video không tìm thấy")

    if isinstance(row, dict):
        video_url = row.get("video_url")
        job_id = row.get("job_id")
    else:
        video_url = getattr(row, "video_url", None)
        job_id = getattr(row, "job_id", None)

    if video_url and video_url.startswith("https://") and "supabase.co" in video_url:
        try:
            parts = video_url.split("/storage/v1/object/")
            if len(parts) > 1:
                object_path = parts[1].split("?", 1)[0]
                if object_path.startswith("public/"):
                    segments = object_path.split("/", 2)
                    object_name = segments[2] if len(segments) == 3 else object_path
                else:
                    segments = object_path.split("/", 1)
                    object_name = segments[1] if len(segments) > 1 else segments[0]

                await __import__("asyncio").to_thread(delete_file_from_supabase_storage, object_name)
        except Exception:
            logger.exception("Failed to delete Supabase object for video %s", video_id)

    try:
        from routes.crawl import _cleanup_generated_video_files
        _cleanup_generated_video_files(job_id or "")
    except Exception:
        logger.exception("Failed to cleanup generated files for job %s", job_id)

    deleted = await db_mod.delete_video(video_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Video không tìm thấy")
    try:
        if job_id:
            from routes.crawl import _set_video_progress
            _set_video_progress(job_id, "deleted", "Đã xóa video", video_id)
    except Exception:
        logger.exception("Failed to set VIDEO_PROGRESS for delete | video_id=%s job_id=%s", video_id, job_id)
    return {"success": True, "message": "Đã xóa video"}


@router.get("/{video_id}/youtube-auth", dependencies=[Depends(auth_utils.get_current_admin_user)])
async def youtube_auth_start(video_id: str):
    auth_url = build_oauth_authorization_url(state=video_id)
    return {"success": True, "data": {"auth_url": auth_url, "video_id": video_id}}


@router.post("/{video_id}/publish-youtube", dependencies=[Depends(auth_utils.get_current_admin_user)])
async def publish_video_to_youtube(video_id: str):
    video_row = await db_mod.get_video_by_id(video_id)
    if not video_row:
        raise HTTPException(status_code=404, detail="Video không tìm thấy")

    refresh_token = get_refresh_token()
    if not refresh_token:
        return {
            "success": True,
            "data": {
                "message": "Cần xác thực Google để đăng video lên YouTube",
                "auth_url": build_oauth_authorization_url(state=video_id),
            },
        }

    token_response = refresh_access_token(refresh_token)
    access_token = token_response.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Không thể lấy access token từ Google")

    video_url = None
    job_id = None
    try:
        if isinstance(video_row, dict):
            video_url = video_row.get("video_url") or video_row.get("videoUrl")
            job_id = video_row.get("job_id") or video_row.get("jobId")
        else:
            video_url = getattr(video_row, "video_url", None) or getattr(video_row, "videoUrl", None)
            job_id = getattr(video_row, "job_id", None) or getattr(video_row, "jobId", None)
            if not video_url and hasattr(video_row, "__dict__"):
                vid_dict = getattr(video_row, "__dict__", {})
                video_url = vid_dict.get("video_url") or vid_dict.get("videoUrl")
                job_id = job_id or vid_dict.get("job_id") or vid_dict.get("jobId")
    except Exception:
        logger.exception("Lỗi khi lấy video_url và job_id từ video_row")

    if not video_url:
        raise HTTPException(status_code=400, detail="Video chưa có URL để đăng lên YouTube")

    video_title = getattr(video_row, "video_title", None) or getattr(video_row, "book_title", None) or "Video truyện"
    video_description = getattr(video_row, "video_description", None) or "Video được tạo tự động"
    video_tags = getattr(video_row, "video_tags", None) or "truyện, video tự động"

    from routes.crawl import VIDEO_BASE_DIR, _set_video_progress
    upload_dir = VIDEO_BASE_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_video_path = upload_dir / f"{video_id}_youtube.mp4"

    try:
        if isinstance(video_url, str) and video_url.startswith("http"):
            downloaded_path = await __import__("asyncio").to_thread(download_remote_video, video_url, str(temp_video_path))
        else:
            raise HTTPException(status_code=400, detail="Video URL không hợp lệ để tải xuống")

        upload_result = await __import__("asyncio").to_thread(
            upload_video_to_youtube,
            access_token,
            video_title,
            video_description,
            video_tags,
            downloaded_path,
        )

        youtube_video_id = upload_result.get("id") or upload_result.get("videoId")
        try:
            if job_id:
                _set_video_progress(job_id, "published", "Đã đăng lên YouTube", str(youtube_video_id))
        except Exception:
            logger.exception("Failed to set VIDEO_PROGRESS for publish | video_id=%s job_id=%s", video_id, job_id)

        return {
            "success": True,
            "data": {
                "message": "Đã đăng video lên YouTube thành công",
                "youtube_video_id": youtube_video_id,
                "youtube_response": upload_result,
            },
        }
    finally:
        try:
            if temp_video_path.exists():
                temp_video_path.unlink(missing_ok=True)
        except Exception:
            logger.exception("Không thể xóa file tạm tải video cho YouTube | video_id=%s", video_id)
