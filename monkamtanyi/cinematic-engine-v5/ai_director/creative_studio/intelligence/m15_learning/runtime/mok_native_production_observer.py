from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class MOKNativeProductionObserver:
    """
    Read-only production observability for MOK.

    This component has no production authority.
    It derives health exclusively from persisted evidence.
    """

    SCHEMA = "MOK_NATIVE_PRODUCTION_HEALTH_V1"

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()

        self.report_paths = {
            "workload_stability": self.root / "output" / "mok_h5_1_workload_stability" / "mok_h5_1_workload_stability_report.json",
            "concurrency": self.root / "output" / "mok_h4_1_concurrent_isolation" / "mok_h4_1_concurrent_isolation_report.json",
            "state_integrity": self.root / "output" / "mok_h3_1_state_integrity" / "mok_h3_1_state_integrity_report.json",
            "fault_recovery": self.root / "output" / "mok_h2_1_fault_recovery" / "mok_h2_1_fault_recovery_report.json",
            "restart_resilience": self.root / "output" / "mok_h1_1_restart_resilience" / "mok_h1_1_restart_resilience_report.json",
            "autonomy": self.root / "output" / "mok_e4_25_1_full_autonomy" / "mok_e4_25_1_full_autonomy_report.json",
        }

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)

        return digest.hexdigest()

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)

        if not isinstance(value, dict):
            raise ValueError(f"Evidence must be a JSON object: {path}")

        return value

    @staticmethod
    def _checks_passed(report: Dict[str, Any]) -> bool:
        checks = report.get("checks")

        if not isinstance(checks, list):
            return bool(report.get("passed"))

        if not checks:
            return bool(report.get("passed"))

        return all(
            isinstance(item, dict)
            and item.get("passed") is True
            for item in checks
        )

    def snapshot(self) -> Dict[str, Any]:
        components: Dict[str, Any] = {}
        evidence_complete = True
        all_verified = True

        for name, path in self.report_paths.items():
            if not path.is_file():
                evidence_complete = False
                all_verified = False

                components[name] = {
                    "available": False,
                    "verified": False,
                    "path": str(path),
                    "reason": "EVIDENCE_MISSING",
                }

                continue

            try:
                report = self._read_json(path)
                checks_passed = self._checks_passed(report)
                verified = (
                    report.get("passed") is True
                    and checks_passed
                    and report.get("synthetic") is not True
                )

                if not verified:
                    all_verified = False

                components[name] = {
                    "available": True,
                    "verified": verified,
                    "reported_status": report.get("status"),
                    "reported_passed": report.get("passed"),
                    "synthetic": report.get("synthetic"),
                    "checks_passed": checks_passed,
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": self._digest(path),
                    "modified_at": datetime.fromtimestamp(
                        path.stat().st_mtime,
                        tz=timezone.utc,
                    ).isoformat(),
                }

            except Exception as exc:
                evidence_complete = False
                all_verified = False

                components[name] = {
                    "available": True,
                    "verified": False,
                    "path": str(path),
                    "reason": "EVIDENCE_INVALID",
                    "error": f"{type(exc).__name__}: {exc}",
                }

        autonomy = components.get("autonomy", {})

        autonomy_verified = (
            autonomy.get("available") is True
            and autonomy.get("verified") is True
        )

        healthy = (
            evidence_complete
            and all_verified
            and autonomy_verified
        )

        h5 = {}

        try:
            if self.report_paths["workload_stability"].is_file():
                h5 = self._read_json(
                    self.report_paths["workload_stability"]
                )
        except Exception:
            h5 = {}

        active_processes = []

        try:
            import psutil

            current_pid = os.getpid()

            for proc in psutil.process_iter(
                ["pid", "name", "cmdline"]
            ):
                try:
                    if proc.pid == current_pid:
                        continue

                    cmdline = " ".join(
                        proc.info.get("cmdline") or []
                    )

                    lowered = cmdline.lower()

                    if (
                        "mok" in lowered
                        and (
                            "python" in lowered
                            or "ffmpeg" in lowered
                        )
                    ):
                        active_processes.append({
                            "pid": proc.pid,
                            "name": proc.info.get("name"),
                            "cmdline": cmdline,
                        })

                except Exception:
                    continue

        except Exception:
            active_processes = []

        return {
            "schema": self.SCHEMA,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "observer_mode": "READ_ONLY",
            "production_authority": False,
            "decision_authority": False,
            "learning_mutation_authority": False,
            "policy_mutation_authority": False,
            "synthetic": False,
            "evidence_complete": evidence_complete,
            "all_hardening_evidence_verified": all_verified,
            "autonomy_verified": autonomy_verified,
            "autonomy_percent": 100 if autonomy_verified else None,
            "autonomy_regression_detected": not autonomy_verified,
            "production_health": (
                "HEALTHY"
                if healthy
                else "NOT_VERIFIED"
            ),
            "components": components,
            "workload_metrics": {
                "cycles": h5.get("cycles"),
                "complete_autonomous_workloads": h5.get(
                    "complete_autonomous_workloads"
                ),
                "rss_delta": h5.get("rss_delta"),
                "disk_delta": h5.get("disk_delta"),
                "orphan_processes": h5.get("orphan_processes"),
                "cycle_metrics": h5.get("cycle_metrics"),
            },
            "currently_observed_mok_processes": active_processes,
            "status": (
                "MOK_NATIVE_PRODUCTION_HEALTH_VERIFIED"
                if healthy
                else "MOK_NATIVE_PRODUCTION_HEALTH_NOT_VERIFIED"
            ),
        }
