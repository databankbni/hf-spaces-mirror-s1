"""
M15.3 Native Learning Retrieval

Authoritative retrieval boundary for MOK learning evidence.

This module deliberately reads immutable learning candidates produced
by M15LearningEvidenceBridge. It does not invent evidence, mutate source
records, or depend on an external retrieval implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class M15NativeLearningRetrieval:
    """
    Native M15.3 retrieval engine.

    Source of truth: learning candidate JSON artifacts produced by
    M15LearningEvidenceBridge.
    """

    VERSION = "M15.3"
    SCHEMA_VERSION = 1

    def __init__(self, learning_root: str | Path | None = None) -> None:
        if learning_root is None:
            learning_root = (
                Path(__file__).resolve().parent
                / "learning_candidates"
            )

        self.learning_root = Path(learning_root)

    def _candidate_files(self) -> List[Path]:
        """Return only real JSON candidate artifacts."""
        if not self.learning_root.is_dir():
            return []

        return sorted(
            path
            for path in self.learning_root.glob("*.json")
            if path.is_file()
        )

    @staticmethod
    def _load_candidate(path: Path) -> Optional[Dict[str, Any]]:
        """Load one candidate without modifying it."""
        try:
            with path.open("r", encoding="utf-8") as handle:
                candidate = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(candidate, dict):
            return None

        return candidate

    @staticmethod
    def _matches_query(
        candidate: Dict[str, Any],
        query: Optional[Dict[str, Any]],
    ) -> bool:
        """
        Apply conservative field matching.

        Empty queries match all valid candidates.
        Unknown query fields are ignored rather than inventing semantics.
        """
        if not query:
            return True

        for key, expected in query.items():
            if expected is None:
                continue

            actual = candidate.get(key)

            if isinstance(expected, (list, tuple, set)):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False

        return True

    def retrieve(
        self,
        query: Optional[Dict[str, Any]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve immutable learning candidates.

        Only candidates that are valid dictionaries and explicitly carry
        a learning_hash are accepted as authoritative learning records.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")

        results: List[Dict[str, Any]] = []

        for path in self._candidate_files():
            candidate = self._load_candidate(path)

            if candidate is None:
                continue

            if not candidate.get("learning_hash"):
                continue

            if not self._matches_query(candidate, query):
                continue

            results.append(dict(candidate))

            if len(results) >= limit:
                break

        return results

    def retrieve_by_execution_id(
        self,
        execution_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve one candidate by authoritative execution identifier."""
        if not execution_id:
            raise ValueError("execution_id is required")

        results = self.retrieve(
            query={"execution_id": execution_id},
            limit=1,
        )

        return results[0] if results else None

    def count(self) -> int:
        """Return count of readable authoritative candidates."""
        return len(self.retrieve(limit=10**9))

    def build_context(
        self,
        query: Optional[Dict[str, Any]] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Build the M15.3 historical context contract."""
        candidates = self.retrieve(query=query, limit=limit)

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "query": dict(query or {}),
            "candidate_count": len(candidates),
            "learning_candidates": candidates,
            "evidence_available": bool(candidates),
            "source": "M15LearningEvidenceBridge",
            "status": (
                "HISTORICAL_LEARNING_CONTEXT_AVAILABLE"
                if candidates
                else "NO_HISTORICAL_LEARNING_EVIDENCE"
            ),
        }

    def summary(self) -> Dict[str, Any]:
        """Return a compact retrieval health summary."""
        count = self.count()

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "learning_root": str(self.learning_root),
            "candidate_count": count,
            "status": (
                "RETRIEVAL_READY"
                if count > 0
                else "RETRIEVAL_READY_NO_DATA"
            ),
        }
