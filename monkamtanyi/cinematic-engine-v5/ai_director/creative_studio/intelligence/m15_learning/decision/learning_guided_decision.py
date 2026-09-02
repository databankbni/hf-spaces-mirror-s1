"""
MOK M15 Learning-Guided Decision Engine
M15.4

Consumes historical learning context from M15.3 and produces
advisory decision context.

This layer does not execute production actions.
It converts learned historical evidence into decision guidance.
"""

from __future__ import annotations

from typing import Any, Dict, List


class LearningGuidedDecisionEngine:
    """
    Converts retrieved learning context into advisory decisions.

    M15.4 deliberately remains advisory-only. It does not mutate
    M13/M14 runtime behavior and does not execute autonomous actions.
    """

    VERSION = "M15.4"

    def __init__(
        self,
        minimum_confidence: float = 0.70,
    ) -> None:
        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError(
                "minimum_confidence must be between 0.0 and 1.0"
            )

        self.minimum_confidence = minimum_confidence

    @staticmethod
    def _safe_float(
        value: Any,
        default: float = 0.0,
    ) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def analyze(
        self,
        historical_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Analyze M15.3 historical context.

        Expected M15.3 context includes:
        - learning_records
        - confirmed_patterns
        - counts
        - status
        """

        if not isinstance(historical_context, dict):
            raise TypeError(
                "historical_context must be a dictionary"
            )

        learning_records: List[Dict[str, Any]] = list(
            historical_context.get(
                "learning_records",
                [],
            )
        )

        confirmed_patterns: List[Dict[str, Any]] = list(
            historical_context.get(
                "confirmed_patterns",
                [],
            )
        )

        counts = historical_context.get(
            "counts",
            {},
        )

        if not isinstance(counts, dict):
            counts = {}

        decision_signals: List[Dict[str, Any]] = []

        for pattern in confirmed_patterns:
            if not isinstance(pattern, dict):
                continue

            learning_type = pattern.get(
                "learning_type",
                "UNKNOWN",
            )

            average_value = self._safe_float(
                pattern.get("average_value"),
            )

            evidence_count = int(
                self._safe_float(
                    pattern.get("evidence_count"),
                )
            )

            decision_signals.append(
                {
                    "learning_type": learning_type,
                    "average_value": average_value,
                    "evidence_count": evidence_count,
                    "signal": "HISTORICAL_PATTERN_CONFIRMED",
                }
            )

        if confirmed_patterns:
            recommendation = "USE_HISTORICAL_GUIDANCE"
            confidence = min(
                1.0,
                max(
                    self.minimum_confidence,
                    sum(
                        self._safe_float(
                            pattern.get("average_value"),
                            0.0,
                        )
                        for pattern in confirmed_patterns
                    )
                    / len(confirmed_patterns),
                ),
            )
        elif learning_records:
            recommendation = "CONTINUE_OBSERVATION"
            confidence = 0.50
        else:
            recommendation = "INSUFFICIENT_LEARNING_CONTEXT"
            confidence = 0.0

        return {
            "version": self.VERSION,
            "mode": "advisory_decision_mode",
            "recommendation": recommendation,
            "confidence": round(confidence, 4),
            "historical_context_available": bool(
                learning_records or confirmed_patterns
            ),
            "decision_signals": decision_signals,
            "counts": {
                "signals": counts.get("signals", 0),
                "learning_records": counts.get(
                    "learning_records",
                    len(learning_records),
                ),
                "confirmed_patterns": counts.get(
                    "confirmed_patterns",
                    len(confirmed_patterns),
                ),
            },
            "status": "DECISION_CONTEXT_AVAILABLE",
        }

    def summarize(
        self,
        historical_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Produce a compact advisory decision summary.
        """

        result = self.analyze(
            historical_context
        )

        return {
            "version": result["version"],
            "mode": result["mode"],
            "recommendation": result["recommendation"],
            "confidence": result["confidence"],
            "status": result["status"],
        }
