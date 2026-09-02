"""Report Post-Processing & Quality Normalisation Pipeline.

A pure, deterministic transformation pass that runs as the FINAL stage after the
RAG report generator produces a section's draft text. It removes PDF-extraction
artifacts, repairs grammar broken by redaction tokens, deduplicates stitched
content and normalises whitespace/punctuation.

HARD CONSTRAINTS (enforced by design):
    * Zero ML models, zero LLM calls, zero network I/O.
    * Never paraphrases or rewrites substantive survey findings — only removes
      artifacts, repairs grammar around redaction tokens, and deduplicates.
    * Stage order is fixed; later stages depend on earlier ones.
    * Does not touch the RAG pipeline, redaction pipeline, or template ingestion.

The single public entry point is :func:`polish_report`.
"""

from __future__ import annotations

import re
from functools import lru_cache

# ── Project defaults ─────────────────────────────────────────────────────────
# The redaction layer emits both base tokens ([REDACTED_REF]) and referential
# tokens ([REDACTED_NAME_1]); some draft text contains double brackets
# ([[REDACTED_NAME_2]]). This default covers all three. Override per-call/config.
DEFAULT_PLACEHOLDER_PATTERN = r"\[{1,2}REDACTED_[A-Z]+(?:_\d+)?\]{1,2}"
DEFAULT_SECTION_SEPARATOR = "\n\n"
DEFAULT_DEDUP_THRESHOLD = 0.85

# Short, meaningful rating boilerplate (e.g. a one-line condition score) must
# never be deduplicated — only substantial repeated content is collapsed.
_MIN_DEDUP_SENTENCE_CHARS = 40
_MIN_DEDUP_PARAGRAPH_CHARS = 80

# Private-use sentinel for placeholder grammar repair (never appears in input).
_PH_SENTINEL = "\ue000"

# Visible, honest placeholder for an unresolved redaction token. Never emit the
# bare word "specified" — an operator must be able to see what needs confirming.
NEUTRAL_PLACEHOLDER = "[SURVEYOR TO CONFIRM]"

# ── Stage 1: PDF extraction artifacts ────────────────────────────────────────
_RE_PAGE_LABEL = re.compile(r"(?i)\bpage\s*\d{1,4}\b")
_RE_ORPHAN_PAGE_NUMBER = re.compile(r"(?m)^[ \t]*\d{1,4}[ \t]*$")
_RE_DEFAULT_DOC_HEADER = re.compile(
    r"(?i)RICS\s+Home\s+Survey\s*[-\u2013\u2014]?\s*Level\s+\d+",
)
_RE_TOC_LINE = re.compile(r"(?im)^[ \t]*ToC\s*[:\-].*$")

# ── Stage 2: repeated section headers ────────────────────────────────────────
_RE_SECTION_HEADER = re.compile(r"^([A-Z][A-Z0-9\s\-/&]{3,}:)\s*$")
_HEADER_DEDUP_WINDOW_WORDS = 500

# ── Stage 4: sentence splitting (newline-agnostic) ───────────────────────────
_RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_RE_WS = re.compile(r"\s+")

# ── Stage 5: ALL-CAPS internal directives ────────────────────────────────────
_DIRECTIVE_CUES = frozenset(
    {"SEE", "REFER", "OUTLINED", "DESCRIBED", "ABOVE", "BELOW", "STATED", "NOTED"}
)
_RE_WORD_TOKEN = re.compile(r"[A-Za-z']+")

# ── Stage 6: whitespace / punctuation ────────────────────────────────────────
_RE_MULTI_NEWLINE = re.compile(r"\n{3,}")
_RE_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_RE_DOUBLE_SPACE = re.compile(r"[ \t]{2,}")
_RE_HYPHEN_LINEBREAK = re.compile(r"([A-Za-z])-\n[ \t]*([a-z])")
# Rejoin a mid-sentence line break (prev char is alnum/comma/semicolon, next is
# lowercase/digit). Crosses blank-line gaps left by stripped page-break artifacts,
# but never merges across sentence-ending punctuation.
_RE_SOFT_WRAP = re.compile(r"(?<=[A-Za-z,;0-9])[ \t]*\n[ \t\n]*(?=[a-z0-9(])")
_RE_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:!?])")
_RE_SPACE_AFTER_SENTENCE = re.compile(r"([a-z0-9])([.!?])([A-Z])")
_UNICODE_TRANSLATION = {
    ord("\u201c"): '"',
    ord("\u201d"): '"',
    ord("\u2018"): "'",
    ord("\u2019"): "'",
    ord("\u2013"): "-",
    ord("\u2014"): "-",
    ord("\u00a0"): " ",
    ord("\u2022"): "-",
}

