import asyncio
import logging
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Dict, List, Optional
from uuid import uuid4
from utils import normalize_source_url

logger = logging.getLogger(__name__)


def _parse_datetime(value: Optional[str]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _get_field(row: dict, field: str, default=None):
    if isinstance(row, dict):
        return row.get(field, default)
    return getattr(row, field, default)

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import auth as auth_utils
import database as db_mod
import scraper as scr
from crawl_queue import CrawlChapterItem, CrawlJobData, CrawlJobStatus, CrawlQueueManager, CrawlChapterStatus
from crawl_worker import crawl_job_worker
from services.crawl_service import submit_crawl as service_submit_crawl
from services.video_metadata import build_video_publish_metadata
from services.youtube_token_store import save_refresh_token
from services.youtube_uploader import exchange_code_for_tokens
from supabase_storage import upload_video_to_supabase_storage
from video_generator import ensure_output_directories, create_audio_from_text, create_video_from_image_and_audio, create_placeholder_image, compose_image_with_chapter_text, ALL_TTS_VOICES, NGHITTS_VOICES, DEFAULT_VOICE, DEFAULT_TTS_RATE
from imageio_ffmpeg import get_ffmpeg_exe

router = APIRouter(
    prefix="/crawl",
    tags=["crawl"],
    dependencies=[Depends(auth_utils.get_current_admin_user)],
)

# OAuth callback router (no admin dependency) - Google will call this without Authorization header
oauth_router = APIRouter(prefix="/crawl", tags=["crawl-oauth"])

queue_manager = CrawlQueueManager()
_background_tasks: Dict[str, asyncio.Task] = {}


def _build_chapter_range(chapter_start: int, chapter_count: int, total_chapters: int) -> tuple[int, int]:
    if chapter_start < 1 or chapter_count < 1:
        raise ValueError("chapter_start và chapter_count phải lớn hơn 0")

    last_index = chapter_start + chapter_count - 1
    if chapter_start > total_chapters or last_index > total_chapters:
        raise ValueError(f"Phạm vi chương không hợp lệ: {chapter_start}-{last_index} trên tổng {total_chapters}")

    return chapter_start, last_index


async def _resolve_job_book_metadata(job: CrawlJobData) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    try:
        book = await db_mod.client.book.find_unique(where={"source_url": normalize_source_url(job.book_url)})
    except Exception:
        book = None

    return (
        getattr(book, "title_vi", None),
        getattr(book, "author_vi", None),
        getattr(book, "description_vi", None),
        getattr(book, "cover_url", None),
    )


class CrawlSubmitRequest(BaseModel):
    url: str


class CrawlJobSummary(BaseModel):
    job_id: str
    book_url: str
    book_id: Optional[str]
    title_vi: Optional[str]
    author_vi: Optional[str]
    description_vi: Optional[str]
    cover_url: Optional[str]
    status: CrawlJobStatus
    total_chapters: int
    crawled_chapters: int
    current_chapter_index: int
    current_chapter_title: Optional[str]
    current_chapter_url: Optional[str]
    remaining_chapters: int
    total_nonvip_chapters: int
    processed_nonvip_chapters: int
    crawled_nonvip_chapters: int
    remaining_nonvip_chapters: int
    created_at: str
    updated_at: str
    chapters: List[Dict]


async def _build_video_image_path(upload_file: Optional[UploadFile], fallback_url: Optional[str], job_id: str) -> Path:
    _ensure_video_dirs()
    image_path = VIDEO_INPUT_DIR / f"{job_id}_{uuid4().hex}"
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
            await _download_image(fallback_url, image_path)
            return image_path
        except Exception:
            pass

    image_path = image_path.with_suffix(".jpg")
    await create_placeholder_image(image_path)
    return image_path


async def _get_db_chapter_count(book_url: str) -> int:
    normalized_book_url = normalize_source_url(book_url)

    cached_entry = JOB_CHAPTER_CACHE.get(normalized_book_url)
    if cached_entry and (perf_counter() - cached_entry[0]) < JOB_CHAPTER_CACHE_TTL_SECONDS:
        return cached_entry[2]

    try:
        book = await db_mod.client.book.find_unique(where={"source_url": normalized_book_url})
        if book:
            chapters_count = getattr(book, "chapters_count", None)
            if chapters_count is None:
                chapters_count = getattr(book, "chaptersCount", None)
            if chapters_count is not None:
                total_chapters = int(chapters_count)
                JOB_CHAPTER_CACHE[normalized_book_url] = (perf_counter(), [], total_chapters, 0)
                return total_chapters
    except Exception as exc:
        logger.warning("Failed to read chapters_count from Book for %s: %s", normalized_book_url, exc)

    _, total_chapters, _ = await _load_book_chapter_summary(book_url)
    return total_chapters


async def _load_book_chapter_summary(book_url: str) -> tuple[list[CrawlChapterItem], int, int]:
    normalized_book_url = normalize_source_url(book_url)
    cached_entry = JOB_CHAPTER_CACHE.get(normalized_book_url)
    if cached_entry and (perf_counter() - cached_entry[0]) < JOB_CHAPTER_CACHE_TTL_SECONDS:
        return cached_entry[1], cached_entry[2], cached_entry[3]

    db_chapters = []

    # Fallback only for detailed chapter loading when we truly need the chapter list.
    # The jobs endpoint now uses Book.chapters_count and does not need this path on the hot path.
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            db_chapters = await db_mod.client.chapter.find_many(
                where={"book_source_url": normalized_book_url},
                order={"chapter_no": "asc"},
            )
            break
        except Exception as exc:
            logger.warning("Attempt %s/%s: failed to load chapters for %s: %s", attempt, max_retries, normalized_book_url, exc)
            if attempt < max_retries:
                await __import__("asyncio").sleep(1)
            else:
                logger.exception("Giving up loading chapters for %s after %s attempts", normalized_book_url, max_retries)
                db_chapters = []

    loaded_chapters: list[CrawlChapterItem] = []
    for chapter_row in db_chapters:
        access = getattr(chapter_row, "access", "regular") if not isinstance(chapter_row, dict) else chapter_row.get("access", "regular")
        content = getattr(chapter_row, "content", None) if not isinstance(chapter_row, dict) else chapter_row.get("content")

        if access == "vip":
            status = CrawlChapterStatus.skipped
        elif content:
            status = CrawlChapterStatus.crawled
        else:
            status = CrawlChapterStatus.pending

        loaded_chapters.append(
            CrawlChapterItem(
                chapter_no=getattr(chapter_row, "chapter_no", 0) if not isinstance(chapter_row, dict) else chapter_row.get("chapter_no", 0),
                title_vi=getattr(chapter_row, "title_vi", "") if not isinstance(chapter_row, dict) else chapter_row.get("title_vi", ""),
                url=getattr(chapter_row, "url", "") if not isinstance(chapter_row, dict) else chapter_row.get("url", ""),
                access=access,
                status=status,
            )
        )

    total_chapters = len(loaded_chapters)
    crawled_chapters = sum(1 for item in loaded_chapters if item.status == CrawlChapterStatus.crawled)
    JOB_CHAPTER_CACHE[normalized_book_url] = (perf_counter(), loaded_chapters, total_chapters, crawled_chapters)
    return loaded_chapters, total_chapters, crawled_chapters


async def _load_job_chapters(job: CrawlJobData) -> None:
    if job.chapters:
        return

    loaded_chapters, total_chapters, crawled_chapters = await _load_book_chapter_summary(job.book_url)
    job.chapters = loaded_chapters
    job.total_chapters = total_chapters
    job.crawled_chapters = crawled_chapters


async def _job_to_payload(job: CrawlJobData, db_chapter_count: Optional[int] = None, include_chapters: bool = True) -> Dict:
    book_title, author_vi, description_vi, cover_url = await _resolve_job_book_metadata(job)

    if include_chapters:
        await _load_job_chapters(job)

    crawled_chapters = job.crawled_chapters
    if job.status == CrawlJobStatus.completed and job.total_chapters > 0:
        crawled_chapters = job.total_chapters

    remaining_chapters = queue_manager.get_remaining_chapters(job.job_id)
    if job.status == CrawlJobStatus.completed:
        remaining_chapters = 0

    if job.chapters:
        total_nonvip = sum(1 for chapter in job.chapters if chapter.access != "vip")
        processed_nonvip = sum(1 for chapter in job.chapters if chapter.access != "vip" and chapter.status != CrawlChapterStatus.pending)
        crawled_nonvip = sum(1 for chapter in job.chapters if chapter.access != "vip" and chapter.status == CrawlChapterStatus.crawled)
        remaining_nonvip = max(0, total_nonvip - processed_nonvip)
    else:
        fallback_total = int(db_chapter_count if db_chapter_count is not None else job.total_chapters or 0)
        total_nonvip = fallback_total
        processed_nonvip = min(int(job.crawled_chapters or 0), fallback_total)
        crawled_nonvip = processed_nonvip
        remaining_nonvip = max(0, fallback_total - processed_nonvip)

    latest_chapter_event = None
    latest_chapter_event_type = "info"
    if job.chapters:
        ordered = sorted(job.chapters, key=lambda chapter: chapter.chapter_no)
        for chapter in reversed(ordered):
            status = chapter.status
            if status == CrawlChapterStatus.crawled:
                latest_chapter_event = f"Đã crawl xong chương {chapter.chapter_no}: {chapter.title_vi or 'Không tên'}"
                latest_chapter_event_type = "success"
                break
            if status == CrawlChapterStatus.failed:
                latest_chapter_event = f"Lỗi chương {chapter.chapter_no}: {chapter.title_vi or 'Không tên'}"
                latest_chapter_event_type = "error"
                break
        if latest_chapter_event is None and job.current_chapter_title:
            latest_chapter_event = f"Đang crawl: {job.current_chapter_title}"
            latest_chapter_event_type = "running"

    payload = {
        "job_id": job.job_id,
        "book_url": job.book_url,
        "book_id": getattr(job, "book_id", None),
        "title_vi": book_title,
        "author_vi": author_vi,
        "description_vi": description_vi,
        "cover_url": cover_url,
        "status": job.status.value,
        "total_chapters": job.total_chapters,
        "crawled_chapters": crawled_chapters,
        "current_chapter_index": job.current_chapter_index,
        "current_chapter_title": job.current_chapter_title,
        "current_chapter_url": job.current_chapter_url,
        "remaining_chapters": remaining_chapters,
        "db_chapter_count": db_chapter_count if db_chapter_count is not None else 0,
        "db_book_exists": bool(db_chapter_count and db_chapter_count > 0),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "total_nonvip_chapters": total_nonvip,
        "processed_nonvip_chapters": processed_nonvip,
        "crawled_nonvip_chapters": crawled_nonvip,
        "remaining_nonvip_chapters": remaining_nonvip,
        "latest_chapter_event": latest_chapter_event,
        "latest_chapter_event_type": latest_chapter_event_type,
        "chapters": [],
    }

    if include_chapters:
        payload["chapters"] = [
            {
                "chapter_no": chapter.chapter_no,
                "title_vi": chapter.title_vi,
                "url": chapter.url,
                "access": getattr(chapter, "access", "regular"),
                "status": chapter.status.value,
            }
            for chapter in job.chapters
        ]

    return payload


VIDEO_BASE_DIR = Path(__file__).resolve().parent.parent / "static"
VIDEO_OUTPUT_DIR = VIDEO_BASE_DIR / "videos"
VIDEO_INPUT_DIR = VIDEO_OUTPUT_DIR / "inputs"
VIDEO_AUDIO_DIR = VIDEO_OUTPUT_DIR / "audio"
VIDEO_CANCEL_TOKENS: Dict[str, asyncio.Event] = {}
VIDEO_PROGRESS: Dict[str, Dict[str, str]] = {}
# Cache chapter summaries per book URL for a short window to reduce repeated Prisma queries.
JOB_CHAPTER_CACHE: Dict[str, tuple[float, list[CrawlChapterItem], int, int]] = {}
JOB_CHAPTER_CACHE_TTL_SECONDS = 30
# Keep concurrent chapter loading low to avoid exhausting the Prisma/Postgres pool.
JOBS_DB_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(2)


def _set_video_progress(job_id: str, step: str, message: str, detail: Optional[str] = None) -> None:
    payload: Dict[str, str] = {"step": step, "message": message}
    if detail is not None:
        payload["detail"] = detail
    VIDEO_PROGRESS[job_id] = payload
    logger.info("Video progress | job_id=%s step=%s message=%s detail=%s", job_id, step, message, detail)


async def _download_image(source_url: str, dest: Path) -> None:
    def download() -> None:
        request = urllib.request.Request(
            source_url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; web-truyen-convert/1.0)",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            content = response.read()
        dest.write_bytes(content)

    await asyncio.to_thread(download)


async def cancel_video_generation(job_id: str) -> dict:
    event = VIDEO_CANCEL_TOKENS.pop(job_id, None)
    if event is not None:
        event.set()

    _set_video_progress(job_id, "cancelled", "Đã hủy tạo video", "Quá trình tạo video bị dừng")
    _cleanup_generated_video_files(job_id)
    return {"success": True, "data": {"cancelled": True}}


def _ensure_video_dirs() -> None:
    ensure_output_directories(VIDEO_BASE_DIR)
    VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


async def _create_video_thumbnail(video_path: Path, thumbnail_path: Path) -> Path:
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        get_ffmpeg_exe(),
        "-y",
        "-ss",
        "0",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(thumbnail_path),
    ]
    result = await asyncio.to_thread(
        subprocess.run,
        command,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not thumbnail_path.exists():
        raise RuntimeError(f"Không thể tạo thumbnail video: {result.stderr}")
    return thumbnail_path


def _cleanup_generated_video_files(job_id: str, base_dir: Optional[Path] = None) -> None:
    target_dir = base_dir or VIDEO_BASE_DIR
    videos_dir = target_dir / "videos"
    if not videos_dir.exists():
        return

    for root, _, files in os.walk(videos_dir):
        for filename in files:
            if not filename.startswith(job_id):
                continue
            file_path = Path(root) / filename
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                logger.exception("Không thể xoá file video tạm | job_id=%s path=%s", job_id, file_path)


def _cleanup_uploaded_assets(job_id: str, video_url: str, fallback_url: str, base_dir: Optional[Path] = None) -> bool:
    if not video_url or not video_url.startswith("https://"):
        return False
    if "supabase.co" not in video_url:
        return False

    target_dir = base_dir or VIDEO_BASE_DIR
    videos_dir = target_dir / "videos"
    if not videos_dir.exists():
        return False

    removed_any = False
    for root, _, files in os.walk(videos_dir):
        for filename in files:
            if not filename.startswith(job_id):
                continue
            file_path = Path(root) / filename
            try:
                file_path.unlink(missing_ok=True)
                removed_any = True
                logger.info("Đã xoá file tạm sau khi upload Supabase | job_id=%s path=%s", job_id, file_path)
            except Exception:
                logger.exception("Không thể xoá file tạm sau khi upload Supabase | job_id=%s path=%s", job_id, file_path)

    return removed_any


def _ensure_background_task(job_id: str) -> None:
    existing = _background_tasks.get(job_id)
    if existing and not existing.done():
        return

    async def _runner():
        job = queue_manager.get_job(job_id)
        if not job:
            return
        logger.info("Starting background crawl worker | job_id=%s", job_id)
        try:
            await crawl_job_worker(job, queue_manager)
        except Exception as exc:
            logger.exception("Background crawl worker crashed | job_id=%s error=%s", job_id, exc)

    def _on_done(task: asyncio.Task, jid: str = job_id) -> None:
        if task.cancelled():
            return
        job = queue_manager.get_job(jid)
        if job and job.status == CrawlJobStatus.queued:
            _ensure_background_task(jid)

    task = asyncio.create_task(_runner())
    task.add_done_callback(_on_done)
    _background_tasks[job_id] = task


def _job_to_db_dict(job: CrawlJobData) -> dict:
    return {
        "job_id": job.job_id,
        "book_url": job.book_url,
        "status": job.status.value,
        "total_chapters": job.total_chapters,
        "crawled_chapters": job.crawled_chapters,
        "current_chapter_index": job.current_chapter_index,
        "current_chapter_title": job.current_chapter_title,
        "current_chapter_url": job.current_chapter_url,
        "createdAt": job.created_at,
        "updatedAt": job.updated_at,
        "bookId": job.book_id,
    }


def _row_to_job(row: dict) -> CrawlJobData:
    status_value = getattr(row, "status", None)
    try:
        status = CrawlJobStatus(status_value)
    except ValueError:
        status = CrawlJobStatus.queued

    created_at = _parse_datetime(getattr(row, "createdAt", None) or getattr(row, "created_at", None))
    updated_at = _parse_datetime(getattr(row, "updatedAt", None) or getattr(row, "updated_at", None))

    return CrawlJobData(
        job_id=_get_field(row, "job_id", ""),
        book_url=_get_field(row, "book_url", ""),
        created_at=created_at,
        updated_at=updated_at,
        status=status,
        total_chapters=getattr(row, "total_chapters", 0),
        crawled_chapters=getattr(row, "crawled_chapters", 0),
        current_chapter_index=getattr(row, "current_chapter_index", 0),
        current_chapter_title=getattr(row, "current_chapter_title", None),
        current_chapter_url=getattr(row, "current_chapter_url", None),
        book_id=getattr(row, "bookId", None) or getattr(row, "book_id", None),
        chapters=[],
    )


async def _persist_job(job: CrawlJobData) -> None:
    if not job:
        return
    try:
        await db_mod.save_crawl_job(_job_to_db_dict(job))
    except Exception as exc:
        logger.warning("Skipping DB persistence for job %s due to DB error: %s", job.job_id, exc)


async def _load_job_into_memory(job_id: str) -> Optional[CrawlJobData]:
    existing = queue_manager.get_job(job_id)
    if existing:
        return existing

    row = await db_mod.get_crawl_job_by_id(job_id)
    if not row:
        return None

    job = _row_to_job(row)
    queue_manager.restore_job(job)
    return job


async def restore_jobs_from_db() -> None:
    try:
        rows = await db_mod.get_crawl_jobs()
    except Exception as exc:
        logger.warning("Skipping crawl job restore from DB because DB is unavailable: %s", exc)
        return

    for row in rows:
        job = _row_to_job(row)
        if job.status == CrawlJobStatus.running:
            job.status = CrawlJobStatus.paused
            job.updated_at = datetime.utcnow()
        queue_manager.restore_job(job)
        if job.status == CrawlJobStatus.queued:
            _ensure_background_task(job.job_id)
        if job.status == CrawlJobStatus.running:
            try:
                await db_mod.update_crawl_job(job.job_id, _job_to_db_dict(job))
            except Exception as update_exc:
                logger.warning("Failed to update paused job %s in DB: %s", job.job_id, update_exc)


@router.post("/submit")
async def submit_crawl(request: CrawlSubmitRequest):
    raw_url = request.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="URL không được để trống")
    if "sangtacviet.com" not in raw_url.lower():
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ URL từ sangtacviet.com")

    try:
        job = await service_submit_crawl(raw_url, queue_manager)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _ensure_background_task(job.job_id)
    db_chapter_count = await _get_db_chapter_count(job.book_url)
    return {"success": True, "data": await _job_to_payload(job, db_chapter_count=db_chapter_count)}


