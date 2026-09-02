from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import auth as auth_utils
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import database as db_mod
import scraper as scr
import translator_utils as tr
import edge_tts
import re
import tempfile
from datetime import datetime
from contextlib import asynccontextmanager
from slugify import slugify
from utils import format_chapter_url, generate_slug
from video_generator import create_audio_from_text
try:
    import backend.logging_config as _lc
except Exception:
    pass
import logging
import os
logger = logging.getLogger(__name__)
from pathlib import Path
from routes.auth import router as auth_router
from routes.user import router as user_router
from routes.crawl import router as crawl_router, oauth_router, restore_jobs_from_db
from routes.video import router as video_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Hệ thống Convert đã sẵn sàng với 1.4 triệu cụm từ!")
    # Đảm bảo nạp từ điển vào RAM từ đây
    tr.translator.load_all_dicts()
    await db_mod.connect()
    await restore_jobs_from_db()
    yield
    try:
        await scr.close_browser()
    except Exception as e:
        logger.exception(f"⚠️ Lỗi khi đóng browser context: {e}")
    await db_mod.disconnect()
    logger.info("💤 Hệ thống đang đóng...")

app = FastAPI(lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.24.180:3000",
    "http://192.168.16.1:3000",
]
configured_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", ",".join(default_origins)).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "User-Agent", "DNT", "Cache-Control", "X-Mx-ReqToken", "Keep-Alive", "X-Requested-With", "If-Modified-Since", "Accept-Encoding", "Accept-Language"],
)

@app.get("/")
async def root():
    return {"success": True, "message": "FastAPI backend is running."}

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(oauth_router)
app.include_router(crawl_router)
app.include_router(video_router)

class TranslationRequest(BaseModel):
    url: str


class ManualChapterInput(BaseModel):
    title: str = ""
    title_vi: str = ""
    content: str = ""
    chapter_no: int = 1
    url: Optional[str] = None


class ManualBookCreateRequest(BaseModel):
    source_url: str = ""
    slug: str = ""
    title_vi: str = ""
    title_en: Optional[str] = None
    author_vi: Optional[str] = None
    description_vi: Optional[str] = None
    cover_url: Optional[str] = None
    chapters: list[ManualChapterInput] = []
    bulk_chapter_text: str = ""


class ManualChapterUpdateInput(BaseModel):
    id: Optional[str] = None
    title: str = ""
    title_vi: str = ""
    content: str = ""
    chapter_no: int = 1
    url: Optional[str] = None


class ManualBookUpdateRequest(BaseModel):
    source_url: str = ""
    slug: str = ""
    title_vi: str = ""
    title_en: Optional[str] = None
    author_vi: Optional[str] = None
    description_vi: Optional[str] = None
    cover_url: Optional[str] = None
    chapters: list[ManualChapterInput] = []
    existing_chapters: list[ManualChapterUpdateInput] = []
    removed_chapter_ids: list[str] = []
    bulk_chapter_text: str = ""


def _extract_title_from_bulk_line(line: str) -> tuple[Optional[str], str]:
    stripped = (line or "").strip()
    if not stripped:
        return None, ""

    match = re.match(r'^(?:chương|chapter)\s*[:.-]?\s*(\d+)?\s*[:.-]?\s*(.*)$', stripped, flags=re.IGNORECASE)
    if match:
        number, rest = match.groups()
        title = (rest or f"Chương {number}" if number else "").strip()
        if title:
            return title, rest.strip()
        if number:
            return f"Chương {number}", ""
        return stripped, ""

    match = re.match(r'^(\d+)\s*[:.-]?\s*(.*)$', stripped)
    if match:
        number, rest = match.groups()
        title = (rest or f"Chương {number}").strip()
        return title if title else f"Chương {number}", rest.strip()

    return None, stripped


def split_text_into_chapter_chunks(raw_text: str, max_chars: int = 1800, max_paragraphs: int = 7) -> list[list[str]]:
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not paragraphs:
        return [[text]]

    chunks: list[list[str]] = []
    current: list[str] = []
    current_chars = 0

    for paragraph in paragraphs:
        paragraph_chars = len(paragraph)
        if current and (current_chars + paragraph_chars > max_chars or len(current) >= max_paragraphs):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(paragraph)
        current_chars += paragraph_chars + 2

    if current:
        chunks.append(current)

    return chunks


