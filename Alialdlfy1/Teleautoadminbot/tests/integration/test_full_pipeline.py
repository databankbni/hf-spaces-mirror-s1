import asyncio
import json
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional, Dict, Any, List, Tuple

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from modules.blogger.ai_manager import (
    AIKeyManager, AIClient, NoAvailableAIProvider, AllProvidersExhausted,
    PROVIDER_CONFIGS, PROVIDER_ORDER, _model_cache, TIMEOUT,
)
from modules.blogger.processor import ArticleProcessor
from modules.blogger.database import BloggerDatabase, DEFAULT_BLOGGER_DATA
import modules.blogger.ai_manager as _ai_mod
import httpx


TEST_RAW_TEXT = """📢 #وظائف #بغداد
تعلن وزارة التربية العراقية عن توفر 500 درجة وظيفية للمتقدمين من حملة الشهادات.
الراتب: 800,000 دينار عراقي
آخر موعد للتقديم: 2026/08/15
للتقديم: https://forms.gle/test123
"""


def mock_http_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or json.dumps(json_data or {}, ensure_ascii=False)
    resp.reason_phrase = "OK" if status_code == 200 else "Error"
    resp.is_error = status_code >= 400
    return resp


class InMemoryDB:

    def __init__(self):
        self.data = json.loads(json.dumps(DEFAULT_BLOGGER_DATA))
        self.data["ai_keys"] = {
            "test_gemini_1": {
                "name": "GEMINI_KEY_1", "key": "test-key-gemini-1",
                "enabled": True, "usage_count": 0, "error_count": 0,
                "last_used": 0, "added_at": 0,
            },
            "test_gemini_2": {
                "name": "GEMINI_KEY_2", "key": "test-key-gemini-2",
                "enabled": True, "usage_count": 0, "error_count": 0,
                "last_used": 0, "added_at": 0,
            },
            "test_groq_1": {
                "name": "GROQ_KEY_1", "key": "test-key-groq-1",
                "enabled": True, "usage_count": 0, "error_count": 0,
                "last_used": 0, "added_at": 0,
            },
            "test_or_1": {
                "name": "OPENROUTER_KEY_1", "key": "test-key-or-1",
                "enabled": True, "usage_count": 0, "error_count": 0,
                "last_used": 0, "added_at": 0,
            },
        }
        self.data["sections"] = {
            "sec1": {"name": "general", "labels": ["عام", "اخبار"]},
        }

    def get_config(self): return dict(self.data.get("config", {}))
    def update_config(self, key, value): self.data["config"][key] = value
    def get_all_ai_keys(self): return dict(self.data.get("ai_keys", {}))
    def get_all_sections(self): return dict(self.data.get("sections", {}))
    def get_all_channels(self): return list(self.data.get("channels", {}).values())
    def get_channel(self, ch_id): return self.data.get("channels", {}).get(str(ch_id))
    def save_channel(self, ch_id, ch_data): self.data["channels"][str(ch_id)] = ch_data
    def get_articles_by_status(self, status): return [a for a in self.data.get("articles", {}).values() if a.get("status") == status]
    def save_article(self, aid, a): self.data["articles"][str(aid)] = a
    def get_article(self, aid): return self.data.get("articles", {}).get(str(aid))
    def is_published(self, fp): return fp in self.data.get("published_ids", [])
    def mark_published(self, fp):
        if fp not in self.data["published_ids"]:
            self.data["published_ids"].append(fp)
            self.data["stats"]["total_published"] += 1
    def mark_failed(self): self.data["stats"]["total_failed"] += 1
    def add_log(self, entry): self.data["logs"].append(entry)
    def get_logs(self, limit=50): return list(self.data["logs"])[-limit:]
    def get_stats(self): return dict(self.data.get("stats", {}))
    def update_article_status(self, aid, status, extra=None):
        if str(aid) in self.data["articles"]:
            self.data["articles"][str(aid)]["status"] = status
            if extra:
                self.data["articles"][str(aid)].update(extra)
    def increment_daily_count(self, section):
        today = time.strftime("%Y-%m-%d")
        self.data["stats"].setdefault("daily", {})
        self.data["stats"]["daily"].setdefault(today, {})
        self.data["stats"]["daily"][today][section] = self.data["stats"]["daily"][today].get(section, 0) + 1
    def get_gemini_pending_queue(self): return self.data.get("_gemini_pending", [])
    def save_gemini_pending_queue(self, q): self.data["_gemini_pending"] = q
    def add_to_gemini_pending(self, raw_text, source_url="", media=None, fingerprint="", channel_id="", section=""):
        self.data.setdefault("_gemini_pending", [])
        if fingerprint and any(p.get("fingerprint") == fingerprint for p in self.data["_gemini_pending"]):
            return
        self.data["_gemini_pending"].append({
            "raw_text": raw_text, "source_url": source_url, "media": media or [],
            "fingerprint": fingerprint, "channel_id": channel_id, "section": section,
            "attempts": 0, "added_at": int(time.time()),
        })
    def remove_from_gemini_pending(self, index=0):
        if 0 <= index < len(self.data.get("_gemini_pending", [])):
            self.data["_gemini_pending"].pop(index)
    def remove_pending_by_fingerprint(self, fingerprint):
        self.data["_gemini_pending"] = [p for p in self.data.get("_gemini_pending", []) if p.get("fingerprint") != fingerprint]
    def increment_pending_attempts(self, fingerprint):
        for p in self.data.get("_gemini_pending", []):
            if p.get("fingerprint") == fingerprint:
                p["attempts"] = p.get("attempts", 0) + 1
                return p["attempts"]
        return -1
    def set_pending_retry_after(self, fingerprint, attempts):
        import math
        seconds = min(3600, 60 * (2 ** max(0, attempts - 1)))
        for p in self.data.get("_gemini_pending", []):
            if p.get("fingerprint") == fingerprint:
                p["retry_after"] = int(time.time()) + seconds
                return seconds
        return seconds
    def get_gemini_state(self): return self.data.get("stats", {}).get("_gemini", {"global_cooldown_until": 0.0})
    def save_gemini_state(self, state): self.data.setdefault("stats", {})["_gemini"] = state
    def increment_ai_key_usage(self, key_id):
        if str(key_id) in self.data.get("ai_keys", {}):
            self.data["ai_keys"][str(key_id)]["usage_count"] += 1
    def increment_ai_key_error(self, key_id):
        if str(key_id) in self.data.get("ai_keys", {}):
            self.data["ai_keys"][str(key_id)]["error_count"] += 1
    def set_ai_key_enabled(self, key_id, enabled):
        if str(key_id) in self.data.get("ai_keys", {}):
            self.data["ai_keys"][str(key_id)]["enabled"] = enabled
    def get_slots_state(self):
        """P28 daily slots state (mirrors BloggerDatabase.get_slots_state)."""
        return dict(self.data.get("stats", {})).get("_daily_slots",
                                                    {"day": "", "sections": {}})

    def save_slots_state(self, state):
        self.data.setdefault("stats", {})["_daily_slots"] = state

    def get_schedule_state(self):
        return self.data.get("stats", {}).get("_schedule", {"day": "", "last_slot": -1})
    def save_schedule_state(self, state):
        self.data.setdefault("stats", {})["_schedule"] = state


