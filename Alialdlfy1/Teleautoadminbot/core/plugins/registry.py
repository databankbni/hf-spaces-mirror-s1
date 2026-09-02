"""Plugin discovery without hard-coding future providers."""
from dataclasses import dataclass, field
from importlib.metadata import entry_points

@dataclass
class PluginSpec:
    name: str
    kind: str
    factory: object | None = None
    secrets: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

class PluginRegistry:
    def __init__(self): self._plugins = {}
    def register(self, spec: PluginSpec): self._plugins[spec.name] = spec
    def get(self, name): return self._plugins.get(name)
    def all(self): return dict(self._plugins)
    def discover(self, group="p29.plugins"):
        eps = entry_points()
        eps = eps.select(group=group) if hasattr(eps, 'select') else eps.get(group, [])
        for ep in eps:
            obj = ep.load(); spec = obj() if callable(obj) else obj
            self.register(spec)
        return self.all()
