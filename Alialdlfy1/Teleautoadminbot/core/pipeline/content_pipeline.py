from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

@dataclass
class PipelineResult:
    status: str
    data: Any = None
    reason: str = ""
    stage: str = ""

class ContentPipeline:
    """
    Common pipeline for Blogger, News, Sports and future sections.
    Services plug into the same stages instead of duplicating business logic.
    """
    def __init__(self, gate, queue, ai_gateway=None, publisher=None):
        self.gate=gate
        self.queue=queue
        self.ai=ai_gateway
        self.publisher=publisher

    def ingest(self, article: str, article_id: str, source: str, target: Optional[str]=None):
        # gate API is intentionally duck-typed to preserve the existing implementation.
        verdict=self.gate.check(article)
        if not getattr(verdict,"accepted",False):
            return PipelineResult("rejected", reason=getattr(verdict,"reason","blocked"), stage="gate")
        job=self.queue.enqueue_article(article_id, {"article":article,"source":source,"target":target})
        return PipelineResult("queued", data={"job_id":job}, stage="queue")

    def process(self, payload: dict):
        if not self.ai:
            raise RuntimeError("AI gateway is not configured")
        result=self.ai.article_package(payload["article"])
        return result
