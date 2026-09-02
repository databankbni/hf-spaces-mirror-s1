"""Note-quality grading: Green / Yellow / Red per review sub-topic.

Stage B of content-mode note intake. Stage A
(:mod:`backend.content_based.intake`) decides *where* each fragment of the
surveyor's notes belongs; this package decides whether what landed there is good
enough, judged strictly against the practice's own rubric.

Public surface::

    from backend.note_quality import grade_subtopics, GradeItem, SubtopicGrade

Everything else — the rubric text, the prompt builders, the LLM transport — is an
implementation detail of the package and should be imported from its submodule.
"""

from backend.note_quality.models import (
    GRADE_GREEN,
    GRADE_RED,
    GRADE_UNKNOWN,
    GRADE_YELLOW,
    GradeItem,
    NoteQualityResult,
    SubtopicGrade,
)
from backend.note_quality.orchestrator import grade_subtopics
from backend.note_quality.rubric import (
    RUBRIC_VERSION,
    UNGRADED_CODES,
    is_gradable,
    rubric_for,
)

__all__ = [
    "GRADE_GREEN",
    "GRADE_RED",
    "GRADE_UNKNOWN",
    "GRADE_YELLOW",
    "RUBRIC_VERSION",
    "UNGRADED_CODES",
    "GradeItem",
    "NoteQualityResult",
    "SubtopicGrade",
    "grade_subtopics",
    "is_gradable",
    "rubric_for",
]
