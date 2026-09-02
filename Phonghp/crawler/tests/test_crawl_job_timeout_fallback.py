from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import routes.crawl as crawl
from crawl_queue import CrawlJobStatus, CrawlQueueManager
import services.crawl_service as crawl_service


@pytest.mark.asyncio
async def test_persist_crawl_job_swallows_db_errors(monkeypatch):
    async def fake_save_crawl_job(*args, **kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(crawl_service.db_mod, "save_crawl_job", fake_save_crawl_job)

    job = SimpleNamespace(
        job_id="job-1",
        book_url="https://example.com/book",
        status=CrawlJobStatus.queued,
        title_vi="Title",
        author_vi=None,
        description_vi=None,
        cover_url=None,
        total_chapters=0,
        crawled_chapters=0,
        current_chapter_index=0,
        current_chapter_title=None,
        current_chapter_url=None,
        book_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    await crawl_service.persist_crawl_job(job)


def test_crawl_queue_add_job_creates_job_with_expected_state():
    manager = CrawlQueueManager()
    job = manager.add_job("https://example.com/book")

    assert job.book_url == "https://example.com/book"
    assert job.status == CrawlJobStatus.queued
    assert job.total_chapters == 0
    assert job.chapters == []


@pytest.mark.asyncio
async def test_job_payload_falls_back_to_job_level_progress_when_chapters_missing():
    job = SimpleNamespace(
        job_id="job-1",
        book_url="https://example.com/book",
        title_vi="Tiêu đề",
        author_vi="Tác giả",
        description_vi="Mô tả",
        cover_url=None,
        status=CrawlJobStatus.running,
        total_chapters=12,
        crawled_chapters=3,
        current_chapter_index=3,
        current_chapter_title="Chương 4",
        current_chapter_url="https://example.com/ch4",
        created_at=crawl.datetime.now(crawl.timezone.utc),
        updated_at=crawl.datetime.now(crawl.timezone.utc),
        chapters=[],
    )

    payload = await crawl._job_to_payload(job, db_chapter_count=12, include_chapters=False)

    assert payload["total_chapters"] == 12
    assert payload["crawled_chapters"] == 3
    assert payload["total_nonvip_chapters"] == 12
    assert payload["crawled_nonvip_chapters"] == 3
    assert payload["remaining_nonvip_chapters"] == 9


@pytest.mark.asyncio
async def test_load_job_chapters_falls_back_to_empty_when_db_times_out(monkeypatch):
    async def fake_find_many(*args, **kwargs):
        raise TimeoutError("db timeout")

    fake_chapter_client = SimpleNamespace(find_many=fake_find_many)
    monkeypatch.setattr(crawl.db_mod.client, "chapter", fake_chapter_client)

    job = SimpleNamespace(
        book_url="https://example.com/book",
        chapters=None,
        total_chapters=0,
        crawled_chapters=0,
    )

    await crawl._load_job_chapters(job)

    assert job.chapters == []
    assert job.total_chapters == 0
    assert job.crawled_chapters == 0
