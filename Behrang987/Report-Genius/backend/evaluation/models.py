"""Pydantic models for post-generation report evaluation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CoverageStatus = Literal["covered", "missing", "partial"]
EvaluationRollupStatus = Literal["PASS", "WARN", "FAIL", "SKIPPED"]


class NoteFactJudgment(BaseModel):
    """One surveyor note atom scored for coverage in generated prose."""

    note: str
    status: CoverageStatus
    evidence: str = Field(
        default="",
        description="Short span or reason from the judge (empty when missing).",
    )


class CoverageJudgmentItem(BaseModel):
    """One note judgment in the Structured Outputs coverage schema."""

    note: str = Field(
        description="Verbatim surveyor note string copied from surveyor_notes.",
    )
    status: CoverageStatus = Field(
        description="covered | partial | missing",
    )
    evidence: str = Field(
        description=(
            "Short span from generated_section for covered/partial "
            "(<=25 words); empty string when missing."
        ),
    )


class CoverageJudgeResponse(BaseModel):
    """Structured Outputs schema for the Approach 2 coverage judge."""

    judgments: list[CoverageJudgmentItem] = Field(
        description=(
            "Exactly one judgment per surveyor_notes item, same order, "
            "note strings copied verbatim."
        ),
    )
    missing_facts: list[str] = Field(
        description=(
            "Every note whose status is missing or partial, verbatim, "
            "same strings as in judgments."
        ),
    )


class FaithfulnessJudgeResponse(BaseModel):
    """Structured Outputs schema for the Approach 3 faithfulness judge."""

    faithfulness: float = Field(
        description=(
            "Score in [0,1]: 1.0 means every property-specific claim in the "
            "generated prose is supported by the notes."
        ),
    )
    unsupported_claims: list[str] = Field(
        description=(
            "Property-specific claims in the generated prose that are not "
            "supported by the surveyor notes."
        ),
    )


class CombinedJudgeResponse(BaseModel):
    """Structured Outputs schema for the golden combined judge."""

    faithfulness: float = Field(
        description=(
            "Score in [0,1]: every property-specific claim in prose supported "
            "by the notes."
        ),
    )
    answer_correctness: float = Field(
        description=(
            "Score in [0,1]: every concrete fact in the notes reflected in prose."
        ),
    )
    unsupported_claims: list[str] = Field(
        description="Ungrounded property-specific claims in the generated prose.",
    )
    missing_facts: list[str] = Field(
        description="Surveyor-note facts missing from the generated prose.",
    )


class SectionEvaluation(BaseModel):
    """Per-leaf evaluation outcome (Approach 2 coverage + optional Approach 3)."""

    section_id: str
    title: str = ""
    observations: list[str] = Field(default_factory=list)
    generated_text: str = ""
    baseline_text: str = ""
    note_judgments: list[NoteFactJudgment] = Field(default_factory=list)
    covered_count: int = 0
    missing_count: int = 0
    partial_count: int = 0
    coverage_rate: float | None = None
    missing_facts: list[str] = Field(default_factory=list)
    faithfulness_score: float | None = None
    unsupported_claims: list[str] = Field(default_factory=list)
    prompt: dict | None = Field(
        default=None,
        description=(
            "Final judge prompt(s) sent for this subsection. Shape mirrors retrieval "
            "manifests: {coverage?: {model, reasoning_effort, system, "
            "final_user_prompt, messages}, faithfulness?: {...}}."
        ),
    )
    error: str | None = Field(
        default=None,
        description="Set when the LLM judge failed for this section.",
    )


class MissingFactRef(BaseModel):
    """Report-level missing fact with section attribution."""

    section_id: str
    fact: str


class UnsupportedClaimRef(BaseModel):
    """Report-level unsupported claim with section attribution."""

    section_id: str
    claim: str


class EvaluationResult(BaseModel):
    """Full-report advisory evaluation rollup."""

    enabled: bool = True
    status: EvaluationRollupStatus = "SKIPPED"
    coverage_rate: float | None = None
    faithfulness_score: float | None = None
    total_note_atoms: int = 0
    covered_note_atoms: int = 0
    missing_facts: list[MissingFactRef] = Field(default_factory=list)
    unsupported_claims: list[UnsupportedClaimRef] = Field(default_factory=list)
    sections: list[SectionEvaluation] = Field(default_factory=list)
    coverage_enabled: bool = True
    faithfulness_enabled: bool = False
    model: str = ""
    error: str | None = None


class SectionEvalInput(BaseModel):
    """Inputs for one section judge call."""

    section_id: str
    title: str = ""
    observations: list[str] = Field(default_factory=list)
    generated_text: str = ""
    baseline_text: str = ""
