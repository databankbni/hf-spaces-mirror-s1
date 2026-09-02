"""Pydantic schemas for the multi-pass RICS validation orchestrator."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# One audit + repair attempt was too tight: genuinely-contaminated multi-violation
# sections could not converge within the budget and were quarantined wholesale. A
# modest bump gives the repair pass room to land grounded prose before the circuit
# breaker fires, while still bounding token/latency cost per section.
MAX_VALIDATION_ITERATIONS = 4

SectionValidationStatus = Literal["STABILIZED", "ROLLED_BACK"]


class ViolationType(str, Enum):  # noqa: UP042 - str+Enum semantics differ from StrEnum
    """Auditor violation taxonomy — matches Prompt 3A VIOLATION_TAXONOMY."""

    invented_defect = "invented_defect"
    invented_material = "invented_material"
    invented_mechanism = "invented_mechanism"
    invented_structural_relationship = "invented_structural_relationship"
    ungrounded_location = "ungrounded_location"
    ungrounded_specific_detail = "ungrounded_specific_detail"
    invented_specialist_action = "invented_specialist_action"
    unsupported_cause = "unsupported_cause"
    stale_historical_data = "stale_historical_data"
    stale_condition_rating = "stale_condition_rating"
    placeholder_leakage = "placeholder_leakage"
    non_british_english = "non_british_english"
    unsupported_monitoring = "unsupported_monitoring"
    # Legacy aliases retained for backward-compatible payloads.
    fabricated_measurement = "fabricated_measurement"
    incorrect_condition_rating = "incorrect_condition_rating"


class AuditorViolation(BaseModel):
    """Single auditor violation entry."""

    violation_type: str
    offending_text: str
    reason: str

    @field_validator("violation_type", "offending_text", "reason", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> str:
        return str(value or "").strip()


class AuditorPayload(BaseModel):
    """Auditor LLM JSON payload — read-only Prompt 3A OUTPUT_CONTRACT."""

    model_config = ConfigDict(populate_by_name=True)

    passed: bool
    audit_summary: str = Field(default="", alias="_audit_summary")
    violations: list[AuditorViolation] = Field(default_factory=list)
    cleaned_text: str = (
        ""  # Legacy field; auditor is read-only — repair pass mutates text.
    )

    @field_validator("audit_summary", "cleaned_text", mode="before")
    @classmethod
    def _coerce_optional_text(cls, value: object) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _enforce_contract(self) -> AuditorPayload:
        if self.violations:
            object.__setattr__(self, "passed", False)
        elif self.passed:
            object.__setattr__(self, "violations", [])
        return self


class SectionValidationInput(BaseModel):
    """Incoming structural payload for one report section."""

    section_id: str
    section_label: str = ""
    baseline_paragraph: str
    draft_text: str
    observations: list[str] = Field(default_factory=list)
    template_paragraphs: list[str] = Field(default_factory=list)
    relaxed_violation_types: list[str] = Field(
        default_factory=list,
        description=(
            "Auditor violation types demoted to soft (non-blocking) for this "
            "section — set from the Expert-mode preference flags. Identity-fact "
            "types are never honoured here (see interference.HARD_VIOLATION_TYPES)."
        ),
    )

    @field_validator("section_id", mode="before")
    @classmethod
    def _normalize_section_id(cls, value: object) -> str:
        return str(value or "").strip().upper()

    @field_validator("baseline_paragraph", "draft_text", mode="before")
    @classmethod
    def _coerce_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("observations", mode="before")
    @classmethod
    def _coerce_observations(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            lines = [
                line.strip().lstrip("•-*·▸▹◆►").strip()
                for line in value.split("\n")
                if line.strip()
            ]
            return lines or [value.strip()]
        return [str(item).strip() for item in value if str(item).strip()]


class ValidationFailureMetadata(BaseModel):
    """Structured failure record for circuit-breaker rollbacks."""

    section_id: str
    reason: str
    iterations: int = 0
    last_error: str | None = None
    leakage_tokens: list[str] = Field(default_factory=list)
    violation_count: int = 0


class SectionValidationResult(BaseModel):
    """Outcome of the judge-editor loop for one section."""

    section_id: str
    status: SectionValidationStatus
    text: str
    iterations: int = 0
    leakage_tokens: list[str] = Field(default_factory=list)
    failure: ValidationFailureMetadata | None = None
    final_violations: list[AuditorViolation] = Field(default_factory=list)
