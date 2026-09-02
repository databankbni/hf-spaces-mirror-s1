"""
Heaven on Earth CMS Backend — System Prompts Package

Exposes ``load_system_prompt(language)`` which reads the language-specific
system prompt from disk once and caches it for subsequent calls.

References
----------
- Req §7.6 (Response Formatter language selection)
- Req §6.3 (language toggle persistence)
- Design § "Bilingual Design (Amharic + English)" → Language-Specific System Prompts
- Task 10 (full implementation of system prompt text files)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Module-level prompt cache — populated lazily on first call
# ---------------------------------------------------------------------------
_PROMPT_CACHE: dict[str, str] = {}

_PROMPT_DIR = Path(__file__).parent


def load_system_prompt(language: Literal["en", "am"]) -> str:
    """
    Return the system prompt for *language*, reading it from disk on first
    call and returning the cached value on subsequent calls.

    Parameters
    ----------
    language:
        ``"en"`` for English, ``"am"`` for Amharic.

    Returns
    -------
    str
        The system prompt text.
    """
    if language not in _PROMPT_CACHE:
        filename = "system_am.txt" if language == "am" else "system_en.txt"
        prompt_path = _PROMPT_DIR / filename
        _PROMPT_CACHE[language] = prompt_path.read_text(encoding="utf-8")

    return _PROMPT_CACHE[language]
