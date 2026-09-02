import unittest

from modules.blogger.prompts import SYSTEM_ARTICLE_PACKAGE, make_article_package_prompt


class ArticlePackageTests(unittest.TestCase):
    def test_single_package_prompt_contains_all_outputs(self):
        prompt = make_article_package_prompt("نص الخبر", True)
        for field in ("title", "body", "summary", "keywords", "hashtags", "notes", "seo", "extracted", "media_alt"):
            self.assertIn(field, SYSTEM_ARTICLE_PACKAGE)
        self.assertIn("نص الخبر", prompt)
        self.assertIn("media_alt", prompt)


if __name__ == "__main__": unittest.main()
