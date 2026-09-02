from services.video_metadata import build_video_publish_metadata


def test_build_video_publish_metadata_generates_title_description_and_tags(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CHANNEL_NAME", "Truyện Audio Hay")
    monkeypatch.setenv("YOUTUBE_CHANNEL_URL", "https://www.youtube.com/channel/test")
    monkeypatch.setenv("YOUTUBE_PLAYLIST_NAME", "Playlist Truyện Audio")
    monkeypatch.setenv("YOUTUBE_PLAYLIST_URL", "https://www.youtube.com/playlist/test")
    monkeypatch.setenv("VIDEO_SUPPORT_EMAIL", "support@truyen.com")
    monkeypatch.setenv("VIDEO_VOICE_LABEL", "Nam Giọng")
    monkeypatch.setenv("VIDEO_BOOK_STATUS", "Hoàn thành")
    monkeypatch.setenv("VIDEO_COPYRIGHT_CHANNEL", "Truyện Audio Hay")

    metadata = build_video_publish_metadata(
        book_title="Độc Cô Cầu Bại",
        author_name="Nguyễn Văn A",
        chapter_start=1,
        chapter_count=3,
        chapter_title="Chương đầu",
    )

    assert metadata["author_name"] == "Nguyễn Văn A"
    assert metadata["video_title"] == "Độc Cô Cầu Bại (Chương 1 - 3) | Sách Nói Truyện Audio | Truyện Audio Hay"
    assert "Độc Cô Cầu Bại - (Chương 1 đến 3) | Truyện Audio Hay" in metadata["video_description"]
    assert "Lắng nghe bộ truyện Độc Cô Cầu Bại từ chương 1 đến chương 3 trên kênh Truyện Audio Hay." in metadata["video_description"]
    assert "Nghe trọn bộ Độc Cô Cầu Bại: https://www.youtube.com/playlist/test" in metadata["video_description"]
    assert "Kênh Truyện Audio Hay: https://www.youtube.com/channel/test" in metadata["video_description"]
    assert "- Tác giả: Nguyễn Văn A" in metadata["video_description"]
    assert "- Trạng thái: Hoàn thành" in metadata["video_description"]
    assert "- Giọng đọc: AI Nam Giọng" in metadata["video_description"]
    assert "Email hỗ trợ/bản quyền: support@truyen.com" in metadata["video_description"]
    assert "Bản quyền thuộc về Truyện Audio Hay. Vui lòng không Reup dưới mọi hình thức!" in metadata["video_description"]
    description_lower = metadata["video_description"].lower()
    assert "#doccocaubai" in description_lower
    assert "#truyenaudiohay" in description_lower
    assert "#truyenaudioconvert" in description_lower
    assert "#sachnoi" in description_lower
    assert "độc cô cầu bại" in metadata["video_tags"]
    assert "nguyễn văn a" in metadata["video_tags"]
    assert "doc co cau bai" in metadata["video_tags"]
    assert "độc cô cầu bại chương 1 3" in metadata["video_tags"]
    assert "truyện audio hay" in metadata["video_tags"]
    assert "sach noi" in metadata["video_tags"]


def test_build_video_publish_metadata_omits_author_tag_when_author_missing():
    metadata = build_video_publish_metadata(
        book_title="Độc Cô Cầu Bại",
        author_name=None,
        chapter_start=1,
        chapter_count=3,
    )

    assert metadata["author_name"] is None
    assert "- Tác giả: Chưa cập nhật" in metadata["video_description"]
    assert "truyện audio hay" in metadata["video_tags"]
    assert "book audio" not in metadata["video_tags"] or "truyện audio hay" in metadata["video_tags"]
    assert "độc cô cầu bại" in metadata["video_tags"]


def test_build_video_publish_metadata_uses_single_chapter_text_for_one_chapter(monkeypatch):
    monkeypatch.delenv("YOUTUBE_CHANNEL_NAME", raising=False)
    monkeypatch.delenv("YOUTUBE_CHANNEL_URL", raising=False)
    monkeypatch.delenv("YOUTUBE_PLAYLIST_NAME", raising=False)
    monkeypatch.delenv("YOUTUBE_PLAYLIST_URL", raising=False)
    monkeypatch.delenv("VIDEO_SUPPORT_EMAIL", raising=False)
    monkeypatch.delenv("VIDEO_VOICE_LABEL", raising=False)
    monkeypatch.delenv("VIDEO_BOOK_STATUS", raising=False)
    monkeypatch.delenv("VIDEO_COPYRIGHT_CHANNEL", raising=False)

    metadata = build_video_publish_metadata(
        book_title="Huyền thoại",
        author_name="Lê Văn B",
        chapter_start=5,
        chapter_count=1,
    )

    assert metadata["video_title"] == "Huyền thoại (Chương 5) | Sách Nói Truyện Audio | Kênh Truyện Audio"
    assert "Chương 5" in metadata["video_description"]
    assert "Kênh Truyện Audio" in metadata["video_description"]
    assert "support@example.com" in metadata["video_description"]
    assert "huyền thoại" in metadata["video_tags"]
    assert "truyện audio hay" in metadata["video_tags"]


def test_build_video_publish_metadata_includes_chapter_title_for_single_chapter(monkeypatch):
    monkeypatch.delenv("YOUTUBE_CHANNEL_NAME", raising=False)
    monkeypatch.delenv("YOUTUBE_CHANNEL_URL", raising=False)
    monkeypatch.delenv("YOUTUBE_PLAYLIST_NAME", raising=False)
    monkeypatch.delenv("YOUTUBE_PLAYLIST_URL", raising=False)
    monkeypatch.delenv("VIDEO_SUPPORT_EMAIL", raising=False)
    monkeypatch.delenv("VIDEO_VOICE_LABEL", raising=False)
    monkeypatch.delenv("VIDEO_BOOK_STATUS", raising=False)
    monkeypatch.delenv("VIDEO_COPYRIGHT_CHANNEL", raising=False)

    metadata = build_video_publish_metadata(
        book_title="Huyền thoại",
        author_name="Lê Văn B",
        chapter_start=5,
        chapter_count=1,
        chapter_title="Chương đầu",
    )

    assert metadata["video_title"] == "Huyền thoại (Chương 5: Chương đầu) | Sách Nói Truyện Audio | Kênh Truyện Audio"
    assert metadata["story_title"] == "Chương 5: Chương đầu"
    assert metadata["actual_title"] == "Chương 5: Chương đầu"
    assert "Chương đầu" in metadata["video_title"]
