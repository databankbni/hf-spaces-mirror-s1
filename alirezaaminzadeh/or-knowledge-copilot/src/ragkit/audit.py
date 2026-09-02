"""In-memory audit log for retrieval queries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ragkit.models import QueryResult


class QueryAuditStore:
    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def record(self, result: QueryResult, actor: str = "analyst", role: str = "user") -> None:
        self._rows.append(
            {
                "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "actor": actor,
                "role": role,
                "question": result.question[:160],
                "confidence": round(result.confidence, 3),
                "level": result.confidence_level.value,
                "citations": len(result.citations),
                "abstained": result.abstained,
                "route": result.route,
            }
        )

    def rows(self) -> list[dict[str, Any]]:
        return list(reversed(self._rows))

    def stats(self) -> dict[str, Any]:
        if not self._rows:
            return {
                "total_queries": 0,
                "avg_confidence": 0.0,
                "high_confidence": 0,
                "abstained": 0,
            }
        conf = [r["confidence"] for r in self._rows]
        return {
            "total_queries": len(self._rows),
            "avg_confidence": round(sum(conf) / len(conf), 4),
            "high_confidence": sum(1 for r in self._rows if r["level"] == "high"),
            "abstained": sum(1 for r in self._rows if r["abstained"]),
        }
