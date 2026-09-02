import asyncio
import re
from datetime import datetime
from typing import Optional

from .client import client


async def get_chapter_by_url(url: str):
    """Get full chapter object by URL."""
    if not url:
        return None

    chapter = await client.chapter.find_unique(where={"url": url})
    return chapter


async def get_chapter_content_by_url(url: str) -> str:
    if not url:
        return None

    chapter = await client.chapter.find_unique(where={"url": url})
    if not chapter:
        return None

    return getattr(chapter, "content", None) if not isinstance(chapter, dict) else chapter.get("content")


async def get_chapter_contents_by_urls(urls: list[str]) -> dict[str, str]:
    if not urls:
        return {}

    rows = await client.chapter.find_many(
        where={"url": {"in": urls}},
    )

    return {
        (getattr(row, "url", None) if not isinstance(row, dict) else row.get("url")): (
            getattr(row, "content", None) if not isinstance(row, dict) else row.get("content")
        )
        for row in rows or []
        if (getattr(row, "url", None) if not isinstance(row, dict) else row.get("url"))
    }


async def save_chapter_content(url: str, paragraphs: list[str], chapter_title: Optional[str] = None) -> None:
    if not url:
        return None

    chapter = await client.chapter.find_unique(where={"url": url})
    if not chapter:
        return None

    # Keep the original chapter-title behavior for reading UX and TTS
    content_paragraphs = paragraphs or []
    if chapter_title:
        title_text = chapter_title.strip()
        if title_text and not title_text.endswith((".", "?", "!", "…")):
            title_text = f"{title_text}."
        content_paragraphs = [title_text] + content_paragraphs

    content_text = "\n".join(content_paragraphs) if content_paragraphs else ""
    await client.chapter.update(where={"url": url}, data={"content": content_text})


def is_story_title(title: Optional[str]) -> bool:
    """Heuristic to decide if a chapter title represents story content.

    Returns True when the title contains common chapter keywords or starts with a number.
    """
    if not title:
        return False
    t = title.lower()
    # common chapter keywords
    if re.search(r"\b(chương|chuong|ch\.|chapter)\b", t, flags=re.I):
        return True
    # leading numeric chapter like "1", "01", "1. Giới thiệu"
    if re.search(r"^\s*\d+\b", t):
        return True
    return False


async def save_chapters(book_url: str, chapters_list: list, replace_existing: bool = False):
    if not chapters_list:
        return None

    book = await client.book.find_unique(where={"source_url": book_url})
    if not book:
        raise ValueError(f"Book với source_url '{book_url}' không tồn tại. Vui lòng gọi /get-basic-info trước.")

    if replace_existing:
        await client.chapter.delete_many(where={"book_source_url": book_url})
        chapter_data_list = []
        for idx, ch in enumerate(chapters_list, start=1):
            chapter_no_value = ch.get("chapter_no")
            if chapter_no_value is None:
                chapter_no_value = 0
            title_val = ch.get("title_vi") or ch.get("title") or ""
            chapter_data_list.append({
                "book_source_url": book_url,
                "title": title_val,
                "title_vi": ch.get("title_vi") or ch.get("title"),
                "url": ch.get("url"),
                "slug": ch.get("slug"),
                "chapter_no": chapter_no_value,
                "access": ch.get("access") or "regular",
                "is_story_content": is_story_title(title_val),
                "updatedAt": datetime.now(),
            })

        created_count = await client.chapter.create_many(data=chapter_data_list)
        try:
            await client.book.update(
                where={"source_url": book_url},
                data={"chapters_count": len(chapter_data_list), "updatedAt": datetime.now()},
            )
        except Exception:
            pass
        return created_count

    tasks = []
    for ch in chapters_list:
        chapter_no_value = ch.get("chapter_no")
        if chapter_no_value is None:
            chapter_no_value = 0
        title_val = ch.get("title_vi") or ch.get("title") or ""

        chapter_data = {
            "book_source_url": book_url,
            "title": title_val,
            "title_vi": ch.get("title_vi") or ch.get("title"),
            "url": ch.get("url"),
            "slug": ch.get("slug"),
            "chapter_no": chapter_no_value,
            "access": ch.get("access") or "regular",
            "is_story_content": is_story_title(title_val),
            "updatedAt": datetime.now(),
        }
        tasks.append(
            client.chapter.upsert(
                where={"url": chapter_data["url"]},
                data={
                    "create": chapter_data,
                    "update": chapter_data,
                },
            )
        )

    result = await asyncio.gather(*tasks)
    try:
        await client.book.update(
            where={"source_url": book_url},
            data={"chapters_count": len(chapters_list), "updatedAt": datetime.now()},
        )
    except Exception:
        pass
    return result