# ── Stage 7: paragraph flow ──────────────────────────────────────────────────
_LEADING_CONJUNCTIONS = frozenset({"and", "but", "or", "nor", "so", "yet"})
_RE_LEADING_CONJUNCTION = re.compile(r"^(and|but|or|nor|so|yet)\b[ ,]*", re.IGNORECASE)
_RE_INLINE_HEADER = re.compile(r"[ \t]*\b([A-Z][A-Z0-9 \-/&]{3,}:)[ \t]*")


def _stage_1_remove_extraction_artifacts(
    text: str,
    extra_header_patterns: list[re.Pattern[str]] | None = None,
) -> str:
    """Remove orphaned page numbers and repeated document headers from PDF extraction."""
    text = _RE_PAGE_LABEL.sub(" ", text)
    text = _RE_DEFAULT_DOC_HEADER.sub(" ", text)
    for pattern in extra_header_patterns or ():
        text = pattern.sub(" ", text)
    text = _RE_TOC_LINE.sub("", text)
    text = _RE_ORPHAN_PAGE_NUMBER.sub("", text)
    return text


def _stage_2_deduplicate_section_headers(text: str) -> str:
    """Keep only the first occurrence of each ALL-CAPS section header within a 500-word window."""
    last_seen: dict[str, int] = {}
    kept_lines: list[str] = []
    word_count = 0
    for line in text.split("\n"):
        match = _RE_SECTION_HEADER.match(line.strip())
        if match:
            key = _RE_WS.sub(" ", match.group(1).strip().upper())
            previous = last_seen.get(key)
            if (
                previous is not None
                and (word_count - previous) <= _HEADER_DEDUP_WINDOW_WORDS
            ):
                last_seen[key] = word_count
                continue
            last_seen[key] = word_count
        word_count += len(line.split())
        kept_lines.append(line)
    return "\n".join(kept_lines)


@lru_cache(maxsize=16)
def _placeholder_regexes(
    placeholder_pattern: str,
) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """Compile (once per unique pattern) the standalone-line and token-run regexes."""
    token = rf"(?:{placeholder_pattern})"
    standalone = re.compile(
        rf"(?m)^[ \t]*{token}(?:[ \t]*{token})*[ \t]*[.;:,\-]?[ \t]*$\n?"
    )
    run = re.compile(rf"{token}(?:\s*{token})*")
    return standalone, run


# Sentinel-stage regexes (independent of the configurable token pattern).
_RE_PH_POSSESSIVE = re.compile(rf"{_PH_SENTINEL}'s\b")
_RE_PH_SENTENCE_INITIAL = re.compile(
    rf"(\A|[.!?][\"')\]]?\s+|\n[ \t]*){_PH_SENTINEL}[ \t]*(\w)"
)
_RE_PLACEHOLDER_DUP = re.compile(
    r"\[SURVEYOR TO CONFIRM\](?:\s+\[SURVEYOR TO CONFIRM\])+"
)
_RE_ARTICLE_DUP = re.compile(r"\b(the|a|an)\s+(the|a|an)\b", re.IGNORECASE)

# ── Dangling redaction-date artifacts ────────────────────────────────────────
# Fixed safety/regulatory boilerplate embeds a date/reference that PII redaction
# sometimes over-masks, leaving "...work undertaken after [SURVEYOR TO CONFIRM]
# should..." or a trailing "...installed in [SURVEYOR TO CONFIRM].". Dropping the
# temporal/locative-date clause yields clean professional prose without inventing
# a value or losing a finding. A placeholder standing for a material, location or
# other finding is deliberately left visible for the surveyor to confirm.
_PH_LITERAL = re.escape(NEUTRAL_PLACEHOLDER)
_RE_PH_DATED_BEFORE_MODAL = re.compile(
    r"\b(?:undertaken|carried out|completed|performed|installed|fitted|constructed|built)\s+"
    r"(?:after|before|since|from|in|on|around|circa|prior to|up to)\s+"
    rf"{_PH_LITERAL}\s+"
    r"(?=(?:should|must|shall|will|would|may|might|can|are|is|was|were|be)\b)",
    re.IGNORECASE,
)
# Trailing rule is restricted to unambiguously TEMPORAL prepositions — "of", "in",
# "on", "from" can introduce a redacted name or location, which must stay visible.
_RE_PH_TRAILING_DATE = re.compile(
    r"\s*,?\s*(?:after|before|since|dated|around|circa|prior to|up to)\s+"
    rf"{_PH_LITERAL}(?=\s*[.;:,)])",
    re.IGNORECASE,
)


