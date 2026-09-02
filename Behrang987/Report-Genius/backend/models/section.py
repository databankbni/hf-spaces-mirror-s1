"""Per-section note model produced by the schema-driven notes parser."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SectionNote(BaseModel):
    """Scrubbed notes routed to a single discovered section."""

    section_id: str = Field(description="Target section id, or 'UNASSIGNED'.")
    text: str = Field(
        default="", description="Joined verbatim note text for this section."
    )
    raw_observations: list[str] = Field(
        default_factory=list,
        description="Individual observations extracted from the notes.",
    )
    rating_value: str | None = Field(
        default=None,
        description="Detected rating token, only set when the schema has a rating system.",
    )
    shorthand_expanded: str | None = Field(
        default=None,
        description="Expanded shorthand text when notes_expansion_enabled is active.",
    )

    @model_validator(mode="after")
    def _sync_text_from_observations(self) -> SectionNote:
        if self.raw_observations and not self.text.strip():
            self.text = "\n".join(self.raw_observations).strip()
        elif self.text.strip() and not self.raw_observations:
            self.raw_observations = [
                line.strip() for line in self.text.split("\n") if line.strip()
            ]
        return self
