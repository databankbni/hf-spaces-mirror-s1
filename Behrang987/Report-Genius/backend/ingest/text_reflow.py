"""Normalize PDF/OCR mid-sentence hard wraps for embedding-friendly prose.

Amazon Textract emits one LINE per visual row, so a wrapped sentence often
contains ``\\n`` mid-clause. LlamaParse usually returns continuous prose.

This module ONLY joins those soft wraps. It does **not** reflow the document
into a different paragraph/heading structure — section headings stay alone on
their line so ``reference_chunker`` still finds the same 54 units.
"""

from __future__ import annotations

import re

# Previous line ends a sentence → keep the following newline.
_SENTENCE_END_RE = re.compile(r'[.!?…]["”\']?\s*$')
# Soft-wrap continuation: next line continues the same sentence.
_CONTINUATION_START_RE = re.compile(r"""^[a-z(]\s*|^["'“‘]\s*[a-z]""")
# Trailing hyphen from PDF hyphenation: investiga-\n tion → investigation
_HYPHEN_BREAK_RE = re.compile(r"[A-Za-z]-$")


def unwrap_soft_line_breaks(text: str) -> str:
    """Join mid-sentence hard wraps; preserve headings and blank-line breaks.

    Joins when:
    * next line starts lower-case / opening paren (continuation), or
    * previous line ends with ``,`` / ``;`` / ``:`` / dash, or
    * previous line ends with a hyphenated break.

    Does **not** join when the next line starts a new sentence/heading (capital
    letter after a non-comma break) — that keeps ``E4 Floors\\nIt should…``
    intact for the chunker.
    """
    if not text or "\n" not in text:
        return text

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n+", normalized)
    reflowed: list[str] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        reflowed.append(_unwrap_block(lines))
    return "\n\n".join(reflowed)


def _unwrap_block(lines: list[str]) -> str:
    parts: list[str] = [lines[0]]
    for nxt in lines[1:]:
        prev = parts[-1]
        if _HYPHEN_BREAK_RE.search(prev) and nxt[:1].islower():
            parts[-1] = prev[:-1] + nxt
            continue
        if _should_join(prev, nxt):
            parts[-1] = f"{prev} {nxt}"
            continue
        parts.append(nxt)
    return "\n".join(parts)


def _should_join(prev: str, nxt: str) -> bool:
    prev = prev.rstrip()
    nxt = nxt.lstrip()
    if not prev or not nxt:
        return False
    # Explicit list / bullet rows stay separate.
    if nxt[:1] in {"•", "-", "*", "·"}:
        return False
    if _CONTINUATION_START_RE.match(nxt):
        return True
    # Soft wrap after comma / semicolon / colon / dash, even if next is capital
    # (e.g. ``However,\\nIf`` is rare; ``However,\\nif`` is the common case and
    # already handled above — this covers ``grounds,\\nOr`` OCR quirks).
    if prev.endswith((",", ";", ":", "—", "–")):
        return True
    if _SENTENCE_END_RE.search(prev):
        return False
    return False
