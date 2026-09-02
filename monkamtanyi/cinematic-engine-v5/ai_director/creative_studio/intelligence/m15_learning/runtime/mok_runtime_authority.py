from __future__ import annotations


from ai_director.platform.execution.mok_native_production_executor import MOKNativeProductionExecutor
from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_native_production_executor import MOKNativeProductionExecutor
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
MOK Autonomous AI Studio
M15.4 -> M15.5 Runtime Authority

MOK-owned runtime authority boundary.

Authority chain:

    M15.3 evidence
        ->
    historical context
        ->
    M15.4 decision
        ->
    M15.5 execution package
        ->
    MOK Runtime Authority
        ->
    authorization
        ->
    execution
        ->
    verification
        ->
    execution evidence

This module does not fabricate execution success.

An execution is considered executed only when a real executor
callable is actually invoked.

Verification is considered proven only when a verifier
actually validates the observed execution result.
"""


from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
import hashlib
import json
import uuid


class MOKRuntimeAuthority:
    """
    MOK-owned authoritative runtime boundary.
    """

    VERSION = "1.0.0"

    AUTHORITY = (
        "MOK_AUTONOMOUS_RUNTIME_AUTHORITY"
    )

    def __init__(
        self,
        executor: Optional[
            Callable[[Dict[str, Any]], Any]
        ] = None,
        verifier: Optional[
            Callable[
                [Any, Dict[str, Any]],
                Dict[str, Any]
            ]
        ] = None,
    ) -> None:

        self.executor = executor
        self.verifier = verifier

    # --------------------------------------------------------
    # Runtime identity
    # --------------------------------------------------------

    def _execution_id(self) -> str:

        return (
            "mok-exec-"
            + uuid.uuid4().hex
        )

    def _timestamp(self) -> str:

        return datetime.now(
            timezone.utc
        ).isoformat()

    # --------------------------------------------------------
    # Execution package fingerprint
    # --------------------------------------------------------

    def _fingerprint(
        self,
        execution_package: Dict[str, Any],
    ) -> str:

        canonical = json.dumps(
            execution_package,
            sort_keys=True,
            default=str,
        ).encode("utf-8")

        return hashlib.sha256(
            canonical
        ).hexdigest()

    # --------------------------------------------------------
    # Validate M15.5 package
    # --------------------------------------------------------

    def validate_execution_package(
        self,
        execution_package: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not isinstance(
            execution_package,
            dict,
        ):

            raise TypeError(
                "execution_package must be a dictionary"
            )

        required = (
            "version",
            "decision_intake",
            "execution_plan",
            "workflow",
            "runtime_handoff",
        )

        missing = [
            key
            for key in required
            if key not in execution_package
        ]

        if missing:

            raise ValueError(
                "M15.5 execution package is incomplete: "
                + ", ".join(missing)
            )

        handoff = execution_package.get(
            "runtime_handoff"
        )

        if not isinstance(
            handoff,
            dict,
        ):

            raise ValueError(
                "runtime_handoff must be a dictionary"
            )

        workflow = execution_package.get(
            "workflow"
        )

        if not isinstance(
            workflow,
            list,
        ):

            raise ValueError(
                "workflow must be a list"
            )

        return {
            "valid": True,
            "required_fields": list(
                required
            ),
            "workflow_steps": len(
                workflow
            ),
            "source_status":
                execution_package.get(
                    "status"
                ),
        }

    # --------------------------------------------------------
    # Authorization
    # --------------------------------------------------------

    def authorize(
        self,
        execution_package: Dict[str, Any],
    ) -> Dict[str, Any]:

        validation = (
            self.validate_execution_package(
                execution_package
            )
        )

        execution_id = (
            self._execution_id()
        )

        return {
            "execution_id":
                execution_id,

            "authority":
                self.AUTHORITY,

            "version":
                self.VERSION,

            "authorized":
                True,

            "authorization_basis": {
                "m155_package_valid":
                    validation["valid"],

                "workflow_steps":
                    validation[
                        "workflow_steps"
                    ],

                "source_status":
                    validation[
                        "source_status"
                    ],
            },

            "authorized_at":
                self._timestamp(),

            "status":
                "EXECUTION_AUTHORIZED",
        }

    # --------------------------------------------------------
    # Execute
    # --------------------------------------------------------

    def execute(
        self,
        execution_package: Dict[str, Any],
    ) -> Dict[str, Any]:

        authorization = (
            self.authorize(
                execution_package
            )
        )

        execution_id = (
            authorization[
                "execution_id"
            ]
        )

        started_at = (
            self._timestamp()
        )

        package_fingerprint = (
            self._fingerprint(
                execution_package
            )
        )

        # ----------------------------------------------------
        # IMPORTANT:
        # No executor means no production execution claim.
        # ----------------------------------------------------

        if self.executor is None:

            return {
                "execution_id":
                    execution_id,

                "authority":
                    self.AUTHORITY,

                "version":
                    self.VERSION,

                "authorized":
                    True,

                "executed":
                    False,

                "verified":
                    False,

                "execution_evidence":
                    None,

                "status":
                    "EXECUTOR_NOT_BOUND",

                "started_at":
                    started_at,

                "completed_at":
                    None,

                "package_fingerprint":
                    package_fingerprint,

                "reason":
                    (
                        "MOK runtime authority is established "
                        "but no production executor is bound."
                    ),
            }

        # ----------------------------------------------------
        # Actual executor invocation
        # ----------------------------------------------------

        try:

            execution_result = (
                self.executor(
                    execution_package
                )
            )

            completed_at = (
                self._timestamp()
            )

            verification = (
                self.verify(
                    execution_result,
                    execution_package,
                )
            )

            verified = bool(
                verification.get(
                    "verified",
                    False,
                )
            )

            status = (
                "EXECUTION_VERIFIED"
                if verified
                else
                "EXECUTION_COMPLETED_UNVERIFIED"
            )

            return {

                "execution_id":
                    execution_id,

                "authority":
                    self.AUTHORITY,

                "version":
                    self.VERSION,

                "authorized":
                    True,

                "executed":
                    True,

                "verified":
                    verified,

                "execution_result":
                    execution_result,

                "execution_evidence": {

                    "execution_id":
                        execution_id,

                    "started_at":
                        started_at,

                    "completed_at":
                        completed_at,

                    "package_fingerprint":
                        package_fingerprint,

                    "executor_bound":
                        True,

                    "result_observed":
                        True,
                },

                "verification":
                    verification,

                "status":
                    status,

                "started_at":
                    started_at,

                "completed_at":
                    completed_at,
            }

        except Exception as exc:

            completed_at = (
                self._timestamp()
            )

            return {

                "execution_id":
                    execution_id,

                "authority":
                    self.AUTHORITY,

                "version":
                    self.VERSION,

                "authorized":
                    True,

                "executed":
                    False,

                "verified":
                    False,

                "execution_evidence": {

                    "execution_id":
                        execution_id,

                    "started_at":
                        started_at,

                    "completed_at":
                        completed_at,

                    "package_fingerprint":
                        package_fingerprint,

                    "executor_bound":
                        True,

                    "result_observed":
                        False,
                },

                "status":
                    "EXECUTION_FAILED",

                "error": {

                    "type":
                        type(exc).__name__,

                    "message":
                        str(exc),
                },

                "started_at":
                    started_at,

                "completed_at":
                    completed_at,
            }

    # --------------------------------------------------------
    # Verification
    # --------------------------------------------------------

    def verify(
        self,
        execution_result: Any,
        execution_package: Dict[str, Any],
    ) -> Dict[str, Any]:

        if self.verifier is not None:

            result = (
                self.verifier(
                    execution_result,
                    execution_package,
                )
            )

            if not isinstance(
                result,
                dict,
            ):

                raise TypeError(
                    "MOK verifier must return a dictionary"
                )

            return result

        # Never fabricate verification.

        return {

            "verified":
                False,

            "verification_authority":
                self.AUTHORITY,

            "status":
                "VERIFICATION_NOT_BOUND",

            "reason":
                (
                    "Execution occurred but no MOK "
                    "verification implementation is bound."
                ),
        }

    # --------------------------------------------------------
    # Complete runtime operation
    # --------------------------------------------------------

    def run(
        self,
        execution_package: Dict[str, Any],
    ) -> Dict[str, Any]:

        result = (
            self.execute(
                execution_package
            )
        )

        runtime_authority_proven = bool(
            result.get(
                "authorized"
            )
            and result.get(
                "executed"
            )
        )

        verification_proven = bool(
            result.get(
                "verified"
            )
        )

        result[
            "runtime_authority_proven"
        ] = (
            runtime_authority_proven
        )

        result[
            "verification_proven"
        ] = (
            verification_proven
        )

        if verification_proven:

            result[
                "authority_status"
            ] = (
                "RUNTIME_AUTHORITY_AND_VERIFICATION_PROVEN"
            )

        elif runtime_authority_proven:

            result[
                "authority_status"
            ] = (
                "RUNTIME_AUTHORITY_PROVEN_VERIFICATION_PENDING"
            )

        elif (
            result.get("status")
            == "EXECUTOR_NOT_BOUND"
        ):

            result[
                "authority_status"
            ] = (
                "RUNTIME_BOUNDARY_ESTABLISHED_EXECUTOR_PENDING"
            )

        else:

            result[
                "authority_status"
            ] = (
                "RUNTIME_AUTHORITY_NOT_PROVEN"
            )

        return result

    def execute_authoritative_production(self, runtime_context):
        """Execute production through the single canonical MOK authority chain."""
        from ai_director.creative_studio.intelligence.m15_learning.runtime.mok_native_production_decision import MOKNativeProductionDecision
        from ai_director.platform.execution.mok_native_production_executor import MOKNativeProductionExecutor as CanonicalMOKNativeProductionExecutor

        if not isinstance(runtime_context, dict):
            raise TypeError("runtime_context must be a dictionary")

        authoritative_context = dict(runtime_context)

        existing_request = authoritative_context.get("production_request")

        if existing_request is None:
            decision_authority = MOKNativeProductionDecision()
            decision = decision_authority.decide(authoritative_context)

            if not bool(decision.get("authorized", False)):
                return {
                    "authority": self.AUTHORITY,
                    "authorized": False,
                    "executed": False,
                    "verified": False,
                    "status": decision.get(
                        "status",
                        "PRODUCTION_DECISION_REFUSED",
                    ),
                    "decision": decision,
                    "reason": decision.get(
                        "reason",
                        "Native production decision refused execution.",
                    ),
                }

            production_request = decision.get("production_request")

            if not isinstance(production_request, dict):
                raise RuntimeError(
                    "Authorized native decision did not produce a production_request."
                )

            authoritative_context["production_request"] = production_request
            authoritative_context["production_decision"] = decision
            authoritative_context["decision_authority"] = decision.get("authority")

            executable = production_request.get("executable")
            arguments = production_request.get("arguments")
            expected_artifacts = production_request.get("expected_artifacts")

            if not isinstance(executable, str) or not executable.strip():
                raise RuntimeError(
                    "Native production decision did not provide a valid executable."
                )

            if not isinstance(arguments, (list, tuple)):
                raise RuntimeError(
                    "Native production decision did not provide valid arguments."
                )

            if not all(isinstance(argument, str) for argument in arguments):
                raise RuntimeError(
                    "Native production arguments must contain strings only."
                )

            if not isinstance(expected_artifacts, (list, tuple)):
                raise RuntimeError(
                    "Native production decision did not provide expected artifacts."
                )

            if not all(
                isinstance(artifact, str) and artifact.strip()
                for artifact in expected_artifacts
            ):
                raise RuntimeError(
                    "Native expected artifacts must contain valid paths."
                )

            authoritative_context["command"] = [
                executable,
                *list(arguments),
            ]
            authoritative_context["expected_artifacts"] = list(
                expected_artifacts
            )

            output_path = production_request.get("output_path")

            if isinstance(output_path, str) and output_path.strip():
                authoritative_context["output_path"] = output_path
        else:
            if not isinstance(existing_request, dict):
                raise TypeError("production_request must be a dictionary")

        executor = CanonicalMOKNativeProductionExecutor()

        if not hasattr(executor, "execute_authoritative_production"):
            import inspect
            raise RuntimeError(
                "Canonical executor binding invalid: "
                f"module={executor.__class__.__module__} "
                f"file={inspect.getfile(executor.__class__)}"
            )

        return executor.execute_authoritative_production(
            authoritative_context
        )

