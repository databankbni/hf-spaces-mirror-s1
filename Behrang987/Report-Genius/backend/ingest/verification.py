"""Ingest verification report — per-subsection capture summary.

Built from the chunks an upload produced so mis-tagged or missed sections are
visible at upload time ("D2 Roof coverings → 3 paragraph(s) captured; D9 →
nothing found") instead of surfacing later as an irrelevant generated
paragraph. Returned in the ingest API response.
"""

from __future__ import annotations

from backend.domain.rics_level3_schema import CANONICAL_SCHEMA
from backend.domain.section_scope import (
    NOTES_PARENT_IDS,
    PARENT_STORAGE_PARENT_IDS,
    parent_letter,
    storage_section_id,
)
from backend.rag.types import CONTENT_ROLE_PARENT_INTRO, Chunk

STATUS_CAPTURED = "captured"
STATUS_MISSING = "missing"


def _expected_units() -> list[tuple[str, str]]:
    """Ordered ``(storage_id, label)`` units the report is expected to cover."""
    rows: list[tuple[str, str]] = []
    for parent in CANONICAL_SCHEMA["sections"]:
        pid = str(parent["id"]).upper()
        plabel = str(parent["label"])
        if pid in PARENT_STORAGE_PARENT_IDS:
            rows.append((pid, plabel))
            continue
        for sub in parent.get("subsections") or []:
            rows.append((str(sub["id"]).upper(), str(sub["label"])))
    return rows


def build_ingest_verification(
    chunks: list[Chunk],
    *,
    source_filename: str,
    segmentation_method: str,
) -> dict:
    """Summarise what an upload captured, per canonical storage unit."""
    body_counts: dict[str, int] = {}
    body_chars: dict[str, int] = {}
    intro_parents: dict[str, int] = {}
    for chunk in chunks:
        if (chunk.content_role or "") == CONTENT_ROLE_PARENT_INTRO:
            parent = parent_letter(chunk.parent_id or chunk.section_id)
            if parent:
                intro_parents[parent] = intro_parents.get(parent, 0) + 1
            continue
        sid = storage_section_id(chunk.section_id)
        if not sid:
            continue
        body_counts[sid] = body_counts.get(sid, 0) + 1
        body_chars[sid] = body_chars.get(sid, 0) + len(chunk.text or "")

    sections: list[dict] = []
    captured = 0
    for sid, label in _expected_units():
        count = body_counts.get(sid, 0)
        status = STATUS_CAPTURED if count else STATUS_MISSING
        if count:
            captured += 1
        sections.append(
            {
                "section_id": sid,
                "label": label,
                "chunks": count,
                "chars": body_chars.get(sid, 0),
                "status": status,
            }
        )

    parent_intros = [
        {"parent_id": pid, "chunks": intro_parents.get(pid, 0)}
        for pid in sorted(NOTES_PARENT_IDS | {"J"})
        if intro_parents.get(pid, 0)
    ]
    missing = [row["section_id"] for row in sections if row["status"] == STATUS_MISSING]
    return {
        "source_filename": source_filename,
        "segmentation_method": segmentation_method,
        "units_expected": len(sections),
        "units_captured": captured,
        "units_missing": missing,
        "sections": sections,
        "parent_intros": parent_intros,
    }
