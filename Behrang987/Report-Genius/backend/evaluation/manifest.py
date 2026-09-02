"""Persist per-report evaluation manifests (notes + generated + baseline + scores)."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from backend.evaluation.models import EvaluationResult
from backend.storage import tenant_store

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def evaluations_dir(tenant_id: str):
    d = tenant_store.tenant_root(tenant_id) / "evaluations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def evaluation_manifest_path(tenant_id: str, report_id: str):
    safe_report = tenant_store.path_safe_segment(report_id, fallback="report")
    return evaluations_dir(tenant_id) / f"{safe_report}.json"


def write_evaluation_manifest(
    tenant_id: str,
    report_id: str,
    result: EvaluationResult,
) -> None:
    """Write the full evaluation result for a report. Never raises."""
    if not report_id:
        return
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        path = evaluation_manifest_path(tenant_id, report_id)
        payload = {
            "report_id": report_id,
            "generated_at": now_iso,
            "updated_at": now_iso,
            # Sections are indexed below for direct subsection lookup. Excluding
            # the list here avoids duplicating generated text, prompts, and
            # judgments in every manifest.
            "evaluation": result.model_dump(exclude={"sections"}),
            "sections": {
                s.section_id.upper(): {
                    "section_title": s.title,
                    "observations": s.observations,
                    "generated_text": s.generated_text,
                    "baseline_text": s.baseline_text,
                    "prompt": s.prompt,
                    "note_judgments": [j.model_dump() for j in s.note_judgments],
                    "covered_count": s.covered_count,
                    "missing_count": s.missing_count,
                    "partial_count": s.partial_count,
                    "coverage_rate": s.coverage_rate,
                    "missing_facts": s.missing_facts,
                    "faithfulness_score": s.faithfulness_score,
                    "unsupported_claims": s.unsupported_claims,
                    "error": s.error,
                }
                for s in result.sections
            },
        }
        with _lock:
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception:  # noqa: BLE001 - non-critical side artifact
        logger.warning(
            "Failed to write evaluation manifest for tenant=%s report=%s.",
            tenant_id,
            report_id,
            exc_info=True,
        )


def load_evaluation_manifest(tenant_id: str, report_id: str) -> dict | None:
    """Return the evaluation JSON dict, or None if missing/unreadable."""
    if not report_id:
        return None
    path = evaluation_manifest_path(tenant_id, report_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None
