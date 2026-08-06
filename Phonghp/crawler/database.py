import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from prisma import Prisma

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Missing DATABASE_URL in environment")

client = Prisma()

async def connect():
    try:
        await client.connect()
    except Exception as e:
        raise SystemExit(f"Cannot connect to PostgreSQL via Prisma: {e}")

async def disconnect():
    await client.disconnect()


def _get_field(row: dict, field: str, default=None):
    if isinstance(row, dict):
        return row.get(field, default)
    return getattr(row, field, default)


from typing import Any


def _slugify(text: str) -> str:
    if not text:
        return ""
    # lower, replace non-alnum with '-', trim duplicate '-' and edges
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def serialize_book_row(row: dict, chapters_count: int = None) -> dict:
    payload = {
        "id": _get_field(row, "id"),
        "source_url": _get_field(row, "source_url"),
        "slug": _get_field(row, "slug"),
        "title_vi": _get_field(row, "title_vi"),
        "title_en": _get_field(row, "title_en"),
        "author_vi": _get_field(row, "author_vi"),
        "description_vi": _get_field(row, "description_vi"),
        "status": _get_field(row, "status"),
        "cover_url": _get_field(row, "cover_url"),
        "views_count": _get_field(row, "views_count", 0),
        "chapters_count": chapters_count if chapters_count is not None else _get_field(row, "chapters_count", 0),
        "updated_at": _get_field(row, "updatedAt") or _get_field(row, "updated_at"),
    }
    return {k: v for k, v in payload.items() if v is not None}


def serialize_chapter_row(row: dict) -> dict:
    title = _get_field(row, "title")
    payload = {
        "id": _get_field(row, "id"),
        "book_source_url": _get_field(row, "book_source_url"),
        "title": title,
        "title_vi": _get_field(row, "title_vi") or title,
        "url": _get_field(row, "url"),
        "slug": (_get_field(row, "slug") or _slugify(title)),
        "chapter_no": _get_field(row, "chapter_no"),
        "updated_at": _get_field(row, "updatedAt") or _get_field(row, "updated_at"),
    }
    return {k: v for k, v in payload.items() if v is not None}


async def get_chapter_content_by_url(url: str) -> str:
    if not url:
        return None

    chapter = await client.chapter.find_unique(where={"url": url})
    if not chapter:
        return None

    return _get_field(chapter, "content")


async def save_chapter_content(url: str, paragraphs: list[str]) -> None:
    if not url:
        return None

    chapter = await client.chapter.find_unique(where={"url": url})
    if not chapter:
        return None

    content_text = "\n".join(paragraphs) if paragraphs else ""
    await client.chapter.update(where={"url": url}, data={"content": content_text})


def _normalize_book_data(data: dict) -> dict:
    book_data = {
        "source_url": data["source_url"],
        "slug": data.get("slug"),
        "title_vi": data.get("title_vi"),
        "title_en": data.get("title_en"),
        "author_vi": data.get("author_vi"),
        "description_vi": data.get("description_vi"),
        "status": data.get("status"),
        "cover_url": data.get("cover_url"),
        "views_count": data.get("views_count", 0),
        "chapters_count": data.get("chapters_count", 0),
        "updatedAt": datetime.now(),
    }
    return {k: v for k, v in book_data.items() if v is not None}

async def save_book(data: dict):
    book_data = _normalize_book_data(data)

    return await client.book.upsert(
        where={"source_url": book_data["source_url"]},
        data={
            "create": book_data,
            "update": book_data,
        },
    )

async def save_chapters(book_url: str, chapters_list: list):
    if not chapters_list:
        return None

    # Kiểm tra book tồn tại trước khi lưu chapters (FK constraint)
    book = await client.book.find_unique(where={"source_url": book_url})
    if not book:
        raise ValueError(f"Book với source_url '{book_url}' không tồn tại. Vui lòng gọi /get-basic-info trước.")

    tasks = []
    for ch in chapters_list:
        chapter_no_value = ch.get("chapter_no")
        if chapter_no_value is None:
            chapter_no_value = 0

        chapter_data = {
            "book_source_url": book_url,
            "title": ch.get("title_vi") or ch.get("title") or "",
            "url": ch.get("url"),
            "slug": ch.get("slug"),
            "chapter_no": chapter_no_value,
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

    return await asyncio.gather(*tasks)

