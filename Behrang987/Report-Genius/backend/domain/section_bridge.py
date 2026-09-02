"""Bridge report-template section IDs to standard-paragraph section IDs.

When the PDF report template and Word standard-paragraphs file share the same
canonical RICS L3 codes (D1, D2, …), aliases are identity mappings. Title overlap
is used only when Word paragraph buckets use legacy alternate codes.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.domain.template_discoverer import (
    DiscoveredChunk,
    discover_standard_paragraph_chunks,
    discover_standard_paragraph_titles,
)
from backend.models.schema import SectionDefinition

_STOP_WORDS = frozenset(
    {
        "about",
        "with",
        "from",
        "this",
        "that",
        "level",
        "section",
        "inside",
        "outside",
        "other",
        "property",
        "report",
        "survey",
        "your",
        "the",
        "and",
    }
)


def _title_tokens(title: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z]{4,}", (title or "").lower())
        if w not in _STOP_WORDS
    }


def _score_titles(report_title: str, paragraph_title: str) -> int:
    a, b = _title_tokens(report_title), _title_tokens(paragraph_title)
    if not a or not b:
        return 0
    return len(a & b)


def build_section_alias_map(
    report_sections: list[SectionDefinition],
    paragraph_titles: dict[str, str],
) -> dict[str, str]:
    """Map each report-template section id to a standard-paragraph section id.

    Strategy (in order):
    1. Exact id match when the Word file has the same code.
    2. Best title-token overlap (minimum 2 shared significant words).
    3. Fallback: report id maps to itself (retrieval uses title+notes only).
    """
    aliases: dict[str, str] = {}
    for sec in report_sections:
        if sec.id in paragraph_titles:
            aliases[sec.id] = sec.id
            continue
        best_id: str | None = None
        best_score = 0
        for pid, ptitle in paragraph_titles.items():
            score = _score_titles(sec.title, ptitle)
            if score > best_score:
                best_score = score
                best_id = pid
        if best_id and best_score >= 2:
            aliases[sec.id] = best_id
        else:
            aliases[sec.id] = sec.id
    return aliases


def paragraph_titles_from_word(path: Path) -> dict[str, str]:
    """Return ``{section_id: title}`` from the standard-paragraphs Word file."""
    return discover_standard_paragraph_titles(path)


def paragraph_chunks_from_word(path: Path) -> list[DiscoveredChunk]:
    return discover_standard_paragraph_chunks(path)
