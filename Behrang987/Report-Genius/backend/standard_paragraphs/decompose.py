"""Light LLM decomposition of subsection notes into distinct findings."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from backend.config import settings
from backend.domain.atomic_observations import split_atomic_observations
from backend.llm import openai_client

logger = logging.getLogger(__name__)

_MAX_ISSUES = 10
_LONG_BLOB_CHARS = 120
_MULTI_CUE = re.compile(
    r"\b(?:also|additionally|plus|and also)\b|[.!?]\s+\S",
    re.IGNORECASE,
)

DECOMPOSE_SYSTEM = """You prepare RICS surveyor inspection notes for standard-paragraph retrieval.

Task: split the notes for ONE subsection into distinct FINDINGS.

A finding is any distinguishable observation that could match a separate firm standard
paragraph — not only defects. Include:
- defects / problems (blockage, leaning aerial, missing weather bar)
- simple / neutral observations (UPVC soil-and-vent stack; balloon grating and clean rod present;
  modern electrics; no smell of gas; valley gutters in good condition; combination boiler)
- construction / materials / fittings / locations
- condition statements and stand-alone recommended actions

Purpose: each finding becomes its own search query against the firm's standard-paragraph
library for this subsection. Missing a finding means the matching paragraph cannot be retrieved.

Rules:
- Emit short plain lines (telegram style is fine); keep materials, locations, and severity.
- Cover EVERY distinguishable fact — do not keep only problems.
- Split different elements into different findings even when they appear in one sentence
  (e.g. inspection-chamber blockage AND soil-and-vent stack UPVC with balloon grating /
  clean rod → two findings).
- "OK" / satisfactory / present / type-of-system notes still count as findings when they
  could map to a standard paragraph.
- Do not invent facts absent from the notes.
- Do not merge unrelated elements into one line.
- Do not split one fact into style-only fragments.
- Ignore section titles / headings that are not real observations.
- If only one distinguishable finding exists, return a single-item list.
- Maximum 10 findings.

Respond using the provided structured schema only."""


class NoteFindings(BaseModel):
    findings: list[str] = Field(
        default_factory=list,
        description=(
            "Distinct SP-matchable findings from the notes (defects AND simple "
            "observations), one short line each."
        ),
    )


# Backward-compatible alias for tests/imports.
NoteIssues = NoteFindings


@dataclass(frozen=True)
class DecomposeResult:
    issues: list[str]
    used_llm: bool
    method: str  # llm | heuristic | atomic | empty


def _clean_issue_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        text = " ".join(str(raw or "").split()).strip(" -•\t")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= _MAX_ISSUES:
            break
    return out


def _needs_llm_decompose(observations: list[str]) -> bool:
    """True when notes look like a multi-issue blob rather than ready atoms."""
    if len(observations) >= 2:
        return any(
            len(o) >= _LONG_BLOB_CHARS or bool(_MULTI_CUE.search(o))
            for o in observations
        )
    if not observations:
        return False
    only = observations[0]
    return len(only) >= _LONG_BLOB_CHARS or bool(_MULTI_CUE.search(only))


def _heuristic_issues(observations: list[str]) -> list[str]:
    atoms = split_atomic_observations(observations)
    expanded: list[str] = []
    for atom in atoms:
        if len(atom) >= _LONG_BLOB_CHARS and ". " in atom:
            parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", atom) if p.strip()]
            expanded.extend(parts or [atom])
        else:
            expanded.append(atom)
    return _clean_issue_lines(expanded)


def _llm_decompose(
    cleaned: list[str],
    *,
    section_id: str,
    section_title: str,
) -> list[str] | None:
    if not openai_client.is_available():
        logger.info(
            "SP note decompose: OpenAI unavailable; heuristic issues section=%s",
            section_id or "?",
        )
        return None

    payload = {
        "section": section_id or "",
        "title": section_title or "",
        "surveyor_notes": cleaned,
    }
    messages = [
        {"role": "system", "content": DECOMPOSE_SYSTEM},
        {
            "role": "user",
            "content": (
                "List every distinguishable finding that could match a standard "
                "paragraph (defects and simple observations).\n"
                + json.dumps(payload, ensure_ascii=False)
            ),
        },
    ]
    try:
        parsed = openai_client.chat_parse(
            messages,
            response_format=NoteFindings,
            model=settings.mapping_model,
            max_tokens=400,
            temperature=0.0,
            call_label="standard_paragraph_decompose",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "SP note decompose failed section=%s err=%s", section_id or "?", exc
        )
        return None

    if parsed is None:
        return None
    raw_findings = list(getattr(parsed, "findings", None) or [])
    # Older alias field if any patched schema still uses issues.
    if not raw_findings:
        raw_findings = list(getattr(parsed, "issues", None) or [])
    issues = _clean_issue_lines(raw_findings)
    return issues or None


def decompose_notes_detailed(
    observations: list[str],
    *,
    section_id: str = "",
    section_title: str = "",
    force_llm: bool = False,
    allow_when_disabled: bool = False,
) -> DecomposeResult:
    """Decompose notes and report whether the LLM ran.

    ``force_llm``: always call the LLM (standalone testing).
    ``allow_when_disabled``: run even if ``STANDARD_PARAGRAPHS_DECOMPOSE_NOTES``
    is false (standalone testing only — generation path should not set this).
    """
    cleaned = _clean_issue_lines(list(observations or []))
    if not cleaned:
        return DecomposeResult(issues=[], used_llm=False, method="empty")

    enabled = bool(settings.standard_paragraphs_decompose_notes) or allow_when_disabled
    if not enabled and not force_llm:
        issues = _heuristic_issues(cleaned)
        method = "atomic" if len(issues) == len(cleaned) else "heuristic"
        return DecomposeResult(issues=issues, used_llm=False, method=method)

    if force_llm or _needs_llm_decompose(cleaned):
        llm_issues = _llm_decompose(
            cleaned, section_id=section_id, section_title=section_title
        )
        if llm_issues is not None:
            logger.info(
                "SP note decompose section=%s observations=%d issues=%d",
                section_id or "?",
                len(cleaned),
                len(llm_issues),
            )
            return DecomposeResult(issues=llm_issues, used_llm=True, method="llm")
        issues = _heuristic_issues(cleaned)
        return DecomposeResult(issues=issues, used_llm=False, method="heuristic")

    issues = _heuristic_issues(cleaned)
    method = "atomic" if len(issues) == len(cleaned) else "heuristic"
    return DecomposeResult(issues=issues, used_llm=False, method=method)


def decompose_notes_to_issues(
    observations: list[str],
    *,
    section_id: str = "",
    section_title: str = "",
    force_llm: bool = False,
    allow_when_disabled: bool = False,
) -> list[str]:
    """Return distinct findings (wrapper around :func:`decompose_notes_detailed`)."""
    return list(
        decompose_notes_detailed(
            observations,
            section_id=section_id,
            section_title=section_title,
            force_llm=force_llm,
            allow_when_disabled=allow_when_disabled,
        ).issues
    )
