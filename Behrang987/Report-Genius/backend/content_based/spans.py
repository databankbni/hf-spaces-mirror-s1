"""Locating a model's quoted phrase inside the surveyor's own notes.

Stage A's second pass asks the model to *quote* the stretch of notes an
observation occupies, because a note blob with no full stops and no line breaks
cannot be pre-split into citable sentences. That reintroduces the one risk the
numbered pass does not have: the reply now contains a string, and a string can be
a paraphrase.

This module closes that hole. Nothing here returns model text. ``find_span``
returns a **range into the source**, and the caller slices the source, so what
reaches a report is always the surveyor's characters — original casing, original
spacing, original spelling.

Three defences, each for a failure seen in practice:

* **Whitespace-flexible, case-insensitive matching.** Models reflow and re-case
  quotes even when told not to. Requiring a byte-exact quote would throw away
  correct classifications over a doubled space.
* **Word boundaries at both ends.** An earlier design let the model cite a
  character range and it sliced words in half ("mortar joints weath"). A quote
  that stops mid-word now finds no match instead of filing a mangled fragment.
* **A floor on length.** A one-word quote like "roof" would match the first
  "roof" anywhere in the notes, which is a coin toss rather than a citation.

Anything that fails is discarded by the caller and the text falls through to the
remainder, which is reported to the surveyor. A refused span is visible; a wrong
span is not.
"""

from __future__ import annotations

import re

# Two words can be a coincidence ("the roof"); three carry enough of the
# surveyor's phrasing to identify a position rather than merely a topic.
_MIN_WORDS = 3


def normalize(text: str) -> str:
    """Collapse runs of whitespace, for comparing what the model sent."""
    return re.sub(r"\s+", " ", (text or "").strip())


def _word_count(text: str) -> int:
    return len(normalize(text).split())


def find_span(source: str, proposed: str, *, min_chars: int) -> tuple[int, int] | None:
    """Where ``proposed`` sits in ``source``, or ``None`` when it does not.

    Returns a ``(start, end)`` range so the caller can slice ``source``. It never
    returns text, which is what stops a paraphrase reaching a report: a quote the
    notes do not contain simply has no range.
    """
    flat = normalize(proposed)
    words = flat.split()
    if not words:
        return None
    if len(flat) < min_chars or len(words) < _MIN_WORDS:
        return None

    pattern = r"\s+".join(re.escape(w) for w in words)
    # \b fails on a token ending in punctuation ("2022." or "tile,"), so only
    # guard the edges when the outer characters are word characters themselves.
    if words[0][:1].isalnum():
        pattern = r"\b" + pattern
    if words[-1][-1:].isalnum():
        pattern = pattern + r"\b"

    match = re.search(pattern, source or "", re.IGNORECASE)
    if match is None:
        return None
    return match.start(), match.end()


def resolve_claims(
    source: str,
    proposals: list[tuple[str, str]],
    *,
    min_chars: int,
) -> tuple[list[tuple[str, str, tuple[int, int]]], int]:
    """Accept the quotes that exist in ``source`` and do not overlap each other.

    ``proposals`` is ``(key, quoted_text)``; the key is opaque here so the caller
    can carry a sub-topic code or an index. Returns the accepted
    ``(key, source_slice, range)`` rows in document order, plus a count of what
    was refused.

    Longest claim wins on overlap. A model that quotes both "roof concrete tile
    moss" and "concrete tile" is describing one observation twice, and the longer
    quote is the one that carries the surveyor's full phrasing. Taking both would
    file the same words under two sub-topics and inflate the note-quality score.
    """
    scored: list[tuple[int, str, tuple[int, int]]] = []
    refused = 0
    for key, quoted in proposals:
        found = find_span(source, quoted, min_chars=min_chars)
        if found is None:
            refused += 1
            continue
        scored.append((found[1] - found[0], key, found))

    # Longest first so the winner is settled before shorter overlaps are tested;
    # ties break on position to keep the outcome deterministic.
    scored.sort(key=lambda row: (-row[0], row[2][0]))

    taken: list[tuple[str, tuple[int, int]]] = []
    for _length, key, (start, end) in scored:
        if any(start < t_end and end > t_start for _k, (t_start, t_end) in taken):
            refused += 1
            continue
        taken.append((key, (start, end)))

    taken.sort(key=lambda row: row[1][0])
    return [(key, source[start:end], (start, end)) for key, (start, end) in taken], refused


def uncovered_ranges(
    source: str,
    taken: list[tuple[int, int]],
    *,
    min_chars: int,
) -> list[str]:
    """The stretches of ``source`` nobody claimed, worth showing to a surveyor.

    Gaps below ``min_chars`` are dropped: they are the connective tissue between
    two accepted quotes ("and", "also", stray punctuation), not an observation
    somebody lost.
    """
    text = source or ""
    if not text:
        return []

    merged: list[tuple[int, int]] = []
    for start, end in sorted(taken):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    out: list[str] = []
    cursor = 0
    for start, end in merged:
        gap = text[cursor:start].strip()
        if len(gap) >= min_chars:
            out.append(gap)
        cursor = max(cursor, end)
    tail = text[cursor:].strip()
    if len(tail) >= min_chars:
        out.append(tail)
    return out
