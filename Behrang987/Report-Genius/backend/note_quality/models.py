"""Pydantic models for note-quality grading."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The practice's three states, plus one for "we could not tell".
GRADE_GREEN = "green"
GRADE_YELLOW = "yellow"
GRADE_RED = "red"
GRADE_UNKNOWN = "unknown"

# Only the three the model is allowed to return. ``unknown`` is ours, used when a
# call fails or the judge stays silent, so a broken call can never read as a pass.
GradeValue = Literal["green", "yellow", "red"]

ORDERED_GRADES: tuple[str, ...] = (GRADE_GREEN, GRADE_YELLOW, GRADE_RED, GRADE_UNKNOWN)


# ── Structured Outputs schema ─────────────────────────────────────────────────
class SubtopicJudgment(BaseModel):
    """One sub-topic graded against its rubric."""

    code: str = Field(
        description="Sub-topic id copied verbatim from the request.",
    )
    grade: GradeValue = Field(
        description="green | yellow | red, per that sub-topic's rubric.",
    )
    present: list[str] = Field(
        description=(
            "Items from that sub-topic's 'relevant information may include' list "
            "that the notes actually cover, copied verbatim from the list."
        ),
    )
    missing: list[str] = Field(
        description=(
            "Up to four items from the same list, copied verbatim, that would most "
            "improve these notes. Still useful on a green: the rubric does not "
            "require every item, but naming the gaps helps the surveyor."
        ),
    )
    reason: str = Field(
        description=(
            "One sentence, under 25 words, in the rubric's own language, saying "
            "why the notes do or do not meet the Green benchmark."
        ),
    )


class NoteQualityJudgeResponse(BaseModel):
    """Structured Outputs schema for one report group of the note-quality judge."""

    judgments: list[SubtopicJudgment] = Field(
        description="Exactly one judgment per sub-topic in the request, same order.",
    )


# ── Result types ──────────────────────────────────────────────────────────────
class GradeItem(BaseModel):
    """One sub-topic's notes, as handed to the grader."""

    code: str
    notes: str = ""


class SubtopicGrade(BaseModel):
    """The grade for one sub-topic, as returned to the client."""

    code: str
    grade: str = GRADE_UNKNOWN
    present: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    reason: str = ""
    # How we arrived at it, so a red from "no notes" is distinguishable from a red
    # the judge actually reasoned about.
    method: str = "unknown"  # empty | judge | unavailable | error


class NoteQualityResult(BaseModel):
    """Everything one grading pass produced."""

    grades: dict[str, SubtopicGrade] = Field(default_factory=dict)
    not_scored: list[str] = Field(default_factory=list)
    llm_available: bool = False
    unavailable_reason: str = ""
    judged_count: int = 0
    call_count: int = 0
    llm_io: list[dict] = Field(
        default_factory=list,
        description="Per-group prompts and parsed replies, written into latest.json.",
    )

    def tally(self) -> dict[str, int]:
        counts = dict.fromkeys(ORDERED_GRADES, 0)
        for grade in self.grades.values():
            counts[grade.grade] = counts.get(grade.grade, 0) + 1
        return counts
