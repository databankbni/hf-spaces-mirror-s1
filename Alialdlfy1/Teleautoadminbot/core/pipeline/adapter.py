from __future__ import annotations
from typing import Any

class SectionPipelineAdapter:
    """Small adapter layer for Blogger/News/Sports/future sections."""
    def __init__(self, section: str, gate, queue, ai_gateway, publisher):
        self.section=section; self.gate=gate; self.queue=queue
        self.ai=ai_gateway; self.publisher=publisher

    def submit(self, item_id: str, text: str, source_url: str="", channel_id: str="", **meta):
        verdict=self.gate.preflight(text, source_url, channel_id)
        if not verdict.allowed:
            return {"status":"rejected","reason":verdict.reason,"matched":list(verdict.matched)}
        job=self.queue.enqueue_article(item_id, {"section":self.section,"text":text,"source_url":source_url,**meta})
        return {"status":"queued","job_id":job,"fingerprint":verdict.fingerprint}

    def process(self, text: str, **kwargs):
        response=self.ai.article_package(text, **kwargs)
        data=response.data
        return data if isinstance(data,dict) else {"result":data}

    def publish(self, item_id: str, target: str, content: str, **kwargs):
        return self.publisher.publish(target,item_id,content,**kwargs)
