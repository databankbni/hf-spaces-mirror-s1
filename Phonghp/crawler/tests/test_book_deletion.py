import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from db.book import delete_book_and_related


class DeleteBookAndRelatedTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_book_and_related_deletes_related_records(self):
        dummy_book = MagicMock()
        dummy_book.source_url = "https://example.com/book"

        mock_client = MagicMock()
        mock_client.book.find_unique = AsyncMock(return_value=dummy_book)
        mock_client.crawljob.delete_many = AsyncMock(return_value=None)
        mock_client.chapter.delete_many = AsyncMock(return_value=None)
        mock_client.video.delete_many = AsyncMock(return_value=None)
        mock_client.book.delete = AsyncMock(return_value=dummy_book)

        with patch("db.book.client", mock_client):
            deleted = await delete_book_and_related("book-id")

        self.assertEqual(deleted, dummy_book)
        mock_client.book.find_unique.assert_awaited_once_with(where={"id": "book-id"})
        mock_client.crawljob.delete_many.assert_awaited_once_with(
            where={
                "OR": [
                    {"bookId": "book-id"},
                    {"book_url": "https://example.com/book"},
                ]
            }
        )
        mock_client.chapter.delete_many.assert_awaited_once_with(where={"book_source_url": "https://example.com/book"})
        mock_client.video.delete_many.assert_awaited_once_with(where={"book_url": "https://example.com/book"})
        mock_client.book.delete.assert_awaited_once_with(where={"id": "book-id"})

    async def test_delete_book_and_related_returns_none_when_book_not_found(self):
        mock_client = MagicMock()
        mock_client.book.find_unique = AsyncMock(return_value=None)

        with patch("db.book.client", mock_client):
            deleted = await delete_book_and_related("missing-id")

        self.assertIsNone(deleted)
        mock_client.book.find_unique.assert_awaited_once_with(where={"id": "missing-id"})


if __name__ == "__main__":
    unittest.main()