def build_bulk_chapters_from_text(raw_text: str, start_chapter_no: int = 1) -> list[dict]:
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    lines = [line.rstrip() for line in text.split("\n")]
    built_blocks: list[dict] = []
    current_title: Optional[str] = None
    current_lines: list[str] = []

    def flush_block():
        nonlocal current_title, current_lines
        if not current_lines:
            return
        content = "\n".join(line.strip() for line in current_lines if line.strip()).strip()
        if not content:
            current_lines = []
            current_title = None
            return
        built_blocks.append({
            "title": current_title or f"Chương {len(built_blocks) + 1}",
            "content": content,
        })
        current_lines = []
        current_title = None

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            if current_title is not None and current_lines:
                current_lines.append("")
            continue

        heading, remainder = _extract_title_from_bulk_line(stripped)
        if heading and (current_title is not None or current_lines):
            flush_block()
            current_title = heading
            if remainder:
                current_lines.append(remainder)
            continue

        if heading and current_title is None and not current_lines:
            current_title = heading
            if remainder:
                current_lines.append(remainder)
            continue

        if current_title is None and not current_lines:
            current_lines.append(stripped)
            continue

        current_lines.append(stripped)

    flush_block()

    final_chapters: list[dict] = []
    if not built_blocks:
        paragraph_chunks = split_text_into_chapter_chunks(text)
        for index, chunk in enumerate(paragraph_chunks, start=start_chapter_no):
            content = "\n\n".join(chunk)
            final_chapters.append({
                "title": f"Chương {index}",
                "title_vi": f"Chương {index}",
                "content": content,
                "chapter_no": index,
            })
        return final_chapters

    for index, block in enumerate(built_blocks, start=start_chapter_no):
        sub_chunks = split_text_into_chapter_chunks(block["content"])
        if len(sub_chunks) <= 1:
            final_chapters.append({
                "title": block["title"],
                "title_vi": block["title"],
                "content": block["content"],
                "chapter_no": index,
            })
            continue

        for sub_index, sub_chunk in enumerate(sub_chunks, start=1):
            final_chapters.append({
                "title": f"{block['title']} - Phần {sub_index}",
                "title_vi": f"{block['title']} - Phần {sub_index}",
                "content": "\n\n".join(sub_chunk),
                "chapter_no": index + sub_index - 1,
            })

    if final_chapters:
        for idx, item in enumerate(final_chapters, start=start_chapter_no):
            item["chapter_no"] = idx
            item["title_vi"] = item["title_vi"] or item["title"]
            item["title"] = item["title"] or item["title_vi"]

    return final_chapters


def build_unique_chapter_url(base_url: str, chapter_title: str, existing_urls: Optional[set[str]] = None) -> str:
    normalized_base = (base_url or "https://manual.local").rstrip("/")
    safe_title = (chapter_title or "chapter").strip() or "chapter"
    slug = slugify(safe_title, lowercase=True, separator="-") or "chapter"
    candidate = f"{normalized_base}/chapter/{slug}"
    if not existing_urls:
        return candidate

    suffix = 2
    final_candidate = candidate
    while final_candidate in existing_urls:
        final_candidate = f"{normalized_base}/chapter/{slug}-{suffix}"
        suffix += 1
    return final_candidate


