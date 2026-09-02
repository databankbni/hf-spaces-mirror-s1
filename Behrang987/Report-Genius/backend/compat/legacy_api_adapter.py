"""Map v2 generation results to legacy SectionPayload JSON for the UI."""

from __future__ import annotations

from backend.models.report import GeneratedSection, ReferenceSource, ReportResult
from backend.models.schema import TemplateSchema

_COMPOSITION_NOTES = {
    "minimum": "Mapped from past report baseline with in-place fact updates (baseline preservation).",
    "medium": "Technical in-place edit on past report baseline with proofread updates.",
    "maximum": "Full narrative in-place edit retaining long-form baseline scaffolding.",
}

# Section statuses whose text is a system placeholder, not survey prose.
_UNPOLISHED_STATUSES = frozenset({"NO_RAG_MATCH", "UNASSIGNED"})


def _polish_section_text(text: str, status: str) -> str:
    """Final cleanup pass on a section's draft text (config-gated, non-destructive)."""
    from backend.config import settings

    if not getattr(settings, "postprocess_enabled", True):
        return text or ""
    if status in _UNPOLISHED_STATUSES or not text or not text.strip():
        return text or ""

    from backend.utils.report_postprocessor import polish_report

    try:
        return polish_report(text)
    except ValueError:
        return text


def _style_payload(style_profile: object | None) -> dict | None:
    if style_profile is None:
        return None
    if hasattr(style_profile, "to_payload"):
        return style_profile.to_payload()  # type: ignore[union-attr]
    if isinstance(style_profile, dict):
        return style_profile
    return None


def interference_for_mode(mode: str, interference_level: str | None) -> str:
    il = (interference_level or "medium").strip().lower()
    # New generation-mode names map onto the legacy composition tiers.
    if il == "assist":
        return "minimum"
    if il == "expert":
        return "maximum"
    if il in _COMPOSITION_NOTES:
        return il
    if mode == "enhance":
        return "maximum"
    if mode == "proofread":
        return "medium"
    return "minimum"


def _section_notes_blob(items: list[str] | None) -> str:
    """Join UI/API bullet items into one inspection-notes blob (script parity).

    Dual-path / past-report scripts pass ``observations=[notes.strip()]`` — one
    string per section. Do not treat newlines as separate findings here.
    """
    parts = [str(item).strip() for item in (items or []) if str(item).strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    # Legacy multi-item clients: one blob, preserve paragraph breaks between items.
    return "\n".join(parts).strip()


def section_notes_from_bullets_by_section(
    bullets_by_section: dict[str, list[str]] | None,
) -> dict[str, "SectionNote"]:
    """Pin each section's textarea to a single ``SectionNote`` observation.

    Skips keyword re-routing / sentence splitting so UI Assist matches the
    dual-path house scripts (whole pasted block = one observation).
    """
    from backend.models.section import SectionNote

    out: dict[str, SectionNote] = {}
    for code, items in (bullets_by_section or {}).items():
        sid = (code or "").strip().upper()
        blob = _section_notes_blob(list(items or []))
        if not sid or not blob:
            continue
        out[sid] = SectionNote(
            section_id=sid,
            raw_observations=[blob],
            text=blob,
        )
    return out


def bullets_to_raw_notes(
    template_id: str,
    bullets: list[str],
    bullets_by_section: dict[str, list[str]] | None = None,
) -> str:
    lines: list[str] = []
    if bullets_by_section:
        for code, items in bullets_by_section.items():
            blob = _section_notes_blob(list(items or []))
            if not blob:
                continue
            # Flatten newlines for the prefixed raw-notes string so a fallback
            # parse keeps the whole blob under this section code.
            flat = " ".join(blob.replace("\r\n", "\n").split())
            if flat:
                lines.append(f"{code}: {flat}")
    elif bullets:
        blob = _section_notes_blob(list(bullets or []))
        if blob:
            flat = " ".join(blob.replace("\r\n", "\n").split())
            if flat:
                lines.append(f"{template_id}: {flat}")
    return "\n\n".join(lines)


def _paragraph_index_from_chunk_id(chunk_id: str) -> int:
    if ":p" not in chunk_id:
        return 0
    try:
        return int(chunk_id.rsplit(":p", 1)[-1])
    except ValueError:
        return 0


def reference_sources_from_payload(
    payload: dict,
    schema: TemplateSchema | None = None,
) -> list[ReferenceSource]:
    """Rebuild structured provenance from legacy payload or v2 preview fields."""
    stored = payload.get("reference_sources")
    if stored:
        return [ReferenceSource.model_validate(item) for item in stored]

    out: list[ReferenceSource] = []
    seen: set[tuple[str, str, int]] = set()
    for item in payload.get("provenance") or []:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or item.get("doc_id") or "").strip()
        if filename.startswith("reference:"):
            filename = filename.split(":", 1)[-1]
        if not filename:
            continue
        section_id = str(item.get("section_hint") or "").strip().upper()
        para = _paragraph_index_from_chunk_id(str(item.get("chunk_id") or ""))
        key = (filename, section_id, para)
        if key in seen:
            continue
        seen.add(key)
        section_title = ""
        if schema and section_id:
            sec = schema.get_section(section_id)
            if sec:
                section_title = sec.title
        out.append(
            ReferenceSource(
                report_filename=filename,
                section_id=section_id,
                section_title=section_title,
                paragraph_index=para,
            )
        )
    return out


