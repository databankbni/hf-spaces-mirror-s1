"""Approach 3: per-section LLM faithfulness judge (notes + generated + baseline)."""

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
    CombinedJudgeResponse,
    FaithfulnessJudgeResponse,
    SectionEvalInput,
)
from backend.evaluation.prompts import (
    build_combined_judge_messages,
    build_faithfulness_messages,
    prompt_record,
)

logger = logging.getLogger(__name__)


def _clip01(value: object) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _faithfulness_prompt_payload(messages: list[dict[str, str]]) -> dict:
    effort = resolved_reasoning_effort()
    return prompt_record(
        messages,
        model=resolved_model(),
        reasoning_effort=effort,
        max_tokens=resolved_max_tokens(effort),
        provider=resolved_provider(),
    )


async def score_section_faithfulness(
    inp: SectionEvalInput,
) -> tuple[float | None, list[str], str | None, dict | None]:
    """Return (faithfulness_score, unsupported_claims, error, prompt_record)."""
    if not is_available():
        return None, [], unavailable_reason(), None
    if not (inp.generated_text or "").strip():
        return None, [], None, None

    observations = [o.strip() for o in (inp.observations or []) if o and o.strip()]
    messages = build_faithfulness_messages(
        section_id=inp.section_id,
        title=inp.title,
        observations=observations,
        generated_text=inp.generated_text,
        baseline_text=inp.baseline_text,
    )
    prompt = _faithfulness_prompt_payload(messages)

    try:
        parsed = await call_judge_parse(
            messages,
            response_format=FaithfulnessJudgeResponse,
            call_label="evaluation_faithfulness",
            section_id=inp.section_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "evaluation_faithfulness_failed section=%s err=%s",
            inp.section_id,
            exc,
        )
        return None, [], str(exc), prompt

    if parsed is None:
        return None, [], "empty_judge_response", prompt

    claims = [c.strip() for c in (parsed.unsupported_claims or []) if c and c.strip()]
    return _clip01(parsed.faithfulness), claims, None, prompt


async def judge_combined_section(
    *,
    section_id: str,
    surveyor_notes: str | list[str],
    generated_text: str,
) -> dict:
    """Combined faithfulness + answer_correctness judge (golden harness compatibility).

    Returns {} when the LLM is unavailable so nightly degrades cleanly.
    """
    if not is_available() or not (generated_text or "").strip():
        return {}
    parsed = await call_judge_parse(
        build_combined_judge_messages(
            section_id=section_id,
            surveyor_notes=surveyor_notes,
            generated_text=generated_text,
        ),
        response_format=CombinedJudgeResponse,
        call_label="evaluation_combined_judge",
        section_id=section_id,
    )
    if parsed is None:
        return {}
    return {
        "faithfulness": _clip01(parsed.faithfulness),
        "answer_correctness": _clip01(parsed.answer_correctness),
        "unsupported_claims": [
            c.strip() for c in (parsed.unsupported_claims or []) if c and c.strip()
        ],
        "missing_facts": [
            f.strip() for f in (parsed.missing_facts or []) if f and f.strip()
        ],
    }
