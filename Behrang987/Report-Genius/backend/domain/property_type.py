"""Canonical property-type buckets for past-report RAG scoping.

UI and upload/generate APIs use only these values for REFERENCE retrieval.
Free-text descriptors on DOCX display (when not using past-report RAG) are
orthogonal and must not be stored as chunk ``property_type`` metadata.
"""

from __future__ import annotations

PROPERTY_TYPES = ("house", "flat")


class PropertyTypeError(ValueError):
    """Raised when a value is not a canonical ``house`` / ``flat`` bucket."""


def normalize_property_type(value: str | None) -> str:
    """Return ``house`` or ``flat``; raise :class:`PropertyTypeError` otherwise."""
    raw = (value or "").strip().lower()
    if raw in PROPERTY_TYPES:
        return raw
    raise PropertyTypeError(
        f"property_type must be one of {list(PROPERTY_TYPES)}, got {value!r}"
    )


def try_canonical_property_type(value: str | None) -> str | None:
    """Return canonical type, or ``None`` when missing/invalid."""
    try:
        return normalize_property_type(value)
    except PropertyTypeError:
        return None
