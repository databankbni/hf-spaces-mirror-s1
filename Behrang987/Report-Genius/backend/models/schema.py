"""Discovered template schema models.

The schema is the structural authority for a tenant. It is produced by
``core.template_discoverer`` from the operator master template and persisted as
``schema.json``. Nothing in the pipeline hardcodes RICS section codes; everything
flows from this schema.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, computed_field


class RatingValue(BaseModel):
    """One allowed value of a rating/condition system."""

    value: str = Field(
        description="Canonical rating token, e.g. '1', '2', '3' or 'NI'."
    )
    label: str = Field(
        default="", description="Human label, e.g. 'No repair currently needed'."
    )
    colour: str = Field(
        default="", description="Optional display colour hint (e.g. 'green')."
    )

    @property
    def meaning(self) -> str | None:
        return self.label or None


class RatingSystem(BaseModel):
    """Rating system discovered in the master, if any.

    ``detected`` gates all rating behaviour downstream: if the template defines no
    rating system, the pipeline must never emit ratings.
    """

    detected: bool = Field(default=False)
    name: str = Field(
        default="", description="Discovered rating system label from the template."
    )
    type: str | None = Field(
        default=None,
        description="numeric | letter | text | boolean — None if absent.",
    )
    values: list[RatingValue] = Field(default_factory=list)
    format_template: str | None = Field(
        default=None,
        description="How the rating appears in template text, e.g. 'Rating [VALUE]'.",
    )
    inline_example: str | None = Field(
        default=None,
        description="Verbatim rating example from the template.",
    )


class PlaceholderSyntax(BaseModel):
    """How blanks/options are marked in the master so notes can be slotted in."""

    free_text_markers: list[str] = Field(
        default_factory=lambda: ["<text>"],
        description="Tokens denoting a free-text blank, e.g. '<text>'.",
    )
    option_pattern: str = Field(
        default=r"\(([^()]+)\)",
        description="Regex matching an inline option group, e.g. '(pitched)(flat)'.",
    )
    variant_pattern: str = Field(
        default=r"\[([A-Z])\]",
        description="Regex matching a variant tag, e.g. '[A]' / '[B]'.",
    )
    detected_formats: list[str] = Field(default_factory=list)
    primary_format: str | None = Field(default=None)


class SectionDefinition(BaseModel):
    """One section discovered in the master template."""

    id: str = Field(
        description="Stable section id (discovered code or slug), e.g. 'E1'."
    )
    title: str = Field(description="Section heading text.")
    order: int = Field(description="Zero-based order within the report.")
    level: int = Field(default=1, description="Heading depth (1 = top level).")
    parent_id: str | None = Field(default=None)
    has_rating_field: bool = Field(
        default=False,
        description="Whether this section carries a rating in the master.",
    )
    rating_inline_format: str | None = Field(
        default=None,
        description="Verbatim rating format for this section, if any.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Terms used to route free-text notes to this section.",
    )
    placeholder_hints: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        """Alias for ``title`` (spec compatibility)."""
        return self.title

    @property
    def keyword_set(self) -> set[str]:
        return {k.lower() for k in self.keywords if k.strip()}


class TemplateSchema(BaseModel):
    """Full discovered schema for a tenant's report template."""

    tenant_id: str = Field(default="", description="Owning tenant id.")
    version: int = Field(default=1)
    source_filename: str = Field(
        default="", description="Primary source file (report template)."
    )
    report_type: str | None = Field(
        default=None, description="Detected report type name."
    )
    extracted_at: str | None = Field(
        default=None, description="ISO timestamp of discovery."
    )
    section_hierarchy: str = Field(
        default="flat",
        description="flat | two-level | three-level",
    )
    report_template_source: str = Field(
        default="",
        description="PDF report template used for section structure discovery.",
    )
    standard_paragraphs_source: str = Field(
        default="",
        description="Word file used for approved standard paragraph wording.",
    )
    section_alias_map: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Maps report-template section id -> standard-paragraph section id "
            "(e.g. PDF D1 -> Word E1 for Chimney stacks)."
        ),
    )
    paragraph_section_titles: dict[str, str] = Field(
        default_factory=dict,
        description="Standard-paragraph section id -> title from the Word master.",
    )
    raw_section_texts: dict[str, str] = Field(
        default_factory=dict,
        description="section_id -> template body text from report template.",
    )
    rating_system: RatingSystem = Field(default_factory=RatingSystem)
    placeholders: PlaceholderSyntax = Field(default_factory=PlaceholderSyntax)
    sections: list[SectionDefinition] = Field(default_factory=list)
    additional_metadata: dict[str, Any] = Field(default_factory=dict)

    def ordered_sections(self) -> list[SectionDefinition]:
        return sorted(self.sections, key=lambda s: s.order)

    def section_ids(self) -> list[str]:
        return [s.id for s in self.ordered_sections()]

    def get_section(self, section_id: str) -> SectionDefinition | None:
        for s in self.sections:
            if s.id == section_id:
                return s
        return None

    def paragraph_section_id(self, report_section_id: str) -> str:
        """Resolve the Word MASTER bucket id for a report-template section."""
        return self.section_alias_map.get(report_section_id, report_section_id)
