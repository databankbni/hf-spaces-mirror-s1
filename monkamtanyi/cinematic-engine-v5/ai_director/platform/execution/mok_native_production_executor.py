from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


class MOKNativeProductionExecutor:
    """Canonical MOK-owned autonomous production execution authority."""

    AUTHORITY = "MOK_NATIVE_PRODUCTION_EXECUTOR"
    VERSION = "MOK-E4.22"
    LEARNING_SCHEMA = "MOK_NATIVE_PRODUCTION_LEARNING_V2"

    def __init__(self, project_root=None):
        self.project_root = Path(project_root or os.getcwd()).resolve()
        self.evidence_dir = self.project_root / "output" / "mok_authority_evidence"
        self.learning_dir = self.project_root / "output" / "mok_learning"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        self.learning_state_path = self.learning_dir / "mok_native_production_learning_state.json"

    @staticmethod
    def _utc_now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _get(context, *names, default=None):
        for name in names:
            if isinstance(context, dict) and name in context:
                value = context.get(name)
                if value is not None:
                    return value
            if hasattr(context, name):
                value = getattr(context, name)
                if value is not None:
                    return value
        return default

    def _load_learning(self):
        if not self.learning_state_path.is_file():
            return {
                "schema": self.LEARNING_SCHEMA,
                "runs": 0,
                "verified_successes": 0,
                "failures": 0,
                "recoveries_attempted": 0,
                "recoveries_succeeded": 0,
                "adaptations_applied": 0,
                "status_counts": {},
                "failure_counts": {},
                "last_recovery_action": None,
                "last_status": None,
                "last_verified": False,
                "updated_at": None,
            }

        try:
            with self.learning_state_path.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        except Exception:
            state = {}

        state.setdefault("schema", self.LEARNING_SCHEMA)
        state.setdefault("runs", 0)
        state.setdefault("verified_successes", 0)
        state.setdefault("failures", 0)
        state.setdefault("recoveries_attempted", 0)
        state.setdefault("recoveries_succeeded", 0)
        state.setdefault("adaptations_applied", 0)
        state.setdefault("status_counts", {})
        state.setdefault("failure_counts", {})
        state.setdefault("last_recovery_action", None)
        state.setdefault("last_status", None)
        state.setdefault("last_verified", False)
        state.setdefault("updated_at", None)
        return state

    def _save_learning(self, result):
        state = self._load_learning()
        state["schema"] = self.LEARNING_SCHEMA
        state["runs"] += 1

        status = result.get("status") or "UNKNOWN"
        state["status_counts"][status] = state["status_counts"].get(status, 0) + 1

        if result.get("verified") is True:
            state["verified_successes"] += 1
        else:
            state["failures"] += 1

        failure_type = result.get("failure_type")
        if failure_type:
            state["failure_counts"][failure_type] = state["failure_counts"].get(failure_type, 0) + 1

        recovery = result.get("recovery") or {}
        if recovery.get("attempted"):
            state["recoveries_attempted"] += 1
        if recovery.get("succeeded"):
            state["recoveries_succeeded"] += 1

        action = recovery.get("action")
        if action:
            state["last_recovery_action"] = action

        if result.get("adaptation_applied"):
            state["adaptations_applied"] += 1

        state["last_status"] = status
        state["last_verified"] = bool(result.get("verified"))
        state["last_executed"] = bool(result.get("executed"))
        state["last_success"] = bool(result.get("success"))
        state["updated_at"] = self._utc_now()

        with self.learning_state_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)

        return state

    def _resolve_command(self, context):
        command = self._get(
            context,
            "command",
            "production_command",
            "ffmpeg_command",
            "args",
            default=None,
        )

        if command is None:
            raise ValueError("No authoritative production command supplied.")

        if isinstance(command, tuple):
            command = list(command)

        if isinstance(command, list) and command:
            return [str(item) for item in command]

        if isinstance(command, str) and command.strip():
            return command

        raise ValueError("Production command is empty or invalid.")

    def _resolve_artifacts(self, context):
        values = self._get(context, "expected_artifacts", "artifacts", default=None)

        if values is None:
            single = self._get(
                context,
                "artifact",
                "output",
                "output_path",
                "movie",
                "video",
                default=None,
            )
            values = [] if single is None else [single]

        if isinstance(values, (str, Path)):
            values = [values]

        result = []

        for value in values or []:
            if isinstance(value, dict):
                value = value.get("path") or value.get("output") or value.get("file")

            if not value:
                continue

            path = Path(str(value))
            if not path.is_absolute():
                path = self.project_root / path

            result.append(path.resolve())

        return result

    def _run_process(self, command):
        started_at = self._utc_now()
        started = time.perf_counter()

        try:
            completed = subprocess.run(
                command,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                shell=isinstance(command, str),
                check=False,
            )

            return {
                "returncode": completed.returncode,
                "return_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "args": command,
                "command": command,
                "executed": True,
                "process_success": completed.returncode == 0,
                "duration": time.perf_counter() - started,
                "started_at": started_at,
                "finished_at": self._utc_now(),
                "error": None if completed.returncode == 0 else completed.stderr,
            }
        except Exception as exc:
            return {
                "returncode": None,
                "return_code": None,
                "stdout": "",
                "stderr": "",
                "args": command,
                "command": command,
                "executed": False,
                "process_success": False,
                "duration": time.perf_counter() - started,
                "started_at": started_at,
                "finished_at": self._utc_now(),
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _verify_mp4_signature(self, path):
        try:
            with path.open("rb") as handle:
                header = handle.read(32)
            return b"ftyp" in header
        except Exception:
            return False

    def _verify_media(self, path):
        ffprobe = shutil.which("ffprobe")

        if not ffprobe:
            return {
                "performed": False,
                "verified": True,
                "reason": "ffprobe_unavailable_file_integrity_used",
            }

        probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration,size",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if probe.returncode != 0:
            return {
                "performed": True,
                "verified": False,
                "returncode": probe.returncode,
                "stderr": probe.stderr,
            }

        try:
            payload = json.loads(probe.stdout or "{}")
            format_data = payload.get("format") or {}
            duration = float(format_data.get("duration") or 0)
            size = int(format_data.get("size") or 0)
        except Exception:
            return {
                "performed": True,
                "verified": False,
                "reason": "invalid_ffprobe_result",
            }

        return {
            "performed": True,
            "verified": duration > 0 and size > 0,
            "duration": duration,
            "size": size,
        }

    def _verify_artifacts(self, artifacts):
        if not artifacts:
            return {
                "verified": False,
                "status": "NO_ARTIFACT_DECLARED",
                "artifacts": [],
            }

        results = []
        all_verified = True

        media_extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

        for path in artifacts:
            exists = path.is_file()
            size = path.stat().st_size if exists else 0
            verified = exists and size > 0

            item = {
                "path": str(path),
                "exists": exists,
                "size_bytes": size,
                "verified": verified,
            }

            if verified and path.suffix.lower() == ".mp4":
                signature = self._verify_mp4_signature(path)
                item["artifact_ftyp_verified"] = signature
                verified = verified and signature
                item["verified"] = verified

            if verified and path.suffix.lower() in media_extensions:
                media = self._verify_media(path)
                item["media_verification"] = media
                verified = verified and bool(media.get("verified"))
                item["verified"] = verified

            if not verified:
                all_verified = False

            results.append(item)

        return {
            "verified": all_verified,
            "status": "REAL_PRODUCTION_ARTIFACT_VERIFIED" if all_verified else "ARTIFACT_VERIFICATION_FAILED",
            "artifacts": results,
        }

    def _classify_failure(self, process_result, artifacts):
        if not process_result.get("executed"):
            return "PROCESS_LAUNCH_FAILURE"

        if process_result.get("returncode") not in (0, None):
            missing_parents = [str(path.parent) for path in artifacts if not path.parent.exists()]
            if missing_parents:
                return "MISSING_ARTIFACT_PARENT_DIRECTORY"
            return "PRODUCTION_PROCESS_FAILURE"

        return "ARTIFACT_VERIFICATION_FAILURE"

    def _apply_learning_preflight(self, artifacts):
        state = self._load_learning()
        action = state.get("last_recovery_action")

        if action != "CREATE_MISSING_ARTIFACT_PARENT_DIRECTORIES":
            return {
                "applied": False,
                "action": None,
                "created": [],
            }

        created = []

        for artifact in artifacts:
            if not artifact.parent.exists():
                artifact.parent.mkdir(parents=True, exist_ok=True)
                created.append(str(artifact.parent))

        return {
            "applied": bool(created),
            "action": action if created else None,
            "created": created,
        }

    def _native_recovery(self, failure_type, command, artifacts):
        recovery = {
            "attempted": False,
            "succeeded": False,
            "action": None,
            "classification": failure_type,
            "repair_evidence": {},
            "result": None,
        }

        if failure_type == "MISSING_ARTIFACT_PARENT_DIRECTORY":
            recovery["attempted"] = True
            recovery["action"] = "CREATE_MISSING_ARTIFACT_PARENT_DIRECTORIES"

            created = []
            for artifact in artifacts:
                if not artifact.parent.exists():
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    created.append(str(artifact.parent))

            recovery["repair_evidence"] = {
                "created_directories": created,
            }

            retry = self._run_process(command)
            recovery["result"] = retry
            recovery["succeeded"] = bool(retry.get("process_success"))

        return recovery

    def _persist_evidence(self, evidence):
        path = self.evidence_dir / f"{evidence['evidence_id']}.json"

        with path.open("w", encoding="utf-8") as handle:
            json.dump(evidence, handle, indent=2, ensure_ascii=False)

        return path

    def execute_authoritative_production(self, execution_context):
        evidence_id = f"mok-{uuid.uuid4().hex}"
        authority_started = self._utc_now()
        artifacts = self._resolve_artifacts(execution_context)

        try:
            command = self._resolve_command(execution_context)
        except Exception as exc:
            result = {
                "evidence_id": evidence_id,
                "authority": self.AUTHORITY,
                "authority_version": self.VERSION,
                "returncode": None,
                "return_code": None,
                "stdout": "",
                "stderr": "",
                "args": None,
                "command": None,
                "executed": False,
                "success": False,
                "verified": False,
                "synthetic": False,
                "status": "AUTHORITY_REFUSED",
                "error": f"{type(exc).__name__}: {exc}",
                "failure_type": "MISSING_OR_INVALID_PRODUCTION_COMMAND",
                "recovery": {
                    "attempted": False,
                    "succeeded": False,
                    "action": None,
                    "result": None,
                },
                "verification": {
                    "verified": False,
                    "status": "NOT_RUN",
                    "artifacts": [],
                },
                "adaptation_applied": False,
                "duration": 0.0,
                "started_at": authority_started,
                "finished_at": self._utc_now(),
                "next_action": "REQUIRE_REAL_PRODUCTION_COMMAND",
            }

            learning = self._save_learning(result)
            result["learning_updated"] = True
            result["learning_state"] = learning

            evidence_path = self._persist_evidence(result)
            result["evidence_path"] = str(evidence_path)
            result["learning_path"] = str(self.learning_state_path)
            return result

        adaptation = self._apply_learning_preflight(artifacts)

        primary = self._run_process(command)
        final_process = primary

        recovery = {
            "attempted": False,
            "succeeded": False,
            "action": None,
            "classification": None,
            "repair_evidence": {},
            "result": None,
        }

        failure_type = None

        if not primary.get("process_success"):
            failure_type = self._classify_failure(primary, artifacts)
            recovery = self._native_recovery(
                failure_type,
                command,
                artifacts,
            )

            if recovery.get("succeeded") and recovery.get("result"):
                final_process = recovery["result"]

        if final_process.get("process_success"):
            verification = self._verify_artifacts(artifacts)
        else:
            verification = {
                "verified": False,
                "status": "PROCESS_FAILED_VERIFICATION_NOT_RUN",
                "artifacts": [],
            }

        verified = bool(
            final_process.get("process_success")
            and verification.get("verified")
        )

        if verified:
            status = "REAL_PRODUCTION_ARTIFACT_VERIFIED"
            final_failure_type = None
            next_action = "CONTINUE_AUTONOMOUS_PRODUCTION"
        else:
            status = (
                "REAL_PRODUCTION_FAILED"
                if not final_process.get("process_success")
                else "ARTIFACT_VERIFICATION_FAILED"
            )
            final_failure_type = failure_type or "ARTIFACT_VERIFICATION_FAILURE"
            next_action = "REPLAN_OR_ESCALATE_RECOVERY"

        result = {
            "evidence_id": evidence_id,
            "authority": self.AUTHORITY,
            "authority_version": self.VERSION,
            "returncode": final_process.get("returncode"),
            "return_code": final_process.get("return_code"),
            "stdout": final_process.get("stdout"),
            "stderr": final_process.get("stderr"),
            "args": final_process.get("args"),
            "command": final_process.get("command"),
            "executed": bool(final_process.get("executed")),
            "success": verified,
            "verified": verified,
            "synthetic": False,
            "status": status,
            "error": final_process.get("error"),
            "failure_type": final_failure_type,
            "verification": verification,
            "primary_execution": primary,
            "recovery": recovery,
            "adaptation": adaptation,
            "adaptation_applied": bool(adaptation.get("applied")),
            "duration": final_process.get("duration"),
            "started_at": authority_started,
            "finished_at": self._utc_now(),
            "next_action": next_action,
        }

        learning = self._save_learning(result)
        result["learning_updated"] = True
        result["learning_state"] = learning

        evidence_path = self._persist_evidence(result)
        result["evidence_path"] = str(evidence_path)
        result["learning_path"] = str(self.learning_state_path)

        return result

    def execute(self, execution_context):
        return self.execute_authoritative_production(execution_context)