def make_gemini_models_response():
    return mock_http_response(200, {
        "models": [
            {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
        ]
    })


def make_openai_models_response():
    return mock_http_response(200, {
        "data": [
            {"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"},
        ]
    })


def make_gemini_chat_response(json_data: dict):
    text = json.dumps(json_data, ensure_ascii=False)
    return mock_http_response(200, {
        "candidates": [{"content": {"parts": [{"text": text}]}}]
    })


def make_openai_chat_response(json_data: dict):
    text = json.dumps(json_data, ensure_ascii=False)
    return mock_http_response(200, {
        "choices": [{"message": {"content": text}}]
    })


def make_gemini_fail_response(status_code=429, message="rate limit"):
    return mock_http_response(status_code, {"error": {"message": message}})


def make_openai_fail_response(status_code=429, message="rate limit"):
    return mock_http_response(status_code, {"error": {"message": message}})


class TestFullPipelineIntegration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        _model_cache.clear()
        self.env_patcher = patch.dict(os.environ, {
            "GEMINI_KEY_1": "test-key-gemini-1",
            "GEMINI_KEY_2": "test-key-gemini-2",
            "GROQ_KEY_1": "test-key-groq-1",
            "OPENROUTER_KEY_1": "test-key-or-1",
        })
        self.env_patcher.start()
        self.db = InMemoryDB()
        self.key_manager = AIKeyManager(self.db)
        self.ai = AIClient(self.key_manager)
        self.ai._http = AsyncMock()
        self.ai._http.post = AsyncMock()
        self.ai._http.get = AsyncMock()
        self.processor = ArticleProcessor(self.db, self.ai, {"default_jobs_image": ""})

    def tearDown(self):
        self.env_patcher.stop()
        _model_cache.clear()

    def _setup_models_discovery(self):
        """Mock HTTP GET to return correct model list per provider."""
        async def mock_get(url, **kwargs):
            if "generativelanguage" in url:
                return make_gemini_models_response()
            return make_openai_models_response()
        self.ai._http.get = AsyncMock(side_effect=mock_get)

    # ================================================================
    # 1. Full Pipeline: raw_text -> queued article with all fields
    # ================================================================
    async def test_full_pipeline_success(self):
        self._setup_models_discovery()

        responses = [
            {"title": "وزارة التربية تعلن عن 500 درجة وظيفية",
             "body": "<h2>التفاصيل</h2><p>أعلنت وزارة التربية عن توفر 500 درجة.</p>",
             "introduction": "أعلنت وزارة التربية عن فرص عمل جديدة.",
             "faq": [{"question": "ما هي الدرجات؟", "answer": "500 درجة وظيفية."}],
             "conclusion": "فرصة ممتازة للباحثين عن عمل."},
            {"ministry": "وزارة التربية", "province": "بغداد",
             "job_type": "وظائف", "salary": "800,000 دينار", "deadline": "2026/08/15"},
            {"summary": "وزارة التربية تعلن عن 500 درجة وظيفية براتب يصل إلى 800 ألف دينار."},
            {"notes": ["الراتب 800,000 دينار عراقي.", "آخر موعد 2026/08/15."],
             "keywords": "وظائف العراق، وزارة التربية، بغداد، تعيينات",
             "hashtags": ["#العراق", "#وظائف", "#التعليم"]},
        ]
        resp_iter = iter(responses)

        async def mock_post(url, **kwargs):
            data = next(resp_iter)
            if "generativelanguage" in url:
                return make_gemini_chat_response(data)
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        fingerprint = self.processor.enqueue_raw_post(TEST_RAW_TEXT, source_url="https://t.me/test/1")
        self.assertIsNotNone(fingerprint)
        pending = self.db.get_gemini_pending_queue()
        self.assertTrue(any(p.get("fingerprint") == fingerprint for p in pending))

        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        result = await self.processor._process_next_pending()
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["title"], "وزارة التربية تعلن عن 500 درجة وظيفية")
        self.assertIn("<h2>التفاصيل</h2>", result["body"])
        self.assertIn("hashtags", result)
        self.assertEqual(result["hashtags"], ["#العراق", "#وظائف", "#التعليم"])

        saved = self.db.get_article(fingerprint)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["status"], "processed")

    # ================================================================
    # 2. HTML contains hashtags after <hr>
    # ================================================================
    async def test_html_contains_hashtags(self):
        article = {
            "title": "Test Title",
            "body": "<p>Test body</p>",
            "hashtags": ["#العراق", "#وظائف", "#التعليم"],
            "extracted": {"ministry": "test"},
            "reading_time": 3,
            "source": {"name": "Test"},
        }
        html = self.processor.make_article_html(article)
        self.assertIn("#العراق", html)
        self.assertIn("#وظائف", html)
        self.assertIn("#التعليم", html)
        self.assertIn("🏷️ الهاشتاكات", html)
        self.assertIn("#العراق", html)
        self.assertIn("#وظائف", html)
        self.assertIn("#التعليم", html)

    # ================================================================
    # 3. Timeout -> tries next key
    # ================================================================
    async def test_ai_timeout_tries_next_key(self):
        _model_cache.clear()
        self._setup_models_discovery()

        call_count = [0]

        async def mock_post(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.TimeoutException("timeout", request=None)
            data = {"title": "OK", "body": "<p>OK</p>"}
            if "generativelanguage" in url:
                return make_gemini_chat_response(data)
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        result = await self.ai.generate("test prompt")
        self.assertIsNotNone(result)
        self.assertGreater(call_count[0], 1)

    # ================================================================
    # 4. Invalid API key -> tries next key
    # ================================================================
    async def test_invalid_key_skips_to_next(self):
        _model_cache.clear()
        self._setup_models_discovery()

        call_count = [0]

        async def mock_post(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return make_gemini_fail_response(401, "API key not valid")
            data = {"title": "OK", "body": "<p>OK</p>"}
            if "generativelanguage" in url:
                return make_gemini_chat_response(data)
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        result = await self.ai.generate("test prompt")
        self.assertIsNotNone(result)

    # ================================================================
    # 5. ALL providers fail -> NoAvailableAIProvider (no recursion)
    # ================================================================
    async def test_all_providers_fail_raises_no_recursion(self):
        _model_cache.clear()
        self._setup_models_discovery()

        async def mock_post(url, **kwargs):
            return make_gemini_fail_response(429, "quota exhausted")

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        with self.assertRaises(NoAvailableAIProvider):
            await self.ai.generate("test prompt")

    # ================================================================
    # 6. No RecursionError when all keys fail
    # ================================================================
    async def test_no_recursion_on_repeated_failures(self):
        _model_cache.clear()
        self._setup_models_discovery()
        self.ai._http.post = AsyncMock(return_value=make_gemini_fail_response(429, "rate limit"))

        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(50)
        try:
            for _ in range(3):
                self.ai.release_session()
                with self.assertRaises(NoAvailableAIProvider):
                    await self.ai.generate("test prompt")
        finally:
            sys.setrecursionlimit(old_limit)

    # ================================================================
    # 7. Blogger error -> article stays queued (not lost)
    # ================================================================
    async def test_blogger_error_keeps_article_pending(self):
        self._setup_models_discovery()

        resp_iter = iter([
            {"title": "Test", "body": "<p>Test</p>", "introduction": "", "faq": [], "conclusion": "",
             "summary": "Test", "notes": [], "keywords": "test", "hashtags": ["#test"]},
            {"ministry": "test"},
            {"summary": "Test"},
            {"notes": [], "keywords": "test", "hashtags": ["#test"]},
        ])

        def save_next_data(*args):
            return {"title": "Test", "body": "<p>Test</p>", "introduction": "", "faq": [], "conclusion": ""}

        async def mock_post(url, **kwargs):
            data = next(resp_iter)
            if "generativelanguage" in url:
                return make_gemini_chat_response(data)
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        fingerprint = self.processor.enqueue_raw_post(TEST_RAW_TEXT)
        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        result = await self.processor._process_next_pending()
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "processed")

        saved = self.db.get_article(fingerprint)
        self.assertEqual(saved["status"], "processed")

    # ================================================================
    # 8. Labels and hashtags independent
    # ================================================================
    async def test_labels_and_hashtags_independent(self):
        self._setup_models_discovery()

        resp_iter = iter([
            {"title": "Test Article", "body": "<p>Content</p>", "introduction": "Intro",
             "faq": [], "conclusion": "Conclusion"},
            {"ministry": "test"},
            {"summary": "Summary text"},
            {"notes": ["Note 1"], "keywords": "kw1, kw2", "hashtags": ["#tag1", "#tag2"]},
        ])

        async def mock_post(url, **kwargs):
            data = next(resp_iter)
            if "generativelanguage" in url:
                return make_gemini_chat_response(data)
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        fingerprint = self.processor.enqueue_raw_post(TEST_RAW_TEXT)
        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        result = await self.processor._process_next_pending()
        self.assertIsNotNone(result)
        self.assertEqual(result.get("hashtags"), ["#tag1", "#tag2"])

        html = self.processor.make_article_html(result)
        self.assertIn("#tag1", html)
        self.assertIn("🏷️ الهاشتاكات", html)

    # ================================================================
    # 9. Duplicate detection
    # ================================================================
    async def test_duplicate_detection(self):
        fp1 = self.processor.enqueue_raw_post(TEST_RAW_TEXT)
        self.assertIsNotNone(fp1)
        fp2 = self.processor.enqueue_raw_post(TEST_RAW_TEXT)
        self.assertIsNone(fp2)

    # ================================================================
    # 10. Generate safe multiple calls
    # ================================================================
    async def test_multiple_generate_calls_safe(self):
        _model_cache.clear()
        self._setup_models_discovery()

        async def mock_post(url, **kwargs):
            data = {"title": "OK", "body": "<p>OK</p>"}
            if "generativelanguage" in url:
                return make_gemini_chat_response(data)
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        for i in range(3):
            result = await self.ai.generate(f"test prompt {i}")
            self.assertIsNotNone(result)
            self.ai.release_session()
            if i < 2:
                session_ok = await self.ai.acquire_session()
                self.assertTrue(session_ok)

    # ================================================================
    # 11. No infinite loop in key rotation
    # ================================================================
    async def test_no_infinite_loop_key_rotation(self):
        _model_cache.clear()
        self._setup_models_discovery()
        self.ai._http.post = AsyncMock(return_value=make_gemini_fail_response(429, "rate limit"))

        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        start = time.time()
        try:
            await self.ai.generate("test")
            self.fail("Should have raised NoAvailableAIProvider")
        except NoAvailableAIProvider:
            elapsed = time.time() - start
            self.assertLess(elapsed, 10)

    # ================================================================
    # 12. Timeout is 30 seconds
    # ================================================================
    def test_timeout_is_30_seconds(self):
        self.assertEqual(TIMEOUT, 30.0)

    # ================================================================
    # 13. Model not found -> tries next model
    # ================================================================
    async def test_model_not_found_tries_next_model(self):
        _model_cache.clear()
        self._setup_models_discovery()

        call_count = [0]

        async def mock_post(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                if "generativelanguage" in url:
                    return mock_http_response(404, {"error": {"message": "model not found"}})
                return mock_http_response(404, {"error": {"message": "model not found"}})
            data = {"title": "OK", "body": "<p>OK</p>"}
            if "generativelanguage" in url:
                return make_gemini_chat_response(data)
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        result = await self.ai.generate("test prompt")
        self.assertIsNotNone(result)
        self.assertGreater(call_count[0], 1)

    # ================================================================
    # 14. Empty hashtags not added to HTML
    # ================================================================
    async def test_empty_hashtags_no_html(self):
        article = {
            "title": "Test",
            "body": "<p>Body</p>",
            "extracted": {},
            "reading_time": 2,
            "source": {"name": "Src"},
        }
        html = self.processor.make_article_html(article)
        self.assertNotIn("<hr", html)

    # ================================================================
    # 15. Hashtags from AI are stored and preserved
    # ================================================================
    async def test_hashtags_preserved_through_full_cycle(self):
        self._setup_models_discovery()

        resp_iter = iter([
            {"title": "T", "body": "<p>B</p>", "introduction": "", "faq": [], "conclusion": ""},
            {"ministry": "t"},
            {"summary": "S"},
            {"notes": [], "keywords": "k", "hashtags": ["#h1", "#h2"]},
        ])

        async def mock_post(url, **kwargs):
            data = next(resp_iter)
            if "generativelanguage" in url:
                return make_gemini_chat_response(data)
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        fp = self.processor.enqueue_raw_post(TEST_RAW_TEXT)
        await self.ai.acquire_session()
        result = await self.processor._process_next_pending()
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["hashtags"], ["#h1", "#h2"])

        html = self.processor.make_article_html(result)
        self.assertIn("#h1", html)
        self.assertIn("#h2", html)

    # ================================================================
    # 15b. Disabled keys are skipped during rotation
    # ================================================================
    async def test_disabled_keys_skipped_in_rotation(self):
        _model_cache.clear()
        self._setup_models_discovery()

        gemini_hits = [0]
        success_hits = [0]

        async def mock_post(url, **kwargs):
            if "generativelanguage" in url:
                gemini_hits[0] += 1
                return make_gemini_fail_response(401, "API key not valid")
            success_hits[0] += 1
            data = {"title": "OK", "body": "<p>OK</p>"}
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        # Disable all Gemini keys so rotation has to skip the whole provider.
        for kid in list(self.key_manager._keys):
            if self.key_manager._keys[kid].get("_provider") == "gemini":
                await self.key_manager.mark_disabled(kid)

        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)
        # A disabled provider must never be selected as the session provider.
        self.assertNotEqual(self.ai._session_provider, "gemini")

        result = await self.ai.generate("test prompt")
        self.assertIsNotNone(result)
        self.assertEqual(gemini_hits[0], 0, "Disabled Gemini keys must never be called")
        self.assertGreaterEqual(success_hits[0], 1)

    # ================================================================
    # 15c. Performance stats are recorded across calls
    # ================================================================
    async def test_perf_stats_recorded_success_and_errors(self):
        _model_cache.clear()
        self._setup_models_discovery()

        call_count = [0]

        async def mock_post(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return make_gemini_fail_response(429, "rate limit")
            data = {"title": "OK", "body": "<p>OK</p>"}
            if "generativelanguage" in url:
                return make_gemini_chat_response(data)
            return make_openai_chat_response(data)

        self.ai._http.post = AsyncMock(side_effect=mock_post)

        session_ok = await self.ai.acquire_session()
        self.assertTrue(session_ok)

        result = await self.ai.generate("test prompt")
        self.assertIsNotNone(result)

        perf = self.key_manager.get_perf_stats()
        self.assertIn("requests", perf)
        self.assertGreaterEqual(perf["requests"], 2)
        self.assertGreaterEqual(perf["rate_limited"], 1)
        self.assertGreaterEqual(perf["success"], 1)
        self.assertIn("avg_latency_ms", perf)
        self.assertIn("by_provider", perf)

    # ================================================================
    # 15d. Exponential backoff defers a failed pending article
    # ================================================================
    async def test_backoff_defers_failed_pending_article(self):
        fp = self.processor.enqueue_raw_post(TEST_RAW_TEXT)
        pending = self.db.get_gemini_pending_queue()
        self.assertTrue(any(p.get("fingerprint") == fp for p in pending))

        # Simulate a failure via the retry path (generic exception, not key exhaustion).
        self.processor._handle_processing_failure(
            fp, TEST_RAW_TEXT, "", [], "ch1", RuntimeError("boom"), {}, section="general"
        )

        pending = self.db.get_gemini_pending_queue()
        item = next(p for p in pending if p.get("fingerprint") == fp)
        self.assertGreater(item.get("retry_after", 0), int(time.time()),
                           "retry_after must be set in the future after a failure")

        # A pending item still inside its backoff window must be deferred instantly.
        result = await self.processor._process_next_pending()
        self.assertIsNone(result)

        # Once the backoff window passes, processing is attempted again.
        item["retry_after"] = int(time.time()) - 1
        self.db.save_gemini_pending_queue(pending)
        self.ai._http.post = AsyncMock(return_value=make_gemini_fail_response(429, "rate limit"))
        self._setup_models_discovery()
        _model_cache.clear()
        await self.ai.acquire_session()
        # Key exhaustion is caught by _process_next_pending, which soft-fails -> None.
        result = await self.processor._process_next_pending()
        self.assertIsNone(result)


# ================================================================
# 16. Scheduler single-publish-per-cycle (no catch-up burst)
# ================================================================
class TestBloggerScheduler(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.db = InMemoryDB()
        self.db.data["channels"] = {
            "ch1": {
                "channel_id": "ch1", "enabled": True,
                "section": "general", "daily_limit": 10,
                "start_hour": 9, "end_hour": 23,
            }
        }
        self.db.data["published_ids"] = []
        self.db.data["stats"]["daily"] = {}
        self.ai = MagicMock()
        self.processor = MagicMock(spec=ArticleProcessor)
        self.processor._fingerprint.return_value = "test_fp"
        self.processor.make_article_html.return_value = "<p>Test</p>"
        self.processor.db = self.db
        self.publisher = MagicMock()
        self.publisher.config.is_enabled.return_value = True
        self.publisher.publish_article = AsyncMock(return_value="post_123")
        from modules.blogger.scheduler import BloggerScheduler
        self.scheduler = BloggerScheduler(self.db, self.processor, self.publisher)
        self.scheduler._queue = []

    def _make_article(self, title, fingerprint, channel_id="ch1"):
        return {
            "fingerprint": fingerprint,
            "title": title,
            "body": "<p>Body</p>",
            "status": "queued",
            "channel_id": channel_id,
            "section": "general",
            "labels": [],
            "source_text": title,
            "created_at": int(time.time()),
        }

    async def test_skips_past_slot_window_no_burst(self):
        """When scheduler starts late, past-slot windows are skipped one per cycle."""
        self.scheduler._queue = [
            self._make_article("Article 1", "fp1"),
            self._make_article("Article 2", "fp2"),
        ]
        for a in self.scheduler._queue:
            self.db.save_article(a["fingerprint"], a)

        import modules.blogger.scheduler as sched_mod
        _real_dt = sched_mod.datetime

        class FakeDatetime(_real_dt):
            @classmethod
            def now(cls):
                return _real_dt(2026, 7, 29, 9, 45, 0)
        sched_mod.datetime = FakeDatetime

        try:
            # Cycle 1: slot 0 (09:00-09:30) is past window → skip, last_slot=0
            await self.scheduler._process_queue()
            state = self.db.get_schedule_state()
            self.assertEqual(state["last_slot"], 0, "Slot 0 should be skipped")
            self.assertEqual(self.publisher.publish_article.call_count, 0,
                             "No publish when skipping past slot")

            # Cycle 2: slot 1 (09:30-10:00) is current window → publish
            await self.scheduler._process_queue()
            state = self.db.get_schedule_state()
            self.assertEqual(state["last_slot"], 1, "Slot 1 should be used for publish")
        finally:
            sched_mod.datetime = _real_dt

        self.assertEqual(self.publisher.publish_article.call_count, 1,
                         "Only one article per cycle")

    async def test_only_one_article_per_cycle(self):
        """Even with many queued articles, only one is published per _process_queue call."""
        self.scheduler._queue = [
            self._make_article("Article 1", "fp1"),
            self._make_article("Article 2", "fp2"),
            self._make_article("Article 3", "fp3"),
        ]
        for a in self.scheduler._queue:
            self.db.save_article(a["fingerprint"], a)

        import modules.blogger.scheduler as sched_mod
        _real_dt = sched_mod.datetime

        class FakeDatetime(_real_dt):
            @classmethod
            def now(cls):
                return _real_dt(2026, 7, 29, 10, 5, 0)
        sched_mod.datetime = FakeDatetime

        try:
            # Skip slots 0 and 1 (past windows), publish in slot 2 (10:00-10:30)
            for _ in range(3):
                await self.scheduler._process_queue()
        finally:
            sched_mod.datetime = _real_dt

        self.assertEqual(self.publisher.publish_article.call_count, 1,
                         "Only one article published across all cycles")

    async def test_no_publish_outside_window(self):
        """When current time is not within any slot window, no article is published."""
        self.scheduler._queue = [
            self._make_article("Article 1", "fp1"),
        ]
        for a in self.scheduler._queue:
            self.db.save_article(a["fingerprint"], a)

        self.db.save_schedule_state({"day": "2026-07-29", "last_slot": -1})

        import modules.blogger.scheduler as sched_mod
        _real_dt = sched_mod.datetime

        class FakeDatetime(_real_dt):
            @classmethod
            def now(cls):
                return _real_dt(2026, 7, 29, 23, 30, 0)
        sched_mod.datetime = FakeDatetime

        try:
            await self.scheduler._process_queue()
        finally:
            sched_mod.datetime = _real_dt

        self.assertEqual(self.publisher.publish_article.call_count, 0,
                         "No publish outside schedule window")

    # ================================================================
    # 16b. Gemini pending queue drains progressively (capped per cycle)
    # ================================================================
    async def test_gemini_pending_drains_progressively(self):
        from modules.blogger.scheduler import PROGRESSIVE_DRAIN_BATCH
        self.publisher.config.is_enabled.return_value = True

        calls = [0]

        def recovered(*args, **kwargs):
            calls[0] += 1
            # Mirrors the real processor: successful recovery removes the item.
            if self.db.get_gemini_pending_queue():
                self.db.remove_from_gemini_pending(0)
            return {
                "fingerprint": f"fp_{calls[0]}",
                "title": f"Article {calls[0]}",
                "body": "<p>Body</p>",
                "status": "queued",
                "channel_id": "ch1",
                "section": "general",
                "labels": ["عام", "اخبار"],
                "hashtags": ["#test"],
            }

        # MagicMock('_process_next_pending') is an un-awaitable default; patch side effect.
        self.processor._process_next_pending = AsyncMock(side_effect=recovered)

        # Simulate a large backlog present in the DB.
        pending = []
        for i in range(12):
            pending.append({
                "raw_text": f"text {i}", "source_url": "", "media": [],
                "fingerprint": f"fp_{i+1}", "channel_id": "ch1",
                "section": "general", "attempts": 0, "added_at": 0,
            })
        self.db.save_gemini_pending_queue(pending)

        await self.scheduler._process_gemini_pending()
        # Only PROGRESSIVE_DRAIN_BATCH articles were recovered in this single cycle.
        self.assertEqual(calls[0], PROGRESSIVE_DRAIN_BATCH,
                         "Pending recovery must be capped per cycle")
        # Remaining articles stay queued for the next cycle.
        remaining = self.db.get_gemini_pending_queue()
        self.assertEqual(len(remaining), 12 - PROGRESSIVE_DRAIN_BATCH)


# ================================================================
# 17. Details table + single apply section (mandatory variant checks)
# ================================================================
class TestArticleHtmlFormatting(unittest.TestCase):

    def setUp(self):
        self.db = InMemoryDB()
        self.ai = MagicMock()
        self.processor = ArticleProcessor(self.db, self.ai, {"default_jobs_image": ""})

    def _make_article(self, extracted=None, body=None, conclusion="", with_channel=True):
        art = {
            "title": "وظيفة في بغداد",
            "body": body or "<h2>طريقة التقديم</h2><p>أرسل سيرتك الذاتية.</p>",
            "extracted": extracted or {},
            "conclusion": conclusion,
            "hashtags": [],
        }
        if with_channel:
            art["source"] = {
                "name": "قناة الوظائف", "username": "jobs_iraq", "link": "https://t.me/jobs_iraq",
            }
        return art

    def _assert_order(self, html, markers):
        idxs = [html.find(m) for m in markers]
        self.assertNotIn(-1, idxs, f"missing marker: {markers}")
        self.assertEqual(idxs, sorted(idxs), f"wrong order: {dict(zip(markers, idxs))}")

    # ---------------- apply section: single source, fixed order ----------------

    def test_phone_only(self):
        html = self.processor.make_article_html(self._make_article({"phone": "07701234567"}))
        self.assertIn('href="tel:07701234567"', html)
        self.assertIn("apply-box-phone", html)
        self.assertIn("📞 معلومات التواصل", html)
        self.assertNotIn("mailto:", html)
        self.assertNotIn('class="apply-box apply-box-link"', html)
        self._assert_order(html, [
            "📞 معلومات التواصل", "📞 رقم الهاتف", "07701234567", "📞 اتصال", "💬 واتساب",
        ])

    def test_phone_and_email(self):
        extracted = {"phone": "07701234567", "email": "jobs@example.com"}
        html = self.processor.make_article_html(self._make_article(extracted))
        self.assertIn('href="mailto:jobs@example.com"', html)
        self.assertIn('href="tel:07701234567"', html)
        self.assertNotIn('class="apply-box apply-box-link"', html)
        self._assert_order(html, [
            "📞 معلومات التواصل", "📞 رقم الهاتف", "07701234567",
            "✉️ البريد الإلكتروني", "jobs@example.com",
        ])

    def test_phone_email_and_link(self):
        extracted = {
            "phone": "07701234567", "email": "jobs@example.com",
            "apply_url": "https://forms.gle/xyz",
        }
        html = self.processor.make_article_html(self._make_article(extracted))
        self.assertIn('apply-btn-now', html)
        self._assert_order(html, [
            "📞 معلومات التواصل", "📞 رقم الهاتف", "07701234567",
            "✉️ البريد الإلكتروني", "jobs@example.com",
            "🌐 رابط التقديم", "https://forms.gle/xyz",
        ])

    def test_email_only(self):
        html = self.processor.make_article_html(self._make_article({"email": "jobs@example.com"}))
        self.assertIn('href="mailto:jobs@example.com"', html)
        self.assertIn("✉️ البريد الإلكتروني", html)
        self.assertIn("📞 معلومات التواصل", html)
        self.assertNotIn('href="tel:', html)
        self.assertNotIn('class="apply-box apply-box-link"', html)
        self._assert_order(html, [
            "📞 معلومات التواصل", "✉️ البريد الإلكتروني", "jobs@example.com",
        ])

    def test_link_only(self):
        html = self.processor.make_article_html(self._make_article({"apply_url": "https://forms.gle/xyz"}))
        self.assertIn('href="https://forms.gle/xyz"', html)
        self.assertIn('apply-btn-now', html)
        self.assertNotIn("mailto:", html)
        self.assertNotIn('href="tel:', html)
        self._assert_order(html, [
            "📞 معلومات التواصل", "🌐 رابط التقديم", "https://forms.gle/xyz", ">التقديم<",
        ])

    def test_all_three_no_duplicates(self):
        extracted = {
            "phone": "07701234567", "email": "jobs@example.com",
            "apply_url": "https://forms.gle/xyz",
        }
        html = self.processor.make_article_html(self._make_article(extracted))
        self.assertEqual(html.count('class="apply-section"'), 1)
        self.assertEqual(html.count('href="mailto:jobs@example.com"'), 2)
        self.assertEqual(html.count('href="tel:07701234567"'), 2)
        self.assertEqual(html.count('href="https://forms.gle/xyz"'), 2)
        self.assertEqual(html.count('class="apply-btn apply-btn-now"'), 1)
        self.assertIn('href="https://wa.me/9647701234567"', html)

    def test_foreign_phone_no_whatsapp(self):
        html = self.processor.make_article_html(self._make_article({"phone": "+44 7700 900123"}))
        self.assertIn('href="tel:+447700900123"', html)
        self.assertNotIn("wa.me", html)

    def test_no_contacts_no_apply_section(self):
        html = self.processor.make_article_html(self._make_article({}))
        self.assertNotIn("📞 معلومات التواصل", html)
        self.assertNotIn('class="apply-', html)

    def test_ai_apply_paragraph_kept_once(self):
        art = self._make_article({"phone": "07701234567"},
                                 body="<h2>طريقة التقديم</h2><p>نص قديم يجب استبداله.</p>")
        html = self.processor.make_article_html(art)
        self.assertIn("نص قديم يجب استبداله", html)
        self.assertIn("📞 معلومات التواصل", html)
        self.assertEqual(html.count("📞 معلومات التواصل"), 1)

    def test_apply_section_first_kept_duplicates_removed(self):
        # CASE 1: single apply section + contacts -> kept
        # CASE 2/3: duplicated 2x/3x + contacts -> only first kept
        # CASE 5: apply section + no contacts -> untouched
        content = "إرسال السيرة الذاتية إلى job@example.com"
        for repeats in (1, 2, 3):
            body = ("<h2>المهام</h2><p>نص وسط.</p>" +
                    f"<h2>طريقة التقديم</h2><p>{content}</p>" * repeats)
            html = self.processor.make_article_html(
                self._make_article({"phone": "07701234567"}, body=body))
            visible = html.split("<script")[0]
            self.assertEqual(visible.count(content), 1, f"repeats={repeats}")
            self.assertEqual(visible.count("طريقة التقديم"), 1, f"repeats={repeats}")
            self.assertEqual(visible.count("نص وسط"), 1, f"repeats={repeats}")
            self.assertEqual(html.count("📞 معلومات التواصل"), 1, f"repeats={repeats}")
        no_contacts = self.processor.make_article_html(self._make_article(
            {}, body=f"<h2>طريقة التقديم</h2><p>{content}</p>"))
        visible2 = no_contacts.split("<script")[0]
        self.assertEqual(visible2.count(content), 1)
        self.assertNotIn("📞 معلومات التواصل", no_contacts)

    def test_apply_builder_log_once(self):
        with self.assertLogs("modules.blogger.processor", level="INFO") as cm:
            self.processor.make_article_html(self._make_article({"phone": "07701234567"}))
        msgs = [r.getMessage() for r in cm.records]
        self.assertEqual(msgs.count("Apply Builder Called"), 1)

    # ---------------- other sections untouched ----------------

    def test_benefits_table_intact(self):
        body = ('<h2>المميزات</h2>'
                '<table><tr><td>الراتب</td><td>800,000 دينار</td></tr>'
                '<tr><td>الدوام</td><td>8 ساعات</td></tr></table>'
                '<h2>طريقة التقديم</h2><p>نص قديم.</p>')
        html = self.processor.make_article_html(self._make_article({"phone": "07701234567"}, body=body))
        self.assertIn('class="job-table"', html)
        self.assertIn("800,000 دينار", html)
        self.assertIn("📞 معلومات التواصل", html)

    def test_no_table(self):
        html = self.processor.make_article_html(self._make_article({}))
        self.assertNotIn('class="job-table"', html)

    def test_legacy_div_kept_apply_section_once(self):
        body = ('<div style="background:#e8f5e9;border-right:4px solid #4caf50;padding:12px 16px;margin:15px 0;border-radius:4px;"><strong style="color:#2e7d32;">🔗 رابط التقديم</strong>'
                '<p><a href="https://forms.gle/dup">https://forms.gle/dup</a></p></div>'
                '<h2>طريقة التقديم</h2><p>نص.</p>')
        html = self.processor.make_article_html(self._make_article({"phone": "07701234567"}, body=body))
        self.assertEqual(html.count('class="apply-section"'), 1)
        self.assertIn("نص.", html)

    def test_conclusion_card(self):
        html = self.processor.make_article_html(
            self._make_article({}, conclusion="للمزيد من الوظائف اليومية تابع قناة قلعة الوظائف العراقية"))
        self.assertIn('class="article-end"', html)
        self.assertIn("قلعة الوظائف العراقية", html)

    def test_no_conclusion_no_card(self):
        html = self.processor.make_article_html(self._make_article({}))
        self.assertNotIn('class="article-end"', html)

    def test_professional_stylesheet_present(self):
        html = self.processor.make_article_html(self._make_article({}))
        self.assertIn("<style>", html)
        self.assertIn(".apply-box-phone", html)
        self.assertIn(".apply-btn-whatsapp", html)
        self.assertIn(".apply-btn-now", html)
        self.assertIn(".job-table", html)
        self.assertIn(".article-end", html)
        self.assertIn("@media (max-width:600px)", html)
        self.assertNotIn("details-table", html)

    # ---------------- single generator per section (no duplicates) ----------------

    def test_nav_section_body_kept_without_toc(self):
        body = ('<h2>التنقل السريع</h2><ul><li>رابط</li></ul>'
                '<h2>الوصف</h2><p>نص.</p>'
                '<h2>المميزات</h2><p>نص.</p>')
        html = self.processor.make_article_html(self._make_article({}, body=body))
        self.assertEqual(html.count('class="toc-box"'), 0)
        self.assertNotIn("📑 المحتويات", html)
        self.assertIn("التنقل السريع", html)

    def test_introduction_before_body_sections(self):
        art = self._make_article({}, body="<h2>الوصف</h2><p>نص.</p><h2>المميزات</h2><p>نص.</p>")
        art["introduction"] = "مقدمة المقال"
        html = self.processor.make_article_html(art)
        self.assertNotIn("📑 المحتويات", html)
        self.assertGreater(html.find("الوصف"), html.find(">المقدمة<"))

    def test_details_table_section_removed_entirely(self):
        html = self.processor.make_article_html(self._make_article({}))
        self.assertNotIn("ملخص تفاصيل الفرصة الوظيفية", html)
        self.assertNotIn("details-table", html)
        self.assertNotIn("الجهة المعلنة", html)

    def test_single_apply_section(self):
        extracted = {"phone": "07701234567", "email": "jobs@example.com",
                     "apply_url": "https://forms.gle/xyz"}
        html = self.processor.make_article_html(self._make_article(extracted))
        self.assertEqual(html.count('class="apply-section"'), 1)
        self.assertEqual(html.count("📞 معلومات التواصل"), 1)
        self.assertEqual(html.count('class="apply-row"'), 3)
        self.assertIn('href="mailto:jobs@example.com"', html)
        self.assertIn('href="tel:07701234567"', html)
        self.assertIn('href="https://forms.gle/xyz"', html)

    # ---------------- final template checks (requested UI) ----------------

    def test_title_heading_rendered(self):
        art = self._make_article({})
        art["title"] = "وظيفة قائد فريق"
        html = self.processor.make_article_html(art)
        self.assertIn('<h1 class="article-title">وظيفة قائد فريق</h1>', html)

    def test_no_quick_navigation_anywhere(self):
        art = self._make_article({}, body=(
            "<h2>التنقل السريع</h2><ul><li>رابط</li></ul>"
            "<h2>الوصف</h2><p>نص.</p><h2>المميزات</h2><p>نص.</p>"))
        html = self.processor.make_article_html(art)
        self.assertNotIn("📑 المحتويات", html)
        self.assertEqual(html.count('class="toc-box"'), 0)
        self.assertIn("التنقل السريع", html)

    def test_quick_navigation_only_section_kept(self):
        art = self._make_article({}, body="<h2>التنقل السريع</h2><ul><li>رابط</li></ul>")
        html = self.processor.make_article_html(art)
        self.assertNotIn("📑 المحتويات", html)
        self.assertEqual(html.count('class="toc-box"'), 0)

    def test_toc_never_rendered(self):
        art = self._make_article({}, body="<h2>الوصف</h2><p>نص.</p><h2>المميزات</h2><p>نص.</p>")
        html = self.processor.make_article_html(art)
        self.assertNotIn("📑 المحتويات", html)
        self.assertNotIn("Table of Contents", html)
        self.assertEqual(html.count('class="toc-box"'), 0)

    def test_contact_box_keeps_real_data(self):
        art = self._make_article({"phone": "07701234567", "email": "jobs@example.com"})
        html = self.processor.make_article_html(art)
        self.assertIn("📞 معلومات التواصل", html)
        self.assertIn("07701234567", html)
        self.assertIn("jobs@example.com", html)
        self.assertIn('href="tel:07701234567"', html)
        self.assertIn('href="mailto:jobs@example.com"', html)
        self.assertIn('class="apply-box"', html)

    def test_contact_box_uses_only_current_article_data(self):
        first = self.processor.make_article_html(self._make_article({
            "phone": "07700000001", "email": "first@example.com",
            "apply_url": "https://forms.example/first",
        }))
        self.assertIn("07700000001", first)
        self.assertIn("first@example.com", first)
        self.assertIn("https://forms.example/first", first)
        self.assertNotIn("second@example.com", first)
        self.assertNotIn("07700000002", first)
        second = self.processor.make_article_html(self._make_article({
            "phone": "07700000002", "email": "second@example.com",
            "apply_url": "https://forms.example/second",
        }))
        self.assertIn("07700000002", second)
        self.assertIn("second@example.com", second)
        self.assertIn("https://forms.example/second", second)
        self.assertNotIn("07700000001", second)
        self.assertNotIn("first@example.com", second)
        self.assertNotIn("https://forms.example/first", second)

    def test_multiple_phones_all_rendered(self):
        html = self.processor.make_article_html(self._make_article({
            "phone": "07700000001, 07700000002, 07700000003",
        }))
        self.assertEqual(html.count("📞 رقم الهاتف"), 3)
        self.assertEqual(html.count('href="tel:07700000001"'), 2)
        self.assertEqual(html.count('href="tel:07700000002"'), 2)
        self.assertEqual(html.count('href="tel:07700000003"'), 2)

    def test_no_fake_contact_rendered(self):
        html = self.processor.make_article_html(self._make_article({
            "phone": "غير متاح", "email": "ليس بريداً",
            "apply_url": "castlejobiq",
        }))
        self.assertNotIn("📞 معلومات التواصل", html)
        self.assertNotIn("href=\"tel:", html)
        self.assertNotIn("href=\"mailto:", html)

    def test_emails_list_all_rendered(self):
        html = self.processor.make_article_html(self._make_article({
            "email": ["hr@example.com", "admin@example.com"],
        }))
        self.assertEqual(html.count("✉️ البريد الإلكتروني"), 2)
        self.assertIn('href="mailto:hr@example.com"', html)
        self.assertIn('href="mailto:admin@example.com"', html)

    def test_telegram_section_with_castlejobiq_before_hashtags(self):
        art = self._make_article({"phone": "07701234567"})
        art["hashtags"] = ["وظائف", "بغداد"]
        art["conclusion"] = "نهاية المقال"
        html = self.processor.make_article_html(art)
        self.assertIn("📢 للمزيد من الوظائف", html)
        self.assertIn("🔵 اشترك في قناة الوظائف على تيليجرام", html)
        self.assertIn('href="https://t.me/CastleJobiq"', html)
        self.assertNotIn('>https://t.me/CastleJobiq<', html)
        self.assertLess(html.find('<div class="article-end">'), html.find('<div class="tg-card">'))
        self.assertLess(html.find('<div class="tg-card">'), html.find('<div class="hashtag-box">'))

    def test_contact_box_between_body_and_conclusion(self):
        art = self._make_article({"phone": "07701234567"}, body="<h2>الوصف</h2><p>نص.</p>")
        art["conclusion"] = "نهاية"
        html = self.processor.make_article_html(art)
        self.assertLess(html.find('<div class="sec-card"><h2 id="sec-0"'), html.find('<div class="apply-box">'))
        self.assertLess(html.find('<div class="apply-box">'), html.find('<div class="article-end">'))

    def test_no_source_section_anywhere(self):
        art = self._make_article({})
        html = self.processor.make_article_html(art)
        self.assertNotIn("المصدر", html)
        self.assertNotIn("Source URL", html)


# ================================================================
# 18. Source footer cleaning + Telegram links never apply methods
# ================================================================
class TestSourceFooterCleaning(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.db = InMemoryDB()
        self.ai = MagicMock()
        self.processor = ArticleProcessor(self.db, self.ai, {"default_jobs_image": ""})

    def _article(self, extracted=None, body=None):
        return {
            "title": "وظيفة في بغداد",
            "body": body or "<h2>الوصف</h2><p>نص.</p><h2>المميزات</h2><p>نص.</p>",
            "extracted": extracted or {},
            "conclusion": "",
            "hashtags": [],
        }

    # --- ad with phone only ---
    def test_phone_only_ad(self):
        raw = ("تعلن شركة عن وظيفة شاغرة\n"
               "07774411303\n"
               "للمزيد من الوظائف تابعوا قناتنا")
        cleaned = self.processor._clean_source_footer(raw)
        self.assertIn("07774411303", cleaned)
        self.assertNotIn("للمزيد من الوظائف", cleaned)
        html = self.processor.make_article_html(self._article({"phone": "07774411303"}))
        self.assertIn("apply-box-phone", html)
        self.assertNotIn('class="apply-box apply-box-mail"', html)
        self.assertNotIn('class="apply-box apply-box-link"', html)

    # --- ad with email only ---
    def test_email_only_ad(self):
        raw = "مطلوب موظف\nhr@company.com\nاشترك بقناتنا"
        cleaned = self.processor._clean_source_footer(raw)
        self.assertIn("hr@company.com", cleaned)
        self.assertNotIn("اشترك بقناتنا", cleaned)
        html = self.processor.make_article_html(self._article({"email": "hr@company.com"}))
        self.assertIn('href="mailto:hr@company.com"', html)
        self.assertNotIn('class="apply-box apply-box-phone"', html)

    # --- ad with apply link only ---
    def test_apply_link_only_ad(self):
        raw = "للتقديم عبر النموذج الرسمي\nhttps://forms.gle/xyz"
        cleaned = self.processor._clean_source_footer(raw)
        self.assertIn("https://forms.gle/xyz", cleaned)
        html = self.processor.make_article_html(self._article({"apply_url": "https://forms.gle/xyz"}))
        self.assertIn("🌐 رابط التقديم", html)
        self.assertIn("apply-btn-now", html)

    # --- ad with phone + email + link ---
    def test_phone_email_link_ad(self):
        raw = ("07774411303\nhr@company.com\nhttps://company.com/jobs\n"
               "تابعونا على قناتنا")
        cleaned = self.processor._clean_source_footer(raw)
        self.assertIn("07774411303", cleaned)
        self.assertIn("hr@company.com", cleaned)
        self.assertIn("https://company.com/jobs", cleaned)
        self.assertNotIn("تابعونا", cleaned)
        html = self.processor.make_article_html(self._article({
            "phone": "07774411303", "email": "hr@company.com",
            "apply_url": "https://company.com/jobs",
        }))
        self.assertEqual(html.count('class="apply-section"'), 1)
        self._assert_order(html, [
            "📞 رقم الهاتف", "✉️ البريد الإلكتروني", "🌐 رابط التقديم",
        ])

    def _assert_order(self, html, markers):
        idxs = [html.find(m) for m in markers]
        self.assertNotIn(-1, idxs, f"missing marker: {markers}")
        self.assertEqual(idxs, sorted(idxs), f"wrong order: {dict(zip(markers, idxs))}")

    # --- ad with Telegram link only ---
    def test_telegram_link_only_ignored(self):
        cleaned = self.processor._clean_source_footer("وظيفة شاغرة\nhttps://t.me/CastleJobiq")
        self.assertNotIn("t.me", cleaned)
        html = self.processor.make_article_html(self._article({"apply_url": "https://t.me/CastleJobiq"}))
        self.assertNotIn('class="apply-section"', html)
        self.assertNotIn('class="apply-box apply-box-link"', html)
        self.assertEqual(html.count('href="https://t.me/CastleJobiq"'), 1)

    # --- Telegram signature at the bottom of the ad ---
    def test_telegram_signature_at_bottom_cleaned(self):
        raw = ("07774411303\nhr@company.com\nhttps://company.com/jobs\n"
               "ولمتابعة المزيد من الوظائف تابع قناة قلعة الوظائف العراقية على التليجرام\n"
               "https://t.me/CastleJobiq")
        cleaned = self.processor._clean_source_footer(raw)
        self.assertIn("07774411303", cleaned)
        self.assertIn("hr@company.com", cleaned)
        self.assertIn("https://company.com/jobs", cleaned)
        self.assertNotIn("تابع قناة", cleaned)
        self.assertNotIn("t.me", cleaned)
        self.assertNotIn("CastleJobiq", cleaned)
        self.assertNotIn("التليجرام", cleaned)
        html = self.processor.make_article_html(self._article({
            "phone": "07774411303", "email": "hr@company.com",
            "apply_url": "https://company.com/jobs",
        }))
        self.assertNotIn('class="apply-box apply-box-link"', html)
        self.assertEqual(html.count('href="https://t.me/CastleJobiq"'), 1)

    # --- "للمزيد من الوظائف تابع قناة CastleJobiq" ---
    def test_follow_channel_phrase_removed(self):
        cleaned = self.processor._clean_source_footer("للمزيد من الوظائف تابع قناة CastleJobiq")
        self.assertEqual(cleaned, "")

    # --- @CastleJobiq username ---
    def test_at_channel_username_removed(self):
        cleaned = self.processor._clean_source_footer("وظيفة شاغرة\n@CastleJobiq")
        self.assertEqual(cleaned, "وظيفة شاغرة")

    # --- multiple Telegram links ---
    def test_multiple_telegram_links_removed(self):
        raw = ("07774411303\n"
               "https://t.me/CastleJobiq\n"
               "https://telegram.me/CastleJobs\n"
               "https://tlgrm.me/join\n"
               "hr@company.com")
        cleaned = self.processor._clean_source_footer(raw)
        self.assertIn("07774411303", cleaned)
        self.assertIn("hr@company.com", cleaned)
        self.assertNotIn("t.me", cleaned)
        self.assertNotIn("telegram", cleaned)

    # --- ad with no contacts at all ---
    def test_no_contacts_no_apply_section(self):
        html = self.processor.make_article_html(self._article({}))
        self.assertNotIn('class="apply-', html)
        self.assertNotIn("آلية التقديم والتواصل", html)

    # --- Telegram apply_url defensively ignored in HTML even if extracted ---
    def test_telegram_apply_url_dropped_but_phone_kept(self):
        html = self.processor.make_article_html(self._article({
            "phone": "07774411303", "apply_url": "https://t.me/CastleJobiq",
        }))
        self.assertEqual(html.count('class="apply-section"'), 1)
        self.assertIn("apply-box-phone", html)
        self.assertNotIn('class="apply-box apply-box-link"', html)
        self.assertEqual(html.count('href="https://t.me/CastleJobiq"'), 1)

    # --- pipeline passes cleaned text to rewrite/extract ---
    async def test_pipeline_extract_receives_cleaned_text(self):
        raw = ("07774411303\nhr@company.com\nhttps://company.com/jobs\n"
               "ولمتابعة المزيد من الوظائف\nhttps://t.me/CastleJobiq")
        self.processor._rewrite = AsyncMock(return_value={
            "title": "وظيفة", "body": "<p>نص</p>", "introduction": "",
            "faq": [], "conclusion": "",
        })
        self.processor._extract = AsyncMock(return_value={
            "phone": "07774411303", "email": "hr@company.com",
            "apply_url": "https://company.com/jobs",
        })
        self.processor._summary = AsyncMock(return_value={"summary": "ملخص"})
        self.processor._metadata = AsyncMock(return_value={
            "notes": [], "keywords": "", "hashtags": ["#وظائف"],
        })
        await self.processor._run_pipeline({"fingerprint": "f1"}, raw)
        prompt = self.processor._extract.await_args.args[0]
        self.assertNotIn("t.me", prompt)
        self.assertNotIn("CastleJobiq", prompt)
        self.assertNotIn("لمتابعة المزيد", prompt)
        self.assertIn("07774411303", prompt)
        self.assertIn("hr@company.com", prompt)
        self.assertIn("https://company.com/jobs", prompt)


if __name__ == "__main__":
    unittest.main()