@app.post("/books/manual")
async def api_create_manual_book(
    request: ManualBookCreateRequest,
    current_user: object = Depends(auth_utils.get_current_admin_user),
):
    if not request.title_vi or not request.title_vi.strip():
        raise HTTPException(status_code=400, detail="Tên truyện không được để trống")

    title_vi = request.title_vi.strip()
    slug_value = (request.slug or generate_slug(title_vi)).strip() or generate_slug(title_vi)
    source_url = (request.source_url or slug_value).strip()
    if not source_url.startswith("http://") and not source_url.startswith("https://"):
        source_url = f"https://manual.local/{slug_value}"

    existing_book = await db_mod.client.book.find_unique(where={"source_url": source_url})
    if existing_book:
        raise HTTPException(status_code=409, detail="Sách với source_url này đã tồn tại")

    existing_slug = await db_mod.client.book.find_unique(where={"slug": slug_value})
    if existing_slug:
        slug_value = f"{slug_value}-{int(datetime.now().timestamp())}"
        source_url = f"https://manual.local/{slug_value}"

    book_payload = {
        "source_url": source_url,
        "slug": slug_value,
        "title_vi": title_vi,
        "title_en": request.title_en.strip() if request.title_en else None,
        "author_vi": request.author_vi.strip() if request.author_vi else None,
        "description_vi": request.description_vi.strip() if request.description_vi else None,
        "cover_url": request.cover_url.strip() if request.cover_url else None,
        "status": "manual",
        "chapters_count": 0,
        "views_count": 0,
    }

    saved_book = await db_mod.save_book(book_payload)
    created_chapters = []
    manual_chapters = request.chapters or []

    if request.bulk_chapter_text and request.bulk_chapter_text.strip():
        auto_generated_chapters = build_bulk_chapters_from_text(request.bulk_chapter_text, start_chapter_no=len(request.chapters) + 1)
        manual_chapters.extend([
            ManualChapterInput(
                title=item.get("title") or item.get("title_vi") or f"Chương {index + 1}",
                title_vi=item.get("title_vi") or item.get("title") or f"Chương {index + 1}",
                content=item.get("content") or "",
                chapter_no=item.get("chapter_no") or (index + 1),
                url=None,
            )
            for index, item in enumerate(auto_generated_chapters)
        ])

    if not manual_chapters:
        default_chapter_title = "Chương 1"
        content = ""
        chapter_slug = slugify(default_chapter_title, lowercase=True, separator="-") or "chapter"
        chapter_url = f"{source_url}/chapter/{chapter_slug}"
        created_chapter = await db_mod.client.chapter.upsert(
            where={"url": chapter_url},
            data={
                "create": {
                    "book_source_url": source_url,
                    "title": default_chapter_title,
                    "title_vi": default_chapter_title,
                    "url": chapter_url,
                    "slug": chapter_slug,
                    "chapter_no": 1,
                    "access": "regular",
                    "content": content,
                    "is_story_content": True,
                },
                "update": {
                    "title": default_chapter_title,
                    "title_vi": default_chapter_title,
                    "content": content,
                    "is_story_content": True,
                },
            },
        )
        created_chapters.append(created_chapter)
    else:
        for index, chapter in enumerate(manual_chapters, start=1):
            chapter_title = (chapter.title_vi or chapter.title or f"Chương {index}").strip() or f"Chương {index}"
            chapter_content = (chapter.content or "").strip()
            chapter_no = chapter.chapter_no or index
            chapter_slug = slugify(chapter_title, lowercase=True, separator="-") or "chapter"
            chapter_url = (chapter.url or f"{source_url}/chapter/{chapter_slug}").strip()
            if not chapter_url.startswith("http://") and not chapter_url.startswith("https://"):
                chapter_url = f"{source_url}/chapter/{chapter_slug}"

            created_chapter = await db_mod.client.chapter.upsert(
                where={"url": chapter_url},
                data={
                    "create": {
                        "book_source_url": source_url,
                        "title": chapter_title,
                        "title_vi": chapter_title,
                        "url": chapter_url,
                        "slug": chapter_slug,
                        "chapter_no": chapter_no,
                        "access": "regular",
                        "content": chapter_content,
                        "is_story_content": True,
                    },
                    "update": {
                        "title": chapter_title,
                        "title_vi": chapter_title,
                        "content": chapter_content,
                        "is_story_content": True,
                        "chapter_no": chapter_no,
                    },
                },
            )
            created_chapters.append(created_chapter)

    total_chapters = await db_mod.client.chapter.count(where={"book_source_url": source_url})
    await db_mod.client.book.update(
        where={"source_url": source_url},
        data={"chapters_count": total_chapters, "updatedAt": datetime.now()},
    )

    return {
        "success": True,
        "data": {
            "book": saved_book,
            "chapters": created_chapters,
            "chapters_count": total_chapters,
        },
    }


@app.get("/books/{book_id}/chapters")
async def api_get_book_chapters(
    book_id: str,
    current_user: object = Depends(auth_utils.get_current_admin_user),
):
    book = await db_mod.client.book.find_unique(where={"id": book_id})
    if not book:
        raise HTTPException(status_code=404, detail="Không tìm thấy sách")

    source_url = getattr(book, "source_url", None) if not isinstance(book, dict) else book.get("source_url")
    chapters = await db_mod.client.chapter.find_many(
        where={"book_source_url": source_url},
        order={"chapter_no": "asc"},
    )
    return {
        "success": True,
        "data": [db_mod.serialize_chapter_row(chapter) for chapter in chapters or []],
    }


