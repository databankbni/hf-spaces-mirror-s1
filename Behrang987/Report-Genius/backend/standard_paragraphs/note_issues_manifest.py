"""Persist LLM / heuristic note-issue decompositions for offline review."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from backend.storage import tenant_store

logger = logging.getLogger(__name__)
_lock = Lock()


def note_issues_dir(tenant_id: str) -> Path:
    path = tenant_store.tenant_root(tenant_id) / "note_issues"
    path.mkdir(parents=True, exist_ok=True)
    return path


def note_issues_manifest_path(tenant_id: str, run_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in (run_id or "run"))
    return note_issues_dir(tenant_id) / f"{safe}.json"


def record_note_issues(
    tenant_id: str,
    run_id: str,
    *,
    section_id: str,
    section_title: str = "",
    observations: list[str],
    issues: list[str],
    source: str = "decompose",
    used_llm: bool | None = None,
) -> Path:
    """Write/merge one section's decomposed issues into ``note_issues/{run_id}.json``."""
    path = note_issues_manifest_path(tenant_id, run_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    sid = (section_id or "").strip().upper() or "UNKNOWN"
    cleaned = [i for i in (issues or []) if str(i).strip()]
    record = {
        "section_id": sid,
        "section_title": section_title or "",
        "observations": [o for o in (observations or []) if str(o).strip()],
        # Primary name: SP-matchable findings (defects + simple observations).
        "findings": cleaned,
        "finding_count": len(cleaned),
        # Legacy aliases (same list).
        "issues": cleaned,
        "issue_count": len(cleaned),
        "source": source,
        "used_llm": used_llm,
        "recorded_at": now_iso,
    }
    with _lock:
        data: dict = {"run_id": run_id, "tenant_id": tenant_id, "sections": {}}
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and "sections" in existing:
                    data = existing
            except (OSError, ValueError):
                pass
        data["run_id"] = run_id
        data["tenant_id"] = tenant_id
        data.setdefault("generated_at", now_iso)
        data["updated_at"] = now_iso
        sections = data.setdefault("sections", {})
        if not isinstance(sections, dict):
            sections = {}
            data["sections"] = sections
        sections[sid] = record
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(
        "Wrote note findings run=%s section=%s findings=%d path=%s",
        run_id,
        sid,
        record["finding_count"],
        path,
    )
    return path
