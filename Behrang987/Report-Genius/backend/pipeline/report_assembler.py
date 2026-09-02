"""Assemble a generated report into output formats (JSON preview + DOCX)."""

from __future__ import annotations

from backend.compat.legacy_api_adapter import payload_to_generated_section
from backend.config import settings
from backend.models.report import GeneratedSection, ReportResult
from backend.models.schema import TemplateSchema
from backend.utils import docx_builder

_REVIEW_STATUSES = frozenset(
    {"NO_RAG_MATCH", "GROUNDING_REVIEW", "UNASSIGNED", "NOTES_ONLY"}
)


def _preview_order_key(s: GeneratedSection, section_ids: list[str]):
    """Order RICS sections by schema position; content sections by topic order."""
    if s.section_id in section_ids:
        return (0, section_ids.index(s.section_id), "")
    if s.topic_id:
        from backend.content_based import taxonomy

        return (1, taxonomy.topic_order(s.topic_id), s.subtopic_id or "")
    return (2, 0, s.section_id)


def to_preview(result: ReportResult, schema: TemplateSchema) -> dict:
    """Schema-ordered (RICS) or topic-ordered (content) JSON preview for the UI."""
    section_ids = schema.section_ids()
    sections_out = []
    for s in sorted(result.sections, key=lambda s: _preview_order_key(s, section_ids)):
        sections_out.append(
            {
                "section_id": s.section_id,
                "title": s.title,
                "text": s.text,
                "paragraph": s.text,
                "rating_value": s.rating_value,
                "status": s.status,
                "notes": s.notes,
                "rag_sources": s.rag_sources,
                "reference_sources": [rs.model_dump() for rs in s.reference_sources],
                "grounding_passed": s.grounding_passed,
                "unmatched_observations": s.unmatched_observations,
                "topic_id": s.topic_id,
                "topic_label": s.topic_label,
                "subtopic_id": s.subtopic_id,
            }
        )

    mapped_ok = sum(1 for s in result.sections if s.status == "OK")
    needing_review = sum(1 for s in result.sections if s.status in _REVIEW_STATUSES)
    total = len(result.sections) or 1
    review_ratio = needing_review / total
    manual_review_required = review_ratio > settings.grounding_alert_threshold

    preview = {
        "tenant_id": result.tenant_id,
        "schema_version": result.schema_version,
        "schema_report_type": schema.report_type,
        "rating_system": schema.rating_system.model_dump(),
        "sections_mapped": mapped_ok,
        "sections_needing_review": needing_review,
        "review_ratio": round(review_ratio, 4),
        "manual_review_required": manual_review_required,
        "sections": sections_out,
        "unassigned_text": result.unassigned_text,
        "property_type": result.property_type,
        "tenure": result.tenure,
    }
    if result.evaluation is not None:
        preview["evaluation"] = result.evaluation
    return preview


def from_sections_payload(
    tenant_id: str,
    schema: TemplateSchema,
    sections_payload: dict[str, dict],
    *,
    property_type: str = "",
    tenure: str = "",
    unassigned_text: str = "",
) -> ReportResult:
    """Rebuild a ReportResult from persisted section payloads (legacy session or preview).

    Content-mode payloads carry a ``topic_id`` and use sub-topic codes that are not
    part of the RICS schema, so they are rebuilt directly from the payload keys and
    ordered by topic; RICS-mode payloads are rebuilt in schema order.
    """
    sections: list[GeneratedSection] = []
    content_codes = [
        code
        for code, p in sections_payload.items()
        if isinstance(p, dict) and str(p.get("topic_id") or "").strip()
    ]
    if content_codes:
        from backend.content_based import taxonomy

        for code, payload in sections_payload.items():
            if not payload or not (payload.get("text") or "").strip():
                continue
            title = str(
                payload.get("subtopic_label")
                or taxonomy.subtopic_label(
                    str(payload.get("topic_id") or ""), str(payload.get("subtopic_id") or code)
                )
            )
            sections.append(payload_to_generated_section(code, title, payload, schema))
        sections.sort(key=lambda s: (taxonomy.topic_order(s.topic_id), s.subtopic_id or ""))
        return ReportResult(
            tenant_id=tenant_id,
            schema_version=schema.version,
            property_type=property_type,
            tenure=tenure,
            sections=sections,
            unassigned_text=unassigned_text,
        )

    for sec in schema.ordered_sections():
        payload = sections_payload.get(sec.id)
        if not payload or not (payload.get("text") or "").strip():
            continue
        sections.append(
            payload_to_generated_section(sec.id, sec.title, payload, schema)
        )
    return ReportResult(
        tenant_id=tenant_id,
        schema_version=schema.version,
        property_type=property_type,
        tenure=tenure,
        sections=sections,
        unassigned_text=unassigned_text,
    )


def to_docx(
    result: ReportResult,
    schema: TemplateSchema,
    *,
    title: str = "Survey Report",
    include_footer: bool = False,
    template_docx_path: str | None = None,
    section_photo_paths: dict[str, list[str]] | None = None,
) -> bytes:
    path = template_docx_path
    if path is None and settings.branded_template_path is not None:
        path = str(settings.branded_template_path)
    return docx_builder.build_docx(
        result,
        schema,
        title=title,
        include_footer=include_footer,
        template_docx_path=path,
        section_photo_paths=section_photo_paths,
    )
