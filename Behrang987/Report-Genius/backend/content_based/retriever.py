"""Topic-scoped retrieval for the content-based report mode.

Thin wrapper over the shared RAG store: retrieve past-report (REFERENCE) or
standard-paragraph baselines filtered by content ``topic_id`` / ``subtopic_id``
instead of RICS ``section_id``, reusing the existing hybrid search + rerankers.
"""

from __future__ import annotations

import logging

from backend.config import settings
from backend.content_based import taxonomy
from backend.rag.retriever import (
    _filter_hits_to_topic,
    build_topic_retrieval_query,
    rerank_hits_by_observations,
)
from backend.rag.store import get_rag_store
from backend.rag.types import TIER_REFERENCE, SearchHit

logger = logging.getLogger(__name__)


def retrieve_topic_hits(
    tenant_id: str,
    *,
    tier: str,
    topic_id: str,
    subtopic_id: str = "",
    observations: list[str] | None = None,
    top_k: int = 5,
    property_type: str | None = None,
    allowed_doc_keys: frozenset[str] | None = None,
    rerank: bool = True,
    require_theme_tags: frozenset[str] | None = None,
) -> list[SearchHit]:
    """Retrieve topic-scoped baselines for one topic/sub-topic.

    Tries sub-topic scope first (when given), then widens to the whole topic so a
    sparsely-populated sub-topic still gets stylistic scaffolding from its topic.

    Themes present in the surveyor's own observations are used to prefer baselines
    that discuss the same theme, so a damp note pulls damp prose rather than the
    element's generic description. ``require_theme_tags`` turns that into a hard
    filter for callers that want one theme only.
    """
    obs = [o for o in (observations or []) if o and o.strip()]
    query = build_topic_retrieval_query(
        taxonomy.topic_label(topic_id),
        taxonomy.subtopic_label(topic_id, subtopic_id) if subtopic_id else "",
        obs,
    )
    store = get_rag_store()
    prefer_tags = frozenset(taxonomy.theme_tags_for_text(" ".join(obs))) if obs else None

    hits: list[SearchHit] = []
    if subtopic_id:
        hits = store.search_topic_scoped_hybrid(
            tenant_id,
            query,
            tier=tier,
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            top_k=top_k,
            property_type=property_type,
            allowed_doc_keys=allowed_doc_keys,
            require_theme_tags=require_theme_tags,
            boost_theme_tags=prefer_tags,
        )
    if not hits:
        hits = store.search_topic_scoped_hybrid(
            tenant_id,
            query,
            tier=tier,
            topic_id=topic_id,
            subtopic_id=None,
            top_k=top_k,
            property_type=property_type,
            allowed_doc_keys=allowed_doc_keys,
            require_theme_tags=require_theme_tags,
            boost_theme_tags=prefer_tags,
        )

    hits = _filter_hits_to_topic(hits, topic_id)
    if rerank and obs and hits:
        hits = rerank_hits_by_observations(hits, obs)
        if (
            tier == TIER_REFERENCE
            and settings.reference_cross_encoder_enabled
            and len(hits) >= 2
        ):
            from backend.llm.reranker import cross_encoder_rerank

            hits = cross_encoder_rerank(query, hits)
    return hits[: max(1, int(top_k))]


def fetch_topic_baseline(
    tenant_id: str,
    *,
    tier: str,
    topic_id: str,
    subtopic_id: str = "",
    property_type: str | None = None,
    allowed_doc_keys: frozenset[str] | None = None,
) -> list[SearchHit]:
    """Every stored chunk for a topic/sub-topic in document order (metadata scan)."""
    store = get_rag_store()
    return store.fetch_topic_chunks(
        tenant_id,
        tier=tier,
        topic_id=topic_id,
        subtopic_id=subtopic_id or None,
        property_type=property_type,
        allowed_doc_keys=allowed_doc_keys,
    )
