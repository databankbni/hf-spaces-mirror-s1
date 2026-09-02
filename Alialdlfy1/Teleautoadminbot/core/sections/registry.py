from __future__ import annotations
from .base import SectionAdapter, NEWS, SPORTS, SectionConfig

BLOGGER = SectionConfig(
    key="blogger", title="🌐 Blogger", source="blogger",
    content_type="blogger", settings_namespace="blogger",
    callbacks_namespace="blogger", options={}
)

class SectionRegistry:
    def __init__(self, pipeline, publisher=None, include_blogger=False):
        self.sections={
            "news": SectionAdapter(NEWS,pipeline,publisher),
            "sports": SectionAdapter(SPORTS,pipeline,publisher),
        }
        if include_blogger:
            self.sections["blogger"]=SectionAdapter(BLOGGER,pipeline,publisher)

    def get(self,key): return self.sections[key]
    def keys(self): return tuple(self.sections)
    def statuses(self): return {k:v.status() for k,v in self.sections.items()}
    def register(self, adapter: SectionAdapter):
        if adapter.config.key in self.sections:
            raise ValueError(f"section already exists: {adapter.config.key}")
        self.sections[adapter.config.key]=adapter
