# -*- coding: utf-8 -*-
import asyncio
import os
import sys
import unittest

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.blogger.processor import ArticleProcessor


class TestPreviewCleanliness(unittest.TestCase):
    """تحقق من أن معاينة تيليجرام لا تعرض CSS أو HTML خام."""

    def _processor(self):
        return ArticleProcessor(db=None, ai_client=None, config={})

    def _article(self):
        return {
            "title": "عنوان تجريبي",
            "summary": "ملخص المقال",
            "introduction": "مقدمة المقال هنا",
            "body": (
                "<h2>القسم الأول</h2><p>نص تجريبي داخل الفقرة.</p>"
                "<h3>القسم الثاني</h3><p>فقرة ثانية.</p>"
                "<table><tr><th>العمود أ</th><th>العمود ب</th></tr>"
                "<tr><td>قيمة 1</td><td>قيمة 2</td></tr></table>"
                "<ul><li>عنصر أول</li><li>عنصر ثانٍ</li></ul>"
                "<a href='https://example.com'>رابط تجريبي</a>"
            ),
            "labels": ["وظائف", "تجربة"],
            "keywords": "كلمة1، كلمة2",
            "hashtags": ["#تاغ1", "#تاغ2"],
            "reading_time": 3,
            "notes": ["ملاحظة مهمة"],
            "faq": [{"question": "سؤال؟", "answer": "جواب."}],
            "source": {"name": "مصدر تجريبي", "username": "example"},
        }

    def test_html_to_telegram_contains_no_css(self):
        html = ArticleProcessor.make_article_html(self._processor(), self._article())
        preview = ArticleProcessor.html_to_telegram(html)
        for bad in ("<style", "</style>", "<script", "</script>", "html{", "body{", "<head>", "class=", "style=", "<div", "<span", "<table", "<h2", "scroll-behavior"):
            self.assertNotIn(bad, preview, f"تسرب: {bad}")
        self.assertNotIn("/*", preview)

    def test_html_to_telegram_keeps_telegram_formatting(self):
        html = ArticleProcessor.make_article_html(self._processor(), self._article())
        preview = ArticleProcessor.html_to_telegram(html)
        self.assertIn("القسم الأول", preview)
        self.assertIn("<a href=", preview)
        self.assertIn("العمود أ", preview)
        self.assertIn("قيمة 1", preview)

    def test_make_preview_data_clean(self):
        image, text = self._processor().make_preview_data(self._article())
        for bad in ("<style", "html{", "body{", "<head>", "class=", "style="):
            self.assertNotIn(bad, text, f"تسرب: {bad}")
        self.assertIn("<b>عنوان تجريبي</b>", text)
        self.assertIn("مدة القراءة: 3 دقيقة", text)


if __name__ == "__main__":
    unittest.main()
