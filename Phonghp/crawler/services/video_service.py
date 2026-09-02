import asyncio
import logging
from uuid import uuid4
from time import perf_counter
from pathlib import Path
from typing import Optional, Dict

from fastapi import Request, HTTPException, UploadFile

import database as db_mod
from services.video_metadata import build_video_publish_metadata
from supabase_storage import upload_video_to_supabase_storage
from video_generator import (
    ensure_output_directories,
    create_audio_from_text,
    create_video_from_image_and_audio,
    compose_image_with_chapter_text,
    create_placeholder_image,
    NGHITTS_VOICES,
)
from utils import normalize_source_url
from imageio_ffmpeg import get_ffmpeg_exe

logger = logging.getLogger(__name__)

VIDEO_BASE_DIR = Path(__file__).resolve().parent.parent / "static"
VIDEO_OUTPUT_DIR = VIDEO_BASE_DIR / "videos"
VIDEO_INPUT_DIR = VIDEO_OUTPUT_DIR / "inputs"
VIDEO_AUDIO_DIR = VIDEO_OUTPUT_DIR / "audio"


async def _build_video_image_path(upload_file: Optional[UploadFile], fallback_url: Optional[str], token: str) -> Path:
    ensure_output_directories(VIDEO_BASE_DIR)
    image_path = VIDEO_INPUT_DIR / f"{token}_{uuid4().hex}"
    if upload_file:
        suffix = Path(upload_file.filename).suffix.lower() or ".jpg"
        if suffix not in {".jpg", ".jpeg", ".png"}:
            raise HTTPException(status_code=400, detail="Ảnh chỉ hỗ trợ định dạng JPG hoặc PNG")
        image_path = image_path.with_suffix(suffix)
        content = await upload_file.read()
        image_path.write_bytes(content)
        return image_path

    if fallback_url:
        image_path = image_path.with_suffix(".jpg")
        try:
            import urllib.request

            def _download():
                req = urllib.request.Request(fallback_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    image_path.write_bytes(resp.read())

            await asyncio.to_thread(_download)
            return image_path
        except Exception:
            logger.exception("Failed to download fallback image %s", fallback_url)

    image_path = image_path.with_suffix(".jpg")
    await create_placeholder_image(image_path)
    return image_path


async def create_video_from_source_url(
    request: Request,
    token: str,
    book_url: str,
    chapter_start: int,
    chapter_count: int,
    cover_image: Optional[UploadFile],
    cover_image_url: Optional[str],
    voice: str,
    rate: str,
    cancel_event: Optional[asyncio.Event] = None,
) -> Dict:
    started_at = perf_counter()
    normalized_book_url = normalize_source_url(book_url)

    story_chapter_count = await db_mod.client.chapter.count(
        where={"book_source_url": normalized_book_url, "is_story_content": True}
    )

    if chapter_start < 1 or chapter_count < 1:
        raise HTTPException(status_code=400, detail="chapter_start và chapter_count phải > 0")
    last_index = chapter_start + chapter_count - 1
    if chapter_start > story_chapter_count or last_index > story_chapter_count:
        raise HTTPException(status_code=400, detail="Phạm vi chương không hợp lệ")

    try:
        chapters = await db_mod.client.chapter.find_many(
            where={"book_source_url": normalized_book_url, "is_story_content": True},
            order={"chapter_no": "asc"},
            skip=chapter_start - 1,
            take=chapter_count,
        )
    except Exception as exc:
        logger.exception("Lỗi khi lấy danh sách chương để tạo video")
        raise HTTPException(status_code=504, detail="Không thể đọc dữ liệu chương từ database") from exc

    if len(chapters or []) < chapter_count:
        raise HTTPException(status_code=400, detail="Không có đủ chương truyện có nội dung để tạo video")

    chapter_urls = []
    chapter_nos = []
    for chapter in chapters:
        chapter_url = getattr(chapter, "url", None) if not isinstance(chapter, dict) else chapter.get("url")
        chapter_no = getattr(chapter, "chapter_no", None) if not isinstance(chapter, dict) else chapter.get("chapter_no")
        if not chapter_url:
            raise HTTPException(status_code=400, detail="Chương không chứa URL")
        chapter_urls.append(chapter_url)
        if isinstance(chapter_no, int):
            chapter_nos.append(chapter_no)

    actual_chapter_start = min(chapter_nos) if chapter_nos else chapter_start
    actual_chapter_end = max(chapter_nos) if chapter_nos else chapter_start

    try:
        chapter_contents_by_url = await db_mod.get_chapter_contents_by_urls(chapter_urls)
    except Exception as exc:
        logger.exception("Lỗi khi lấy nội dung chương để tạo video")
        raise HTTPException(status_code=504, detail="Không thể đọc nội dung chương từ database") from exc

    contents = []
    for chapter in chapters:
        chapter_url = getattr(chapter, "url", None) if not isinstance(chapter, dict) else chapter.get("url")
        chapter_content = chapter_contents_by_url.get(chapter_url)
        if not chapter_content:
            raise HTTPException(status_code=400, detail=f"Chưa có nội dung cho chương {getattr(chapter, 'chapter_no', '?')}")
        contents.append(chapter_content)

    audio_text = "\n\n".join(contents)

    ensure_output_directories(VIDEO_BASE_DIR)
    if cancel_event is None:
        cancel_event = asyncio.Event()

    book = await db_mod.client.book.find_unique(where={"source_url": normalized_book_url})
    book_title = getattr(book, "title_vi", None) or "Video truyện"
    author_name = getattr(book, "author_vi", None)
    fallback_cover = getattr(book, "cover_url", None) if book else None

    publish_metadata = build_video_publish_metadata(
        book_title=book_title,
        author_name=author_name,
        chapter_start=chapter_start,
        chapter_count=chapter_count,
        story_chapter_start=chapter_start,
        story_chapter_end=chapter_start + chapter_count - 1,
        actual_chapter_start=actual_chapter_start,
        actual_chapter_end=actual_chapter_end,
    )

    chapter_range_text = publish_metadata.get("chapter_range_text") or (
        f"Chương {chapter_start}" if chapter_count == 1 else f"Chương {chapter_start} đến {chapter_start + chapter_count - 1}"
    )

    image_path = await _build_video_image_path(cover_image, cover_image_url or fallback_cover, token)
    composed_image_path = VIDEO_INPUT_DIR / f"{token}_{uuid4().hex}{image_path.suffix}"
    image_path = await compose_image_with_chapter_text(image_path, chapter_range_text, composed_image_path)

    suffix = ".wav" if voice in NGHITTS_VOICES else ".mp3"
    audio_path = VIDEO_AUDIO_DIR / f"{token}_{uuid4().hex}{suffix}"
    if cancel_event.is_set():
        raise HTTPException(status_code=499, detail="Đã hủy tạo video")
    await create_audio_from_text(audio_text, audio_path, voice, rate, job_id=token)

    output_path = VIDEO_OUTPUT_DIR / f"{token}_{uuid4().hex}.mp4"
    if cancel_event.is_set():
        raise HTTPException(status_code=499, detail="Đã hủy tạo video")
    await create_video_from_image_and_audio(image_path, audio_path, output_path)

    try:
        if audio_path.exists():
            audio_path.unlink(missing_ok=True)
    except Exception:
        logger.exception("Không thể xoá file audio tạm | token=%s audio_path=%s", token, audio_path)

    base_url = str(request.base_url).rstrip("/")
    fallback_video_url = f"{base_url}/static/videos/{output_path.name}"
    video_url = await upload_video_to_supabase_storage(output_path, f"videos/{output_path.name}", fallback_video_url)

    thumbnail_url = None
    try:
        thumbnail_path = VIDEO_BASE_DIR / "video-thumbnails" / f"{output_path.stem}.jpg"
        command = [
            get_ffmpeg_exe(),
            "-y",
            "-ss",
            "0",
            "-i",
            str(output_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(thumbnail_path),
        ]
        await asyncio.to_thread(__import__("subprocess").run, command, capture_output=True, text=True)
        if thumbnail_path.exists():
            thumbnail_url = f"{base_url}/static/video-thumbnails/{thumbnail_path.name}"
    except Exception:
        logger.exception("Không thể tạo thumbnail video | token=%s output=%s", token, output_path.name)
        thumbnail_url = cover_image_url or fallback_cover
        if not thumbnail_url and image_path:
            thumbnail_url = f"{base_url}/static/videos/inputs/{image_path.name}"

    saved_video = await db_mod.save_video(
        {
            "book_url": normalized_book_url,
            "video_url": video_url,
            "chapter_start": chapter_start,
            "chapter_count": chapter_count,
            "voice": voice,
            "rate": rate,
            "job_id": token,
            "bookId": getattr(book, "id", None) if book else None,
            "thumbnail_url": thumbnail_url,
            "book_title": book_title,
            "author_name": publish_metadata.get("author_name"),
            "video_title": publish_metadata.get("video_title"),
            "video_description": publish_metadata.get("video_description"),
            "video_tags": publish_metadata.get("video_tags"),
        }
    )

    return {
        "success": True,
        "data": {
            "video_url": video_url,
            "chapter_start": chapter_start,
            "chapter_count": chapter_count,
            "saved_video": saved_video,
        },
    }
