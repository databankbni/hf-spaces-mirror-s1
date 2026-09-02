from __future__ import annotations
from .registry import PluginRegistry
from .builtin import register_builtins

class SectionManager:
    """Central registry: new sections are plugins, not edits to the core pipeline."""
    def __init__(self, registry=None):
        self.registry=registry or PluginRegistry()
        register_builtins(self.registry)
        self.registry.discover()

    def get(self, name):
        return self.registry.get(name)

    def list(self):
        return self.registry.all()
