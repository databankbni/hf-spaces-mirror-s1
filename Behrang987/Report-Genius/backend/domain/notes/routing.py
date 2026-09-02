"""Multi-stage RICS L3 note routing: explicit prefix → element label → keywords → semantic fallback.

Priority 1 — explicit section tokens at line start (``G1,``, ``D9:``, ``D4 -``).
Priority 1b — surveyor element labels (``Main roof:``, ``Rainwater fittings:``).
Priority 2 — high-confidence domain keyword tiers (full canonical lexicon).
Priority 3 — general keyword patterns, then embedding/RAG when enabled.
"""

from __future__ import annotations

import re
from collections import defaultdict

from backend.domain.notes.element_labels import ELEMENT_LABEL_ROUTES
from backend.domain.notes.high_confidence_lexicon import (
    compile_high_confidence_patterns,
)
from backend.domain.rics_level3_schema import valid_leaf_section_ids
from backend.domain.section_scope import storage_section_id

UNASSIGNED = "UNASSIGNED"

# Priority 1a: real leaf codes (D1…) — space or punctuation separator.
_EXPLICIT_LEAF_PREFIX = re.compile(
    r"^\s*(?:section\s+)?([A-N]\d{1,2})\s*(?:[:,;\-–—\.]\s*|\s+)(.+)$",
    re.IGNORECASE | re.DOTALL,
)
# Priority 1b: parent-level units (A/B/C/K/L/M/N) — punctuation separator only.
# Bare "A few …" must NOT match (would steal D2 slate notes).
_EXPLICIT_PARENT_PREFIX = re.compile(
    r"^\s*(?:section\s+)?([A-N])\s*[:,;\-–—\.]\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)

_ELEMENT_LABEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        section_id,
        re.compile(rf"^\s*({label})\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL),
    )
    for section_id, label in ELEMENT_LABEL_ROUTES
]

# Priority 2: full canonical lexicon (order-sensitive; see notes_high_confidence_lexicon.py).
_HIGH_CONFIDENCE_PATTERNS = compile_high_confidence_patterns()

RAG_CLASSIFICATION_GUIDANCE = (
    "You are a strict RICS Level 3 surveyor assistant. Allocate the following note "
    "to exactly one of the canonical product sections (parent-level A/B/C/K/L/M/N or "
    "leaf codes D1–J5). If the text describes a building element (like gutters), do "
    "not assign it to the surrounding element (like main walls); assign it to its "
    "exact dedicated section (D3)."
)


def parse_explicit_section_prefix(line: str) -> tuple[str, str] | None:
    """Return ``(section_id, body)`` when the line starts with a product section token."""
    text = (line or "").strip()
    if len(text) < 2:
        return None
    match = _EXPLICIT_LEAF_PREFIX.match(text) or _EXPLICIT_PARENT_PREFIX.match(text)
    if not match:
        return None
    # Collapse legacy layout hooks (A1/C3/K1) to parent-level product ids.
    section_id = storage_section_id(match.group(1).upper())
    body = match.group(2).strip()
    allowed = valid_leaf_section_ids()
    if section_id in allowed and body:
        return section_id, body
    return None


def parse_element_label_prefix(line: str) -> tuple[str, str] | None:
    """Return ``(section_id, full_line)`` when the line opens with a known element label."""
    text = (line or "").strip()
    if len(text) < 3 or ":" not in text:
        return None
    allowed = valid_leaf_section_ids()
    for section_id, pattern in _ELEMENT_LABEL_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        body = match.group(2).strip()
        sid = storage_section_id(section_id.upper())
        if body and sid in allowed:
            return sid, text
    return None


def classify_high_confidence_keywords(text: str) -> tuple[str, float]:
    """Priority-2 keyword tier; returns ``UNASSIGNED`` when no rule fires."""
    line = (text or "").strip()
    if len(line) < 3:
        return UNASSIGNED, 0.0
    valid = valid_leaf_section_ids()
    for section_id, pattern in _HIGH_CONFIDENCE_PATTERNS:
        if pattern.search(line):
            sid = storage_section_id(section_id.upper())
            if sid in valid:
                return sid, 1.0
    return UNASSIGNED, 0.0


def route_lines_to_level3_sections(
    lines: list[str],
) -> tuple[dict[str, list[str]], list[str]]:
    """Route note lines into L3 section buckets using the full cascade."""
    from backend.domain.notes.keyword_router import classify_note_cascade

    routed: dict[str, list[str]] = defaultdict(list)
    unmatched: list[str] = []
    for raw in lines:
        text = (raw or "").strip()
        if len(text) < 3:
            continue
        section_id, _, observation = classify_note_cascade(text)
        if section_id == UNASSIGNED:
            unmatched.append(observation)
        else:
            routed[section_id].append(observation)
    return dict(routed), unmatched
