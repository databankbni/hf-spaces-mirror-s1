"""Strip unsupported Condition Ratings from generated section prose.

Past-report scaffolds often carry ``Condition Rating N`` or bare badge digits
(e.g. after a limitations banner). When the current inspection notes / system
supply no explicit rating, those must not appear in the output.
"""

from __future__ import annotations

import re

# Explicit rating cues in notes / system — not bare digits (avoids "Option 3", "5 mm").
_EXPLICIT_NOTES_RATING_RE = re.compile(
    r"""(?ix)
    \bCR\s*[123]\b
    | \bCondition\s+Rating\s*[:\-]?\s*(?:[123]|NI|N/?A)\b
    | \b(?:rating|cat)\s*[=:]?\s*(?:[123]|NI)\b
    | \bcondition\s+(?:[123]|NI)\b
    """
)

_FULL_CONDITION_RATING_RE = re.compile(
    r"(?i)\s*Condition\s+Rating\s*[:\-]?\s*(?:[123]|NI|N/?A)\b\.?"
)

# Banner + trailing badge digit / NI (scaffold bleed after OCR / float-right cells).
_LIMITATIONS_BANNER_BADGE_RE = re.compile(
    r"(?i)((?:\*\*)?SEE THE LIMITATIONS OF OUR INSPECTION ABOVE\.?(?:\*\*)?)"
    r"(?:\s+)(?:[123]|NI)\b"
)

_STANDALONE_BADGE_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:Condition\s+Rating\s*[:\-]?\s*)?(?:[123]|NI)[ \t]*\.?[ \t]*$"
)

_RATING_ICON_CRUMB_RE = re.compile(
    r"(?i)\s*(?:Condition\s+Rating\s+)?(?:[123]|NI)\s+icon\b"
)


def notes_have_explicit_condition_rating(
    notes_text: str = "",
    rating_value: str | None = None,
) -> bool:
    """True when surveyor notes or structured system data supply an explicit CR."""
    if (rating_value or "").strip():
        return True
    return bool(_EXPLICIT_NOTES_RATING_RE.search(notes_text or ""))


def strip_unsupported_condition_ratings(text: str) -> str:
    """Remove Condition Rating phrases and rating-position badge tokens from prose."""
    cleaned = text or ""
    if not cleaned.strip():
        return ""
    cleaned = _FULL_CONDITION_RATING_RE.sub("", cleaned)
    cleaned = _RATING_ICON_CRUMB_RE.sub("", cleaned)
    cleaned = _LIMITATIONS_BANNER_BADGE_RE.sub(r"\1", cleaned)
    cleaned = _STANDALONE_BADGE_LINE_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def apply_condition_rating_policy(
    text: str,
    *,
    notes_text: str = "",
    rating_value: str | None = None,
) -> str:
    """Keep ratings only when notes/system supply an explicit CR; otherwise strip."""
    if notes_have_explicit_condition_rating(notes_text, rating_value):
        return (text or "").strip()
    return strip_unsupported_condition_ratings(text)
