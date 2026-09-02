"""Grounding + PII audit for mapped sections (instructions v2).

Stage 1: deterministic regex PII scrub via ``pii_scrubber``.
Stage 2: read-only LLM auditor via OpenAI returning ``passed``, ``_audit_summary``, and ``violations``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.config import settings
from backend.llm import openai_client
from backend.pii import scrubber as pii_scrubber
from backend.prompts.grounding_prompt import build_grounding_messages

logger = logging.getLogger(__name__)


def _normalize_violation(item: object) -> str:
    """Flatten structured or legacy violation entries to a loggable string."""
    if isinstance(item, dict):
        offending = str(item.get("offending_text") or "").strip()
        reason = str(item.get("reason") or "").strip()
        vtype = str(item.get("violation_type") or "").strip()
        parts = [p for p in (vtype, offending, reason) if p]
        return " — ".join(parts) if parts else str(item)
    text = str(item).strip()
    return text


@dataclass
class GroundingResult:
    cleaned_text: str
    pii_violations: dict[str, int] = field(default_factory=dict)
    ungrounded: list[str] = field(default_factory=list)
    passed: bool = True

    @property
    def had_pii(self) -> bool:
        return bool(self.pii_violations)

    @property
    def grounding_passed(self) -> bool:
        return self.passed and not self.ungrounded and not self.had_pii


def _as_observations(notes: str | list[str]) -> list[str]:
    if isinstance(notes, list):
        return [o.strip() for o in notes if o and o.strip()]
    lines = [
        line.strip().lstrip("•-*·▸▹◆►").strip()
        for line in notes.split("\n")
        if line.strip()
    ]
    return lines or [notes.strip()]


def check_section(
    section_text: str,
    notes_text: str | list[str],
    template_paragraphs: list[str] | None = None,
) -> GroundingResult:
    """Run regex PII pass, then (if available) the LLM audit; merge results."""
    text = section_text or ""
    observations = _as_observations(notes_text)

    scrub = pii_scrubber.scrub(text)
    cleaned = scrub.text
    pii = dict(scrub.audit)
    violations: list[str] = []
    passed = True

    baseline = ""
    if template_paragraphs:
        baseline = (template_paragraphs[0] or "").strip()

    if settings.grounding_enabled and openai_client.is_available():
        try:
            data = openai_client.chat_json(
                build_grounding_messages(
                    cleaned,
                    observations,
                    template_paragraphs,
                    baseline_paragraph=baseline,
                ),
                model=settings.grounding_model,
                max_tokens=settings.max_tokens_grounding,
                temperature=float(settings.grounding_temperature),
                reasoning_effort=settings.grounding_reasoning_effort,
            )

            violations = [
                norm
                for v in data.get("violations", [])
                if (norm := _normalize_violation(v))
            ]
            # Backward compatibility with older prompt JSON shape.
            violations.extend(
                str(u) for u in data.get("ungrounded", []) if str(u).strip()
            )
            for item in data.get("pii", []):
                if str(item).strip():
                    violations.append(str(item))
                    pii["LLM_FLAGGED"] = pii.get("LLM_FLAGGED", 0) + 1

            passed = bool(data.get("passed", len(violations) == 0))
            if violations:
                passed = False
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM grounding audit failed (%s); regex result kept.", exc)

    if pii:
        passed = False

    return GroundingResult(
        cleaned_text=cleaned,
        pii_violations=pii,
        ungrounded=violations,
        passed=passed,
    )
