import pytest

import main


@pytest.mark.asyncio
async def test_resolve_chapter_content_prefers_db(monkeypatch):
    async def fake_get_content(url: str):
        assert url == "https://example.com/chapter"
        return ["Đoạn 1", "Đoạn 2"]

    async def fake_scrape(url: str):
        raise AssertionError("should not crawl when database content exists")

    monkeypatch.setattr(main.db_mod, "get_chapter_content_by_url", fake_get_content)
    monkeypatch.setattr(main.scr, "scrape_chapter_content", fake_scrape)

    paragraphs, source = await main.resolve_chapter_content("https://example.com/chapter")

    assert paragraphs == ["Đoạn 1", "Đoạn 2"]
    assert source == "db"


@pytest.mark.asyncio
async def test_resolve_chapter_content_falls_back_to_crawler(monkeypatch):
    async def fake_get_content(url: str):
        return None

    async def fake_scrape(url: str):
        return "Dòng 1\nDòng 2"

    async def fake_save_content(url: str, paragraphs):
        assert url == "https://example.com/chapter"
        assert paragraphs == ["Dòng 1", "Dòng 2"]

    monkeypatch.setattr(main.db_mod, "get_chapter_content_by_url", fake_get_content)
    monkeypatch.setattr(main.scr, "scrape_chapter_content", fake_scrape)
    monkeypatch.setattr(main.db_mod, "save_chapter_content", fake_save_content)
    monkeypatch.setattr(main.tr, "translate_text", lambda text: text)

    paragraphs, source = await main.resolve_chapter_content("https://example.com/chapter")

    assert paragraphs == ["Dòng 1", "Dòng 2"]
    assert source == "crawler"
