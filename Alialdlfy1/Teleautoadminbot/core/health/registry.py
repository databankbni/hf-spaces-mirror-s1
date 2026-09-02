from dataclasses import dataclass, field
from datetime import datetime, timezone

@dataclass
class Health:
    name: str; ok: bool; message: str=''; latency_ms: float|None=None; updated_at: str=field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class HealthRegistry:
    def __init__(self): self._items={}
    def set(self, name, ok, message='', latency_ms=None): self._items[name]=Health(name,ok,message,latency_ms)
    def snapshot(self): return {k:v.__dict__.copy() for k,v in self._items.items()}
