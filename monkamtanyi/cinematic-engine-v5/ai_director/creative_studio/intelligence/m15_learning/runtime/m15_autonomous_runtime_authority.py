from __future__ import annotations


from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_runtime_authority import MOKRuntimeAuthority
"""
M15 ARCHITECTURAL FREEZE

This module is a legacy/duplicate execution surface.

CANONICAL AUTHORITY:
    native_execution_authority.py

CANONICAL BINDING:
    mok_production_binding.py

CANONICAL EXECUTOR:
    mok_native_production_executor.py

M15_ARCHITECTURAL_FREEZE

Do not introduce new production callers here.
Do not add new authorization logic here.
Do not treat this module as an execution authority.
"""

"""
MOK M15 Autonomous Runtime Authority.

This module is the authoritative M15.4 -> M15.5 runtime boundary.

Architecture:
    M15.3 retrieval
        -> historical context
        -> M15.4 decision
        -> M15.5 execution preparation
        -> MOK runtime authorization
        -> MOK production execution
        -> execution record

The runtime authority never fabricates learning evidence.
It never treats a handoff package as completed execution.
It never executes an unauthorized decision.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ai_director.creative_studio.intelligence.m15_learning.decision.native_m153_m154_connector import (
    MOKM153M154DecisionConnector,
)
from ai_director.creative_studio.intelligence.m15_learning.execution.autonomous_execution import (
    AutonomousCreativeExecution,
)
from ai_director.production_execution.execution_engine import ExecutionEngine


class M15AutonomousRuntimeAuthority:
    """
    MOK-owned runtime authority connecting M15.4 to M15.5.

    This class owns the runtime transition.
    It does not manufacture evidence and does not silently authorize
    execution when the upstream decision boundary has not authorized it.
    """

    VERSION = "M15.5-MOK-RUNTIME-AUTHORITY"
    SCHEMA_VERSION = 1
    AUTHORITY = "MOK_AUTONOMOUS_RUNTIME"

    def __init__(
        self,
        connector: Optional[MOKM153M154DecisionConnector] = None,
        execution_engine: Optional[ExecutionEngine] = None,
    ) -> None:
        self.connector = connector or MOKM153M154DecisionConnector()
        self.execution_authority = AutonomousCreativeExecution()
        self.execution_engine = execution_engine or ExecutionEngine()
        self.execution_history = []

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def build_runtime_context(self, limit: int = 10) -> Dict[str, Any]:
        """
        Build the authoritative M15.3 -> M15.4 runtime context.

        This is composition only. Evidence remains owned by M15.3.
        """
        context = self.connector.build_decision_context(limit=limit)

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "authority": self.AUTHORITY,
            "source": context.get("source"),
            "authority_chain": context.get("authority_chain", []),
            "historical_context": context.get("historical_context", {}),
            "decision_context": context.get("decision_context", {}),
            "candidate_count": context.get("candidate_count", 0),
            "evidence_available": context.get("evidence_available", False),
            "upstream_status": context.get("status"),
            "status": "RUNTIME_CONTEXT_READY",
        }

    def authorize_execution(
        self,
        execution_package: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        MOK-owned execution authorization gate.

        Authorization requires all of the following:
          1. upstream execution package exists;
          2. evidence is explicitly available;
          3. candidate count is greater than zero;
          4. decision context exists;
          5. upstream preparation explicitly authorizes execution.

        No-data or handoff-only states are rejected honestly.
        """
        decision_intake = execution_package.get("decision_intake", {})
        runtime_handoff = execution_package.get("runtime_handoff", {})
        decision_context = execution_package.get("decision_context", {})

        evidence_available = bool(
            execution_package.get("evidence_available", False)
        )
        candidate_count = execution_package.get("candidate_count", 0)
        upstream_authorized = bool(
            runtime_handoff.get("execution_authorized", False)
        )

        reasons = []

        if not evidence_available:
            reasons.append("NO_VERIFIED_LEARNING_EVIDENCE")

        if not isinstance(candidate_count, int) or candidate_count <= 0:
            reasons.append("NO_LEARNING_CANDIDATES")

        if not isinstance(decision_context, dict) or not decision_context:
            reasons.append("NO_DECISION_CONTEXT")

        if not upstream_authorized:
            reasons.append("UPSTREAM_EXECUTION_NOT_AUTHORIZED")

        authorized = len(reasons) == 0

        return {
            "authority": self.AUTHORITY,
            "authorized": authorized,
            "execution_authorized": authorized,
            "reasons": reasons,
            "decision_intake": decision_intake,
            "status": (
                "EXECUTION_AUTHORIZED"
                if authorized
                else "EXECUTION_BLOCKED"
            ),
        }

    def prepare(
        self,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Prepare the complete M15 runtime transition.

        No production action is performed here.
        """
        runtime_context = self.build_runtime_context(limit=limit)

        decision_context = runtime_context["decision_context"]

        execution_package = self.execution_authority.prepare_execution(
            decision_context
        )

        enriched_package = dict(execution_package)
        enriched_package["candidate_count"] = runtime_context["candidate_count"]
        enriched_package["evidence_available"] = runtime_context["evidence_available"]
        enriched_package["decision_context"] = decision_context
        enriched_package["authority_chain"] = runtime_context["authority_chain"]
        enriched_package["source"] = runtime_context["source"]

        authorization = self.authorize_execution(enriched_package)

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "authority": self.AUTHORITY,
            "runtime_context": runtime_context,
            "execution_package": enriched_package,
            "authorization": authorization,
            "status": authorization["status"],
        }

    def execute(
        self,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Execute only after MOK authorization succeeds.

        The underlying production execution engine remains responsible
        for the actual production action. This class owns the authority
        transition and records the observable result.
        """
        prepared = self.prepare(limit=limit)
        authorization = prepared["authorization"]
        package = prepared["execution_package"]

        execution_record = {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "authority": self.AUTHORITY,
            "execution_id": None,
            "started_at": None,
            "completed_at": None,
            "authorized": authorization["authorized"],
            "status": None,
            "result": None,
            "verification": {
                "status": "NOT_EXECUTED",
                "evidence": None,
            },
        }

        if not authorization["authorized"]:
            execution_record["status"] = "EXECUTION_BLOCKED"
            execution_record["blocked_reasons"] = authorization["reasons"]
            return {
                "prepared": prepared,
                "execution": execution_record,
                "status": "EXECUTION_BLOCKED",
            }

        execution_id = "mok-m15-" + self._timestamp().replace(":", "").replace(".", "")
        execution_record["execution_id"] = execution_id
        execution_record["started_at"] = self._timestamp()

        result = self.execution_engine.execute(
            package["execution_plan"]
        )

        execution_record["result"] = result
        execution_record["completed_at"] = self._timestamp()
        execution_record["status"] = "EXECUTION_COMPLETED"

        execution_record["verification"] = {
            "status": "OBSERVATION_RECORDED",
            "evidence": {
                "execution_id": execution_id,
                "engine_result_present": result is not None,
                "result_type": type(result).__name__,
            },
        }

        self.execution_history.append(execution_record)

        return {
            "prepared": prepared,
            "execution": execution_record,
            "status": "EXECUTION_COMPLETED",
        }

    def summary(self, limit: int = 10) -> Dict[str, Any]:
        prepared = self.prepare(limit=limit)

        return {
            "version": self.VERSION,
            "schema_version": self.SCHEMA_VERSION,
            "authority": self.AUTHORITY,
            "candidate_count": prepared["runtime_context"]["candidate_count"],
            "evidence_available": prepared["runtime_context"]["evidence_available"],
            "execution_authorized": prepared["authorization"]["authorized"],
            "authorization_status": prepared["authorization"]["status"],
            "execution_history_count": len(self.execution_history),
            "status": prepared["status"],
        }

    def execute_authoritative_production(self, execution_context):
        from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_runtime_authority import MOKRuntimeAuthority as CanonicalMOKRuntimeAuthority
        runtime = CanonicalMOKRuntimeAuthority()
        return runtime.execute_authoritative_production(execution_context)
