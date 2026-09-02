"""Approach 2: per-section LLM coverage judge (notes vs generated prose)."""

from __future__ import annotations

import logging

from backend.evaluation.judge_llm import (
    call_judge_parse,
    is_available,
    resolved_max_tokens,
    resolved_model,
    resolved_provider,
    resolved_reasoning_effort,
    unavailable_reason,
)
from backend.evaluation.models import (
    CoverageJudgeResponse,
    NoteFactJudgment,
    SectionEvalInput,
    SectionEvaluation,
)
from backend.evaluation.prompts import build_coverage_messages, prompt_record

logger = logging.getLogger(__name__)

_VALID_STATUS = frozenset({"covered", "missing", "partial"})


def _normalize_judgments(
    observations: list[str],
    raw: CoverageJudgeResponse,
) -> tuple[list[NoteFactJudgment], list[str], int]:
    """Map structured judge output onto the input notes; score omitted notes missing."""
    by_note: dict[str, NoteFactJudgment] = {}

    for item in raw.judgments:
        note = (item.note or "").strip()
        status = (item.status or "").strip().lower()
        if not note or status not in _VALID_STATUS:
            continue
        by_note[note.lower()] = NoteFactJudgment(
            note=note,
            status=status,  # type: ignore[arg-type]
            evidence=(item.evidence or "").strip(),
        )

    missing_listed = {
        str(f).strip().lower() for f in (raw.missing_facts or []) if str(f).strip()
    }

    judgments: list[NoteFactJudgment] = []
    omitted = 0
    for obs in observations:
        key = obs.strip()
        if not key:
            continue
        existing = by_note.get(key.lower())
        if existing is not None:
            judgments.append(existing)
            continue
        omitted += 1
        judgments.append(
            NoteFactJudgment(
                note=key,
                status="missing",
                evidence="omitted_by_judge" if key.lower() not in missing_listed else "",
            )
        )

    missing_facts = [j.note for j in judgments if j.status in ("missing", "partial")]
    return judgments, missing_facts, omitted


def _rollup_coverage(
    judgments: list[NoteFactJudgment],
) -> tuple[int, int, int, float | None]:
    covered = sum(1 for j in judgments if j.status == "covered")
    missing = sum(1 for j in judgments if j.status == "missing")
    partial = sum(1 for j in judgments if j.status == "partial")
    total = len(judgments)
    rate = (covered + 0.5 * partial) / total if total else None
    return covered, missing, partial, rate


def _coverage_prompt_payload(messages: list[dict[str, str]]) -> dict:
    effort = resolved_reasoning_effort()
    return {
        "coverage": prompt_record(
            messages,
            model=resolved_model(),
            reasoning_effort=effort,
            max_tokens=resolved_max_tokens(effort),
            provider=resolved_provider(),
        )
    }


async def score_section_coverage(inp: SectionEvalInput) -> SectionEvaluation:
    """Run Approach 2 coverage judge for one section."""
    observations = [o.strip() for o in (inp.observations or []) if o and o.strip()]
    base = SectionEvaluation(
        section_id=inp.section_id,
        title=inp.title,
        observations=observations,
        generated_text=inp.generated_text or "",
        baseline_text=inp.baseline_text or "",
    )
    if not observations:
        return base
    if not (inp.generated_text or "").strip():
        judgments = [
            NoteFactJudgment(note=o, status="missing", evidence="empty generated text")
            for o in observations
        ]
        covered, missing, partial, rate = _rollup_coverage(judgments)
        base.note_judgments = judgments
        base.covered_count = covered
        base.missing_count = missing
        base.partial_count = partial
        base.coverage_rate = rate
        base.missing_facts = [j.note for j in judgments]
        return base
    if not is_available():
        base.error = unavailable_reason()
        return base

    messages = build_coverage_messages(
        section_id=inp.section_id,
        title=inp.title,
        observations=observations,
        generated_text=inp.generated_text,
    )
    base.prompt = _coverage_prompt_payload(messages)

    try:
        parsed = await call_judge_parse(
            messages,
            response_format=CoverageJudgeResponse,
            call_label="evaluation_coverage",
            section_id=inp.section_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "evaluation_coverage_failed section=%s err=%s",
            inp.section_id,
            exc,
        )
        base.error = str(exc)
        return base

    if parsed is None:
        base.error = "empty_judge_response"
        return base
    if not parsed.judgments:
        base.error = "empty_judge_response"
        return base

    judgments, missing_facts, omitted = _normalize_judgments(observations, parsed)
    if omitted:
        base.error = f"judge_omitted_{omitted}_of_{len(observations)}_notes"
    covered, missing, partial, rate = _rollup_coverage(judgments)
    base.note_judgments = judgments
    base.covered_count = covered
    base.missing_count = missing
    base.partial_count = partial
    base.coverage_rate = rate
    base.missing_facts = missing_facts
    return base
