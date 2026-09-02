"""Simple event hook system so modules can observe the RAG pipeline."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

HookHandler = Callable[[dict[str, Any]], None]


class HookManager:
    """Register handlers for pipeline events and emit them safely.

    Events used by the pipeline:
    - query_start:     {"query": str}
    - cache_hit:       {"query": str}
    - retrieval_done:  {"count": int, "top_score": float}
    - tool_called:     {"tool": str}
    - query_blocked:   {"reason": str}
    - query_end:       {"latency": float, "answered": bool}
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[HookHandler]] = defaultdict(list)

    def register(self, event: str, handler: HookHandler) -> None:
        self._handlers[event].append(handler)

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        """Call all handlers for the event; a failing hook never breaks the pipeline."""
        for handler in self._handlers.get(event, []):
            try:
                handler(payload or {})
            except Exception:
                logger.exception("Hook handler for event '%s' failed.", event)
