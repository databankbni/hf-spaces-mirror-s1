"""Persist Stage A + Stage B replies as one JSON file under the tenant data dir.

Surveyors (and anyone debugging a live paste) need the intake assignment and the
rubric grades side by side. The HTTP responses are already that payload; this
module writes them to ``<data_dir>/tenants/<id>/note-stages/latest.json`` so the
combined result survives after the browser tab is closed.

A new Stage A run clears any previous Stage B block: those grades belonged to
the last filing and must not sit next to a different assignment.

``stage_a_io`` is the inspect block: every LLM call's ``system_prompt`` and
``user_prompt`` (the exact strings sent), the same pair as ``input.messages``,
the model's parsed reply, and a short note on how the server turns that reply
into filed text without the model writing a word.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.storage import tenant_store

logger = logging.getLogger(__name__)

LATEST_NAME = "latest.json"

HOW_STAGE_A_WORKS = {
    "what_is_sent": (
        "One LLM call. system_prompt is the finalized lossless extraction/"
        "classification contract (atom accounting, no-drop, micro-information, "
        "coverage audit, contextual reference resolution, topic persistence, "
        "location is not subject, verbatim source-span copy). user_prompt is TASK + "
        "Sub-Sections (flat id - Label lines from REVIEW_GROUPS) + SOURCE NOTES."
    ),
    "what_the_model_returns": (
        "One JSON object: property_type (house|flat|unknown), assignments "
        "(list of {code, text} with preserved raw source wording per destination; "
        "each atomic observation filed once; multiple atoms as separate lines)."
    ),
    "how_filed_text_is_possible": (
        "Chip text is classified source material — original wording preserved "
        "verbatim, not rewritten survey prose. Missing destination ids are filled "
        "with 'No specific information provided.'. Unknown codes are discarded."
    ),
    "semantic_not_keyword": (
        "The model must classify what the source means into the supplied schema, "
        "not match keywords to labels. Secondary codes, confidence, and theme tags "
        "are not part of the reply."
    ),
}

HOW_STAGE_B_WORKS = {
    "what_is_sent": (
        "Each LLM call grades one report group. system_prompt is the grading "
        "rules; user_prompt is only that group's chips, each with its own "
        "verbatim rubric and the notes filed there. Other groups' rubrics are "
        "not included."
    ),
    "what_the_model_returns": (
        "One judgment per requested code: grade (green/yellow/red), present, "
        "missing, reason."
    ),
}


def dump_dir(tenant_id: str) -> Path:
    path = tenant_store.tenant_root(tenant_id) / "note-stages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def latest_path(tenant_id: str) -> Path:
    return dump_dir(tenant_id) / LATEST_NAME


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("note-stages dump unreadable (%s): %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def load_latest(tenant_id: str) -> dict[str, Any]:
    """Return the tenant's ``latest.json`` payload, or ``{}`` if missing/unreadable."""
    return _load(latest_path(tenant_id))


def load_stage_a_assignments(tenant_id: str) -> dict[str, list[str]]:
    """Return Stage A filed notes as ``{code: [text, ...]}``, empty placeholders dropped.

    Content-mode generation uses this as the inspection-notes source of truth so
    report prose tracks the classified messy paste, not manually typed textareas.
    """
    # Lazy import: intake imports review_taxonomy; keep dump free of that cycle.
    from backend.content_based.intake import EMPTY_SUBSECTION

    stage_a = load_latest(tenant_id).get("stage_a") or {}
    raw = stage_a.get("assignments") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    empty = (EMPTY_SUBSECTION or "").strip()
    for code, texts in raw.items():
        sid = str(code or "").strip().lower()
        if not sid:
            continue
        if isinstance(texts, str):
            candidates = [texts]
        elif isinstance(texts, list):
            candidates = texts
        else:
            continue
        cleaned = [
            t.strip()
            for t in candidates
            if isinstance(t, str) and t.strip() and t.strip() != empty
        ]
        if cleaned:
            out[sid] = cleaned
    return out


def resolve_content_mode_notes(
    tenant_id: str,
    request_bullets_by_section: dict[str, list[str]] | None,
) -> dict[str, list[str]] | None:
    """Pick Stage A assignments over request bullets when a filing exists.

    Returns ``None`` when neither source has notes (caller may still use
    ``body.bullets`` / template_id alone).
    """
    stored = load_stage_a_assignments(tenant_id)
    if stored:
        return stored
    return request_bullets_by_section or None


def record(
    tenant_id: str,
    *,
    stage_a: dict[str, Any] | None = None,
    stage_b: dict[str, Any] | None = None,
    source_notes: str | None = None,
    llm_io: list[dict[str, Any]] | None = None,
    stage_b_io: list[dict[str, Any]] | None = None,
) -> Path:
    """Merge this stage into ``latest.json`` and return that path."""
    path = latest_path(tenant_id)
    payload = _load(path)
    now = datetime.now(timezone.utc).isoformat()
    payload["saved_at"] = now
    payload["tenant_id"] = tenant_id
    if source_notes is not None:
        payload["source_notes"] = source_notes
    if stage_a is not None:
        payload["stage_a"] = stage_a
        payload["stage_a_saved_at"] = now
        payload["stage_b"] = None
        payload.pop("stage_b_saved_at", None)
        payload.pop("stage_b_io", None)
        payload["stage_a_io"] = {
            "how_it_works": HOW_STAGE_A_WORKS,
            "calls": list(llm_io or []),
        }
    if stage_b is not None:
        payload["stage_b"] = stage_b
        payload["stage_b_saved_at"] = now
        payload["stage_b_io"] = {
            "how_it_works": HOW_STAGE_B_WORKS,
            "calls": list(stage_b_io or []),
        }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def record_quietly(
    tenant_id: str,
    *,
    stage_a: dict[str, Any] | None = None,
    stage_b: dict[str, Any] | None = None,
    source_notes: str | None = None,
    llm_io: list[dict[str, Any]] | None = None,
    stage_b_io: list[dict[str, Any]] | None = None,
) -> str:
    """Same as :func:`record`, but a dump failure must never fail the HTTP call."""
    try:
        return str(
            record(
                tenant_id,
                stage_a=stage_a,
                stage_b=stage_b,
                source_notes=source_notes,
                llm_io=llm_io,
                stage_b_io=stage_b_io,
            )
        )
    except OSError as exc:
        logger.warning("note-stages dump failed: %s", exc)
        return ""
