"""Unified, deterministic text normalization for ingest + retrieval queries.

A single normalization pass keeps the *indexed* reference text and the *query*
text in the same canonical form, so cosmetic Unicode differences (smart quotes,
en/em dashes, ligatures, non-breaking spaces, PDF line-break hyphenation) never
cause a lexical/semantic miss. It is intentionally conservative:

* **Structure preserving** — paragraph breaks (blank lines) survive, so the
  reference chunker's section/paragraph splitting is unaffected. Only *runs* of
  intra-line whitespace collapse to a single space.
* **Code preserving** — RICS section codes (``D4``, ``E2``, ``F1`` …) are plain
  alphanumerics and are never altered by any transform here.
* **No semantic edits** — no stemming, casing, stop-word or PII handling. PII
  scrubbing happens on its own path and is untouched.

Gated by ``settings.text_normalize_enabled`` at every call site (default off);
this module itself is a pure function with no global state.
"""

from __future__ import annotations

import re
import unicodedata

# Smart quotes / primes -> straight ASCII; dashes -> hyphen; ellipsis -> "..."
_FOLD: dict[str, str] = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u2032": "'",
    "\u02bc": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u2033": '"',
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
    "\u2026": "...",
}
_TRANSLATION = str.maketrans(_FOLD)

# Newline canonicalization: CR/CRLF and Unicode line/paragraph separators -> \n
_NEWLINE_RE = re.compile(r"\r\n?|\u2028|\u2029")
# Soft-hyphen or hyphen immediately before a newline that splits a word (PDF
# extraction artifact): join the two word halves back together.
_DEHYPHEN_RE = re.compile(r"(\w)[\u00ad\-]\n[ \t]*(\w)")
# Strip stray soft hyphens left anywhere else.
_SOFT_HYPHEN_RE = re.compile(r"\u00ad")
# Any run of horizontal whitespace (incl. NBSP / thin / figure spaces) -> one space
_HSPACE_RE = re.compile(r"[ \t\u00a0\u2000-\u200a\u202f\u205f\u3000]+")
_TRAILING_HSPACE_RE = re.compile(r"[ \t]+\n")
_LEADING_HSPACE_RE = re.compile(r"\n[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Canonicalize Unicode, fold quotes/dashes, de-hyphenate, collapse whitespace.

    Preserves blank-line paragraph boundaries; collapses only intra-line
    whitespace runs. Returns ``""`` for falsy input. Idempotent.
    """
    if not text:
        return ""
    text = _NEWLINE_RE.sub("\n", text)
    text = _DEHYPHEN_RE.sub(r"\1\2", text)
    text = _SOFT_HYPHEN_RE.sub("", text)
    text = text.translate(_TRANSLATION)
    # NFKC folds ligatures (ﬁ -> fi), full-width forms and compatibility chars.
    text = unicodedata.normalize("NFKC", text)
    text = _HSPACE_RE.sub(" ", text)
    text = _TRAILING_HSPACE_RE.sub("\n", text)
    text = _LEADING_HSPACE_RE.sub("\n", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def normalize_query(text: str) -> str:
    """Single-line normalization for a retrieval query (newlines -> spaces)."""
    normalized = normalize_text(text)
    return _HSPACE_RE.sub(" ", normalized.replace("\n", " ")).strip()
