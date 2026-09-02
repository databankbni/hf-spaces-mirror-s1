"""LLM-assisted per-subsection segmentation of uploaded past reports.

PDF layout frequently defeats the regex heading matcher (missed headings,
multi-column scrambles, banner splits), which mis-tags prose with the wrong
``section_id`` at ingest — the root cause of the "irrelevant paragraphs"
failure. This module gives the model the extracted text (line-numbered) plus
the canonical RICS L3 storage schema and gets back section START MARKERS
(``{id, line, role}``), then slices bodies deterministically. Marker output is
tiny, so a whole report costs one cheap JSON call per text window.

Storage rules (see :mod:`backend.domain.section_scope`):
* D–I and J → real leaf ids (``D1``…``J5``).
* A/B/C/K/L/M/N → one PARENT-level body each; C's official prose headings
  ("Type of property", "Approximate year of construction", …) map to ``C``.
* Prose between a parent banner (e.g. "D Outside the property") and its first
  leaf → a ``parent_intro`` unit for that parent.

Fails soft: any error or empty result returns ``None`` and the caller falls
back to the regex chunker.
"""

from __future__ import annotations

import logging
import re

from backend.config import settings
from backend.domain.rics_level3_schema import CANONICAL_SCHEMA
from backend.domain.section_scope import (
    LEAF_STORAGE_PARENT_IDS,
    PARENT_INTRO_SECTION_IDS,
    PARENT_STORAGE_PARENT_IDS,
    parent_letter,
    storage_section_id,
)
from backend.llm import openai_client
from backend.rag.reference_chunker import (
    _chunk_section_body,
    _clean_reference_body,
    strip_pdf_extract_furniture,
    truncate_at_foreign_parent_banner,
)
from backend.rag.store import DOC_TYPE_REFERENCE_REPORT
from backend.rag.types import (
    CONTENT_ROLE_BODY,
    CONTENT_ROLE_PARENT_INTRO,
    TIER_REFERENCE,
    Chunk,
)

logger = logging.getLogger(__name__)

ROLE_BODY = "body"
ROLE_PARENT_INTRO = "parent_intro"


def _storage_units() -> list[tuple[str, str]]:
    """Ordered ``(storage_id, label)`` rows: leaf ids for D–I/J, parents otherwise."""
    rows: list[tuple[str, str]] = []
    for parent in CANONICAL_SCHEMA["sections"]:
        pid = str(parent["id"]).upper()
        plabel = str(parent["label"])
        if pid in PARENT_STORAGE_PARENT_IDS:
            rows.append((pid, plabel))
            continue
        if pid in PARENT_INTRO_SECTION_IDS:
            rows.append((pid, f"{plabel} (parent introduction)"))
        for sub in parent.get("subsections") or []:
            rows.append((str(sub["id"]).upper(), f"{plabel}: {sub['label']}"))
    return rows


def _valid_marker_ids() -> frozenset[str]:
    return frozenset(sid for sid, _ in _storage_units())


_SEGMENTATION_SYSTEM = """\
You segment the extracted text of a UK RICS Home Survey Level 3 report into
its canonical sections. You receive numbered lines and must return the LINE
NUMBER where each section's content starts.

SECTION ID RULES (strict):
- Parents D, E, F, G, H, I and J have real numbered leaf subsections (D1..D9,
  E1..E9, F1..F7, G1..G3, H1..H3, I1..I4, J1..J5). Mark each leaf you find.
- Parents A, B, C, K, L, M and N have NO leaf codes in real reports. Mark ONE
  "A", "B", "C", "K", "L", "M" or "N" marker at the start of each parent's
  body. Never invent ids like A1, B1, C1 or K1.
- Section C uses official-form prose headings instead of codes ("Type of
  property", "Approximate year of construction", "Accommodation", "Energy",
  "Location", "Facilities", ...). All of them belong to the single "C" body —
  mark only where C starts.
- Section B contains the overall opinion and the summary-of-condition-ratings
  tables. Mark where B starts; the tables belong to B.
- Prose that appears AFTER a parent group banner (e.g. a line "D" followed by
  "Outside the property", or "F Services") but BEFORE that parent's first leaf
  subsection is a parent introduction. Emit a marker with role
  "parent_intro" and the PARENT letter as id (only for parents D, E, F, G, H,
  I, J).
- Ignore table-of-contents listings, ratings summary stub rows ("Element no.
  Element name"), page headers/footers and photo captions: never place a
  marker on them. Mark the REAL body occurrence of each section (the one with
  prose), not its ToC or summary-table mention.
- A section that does not appear in the text is simply omitted.

OUTPUT CONTRACT: return exactly one JSON object:
{"markers": [{"id": "D1", "line": 123, "role": "body"}, ...]}
- "id": one of the allowed ids listed in the user message.
- "line": the line number (from the numbered input) of the section heading, or
  of the first body line when the heading is corrupted.
- "role": "body" or "parent_intro".
No markdown fences, no commentary.
"""

