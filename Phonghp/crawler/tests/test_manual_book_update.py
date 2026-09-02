import unittest

from main import build_unique_chapter_url


class ManualBookUpdateTests(unittest.TestCase):
    def test_build_unique_chapter_url_keeps_slug_unique_for_existing_titles(self):
        existing_urls = {
            "https://manual.local/demo/chapter/chuong-1",
            "https://manual.local/demo/chapter/chuong-1-2",
        }

        self.assertEqual(
            build_unique_chapter_url("https://manual.local/demo", "Chương 1", existing_urls),
            "https://manual.local/demo/chapter/chuong-1-3",
        )


if __name__ == "__main__":
    unittest.main()
