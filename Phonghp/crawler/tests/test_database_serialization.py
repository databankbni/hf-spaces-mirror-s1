import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault('DATABASE_URL', 'postgresql://test:test@localhost:5432/test')

import main
from database import serialize_book_row, serialize_chapter_row
from main import build_bulk_chapters_from_text


class SerializationTests(unittest.TestCase):
    def test_serialize_book_row_includes_api_fields(self):
        row = {
            'source_url': 'https://example.com/book',
            'slug': 'book-slug',
            'title_vi': 'Tiêu đề',
            'author_vi': 'Tác giả',
            'description_vi': 'Mô tả',
            'cover_url': 'https://example.com/cover.jpg',
            'status': 'info_only',
            'views_count': 12,
            'updatedAt': '2024-01-01T00:00:00',
        }

        payload = serialize_book_row(row, chapters_count=3)

        self.assertEqual(payload['source_url'], 'https://example.com/book')
        self.assertEqual(payload['chapters_count'], 3)
        self.assertEqual(payload['title_vi'], 'Tiêu đề')
        self.assertEqual(payload['views_count'], 12)
        self.assertEqual(payload['updated_at'], '2024-01-01T00:00:00')

    def test_serialize_chapter_row_uses_expected_shape(self):
        row = {
            'book_source_url': 'https://example.com/book',
            'title': 'Chương 1',
            'url': 'https://example.com/chapter-1',
            'slug': 'chapter-1',
            'chapter_no': 1,
            'content': 'Nội dung chương cũ cần hiển thị để sửa',
            'updatedAt': '2024-01-01T00:00:00',
        }

        payload = serialize_chapter_row(row)

        self.assertEqual(payload['title'], 'Chương 1')
        self.assertEqual(payload['slug'], 'chapter-1')
        self.assertEqual(payload['chapter_no'], 1)
        self.assertEqual(payload['book_source_url'], 'https://example.com/book')
        self.assertEqual(payload['content'], 'Nội dung chương cũ cần hiển thị để sửa')
        self.assertEqual(payload['updated_at'], '2024-01-01T00:00:00')
        # default when missing in row
        self.assertIn('is_story_content', payload)
        self.assertEqual(payload['is_story_content'], False)

    def test_build_bulk_chapters_from_text_splits_by_title_and_content(self):
        bulk_text = """Chương 1: Mở đầu\n\nNội dung chương 1 rất dài ...\n\nChương 2: Bắt đầu hành trình\n\nNội dung chương 2 rất dài ..."""

        chapters = build_bulk_chapters_from_text(bulk_text)

        self.assertGreaterEqual(len(chapters), 2)
        self.assertEqual(chapters[0]['title'], 'Mở đầu')
        self.assertIn('Nội dung chương 1', chapters[0]['content'])
        self.assertEqual(chapters[1]['title'], 'Bắt đầu hành trình')
        self.assertIn('Nội dung chương 2', chapters[1]['content'])

    def test_api_create_manual_book_bulk_text_creates_chapters(self):
        request = main.ManualBookCreateRequest(
            title_vi='Truyện bulk test',
            source_url='https://manual.local/truyen-bulk-test',
            slug='truyen-bulk-test',
            bulk_chapter_text='''Chương 1: Mở đầu\n\nNội dung chương 1 rất dài\n\nChương 2: Khởi hành\n\nNội dung chương 2 rất dài''',
            chapters=[],
        )

        with patch.object(main.db_mod.client, 'book', new_callable=type, __dict__={}), \
             patch.object(main.db_mod, 'save_book', AsyncMock(return_value={'id': 'book-1', 'source_url': request.source_url})), \
             patch.object(main.db_mod.client.chapter, 'upsert', AsyncMock(side_effect=lambda **kwargs: {'id': 'chapter-1', 'title': kwargs['data']['create']['title']})), \
             patch.object(main.db_mod.client.chapter, 'count', AsyncMock(return_value=2)), \
             patch.object(main.db_mod.client.book, 'update', AsyncMock(return_value={'id': 'book-1'})):
            main.db_mod.client.book.find_unique = AsyncMock(return_value=None)
            response = asyncio.run(main.api_create_manual_book(request, current_user={}))

        self.assertTrue(response['success'])
        self.assertEqual(len(response['data']['chapters']), 2)
        self.assertEqual(response['data']['chapters'][0]['title'], 'Mở đầu')
        self.assertEqual(response['data']['chapters'][1]['title'], 'Khởi hành')


if __name__ == '__main__':
    unittest.main()
