"""
MOK M15 Learning-Guided Decision Integration
M15.4

Connects M15.3 historical learning retrieval with the M15.4
advisory decision engine.
"""

from __future__ import annotations

from typing import Any, Dict


class LearningGuidedDecisionIntegration:
    """
    Integration boundary between M15.3 retrieval and M15.4 decisions.
    """

    VERSION = "M15.4"

    def __init__(
        self,
        decision_engine: Any,
    ) -> None:
        if decision_engine is None:
            raise ValueError(
                "decision_engine is required"
            )

        self.decision_engine = decision_engine

    def build_decision_context(
        self,
        historical_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Transform historical learning context into advisory
        decision context.
        """

        result = self.decision_engine.analyze(
            historical_context
        )

        return {
            "integration": (
                "MOK M15 Learning-Guided Decision Integration"
            ),
            "version": self.VERSION,
            "historical_context": historical_context,
            "decision": result,
            "mode": "advisory_decision_mode",
            "status": "DECISION_CONTEXT_AVAILABLE",
        }

    def summary(
        self,
        historical_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = self.build_decision_context(
            historical_context
        )

        return {
            "version": self.VERSION,
            "recommendation": result["decision"][
                "recommendation"
            ],
            "confidence": result["decision"][
                "confidence"
            ],
            "mode": result["mode"],
            "status": result["status"],
        }
