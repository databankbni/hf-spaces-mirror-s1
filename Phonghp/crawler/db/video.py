import asyncio
from datetime import datetime
from uuid import uuid4

from .client import client


async def save_video(data: dict):
    if not data:
        return None

    if hasattr(client, "video"):
        return await client.video.create(data=data)

    columns = [
        "id",
        "book_url",
        "video_url",
        "chapter_start",
        "chapter_count",
        "voice",
        "rate",
        "job_id",
        "bookId",
        "thumbnail_url",
        "book_title",
        "author_name",
        "video_title",
        "video_description",
        "video_tags",
        "createdAt",
        "updatedAt",
    ]
    placeholders = ", ".join(f"${idx + 1}" for idx in range(len(columns) - 2))
    quoted_columns = ', '.join(f'"{c}"' for c in columns)
    query = (
        f"INSERT INTO \"Video\" ({quoted_columns}) VALUES ({placeholders}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
        f"RETURNING *"
    )
    values = [
        str(uuid4()),
        data.get("book_url"),
        data.get("video_url"),
        data.get("chapter_start"),
        data.get("chapter_count"),
        data.get("voice"),
        data.get("rate"),
        data.get("job_id"),
        data.get("bookId"),
        data.get("thumbnail_url"),
        data.get("book_title"),
        data.get("author_name"),
        data.get("video_title"),
        data.get("video_description"),
        data.get("video_tags"),
    ]
    result = await client.query_raw(query, *values)
    return result[0] if result else None


async def get_videos_by_book_url(book_url: str):
    if not book_url:
        return []

    if hasattr(client, "video"):
        return await client.video.find_many(
            where={"book_url": book_url},
            order={"createdAt": "desc"},
        )

    return await client.query_raw(
        'SELECT * FROM "Video" WHERE "book_url" = $1 ORDER BY "createdAt" DESC',
        book_url,
    )


async def get_all_videos():
    if hasattr(client, "video"):
        return await client.video.find_many(
            order={"createdAt": "desc"},
        )

    return await client.query_raw(
        'SELECT * FROM "Video" ORDER BY "createdAt" DESC',
    )


async def get_video_by_id(video_id: str):
    if not video_id:
        return None

    if hasattr(client, "video"):
        return await client.video.find_unique(where={"id": video_id})

    result = await client.query_raw('SELECT * FROM "Video" WHERE "id" = $1', video_id)
    return result[0] if result else None


async def delete_video(video_id: str):
    if not video_id:
        return None

    if hasattr(client, "video"):
        return await client.video.delete(where={"id": video_id})

    result = await client.query_raw('DELETE FROM "Video" WHERE "id" = $1 RETURNING *', video_id)
    return result[0] if result else None
