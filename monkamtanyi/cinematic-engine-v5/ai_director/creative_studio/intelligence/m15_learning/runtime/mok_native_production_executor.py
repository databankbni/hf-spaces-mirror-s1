from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ai_director.platform.execution.mok_native_execution import MOKNativeExecution


class MOKNativeProductionExecutor:
    """Canonical MOK-owned production execution authority."""

    AUTHORITY = "MOKNativeProductionExecutor"
    EXECUTION_OWNER = "MOKNativeExecution"

    def __init__(
        self,
        native_execution: Optional[MOKNativeExecution] = None,
        governor: Any = None,
        **_: Any,
    ) -> None:
        self._native_execution = (
            native_execution
            if native_execution is not None
            else MOKNativeExecution(governor=governor)
        )

    def _failure(
        self,
        status: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "authority": self.AUTHORITY,
            "execution_owner": self.EXECUTION_OWNER,
            "status": status,
            "execution_authorized": False,
            "executed": False,
            "completed": False,
            "success": False,
            "synthetic_success": False,
            "synthetic_execution_evidence": False,
        }

        if details:
            payload["details"] = dict(details)

        return payload

    @staticmethod
    def _normalize_command(value: Any) -> Optional[List[str]]:
        if value is None:
            return None

        if isinstance(value, (str, bytes)):
            return None

        if not isinstance(value, Sequence):
            return None

        command = [str(part) for part in value]

        if not command:
            return None

        if any(not part.strip() for part in command):
            return None

        return command

    def _build_command(
        self,
        production_request: Mapping[str, Any],
    ) -> Optional[List[str]]:
        """
        Consume an authoritative production command from upstream.

        This executor intentionally does not invent creative/render
        intent. Upstream MOK production planning owns that decision.
        """

        command = self._normalize_command(
            production_request.get("command")
        )

        if command is not None:
            return command

        executable = production_request.get("executable")
        arguments = production_request.get("arguments")

        if executable and isinstance(arguments, Sequence):
            if not isinstance(arguments, (str, bytes)):
                command = [str(executable)]
                command.extend(str(value) for value in arguments)
                return self._normalize_command(command)

        return None

    @staticmethod
    def _resolve_inputs(
        values: Iterable[Any],
    ) -> List[Path]:
        resolved: List[Path] = []

        for value in values:
            path = Path(str(value)).expanduser().resolve()
            resolved.append(path)

        return resolved

    @staticmethod
    def _verify_artifact(path: Path) -> Dict[str, Any]:
        """Independent verification without spawning another process."""

        exists = path.exists()
        is_file = bool(exists and path.is_file())
        size_bytes = path.stat().st_size if is_file else 0

        suffix = path.suffix.lower()
        signature_verified = False
        verification_kind = "generic_file"

        if is_file and size_bytes > 0:
            if suffix in {".mp4", ".mov", ".m4v"}:
                verification_kind = "iso_base_media_signature"

                try:
                    with path.open("rb") as handle:
                        header = handle.read(64)

                    signature_verified = b"ftyp" in header
                except OSError:
                    signature_verified = False
            else:
                signature_verified = True

        verified = bool(
            exists
            and is_file
            and size_bytes > 0
            and signature_verified
        )

        return {
            "artifact_path": str(path),
            "exists": exists,
            "is_file": is_file,
            "size_bytes": size_bytes,
            "suffix": suffix,
            "verification_kind": verification_kind,
            "signature_verified": signature_verified,
            "verified": verified,
        }

    @staticmethod
    def _native_payload(native_result: Any) -> Dict[str, Any]:
        if isinstance(native_result, dict):
            return dict(native_result)

        if hasattr(native_result, "to_dict"):
            value = native_result.to_dict()

            if isinstance(value, dict):
                return dict(value)

        if hasattr(native_result, "__dict__"):
            return dict(native_result.__dict__)

        return {
            "native_result": native_result,
        }

    def _invoke_native_execution(
        self,
        contract: Any,
        command: Sequence[str],
        execution_context: Mapping[str, Any],
    ) -> Any:
        """Bind to the installed MOKNativeExecution API safely."""

        execute = self._native_execution.execute
        parameters = inspect.signature(execute).parameters

        kwargs: Dict[str, Any] = {}

        if "command" in parameters:
            kwargs["command"] = list(command)

        timeout_value = float(
            execution_context.get("timeout_seconds", 300.0)
        )

        if "timeout_seconds" in parameters:
            kwargs["timeout_seconds"] = timeout_value
        elif "timeout" in parameters:
            kwargs["timeout"] = timeout_value

        environment = execution_context.get("environment")

        if "environment" in parameters:
            kwargs["environment"] = environment
        elif "env" in parameters:
            kwargs["env"] = environment

        if "cwd" in parameters:
            kwargs["cwd"] = execution_context.get("cwd")

        if "contract" in parameters:
            kwargs["contract"] = contract
            return execute(**kwargs)

        return execute(contract, **kwargs)

    def execute(
        self,
        execution_context: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Execute one authoritative real-production request."""

        if not isinstance(execution_context, Mapping):
            raise TypeError(
                "execution_context must be a mapping"
            )

        contract = execution_context.get("contract")

        if contract is None:
            return self._failure(
                "NATIVE_EXECUTION_CONTRACT_REQUIRED"
            )

        production_request = execution_context.get(
            "production_request"
        )

        if not isinstance(production_request, Mapping):
            return self._failure(
                "PRODUCTION_REQUEST_INVALID"
            )

        input_values = production_request.get(
            "input_files",
            [],
        )

        if not isinstance(input_values, list) or not input_values:
            return self._failure(
                "REAL_INPUT_MEDIA_REQUIRED"
            )

        resolved_inputs = self._resolve_inputs(input_values)

        for path in resolved_inputs:
            if not path.exists():
                return self._failure(
                    "INPUT_MEDIA_NOT_FOUND",
                    {"path": str(path)},
                )

            if not path.is_file():
                return self._failure(
                    "INPUT_MEDIA_NOT_A_FILE",
                    {"path": str(path)},
                )

        output_value = production_request.get("output_path")

        if not output_value:
            return self._failure(
                "OUTPUT_PATH_REQUIRED"
            )

        output_path = Path(
            str(output_value)
        ).expanduser().resolve()

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        command = self._build_command(production_request)

        if command is None:
            return self._failure(
                "AUTHORITATIVE_PRODUCTION_COMMAND_REQUIRED",
                {
                    "reason": (
                        "Upstream MOK production planning must provide "
                        "command or executable+arguments."
                    )
                },
            )

        native_result = self._invoke_native_execution(
            contract=contract,
            command=command,
            execution_context=execution_context,
        )

        native_payload = self._native_payload(native_result)

        native_success = bool(
            native_payload.get("success", False)
        )

        native_executed = bool(
            native_payload.get(
                "executed",
                native_payload.get("started", False),
            )
        )

        native_completed = bool(
            native_payload.get(
                "completed",
                native_payload.get("finished", False),
            )
        )

        exit_code = native_payload.get("exit_code")

        if exit_code is None:
            exit_code = native_payload.get("returncode")

        if exit_code is None:
            exit_code = native_payload.get("return_code")

        verification = self._verify_artifact(output_path)

        artifact_verified = bool(
            verification.get("verified", False)
        )

        success = bool(
            native_success
            and native_executed
            and artifact_verified
        )

        evidence = {
            "authority": self.AUTHORITY,
            "execution_owner": self.EXECUTION_OWNER,
            "command": list(command),
            "input_files": [
                str(path)
                for path in resolved_inputs
            ],
            "artifact_path": str(output_path),
            "artifact_exists": bool(
                verification.get("exists", False)
            ),
            "artifact_size_bytes": int(
                verification.get("size_bytes", 0)
            ),
            "artifact_verified": artifact_verified,
            "executed": native_executed,
            "completed": native_completed,
            "exit_code": exit_code,
            "native_success": native_success,
            "success": success,
            "native_result": native_payload,
            "verification": verification,
            "synthetic_success": False,
            "synthetic_execution_evidence": False,
        }

        return {
            "authority": self.AUTHORITY,
            "execution_owner": self.EXECUTION_OWNER,
            "status": (
                "REAL_PRODUCTION_ARTIFACT_VERIFIED"
                if success
                else "REAL_PRODUCTION_EXECUTION_NOT_VERIFIED"
            ),
            "execution_authorized": bool(
                native_payload.get(
                    "executable",
                    native_payload.get(
                        "authorized",
                        native_payload.get(
                            "execution_authorized",
                            False,
                        ),
                    ),
                )
            ),
            "executed": native_executed,
            "completed": native_completed,
            "success": success,
            "native_result": native_payload,
            "execution_evidence": evidence,
            "verification": verification,
            "command": list(command),
            "artifact_path": str(output_path),
            "synthetic_success": False,
            "synthetic_execution_evidence": False,
        }