@router.get("/check")
async def check_crawl_in_db(url: str):
    normalized_url = normalize_source_url(url)
    book = await db_mod.client.book.find_unique(where={"source_url": normalized_url})
    if not book:
        return {"success": True, "data": None}

    chapters = await db_mod.client.chapter.find_many(
        where={"book_source_url": normalized_url},
        order={"chapter_no": "asc"},
    )

    return {
        "success": True,
        "data": {
            "book": db_mod.serialize_book_row(book, len(chapters)),
            "chapters": [db_mod.serialize_chapter_row(ch) for ch in chapters],
        },
    }


@router.post("/jobs/{job_id}/video")
async def create_crawl_video(
    request: Request,
    job_id: str,
    chapter_start: int = Form(...),
    chapter_count: int = Form(...),
    cover_image: Optional[UploadFile] = File(None),
    cover_image_url: Optional[str] = Form(None),
    voice: str = Form(DEFAULT_VOICE),
    rate: str = Form(DEFAULT_TTS_RATE),
):
    # Wrap existing job-based create into service-backed create_video_from_source_url
    job = queue_manager.get_job(job_id) or await _load_job_into_memory(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job không tìm thấy")

    normalized_book_url = normalize_source_url(job.book_url)
    # use existing job_id as token so progress/cancel remain compatible
    cancel_event = __import__("asyncio").Event()
    VIDEO_CANCEL_TOKENS[job_id] = cancel_event
    # delegate to shared service
    from services.video_service import create_video_from_source_url

    return await create_video_from_source_url(
        request=request,
        token=job_id,
        book_url=normalized_book_url,
        chapter_start=chapter_start,
        chapter_count=chapter_count,
        cover_image=cover_image,
        cover_image_url=cover_image_url,
        voice=voice,
        rate=rate,
        cancel_event=cancel_event,
    )

    chapter_urls = []
    chapter_nos = []
    for chapter in chapter_slice:
        chapter_url = getattr(chapter, "url", None) if not isinstance(chapter, dict) else chapter.get("url")
        chapter_no = getattr(chapter, "chapter_no", None) if not isinstance(chapter, dict) else chapter.get("chapter_no")
        if not chapter_url:
            raise HTTPException(status_code=400, detail="Chương không chứa URL")
        chapter_urls.append(chapter_url)
        if isinstance(chapter_no, int):
            chapter_nos.append(chapter_no)

    actual_chapter_start = min(chapter_nos) if chapter_nos else chapter_start
    actual_chapter_end = max(chapter_nos) if chapter_nos else chapter_start

    _set_video_progress(job_id, "fetch_content", "Đang lấy nội dung từng chương", f"{len(chapter_slice)} chương")
    content_fetch_started = perf_counter()
    try:
        chapter_contents_by_url = await db_mod.get_chapter_contents_by_urls(chapter_urls)
    except Exception as exc:
        logger.exception("Lỗi khi lấy nội dung chương để tạo video")
        raise HTTPException(status_code=504, detail="Không thể đọc nội dung chương từ database") from exc

    logger.info(
        "Đã lấy nội dung chương | job_id=%s chapter_count=%s duration_ms=%.2f at=%s",
        job_id,
        len(chapter_slice),
        (perf_counter() - content_fetch_started) * 1000,
        datetime.now().strftime("%H:%M:%S.%f")[:-3],
    )

    contents = []
    for chapter in chapter_slice:
        chapter_url = getattr(chapter, "url", None) if not isinstance(chapter, dict) else chapter.get("url")
        chapter_content = chapter_contents_by_url.get(chapter_url)
        if not chapter_content:
            raise HTTPException(status_code=400, detail=f"Chưa có nội dung cho chương {chapter.chapter_no}")
        contents.append(chapter_content)

    audio_text = "\n\n".join(contents)
    _ensure_video_dirs()
    cancel_event = asyncio.Event()
    VIDEO_CANCEL_TOKENS[job_id] = cancel_event
    _set_video_progress(job_id, "prepare_assets", "Đang chuẩn bị thư mục và ảnh bìa", "Tạo file ảnh nền cho video")

    book = await db_mod.client.book.find_unique(where={"source_url": normalized_book_url})
    cover_url = getattr(book, "cover_url", None) if book else None
    book_title = getattr(book, "title_vi", None) or "Video truyện"
    author_name = getattr(book, "author_vi", None)
    cover_url = getattr(book, "cover_url", None) if book else None

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

    image_path = await _build_video_image_path(cover_image, cover_image_url or cover_url, job_id)
    composed_image_path = VIDEO_INPUT_DIR / f"{job_id}_{uuid4().hex}{image_path.suffix}"
    image_path = await compose_image_with_chapter_text(image_path, chapter_range_text, composed_image_path)

    suffix = ".wav" if voice in NGHITTS_VOICES else ".mp3"
    audio_path = VIDEO_AUDIO_DIR / f"{job_id}_{uuid4().hex}{suffix}"
    _set_video_progress(job_id, "generate_audio", "Đang tạo file audio bằng TTS", f"voice={voice} rate={rate}")
    audio_started = perf_counter()
    try:
        if cancel_event.is_set():
            raise HTTPException(status_code=499, detail="Đã hủy tạo video")
        await create_audio_from_text(audio_text, audio_path, voice, rate, job_id=job_id)
        logger.info(
            "Đã tạo audio | job_id=%s audio_path=%s duration_ms=%.2f at=%s",
            job_id,
            audio_path.name,
            (perf_counter() - audio_started) * 1000,
            datetime.now().strftime("%H:%M:%S.%f")[:-3],
        )

        output_path = VIDEO_OUTPUT_DIR / f"{job_id}_{uuid4().hex}.mp4"
        _set_video_progress(job_id, "generate_video", "Đang render video từ ảnh và audio", output_path.name)
        video_started = perf_counter()
        if cancel_event.is_set():
            raise HTTPException(status_code=499, detail="Đã hủy tạo video")
        await create_video_from_image_and_audio(image_path, audio_path, output_path)
        logger.info(
            "Đã tạo video file | job_id=%s output_path=%s duration_ms=%.2f at=%s",
            job_id,
            output_path.name,
            (perf_counter() - video_started) * 1000,
            datetime.now().strftime("%H:%M:%S.%f")[:-3],
        )

        if audio_path.exists():
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                logger.exception("Không thể xoá file audio tạm | job_id=%s audio_path=%s", job_id, audio_path)

        VIDEO_CANCEL_TOKENS.pop(job_id, None)

        base_url = str(request.base_url).rstrip("/")
        fallback_video_url = f"{base_url}/static/videos/{output_path.name}"
        video_url = await upload_video_to_supabase_storage(
            output_path,
            f"videos/{output_path.name}",
            fallback_video_url,
        )
        thumbnail_path = VIDEO_BASE_DIR / "video-thumbnails" / f"{output_path.stem}.jpg"
        try:
            await _create_video_thumbnail(output_path, thumbnail_path)
            thumbnail_url = f"{base_url}/static/video-thumbnails/{thumbnail_path.name}"
        except Exception:
            logger.exception("Không thể tạo thumbnail video | job_id=%s output=%s", job_id, output_path.name)
            thumbnail_url = cover_image_url or cover_url
            if not thumbnail_url and image_path:
                thumbnail_url = f"{base_url}/static/videos/inputs/{image_path.name}"
        _cleanup_uploaded_assets(job_id, video_url, fallback_video_url)
        book_id = getattr(book, "id", None) if book else None

        _set_video_progress(job_id, "save_metadata", "Đang lưu metadata và kết nối video", output_path.name)
        save_started = perf_counter()
        saved_video = await db_mod.save_video(
            {
                "book_url": normalized_book_url,
                "video_url": video_url,
                "chapter_start": chapter_start,
                "chapter_count": chapter_count,
                "voice": voice,
                "rate": rate,
                "job_id": job_id,
                "bookId": book_id,
                "thumbnail_url": thumbnail_url,
                "book_title": book_title,
                "author_name": publish_metadata.get("author_name"),
                "video_title": publish_metadata.get("video_title"),
                "video_description": publish_metadata.get("video_description"),
                "video_tags": publish_metadata.get("video_tags"),
            }
        )
        logger.info(
            "Đã lưu metadata video | job_id=%s video_id=%s duration_ms=%.2f at=%s",
            job_id,
            saved_video.get("id") if isinstance(saved_video, dict) else None,
            (perf_counter() - save_started) * 1000,
            datetime.now().strftime("%H:%M:%S.%f")[:-3],
        )

        logger.info(
            "Hoàn tất tạo video | job_id=%s duration_ms=%.2f at=%s",
            job_id,
            (perf_counter() - started_at) * 1000,
            datetime.now().strftime("%H:%M:%S.%f")[:-3],
        )
        _set_video_progress(job_id, "done", "Hoàn tất tạo video", video_url)

        return {
            "success": True,
            "data": {
                "video_url": video_url,
                "chapter_start": chapter_start,
                "chapter_count": chapter_count,
            },
        }
    except HTTPException as exc:
        _cleanup_generated_video_files(job_id)
        VIDEO_CANCEL_TOKENS.pop(job_id, None)
        if exc.status_code == 499:
            _set_video_progress(job_id, "cancelled", "Đã hủy tạo video", "Bị dừng bởi người dùng")
        else:
            _set_video_progress(job_id, "failed", "Tạo video thất bại", str(exc.detail))
        raise
    except Exception as exc:
        logger.exception("Lỗi khi tạo video | job_id=%s", job_id)
        _cleanup_generated_video_files(job_id)
        VIDEO_CANCEL_TOKENS.pop(job_id, None)
        _set_video_progress(job_id, "failed", "Tạo video thất bại", "Lỗi không xác định trong quá trình tạo video")
        raise HTTPException(status_code=500, detail="Lỗi khi tạo video") from exc


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


@router.post("/jobs/{job_id}/video/cancel")
async def cancel_video_generation_route(job_id: str):
    return await cancel_video_generation(job_id)


@router.get("/jobs/{job_id}/video/progress")
async def get_video_progress_route(job_id: str):
    progress = VIDEO_PROGRESS.get(job_id)
    if progress is None:
        return {"success": True, "data": {"step": "idle", "message": "Chưa bắt đầu"}}
    return {"success": True, "data": progress}


@oauth_router.get("/youtube/callback", response_class=HTMLResponse)
async def youtube_oauth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth code")

    tokens = exchange_code_for_tokens(code)
    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")

    if not refresh_token or not access_token:
        raise HTTPException(status_code=400, detail="Failed to obtain YouTube tokens")

    save_refresh_token(refresh_token)
    html = f"""
<html>
  <head>
    <title>Google OAuth thành công</title>
    <style>body{{background:#040404;color:#f8f8f2;font-family:system-ui, sans-serif;padding:32px;}}</style>
  </head>
  <body>
    <h1>Google OAuth thành công</h1>
    <p>Bạn có thể đóng tab này và quay lại ứng dụng.</p>
    <p>State: {state or 'n/a'}</p>
  </body>
</html>
"""
    return HTMLResponse(content=html, status_code=200)


@router.get("/jobs")
async def list_crawl_jobs():
    in_memory_jobs = queue_manager.get_all_jobs()
    if in_memory_jobs:
        jobs = []
        for job in in_memory_jobs:
            db_chapter_count = int(getattr(job, "total_chapters", 0) or 0)
            try:
                payload = await _job_to_payload(job, db_chapter_count=db_chapter_count, include_chapters=False)
            except Exception as exc:
                logger.exception("Error building in-memory job payload: %s", exc)
                continue
            jobs.append(payload)
        return {"success": True, "data": jobs}

    try:
        rows = await db_mod.get_crawl_jobs()
    except Exception as exc:
        logger.warning("Falling back to empty crawl job list because DB is unavailable: %s", exc)
        return {"success": True, "data": []}

    db_job_ids = set()
    for row in rows:
        job_id = getattr(row, "job_id", None)
        if not job_id:
            continue
        db_job_ids.add(job_id)
        if queue_manager.get_job(job_id):
            continue
        job = _row_to_job(row)
        queue_manager.restore_job(job)

    for job in list(queue_manager.get_all_jobs()):
        if job.job_id not in db_job_ids:
            queue_manager.remove_job(job.job_id)

    jobs = []
    for job in queue_manager.get_all_jobs():
        db_chapter_count = int(getattr(job, "total_chapters", 0) or 0)
        try:
            payload = await _job_to_payload(job, db_chapter_count=db_chapter_count, include_chapters=False)
        except Exception as exc:
            logger.exception("Error building job payload from DB rows: %s", exc)
            continue
        jobs.append(payload)

    return {"success": True, "data": jobs}


@router.post("/jobs/{job_id}/pause")
async def pause_crawl_job(job_id: str):
    job = queue_manager.pause_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job không tìm thấy")
    await _persist_job(job)
    return {"success": True, "data": await _job_to_payload(job)}


@router.post("/jobs/{job_id}/resume")
async def resume_crawl_job(job_id: str):
    job = queue_manager.resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job không tìm thấy")
    await _persist_job(job)
    _ensure_background_task(job_id)
    return {"success": True, "data": await _job_to_payload(job)}


@router.delete("/jobs/{job_id}")
async def delete_crawl_job(job_id: str):
    job = queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job không tìm thấy")
    queue_manager.remove_job(job_id)
    await db_mod.delete_crawl_job(job_id)
    return {"success": True, "message": "Đã xóa job"}


@router.delete("/books/{book_id}")
async def delete_crawl_book(book_id: str):
    if not book_id:
        raise HTTPException(status_code=400, detail="Book ID không được để trống")

    deleted_book = await db_mod.delete_book_and_related(book_id)
    if not deleted_book:
        raise HTTPException(status_code=404, detail="Book không tìm thấy")

    # Remove any in-memory crawl job for this book if present
    for job in list(queue_manager.get_all_jobs()):
        if getattr(job, "book_id", None) == book_id or job.book_url == getattr(deleted_book, "source_url", None):
            queue_manager.remove_job(job.job_id)

    return {"success": True, "message": "Đã xóa sách và dữ liệu liên quan"}
