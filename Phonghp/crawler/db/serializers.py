import re


def _get_field(row: dict, field: str, default=None):
    if isinstance(row, dict):
        return row.get(field, default)
    return getattr(row, field, default)


def _slugify(text: str) -> str:
    if not text:
        return ""
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
        "content": _get_field(row, "content") or "",
        "access": _get_field(row, "access") or "regular",
        "is_story_content": _get_field(row, "is_story_content", False),
        "updated_at": _get_field(row, "updatedAt") or _get_field(row, "updated_at"),
    }
    return {k: v for k, v in payload.items() if v is not None}