@app.patch("/chapters/{chapter_id}")
async def api_update_manual_chapter(
    chapter_id: str,
    request: ManualChapterUpdateInput,
    current_user: object = Depends(auth_utils.get_current_admin_user),
):
    chapter = await db_mod.client.chapter.find_unique(where={"id": chapter_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương")

    source_url = getattr(chapter, "book_source_url", None) if not isinstance(chapter, dict) else chapter.get("book_source_url")
    title = (request.title_vi or request.title or getattr(chapter, "title_vi", None) or getattr(chapter, "title", None) or f"Chương {getattr(chapter, 'chapter_no', 1)}").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Tên chương không được để trống")

    chapter_no = request.chapter_no or getattr(chapter, "chapter_no", 1) or 1
    generated_slug = slugify(title, lowercase=True, separator="-") or "chapter"
    chapter_url = (request.url or getattr(chapter, "url", None) or f"{source_url}/chapter/{generated_slug}").strip()
    if not chapter_url.startswith("http://") and not chapter_url.startswith("https://"):
        chapter_url = f"{source_url}/chapter/{generated_slug}"

    existing_by_url = await db_mod.client.chapter.find_unique(where={"url": chapter_url})
    if existing_by_url and existing_by_url.id != chapter_id:
        chapter_url = build_unique_chapter_url(source_url, title, {
            getattr(item, "url", None) if not isinstance(item, dict) else item.get("url")
            for item in await db_mod.client.chapter.find_many(where={"book_source_url": source_url}) or []
            if (getattr(item, "url", None) if not isinstance(item, dict) else item.get("url"))
        })

    updated_chapter = await db_mod.client.chapter.update(
        where={"id": chapter_id},
        data={
            "title": title,
            "title_vi": title,
            "url": chapter_url,
            "slug": generated_slug,
            "chapter_no": chapter_no,
            "content": request.content.strip() if request.content else getattr(chapter, "content", None) or "",
            "is_story_content": True,
            "updatedAt": datetime.now(),
        },
    )

    total_chapters = await db_mod.client.chapter.count(where={"book_source_url": source_url})
    await db_mod.client.book.update(
        where={"source_url": source_url},
        data={"chapters_count": total_chapters, "updatedAt": datetime.now()},
    )
    return {"success": True, "data": db_mod.serialize_chapter_row(updated_chapter)}


@app.delete("/chapters/{chapter_id}")
async def api_delete_manual_chapter(
    chapter_id: str,
    current_user: object = Depends(auth_utils.get_current_admin_user),
):
    chapter = await db_mod.client.chapter.find_unique(where={"id": chapter_id})
    if not chapter:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương")

    source_url = getattr(chapter, "book_source_url", None) if not isinstance(chapter, dict) else chapter.get("book_source_url")
    await db_mod.client.chapter.delete(where={"id": chapter_id})
    total_chapters = await db_mod.client.chapter.count(where={"book_source_url": source_url})
    await db_mod.client.book.update(
        where={"source_url": source_url},
        data={"chapters_count": total_chapters, "updatedAt": datetime.now()},
    )
    return {"success": True, "data": {"deleted_id": chapter_id, "chapters_count": total_chapters}}


@app.patch("/books/{book_id}")
async def api_update_manual_book(
    book_id: str,
    request: ManualBookUpdateRequest,
    current_user: object = Depends(auth_utils.get_current_admin_user),
):
    if not book_id:
        raise HTTPException(status_code=400, detail="Thiếu ID sách")

    existing_book = await db_mod.client.book.find_unique(where={"id": book_id})
    if not existing_book:
        raise HTTPException(status_code=404, detail="Không tìm thấy sách để sửa")

    existing_source_url = getattr(existing_book, "source_url", None) if not isinstance(existing_book, dict) else existing_book.get("source_url")
    title_vi = (request.title_vi or getattr(existing_book, "title_vi", "") or "").strip()
    if not title_vi:
        raise HTTPException(status_code=400, detail="Tên truyện không được để trống")

    slug_value = (request.slug or getattr(existing_book, "slug", "") or generate_slug(title_vi)).strip() or generate_slug(title_vi)
    source_url = (request.source_url or existing_source_url or slug_value).strip()
    if not source_url.startswith("http://") and not source_url.startswith("https://"):
        source_url = f"https://manual.local/{slug_value}"

    duplicate_book = await db_mod.client.book.find_unique(where={"source_url": source_url})
    if duplicate_book and duplicate_book.id != book_id:
        raise HTTPException(status_code=409, detail="Sách với source_url này đã tồn tại")

    duplicate_slug = await db_mod.client.book.find_unique(where={"slug": slug_value})
    if duplicate_slug and duplicate_slug.id != book_id:
        slug_value = f"{slug_value}-{int(datetime.now().timestamp())}"
        source_url = f"https://manual.local/{slug_value}"

    book_payload = {
        "source_url": source_url,
        "slug": slug_value,
        "title_vi": title_vi,
        "title_en": (request.title_en or getattr(existing_book, "title_en", None) or None).strip() if (request.title_en or getattr(existing_book, "title_en", None)) else None,
        "author_vi": (request.author_vi or getattr(existing_book, "author_vi", None) or None).strip() if (request.author_vi or getattr(existing_book, "author_vi", None)) else None,
        "description_vi": (request.description_vi or getattr(existing_book, "description_vi", None) or None).strip() if (request.description_vi or getattr(existing_book, "description_vi", None)) else None,
        "cover_url": (request.cover_url or getattr(existing_book, "cover_url", None) or None).strip() if (request.cover_url or getattr(existing_book, "cover_url", None)) else None,
        "status": getattr(existing_book, "status", None) or "manual",
        "views_count": getattr(existing_book, "views_count", 0) or 0,
        "updatedAt": datetime.now(),
    }

    if existing_source_url and existing_source_url != source_url:
        await db_mod.client.chapter.update_many(
            where={"book_source_url": existing_source_url},
            data={"book_source_url": source_url},
        )

    saved_book = await db_mod.client.book.update(
        where={"id": book_id},
        data=book_payload,
    )

    for chapter_id in request.removed_chapter_ids or []:
        if not chapter_id:
            continue
        try:
            await db_mod.client.chapter.delete(where={"id": chapter_id})
        except Exception:
            continue

    rows = await db_mod.client.chapter.find_many(where={"book_source_url": source_url})
    used_urls = {
        getattr(row, "url", None) if not isinstance(row, dict) else row.get("url")
        for row in rows or []
        if (getattr(row, "url", None) if not isinstance(row, dict) else row.get("url"))
    }
    next_chapter_no = max((getattr(row, "chapter_no", 0) if not isinstance(row, dict) else row.get("chapter_no", 0) for row in rows or []), default=0)

    for chapter_index, chapter in enumerate(request.existing_chapters or [], start=1):
        chapter_id = chapter.id
        if not chapter_id:
            continue
        existing = await db_mod.client.chapter.find_unique(where={"id": chapter_id})
        if not existing:
            continue
        resolved_chapter_no = chapter.chapter_no or getattr(existing, "chapter_no", 1) or 1
        chapter_title = (chapter.title_vi or chapter.title or getattr(existing, "title_vi", None) or getattr(existing, "title", None) or f"Chương {resolved_chapter_no}").strip() or f"Chương {resolved_chapter_no}"
        chapter_content = (chapter.content or getattr(existing, "content", None) or "").strip()
        chapter_no = resolved_chapter_no
        generated_slug = slugify(chapter_title, lowercase=True, separator="-") or "chapter"
        chapter_url = (chapter.url or getattr(existing, "url", None) or f"{source_url}/chapter/{generated_slug}").strip()
        if not chapter_url.startswith("http://") and not chapter_url.startswith("https://"):
            chapter_url = f"{source_url}/chapter/{generated_slug}"
        if chapter_url in used_urls and chapter_url != getattr(existing, "url", None):
            chapter_url = build_unique_chapter_url(source_url, chapter_title, used_urls)
        used_urls.discard(getattr(existing, "url", None))
        used_urls.add(chapter_url)
        await db_mod.client.chapter.update(
            where={"id": chapter_id},
            data={
                "title": chapter_title,
                "title_vi": chapter_title,
                "url": chapter_url,
                "slug": generated_slug,
                "chapter_no": chapter_no,
                "content": chapter_content,
                "is_story_content": True,
                "updatedAt": datetime.now(),
            },
        )

    new_bulk_chapters = []
    if request.bulk_chapter_text and request.bulk_chapter_text.strip():
        new_bulk_chapters = build_bulk_chapters_from_text(request.bulk_chapter_text, start_chapter_no=next_chapter_no + 1)

    combined_new_chapters = list(request.chapters or []) + [
        ManualChapterInput(
            title=item["title"],
            title_vi=item["title_vi"],
            content=item["content"],
            chapter_no=item["chapter_no"],
            url=None,
        )
        for item in new_bulk_chapters
    ]

    for chapter_index, chapter in enumerate(combined_new_chapters, start=1):
        chapter_title = chapter.title_vi or chapter.title or ""
        chapter_title = chapter_title.strip() or f"Chương {next_chapter_no + chapter_index}"
        if not (chapter.title or chapter.title_vi or chapter.content):
            continue
        if not chapter.content.strip() and not (chapter.title or chapter.title_vi):
            continue

        chapter_no = chapter.chapter_no or (next_chapter_no + chapter_index)
        chapter_url = (chapter.url or "").strip()
        generated_slug = slugify(chapter_title, lowercase=True, separator="-") or "chapter"
        if not chapter_url:
            chapter_url = build_unique_chapter_url(source_url, chapter_title, used_urls)
        elif not chapter_url.startswith("http://") and not chapter_url.startswith("https://"):
            chapter_url = f"{source_url}/chapter/{generated_slug}"
        if chapter_url in used_urls:
            chapter_url = build_unique_chapter_url(source_url, chapter_title, used_urls)
        used_urls.add(chapter_url)

        chapter_content = (chapter.content or "").strip()
        await db_mod.client.chapter.upsert(
            where={"url": chapter_url},
            data={
                "create": {
                    "book_source_url": source_url,
                    "title": chapter_title,
                    "title_vi": chapter_title,
                    "url": chapter_url,
                    "slug": generated_slug,
                    "chapter_no": chapter_no,
                    "access": "regular",
                    "content": chapter_content,
                    "is_story_content": True,
                },
                "update": {
                    "title": chapter_title,
                    "title_vi": chapter_title,
                    "content": chapter_content,
                    "chapter_no": chapter_no,
                    "is_story_content": True,
                },
            },
        )

    total_chapters = await db_mod.client.chapter.count(where={"book_source_url": source_url})
    await db_mod.client.book.update(
        where={"id": book_id},
        data={"chapters_count": total_chapters, "updatedAt": datetime.now()},
    )

    return {
        "success": True,
        "data": {
            "book": saved_book,
            "chapters_count": total_chapters,
        },
    }


@app.get("/books")
async def api_list_books(
    slug: Optional[str] = None,
    source_url: Optional[str] = None,
    id: Optional[str] = None,
    limit: int = 12,
    skip: int = 0,
    q: Optional[str] = None,
):
    try:
        if slug:
            book = await db_mod.client.book.find_unique(where={"slug": slug})
            if not book:
                return {"success": True, "data": []}
            source_url_value = getattr(book, "source_url", None) if not isinstance(book, dict) else book["source_url"]
            chapters_count = await db_mod.client.chapter.count(where={"book_source_url": source_url_value})
            return {"success": True, "data": [db_mod.serialize_book_row(book, chapters_count)]}

        if source_url:
            book = await db_mod.client.book.find_unique(where={"source_url": source_url})
            if not book:
                return {"success": True, "data": []}
            source_url_value = getattr(book, "source_url", None) if not isinstance(book, dict) else book["source_url"]
            chapters_count = await db_mod.client.chapter.count(where={"book_source_url": source_url_value})
            return {"success": True, "data": [db_mod.serialize_book_row(book, chapters_count)]}

        if id:
            book = await db_mod.client.book.find_unique(where={"id": id})
            if not book:
                return {"success": True, "data": []}
            source_url_value = getattr(book, "source_url", None) if not isinstance(book, dict) else book["source_url"]
            chapters_count = await db_mod.client.chapter.count(where={"book_source_url": source_url_value})
            return {"success": True, "data": [db_mod.serialize_book_row(book, chapters_count)]}

        where_clause = {}
        if q and q.strip():
            where_clause = {
                "OR": [
                    {"title_vi": {"contains": q, "mode": "insensitive"}},
                    {"title_en": {"contains": q, "mode": "insensitive"}},
                ]
            }

        books = await db_mod.client.book.find_many(
            where=where_clause,
            order={"updatedAt": "desc"},
            skip=skip,
            take=limit,
        )

        payload = []
        for book in books:
            source_url_value = getattr(book, "source_url", None) if not isinstance(book, dict) else book["source_url"]
            chapters_count = 0
            if source_url_value:
                try:
                    chapters_count = await db_mod.client.chapter.count(where={"book_source_url": source_url_value})
                except Exception:
                    chapters_count = 0
            payload.append(db_mod.serialize_book_row(book, chapters_count))

        total = await db_mod.client.book.count(where=where_clause)
        return {"success": True, "data": payload, "total": total, "limit": limit, "skip": skip}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/books/search")
async def api_search_books(q: str = Query(...)):
    return await api_list_books(q=q, limit=10, skip=0)


@app.get("/chapters")
async def api_list_chapters(book: Optional[str] = None):
    if not book:
        raise HTTPException(status_code=400, detail="Missing book parameter")

    try:
        chapters = await db_mod.client.chapter.find_many(
            where={"book_source_url": book},
            order={"chapter_no": "asc"},
        )
        return {"success": True, "data": [db_mod.serialize_chapter_row(ch) for ch in chapters]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- CÁC API ENDPOINTS GIỮ NGUYÊN ---

# --- PHẦN SỬA ĐỔI CHO ĐỌC TRUYỆN & TTS ---

def build_paragraphs_from_raw_content(raw_content: str) -> list[str]:
    raw_lines = [p.strip() for p in raw_content.split('\n') if p.strip()]
    translated_paragraphs = []
    for line in raw_lines:
        translated = tr.translate_text(line)
        if not re.match(r'^\d{4}-\d{2}-\d{2}', translated):
            translated_paragraphs.append(translated)
    return translated_paragraphs


def remove_saved_notice(raw_content: str) -> str:
    if not raw_content:
        return raw_content

    cleaned = re.sub(r'@?Bạn đang đọc bản lưu trong hệ thống', '', raw_content)
    cleaned = re.sub(r'\n{2,}', '\n', cleaned)
    return cleaned.strip()


async def resolve_chapter_content(url: str) -> tuple[list[str], str]:
    cached_content = await db_mod.get_chapter_content_by_url(url)
    if cached_content:
        cleaned = remove_saved_notice(cached_content)
        return cleaned.splitlines(), "db"

    if "sangtacviet" in url:
        raw_content = await scr.scrape_stv_chapter_content(url)
    else:
        raw_content = await scr.scrape_chapter_content(url)

    if not raw_content:
        raise HTTPException(status_code=400, detail="Không lấy được nội dung.")

    raw_content = remove_saved_notice(raw_content)
    if "sangtacviet" in url:
        paragraphs = [p.strip() for p in raw_content.splitlines() if p.strip()]
    else:
        paragraphs = build_paragraphs_from_raw_content(raw_content)

    chapter = await db_mod.get_chapter_by_url(url)
    chapter_title = None
    if chapter:
        chapter_title = getattr(chapter, "title_vi", None) or getattr(chapter, "title", None) or getattr(chapter, "title_en", None)
        if chapter_title:
            chapter_title = str(chapter_title).strip()

    # Keep the original behavior: title is included in the stored chapter text for the reading flow.
    await db_mod.save_chapter_content(url, paragraphs, chapter_title=chapter_title)
    return paragraphs, "crawler"


@app.post("/get-chapter-content")
async def api_get_content(request: TranslationRequest):
    try:
        paragraphs, source = await resolve_chapter_content(request.url)
        return {
            "success": True,
            "paragraphs": paragraphs,
            "source": source,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stream-chapter-audio")
async def api_stream_audio(
    text: str = Query(...), 
    rate: str = Query("+0%"), 
    voice: str = Query("vi-VN-NamMinhNeural")
):
    valid_voices = {"vi-VN-NamMinhNeural", "vi-VN-HoaiMyNeural", "nghitts:ngochuyennew"}
    if voice not in valid_voices:
        logger.warning("Unsupported voice requested: %s. Falling back to vi-VN-NamMinhNeural", voice)
        voice = "vi-VN-NamMinhNeural"

    rate_clean = rate.replace(" ", "+").strip()
    if not rate_clean.startswith("+") and not rate_clean.startswith("-"):
        rate_clean = "+" + rate_clean

    try:
        if voice == "nghitts:ngochuyennew":
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                await create_audio_from_text(text, tmp_path, voice=voice, rate=rate_clean, job_id="stream")
                wav_bytes = tmp_path.read_bytes()
            finally:
                tmp_path.unlink(missing_ok=True)
            return StreamingResponse(iter([wav_bytes]), media_type="audio/wav")

        communicate = edge_tts.Communicate(text, voice, rate=rate_clean)

        async def audio_generator():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]

        return StreamingResponse(audio_generator(), media_type="audio/mpeg")
    except Exception as e:
        logger.exception("❌ Lỗi TTS với voice=%s: %s", voice, e)
        raise HTTPException(status_code=500, detail=str(e))

# --- Cập nhật endpoint /get-basic-info ---
@app.post("/get-basic-info")
async def api_get_info(request: TranslationRequest):
    logger.info(f"🔍 Đang lấy thông tin: {request.url}")
    
    if "sangtacviet.com" in request.url.lower():
        # Dùng logic mới cho STV (Không cần dịch qua tr.translate_text)
        raw = await scr.scrape_stv_basic_info(request.url)
        if not raw: raise HTTPException(status_code=400, detail="Lỗi nguồn STV")
        
        book_data = {
            "source_url": request.url,
            "title_vi": raw.get('title_vi'),
            "author_vi": raw.get('author_vi'),
            "description_vi": raw.get('description_vi'),
            "cover_url": raw.get('cover_url', ''),
            "status": "info_only",
            "updated_at": datetime.now().isoformat(),
            "slug": generate_slug(raw.get('title_vi'))
        }
    else:
        # GIỮ NGUYÊN LOGIC CŨ CỦA PHONG CHO SHUBA
        raw = await scr.scrape_basic_info(request.url)
        if not raw: raise HTTPException(status_code=400, detail="Không lấy được dữ liệu.")
        title_translated = tr.translate_text(raw.get('title_cn', ''))
        book_data = {
            "source_url": request.url,
            "title_vi": title_translated,
            "author_vi": tr.translate_text(raw.get('author_cn', '')),
            "description_vi": tr.translate_text(raw.get('description_cn', ''), limit=1000),
            "cover_url": raw.get('cover_url', ''),
            "status": "info_only",
            "updated_at": datetime.now().isoformat(),
            "slug": generate_slug(title_translated)
        }
    
    await db_mod.save_book(book_data)
    return {"success": True, "data": book_data}

# --- Cập nhật endpoint /get-chapters ---
@app.post("/get-chapters")
async def api_get_chapters(request: TranslationRequest):
    if "sangtacviet.com" in request.url.lower():
        raw_chapters = await scr.scrape_stv_chapters(request.url)
        is_stv = True
    else:
        chapter_url = format_chapter_url(request.url)
        raw_chapters = await scr.scrape_chapters(chapter_url)
        is_stv = False

    if not raw_chapters:
        raise HTTPException(status_code=400, detail="Không lấy được danh sách chương.")
    
    try:
        translated_chapters = []
        for index, ch in enumerate(raw_chapters):
            # Nếu là STV thì lấy title_vi trực tiếp, nếu không thì dịch title_cn
            const_title = ch.get('title_vi') if is_stv else tr.translate_text(ch.get('title_cn', ''))
            title_final = const_title or ch.get('title_vi') or ch.get('title') or f"Chương {index + 1}"
            translated_chapters.append({
                "chapter_no": index + 1,
                "title_vi": title_final,
                "url": ch.get('url', ''),
                "slug": generate_slug(title_final),
                "access": ch.get('access') if is_stv else "regular",
            })

        await db_mod.save_chapters(request.url, translated_chapters, replace_existing=True)
        return {"success": True, "total": len(translated_chapters), "chapters": translated_chapters}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/get-qidian-rank")
async def api_get_qidian_rank(
    type: str = "yuepiao", 
    chn: int = -1,          # Đổi mặc định thành -1 để khớp với mục "Tất Cả" mới cập nhật
    page: int = 1,          # Bổ sung tham số phân trang page
    year: str = None,       # Bổ sung bộ lọc năm động
    month: str = None       # Bổ sung bộ lọc tháng động
):
    """
    Endpoint xử lý dữ liệu In-Memory (RAM):
    - Nhận tham số loại BXH (type), ID Thể loại (chn), phân trang (page) và thời gian (year, month).
    - Gọi hàm cào đa năng từ scraper.py để lấy mảng chữ Hán thô theo thời gian chỉ định.
    - Chạy qua bộ dịch thuật Aho-Corasick có sẵn trong RAM để Việt hóa.
    - Định dạng lại tên trường (camelCase) và bọc dữ liệu chuẩn theo thiết kế Frontend.
    """
    try:
        # 1. Gọi hàm cào từ scraper.py, chuyển tiếp toàn bộ tham số bộ lọc thời gian và phân trang
        raw_data = await scr.scrape_qidian_ranking(
            category_id=type, 
            chn_id=chn, 
            page=page, 
            year=year, 
            month=month
        )
        
        if not raw_data:
            return {
                "success": False, 
                "data": {"data": []}, 
                "message": "Không tìm thấy hoặc lỗi cào dữ liệu từ nguồn gốc."
            }

        translated_results = []
        
        for book in raw_data:
            # 2. Đưa qua bộ dịch thuật Aho-Corasick đã được map sẵn trong RAM từ lúc khởi động hệ thống
            title_vi = tr.translate_text(book['title_cn'])
            author_vi = tr.translate_text(book['author_cn'])
            category_vi = tr.translate_text(book['category_cn'])
            desc_vi = tr.translate_text(book['desc_cn'], limit=500)  # Giới hạn độ dài mô tả cho gọn UI
            
            # 3. Tạo cấu trúc key phẳng, chuẩn camelCase khớp 100% với file page.tsx của Next.js
            translated_results.append({
                "rank": getattr(book, 'rank', None) if not isinstance(book, dict) else book['rank'],
                "title": title_vi if title_vi else (getattr(book, 'title_cn', None) if not isinstance(book, dict) else book['title_cn']),
                "title_cn": getattr(book, 'title_cn', None) if not isinstance(book, dict) else book['title_cn'],
                "author": author_vi if author_vi else "Ẩn danh",
                "category": category_vi if category_vi else "Chưa phân loại",
                "intro": desc_vi if desc_vi else "Chưa có tóm tắt cốt truyện...",
                "coverUrl": getattr(book, 'cover_url', None) if not isinstance(book, dict) else book['cover_url'],
                "sourceUrl": getattr(book, 'source_url', None) if not isinstance(book, dict) else book['source_url'],
                "slug": generate_slug(title_vi if title_vi else (getattr(book, 'title_cn', None) if not isinstance(book, dict) else book['title_cn']))
            })

        # 4. Bọc đúng 2 lớp .data.data để tương thích hoàn toàn với logic check bên Next.js
        return {
            "success": True,
            "data": {
                "data": translated_results
            }
        }

    except Exception as e:
        logger.exception(f"🔥 Lỗi nghiêm trọng tại API BXH Qidian: {e}")
        raise HTTPException(status_code=500, detail=str(e))