_SEGMENTATION_USER_TEMPLATE = """\
ALLOWED SECTION IDS (id — meaning):
{allowed_ids}

NUMBERED REPORT TEXT (lines {first_line}-{last_line} of {total_lines}):
{numbered_text}

Return the markers JSON only. Line numbers must be within the shown range.
"""


def _allowed_ids_block() -> str:
    return "\n".join(f"{sid} — {label}" for sid, label in _storage_units())


def _window_bounds(total_lines: int) -> list[tuple[int, int]]:
    size = max(50, int(settings.ingest_segmentation_window_lines))
    overlap = max(0, min(int(settings.ingest_segmentation_window_overlap), size // 2))
    if total_lines <= size:
        return [(0, total_lines)]
    step = size - overlap
    bounds: list[tuple[int, int]] = []
    start = 0
    while start < total_lines:
        end = min(start + size, total_lines)
        bounds.append((start, end))
        if end >= total_lines:
            break
        start += step
    return bounds


def _parse_markers(
    raw: object, *, lo: int, hi: int, valid_ids: frozenset[str]
) -> list[tuple[str, int, str]]:
    """Validate one window's marker payload -> ``(id, line, role)`` rows."""
    if not isinstance(raw, dict):
        return []
    out: list[tuple[str, int, str]] = []
    for item in raw.get("markers") or []:
        if not isinstance(item, dict):
            continue
        sid = storage_section_id(str(item.get("id") or ""))
        role = str(item.get("role") or ROLE_BODY).strip().lower()
        try:
            line = int(item.get("line"))
        except (TypeError, ValueError):
            continue
        if role not in (ROLE_BODY, ROLE_PARENT_INTRO):
            continue
        if role == ROLE_PARENT_INTRO:
            sid = parent_letter(sid)
            if sid not in PARENT_INTRO_SECTION_IDS:
                continue
        elif sid not in valid_ids:
            continue
        if not (lo <= line < hi):
            continue
        out.append((sid, line, role))
    return out


def _alpha_len(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


_HEADING_LINE_RE = re.compile(r"^\s*[A-N]\d{0,2}\b[\s:.\-\u2013\u2014]*[^\n]{0,120}$")


def _slice_segments(
    lines: list[str],
    markers: list[tuple[str, int, str]],
    *,
    include_section_headings: bool | None = None,
) -> dict[tuple[str, str], str]:
    """Slice bodies between sorted markers; keep the richest body per unit."""
    from backend.rag.reference_chunker import _include_headings, _format_leaf_heading

    keep_heading = _include_headings(include_section_headings)
    ordered = sorted(markers, key=lambda m: m[1])
    best: dict[tuple[str, str], str] = {}
    for i, (sid, line, role) in enumerate(ordered):
        end = ordered[i + 1][1] if i + 1 < len(ordered) else len(lines)
        seg_lines = list(lines[line:end])
        heading = ""
        if (
            role == ROLE_BODY
            and seg_lines
            and _HEADING_LINE_RE.match(seg_lines[0] or "")
        ):
            first = (seg_lines[0] or "").strip()
            if len(first) <= 120:
                if keep_heading and len(sid) >= 2:
                    heading = _format_leaf_heading(first, sid)
                seg_lines = seg_lines[1:]
        body = _clean_reference_body("\n".join(seg_lines))
        if role == ROLE_BODY and len(sid) >= 2:
            body = truncate_at_foreign_parent_banner(body, sid)
        if keep_heading and heading:
            body = f"{heading}\n\n{body}".strip() if body else heading
        if not body:
            continue
        key = (sid, role)
        if _alpha_len(body) > _alpha_len(best.get(key, "")):
            best[key] = body
    return best


def _segments_to_chunks(
    segments: dict[tuple[str, str], str],
    *,
    source_filename: str,
    one_chunk_per_section: bool | None = None,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for (sid, role), body in segments.items():
        parent = parent_letter(sid)
        pieces = _chunk_section_body(body, one_chunk_per_section=one_chunk_per_section)
        for idx, piece in enumerate(pieces, start=1):
            if role == ROLE_PARENT_INTRO:
                chunks.append(
                    Chunk(
                        text=piece,
                        section_id=parent,
                        tier=TIER_REFERENCE,
                        is_scrubbed=False,
                        source_filename=source_filename,
                        chunk_id=f"{source_filename}:parent_{parent}:p{idx}",
                        paragraph_index=idx,
                        document_type=DOC_TYPE_REFERENCE_REPORT,
                        content_role=CONTENT_ROLE_PARENT_INTRO,
                        parent_id=parent,
                    )
                )
            else:
                chunks.append(
                    Chunk(
                        text=piece,
                        section_id=sid,
                        tier=TIER_REFERENCE,
                        is_scrubbed=False,
                        source_filename=source_filename,
                        chunk_id=f"{source_filename}:{sid}:p{idx}",
                        paragraph_index=idx,
                        document_type=DOC_TYPE_REFERENCE_REPORT,
                        content_role=CONTENT_ROLE_BODY,
                        parent_id=parent,
                    )
                )
    return chunks


def is_available() -> bool:
    return bool(settings.ingest_llm_segmentation_enabled) and (
        openai_client.is_available()
    )


def _segment_window(
    *,
    numbered: str,
    allowed_block: str,
    lo: int,
    hi: int,
    total_lines: int,
    valid_ids: frozenset[str],
) -> list[tuple[str, int, str]]:
    """One segmentation window; retry once if gpt-5-nano returns empty content."""
    model = settings.ingest_segmentation_model or settings.discovery_model
    messages = [
        {"role": "system", "content": _SEGMENTATION_SYSTEM},
        {
            "role": "user",
            "content": _SEGMENTATION_USER_TEMPLATE.format(
                allowed_ids=allowed_block,
                first_line=lo,
                last_line=hi - 1,
                total_lines=total_lines,
                numbered_text=numbered,
            ),
        },
    ]
    attempts: list[dict] = [
        {"reasoning_effort": "none", "max_tokens": None},
        # Second try: still no length cap; "minimal" if "none" was ignored by the API.
        {"reasoning_effort": "minimal", "max_tokens": None},
    ]
    for i, opts in enumerate(attempts):
        raw = openai_client.chat_json(
            messages,
            model=model,
            max_tokens=opts["max_tokens"],
            temperature=0.0,
            timeout=float(settings.ingest_segmentation_timeout_seconds),
            reasoning_effort=opts["reasoning_effort"],
            call_label="ingest_segmentation",
        )
        markers = _parse_markers(raw, lo=lo, hi=hi, valid_ids=valid_ids)
        if markers or i == len(attempts) - 1:
            if not markers and i > 0:
                logger.warning(
                    "LLM segmentation window [%d,%d) returned no markers after retry.",
                    lo,
                    hi,
                )
            return markers
        logger.info(
            "LLM segmentation window [%d,%d) empty; retrying once.",
            lo,
            hi,
        )
    return []


def llm_segment_reference_text(
    text: str,
    *,
    source_filename: str,
    one_chunk_per_section: bool | None = None,
) -> list[Chunk] | None:
    """Segment a past report into canonical storage units via the LLM.

    Returns ``None`` when segmentation is unavailable or fails, so the caller
    falls back to the regex chunker.
    """
    if not is_available():
        return None

    cleaned = strip_pdf_extract_furniture(text or "")
    lines = cleaned.splitlines()
    if not any(line.strip() for line in lines):
        return None

    valid_ids = _valid_marker_ids()
    allowed_block = _allowed_ids_block()
    markers: list[tuple[str, int, str]] = []

    try:
        for lo, hi in _window_bounds(len(lines)):
            numbered = "\n".join(
                f"{i}| {lines[i]}" for i in range(lo, hi) if lines[i].strip()
            )
            if not numbered:
                continue
            markers.extend(
                _segment_window(
                    numbered=numbered,
                    allowed_block=allowed_block,
                    lo=lo,
                    hi=hi,
                    total_lines=len(lines),
                    valid_ids=valid_ids,
                )
            )
    except Exception as exc:  # noqa: BLE001 — fail soft to the regex path
        logger.warning(
            "LLM segmentation failed for %s (%s); falling back to regex chunker.",
            source_filename,
            exc,
        )
        return None

    if not markers:
        logger.info(
            "LLM segmentation returned no markers for %s; using regex chunker.",
            source_filename,
        )
        return None

    # Overlapping windows can emit the same marker twice — dedupe exact repeats.
    markers = sorted(set(markers), key=lambda m: m[1])
    segments = _slice_segments(lines, markers)
    if not segments:
        return None
    leaf_units = sum(
        1
        for (sid, role) in segments
        if role == ROLE_BODY and parent_letter(sid) in LEAF_STORAGE_PARENT_IDS
    )
    logger.info(
        "LLM segmentation for %s: %d unit(s) captured (%d leaf, %d parent-level).",
        source_filename,
        len(segments),
        leaf_units,
        len(segments) - leaf_units,
    )
    return _segments_to_chunks(
        segments,
        source_filename=source_filename,
        one_chunk_per_section=one_chunk_per_section,
    )
