"""
MOK Canonical Native Process Execution Authority.

MOKNativeExecution is the sole MOK-owned process authority.

Architectural rule:

    policy/governor
        ->
    MOKNativeExecution
        ->
    real OS process
        ->
    real process result

No higher production adapter may import subprocess or create Popen.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence


class MOKNativeExecutionError(RuntimeError):
    """Raised when native process execution cannot be performed."""


@dataclass(frozen=True)
class MOKNativeProcessResult:
    """
    Ground-truth result of an actual native process.

    Success is derived from the real process return code.
    It is never supplied by a caller as synthetic evidence.
    """

    success: bool
    returncode: int
    stdout: str
    stderr: str
    args: Any
    duration: float
    executed: bool
    process_authority: str = "MOKNativeExecution"
    execution_owner: str = "MOKNativeExecution"
    synthetic_execution_evidence: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MOKNativeExecution:
    """
    Canonical native process owner.

    This is intentionally the ONLY canonical layer that imports
    subprocess and invokes Popen.
    """

    EXECUTION_OWNER = "MOKNativeExecution"
    PROCESS_AUTHORITY = "MOKNativeExecution"

    def __init__(self, governor: Optional[Any] = None):
        self.governor = governor

    def authority(self) -> dict[str, Any]:
        return {
            "execution_owner": self.EXECUTION_OWNER,
            "process_authority": self.PROCESS_AUTHORITY,
            "direct_subprocess": True,
            "native_process_owner": True,
            "synthetic_execution_evidence": False,
            "mechanism": "subprocess.Popen",
        }

    def _evaluate_governor(self, contract: Any) -> Any:
        """
        Governor evaluation is mandatory when a governor is attached.

        We deliberately do not manufacture authorization if a governor
        exists but cannot evaluate the contract.
        """

        if self.governor is None:
            return None

        evaluate = getattr(self.governor, "evaluate", None)

        if not callable(evaluate):
            raise MOKNativeExecutionError(
                "Attached MOK execution governor has no evaluate() method."
            )

        decision = evaluate(contract)

        decision_value = getattr(decision, "decision", None)

        if decision_value is None and isinstance(decision, Mapping):
            decision_value = decision.get("decision")

        if decision_value != "READY_FOR_NATIVE_EXECUTION":
            raise MOKNativeExecutionError(
                "MOK execution governor blocked native execution: "
                f"{decision_value!r}"
            )

        return decision

    @staticmethod
    def _normalize_command(command: Any) -> Any:
        """
        Preserve the caller's command shape.

        Strings are intentionally preserved so shell semantics remain
        caller-controlled. Sequence commands are passed directly to Popen.
        """

        if isinstance(command, str):
            if not command.strip():
                raise MOKNativeExecutionError(
                    "Native execution requires a non-empty command."
                )
            return command

        if isinstance(command, Sequence):
            if len(command) == 0:
                raise MOKNativeExecutionError(
                    "Native execution requires a non-empty command sequence."
                )
            return list(command)

        raise MOKNativeExecutionError(
            "Unsupported native command type: "
            f"{type(command).__name__}"
        )

    @staticmethod
    def _extract_command(contract: Any, context: Optional[Mapping[str, Any]]) -> Any:
        """
        Resolve the real command from the canonical contract/context.

        No command is fabricated.
        """

        if context:
            for key in (
                "command",
                "cmd",
                "argv",
                "args",
                "process_command",
            ):
                value = context.get(key)
                if value:
                    return value

        if contract is not None:
            for key in (
                "command",
                "cmd",
                "argv",
                "args",
                "process_command",
            ):
                value = getattr(contract, key, None)
                if value:
                    return value

                if isinstance(contract, Mapping):
                    value = contract.get(key)
                    if value:
                        return value

        raise MOKNativeExecutionError(
            "Canonical execution contract does not contain a real "
            "process command."
        )

    def execute(
        self,
        contract: Any = None,
        context: Optional[Mapping[str, Any]] = None,
        command: Any = None,
        **kwargs: Any,
    ) -> MOKNativeProcessResult:
        """
        Execute one real native process.

        The process is created here and nowhere else in the canonical
        production path.
        """

        # Authorization must happen before process creation.
        self._evaluate_governor(contract)

        real_command = command
        if real_command is None:
            real_command = self._extract_command(contract, context)

        real_command = self._normalize_command(real_command)

        cwd = None
        env = None

        if context:
            cwd = context.get("cwd") or context.get("working_directory")
            env_value = context.get("env")
            if env_value is not None:
                env = dict(os.environ)
                env.update({str(k): str(v) for k, v in env_value.items()})

        if kwargs.get("cwd") is not None:
            cwd = kwargs["cwd"]

        if kwargs.get("env") is not None:
            env = dict(os.environ)
            env.update({str(k): str(v) for k, v in kwargs["env"].items()})

        started = time.perf_counter()

        process = None

        try:
            # ========================================================
            # CANONICAL PROCESS CREATION POINT
            # ========================================================
            process = subprocess.Popen(
                real_command,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=isinstance(real_command, str),
            )

            stdout, stderr = process.communicate()

            duration = time.perf_counter() - started

            returncode = int(process.returncode)

            return MOKNativeProcessResult(
                success=(returncode == 0),
                returncode=returncode,
                stdout=stdout or "",
                stderr=stderr or "",
                args=real_command,
                duration=duration,
                executed=True,
                process_authority=self.PROCESS_AUTHORITY,
                execution_owner=self.EXECUTION_OWNER,
                synthetic_execution_evidence=False,
            )

        except OSError as exc:
            duration = time.perf_counter() - started

            return MOKNativeProcessResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr=str(exc),
                args=real_command,
                duration=duration,
                executed=False,
                process_authority=self.PROCESS_AUTHORITY,
                execution_owner=self.EXECUTION_OWNER,
                synthetic_execution_evidence=False,
            )

        except Exception:
            # Do not convert unexpected failures into synthetic success.
            raise


__all__ = [
    "MOKNativeExecution",
    "MOKNativeExecutionError",
    "MOKNativeProcessResult",
]
