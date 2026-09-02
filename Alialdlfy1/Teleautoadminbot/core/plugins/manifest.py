from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class PluginManifest:
    key: str
    version: str
    section: str
    adapter: str
    enabled: bool=True

class PluginRegistry:
    def __init__(self): self._items={}
    def register(self,manifest,adapter):
        if manifest.key in self._items: raise ValueError("duplicate plugin")
        self._items[manifest.key]=(manifest,adapter)
    def get(self,key): return self._items[key][1]
    def manifests(self): return [x[0] for x in self._items.values()]
