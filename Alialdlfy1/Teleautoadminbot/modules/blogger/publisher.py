import asyncio
import time
import hashlib
import logging
from typing import Optional, Dict, Any

from modules.blogger.database import BloggerDatabase
from modules.blogger.blogger_client import BloggerClient
from modules.blogger.config import BloggerConfig
from modules.blogger.ai_manager import AIClient, AIKeyManager
from modules.blogger.processor import ArticleProcessor
from modules.blogger.scheduler import BloggerScheduler
from core.runtime.integration import RuntimeIntegration
from core.runtime.legacy_bridge import LegacyRuntimeBridge

logger = logging.getLogger(__name__)


class BloggerPublisher:
    def __init__(self, runtime=None):
        self.db = BloggerDatabase()
        self.config = BloggerConfig(self.db)
        self.client = BloggerClient(self.db, self.config)
        self.key_manager = AIKeyManager(self.db)
        self.ai = AIClient(self.key_manager)
        self.runtime = runtime or RuntimeIntegration(db=self.db, db_path="data/p29_runtime.sqlite3", project_root=".")
        self.bridge = LegacyRuntimeBridge(self.runtime, "blogger")
        self.runtime.register_publisher("blogger", self._runtime_publish_adapter)
        self.processor = ArticleProcessor(self.db, self.ai, self.config, runtime=self.runtime, section="blogger")
        self._runtime_worker = None
        self._runtime_worker_thread = None
        self.scheduler = BloggerScheduler(self.db, self.processor, self)
        self._running = False

    async def start(self):
        self._running = True
        logger.info("BloggerPublisher: started")
        asyncio.create_task(self.scheduler.start())
        self._runtime_worker = self.bridge.worker(worker_id="blogger-runtime")
        import threading
        self._runtime_worker_thread = threading.Thread(target=self._runtime_worker.run_forever, name="p29-blogger-runtime", daemon=True)
        self._runtime_worker_thread.start()
        logger.info("BloggerPublisher: Phase 18 runtime cutover active")

    async def stop(self):
        self._running = False
        await self.scheduler.stop()
        if self._runtime_worker:
            self._runtime_worker.stop()
        if self._runtime_worker_thread:
            self._runtime_worker_thread.join(timeout=3)
        await self.ai.close()
        await self.client.close()
        logger.info("BloggerPublisher: stopped")

    def is_running(self):
        return self._running


    def _runtime_publish_adapter(self, content, idempotency_key=None, article=None, **kwargs):
        payload = dict(article or {})
        if "content" not in payload:
            payload["content"] = content
        result = LegacyRuntimeBridge.call_async(self.client.publish(payload, draft=False))
        if not result:
            raise RuntimeError("legacy Blogger publisher returned no remote id")
        return {"remote_id": result, "legacy": True}

    async def test_connection(self) -> bool:
        logger.info("BloggerPublisher: testing connection")
        ok = await self.client.test_connection()
        logger.info(f"BloggerPublisher: connection test {'OK' if ok else 'FAILED'}")
        return ok

    async def publish_article(self, article: Dict[str, Any], fingerprint: str = None, draft: bool = False) -> Optional[str]:
        title = article.get("title", "")[:30]
        logger.info(f"BloggerPublisher: publish_article called for '{title}'")
        if not self.config.is_enabled():
            logger.warning(f"BloggerPublisher: publisher is disabled, skipping '{title}'")
            return None
        if not self.client.is_configured():
            logger.warning(f"BloggerPublisher: Blogger not configured, skipping '{title}'")
            return None
        if not fingerprint:
            fingerprint = hashlib.md5(article.get("title", "").encode("utf-8")).hexdigest()
            logger.info(f"BloggerPublisher: generated fingerprint {fingerprint[:16]}...")
        if self.db.is_published(fingerprint):
            logger.info(f"BloggerPublisher: article already published: {fingerprint[:16]}...")
            return None
        logger.info(f"BloggerPublisher: calling client.publish for '{title}'")
        post_id = await self.client.publish(article, draft=draft)
        if post_id:
            self.db.mark_published(fingerprint)
            self.db.add_log({
                "time": int(time.time()),
                "type": "publish",
                "post_id": post_id,
                "title": article.get("title", ""),
                "status": "success",
            })
            logger.info(f"BloggerPublisher: publish SUCCESS for '{title}', post_id={post_id}")
            return post_id
        self.db.mark_failed()
        self.db.add_log({
            "time": int(time.time()),
            "type": "publish",
            "title": article.get("title", ""),
            "status": "failed",
        })
        logger.error(f"BloggerPublisher: publish FAILED for '{title}'")
        return None
