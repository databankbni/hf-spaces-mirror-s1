from datetime import datetime

from .client import client


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


async def delete_book_and_related(book_id: str):
    if not book_id:
        return None

    book = await client.book.find_unique(where={"id": book_id})
    if not book:
        return None

    source_url = getattr(book, "source_url", None) if not isinstance(book, dict) else book.get("source_url")

    if hasattr(client, "crawljob"):
        await client.crawljob.delete_many(
            where={
                "OR": [
                    {"bookId": book_id},
                    {"book_url": source_url} if source_url else {"bookId": book_id},
                ]
            }
        )
    else:
        await client.execute_raw(
            'DELETE FROM "CrawlJob" WHERE "bookId" = $1 OR "book_url" = $2',
            book_id,
            source_url,
        )

    if source_url:
        if hasattr(client, "chapter"):
            await client.chapter.delete_many(where={"book_source_url": source_url})
        else:
            await client.execute_raw(
                'DELETE FROM "Chapter" WHERE "book_source_url" = $1',
                source_url,
            )

        if hasattr(client, "video"):
            await client.video.delete_many(where={"book_url": source_url})
        else:
            await client.execute_raw(
                'DELETE FROM "Video" WHERE "book_url" = $1',
                source_url,
            )

    if hasattr(client, "book"):
        deleted_book = await client.book.delete(where={"id": book_id})
    else:
        result = await client.query_raw('DELETE FROM "Book" WHERE "id" = $1 RETURNING *', book_id)
        deleted_book = result[0] if result else None

    return deleted_book