def neutralise_dangling_placeholders(text: str) -> str:
    """Drop a temporal/date clause whose only value is an unresolved placeholder.

    Targets the recurring redaction-date artifact in fixed safety/regulatory
    boilerplate. Never removes a placeholder that stands for a material, location
    or finding — that stays visible for surveyor confirmation.
    """
    if NEUTRAL_PLACEHOLDER not in text:
        return text
    text = _RE_PH_DATED_BEFORE_MODAL.sub("", text)
    text = _RE_PH_TRAILING_DATE.sub("", text)
    return text


def _stage_3_normalise_placeholder_grammar(text: str, placeholder_pattern: str) -> str:
    """Repair grammatical breakage caused by inline redaction tokens.

    Tokens are replaced with neutral language; the redacted value is never
    revealed or approximated.
    """
    standalone_re, run_re = _placeholder_regexes(placeholder_pattern)

    # 1. Standalone token(s) on their own line → drop the entire line.
    text = standalone_re.sub("", text)
    # 2. Collapse any run of (adjacent) tokens to a single sentinel.
    text = run_re.sub(_PH_SENTINEL, text)
    # 3. Drop a possessive clitic clinging to a sentinel ([REDACTED]'s → sentinel).
    text = _RE_PH_POSSESSIVE.sub(_PH_SENTINEL, text)
    # 4. Sentence-initial sentinel → drop token, capitalise the following word.
    text = _RE_PH_SENTENCE_INITIAL.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    # 5. Remaining mid-sentence sentinels → explicit surveyor placeholder
    #    (never the bare word "specified", which reads as real content).
    text = text.replace(_PH_SENTINEL, NEUTRAL_PLACEHOLDER)
    # 6. Tidy artefacts of the substitution.
    text = _RE_PLACEHOLDER_DUP.sub(NEUTRAL_PLACEHOLDER, text)
    text = _RE_ARTICLE_DUP.sub(r"\1", text)
    text = neutralise_dangling_placeholders(text)
    return text


def _normalise_for_compare(text: str) -> str:
    return _RE_WS.sub(" ", text.lower()).strip()


def _trigrams(text: str) -> set[str]:
    return {text[i : i + 3] for i in range(len(text) - 2)}


def _jaccard_similarity(a: str, b: str) -> float:
    """Character-trigram Jaccard similarity — fast, zero dependencies."""
    t_a, t_b = _trigrams(a.lower()), _trigrams(b.lower())
    if not t_a or not t_b:
        return 0.0
    return len(t_a & t_b) / len(t_a | t_b)


def _stage_4_deduplicate_content(
    text: str, similarity_threshold: float = DEFAULT_DEDUP_THRESHOLD
) -> str:
    """Remove duplicate sentences (exact) and near-duplicate paragraphs (Jaccard).

    Short boilerplate below ``_MIN_DEDUP_SENTENCE_CHARS`` (e.g. condition-rating
    tags) is preserved verbatim. Pure string comparison only — no ML.
    """
    paragraphs = re.split(r"\n{2,}", text)
    seen_sentences: set[str] = set()
    kept_paragraphs: list[str] = []
    kept_norms: list[str] = []

    for paragraph in paragraphs:
        sentences = _RE_SENTENCE_SPLIT.split(paragraph.strip())
        deduped: list[str] = []
        prev_norm: str | None = None
        for sentence in sentences:
            norm = _normalise_for_compare(sentence)
            # Collapse immediately-adjacent identical sentences (stitching noise),
            # regardless of length — non-adjacent short repeats are preserved.
            if norm and norm == prev_norm:
                continue
            if len(norm) >= _MIN_DEDUP_SENTENCE_CHARS:
                if norm in seen_sentences:
                    prev_norm = norm
                    continue
                seen_sentences.add(norm)
            if sentence.strip():
                deduped.append(sentence.strip())
            prev_norm = norm

        rebuilt = " ".join(deduped)
        if not rebuilt.strip():
            continue

        norm_paragraph = _normalise_for_compare(rebuilt)
        if len(norm_paragraph) >= _MIN_DEDUP_PARAGRAPH_CHARS and any(
            _jaccard_similarity(norm_paragraph, prior) >= similarity_threshold
            for prior in kept_norms
        ):
            continue

        kept_paragraphs.append(rebuilt)
        kept_norms.append(norm_paragraph)

    return "\n\n".join(kept_paragraphs)


