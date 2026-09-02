"""Phase 18 legacy-runtime compatibility bridge.

Keeps the public legacy Blogger interfaces intact while routing automatic
ingestion through the P29 runtime.  The bridge is deliberately small: section
adapters own external APIs, while RuntimeIntegration owns gate/queue/AI/
validation/idempotency/health.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Optional

from core.runtime.integration import RuntimeIntegration


class LegacyRuntimeBridge:
    def __init__(self, runtime: RuntimeIntegration, section: str = "blogger"):
        self.runtime = runtime
        self.section = section

    def ingest(self, raw_text: str, article_id: str, *, source: str = "", source_url: str = "",
               channel_id: str = "", target: str = "", metadata: Optional[dict] = None):
        return self.runtime.ingest(
            self.section, raw_text, article_id,
            source=source, source_url=source_url, channel_id=channel_id,
            target=target or self.section, metadata=metadata,
        )

    def worker(self, worker_id: Optional[str] = None):
        return self.runtime.build_worker(worker_id=worker_id)

    @staticmethod
    def call_async(awaitable):
        """Run a legacy async adapter from a synchronous runtime worker safely."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        result, error = [], []
        def runner():
            try:
                result.append(asyncio.run(awaitable))
            except BaseException as exc:
                error.append(exc)
        thread = threading.Thread(target=runner, daemon=True)
        thread.start(); thread.join()
        if error:
            raise error[0]
        return result[0] if result else None
