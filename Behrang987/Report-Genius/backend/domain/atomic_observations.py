"""Split surveyor notes into ordered atomic observation units for routing."""

from __future__ import annotations

import re


def split_atomic_observations(observations: list[str]) -> list[str]:
    """Return one claim per list entry, preserving order.

    Each input line may already be atomic (from :func:`notes_parser`). This helper
    further splits semicolon-separated shorthand when present.
    """
    out: list[str] = []
    for obs in observations:
        text = (obs or "").strip()
        if not text:
            continue
        parts = [p.strip() for p in re.split(r"\s*;\s*", text) if p.strip()]
        if len(parts) > 1:
            out.extend(parts)
        else:
            out.append(text)
    return out
