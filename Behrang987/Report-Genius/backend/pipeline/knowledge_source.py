"""Resolve which generation knowledge path(s) a tenant can use."""

from __future__ import annotations

from backend.rag.store import get_rag_store, is_add_to_memory_meta
from backend.rag.types import (
    KNOWLEDGE_SOURCE_BOTH,
    KNOWLEDGE_SOURCE_PAST_REPORT,
    KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
    TIER_REFERENCE,
    TIER_STANDARD_PARAGRAPHS,
)

_VALID = frozenset(
    {
        KNOWLEDGE_SOURCE_PAST_REPORT,
        KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
        KNOWLEDGE_SOURCE_BOTH,
    }
)


def tenant_has_past_reports(tenant_id: str) -> bool:
    """True when REFERENCE holds at least one non–Add-to-Memory chunk."""
    store = get_rag_store()
    for row in store.list_meta(tenant_id, TIER_REFERENCE):
        if not is_add_to_memory_meta(row):
            return True
    return False


def tenant_has_standard_paragraphs(tenant_id: str) -> bool:
    """True when the standard-paragraphs tier has any ingested chunks."""
    return get_rag_store().count(tenant_id, TIER_STANDARD_PARAGRAPHS) > 0


def normalize_knowledge_source(raw: str | None) -> str:
    ks = (raw or KNOWLEDGE_SOURCE_BOTH).strip().lower() or KNOWLEDGE_SOURCE_BOTH
    if ks not in _VALID:
        return KNOWLEDGE_SOURCE_BOTH
    return ks


def resolve_knowledge_source(tenant_id: str, requested: str | None) -> str:
    """Map a requested source to an executable path.

    * ``past_report`` / ``standard_paragraph`` — honour the request when that
      index has content; otherwise fall back to the other if available.
    * ``both`` (default) — run dual-path when past reports **and** standard
      paragraphs exist; otherwise the single available path. Returns ``both``
      only when both indices are non-empty.
    """
    ks = normalize_knowledge_source(requested)
    has_past = tenant_has_past_reports(tenant_id)
    has_sp = tenant_has_standard_paragraphs(tenant_id)

    if ks == KNOWLEDGE_SOURCE_PAST_REPORT:
        if has_past:
            return KNOWLEDGE_SOURCE_PAST_REPORT
        if has_sp:
            return KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH
        return KNOWLEDGE_SOURCE_PAST_REPORT

    if ks == KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH:
        if has_sp:
            return KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH
        if has_past:
            return KNOWLEDGE_SOURCE_PAST_REPORT
        return KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH

    # both / auto
    if has_past and has_sp:
        return KNOWLEDGE_SOURCE_BOTH
    if has_past:
        return KNOWLEDGE_SOURCE_PAST_REPORT
    if has_sp:
        return KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH
    return KNOWLEDGE_SOURCE_BOTH  # neither — caller raises readiness error
