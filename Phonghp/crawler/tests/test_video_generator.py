import pytest
from pathlib import Path

from backend import video_generator


def test_sanitize_text_collapses_whitespace_and_paragraphs():
    raw_text = "\n  Đây là dòng đầu.  \n\n\n  Đây là đoạn hai.\n  \n"
    sanitized = video_generator._sanitize_text(raw_text)
    assert sanitized == "Đây là dòng đầu.\n\nĐây là đoạn hai."


def test_split_text_for_tts_preserves_sentence_boundaries():
    text = (
        "Một câu ngắn. "
        "Một câu dài hơn có nhiều từ để kiểm tra việc ghép đúng. "
        "Câu cuối cùng sẽ được giữ nguyên."
    )
    chunks = video_generator._split_text_for_tts(text, max_bytes=80)
    assert len(chunks) >= 2
    assert all(chunk.endswith('.') or chunk.endswith('!') or chunk.endswith('?') for chunk in chunks)
    assert ''.join(chunks).replace('  ', ' ') == text


def test_split_text_for_tts_splits_long_sentence_by_commas():
    text = (
        "Đây là một câu rất dài, chứa nhiều cụm từ, để kiểm tra tách đoạn sao cho không vượt quá giới hạn, "
        "và vẫn giữ các ý liền nhau khi có dấu phẩy."
    )
    chunks = video_generator._split_text_for_tts(text, max_bytes=90)
    assert len(chunks) >= 2
    assert all(len(chunk.encode('utf-8')) <= 90 for chunk in chunks)
    assert ''.join(chunks).replace('  ', ' ') == text
