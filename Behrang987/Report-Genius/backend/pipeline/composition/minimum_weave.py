"""Minimum AI: in-place fact update on the REFERENCE baseline."""

from __future__ import annotations

from backend.models.schema import TemplateSchema
from backend.pipeline.reference_mapper import map_reference_paragraph


def map_minimum_reference(
    reference_paragraph: str,
    observations: list[str],
    schema: TemplateSchema,
    *,
    section_title: str = "",
    section_id: str = "",
) -> str:
    """Keep the whole reference paragraph; apply in-place fact updates only."""
    text, _usage = map_reference_paragraph(
        reference_paragraph,
        observations,
        schema,
        "minimum",
        section_id=section_id,
        section_title=section_title,
    )
    return text


def weave_minimum_ai(observations: list[str], reference_paragraph: str) -> str:
    from backend.models.schema import TemplateSchema

    return map_minimum_reference(reference_paragraph, observations, TemplateSchema())
