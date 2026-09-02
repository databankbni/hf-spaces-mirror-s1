"""Retrieve MASTER or REFERENCE paragraphs for mapping messy field notes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from backend.config import settings
from backend.llm.reranker import cross_encoder_rerank
from backend.models.schema import TemplateSchema
from backend.observability import tracing as observability
from backend.rag.store import get_rag_store
from backend.rag.types import SearchHit

logger = logging.getLogger(__name__)

InterferenceLevel = Literal["minimum", "medium", "maximum"]
RetrievalLevel = Literal["paragraph", "section", "document"]

_STOP = frozenset(
    {
        "about",
        "with",
        "from",
        "this",
        "that",
        "level",
        "section",
        "inside",
        "outside",
        "other",
        "property",
        "report",
        "survey",
        "your",
        "the",
        "and",
        "were",
        "was",
        "has",
        "have",
        "been",
        "noted",
        "inspected",
        "ground",
    }
)


def build_retrieval_query(
    section_label: str,
    observations: list[str],
    *,
    section_id: str = "",
) -> str:
    """Semantic query anchored to the target section ID + observations.

    Past-report retrieval embeds the **full** inspection-note text for the
    section (all observation strings joined in order). Do not truncate to a
    top-N longest subset — short findings must still influence the match.
    """
    sid = (section_id or "").strip().upper()
    label = section_label.strip()
    prefix = f"{sid} {label}".strip() if sid else label
    parts = [o.strip() for o in observations if o and o.strip()]
    query = prefix if not parts else f"{prefix}: " + " ".join(parts)
    if settings.text_normalize_enabled:
        from backend.domain.text_normalize import normalize_query

        return normalize_query(query)
    return query


def _content_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}


def rerank_hits_by_observations(
    hits: list[SearchHit],
    observations: list[str],
) -> list[SearchHit]:
    if not hits or not observations:
        return hits
    obs_tokens = _content_tokens(" ".join(observations))
    if not obs_tokens:
        return hits
    boost = settings.retrieval_lexical_boost

    def rank_key(h: SearchHit) -> float:
        para_tokens = _content_tokens(h.text)
        overlap = len(obs_tokens & para_tokens)
        return h.score + overlap * boost

    return sorted(hits, key=rank_key, reverse=True)


def rerank_hits_for_comprehensive_baseline(hits: list[SearchHit]) -> list[SearchHit]:
    """Among similarly scored REFERENCE hits, prefer the longest / fullest text block."""
    if len(hits) < 2:
        return hits
    top_score = hits[0].score
    score_floor = top_score - max(0.06, top_score * 0.08)

    def sort_key(h: SearchHit) -> tuple[float, int, int]:
        return (
            h.score,
            len(h.text.split()),
            -(h.paragraph_index or 0),
        )

    close = [h for h in hits if h.score >= score_floor]
    tail = [h for h in hits if h.score < score_floor]
    close.sort(key=sort_key, reverse=True)
    return close + tail


def _filter_hits_to_section(
    hits: list[SearchHit],
    paragraph_section_id: str,
) -> list[SearchHit]:
    """Keep only chunks tagged with the target section (case-insensitive).

    D–J parent-intro units also keep ``content_role=parent_intro`` hits whose
    ``parent_id`` matches (legacy rows with an empty ``section_id``).
    """
    from backend.rag.store import _meta_matches_section

    want = (paragraph_section_id or "").strip().upper()
    if not want:
        return hits
    return [
        h
        for h in hits
        if _meta_matches_section(
            {
                "section_id": h.section_id,
                "content_role": h.content_role,
                "parent_id": h.parent_id,
            },
            want,
        )
    ]


def _selected_property_type(property_context: dict | None) -> str | None:
    """Canonical ``house``/``flat`` from context, or ``None`` when not scoping."""
    from backend.domain.property_type import try_canonical_property_type

    if not property_context:
        return None
    return try_canonical_property_type(property_context.get("property_type"))


def _filter_hits_by_property_type(
    hits: list[SearchHit],
    property_context: dict | None,
) -> list[SearchHit]:
    """Keep hits whose metadata ``property_type`` exactly matches the selection.

    When a canonical type is selected, untagged and cross-type chunks are
    dropped (no soft fallback). When no canonical type is present, hits are
    unchanged (call sites that omit property scoping).
    """
    selected = _selected_property_type(property_context)
    if selected is None:
        return hits
    return [h for h in hits if (h.property_type or "").strip().lower() == selected]


def build_topic_retrieval_query(
    topic_label: str,
    subtopic_label: str,
    observations: list[str],
) -> str:
    """Content-mode query anchored to a topic + sub-topic label + observations."""
    prefix = " ".join(p for p in (topic_label.strip(), subtopic_label.strip()) if p)
    parts = [o.strip() for o in observations if o and o.strip()]
    query = (
        prefix
        if not parts
        else f"{prefix}: " + " ".join(sorted(parts, key=len, reverse=True)[:5])
    )
    if settings.text_normalize_enabled:
        from backend.domain.text_normalize import normalize_query

        return normalize_query(query)
    return query


def _filter_hits_to_topic(
    hits: list[SearchHit],
    topic_id: str,
    subtopic_id: str = "",
) -> list[SearchHit]:
    """Keep only chunks tagged with the target topic (and sub-topic when given)."""
    want_topic = (topic_id or "").strip()
    if not want_topic:
        return hits
    want_sub = (subtopic_id or "").strip()
    out = [h for h in hits if (getattr(h, "topic_id", "") or "").strip() == want_topic]
    if want_sub:
        out = [h for h in out if (getattr(h, "subtopic_id", "") or "").strip() == want_sub]
    return out


def _selected_property_type(property_context: dict | None) -> str | None:
    """Canonical ``house``/``flat`` from context, or ``None`` when not scoping."""
    from backend.domain.property_type import try_canonical_property_type

    if not property_context:
        return None
    return try_canonical_property_type(property_context.get("property_type"))


def _filter_hits_by_property_type(
    hits: list[SearchHit],
    property_context: dict | None,
) -> list[SearchHit]:
    """Keep hits whose metadata ``property_type`` exactly matches the selection.

    When a canonical type is selected, untagged and cross-type chunks are
    dropped (no soft fallback). When no canonical type is present, hits are
    unchanged (call sites that omit property scoping).
    """
    selected = _selected_property_type(property_context)
    if selected is None:
        return hits
    return [h for h in hits if (h.property_type or "").strip().lower() == selected]


def _complete_section_group(
    tenant_id: str,
    source_key: str | None,
    section_id: str,
    *,
    tier: str | None,
    allowed_doc_keys: frozenset[str] | None,
    property_context: dict | None,
) -> list[SearchHit]:
    """Pull EVERY stored chunk for a section (optionally pinned to one source).

    When ``property_context`` carries a canonical ``property_type``, only chunks
    with that exact metadata value are returned.
    """
    from backend.rag.store import get_rag_store
    from backend.rag.types import TIER_REFERENCE

    use_tier = tier or TIER_REFERENCE
    return get_rag_store().fetch_section_chunks(
        tenant_id,
        tier=use_tier,
        section_id=section_id,
        source_key=source_key,
        allowed_doc_keys=allowed_doc_keys,
        property_type=_selected_property_type(property_context),
    )


def _parent_letter_from_section(section_id: str) -> str:
    sid = (section_id or "").strip().upper()
    return sid[:1] if len(sid) >= 2 else ""


def _fetch_parent_intro_hits(
    tenant_id: str,
    *,
    paragraph_section_id: str,
    best_source: str,
    tier: str | None,
    allowed_doc_keys: frozenset[str] | None,
    property_context: dict | None,
) -> list[SearchHit]:
    parent = _parent_letter_from_section(paragraph_section_id)
    if not parent or not tenant_id:
        return []
    from backend.rag.store import get_rag_store
    from backend.rag.types import TIER_REFERENCE

    use_tier = tier or TIER_REFERENCE
    return get_rag_store().fetch_parent_intro_chunks(
        tenant_id,
        tier=use_tier,
        parent_id=parent,
        source_key=best_source,
        allowed_doc_keys=allowed_doc_keys,
        property_type=_selected_property_type(property_context),
    )


# Each past report that holds this subsection is fed to the prompt as its OWN
# scaffold block — never merged with other reports. How many reports are included
# (highest-ranked first) is controlled by RETRIEVAL_TOP_K (settings.retrieval_top_k),
# so the operator tunes prompt size / cost from the env rather than a hardcoded cap.


@dataclass
class ReferenceSourceBaseline:
    """One past report's version of a subsection, kept separate from other reports.

    ``source_filename`` is retained for provenance/logging only — it is NEVER placed
    in the LLM prompt (a filename can itself be PII, e.g. an address).
    """

    source_filename: str
    text: str
    hits: list["SearchHit"]


def _source_key_of(hit: "SearchHit") -> str:
    return hit.source_filename or hit.doc_id or "unknown"


def _primary_rank_from_group(
    group: list["SearchHit"],
) -> tuple[float, float, float, float, float]:
    """Ranking signals for one past-report source.

    Returns
    ``(primary, max_similarity, max_bm25, max_fusion, max_rerank)`` where
    ``primary`` decides source order: cross-encoder rerank when present, else
    hybrid RRF ``fusion_score``, else dense ``similarity_score``.
    """
    if not group:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    max_rerank = max((h.rerank_score or 0.0) for h in group)
    max_fusion = max((h.fusion_score or 0.0) for h in group)
    max_bm25 = max((getattr(h, "bm25_score", 0.0) or 0.0) for h in group)
    max_similarity = max(
        (
            (getattr(h, "similarity_score", 0.0) or 0.0) or (h.score or 0.0)
            for h in group
        ),
        default=0.0,
    )
    if max_rerank > 0.0:
        primary = max_rerank
    elif max_fusion > 0.0:
        primary = max_fusion
    else:
        primary = max_similarity
    return primary, max_similarity, max_bm25, max_fusion, max_rerank


def _stamp_source_rank_scores(
    targets: list["SearchHit"],
    ranked_group: list["SearchHit"],
) -> None:
    """Copy source-level hybrid component scores onto expanded chunks (in place).

    ``fetch_section_chunks`` assigns a placeholder ``score=1.0`` because ordering
    there is by document position. After expansion, stamp the similarity / BM25 /
    RRF scores that selected this source, and set ``score`` to the primary ranking
    value used for source ordering.
    """
    if not targets or not ranked_group:
        return
    primary, max_sim, max_bm25, max_fusion, max_rerank = _primary_rank_from_group(
        ranked_group
    )
    for hit in targets:
        hit.score = float(primary)
        hit.similarity_score = float(max_sim)
        hit.bm25_score = float(max_bm25)
        hit.fusion_score = float(max_fusion)
        hit.rerank_score = float(max_rerank)


def _source_section_block(
    section_hits: list["SearchHit"], section_id: str
) -> tuple[str, list["SearchHit"]]:
    """Join ONE source's section chunks in document order with formatting preserved.

    No sentence-level merge and no cross-report dedup: each report keeps its own
    paragraphs/headings verbatim. Only exact-duplicate chunk bodies within the same
    source (or a repeated paragraph index) are collapsed. A trailing foreign parent
    banner is trimmed so a leaf block never bleeds into a sibling section.
    """
    from backend.rag.reference_chunker import truncate_at_foreign_parent_banner

    ordered = sorted(
        section_hits,
        key=lambda h: (h.paragraph_index or 0, -len(h.text.split()), -h.score),
    )
    parts: list[str] = []
    contributing: list["SearchHit"] = []
    seen_para: set[tuple[str, int]] = set()
    for hit in ordered:
        body = (hit.text or "").strip()
        if not body:
            continue
        para_idx = hit.paragraph_index or 0
        para_key = (hit.content_role or "body", para_idx)
        if para_idx and para_key in seen_para:
            continue
        if body in parts:
            continue
        if para_idx:
            seen_para.add(para_key)
        parts.append(body)
        contributing.append(hit)
    if not parts:
        return "", []
    combined = "\n\n".join(parts)
    return truncate_at_foreign_parent_banner(combined, section_id), contributing


def assemble_reference_baselines_per_source(
    hits: list["SearchHit"],
    *,
    paragraph_section_id: str = "",
    tenant_id: str | None = None,
    tier: str | None = None,
    allowed_doc_keys: frozenset[str] | None = None,
    property_context: dict | None = None,
    expand: bool = True,
    max_sources: int | None = None,
) -> list[ReferenceSourceBaseline]:
    """One SEPARATE baseline block per past report — never merged across reports.

    Mirrors :func:`assemble_reference_baseline`'s per-source ranking and
    section-complete expansion, but returns EVERY qualifying source (best-first) so
    each report's version of the subsection reaches the prompt as its own scaffold
    instead of collapsing to a single winner. The number of reports included is
    capped by ``max_sources``, which defaults to ``RETRIEVAL_TOP_K``
    (``settings.retrieval_top_k``) when not given.

    ``expand`` re-fetches each source's complete section by metadata; pass ``False``
    when ``hits`` already hold the complete per-source sections (metadata-first path)
    to avoid a redundant scan.
    """
    if not hits:
        return []
    cap = max_sources if max_sources is not None else settings.retrieval_top_k
    sid = (paragraph_section_id or "").upper()
    by_source: dict[str, list[SearchHit]] = {}
    for hit in hits:
        by_source.setdefault(_source_key_of(hit), []).append(hit)

    def source_rank(key: str) -> tuple[float, float, int]:
        group = by_source[key]
        primary, max_similarity, _bm25, _fusion, _rerank = _primary_rank_from_group(
            group
        )
        matched = [
            h for h in group if sid and (h.section_id or "").upper() == sid
        ] or group
        word_count = sum(len(h.text.split()) for h in matched)
        # Length is tie-break only — never outweigh note-similarity.
        return primary, max_similarity, word_count

    blocks: list[ReferenceSourceBaseline] = []
    for key in sorted(by_source, key=source_rank, reverse=True):
        ranked_group = by_source[key]
        group = ranked_group
        if expand and tenant_id and sid and settings.reference_section_complete_enabled:
            complete = _complete_section_group(
                tenant_id,
                key,
                sid,
                tier=tier,
                allowed_doc_keys=allowed_doc_keys,
                property_context=property_context,
            )
            if complete:
                _stamp_source_rank_scores(complete, ranked_group)
                group = complete
        section_hits = _filter_hits_to_section(group, sid)
        if not section_hits:
            continue
        text, contributing = _source_section_block(section_hits, sid)
        if not text.strip():
            continue
        blocks.append(
            ReferenceSourceBaseline(
                source_filename=key, text=text, hits=contributing
            )
        )
        if len(blocks) >= cap:
            break
    return blocks


def assemble_reference_baseline(
    hits: list[SearchHit],
    *,
    paragraph_section_id: str = "",
    tenant_id: str | None = None,
    tier: str | None = None,
    allowed_doc_keys: frozenset[str] | None = None,
    property_context: dict | None = None,
    observations: list[str] | None = None,
) -> tuple[str, list[SearchHit]]:
    """Build the fullest REFERENCE baseline from ranked hits (same doc + section).

    When ``tenant_id`` is supplied and section-complete assembly is enabled, the
    best source is chosen by similarity (as before) but the baseline is then built
    from EVERY chunk that source holds for the section — in document order — rather
    than only the top-K chunks similarity surfaced. This is what makes the whole
    past-report section get mapped instead of a partial fragment. A character budget
    bounds the assembled length so the mapping prompt stays sane.
    """
    from backend.pipeline.paragraph_merge import combine_reference_blocks

    if not hits:
        return "", []

    by_source: dict[str, list[SearchHit]] = {}
    for hit in hits:
        key = hit.source_filename or hit.doc_id or "unknown"
        by_source.setdefault(key, []).append(hit)

    sid = (paragraph_section_id or "").upper()

    def source_rank(key: str) -> tuple[float, int]:
        group = by_source[key]
        # Prefer the reranker's multi-signal verdict; fall back to raw similarity
        # for metadata-only groups (section-complete scans carry no rerank score).
        max_rerank = max((h.rerank_score or 0.0) for h in group)
        primary = max_rerank if max_rerank > 0.0 else max(h.score for h in group)
        matched = _filter_hits_to_section(group, sid) or group
        word_count = sum(len(h.text.split()) for h in matched)
        return primary + min(word_count / 400.0, 0.2), word_count

    best_source = max(by_source, key=source_rank)
    ranked_group = by_source[best_source]
    group = ranked_group

    # Section-complete expansion: replace the top-K group with the chosen source's
    # ENTIRE section so no paragraph the surveyor expects is left unmapped.
    section_complete = False
    if tenant_id and sid and settings.reference_section_complete_enabled:
        complete = _complete_section_group(
            tenant_id,
            best_source,
            sid,
            tier=tier,
            allowed_doc_keys=allowed_doc_keys,
            property_context=property_context,
        )
        if complete:
            _stamp_source_rank_scores(complete, ranked_group)
            group = complete
            section_complete = True

    section_hits = _filter_hits_to_section(group, sid)
    if not section_hits:
        return "", []

    # Parent-group intros are stored as separate chunks at ingest. Leaf baselines
    # (D1, E2, …) never prepend them — no env toggle; product rule is leaf-only.
    parent_intro_hits: list[SearchHit] = []

    section_hits.sort(
        key=lambda h: (h.paragraph_index or 0, -len(h.text.split()), -h.score),
    )

    # Only the expanded path is char-budgeted; the bounded top-K path is untouched.
    budget = settings.reference_section_complete_max_chars if section_complete else None
    # Relevance-aware compression keeps the highest note-overlap sentences within
    # budget rather than positionally tail-cutting. When enabled we must collect the
    # whole section first (no early break), then compress the combined prose.
    compress = (
        budget is not None
        and settings.context_compression_enabled
        and bool(observations)
    )
    texts: list[str] = []
    contributing: list[SearchHit] = []
    seen_para: set[tuple[str, int]] = set()
    used = 0
    for hit in parent_intro_hits + section_hits:
        para_idx = hit.paragraph_index or 0
        para_key = (hit.content_role or "body", para_idx)
        if para_idx and para_key in seen_para:
            continue
        body = hit.text.strip()
        if not body:
            continue
        if not compress and budget is not None and texts and used + len(body) > budget:
            break
        if para_idx:
            seen_para.add(para_key)
        if body not in texts:
            texts.append(body)
            contributing.append(hit)
            used += len(body)

    if not texts:
        best = max(section_hits, key=lambda h: (h.score, len(h.text.split())))
        return best.text.strip(), [best]

    from backend.rag.reference_chunker import truncate_at_foreign_parent_banner

    combined = combine_reference_blocks(texts[0], texts[1:])
    if compress and budget is not None and len(combined) > budget:
        from backend.pipeline.paragraph_merge import _content_tokens, compress_to_budget

        note_terms = _content_tokens(" ".join(observations or []))
        combined = compress_to_budget(combined, note_terms, budget)
    baseline = truncate_at_foreign_parent_banner(combined, sid)
    return baseline, contributing


def fetch_complete_section_baseline(
    tenant_id: str,
    *,
    paragraph_section_id: str,
    tier: str | None = None,
    allowed_doc_keys: frozenset[str] | None = None,
    property_context: dict | None = None,
    observations: list[str] | None = None,
) -> tuple[str, list[SearchHit]]:
    """Metadata-only baseline for a section (no similarity query).

    Fallback for when similarity search surfaced nothing for a section that
    nonetheless exists in the index (weak query match, alias drift). Returns the
    fullest single-source section, or ``("", [])`` when the section is genuinely
    absent — in which case the caller correctly degrades to a notes-only section.
    """
    if not settings.reference_section_complete_enabled:
        return "", []
    chunks = _complete_section_group(
        tenant_id,
        None,
        paragraph_section_id,
        tier=tier,
        allowed_doc_keys=allowed_doc_keys,
        property_context=property_context,
    )
    if not chunks:
        return "", []
    return assemble_reference_baseline(
        chunks,
        paragraph_section_id=paragraph_section_id,
        tenant_id=tenant_id,
        tier=tier,
        allowed_doc_keys=allowed_doc_keys,
        property_context=property_context,
        observations=observations,
    )


def fetch_complete_section_baselines_per_source(
    tenant_id: str,
    *,
    paragraph_section_id: str,
    tier: str | None = None,
    allowed_doc_keys: frozenset[str] | None = None,
    property_context: dict | None = None,
    max_sources: int | None = None,
) -> list[ReferenceSourceBaseline]:
    """Metadata-only per-source section baselines (no similarity query).

    Every uploaded report that holds this exact subsection is returned as its own
    separate block, best-first, up to ``max_sources`` (defaults to ``RETRIEVAL_TOP_K``).
    The chunks are already complete per source, so the per-source assembler runs with
    ``expand=False`` to skip a redundant scan.
    """
    if not settings.reference_section_complete_enabled:
        return []
    chunks = _complete_section_group(
        tenant_id,
        None,
        paragraph_section_id,
        tier=tier,
        allowed_doc_keys=allowed_doc_keys,
        property_context=property_context,
    )
    if not chunks:
        return []
    return assemble_reference_baselines_per_source(
        chunks,
        paragraph_section_id=paragraph_section_id,
        tenant_id=tenant_id,
        tier=tier,
        allowed_doc_keys=allowed_doc_keys,
        property_context=property_context,
        expand=False,
        max_sources=max_sources,
    )


def _uses_reference_tier(interference_level: InterferenceLevel) -> bool:
    return interference_level in ("minimum", "medium", "maximum")


def _retrieval_params(
    retrieval_level: RetrievalLevel,
    *,
    paragraph_section_id: str,
    k: int,
) -> tuple[bool, int]:
    level = (retrieval_level or "paragraph").lower()
    if level == "section":
        return bool(paragraph_section_id), max(k, 8)
    if level == "document":
        return bool(paragraph_section_id), max(k, 15)
    return bool(paragraph_section_id), k


def _focus_document_hits(hits: list[SearchHit], k: int) -> list[SearchHit]:
    """Prefer chunks from the single best-matching past report."""
    if not hits:
        return hits
    by_source: dict[str, list[SearchHit]] = {}
    for hit in hits:
        key = hit.source_filename or hit.doc_id or "unknown"
        by_source.setdefault(key, []).append(hit)
    best_key = max(by_source, key=lambda name: max(h.score for h in by_source[name]))
    focused = sorted(by_source[best_key], key=lambda h: h.score, reverse=True)
    return focused[:k]


def _search_tier(
    tenant_id: str,
    query: str,
    *,
    paragraph_section_id: str,
    k: int,
    interference_level: InterferenceLevel,
    retrieval_level: RetrievalLevel = "paragraph",
    allowed_doc_keys: frozenset[str] | None = None,
    property_type: str | None = None,
) -> list[SearchHit]:
    store = get_rag_store()
    if _uses_reference_tier(interference_level):
        search = store.search_for_reference_mapping
    else:
        search = store.search_for_generation

    strict, fetch_k = _retrieval_params(
        retrieval_level,
        paragraph_section_id=paragraph_section_id,
        k=k,
    )
    search_kwargs: dict = {
        "section_id": paragraph_section_id or None,
    }
    if _uses_reference_tier(interference_level):
        search_kwargs["allowed_doc_keys"] = allowed_doc_keys
        search_kwargs["property_type"] = property_type
    # Never widen to cross-section retrieval — empty is safer than wrong-section bleed.
    use_strict = strict or bool(paragraph_section_id)
    hits = search(
        tenant_id,
        query,
        top_k=max(fetch_k * 3, fetch_k),
        section_strict=use_strict,
        **search_kwargs,
    )
    hits = _filter_hits_to_section(hits, paragraph_section_id)
    if (retrieval_level or "paragraph").lower() == "document":
        hits = _focus_document_hits(hits, fetch_k)
    return hits


def retrieve_paragraphs_for_mapping(
    tenant_id: str,
    *,
    section_label: str,
    paragraph_section_id: str,
    observations: list[str],
    interference_level: InterferenceLevel = "minimum",
    retrieval_level: RetrievalLevel = "paragraph",
    top_k: int | None = None,
    allowed_doc_keys: frozenset[str] | None = None,
    property_context: dict | None = None,
) -> list[SearchHit]:
    """Ranked paragraphs from uploaded past reports for all interference levels.

    When ``property_context`` carries a canonical ``property_type``, retrieval is
    scoped to ``section_id ∩ property_type`` (untagged / other types excluded).
    """
    k = top_k or settings.reference_baseline_top_k
    if interference_level == "medium":
        k = max(k, settings.reference_baseline_top_k)
    elif interference_level == "maximum":
        k = max(k, settings.reference_baseline_top_k + 2)
    query = build_retrieval_query(
        section_label,
        observations,
        section_id=paragraph_section_id,
    )
    selected_pt = _selected_property_type(property_context)

    def _retrieve(fetch_k: int) -> list[SearchHit]:
        hits = _search_tier(
            tenant_id,
            query,
            paragraph_section_id=paragraph_section_id,
            k=fetch_k,
            interference_level=interference_level,
            retrieval_level=retrieval_level,
            allowed_doc_keys=allowed_doc_keys,
            property_type=selected_pt,
        )
        return _filter_hits_by_property_type(hits, property_context)

    # One hybrid retrieval pass (dense FAISS + sparse BM25, RRF-fused), scoped to
    # the target section. The pool is sized to the cross-encoder shortlist so
    # jina-reranker-v3 has the full candidate set to reorder before we trim to k.
    fetch_k = max(k, settings.reference_cross_encoder_top_n)
    with observability.span(
        "retrieve",
        section_id=paragraph_section_id,
        interference=interference_level,
        retrieval_level=retrieval_level,
    ):
        best = _retrieve(fetch_k)

    # Audit hook: dump the hybrid (embedder + BM25) shortlist exactly as retrieved,
    # BEFORE the reranker reorders it. No-op unless RETRIEVAL_DEBUG_DUMP is set.
    from backend.rag import retrieval_debug

    retrieval_debug.dump_pre_rerank(
        tenant_id=tenant_id,
        query=query,
        section_id=paragraph_section_id,
        section_label=section_label,
        interference_level=str(interference_level),
        retrieval_level=str(retrieval_level),
        hits=best,
        rerank_top_n=max(2, settings.reference_cross_encoder_top_n),
        final_top_k=k,
    )

    # jina-reranker-v3 re-scores the shortlist jointly against the query so the
    # genuine best match wins — not merely the closest embedding. When the
    # reranker is disabled or its weights are unavailable this is a no-op and the
    # raw hybrid (FAISS + BM25) order is returned.
    if settings.reference_cross_encoder_enabled and len(best) >= 2:
        with observability.span(
            "rerank", section_id=paragraph_section_id, candidates=len(best)
        ):
            best = cross_encoder_rerank(query, best)
    return best[:k]


def retrieve_past_report_baselines_hybrid(
    tenant_id: str,
    *,
    section_label: str,
    paragraph_section_id: str,
    observations: list[str],
    tier: str | None = None,
    allowed_doc_keys: frozenset[str] | None = None,
    property_context: dict | None = None,
    max_sources: int | None = None,
) -> tuple[list[ReferenceSourceBaseline], list[SearchHit]]:
    """SP-style past-report retrieve: filter → hybrid similarity → top-K sources.

    1. Restrict FAISS meta to ``section_id`` ∩ optional ``property_type`` / allowlist.
    2. Rank that pool with dense cosine + BM25 (RRF) against the inspection notes.
    3. Collapse to one full subsection scaffold per past report, best-first, capped
       by ``max_sources`` (defaults to ``RETRIEVAL_TOP_K``).

    Returns ``(source_blocks, ranking_hits)``. Empty when nothing matches the filter.
    """
    from backend.rag.types import TIER_REFERENCE

    sid = (paragraph_section_id or "").strip()
    if not sid:
        return [], []
    use_tier = tier or TIER_REFERENCE
    selected_pt = _selected_property_type(property_context)
    cap = max_sources if max_sources is not None else settings.retrieval_top_k
    query = build_retrieval_query(
        section_label,
        observations,
        section_id=sid,
    )
    if not (query or "").strip():
        return [], []

    # Wide chunk pool so many reports can compete before the per-source cap.
    pool_k = max(int(cap) * 8, 40)
    store = get_rag_store()
    with observability.span(
        "retrieve_past_hybrid",
        section_id=sid,
        property_type=selected_pt or "",
        max_sources=cap,
    ):
        hits = store.search_section_scoped_hybrid(
            tenant_id,
            query,
            tier=use_tier,
            section_id=sid,
            top_k=pool_k,
            property_type=selected_pt,
            allowed_doc_keys=allowed_doc_keys,
        )
    hits = _filter_hits_by_property_type(hits, property_context)
    if not hits:
        return [], []

    blocks = assemble_reference_baselines_per_source(
        hits,
        paragraph_section_id=sid,
        tenant_id=tenant_id,
        tier=use_tier,
        allowed_doc_keys=allowed_doc_keys,
        property_context=property_context,
        expand=True,
        max_sources=cap,
    )
    return blocks, hits


def find_paragraph_by_topic(
    tenant_id: str,
    observations: list[str],
    *,
    interference_level: InterferenceLevel = "minimum",
    top_k: int = 3,
    allowed_doc_keys: frozenset[str] | None = None,
    paragraph_section_id: str = "",
) -> list[SearchHit]:
    """Topic search scoped to ``paragraph_section_id`` when provided."""
    parts = [o.strip() for o in observations if o and o.strip()]
    if not parts:
        return []
    query = " ".join(parts)
    store = get_rag_store()
    sid = (paragraph_section_id or "").strip() or None
    use_strict = bool(sid)
    if _uses_reference_tier(interference_level):
        hits = store.search_for_reference_mapping(
            tenant_id,
            query,
            section_id=sid,
            top_k=max(top_k * 5, top_k),
            section_strict=use_strict,
            allowed_doc_keys=allowed_doc_keys,
        )
    else:
        hits = store.search_for_generation(
            tenant_id,
            query,
            section_id=sid,
            top_k=max(top_k * 5, top_k),
            section_strict=use_strict,
        )
    hits = _filter_hits_to_section(hits, paragraph_section_id)
    ranked = rerank_hits_by_observations(hits, parts)
    return rerank_hits_for_comprehensive_baseline(ranked)[:top_k]


def report_section_for_paragraph_id(
    schema: TemplateSchema,
    paragraph_section_id: str,
) -> str | None:
    if not paragraph_section_id:
        return None
    for report_id, para_id in schema.section_alias_map.items():
        if para_id == paragraph_section_id:
            return report_id
    if schema.get_section(paragraph_section_id):
        return paragraph_section_id
    return None


def guess_report_section_from_topic(
    schema: TemplateSchema,
    observations: list[str],
    reference_text: str = "",
) -> str | None:
    """Best-effort section when REFERENCE chunks lack section_id metadata."""
    corpus = " ".join(observations) + " " + reference_text
    words = _content_tokens(corpus)
    if not words:
        return None

    best_id: str | None = None
    best_score = 0
    for sec in schema.ordered_sections():
        title_words = _content_tokens(f"{sec.id} {sec.title}")
        overlap = len(words & title_words)
        if overlap > best_score:
            best_score = overlap
            best_id = sec.id
    return best_id if best_score > 0 else None


# Backward-compatible alias — always searches MASTER tier.
def retrieve_master_paragraphs(
    tenant_id: str,
    *,
    section_label: str,
    paragraph_section_id: str,
    observations: list[str],
    top_k: int | None = None,
) -> list[SearchHit]:
    k = top_k or settings.retrieval_top_k
    query = build_retrieval_query(
        section_label,
        observations,
        section_id=paragraph_section_id,
    )
    store = get_rag_store()
    hits = store.search_for_generation(
        tenant_id,
        query,
        section_id=paragraph_section_id or None,
        top_k=max(k * 3, k),
        section_strict=bool(paragraph_section_id),
    )
    hits = _filter_hits_to_section(hits, paragraph_section_id)
    hits = rerank_hits_by_observations(hits, observations)
    hits = rerank_hits_for_comprehensive_baseline(hits)
    return hits[:k]
