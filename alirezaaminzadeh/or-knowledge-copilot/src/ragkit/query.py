"""Query rewrite and metadata routing."""

from __future__ import annotations

import re
from typing import Any


def detect_language(text: str) -> str:
    persian = len(re.findall(r"[\u0600-\u06FF]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "fa" if persian > latin else "en"


def rewrite_query(question: str, synonyms: dict[str, list[str]] | None = None) -> str:
    expanded = [question]
    lower = question.lower()
    for key, alts in (synonyms or {}).items():
        if key in lower:
            expanded.extend(alts)
    return " ".join(expanded)


def apply_filters(
    metadata: dict[str, Any],
    filters: dict[str, Any] | None,
) -> bool:
    if not filters:
        return True
    for key, expected in filters.items():
        if expected in (None, "", "all"):
            continue
        value = metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            if value not in expected:
                return False
        elif str(value).lower() != str(expected).lower():
            return False
    return True
