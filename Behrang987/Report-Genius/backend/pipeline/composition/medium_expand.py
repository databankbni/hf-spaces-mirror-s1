"""Medium AI — same in-place baseline adaptation as minimum/maximum."""

from __future__ import annotations

from backend.models.schema import TemplateSchema
from backend.pipeline.reference_mapper import map_reference_paragraph


def expand_medium_ai(
    observations: list[str],
    reference_paragraph: str,
    *,
    extra_references: list[str] | None = None,
    schema: TemplateSchema | None = None,
    section_title: str = "",
    section_id: str = "",
    rating_value: str | None = None,
) -> str:
    """Map notes onto the full REFERENCE baseline via in-place fact update."""
    _ = extra_references
    sch = schema or TemplateSchema()
    text, _usage = map_reference_paragraph(
        reference_paragraph,
        observations,
        sch,
        "medium",
        section_id=section_id,
        section_title=section_title,
        rating_value=rating_value,
        extra_references=extra_references,
    )
    return text
