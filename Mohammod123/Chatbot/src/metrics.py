"""RAG metrics collected through pipeline hooks."""

from __future__ import annotations

import time
from collections import deque
from threading import RLock
from typing import Any

from src.hooks import HookManager


class RagMetrics:
    """Thread-safe counters and latency stats for the RAG pipeline."""

    def __init__(self, latency_window: int = 200) -> None:
        self._lock = RLock()
        self._started_at = time.time()
        self._total_queries = 0
        self._answered_queries = 0
        self._blocked_queries = 0
        self._cache_hits = 0
        self._tool_calls = 0
        self._no_context_queries = 0
        self._retrieval_counts: deque[int] = deque(maxlen=latency_window)
        self._top_scores: deque[float] = deque(maxlen=latency_window)
        self._latencies: deque[float] = deque(maxlen=latency_window)

    def bind(self, hooks: HookManager) -> None:
        """Subscribe to pipeline events."""
        hooks.register("query_start", self._on_query_start)
        hooks.register("cache_hit", self._on_cache_hit)
        hooks.register("retrieval_done", self._on_retrieval_done)
        hooks.register("tool_called", self._on_tool_called)
        hooks.register("query_blocked", self._on_query_blocked)
        hooks.register("query_end", self._on_query_end)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable metrics summary."""
        with self._lock:
            latencies = sorted(self._latencies)
            retrievals = list(self._retrieval_counts)
            scores = list(self._top_scores)

            return {
                "uptime_seconds": round(time.time() - self._started_at, 1),
                "queries": {
                    "total": self._total_queries,
                    "answered": self._answered_queries,
                    "blocked_by_guardrails": self._blocked_queries,
                    "cache_hits": self._cache_hits,
                    "no_relevant_context": self._no_context_queries,
                    "tool_calls": self._tool_calls,
                },
                "latency_seconds": {
                    "avg": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
                    "p50": round(latencies[len(latencies) // 2], 3) if latencies else 0.0,
                    "p95": round(latencies[int(len(latencies) * 0.95) - 1], 3)
                    if len(latencies) >= 2
                    else (round(latencies[0], 3) if latencies else 0.0),
                    "max": round(latencies[-1], 3) if latencies else 0.0,
                },
                "retrieval": {
                    "avg_chunks_returned": round(sum(retrievals) / len(retrievals), 2)
                    if retrievals
                    else 0.0,
                    "avg_top_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
                },
            }

    def _on_query_start(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._total_queries += 1

    def _on_cache_hit(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._cache_hits += 1

    def _on_retrieval_done(self, payload: dict[str, Any]) -> None:
        with self._lock:
            count = int(payload.get("count", 0))
            self._retrieval_counts.append(count)
            if count == 0:
                self._no_context_queries += 1
            else:
                self._top_scores.append(float(payload.get("top_score", 0.0)))

    def _on_tool_called(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._tool_calls += 1

    def _on_query_blocked(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._blocked_queries += 1

    def _on_query_end(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._latencies.append(float(payload.get("latency", 0.0)))
            if payload.get("answered"):
                self._answered_queries += 1
