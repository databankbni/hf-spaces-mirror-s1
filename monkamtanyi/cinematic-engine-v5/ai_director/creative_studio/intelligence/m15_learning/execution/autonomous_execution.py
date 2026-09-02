"""
MOK M15.5 Autonomous Creative Execution Intelligence

Transforms an approved M15.4 advisory decision context into an
execution-ready autonomous creative workflow.

M15.5 does not execute production actions. It creates and validates
the workflow and runtime handoff contract required by downstream
production systems.
"""

from __future__ import annotations

from typing import Any, Dict, List


class AutonomousCreativeExecution:
    """
    M15.5 execution planning and workflow generation boundary.
    """

    VERSION = "M15.5"

    def __init__(self) -> None:
        self.integration_name = (
            "MOK M15 Autonomous Creative Execution Intelligence"
        )

    def intake_decision(
        self,
        decision_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Consume and validate the M15.4 decision context.
        """

        if not isinstance(decision_context, dict):
            raise TypeError(
                "decision_context must be a dictionary"
            )

        decision = decision_context.get("decision")

        if not isinstance(decision, dict):
            raise ValueError(
                "M15.4 decision context must contain a decision object"
            )

        recommendation = decision.get("recommendation")

        if not recommendation:
            raise ValueError(
                "M15.4 decision must contain a recommendation"
            )

        return {
            "decision": decision,
            "recommendation": recommendation,
            "confidence": decision.get("confidence"),
            "source_mode": decision_context.get(
                "mode",
                "advisory_decision_mode",
            ),
            "source_status": decision_context.get(
                "status",
                "DECISION_CONTEXT_AVAILABLE",
            ),
            "status": "DECISION_ACCEPTED",
        }

    def build_execution_plan(
        self,
        decision_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Convert an M15.4 decision into an execution plan.
        """

        intake = self.intake_decision(decision_context)

        recommendation = intake["recommendation"]

        return {
            "plan_type": "autonomous_creative_execution",
            "version": self.VERSION,
            "recommendation": recommendation,
            "confidence": intake["confidence"],
            "objective": (
                f"Execute creative workflow aligned with: "
                f"{recommendation}"
            ),
            "status": "EXECUTION_PLAN_READY",
        }

    def generate_workflow(
        self,
        execution_plan: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Generate an ordered production workflow.
        """

        if not isinstance(execution_plan, dict):
            raise TypeError(
                "execution_plan must be a dictionary"
            )

        recommendation = execution_plan.get(
            "recommendation"
        )

        if not recommendation:
            raise ValueError(
                "execution_plan must contain a recommendation"
            )

        return [
            {
                "step": 1,
                "action": "prepare_creative_context",
                "objective": (
                    "Prepare assets, constraints, and creative intent"
                ),
                "status": "READY",
            },
            {
                "step": 2,
                "action": "configure_production_workflow",
                "objective": (
                    "Configure the production sequence from the decision"
                ),
                "recommendation": recommendation,
                "status": "READY",
            },
            {
                "step": 3,
                "action": "execute_render_workflow",
                "objective": (
                    "Hand the prepared workflow to the production runtime"
                ),
                "status": "READY_FOR_RUNTIME",
            },
            {
                "step": 4,
                "action": "collect_execution_result",
                "objective": (
                    "Capture downstream execution results for M15.6"
                ),
                "status": "READY_FOR_FEEDBACK",
            },
        ]

    def create_runtime_handoff(
        self,
        execution_plan: Dict[str, Any],
        workflow: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Produce a runtime handoff contract without executing it.
        """

        return {
            "handoff_type": (
                "autonomous_creative_runtime_handoff"
            ),
            "version": self.VERSION,
            "execution_plan": execution_plan,
            "workflow": workflow,
            "execution_authorized": False,
            "runtime_action": "HANDOFF_ONLY",
            "status": "RUNTIME_HANDOFF_READY",
        }

    def prepare_execution(
        self,
        decision_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build the complete M15.5 execution-ready package.
        """

        intake = self.intake_decision(
            decision_context
        )

        execution_plan = self.build_execution_plan(
            decision_context
        )

        workflow = self.generate_workflow(
            execution_plan
        )

        handoff = self.create_runtime_handoff(
            execution_plan,
            workflow,
        )

        return {
            "integration": self.integration_name,
            "version": self.VERSION,
            "decision_intake": intake,
            "execution_plan": execution_plan,
            "workflow": workflow,
            "runtime_handoff": handoff,
            "production_readiness": {
                "ready": True,
                "execution_authorized": False,
                "status": "PRODUCTION_EXECUTION_READY",
            },
            "status": "EXECUTION_READY",
        }

    def summary(
        self,
        decision_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Return a compact execution-readiness summary.
        """

        result = self.prepare_execution(
            decision_context
        )

        return {
            "version": result["version"],
            "recommendation": result[
                "decision_intake"
            ]["recommendation"],
            "confidence": result[
                "decision_intake"
            ]["confidence"],
            "workflow_steps": len(
                result["workflow"]
            ),
            "execution_authorized": result[
                "runtime_handoff"
            ]["execution_authorized"],
            "status": result["status"],
        }