def _is_caps_directive(sentence: str) -> bool:
    """True when a sentence is an ALL-CAPS internal directive (not client-facing)."""
    tokens = _RE_WORD_TOKEN.findall(sentence)
    alpha = [t for t in tokens if any(c.isalpha() for c in t)]
    if len(alpha) < 2:
        return False
    upper = [t for t in alpha if len(t) >= 2 and t.upper() == t]
    if len(upper) / len(alpha) <= 0.6:
        return False
    return bool({t.upper() for t in tokens} & _DIRECTIVE_CUES)


def _stage_5_scrub_internal_directives(text: str) -> str:
    """Remove ALL-CAPS procedural directives (e.g. SEE THE LIMITATIONS ... ABOVE)."""
    paragraphs = re.split(r"\n{2,}", text)
    out: list[str] = []
    for paragraph in paragraphs:
        sentences = _RE_SENTENCE_SPLIT.split(paragraph)
        kept = [s for s in sentences if not _is_caps_directive(s)]
        rebuilt = " ".join(s.strip() for s in kept if s.strip())
        if rebuilt.strip():
            out.append(rebuilt)
    return "\n\n".join(out)


def _stage_6_normalise_whitespace_and_punctuation(text: str) -> str:
    """Normalise unicode, rejoin soft-wrapped lines, and tidy spacing/newlines."""
    text = text.translate(_UNICODE_TRANSLATION)
    text = _RE_HYPHEN_LINEBREAK.sub(r"\1\2", text)  # de-hyphenate broken words
    text = _RE_SOFT_WRAP.sub(" ", text)  # rejoin mid-sentence line wraps
    text = _RE_TRAILING_SPACE.sub("", text)
    text = _RE_DOUBLE_SPACE.sub(" ", text)
    text = _RE_SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _RE_SPACE_AFTER_SENTENCE.sub(r"\1\2 \3", text)
    text = _RE_MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def _repair_paragraph(paragraph: str) -> str:
    stripped = paragraph.strip()
    if not stripped:
        return ""
    # Drop a coordinating conjunction orphaned from a stripped predecessor sentence.
    first_word = stripped.split(maxsplit=1)[0].lower().strip(",")
    if first_word in _LEADING_CONJUNCTIONS and not stripped[0].isupper():
        stripped = _RE_LEADING_CONJUNCTION.sub("", stripped, count=1).lstrip()
    if not stripped:
        return ""
    # Capitalise the first alphabetic character.
    if stripped[0].islower():
        stripped = stripped[0].upper() + stripped[1:]
    # Ensure terminal punctuation (headers ending ':' are left alone).
    if stripped[-1] not in ".!?:":
        stripped = f"{stripped}."
    return stripped


def _stage_7_repair_paragraph_flow(text: str) -> str:
    """Capitalise paragraph starts, drop orphan leading conjunctions, ensure terminal stops."""
    # Lift inline ALL-CAPS headers onto their own line for readability.
    text = _RE_INLINE_HEADER.sub(lambda m: f"\n\n{m.group(1)}\n", text)
    text = _RE_MULTI_NEWLINE.sub("\n\n", text)
    paragraphs = re.split(r"\n{2,}", text)
    repaired = [_repair_paragraph(p) for p in paragraphs]
    return "\n\n".join(p for p in repaired if p)


