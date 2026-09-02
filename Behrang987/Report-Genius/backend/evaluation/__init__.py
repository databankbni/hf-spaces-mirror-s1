"""Post-generation report evaluation (Approach 2 coverage + optional Approach 3 faithfulness).

Public API for the live pipeline and golden harness.
"""

from __future__ import annotations

from backend.evaluation.faithfulness import judge_combined_section
from backend.evaluation.manifest import (
    evaluation_manifest_path,
    load_evaluation_manifest,
    write_evaluation_manifest,
)
from backend.evaluation.models import (
    CombinedJudgeResponse,
    CoverageJudgeResponse,
    CoverageJudgmentItem,
    EvaluationResult,
    FaithfulnessJudgeResponse,
    MissingFactRef,
    NoteFactJudgment,
    SectionEvalInput,
    SectionEvaluation,
    UnsupportedClaimRef,
)
from backend.evaluation.orchestrator import (
    build_section_eval_inputs,
    evaluate_report,
)

__all__ = [
    "CombinedJudgeResponse",
    "CoverageJudgeResponse",
    "CoverageJudgmentItem",
    "EvaluationResult",
    "FaithfulnessJudgeResponse",
    "MissingFactRef",
    "NoteFactJudgment",
    "SectionEvalInput",
    "SectionEvaluation",
    "UnsupportedClaimRef",
    "build_section_eval_inputs",
    "evaluate_report",
    "evaluation_manifest_path",
    "judge_combined_section",
    "load_evaluation_manifest",
    "write_evaluation_manifest",
]
