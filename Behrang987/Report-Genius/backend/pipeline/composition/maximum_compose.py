"""Maximum AI — same in-place baseline adaptation as minimum/medium."""

from __future__ import annotations

from backend.models.schema import TemplateSchema
from backend.pipeline.reference_mapper import map_reference_paragraph


def compose_maximum_ai(
    observations: list[str],
    reference_excerpts: list[str],
    *,
    section_title: str = "",
    section_id: str = "",
    schema: TemplateSchema | None = None,
    rating_value: str | None = None,
) -> str:
    """Apply in-place fact updates to the assembled REFERENCE baseline."""
    refs = [r.strip() for r in reference_excerpts if r.strip()]
    sch = schema or TemplateSchema()
    baseline = refs[0] if refs else ""
    text, _usage = map_reference_paragraph(
        baseline,
        observations,
        sch,
        "maximum",
        section_id=section_id,
        section_title=section_title,
        rating_value=rating_value,
    )
    return text
