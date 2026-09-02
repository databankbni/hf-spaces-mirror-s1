"""LLM transport for the note-quality judge.

Deliberately thin, and deliberately this package's own rather than shared with
:mod:`backend.evaluation`: the two judges answer to different config, run on
different latency budgets (a surveyor is waiting for this one) and should be
tunable apart.
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.llm import openai_client
from backend.note_quality.models import NoteQualityJudgeResponse

logger = logging.getLogger(__name__)


def resolved_model() -> str:
    return (settings.note_quality_model or "").strip() or settings.grounding_model


def is_available() -> bool:
    """True when grading is switched on and the provider has credentials."""
    return bool(settings.note_quality_enabled) and openai_client.is_available()


def unavailable_reason() -> str:
    if not settings.note_quality_enabled:
        return "note_quality_disabled"
    if not openai_client.is_available():
        return "openai_unavailable"
    return ""


async def call_judge(
    messages: list[dict[str, str]],
) -> NoteQualityJudgeResponse | None:
    """Grade one report group, or ``None`` when the call fails or is refused.

    Never raises: a judge that falls over must leave the chips grey, not stop the
    surveyor writing their report.
    """
    try:
        parsed = await openai_client.chat_parse_async(
            messages,
            response_format=NoteQualityJudgeResponse,
            model=resolved_model(),
            temperature=0.0,
            max_tokens=settings.note_quality_max_tokens,
            timeout=settings.note_quality_timeout_seconds,
            reasoning_effort=(settings.note_quality_reasoning_effort or "").strip()
            or None,
            call_label="note_quality",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("note_quality judge call failed: %s", exc)
        return None

    if parsed is None:
        logger.warning(
            "note_quality judge returned no structured object (model=%s).",
            resolved_model(),
        )
    return parsed
