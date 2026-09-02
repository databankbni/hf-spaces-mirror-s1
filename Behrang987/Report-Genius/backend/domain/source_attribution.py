"""Format REFERENCE-tier provenance for generated sections."""

from __future__ import annotations

from backend.config import settings
from backend.models.report import ReferenceSource
from backend.models.schema import TemplateSchema
from backend.rag.types import TIER_REFERENCE, SearchHit


def report_filename_from_hit(hit: SearchHit) -> str:
    if hit.source_filename:
        return hit.source_filename
    if hit.doc_id.startswith("reference:"):
        return hit.doc_id.split(":", 1)[-1]
    return hit.doc_id or "unknown"


def section_title_for_id(schema: TemplateSchema, section_id: str) -> str:
    sec = schema.get_section(section_id)
    if sec:
        return sec.title
    return schema.paragraph_section_titles.get(section_id, "")


def build_reference_sources(
    hits: list[SearchHit],
    schema: TemplateSchema,
    *,
    max_sources: int | None = None,
) -> list[ReferenceSource]:
    """Build provenance records from REFERENCE hits only (never MASTER)."""
    cap = int(max_sources if max_sources is not None else settings.retrieval_top_k)
    out: list[ReferenceSource] = []
    seen: set[tuple[str, str, int]] = set()

    for hit in hits:
        if hit.tier != TIER_REFERENCE:
            continue
        filename = report_filename_from_hit(hit)
        sid = (hit.section_id or "").strip().upper()
        para = hit.paragraph_index or 0
        key = (filename, sid, para)
        if key in seen:
            continue
        seen.add(key)

        out.append(
            ReferenceSource(
                report_filename=filename,
                section_id=sid,
                section_title=section_title_for_id(schema, sid),
                paragraph_index=para,
                tier=TIER_REFERENCE,
            )
        )
        if len(out) >= cap:
            break

    return out


def format_reference_source(source: ReferenceSource) -> str:
    title = f" ({source.section_title})" if source.section_title else ""
    if source.paragraph_index > 0:
        para = f", paragraph {source.paragraph_index}"
    else:
        para = ""
    sid = source.section_id or "unknown section"
    return f'Past report "{source.report_filename}", section {sid}{title}{para}'


def format_reference_attribution(
    hits: list[SearchHit],
    schema: TemplateSchema,
    *,
    max_sources: int | None = None,
) -> tuple[list[ReferenceSource], list[str]]:
    sources = build_reference_sources(hits, schema, max_sources=max_sources)
    labels = [format_reference_source(s) for s in sources]
    return sources, labels
