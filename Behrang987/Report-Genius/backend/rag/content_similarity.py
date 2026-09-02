"""Semantic library search + draft overlap detection for the legacy UI."""

from __future__ import annotations

import re
from typing import Any

from backend.rag.store import get_rag_store
from backend.rag.types import TIER_REFERENCE
from backend.storage.report_session import list_documents

_MIN_CHARS_LIBRARY = 12
_MIN_LINE_CHARS = 14
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokens(s: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(s)}


def jaccard_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def find_draft_overlaps(
    text: str,
    section_code: str | None,
    peer_sections: dict[str, str],
    *,
    line_threshold: float = 0.42,
    block_threshold: float = 0.38,
) -> list[dict[str, Any]]:
    text = text.strip()
    if not text:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    current_lines = [
        ln.strip() for ln in text.splitlines() if len(ln.strip()) >= _MIN_LINE_CHARS
    ]
    if not current_lines:
        current_lines = [text] if len(text) >= _MIN_LINE_CHARS else []

    for other_code, peer_raw in peer_sections.items():
        if section_code and other_code == section_code:
            continue
        peer_text = (peer_raw or "").strip()
        if not peer_text:
            continue

        blk_sim = jaccard_similarity(text, peer_text)
        if (
            blk_sim >= block_threshold
            and len(text) >= _MIN_LINE_CHARS
            and len(peer_text) >= _MIN_LINE_CHARS
        ):
            bkey = f"b:{section_code or ''}:{other_code}:{text[:80]}:{peer_text[:80]}"
            if bkey not in seen:
                seen.add(bkey)
                short_peer = (
                    peer_text if len(peer_text) <= 220 else peer_text[:217] + "…"
                )
                short_you = text if len(text) <= 220 else text[:217] + "…"
                out.append(
                    {
                        "other_section_code": other_code,
                        "overlap_kind": "block",
                        "similarity": round(blk_sim, 4),
                        "your_preview": short_you,
                        "other_preview": short_peer,
                    }
                )

        peer_lines = [
            ln.strip()
            for ln in peer_text.splitlines()
            if len(ln.strip()) >= _MIN_LINE_CHARS
        ]
        for cl in current_lines:
            for pl in peer_lines:
                sim = jaccard_similarity(cl, pl)
                if sim < line_threshold:
                    continue
                lkey = f"l:{other_code}:{cl[:60]}:{pl[:60]}"
                if lkey in seen:
                    continue
                seen.add(lkey)
                out.append(
                    {
                        "other_section_code": other_code,
                        "overlap_kind": "line",
                        "similarity": round(sim, 4),
                        "your_preview": cl if len(cl) <= 200 else cl[:197] + "…",
                        "other_preview": pl if len(pl) <= 200 else pl[:197] + "…",
                    }
                )

    out.sort(key=lambda m: m["similarity"], reverse=True)
    return out[:24]


def scan_similar_content(
    tenant_id: str,
    *,
    text: str,
    section_code: str | None = None,
    peer_sections: dict[str, str] | None = None,
    limit: int = 8,
    min_relevance_percent: float = 28.0,
    exclude_document_ids: list[str] | None = None,
) -> dict[str, Any]:
    peer_sections = peer_sections or {}
    draft_overlaps = find_draft_overlaps(text, section_code, peer_sections)

    q = text.strip()
    if len(q) < _MIN_CHARS_LIBRARY:
        msg = (
            "Add a little more text (at least 12 characters) to search your uploaded library."
            if q
            else "Enter some notes to compare against your library."
        )
        return {"library_matches": [], "draft_overlaps": draft_overlaps, "message": msg}

    store = get_rag_store()
    if store.count(tenant_id, TIER_REFERENCE) == 0:
        return {
            "library_matches": [],
            "draft_overlaps": draft_overlaps,
            "message": "No indexed reference documents yet for this tenant, or nothing similar was found.",
        }

    exclude_filenames: set[str] = set()
    if exclude_document_ids:
        docs = list_documents(tenant_id)
        for doc_id in exclude_document_ids:
            row = docs.get(doc_id)
            if row:
                exclude_filenames.add(row.filename)

    fetch_k = min(max(limit * 6, 16), 80)
    raw = store.search_for_reference_mapping(
        tenant_id,
        q,
        section_id=section_code or None,
        top_k=fetch_k,
        section_strict=False,
    )
    if not raw:
        return {
            "library_matches": [],
            "draft_overlaps": draft_overlaps,
            "message": "No indexed reference documents yet for this tenant, or nothing similar was found.",
        }

    docs = list_documents(tenant_id)
    filename_to_doc_id = {d.filename: d.document_id for d in docs.values()}

    mx = max(r.score for r in raw)
    library: list[dict[str, Any]] = []
    seen_chunks: set[str] = set()

    for hit in raw:
        sf = hit.source_filename or ""
        if sf in exclude_filenames:
            continue
        chunk_key = hit.chunk_id or f"{hit.doc_id}:{hit.paragraph_index}"
        if chunk_key in seen_chunks:
            continue
        pct = 100.0 * hit.score / mx if mx > 0 else 0.0
        if pct < min_relevance_percent:
            continue
        seen_chunks.add(chunk_key)
        snip = (hit.text or "").strip()
        if len(snip) > 320:
            snip = snip[:317] + "…"
        library.append(
            {
                "chunk_id": chunk_key,
                "document_id": filename_to_doc_id.get(sf, hit.doc_id),
                "filename": sf or None,
                "snippet": snip,
                "relevance_percent": round(pct, 1),
                "section_type": hit.section_id or "paragraph",
            }
        )
        if len(library) >= limit:
            break

    msg = ""
    if not library and raw:
        msg = (
            "No library matches after applying your filters (excluded documents and/or relevance threshold). "
            "Lower min_relevance_percent, clear exclude_document_ids, or upload additional reference files."
        )

    return {
        "library_matches": library,
        "draft_overlaps": draft_overlaps,
        "message": msg,
    }