def _resolve_defaults(
    placeholder_pattern: str | None,
    dedup_similarity_threshold: float | None,
    extra_header_patterns: list[re.Pattern[str]] | list[str] | None,
    debug: bool | None,
) -> tuple[str, float, list[re.Pattern[str]], bool]:
    """Pull unset arguments from project config, with hard-coded fallbacks."""
    cfg_pattern = DEFAULT_PLACEHOLDER_PATTERN
    cfg_threshold = DEFAULT_DEDUP_THRESHOLD
    cfg_extra: list[str] = []
    cfg_debug = False
    try:  # config is optional so the module stays standalone-importable/testable.
        from backend.config import settings

        cfg_pattern = getattr(settings, "postprocess_placeholder_pattern", cfg_pattern)
        cfg_threshold = getattr(settings, "dedup_similarity_threshold", cfg_threshold)
        cfg_extra = list(getattr(settings, "extra_header_patterns", []) or [])
        cfg_debug = bool(getattr(settings, "postprocess_debug", False))
    except Exception:  # noqa: BLE001 — never let config import break a pure transform.
        pass

    pattern = placeholder_pattern if placeholder_pattern is not None else cfg_pattern
    threshold = (
        dedup_similarity_threshold
        if dedup_similarity_threshold is not None
        else cfg_threshold
    )

    raw_extra = (
        extra_header_patterns if extra_header_patterns is not None else cfg_extra
    )
    compiled_extra: list[re.Pattern[str]] = []
    for item in raw_extra:
        compiled_extra.append(
            item if isinstance(item, re.Pattern) else re.compile(item, re.IGNORECASE)
        )

    return (
        pattern,
        threshold,
        compiled_extra,
        (debug if debug is not None else cfg_debug),
    )


def polish_report(
    raw_report: str,
    placeholder_pattern: str | None = None,
    section_separator: str = DEFAULT_SECTION_SEPARATOR,
    extra_header_patterns: list[re.Pattern[str]] | list[str] | None = None,
    dedup_similarity_threshold: float | None = None,
    debug: bool | None = None,
) -> str:
    """Apply a sequential, non-destructive post-processing pipeline to a draft report.

    Stages (in strict order):
      1. PDF extraction artifact removal
      2. Repeated section header suppression
      3. Placeholder grammar normalisation
      4. Duplicate sentence / paragraph deduplication
      5. ALL-CAPS directive scrubbing
      6. Whitespace and punctuation normalisation
      7. Paragraph-level flow repair

    Args:
        raw_report: The full draft report string from the RAG pipeline.
        placeholder_pattern: Regex matching redacted tokens. Defaults to the
            project pattern (config ``postprocess_placeholder_pattern``), which
            covers ``[REDACTED_NAME_1]``, ``[REDACTED_REF]`` and ``[[...]]``.
        section_separator: Delimiter used to join the polished section blocks.
        extra_header_patterns: Additional firm-specific header patterns to strip
            (strings or compiled patterns). Falls back to config
            ``extra_header_patterns``; keeps the pipeline firm-agnostic.
        dedup_similarity_threshold: 0.0-1.0 character-trigram Jaccard threshold
            for near-duplicate paragraph removal (config ``dedup_similarity_threshold``).
        debug: When true, print a before/after preview to stdout.

    Returns:
        A clean, publication-ready report string.

    Raises:
        ValueError: If ``raw_report`` is empty or None.
    """
    if not raw_report or not raw_report.strip():
        raise ValueError("raw_report cannot be empty.")

    pattern, threshold, compiled_extra, debug_on = _resolve_defaults(
        placeholder_pattern, dedup_similarity_threshold, extra_header_patterns, debug
    )

    text = raw_report
    text = _stage_1_remove_extraction_artifacts(text, compiled_extra)
    text = _stage_2_deduplicate_section_headers(text)
    text = _stage_3_normalise_placeholder_grammar(text, pattern)
    text = _stage_4_deduplicate_content(text, threshold)
    text = _stage_5_scrub_internal_directives(text)
    text = _stage_6_normalise_whitespace_and_punctuation(text)
    text = _stage_7_repair_paragraph_flow(text)

    result = section_separator.join(
        block for block in re.split(r"\n{2,}", text) if block.strip()
    ).strip()

    if debug_on:
        print("=" * 72)
        print("polish_report — BEFORE:\n")
        print(raw_report[:1200])
        print("\n" + "-" * 72)
        print("polish_report — AFTER:\n")
        print(result[:1200])
        print("=" * 72)

    return result


if __name__ == "__main__":  # pragma: no cover — manual before/after demo
    _SAMPLE = (
        "[REDACTED_NAME_1] repairs tend to be expensive due to the associated "
        "scaffolding costs. SEE THE LIMITATIONS OF OUR INSPECTION ABOVE. MAIN ROOF:\n"
        "The main roof structure is of hipped pitch and [[REDACTED_NAME_2]] "
        "construction, partially extended to form\ndormers. The pitched roof "
        "covering appears to be of plain concrete tiles. However, some areas were "
        "concealed from view due to the loft\n2\nRICS Home Survey - Level 3\n26\n"
        "conversion. The element rating is 2. The element rating is 2."
    )
    polish_report(_SAMPLE, debug=True)
