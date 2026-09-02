import pytest
from types import SimpleNamespace
from fastapi import HTTPException

import routes.crawl as crawl


@pytest.mark.asyncio
async def test_delete_crawl_book_removes_job_from_queue(monkeypatch):
    deleted_book = SimpleNamespace(id="book-id", source_url="https://example.com/book")

    async def fake_delete_book_and_related(book_id: str):
        assert book_id == "book-id"
        return deleted_book

    monkeypatch.setattr(crawl.db_mod, "delete_book_and_related", fake_delete_book_and_related)

    fake_job = SimpleNamespace(job_id="job-123", book_id="book-id", book_url="https://example.com/book")
    monkeypatch.setattr(crawl.queue_manager, "get_all_jobs", lambda: [fake_job])

    removed_jobs = []

    def fake_remove_job(job_id: str):
        removed_jobs.append(job_id)

    monkeypatch.setattr(crawl.queue_manager, "remove_job", fake_remove_job)

    result = await crawl.delete_crawl_book("book-id")

    assert result["success"] is True
    assert result["message"] == "Đã xóa sách và dữ liệu liên quan"
    assert removed_jobs == ["job-123"]


@pytest.mark.asyncio
async def test_delete_crawl_book_returns_404_when_book_not_found(monkeypatch):
    async def fake_delete_book_and_related(book_id: str):
        return None

    monkeypatch.setattr(crawl.db_mod, "delete_book_and_related", fake_delete_book_and_related)

    with pytest.raises(HTTPException) as exc_info:
        await crawl.delete_crawl_book("missing-book")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_crawl_book_returns_400_for_empty_book_id():
    with pytest.raises(HTTPException) as exc_info:
        await crawl.delete_crawl_book("")

    assert exc_info.value.status_code == 400
