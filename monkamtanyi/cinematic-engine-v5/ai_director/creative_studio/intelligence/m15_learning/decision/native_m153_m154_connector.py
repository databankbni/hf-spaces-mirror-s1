"""MOK-owned authoritative M15.3 -> M15.4 decision connector.

This module is the explicit integration boundary between:

    M15 execution evidence
        -> verified learning candidates
        -> M15.3 native retrieval
        -> M15.3 historical context
        -> M15.4 decision intelligence

The connector does not create evidence, modify evidence, or bypass
the evidence authority established by the M15 learning pipeline.
"""

from __future__ import annotations

from typing import Any, Dict

from ai_director.creative_studio.intelligence.m15_learning.historical_context import (
    M15HistoricalContext,
)
from ai_director.creative_studio.intelligence.m15_learning.retrieval import (
    M15NativeLearningRetrieval,
)
from ai_director.creative_studio.intelligence.m15_learning.decision.learning_guided_decision import (
    LearningGuidedDecisionEngine,
)
from ai_director.creative_studio.intelligence.m15_learning.decision_integration import (
    LearningGuidedDecisionIntegration,
)


class MOKM153M154DecisionConnector:
    """Authoritative MOK-owned M15.3 -> M15.4 integration boundary."""

    VERSION = "M15.4-MOK-CONNECTOR"
    SCHEMA_VERSION = 1

    def __init__(
        self,
        retrieval: M15NativeLearningRetrieval | None = None,
        historical_context: M15HistoricalContext | None = None,
        decision_engine: LearningGuidedDecisionEngine | None = None,
        decision_integration: LearningGuidedDecisionIntegration | None = None,
    ) -> None:
        self.retrieval = retrieval or M15NativeLearningRetrieval()
        self.historical_context = historical_context or M15HistoricalContext(
            retrieval=self.retrieval
        )
        self.decision_engine = decision_engine or LearningGuidedDecisionEngine()
        self.decision_integration = decision_integration or LearningGuidedDecisionIntegration(
            decision_engine=self.decision_engine
        )

    def build_decision_context(self, limit: int = 10) -> Dict[str, Any]:
        """
        Build the authoritative M15.3 -> M15.4 decision context.

        Evidence authority remains entirely inside M15.3 retrieval and
        historical-context construction. This connector only composes
        those already-authoritative boundaries with M15.4.
        """
        if not isinstance(limit, int):
            raise TypeError("limit must be an integer")

        if limit < 1:
            raise ValueError("limit must be greater than zero")

        historical_context = self.historical_context.for_decision(
            limit=limit
        )

        decision_context = self.decision_integration.build_decision_context(
            historical_context
        )

        learning_candidates = historical_context.get(
            "learning_candidates",
            [],
        )

        if not isinstance(learning_candidates, list):
            raise TypeError(
                "M15.3 historical context learning_candidates must be a list"
            )

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "authority_chain": [
                "m15_execution_evidence",
                "verified_learning_candidate",
                "m15_3_native_retrieval",
                "m15_3_historical_context",
                "m15_4_decision_engine",
            ],
            "historical_context": historical_context,
            "decision_context": decision_context,
            "candidate_count": len(learning_candidates),
            "evidence_available": bool(learning_candidates),
            "source": "MOK_NATIVE_M153_M154_CONNECTOR",
            "status": (
                "DECISION_CONTEXT_AVAILABLE"
                if learning_candidates
                else "DECISION_CONTEXT_READY_NO_LEARNING_DATA"
            ),
        }

    def summary(self) -> Dict[str, Any]:
        """Return an infrastructure summary without fabricating evidence."""
        retrieval_summary = self.retrieval.summary()

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "retrieval": retrieval_summary,
            "status": "MOK_M153_M154_CONNECTOR_READY",
        }
