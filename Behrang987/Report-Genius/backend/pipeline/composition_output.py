"""Validate and sanitize LLM narrative section output."""

from __future__ import annotations

import re
from typing import Literal

InterferenceLevel = Literal["medium", "maximum"]

_UNMATCHED_TAG_RE = re.compile(
    r"\[UNMATCHED_OBSERVATION:\s*[^\]]*\]",
    re.IGNORECASE,
)
_UNMATCHED_LINE_RE = re.compile(
    r"^\s*UNMATCHED_OBSERVATION:\s*.+$",
    re.IGNORECASE | re.MULTILINE,
)
_UNMATCHED_HEADING_BLOCK_RE = re.compile(
    r"\n*#{1,6}\s*UNMATCHED_OBSERVATION\b.*",
    re.IGNORECASE | re.DOTALL,
)
_GROUNDING_TAG_RE = re.compile(
    r"\[Grounding\s+review\s+required[^\]]*\]",
    re.IGNORECASE,
)
_SOURCE_TAG_RE = re.compile(
    r"\[Source:\s[^\]]+\]",
    re.IGNORECASE,
)


def _observation_signal(text: str, observations: list[str]) -> bool:
    """True when at least one note contributes a recognizable token to the output."""
    lower = text.lower()
    for obs in observations:
        obs = (obs or "").strip()
        if not obs:
            continue
        tokens = [t for t in re.findall(r"[a-z]{4,}", obs.lower()) if len(t) >= 4]
        if any(t in lower for t in tokens[:6]):
            return True
        if len(obs) >= 12 and obs.lower()[:12] in lower:
            return True
    return False


def sanitize_section_prose(text: str) -> str:
    """Remove internal audit tags that must never appear in user-facing prose."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    cleaned = _UNMATCHED_TAG_RE.sub("", cleaned)
    cleaned = _UNMATCHED_LINE_RE.sub("", cleaned)
    cleaned = _GROUNDING_TAG_RE.sub("", cleaned)
    cleaned = _SOURCE_TAG_RE.sub("", cleaned)
    cleaned = _UNMATCHED_HEADING_BLOCK_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def accept_narrative_section_output(
    text: str,
    observations: list[str],
) -> bool:
    """Accept polished narrative prose that integrates notes without internal tags."""
    cleaned = sanitize_section_prose(text)
    if not cleaned:
        return False
    if "•" in cleaned or "·" in cleaned:
        return False
    if re.search(r"UNMATCHED_OBSERVATION", cleaned, re.IGNORECASE):
        return False
    if re.search(r"\[Source:", cleaned, re.IGNORECASE):
        return False
    if re.search(r"\[Grounding\s+review", cleaned, re.IGNORECASE):
        return False
    if observations and not _observation_signal(cleaned, observations):
        return False
    return True


def accept_inplace_baseline_output(
    text: str,
    baseline: str,
    observations: list[str],
) -> bool:
    """Backward-compatible alias — narrative validation (baseline retained for callers)."""
    _ = baseline
    return accept_narrative_section_output(text, observations)


def accept_llm_compose_output(
    text: str,
    reference: str,
    observations: list[str],
    *,
    level: InterferenceLevel,
) -> bool:
    """Backward-compatible alias — all levels use narrative rules."""
    _ = reference, level
    return accept_narrative_section_output(text, observations)
