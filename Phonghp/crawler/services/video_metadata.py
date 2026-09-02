from __future__ import annotations

import os
import re
import unicodedata
from typing import Any


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = re.sub(r"\s+", " ", value.strip())
    return text


def _remove_diacritics(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", stripped).strip()


def _slug_compact(value: Optional[str]) -> str:
    if not value:
        return ""
    text = _remove_diacritics(value)
    text = re.sub(r"\s+", "", text)
    return text.lower()


def _env_str(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


def _join_tags(tags: list[str]) -> str:
    seen: list[str] = []
    for tag in tags:
        normalized = _normalize_text(tag).lower()
        if normalized and normalized not in seen:
            seen.append(normalized)
    return ", ".join(seen)


def _safe_youtube_tag(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    tag = str(value)
    tag = tag.replace("#", " ").replace("@", " ").replace("/", " ").replace("\\", " ")
    tag = tag.replace("http://", " ").replace("https://", " ")
    tag = re.sub(r"[^\w\s\u00C0-\u024F\u1E00-\u1EFF]", " ", tag, flags=re.UNICODE)
    tag = re.sub(r"\s+", " ", tag).strip()
    tag = tag.strip("-_. ")
    if not tag or len(tag) < 2 or len(tag) > 30:
        return None
    return tag


def build_video_publish_metadata(
    *,
    book_title: Optional[str] = None,
    author_name: Optional[str] = None,
    chapter_start: Optional[int] = None,
    chapter_count: Optional[int] = None,
    chapter_title: Optional[str] = None,
    story_chapter_start: Optional[int] = None,
    story_chapter_end: Optional[int] = None,
    actual_chapter_start: Optional[int] = None,
    actual_chapter_end: Optional[int] = None,
) -> dict[str, Any]:
    safe_book_title = _normalize_text(book_title) or "Video truyện"
    clean_author_name = _normalize_text(author_name) or None
    safe_chapter_start = chapter_start or 1
    safe_chapter_count = chapter_count or 1
    safe_chapter_end = safe_chapter_start + safe_chapter_count - 1
    story_start = (
        story_chapter_start
        if story_chapter_start is not None
        else chapter_start or actual_chapter_start or 1
    )
    story_end = (
        story_chapter_end
        if story_chapter_end is not None
        else (story_start + safe_chapter_count - 1 if chapter_count is not None else actual_chapter_end or story_start)
    )
    actual_start = actual_chapter_start or story_start
    actual_end = actual_chapter_end or story_end
    story_title_range = (
        f"Chương {story_start}" if story_start == story_end else f"Chương {story_start} - {story_end}"
    )
    actual_title_range = (
        f"Chương {actual_start}" if actual_start == actual_end else f"Chương {actual_start} - {actual_end}"
    )
    chapter_title_suffix = f": {_normalize_text(chapter_title)}" if chapter_title and story_start == story_end else ""
    story_title_range_with_title = f"{story_title_range}{chapter_title_suffix}"
    actual_title_range_with_title = f"{actual_title_range}{chapter_title_suffix}"

    channel_name = _normalize_text(_env_str("YOUTUBE_CHANNEL_NAME", "Kênh Truyện Audio"))
    channel_url = _normalize_text(_env_str("YOUTUBE_CHANNEL_URL", "https://www.youtube.com"))
    playlist_name = _normalize_text(_env_str("YOUTUBE_PLAYLIST_NAME", "Playlist Truyện Audio"))
    playlist_url = _normalize_text(_env_str("YOUTUBE_PLAYLIST_URL", channel_url))
    support_email = _normalize_text(_env_str("VIDEO_SUPPORT_EMAIL", "support@example.com"))
    voice_label = _normalize_text(_env_str("VIDEO_VOICE_LABEL", "AI"))
    book_status = _normalize_text(_env_str("VIDEO_BOOK_STATUS", "Đang ra"))
    copyright_channel = _normalize_text(_env_str("VIDEO_COPYRIGHT_CHANNEL", channel_name))

    chapter_range_text = (
        f"Chương {story_start}" if story_start == story_end else f"Chương {story_start} đến {story_end}"
    )
    chapter_title_range = story_title_range_with_title
    title = f"{safe_book_title} ({chapter_title_range}) | Sách Nói Truyện Audio | {channel_name}"
    video_description = (
        f"{safe_book_title} - ({chapter_range_text}) | {channel_name}\n"
        f"Lắng nghe bộ truyện {safe_book_title} từ chương {story_start} đến chương {story_end} trên kênh {channel_name}.\n\n"
        "Nhấn ĐĂNG KÝ KÊNH và BẬT CHUÔNG THÔNG BÁO để không bỏ lỡ các chương tiếp theo nhé!\n\n"
        "DANH SÁCH PHÁT (PLAYLIST) TRỌN BỘ:\n"
        f"Nghe trọn bộ {safe_book_title}: {playlist_url}\n"
        f"Kênh {channel_name}: {channel_url}\n\n"
        "THÔNG TIN TRUYỆN:\n"
        f"- Tác giả: {clean_author_name or 'Chưa cập nhật'}\n"
        f"- Trạng thái: {book_status}\n"
        f"- Giọng đọc: AI {voice_label}\n\n"
        "LIÊN HỆ VÀ BẢN QUYỀN:\n"
        f"Email hỗ trợ/bản quyền: {support_email}\n"
        f"Bản quyền thuộc về {copyright_channel}. Vui lòng không Reup dưới mọi hình thức!\n\n"
        f"#{_slug_compact(safe_book_title)} #{_slug_compact(channel_name)} #TruyenAudioConvert #TruyenAudioHay #SachNoi"
    )

    tag_pool = [
        safe_book_title,
        _remove_diacritics(safe_book_title),
        f"{safe_book_title} story {story_start} {story_end}",
        f"{safe_book_title} chương {actual_start} {actual_end}",
        f"truyện {safe_book_title}",
        f"truyen {safe_book_title}",
        "truyện audio",
        "truyen audio",
        "truyện audio hay",
        "truyen audio hay",
        "truyện audio convert",
        "truyen audio convert",
        "sách nói",
        "sach noi",
        "nghe truyện audio",
        "truyen hay full",
        channel_name,
        _remove_diacritics(channel_name),
    ]
    if clean_author_name:
        tag_pool.extend([clean_author_name, _remove_diacritics(clean_author_name)])

    tags = []
    for value in tag_pool:
        tag = _safe_youtube_tag(value)
        if tag:
            tags.append(tag)

    return {
        "author_name": clean_author_name,
        "video_title": title,
        "video_description": video_description,
        "video_tags": _join_tags(tags),
        "story_title": story_title_range_with_title,
        "actual_title": actual_title_range_with_title,
        "chapter_range_text": chapter_range_text,
    }
