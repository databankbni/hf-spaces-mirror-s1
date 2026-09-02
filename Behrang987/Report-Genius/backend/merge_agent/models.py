"""Models for dual-path draft merge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DualPathDraft:
    """One section's two path drafts ready for merge."""

    section_id: str
    section_title: str
    past_report_draft: str
    standard_paragraph_draft: str
    style_cues: str = ""  # unused; merge prompts no longer inject style cues
    past_report_source: str = ""
    standard_paragraph_source: str = ""
    inspection_notes: str = ""


@dataclass
class MergeResult:
    """Merge LLM output for one section."""

    section_id: str
    section_title: str
    merged_text: str
    llm_usage: dict[str, Any] | None = None
    past_report_draft: str = ""
    standard_paragraph_draft: str = ""
    past_report_source: str = ""
    standard_paragraph_source: str = ""
    model: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
