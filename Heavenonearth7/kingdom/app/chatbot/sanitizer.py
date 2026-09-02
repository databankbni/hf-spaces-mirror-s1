"""
Heaven on Earth CMS Backend — Input Sanitizer

Cleans user-submitted chat messages before they are passed to the LLM agent.

References
----------
- Req §12 (Chat API Endpoint), acceptance criteria 12.5–12.6
- Design § "Security & Rate Limiting" → "Input Sanitization"
"""

from __future__ import annotations

import re

# Control characters U+0000–U+001F, excluding tab (\t), newline (\n), carriage return (\r)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_MAX_LENGTH = 2000


def sanitize_input(text: str) -> str:
    """
    Sanitize a user chat message before passing it to the LLM agent.

    Steps applied in order:
    1. Strip leading and trailing whitespace.
    2. Truncate to 2000 characters.
    3. Remove null bytes and control characters (U+0000–U+001F) except
       ``\\t`` (U+0009), ``\\n`` (U+000A), and ``\\r`` (U+000D).

    Parameters
    ----------
    text:
        Raw user input string.

    Returns
    -------
    str
        Cleaned string safe to pass to the agent pipeline.
    """
    # 1. Strip whitespace
    text = text.strip()

    # 2. Truncate to max length
    text = text[:_MAX_LENGTH]

    # 3. Remove disallowed control characters
    text = _CONTROL_CHAR_RE.sub("", text)

    return text
