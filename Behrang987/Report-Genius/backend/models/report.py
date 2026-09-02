"""Result models for a generated report."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReferenceSource(BaseModel):
    """Provenance for content mapped from an uploaded past report (REFERENCE tier)."""

    report_filename: str
    section_id: str = ""
    section_title: str = ""
    paragraph_index: int = 0
    tier: str = Field(
        default="reference", description="Always reference for user-facing attribution."
    )


class GeneratedSection(BaseModel):
    """One section of mapped output."""

    section_id: str
    title: str
    text: str = Field(default="")
    rating_value: str | None = Field(default=None)
    status: str = Field(
        default="OK",
        description="OK | empty | NO_RAG_MATCH | GROUNDING_REVIEW | UNASSIGNED",
    )
    notes: str = Field(default="", description="Diagnostic note for this section.")
    rag_sources: list[str] = Field(
        default_factory=list,
        description="Human-readable REFERENCE provenance strings.",
    )
    reference_sources: list[ReferenceSource] = Field(
        default_factory=list,
        description="Structured provenance from uploaded past reports only.",
    )
    grounding_passed: bool = Field(default=True)
    unmatched_observations: list[str] = Field(default_factory=list)
    shorthand_expanded: str | None = Field(
        default=None,
        description="Optional expanded shorthand for this section's notes.",
    )
    # Content-based topic mode: populated when structure_mode="content" so the
    # preview/DOCX can group by topic. Empty for the RICS structure mode.
    topic_id: str = Field(default="")
    topic_label: str = Field(default="")
    subtopic_id: str = Field(default="")


class ReportResult(BaseModel):
    """Full generation result before DOCX assembly."""

    tenant_id: str
    schema_version: int
    property_type: str = Field(default="")
    tenure: str = Field(default="")
    sections: list[GeneratedSection] = Field(default_factory=list)
    unassigned_text: str = Field(default="")
    active_section_count: int = Field(
        default=0,
        description="Leaf subsections with notes and/or AI-selected photos.",
    )
    processed_section_count: int = Field(
        default=0,
        description="Leaf subsections actually processed in this run.",
    )
    evaluation: dict | None = Field(
        default=None,
        description=(
            "Advisory post-generation evaluation payload (EvaluationResult.model_dump). "
            "None when evaluation is disabled."
        ),
    )
