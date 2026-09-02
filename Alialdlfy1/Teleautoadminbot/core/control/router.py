from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional

@dataclass
class CallbackAction:
    callback: str
    handler: Callable

class ControlRouter:
    """Additive callback router; existing bot callbacks remain untouched."""
    def __init__(self):
        self._handlers: dict[str, Callable] = {}

    def register(self, callback: str, handler: Callable):
        self._handlers[callback]=handler

    def dispatch(self, callback: str, *args, **kwargs):
        handler=self._handlers.get(callback)
        if handler is None:
            raise KeyError(f"Unknown callback: {callback}")
        return handler(*args, **kwargs)

    def has(self, callback: str) -> bool:
        return callback in self._handlers
