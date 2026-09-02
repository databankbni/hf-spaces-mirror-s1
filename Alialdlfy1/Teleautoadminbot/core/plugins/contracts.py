from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol

@dataclass(frozen=True)
class SectionSpec:
    name: str
    kind: str
    version: str = "1"
    secret_names: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ("ingest", "process", "publish")
    metadata: dict[str, Any] = field(default_factory=dict)

class SectionAdapter(Protocol):
    spec: SectionSpec
    def ingest(self, item: dict[str, Any]) -> dict[str, Any]: ...
    def process(self, item: dict[str, Any], ai_gateway: Any) -> dict[str, Any]: ...
    def publish(self, item: dict[str, Any], publisher: Any) -> dict[str, Any]: ...
