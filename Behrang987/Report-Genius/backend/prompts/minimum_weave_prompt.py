"""Minimum AI — delegates to reference_mapper tier routing."""

from __future__ import annotations

from backend.models.schema import TemplateSchema
from backend.pipeline.reference_mapper import (
    build_interference_messages,
    compose_mapping_system_prompt,
)

MINIMUM_SYSTEM = compose_mapping_system_prompt("minimum")


def build_minimum_messages(notes: str, baseline: str) -> list[dict[str, str]]:
    observations = [line.strip() for line in notes.split("\n") if line.strip()]
    if not observations and notes.strip():
        observations = [notes.strip()]
    return build_interference_messages(
        "minimum",
        observations=observations,
        baseline=baseline,
        schema=TemplateSchema(),
    )


def build_minimum_map_messages(
    observations: list[str],
    reference_paragraph: str,
    **_: object,
) -> list[dict[str, str]]:
    notes = "\n".join(o.strip() for o in observations if o.strip())
    return build_minimum_messages(notes, reference_paragraph)
