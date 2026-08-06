import os
import unittest

os.environ.setdefault('DATABASE_URL', 'postgresql://test:test@localhost:5432/test')

from database import serialize_book_row, serialize_chapter_row


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
            'updatedAt': '2024-01-01T00:00:00',
        }

        payload = serialize_chapter_row(row)

        self.assertEqual(payload['title'], 'Chương 1')
        self.assertEqual(payload['slug'], 'chapter-1')
        self.assertEqual(payload['chapter_no'], 1)
        self.assertEqual(payload['book_source_url'], 'https://example.com/book')
        self.assertEqual(payload['updated_at'], '2024-01-01T00:00:00')


if __name__ == '__main__':
    unittest.main()
