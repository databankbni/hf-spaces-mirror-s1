import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from utils import generate_slug, normalize_source_url

import db as db_mod
import scraper as scr
from crawl_queue import CrawlChapterItem, CrawlJobData, CrawlJobStatus, CrawlChapterStatus, CrawlQueueManager

logger = logging.getLogger(__name__)

# Delay ước lượng để chậm nhẹ hơn, giảm nguy cơ bị CAPTCHA/anti-bot
# nhưng vẫn giữ browser context sống xuyên suốt job crawl.
DELAY_SECONDS_PER_CHAPTER = 20


def _get_book_title(title_vi: Optional[str], title_cn: Optional[str], fallback: str) -> str:
    return title_vi or title_cn or fallback


def _build_book_data(source_url: str, title_vi: Optional[str], title_cn: Optional[str], author_vi: Optional[str], description_vi: Optional[str], cover_url: Optional[str], status: str = "info_only") -> dict:
    title = _get_book_title(title_vi, title_cn, "Truyện từ SangTacViet")
    return {
        "source_url": source_url,
        "title_vi": title,
        "author_vi": author_vi,
        "description_vi": description_vi,
        "cover_url": cover_url or "",
        "status": status,
        "slug": generate_slug(title),
    }


def _get_chapter_title(raw: dict, index: int) -> str:
    return raw.get("title_vi") or raw.get("title_cn") or f"Chương {index}"


def _build_chapter_data(raw: dict, index: int) -> dict:
    title_vi = _get_chapter_title(raw, index)
    access = raw.get("access") or "regular"
    return {
        "chapter_no": index,
        "title_vi": title_vi,
        "url": raw.get("url", ""),
        "slug": generate_slug(title_vi),
        "access": access,
    }


def _crawl_job_to_db_dict(job: CrawlJobData) -> dict:
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
        "bookId": getattr(job, "book_id", None),
    }


async def persist_crawl_job(job: CrawlJobData) -> None:
    if not job:
        return
    try:
        await db_mod.save_crawl_job(_crawl_job_to_db_dict(job))
    except Exception as exc:
        logger.warning("Skipping crawl job persistence for %s because DB is unavailable: %s", job.job_id, exc)


async def save_book_info(job: CrawlJobData, raw_info: Optional[dict]):
    if not job:
        return

    raw_info = raw_info or {}
    try:
        existing_book = await db_mod.client.book.find_unique(where={"source_url": job.book_url})
    except Exception:
        existing_book = None

    if not raw_info and existing_book:
        return

    title_vi = raw_info.get("title_vi") or (getattr(existing_book, "title_vi", None) if existing_book else None) or "Truyện từ SangTacViet"
    author_vi = raw_info.get("author_vi") or (getattr(existing_book, "author_vi", None) if existing_book else None)
    description_vi = raw_info.get("description_vi") or (getattr(existing_book, "description_vi", None) if existing_book else None)
    cover_url = raw_info.get("cover_url") or (getattr(existing_book, "cover_url", None) if existing_book else None)

    try:
        await db_mod.save_book(_build_book_data(
            source_url=job.book_url,
            title_vi=title_vi,
            title_cn=None,
            author_vi=author_vi,
            description_vi=description_vi,
            cover_url=cover_url,
        ))
    except Exception as exc:
        logger.warning("Skipping book persistence for job %s because DB is unavailable: %s", job.job_id, exc)


async def save_chapter_index(job: CrawlJobData, raw_chapters: list[dict]):
    if not raw_chapters:
        return

    chapter_items = []
    chapter_batch = []
    for index, raw in enumerate(raw_chapters, start=1):
        chapter_data = _build_chapter_data(raw, index)
        chapter_items.append(
            CrawlChapterItem(chapter_no=chapter_data["chapter_no"], title_vi=chapter_data["title_vi"], url=chapter_data["url"], access=chapter_data["access"])
        )
        chapter_batch.append(chapter_data)

    return chapter_items, chapter_batch


