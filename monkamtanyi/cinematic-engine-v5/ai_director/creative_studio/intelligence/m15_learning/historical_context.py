"""
M15.3 Historical Context

Native historical-learning context producer for MOK.

This module owns the boundary between retrieved learning candidates
and downstream M15 decision intelligence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .retrieval import M15NativeLearningRetrieval


class M15HistoricalContext:
    """Produce authoritative M15.3 historical learning context."""

    VERSION = "M15.3"
    SCHEMA_VERSION = 1

    def __init__(
        self,
        retrieval: M15NativeLearningRetrieval | None = None,
        learning_root: str | Path | None = None,
    ) -> None:
        self.retrieval = retrieval or M15NativeLearningRetrieval(
            learning_root=learning_root
        )

    def build(
        self,
        query: Optional[Dict[str, Any]] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Produce the canonical historical_context object consumed by
        downstream M15 intelligence.
        """
        context = self.retrieval.build_context(
            query=query,
            limit=limit,
        )

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "historical_context": context,
            "learning_candidates": context["learning_candidates"],
            "candidate_count": context["candidate_count"],
            "evidence_available": context["evidence_available"],
            "source": context["source"],
            "status": context["status"],
        }

    def for_decision(
        self,
        query: Optional[Dict[str, Any]] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Produce a clean historical_context payload for M15.4.

        No decision is made here. This is strictly a context boundary.
        """
        result = self.build(query=query, limit=limit)

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "learning_candidates": result["learning_candidates"],
            "candidate_count": result["candidate_count"],
            "evidence_available": result["evidence_available"],
            "source": result["source"],
            "status": result["status"],
        }

    def summary(self) -> Dict[str, Any]:
        """Return historical-context health information."""
        retrieval_summary = self.retrieval.summary()

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "retrieval": retrieval_summary,
            "status": (
                "HISTORICAL_CONTEXT_READY"
                if retrieval_summary["status"]
                in {"RETRIEVAL_READY", "RETRIEVAL_READY_NO_DATA"}
                else "HISTORICAL_CONTEXT_UNAVAILABLE"
            ),
        }