def payload_to_generated_section(
    section_id: str,
    title: str,
    payload: dict,
    schema: TemplateSchema | None = None,
) -> GeneratedSection:
    """Map a persisted section payload back to a GeneratedSection for DOCX export."""
    ref_sources = reference_sources_from_payload(payload, schema)
    # rag_sources are live-generation display strings; do NOT synthesize them
    # from provenance here, so reports rebuilt from provenance-only payloads omit
    # the internal source attribution footnote on export.
    rag_sources = list(payload.get("rag_sources") or [])

    status = str(payload.get("status") or "OK")
    grounding = payload.get("grounding_passed")
    if grounding is None:
        grounding = status == "OK" and bool((payload.get("text") or "").strip())

    citation = (
        payload.get("citation_audit")
        if isinstance(payload.get("citation_audit"), dict)
        else {}
    )
    unmatched = list(
        payload.get("unmatched_observations") or citation.get("dropped_claims") or []
    )
    ai = (
        payload.get("ai_transparency")
        if isinstance(payload.get("ai_transparency"), dict)
        else {}
    )

    return GeneratedSection(
        section_id=section_id,
        title=title,
        text=payload.get("text") or "",
        rating_value=payload.get("rating_value"),
        status=status,
        notes=str(payload.get("notes") or ai.get("plain_language") or ""),
        rag_sources=rag_sources,
        reference_sources=ref_sources,
        grounding_passed=bool(grounding),
        unmatched_observations=unmatched,
        topic_id=str(payload.get("topic_id") or ""),
        topic_label=str(payload.get("topic_label") or ""),
        subtopic_id=str(payload.get("subtopic_id") or ""),
    )


def section_to_payload(
    section: GeneratedSection,
    *,
    interference_level: str,
    mode: str,
    style_profile: object | None = None,
) -> dict:
    composition_note = _COMPOSITION_NOTES.get(
        interference_level,
        _COMPOSITION_NOTES["medium"],
    )
    provenance = [
        {
            "doc_id": src.report_filename,
            "chunk_id": f"{src.section_id}:p{src.paragraph_index or 0}",
            "score": 1.0,
            "filename": src.report_filename,
            "snippet_preview": (
                f"Section {src.section_id}"
                + (f", paragraph {src.paragraph_index}" if src.paragraph_index else "")
            )[:240],
            "section_hint": src.section_id,
        }
        for src in section.reference_sources
    ]
    confidence = 0.92 if section.status == "OK" and section.grounding_passed else 0.55
    if section.status == "NO_RAG_MATCH":
        confidence = 0.2
    polished_text = _polish_section_text(section.text or "", section.status)
    return {
        "text": polished_text,
        "confidence": confidence,
        "provenance": provenance,
        "reference_sources": [rs.model_dump() for rs in section.reference_sources],
        "rag_sources": list(section.rag_sources),
        "status": section.status,
        "grounding_passed": section.grounding_passed,
        "unmatched_observations": list(section.unmatched_observations),
        "rating_value": section.rating_value,
        "topic_id": section.topic_id,
        "topic_label": section.topic_label,
        "subtopic_id": section.subtopic_id,
        "cached": False,
        "mode": mode if mode in ("generate", "proofread", "enhance") else "generate",
        "style_profile": _style_payload(style_profile),
        "interference_level": interference_level,
        "composition_depth": interference_level,
        "ai_transparency": {
            "plain_language": section.notes or composition_note,
            "composition_note": composition_note,
        },
        "photos": [],
        "pipeline": "v2_reference_mapping",
        "citation_audit": {
            "confidence": confidence,
            "findings": len(provenance),
            "contradictions": [],
            "dropped_claims": section.unmatched_observations or [],
        },
        "word_count": len(polished_text.split()),
    }


def result_to_sections_payload(
    result: ReportResult,
    *,
    interference_level: str,
    mode: str,
    style_profile: object | None = None,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for section in result.sections:
        if section.section_id == "UNASSIGNED":
            continue
        out[section.section_id] = section_to_payload(
            section,
            interference_level=interference_level,
            mode=mode,
            style_profile=style_profile,
        )
    return out
