import os, tempfile, unittest

from core.content_pipeline import ContentGate


class FakeDB:
    def __init__(self):
        self.articles = {}
        self.published = set()
        self.global_words = ["كلمة_محظورة"]
        self.channel_words = {"news": ["منع_خاص"]}

    def get_blocked_words(self): return self.global_words
    def get_channel_blocked_words(self, cid): return self.channel_words.get(cid, [])
    def is_published(self, fp): return fp in self.published
    def get_article(self, fp): return self.articles.get(fp)
    def get_all_articles(self): return list(self.articles.values())


class ContentGateTests(unittest.TestCase):
    def setUp(self): self.g = ContentGate(FakeDB())

    def test_blocked_before_duplicate(self):
        r = self.g.preflight("هذا يحتوي كلمة_محظورة", "https://x")
        self.assertFalse(r.allowed)
        self.assertEqual(r.reason, "blocked_word")
        self.assertEqual(r.matched, ("كلمة_محظورة",))

    def test_channel_blocked(self):
        r = self.g.preflight("هذا يحتوي منع_خاص", channel_id="news")
        self.assertFalse(r.allowed)
        self.assertEqual(r.reason, "blocked_word")

    def test_duplicate_without_ai(self):
        fp = self.g.fingerprint("خبر جديد", "https://x")
        self.g.db.published.add(fp)
        r = self.g.preflight("خبر جديد", "https://x")
        self.assertFalse(r.allowed)
        self.assertEqual(r.reason, "duplicate")

    def test_allowed_gets_fingerprint(self):
        r = self.g.preflight("خبر سليم", "https://x")
        self.assertTrue(r.allowed)
        self.assertEqual(len(r.fingerprint), 64)

    def test_normalization(self):
        self.assertEqual(self.g.normalize("أَخـبار   العراق"), "اخبار العراق")


if __name__ == "__main__": unittest.main()
