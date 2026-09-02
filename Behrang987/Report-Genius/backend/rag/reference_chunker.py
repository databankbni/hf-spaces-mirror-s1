"""Split uploaded past-report text into section-tagged paragraphs for REFERENCE RAG."""

from __future__ import annotations

import re

from backend.config import settings
from backend.domain.section_scope import (
    C_PROSE_HEADINGS,
    PARENT_STORAGE_PARENT_IDS,
    fold_parent_title,
    parent_letter_for_title,
    storage_section_id,
)
from backend.rag.store import DOC_TYPE_REFERENCE_REPORT
from backend.rag.types import CONTENT_ROLE_PARENT_INTRO, TIER_REFERENCE, Chunk

_RICS_HEADING_LINE = re.compile(
    r"""
    (?m)^\s*
    (?:\*\*)?                              # optional markdown bold open
    (?:(?:section|part|element|item)\s+)?   # optional descriptive label before the code
    (?P<code>[A-N]\d{1,2})
    \b
    (?:[\s:.\-\u2013\u2014]+[^\n*]{0,120})?  # optional separator + title on the same line
    (?:\*\*)?                              # optional markdown bold close
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Page-header/footer furniture that bleeds into PDF text extraction. Stripped from
# section bodies so it never becomes the stored baseline (e.g. a section whose only
# captured body was "Page 24RICS Home Survey - Level 3"). Bare standalone numbers are
# deliberately NOT stripped here — a lone digit may be a rating value, not a page number.
_PAGE_HEADER_FURNITURE_RE = re.compile(
    r"(?im)^[ \t]*(?:page[ \t]*\d+[ \t]*)?"
    r"rics[ \t]+home[ \t]+survey[ \t]*[-\u2013\u2014][ \t]*level[ \t]+\d.*$"
)
_PAGE_LABEL_RE = re.compile(r"(?im)^[ \t]*page[ \t]*\d+[ \t]*$")

# ToC / page-divider furniture emitted by pypdf before a new parent/leaf body:
# a ``ToC:E Inside the property`` anchor line (often glued to the tail of the
# previous section's page), then ``section-page`` divider markers, then
# ``report-page`` before the real body. Matched as FULL lines only so a ``ToC:``
# fragment inside prose is never deleted mid-paragraph.
_TOC_LINE_RE = re.compile(r"(?im)^[ \t]*ToC:[A-N]\b.*$")
_SECTION_PAGE_RE = re.compile(r"(?im)^[ \t]*section-page[ \t]*$")
_REPORT_PAGE_RE = re.compile(r"(?im)^[ \t]*report-page[ \t]*$")
# Orphan rating-badge digits: PDF layout drops the rating badge (1/2/3) onto its
# own line mid-sentence across page breaks. The inline rating sentence in the
# body prose is the reliable rating source, so a LONE 1-3 line is always noise.
_ORPHAN_RATING_BADGE_RE = re.compile(r"(?m)^[ \t]*[123][ \t]*$")

# Survey-report PDFs embed photo index lines and RICS procedural NOTE blocks inside
# section bodies. These are not mappable baseline prose — they bloat the baseline,
# confuse the weave gate, and cause grounding rollbacks. Stripped at ingest only.
_PHOTO_LINE_RE = re.compile(r"(?im)^[ \t]*Photo\s*[-\u2013]?\s*\d+.*$")
_PHOTO_INLINE_RE = re.compile(
    r"(?i)\s*Photo\s*[-\u2013]?\s*\d+\s*(?:[^\n.!?]|(?:\n(?![ \t]*Photo\s*[-\u2013]?\s*\d+)))*?[.!?]?"
)
_ELEMENT_TABLE_STUB_RE = re.compile(r"(?im)^[ \t]*Element\s+no\.?\s*Element\s+name\s*$")
# LlamaParse / PDF chrome that is not survey prose. Covers all observed forms:
# ``RICS logo``, ``Section E icon``, ``Letter H icon``, ``B section icon``,
# ``F icon``, ``K icon``, ``Letter M logo``, ``NI icon``, ``Level 3 icon``, etc.
_UI_CHROME_LINE_RE = re.compile(
    r"""
    (?im)^[ \t]*(?:
        RICS[ \t]+logo
        |Letter[ \t]+[A-N][ \t]+(?:icon|logo)
        |Section[ \t]+[A-N][ \t]+(?:icon|logo)
        |[A-N][ \t]+section[ \t]+(?:icon|logo)
        |[A-N][ \t]+(?:icon|logo)(?:\b.*)?
        |Level[ \t]+\d+[ \t]+icon
        |Not[ \t]+Inspected[ \t]+icon
        |NI[ \t]+icon
        |Condition[ \t]+Rating[ \t]+[123][ \t]+icon
        |R[ \t]+icon
        |[123][ \t]+icon
        |icon\b.*
    )[ \t]*$
    """,
    re.VERBOSE,
)
# Same chrome, but capture the parent letter for foreign-banner truncation.
_UI_CHROME_LETTER_RE = re.compile(
    r"""
    (?im)^[ \t]*(?:
        Letter[ \t]+(?P<letter1>[A-N])[ \t]+(?:icon|logo)
        |Section[ \t]+(?P<letter2>[A-N])[ \t]+(?:icon|logo)
        |(?P<letter3>[A-N])[ \t]+section[ \t]+(?:icon|logo)
        |(?P<letter4>[A-N])[ \t]+(?:icon|logo)(?:\b.*)?
    )[ \t]*$
    """,
    re.VERBOSE,
)
# Inline OCR crumb in uploaded PDFs: "… Condition Rating 3 icon". rics-literal-ok
_INLINE_CONDITION_RATING_ICON_RE = re.compile(
    r"(?i)\s*Condition[ \t]+Rating[ \t]+[123][ \t]+icon\b"
)
_INLINE_NOT_INSPECTED_ICON_RE = re.compile(r"(?i)\s*Not[ \t]+Inspected[ \t]+icon\b")
_INLINE_NI_ICON_RE = re.compile(r"(?i)\s*\bNI[ \t]+icon\b")
_INLINE_LETTER_ICON_RE = re.compile(
    r"(?i)\s*\b(?:Letter|Section)[ \t]+[A-N][ \t]+(?:icon|logo)\b"
)
# NOTE N: procedural blocks (Building Regs boilerplate etc.) precede real findings.
# Stop at the next line that reads like survey prose, not a caption or header.
_NOTE_BLOCK_RE = re.compile(
    r"(?ims)"
    r"^NOTE\s+\d+\s*:.*?"
    r"(?="
    r"\n(?:"
    r"The|There|We|It|A|An|In|Condition|Main|Our|Your|This|These|Some|No|Where|When|"
    r"Whilst|While|During|Following|Upon|After|Before|Internal|External|Ground|Roof|"
    r"Wall|Floor|Ceiling|Chimney|Window|Door|Gutter|Rainwater|Damp|Mould|Wood|Timber|"
    r"Brick|Stone|Slate|Tile|Pipe|Drain|Electric|Gas|Water|Heating|Boiler|Insulation|"
    r"Ventilation|Asbestos|Structural|Surface|Visible|Noted|Observed|Evidence|Appears|"
    r"Found|Seen|Installed|Located|Constructed|Finished|Painted|Plastered|Rendered|"
    r"Pointed|Bedded|Covering|Structure|Material|Building|Property|Survey|Client|"
    r"Surveyor|Defective|Further|Regular|Although|However|Generally|Typically|"
    r"Inspection|Inspected|Examined|Checked|Tested|Operated|Opened|Accessed"
    r")\b|\Z)"
)
# Collapse runs of blank lines left after stripping.
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
# Parent-group banners in PDF layout (e.g. ``F\\nServices``) are not leaf headings.
# When they appear inside a leaf section body, the next parent group has started
# and everything after the banner belongs to a different section group.
_PARENT_BANNER_RE = re.compile(
    r"(?m)^\s*(?P<letter>[A-N])\s*\n\s*(?P<title>[^\n]{3,120})\s*$"
)
# Title-only parent banners (letter missing) — LlamaParse often emits
# ``# Energy matters`` / ``# Inside the property`` without the letter line.
_PARENT_TITLE_ONLY_RE = re.compile(r"(?m)^\s*(?P<title>[A-Za-z][^\n]{2,120})\s*$")

# Official-form prose headings under parent C ("Type of property", "Energy", …).
# Real reports carry no C1–C5 codes, so when the C banner itself is corrupted by
# PDF extraction the first of these headings marks where C's body starts.
_C_PROSE_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(?:"
    + "|".join(re.escape(h) for h in C_PROSE_HEADINGS)
    + r")[ \t]*:?[ \t]*$"
)


def _section_parent_letter(section_id: str) -> str:
    return (section_id or "").strip()[:1].upper()


_C_PROSE_FOLDED = frozenset(fold_parent_title(h) for h in C_PROSE_HEADINGS)


def _title_is_c_prose_heading(title: str) -> bool:
    return fold_parent_title(title) in _C_PROSE_FOLDED


def truncate_at_foreign_parent_banner(body: str, section_id: str) -> str:
    """Drop prose after a sibling parent-group banner (e.g. E9 body containing ``F\\nServices``).

    Also stops at title-only parent lines (``Inside the property``) whose letter
    differs from the current leaf's parent — common in LlamaParse markdown.
    Ignores C-form prose headings (``Grounds``, ``Energy``, …) which are not
    parent banners. Cuts at foreign ``Section E icon`` / ``Letter H icon`` chrome
    and at leaf headings belonging to a different parent (``D1`` inside a G intro).

    ``section_id`` may be a leaf (``D1``) or a parent letter (``G``) for parent_intro.
    """
    parent = _section_parent_letter(section_id)
    if not parent:
        return body
    cut_at: int | None = None
    for match in _PARENT_BANNER_RE.finditer(body or ""):
        letter = match.group("letter").upper()
        if letter != parent:
            cut_at = match.start() if cut_at is None else min(cut_at, match.start())
    for match in _PARENT_TITLE_ONLY_RE.finditer(body or ""):
        title = match.group("title")
        if _title_is_c_prose_heading(title):
            continue
        letter = parent_letter_for_title(title)
        if letter and letter != parent:
            cut_at = match.start() if cut_at is None else min(cut_at, match.start())
    for match in _UI_CHROME_LETTER_RE.finditer(body or ""):
        letter = (
            match.group("letter1")
            or match.group("letter2")
            or match.group("letter3")
            or match.group("letter4")
            or ""
        ).upper()
        if letter and letter != parent:
            cut_at = match.start() if cut_at is None else min(cut_at, match.start())
    for match in _RICS_HEADING_LINE.finditer(body or ""):
        code = _normalise_code(match.group("code"))
        if _section_parent_letter(code) != parent:
            cut_at = match.start() if cut_at is None else min(cut_at, match.start())
    if cut_at is not None:
        return body[:cut_at].strip()
    return body


def _format_leaf_heading(raw_line: str, code: str) -> str:
    """Normalise a matched heading line to ``D1 Chimney stacks`` (no markdown bold)."""
    line = (raw_line or "").strip()
    line = re.sub(r"^\*\*|\*\*$", "", line).strip()
    line = re.sub(r"^(?:section|part|element|item)\s+", "", line, flags=re.IGNORECASE)
    # Ensure code is uppercase and present.
    m = re.match(
        rf"^(?P<code>{re.escape(code)})\b(?P<rest>.*)$",
        line,
        re.IGNORECASE,
    )
    if not m:
        return code
    rest = (m.group("rest") or "").strip(" :.–—-")
    return f"{code} {rest}".rstrip() if rest else code


def _include_headings(explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return bool(getattr(settings, "reference_include_section_headings", True))


def _one_chunk_mode(explicit: bool | None) -> bool:
    """REFERENCE sections are always stored as one whole chunk (no char/para split).

    The ``explicit`` arg is ignored — product rule is section-wise only. Kept so
    call sites need not change.
    """
    return True


def _emit_body_parts(
    body: str, *, one_chunk_per_section: bool = True
) -> list[tuple[int, str]]:
    """Return ``(paragraph_index, text)`` — always one part (no size limit)."""
    cleaned = (body or "").strip()
    if not cleaned:
        return []
    return [(1, cleaned)]


def _strip_page_furniture(text: str) -> str:
    """Remove repeated page header/footer lines bled in by PDF extraction."""
    cleaned = _PAGE_HEADER_FURNITURE_RE.sub("", text)
    cleaned = _PAGE_LABEL_RE.sub("", cleaned)
    return cleaned


_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_BOLD_LEAF_RE = re.compile(
    r"^\*\*\s*([A-N]\d{1,2})\b(?:\s*[:.\-\u2013\u2014]\s*|\s+)([^*]+?)\s*\*\*\s*$",
    re.IGNORECASE,
)
_MD_HEADING_LEAF_RE = re.compile(
    r"^([A-N]\d{1,2})\b(?:\s*[:.\-\u2013\u2014]\s*|\s+)(.*)$", re.IGNORECASE
)


def normalize_reference_markdown(text: str) -> str:
    """Fold LlamaParse markdown into the plain heading/banner shapes the RICS
    segmenters expect.

    Without this, raw LlamaParse output (``## D1 Chimney stacks``,
    ``# Outside the property``, ``**J1 Insulation**``) never matches the heading
    regex or the ``Letter\\nTitle`` parent banner, so ingest captures almost
    nothing (4–10 chunks instead of ~50). This is the same transform the
    ``scripts/chunk_rics_text.py`` CLI applied; production ingest must run it too
    or the two paths disagree.

    - ``## D1 Chimney`` / ``**J1 Insulation**`` -> ``D1 Chimney`` (leaf heading)
    - ``# J`` -> ``J`` (lone parent letter)
    - title-only parent lines (``Overall opinion`` / ``Outside the property``)
      get their parent letter injected as a preceding line so intros/bodies do
      not bleed into the previous section.
    """
    raw_lines = (text or "").splitlines()
    lines: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        bold_leaf = _MD_BOLD_LEAF_RE.match(stripped)
        if bold_leaf:
            code = bold_leaf.group(1).upper()
            title = bold_leaf.group(2).strip()
            lines.append(f"{code} {title}".rstrip() if title else code)
            continue
        m = _ATX_HEADING_RE.match(line)
        if m:
            body = m.group(2).strip()
            leaf = _MD_HEADING_LEAF_RE.match(body)
            if leaf:
                code = leaf.group(1).upper()
                title = (leaf.group(2) or "").strip()
                lines.append(f"{code} {title}".rstrip() if title else code)
                continue
            if re.fullmatch(r"[A-N]", body, re.IGNORECASE):
                lines.append(body.upper())
                continue
            parent = re.match(r"^([A-N])\s+(.+)$", body, re.IGNORECASE)
            if parent:
                rest = parent.group(2).strip()
                rest_l = rest.lower()
                if rest_l.startswith("icon") or rest_l.startswith("logo"):
                    continue
                lines.append(parent.group(1).upper())
                lines.append(rest)
                continue
            lines.append(body)
            continue
        lines.append(line)

    # Second pass: standalone parent-title lines -> ``Letter\nTitle`` so a
    # title-only banner (LlamaParse) behaves like a real parent banner.
    out: list[str] = []
    for line in lines:
        letter = parent_letter_for_title(line.strip())
        if letter:
            prev = out[-1].strip().upper() if out else ""
            if prev != letter:
                out.append(letter)
            out.append(line.strip())
            continue
        out.append(line)
    return "\n".join(out)


def strip_pdf_extract_furniture(text: str) -> str:
    """Strip pypdf ToC/page-divider artifacts BEFORE segmentation.

    Runs once on the whole extracted text so neither the LLM segmenter nor the
    regex chunker ever sees ``ToC:E …`` anchors, ``section-page``/``report-page``
    dividers, orphan rating-badge digits, or page header/footer lines.
    """
    cleaned = text or ""
    cleaned = _TOC_LINE_RE.sub("", cleaned)
    cleaned = _SECTION_PAGE_RE.sub("", cleaned)
    cleaned = _REPORT_PAGE_RE.sub("", cleaned)
    cleaned = _ORPHAN_RATING_BADGE_RE.sub("", cleaned)
    cleaned = _strip_page_furniture(cleaned)
    cleaned = _MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned


def _clean_reference_body(text: str) -> str:
    """Remove non-prose survey-report artifacts from a REFERENCE section body."""
    cleaned = text or ""
    if settings.text_normalize_enabled:
        from backend.domain.text_normalize import normalize_text

        cleaned = normalize_text(cleaned)
    cleaned = _strip_page_furniture(cleaned)
    cleaned = _NOTE_BLOCK_RE.sub("", cleaned)
    cleaned = _ELEMENT_TABLE_STUB_RE.sub("", cleaned)
    cleaned = _PHOTO_LINE_RE.sub("", cleaned)
    cleaned = _UI_CHROME_LINE_RE.sub("", cleaned)
    cleaned = _INLINE_CONDITION_RATING_ICON_RE.sub("", cleaned)
    cleaned = _INLINE_NOT_INSPECTED_ICON_RE.sub("", cleaned)
    cleaned = _INLINE_NI_ICON_RE.sub("", cleaned)
    cleaned = _INLINE_LETTER_ICON_RE.sub("", cleaned)
    # Trailing / inline photo runs (often concatenated without newlines at section tail).
    prev = None
    while prev != cleaned:
        prev = cleaned
        cleaned = _PHOTO_INLINE_RE.sub("", cleaned)
    cleaned = _MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def _alpha_len(text: str) -> int:
    """Count alphabetic characters — a body-richness proxy for de-duplication."""
    return sum(1 for ch in text if ch.isalpha())


def _normalise_code(raw: str) -> str:
    return re.sub(r"\s+", "", raw.strip().upper())


def _is_valid_code(code: str, valid_section_ids: set[str] | None) -> bool:
    if valid_section_ids is None:
        return True
    return code in {s.upper() for s in valid_section_ids}


def split_into_section_paragraphs(
    text: str,
    valid_section_ids: set[str] | None = None,
    *,
    one_chunk_per_section: bool | None = None,
    include_section_headings: bool | None = None,
) -> list[tuple[str, int, str]]:
    """Return ``(section_id, paragraph_index, paragraph_text)`` tuples."""
    matches = list(_RICS_HEADING_LINE.finditer(text))
    if not matches:
        return []

    keep_one = _one_chunk_mode(one_chunk_per_section)
    keep_heading = _include_headings(include_section_headings)

    # A RICS code typically appears twice in one report: once as a stub row in the
    # ratings summary table (body ≈ "Element no. Element name") and once as the real
    # section with prose. Keep only the richest-prose body per code so the table stub
    # never shadows the genuine content (both previously shared one chunk_id).
    best_body: dict[str, str] = {}
    for i, match in enumerate(matches):
        code = _normalise_code(match.group("code"))
        if not _is_valid_code(code, valid_section_ids):
            continue
        body_start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = truncate_at_foreign_parent_banner(
            _clean_reference_body(text[body_start:end]),
            code,
        )
        if keep_heading:
            heading = _format_leaf_heading(match.group(0), code)
            body = f"{heading}\n\n{body}".strip() if body else heading
        if not body:
            continue
        if _alpha_len(body) > _alpha_len(best_body.get(code, "")):
            best_body[code] = body

    if not best_body:
        return []

    out: list[tuple[str, int, str]] = []
    for section_id, body in best_body.items():
        for idx, part in _emit_body_parts(body, one_chunk_per_section=keep_one):
            out.append((section_id, idx, part))
    return out


def _intro_has_prose(intro: str) -> bool:
    """True when intro has substance beyond a single banner/heading line."""
    lines = [ln.strip() for ln in (intro or "").splitlines() if ln.strip()]
    if len(lines) <= 1:
        return False
    return _alpha_len("\n".join(lines[1:])) >= 40


def split_parent_intro_paragraphs(
    text: str,
    valid_section_ids: set[str] | None = None,
    *,
    one_chunk_per_section: bool | None = None,
) -> list[tuple[str, int, str]]:
    """Return ``(parent_id, paragraph_index, paragraph_text)`` for prose before the
    first leaf subsection under a parent-group banner (e.g. ``F\\nServices`` … ``F1``).

    When the same parent letter appears more than once (ToC / early preview banner
    before the real section), keep the **last** banner before the first leaf that
    still has prose — not the longest span, and not a trailing empty re-banner.
    Intros are also truncated at foreign parent banners / foreign leaf headings.
    """
    headings = list(_RICS_HEADING_LINE.finditer(text))
    banners = list(_PARENT_BANNER_RE.finditer(text))
    if not banners or not headings:
        return []

    keep_one = _one_chunk_mode(one_chunk_per_section)
    keep_heading = _include_headings(None)
    # parent -> (banner_start, intro_text)
    best: dict[str, tuple[int, str]] = {}
    for banner in banners:
        parent = banner.group("letter").upper()
        intro_start = banner.end()
        first_leaf_start: int | None = None
        for heading in headings:
            code = _normalise_code(heading.group("code"))
            if not _is_valid_code(code, valid_section_ids):
                continue
            if _section_parent_letter(code) != parent:
                continue
            if heading.start() < intro_start:
                continue
            first_leaf_start = heading.start()
            break
        if first_leaf_start is None:
            continue
        intro = _clean_reference_body(text[intro_start:first_leaf_start])
        if keep_heading:
            title = (banner.group("title") or "").strip()
            title_l = title.lower()
            if title_l.startswith("icon") or title_l.startswith("logo"):
                title = ""
            banner_line = f"{parent} {title}".rstrip() if title else parent
            intro = f"{banner_line}\n\n{intro}".strip() if intro else banner_line
        if not intro:
            continue
        # Drop residual icon-caption lines that survived banner parsing.
        intro = _UI_CHROME_LINE_RE.sub("", intro)
        intro = _MULTI_BLANK_RE.sub("\n\n", intro).strip()
        intro = truncate_at_foreign_parent_banner(intro, parent)
        if not intro:
            continue
        prev = best.get(parent)
        if prev is None:
            best[parent] = (banner.start(), intro)
            continue
        prev_start, prev_intro = prev
        if banner.start() < prev_start:
            continue
        # Later banner wins unless it is heading-only while earlier still has prose.
        if _intro_has_prose(intro) or not _intro_has_prose(prev_intro):
            best[parent] = (banner.start(), intro)

    if not best:
        return []

    out: list[tuple[str, int, str]] = []
    for parent_id, (_banner_at, body) in best.items():
        for idx, part in _emit_body_parts(body, one_chunk_per_section=keep_one):
            out.append((parent_id, idx, part))
    return out


def split_parent_level_bodies(
    text: str,
    valid_section_ids: set[str] | None = None,
    *,
    one_chunk_per_section: bool | None = None,
) -> list[tuple[str, int, str]]:
    """Return ``(parent_id, paragraph_index, body)`` for A/B/C/K/L/M/N.

    These parents carry no leaf codes in live reports, so their bodies are
    located from the parent-group banner (``B\\nOverall opinion…``). Each body
    runs to the next parent banner or the next leaf heading. For C, the
    official-form prose headings ("Type of property", …) are used as a start
    anchor when the banner itself was corrupted by PDF extraction.
    """
    headings = list(_RICS_HEADING_LINE.finditer(text))
    all_banners = list(_PARENT_BANNER_RE.finditer(text))
    keep_one = _one_chunk_mode(one_chunk_per_section)

    starts: list[tuple[str, int]] = [
        (b.group("letter").upper(), b.end())
        for b in all_banners
        if b.group("letter").upper() in PARENT_STORAGE_PARENT_IDS
    ]
    if not any(letter == "C" for letter, _ in starts):
        c_heading = _C_PROSE_HEADING_RE.search(text)
        if c_heading:
            starts.append(("C", c_heading.start()))

    best_body: dict[str, str] = {}
    for letter, start in starts:
        end = len(text)
        for banner in all_banners:
            if banner.start() > start:
                end = min(end, banner.start())
                break
        for heading in headings:
            code = _normalise_code(heading.group("code"))
            if heading.start() > start and _is_valid_code(code, valid_section_ids):
                end = min(end, heading.start())
                break
        # Also stop at a foreign title-only parent line (not C prose headings).
        for match in _PARENT_TITLE_ONLY_RE.finditer(text):
            if match.start() <= start:
                continue
            title = match.group("title")
            if _title_is_c_prose_heading(title):
                continue
            other = parent_letter_for_title(title)
            if other and other != letter:
                end = min(end, match.start())
                break
        body = _clean_reference_body(text[start:end])
        if body and _alpha_len(body) > _alpha_len(best_body.get(letter, "")):
            best_body[letter] = body

    out: list[tuple[str, int, str]] = []
    for parent_id, body in sorted(best_body.items()):
        for idx, part in _emit_body_parts(body, one_chunk_per_section=keep_one):
            out.append((parent_id, idx, part))
    return out


def _chunk_section_body(
    para_text: str, *, one_chunk_per_section: bool | None = None
) -> list[str]:
    """Keep the whole section body as one chunk (no character limit)."""
    text = (para_text or "").strip()
    return [text] if text else []


def build_reference_chunks(
    text: str,
    *,
    source_filename: str,
    valid_section_ids: set[str] | None = None,
    one_chunk_per_section: bool | None = None,
    include_section_headings: bool | None = None,
) -> list[Chunk]:
    """Build REFERENCE chunks with section metadata; prefer long-form section bodies.

    ``one_chunk_per_section`` (or settings.reference_one_chunk_per_section) keeps
    each subsection / parent-intro / parent body as a single chunk.
    ``include_section_headings`` prepends ``D1 Chimney stacks``-style headings.
    """
    from backend.ingest.pipeline import _chunk_reference_text

    keep_one = _one_chunk_mode(one_chunk_per_section)
    keep_heading = _include_headings(include_section_headings)
    text = normalize_reference_markdown(text)
    text = strip_pdf_extract_furniture(text)
    tagged = split_into_section_paragraphs(
        text,
        valid_section_ids,
        one_chunk_per_section=keep_one,
        include_section_headings=keep_heading,
    )
    if not tagged:
        if keep_one:
            cleaned = _clean_reference_body(text)
            return (
                [
                    Chunk(
                        text=cleaned,
                        tier=TIER_REFERENCE,
                        is_scrubbed=False,
                        source_filename=source_filename,
                        document_type=DOC_TYPE_REFERENCE_REPORT,
                    )
                ]
                if cleaned
                else []
            )
        return [
            Chunk(
                text=_clean_reference_body(t),
                tier=TIER_REFERENCE,
                is_scrubbed=False,
                source_filename=source_filename,
                document_type=DOC_TYPE_REFERENCE_REPORT,
            )
            for t in _chunk_reference_text(text)
            if _clean_reference_body(t).strip()
        ]

    chunks: list[Chunk] = []
    seen_parent_level: set[str] = set()
    for section_id, para_idx, para_text in tagged:
        cleaned = _clean_reference_body(para_text)
        if not cleaned:
            continue
        # Artificial leaf codes under A/B/C/K/L/M/N (layout hooks like ``C1``)
        # collapse to their PARENT storage id — those parents have no real leaf
        # codes in live reports and are stored/retrieved as one parent body.
        stored_id = storage_section_id(section_id) or section_id
        if stored_id != section_id:
            seen_parent_level.add(stored_id)
        pieces = _chunk_section_body(cleaned, one_chunk_per_section=keep_one)
        for piece_i, piece in enumerate(pieces, start=1):
            idx = para_idx if keep_one or len(pieces) == 1 else piece_i
            chunks.append(
                Chunk(
                    text=piece,
                    section_id=stored_id,
                    tier=TIER_REFERENCE,
                    is_scrubbed=False,
                    source_filename=source_filename,
                    chunk_id=f"{source_filename}:{section_id}:p{idx}",
                    paragraph_index=idx,
                    document_type=DOC_TYPE_REFERENCE_REPORT,
                    parent_id=_section_parent_letter(stored_id),
                )
            )

    for parent_id, para_idx, para_text in split_parent_level_bodies(
        text, valid_section_ids, one_chunk_per_section=keep_one
    ):
        if parent_id in seen_parent_level:
            continue
        cleaned = _clean_reference_body(para_text)
        if not cleaned:
            continue
        pieces = _chunk_section_body(cleaned, one_chunk_per_section=keep_one)
        for piece_i, piece in enumerate(pieces, start=1):
            idx = para_idx if keep_one or len(pieces) == 1 else piece_i
            chunks.append(
                Chunk(
                    text=piece,
                    section_id=parent_id,
                    tier=TIER_REFERENCE,
                    is_scrubbed=False,
                    source_filename=source_filename,
                    chunk_id=f"{source_filename}:{parent_id}:p{idx}",
                    paragraph_index=idx,
                    document_type=DOC_TYPE_REFERENCE_REPORT,
                    parent_id=parent_id,
                )
            )

    for parent_id, para_idx, para_text in split_parent_intro_paragraphs(
        text, valid_section_ids, one_chunk_per_section=keep_one
    ):
        cleaned = _clean_reference_body(para_text)
        if not cleaned:
            continue
        pieces = _chunk_section_body(cleaned, one_chunk_per_section=keep_one)
        for piece_i, piece in enumerate(pieces, start=1):
            idx = para_idx if keep_one or len(pieces) == 1 else piece_i
            chunks.append(
                Chunk(
                    text=piece,
                    section_id=parent_id,
                    tier=TIER_REFERENCE,
                    is_scrubbed=False,
                    source_filename=source_filename,
                    chunk_id=f"{source_filename}:parent_{parent_id}:p{idx}",
                    paragraph_index=idx,
                    document_type=DOC_TYPE_REFERENCE_REPORT,
                    content_role=CONTENT_ROLE_PARENT_INTRO,
                    parent_id=parent_id,
                )
            )
    return chunks
