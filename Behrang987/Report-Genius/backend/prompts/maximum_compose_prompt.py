"""Maximum AI — delegates to reference_mapper tier routing."""

from __future__ import annotations

from backend.models.schema import TemplateSchema
from backend.pipeline.reference_mapper import (
    build_interference_messages,
    compose_mapping_system_prompt,
)

MAXIMUM_SYSTEM = compose_mapping_system_prompt("maximum")


def build_maximum_messages(notes: str, baseline: str) -> list[dict[str, str]]:
    observations = [line.strip() for line in notes.split("\n") if line.strip()]
    if not observations and notes.strip():
        observations = [notes.strip()]
    return build_interference_messages(
        "maximum",
        observations=observations,
        baseline=baseline,
        schema=TemplateSchema(),
    )


def build_maximum_compose_messages(
    observations: list[str],
    reference_excerpts: list[str],
    **_: object,
) -> list[dict[str, str]]:
    notes = "\n".join(o.strip() for o in observations if o.strip())
    baseline = "\n\n".join(t.strip() for t in reference_excerpts if t.strip())
    return build_maximum_messages(notes, baseline)
