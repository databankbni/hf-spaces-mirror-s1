from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass(frozen=True)
class SectionConfig:
    key: str
    title: str
    source: str
    content_type: str
    settings_namespace: str
    callbacks_namespace: str
    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)

class SectionAdapter:
    """Common contract; each section has isolated configuration/state but shared infrastructure."""
    def __init__(self, config: SectionConfig, pipeline, publisher=None):
        self.config=config
        self.pipeline=pipeline
        self.publisher=publisher

    def ingest(self, article: str, article_id: str, target=None):
        return self.pipeline.ingest(
            article=article,
            article_id=f"{self.config.key}:{article_id}",
            source=self.config.source,
            target=target,
        )

    def process(self, payload: dict):
        return self.pipeline.process(payload)

    def status(self):
        return {"section":self.config.key,"enabled":self.config.enabled,"options":dict(self.config.options)}

    def set_option(self, name: str, value: Any):
        opts=dict(self.config.options)
        opts[name]=value
        object.__setattr__(self.config,"options",opts)

# News and Sports are deliberately separate sections, while sharing the same capabilities.
NEWS = SectionConfig(
    key="news", title="📰 الأخبار", source="news",
    content_type="news", settings_namespace="news",
    callbacks_namespace="news", options={}
)
SPORTS = SectionConfig(
    key="sports", title="⚽ الرياضة", source="sports",
    content_type="sports", settings_namespace="sports",
    callbacks_namespace="sports", options={}
)
