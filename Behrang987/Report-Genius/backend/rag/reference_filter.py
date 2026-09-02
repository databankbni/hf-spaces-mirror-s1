"""Resolve API reference_document_ids to FAISS metadata keys for strict retrieval."""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.storage.report_session import list_documents


def _allowlist_key_forms(token: str) -> set[str]:
    """Exact key plus ``reference:``-stripped and extension-stripped variants.

    FAISS rows may store ``reference:<id>.pdf`` while the allowlist holds a bare
    document id (or the reverse). Matching any shared form keeps strict filtering
    from dropping the entire reference tier.
    """
    raw = str(token or "").strip()
    if not raw:
        return set()
    forms = {raw}
    bare = raw.split(":", 1)[-1] if raw.startswith("reference:") else raw
    if bare:
        forms.add(bare)
        stem = PurePosixPath(bare).stem
        if stem:
            forms.add(stem)
    return forms


def meta_matches_allowlist(meta: dict, allowlist: frozenset[str]) -> bool:
    """True when chunk ``doc_id`` or ``source_filename`` is in the allowlist.

    Tolerates ``reference:`` prefix and trailing file-extension skew between
    allowlist keys and FAISS metadata (bare id vs ``<id>.pdf`` /
    ``reference:<id>.pdf``).
    """
    if not allowlist:
        return False
    doc_id = str(meta.get("doc_id") or "").strip()
    source = str(meta.get("source_filename") or "").strip()
    if doc_id in allowlist or source in allowlist:
        return True

    meta_forms = _allowlist_key_forms(doc_id) | _allowlist_key_forms(source)
    if not meta_forms:
        return False
    allow_forms: set[str] = set()
    for key in allowlist:
        allow_forms |= _allowlist_key_forms(key)
    return bool(meta_forms & allow_forms)


def list_registered_reference_document_ids(tenant_id: str) -> list[str]:
    """Every user-uploaded reference document indexed for this tenant."""
    return [
        doc_id
        for doc_id, doc in list_documents(tenant_id).items()
        if doc.status == "complete" and doc.ingested_chunks > 0
    ]


def resolve_reference_document_ids(
    tenant_id: str,
    reference_document_ids: list[str] | None,
    *,
    session_document_ids: list[str] | None = None,
    primary_document_id: str | None = None,
    strict_uploaded_only: bool = False,
) -> list[str] | None:
    """Merge explicit, session, primary, and historical uploads into one RAG scope.

    Returns ``None`` when the caller should search the full FAISS tier (default).
    When ``strict_uploaded_only`` is True, the scope is **all registered tenant
    uploads** (current + historical) plus any explicit/session ids not yet in the
    registry — never a single-document subset. This excludes bundled auto-ingest
    samples that were never registered in ``compat_documents.json``.
    """
    if not strict_uploaded_only:
        return None

    merged: set[str] = set(list_registered_reference_document_ids(tenant_id))
    for bucket in (reference_document_ids or [], session_document_ids or []):
        for doc_id in bucket:
            token = str(doc_id or "").strip()
            if token:
                merged.add(token)
    primary = str(primary_document_id or "").strip()
    if primary:
        merged.add(primary)
    return sorted(merged) if merged else None


def build_reference_allowlist(
    tenant_id: str,
    reference_document_ids: list[str] | None,
    *,
    strict_uploaded_only: bool,
    session_document_ids: list[str] | None = None,
    primary_document_id: str | None = None,
) -> frozenset[str] | None:
    """Build allowlist for ``rag_store.search`` when strict filtering is requested.

    Returns ``None`` when no filtering should be applied (search the full tier).
    """
    ids = resolve_reference_document_ids(
        tenant_id,
        reference_document_ids,
        session_document_ids=session_document_ids,
        primary_document_id=primary_document_id,
        strict_uploaded_only=strict_uploaded_only,
    )
    if ids is None:
        return None
    if not ids:
        return None

    docs = list_documents(tenant_id)
    allow: set[str] = set()
    for doc_id in ids:
        allow.add(doc_id)
        row = docs.get(doc_id)
        if row is None:
            continue
        filename = (row.filename or "").strip()
        if filename:
            allow.add(filename)
            allow.add(f"reference:{filename}")
    return frozenset(allow)