async def crawl_job_worker(job: CrawlJobData, manager: CrawlQueueManager) -> None:
    try:
        if job.status == CrawlJobStatus.paused:
            return

        job.status = CrawlJobStatus.running
        job.updated_at = datetime.now(timezone.utc)
        await persist_crawl_job(job)

        raw_info = await scr.scrape_stv_basic_info(job.book_url)
        await save_book_info(job, raw_info)

        raw_chapters = await scr.scrape_stv_chapters(job.book_url)
        if not raw_chapters:
            manager.fail_job(job.job_id)
            await persist_crawl_job(job)
            return

        chapter_items, chapter_batch = await save_chapter_index(job, raw_chapters)

        manager.add_chapters(job.job_id, chapter_items)
        await persist_crawl_job(job)

        try:
            await db_mod.save_chapters(job.book_url, chapter_batch)
        except Exception as exc:
            logger.warning("Skipping chapter index persistence for job %s because DB is unavailable: %s", job.job_id, exc)

        for index, chapter in enumerate(job.chapters, start=1):
            manager.update_current_chapter(job.job_id, chapter)
            access = getattr(chapter, "access", "regular")
            if access == "vip":
                chapter.status = CrawlChapterStatus.skipped
                manager.record_chapter_status(job.job_id, chapter.chapter_no, CrawlChapterStatus.skipped)
                manager.update_progress(job.job_id, job.crawled_chapters, index)
                continue

            if manager.is_paused(job.job_id):
                job.status = CrawlJobStatus.paused
                job.updated_at = datetime.now(timezone.utc)
                return

            existing = None
            try:
                existing = await db_mod.client.chapter.find_unique(where={"url": chapter.url})
            except Exception as exc:
                logger.warning("Failed to check existing chapter content for %s: %s", chapter.url, exc)

            if existing and getattr(existing, "content", None):
                chapter.status = CrawlChapterStatus.skipped
                manager.record_chapter_status(job.job_id, chapter.chapter_no, CrawlChapterStatus.skipped)
                manager.update_progress(job.job_id, job.crawled_chapters, index)
                await persist_crawl_job(job)
                continue

            raw_content = await scr.scrape_stv_chapter_content(chapter.url)
            if not raw_content:
                chapter.status = CrawlChapterStatus.failed
                manager.record_chapter_status(job.job_id, chapter.chapter_no, CrawlChapterStatus.failed)
                manager.update_progress(job.job_id, job.crawled_chapters, index)
                await persist_crawl_job(job)
                continue

            paragraphs = [p.strip() for p in raw_content.splitlines() if p.strip()]
            try:
                await db_mod.save_chapter_content(chapter.url, paragraphs, chapter_title=chapter.title_vi)
            except Exception as exc:
                logger.warning("Skipping chapter content persistence for %s because DB is unavailable: %s", chapter.url, exc)
            chapter.status = CrawlChapterStatus.crawled
            manager.record_chapter_status(job.job_id, chapter.chapter_no, CrawlChapterStatus.crawled)
            manager.update_progress(job.job_id, job.crawled_chapters, index)
            await persist_crawl_job(job)
            await asyncio.sleep(DELAY_SECONDS_PER_CHAPTER)

        manager.complete_job(job.job_id)
        await persist_crawl_job(job)
        await scr.close_browser()
    except Exception:
        manager.fail_job(job.job_id)
        await scr.close_browser()


async def submit_crawl(raw_url: str, queue_manager: CrawlQueueManager):
    normalized_url = normalize_source_url(raw_url.strip())

    book_info = await scr.scrape_stv_basic_info(normalized_url)
    if not book_info:
        raise ValueError("Không lấy được thông tin truyện từ SangTacViet")

    raw_chapters = await scr.scrape_stv_chapters(normalized_url)
    if not raw_chapters:
        raise ValueError("Không lấy được danh sách chương từ SangTacViet")

    # browser context is intentionally kept open for the whole crawl job,
    # then closed once the job ends so we avoid reinitializing Chromium per chapter.
    book_data = _build_book_data(
        source_url=normalized_url,
        title_vi=book_info.get("title_vi"),
        title_cn=book_info.get("title_cn"),
        author_vi=book_info.get("author_vi"),
        description_vi=book_info.get("description_vi"),
        cover_url=book_info.get("cover_url", ""),
    )
    book = await db_mod.save_book(book_data)

    chapters = [_build_chapter_data(raw, index) for index, raw in enumerate(raw_chapters, start=1)]

    await db_mod.save_chapters(normalized_url, chapters, replace_existing=True)

    job = queue_manager.add_job(normalized_url)
    job.book_id = getattr(book, "id", None) if book is not None else None
    await persist_crawl_job(job)
    return job
