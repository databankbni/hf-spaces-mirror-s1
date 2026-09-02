import pytest

from routes import crawl as crawl_routes


def test_build_chapter_range_for_two_chapters():
    chapter_start, last_index = crawl_routes._build_chapter_range(1, 2, 10)

    assert chapter_start == 1
    assert last_index == 2


def test_build_chapter_range_rejects_invalid_window():
    with pytest.raises(ValueError):
        crawl_routes._build_chapter_range(9, 3, 10)


