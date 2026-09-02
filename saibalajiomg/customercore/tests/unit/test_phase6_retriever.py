"""
tests/unit/test_phase6_retriever.py

Phase 6: Multi-Tenant Vector DB Security + Hybrid Retrieval — Full Test Suite

Tests:
  1. TenantBM25Index        — basic indexing and search
  2. BM25 Tenant Isolation  — Tenant A cannot get Tenant B's results
  3. RRF Fusion             — merging dense + sparse lists correctly
  4. HybridRetriever        — end-to-end BM25-only retrieval (no ChromaDB dependency)
  5. Retriever Isolation    — cross-tenant search returns only own tenant docs
  6. Score ordering         — highest RRF scores first
  7. Empty corpus           — search on empty index returns empty list
  8. Idempotent indexing    — duplicate tickets don't double-count
  9. doc_count()            — accurate per-tenant document counting
 10. Single result          — k=1 returns exactly 1 result
"""

import pytest
from src.rag.hybrid_retriever import (
    HybridRetriever,
    TenantBM25Index,
    RetrievedDoc,
    reciprocal_rank_fusion,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def bm25():
    return TenantBM25Index()


@pytest.fixture
def retriever():
    """HybridRetriever without ChromaDB — uses BM25-only sparse retrieval."""
    return HybridRetriever(chroma_client=None, embedding_fn=None)


def _index_tenant_a(r: HybridRetriever):
    tickets = [
        ("TKT-A001", "Checkout API is returning 500 errors on every request"),
        ("TKT-A002", "March billing invoice shows wrong amount double charged"),
        ("TKT-A003", "Login page is completely broken after your latest deploy"),
        ("TKT-A004", "Need to update our payment method card on file"),
        ("TKT-A005", "Admin dashboard is inaccessible for our entire team"),
        ("TKT-A006", "API rate limits are too restrictive for our integration"),
        ("TKT-A007", "Webhook events stopped firing two hours ago"),
    ]
    for tid, text in tickets:
        r.index_ticket("acme-corp", tid, text, {"category": "technical"})


def _index_tenant_b(r: HybridRetriever):
    tickets = [
        ("TKT-B001", "CONFIDENTIAL: EU cluster latency spike affecting prod"),
        ("TKT-B002", "CONFIDENTIAL: Overcharged by $2400 on last billing cycle"),
        ("TKT-B003", "CONFIDENTIAL: Globex internal data export failing timeout"),
    ]
    for tid, text in tickets:
        r.index_ticket("globex-inc", tid, text, {"category": "technical"})


# ── 1. TenantBM25Index: Basic Indexing ────────────────────────────────────────

class TestBM25Index:
    def test_add_and_search(self, bm25):
        bm25.add_document("acme", "DOC1", "checkout payment error billing", {})
        results = bm25.search("acme", "billing payment", k=5)
        assert len(results) >= 1
        assert results[0].doc_id == "DOC1"

    def test_no_results_on_empty(self, bm25):
        results = bm25.search("empty-tenant", "anything", k=5)
        assert results == []

    def test_unrelated_doc_does_not_appear_from_other_tenant(self, bm25):
        """An unrelated doc in a DIFFERENT tenant must never appear in Tenant A's results."""
        bm25.add_document("acme", "DOC-RELEVANT", "checkout API payment error critical", {})
        bm25.add_document("other-tenant", "DOC-UNRELATED", "weather today is sunny and warm", {})
        results = bm25.search("acme", "checkout API error", k=5)
        result_ids = {r.doc_id for r in results}
        assert "DOC-UNRELATED" not in result_ids, "Cross-tenant document appeared in results!"


    def test_document_count(self, bm25):
        bm25.add_document("t1", "D1", "hello world", {})
        bm25.add_document("t1", "D2", "goodbye world", {})
        bm25.add_document("t2", "D3", "foo bar baz", {})
        assert bm25.document_count("t1") == 2
        assert bm25.document_count("t2") == 1
        assert bm25.document_count() == 3


# ── 2. BM25 Tenant Isolation ──────────────────────────────────────────────────

class TestBM25Isolation:
    def test_tenant_a_cannot_see_tenant_b_docs(self, bm25):
        bm25.add_document("acme", "ACME-1", "billing refund checkout", {})
        bm25.add_document("globex", "GLOBEX-SECRET", "billing refund checkout globex secret", {})

        results_a = bm25.search("acme", "billing refund checkout", k=10)
        result_ids = [r.doc_id for r in results_a]
        assert "GLOBEX-SECRET" not in result_ids, "Cross-tenant data LEAKED into Tenant A's results!"

    def test_tenant_b_cannot_see_tenant_a_docs(self, bm25):
        bm25.add_document("acme", "ACME-SECRET", "acme internal confidential data", {})
        bm25.add_document("globex", "GLOBEX-1", "some globex ticket", {})

        results_b = bm25.search("globex", "acme internal confidential data", k=10)
        result_ids = [r.doc_id for r in results_b]
        assert "ACME-SECRET" not in result_ids, "Cross-tenant data LEAKED into Tenant B's results!"

    def test_different_tenants_same_query_different_results(self, bm25):
        bm25.add_document("t-alpha", "ALPHA-1", "payment failed critical issue", {})
        bm25.add_document("t-beta", "BETA-1", "payment failed outage severe", {})

        r_alpha = bm25.search("t-alpha", "payment failed", k=5)
        r_beta = bm25.search("t-beta", "payment failed", k=5)

        ids_alpha = {r.doc_id for r in r_alpha}
        ids_beta = {r.doc_id for r in r_beta}

        assert "ALPHA-1" in ids_alpha
        assert "BETA-1" in ids_beta
        assert ids_alpha.isdisjoint(ids_beta), "Tenants share document IDs — isolation broken!"

    def test_tenant_id_recorded_in_results(self, bm25):
        bm25.add_document("my-tenant", "DOC-X", "test document content", {"ticket_id": "TKT-X"})
        results = bm25.search("my-tenant", "test document", k=1)
        assert results[0].tenant_id == "my-tenant"


# ── 3. Reciprocal Rank Fusion ─────────────────────────────────────────────────

class TestRRF:
    def _make_docs(self, ids: list[str], source: str) -> list[RetrievedDoc]:
        return [
            RetrievedDoc(doc_id=did, text=f"text for {did}", tenant_id="t",
                         score=1.0 / (i + 1), source=source)
            for i, did in enumerate(ids)
        ]

    def test_rrf_combines_both_lists(self):
        dense = self._make_docs(["D1", "D2", "D3"], "dense")
        sparse = self._make_docs(["S1", "D2", "S3"], "sparse")
        fused = reciprocal_rank_fusion(dense, sparse)
        fused_ids = [d.doc_id for d in fused]
        # D2 appears in both lists — should rank higher than D1 (dense-only)
        assert "D2" in fused_ids
        assert "D1" in fused_ids
        assert "S1" in fused_ids

    def test_shared_doc_scores_higher(self):
        """D2 is in both dense and sparse lists — must beat D1 which is only in dense."""
        dense = self._make_docs(["D1", "D2", "D3"], "dense")
        sparse = self._make_docs(["D2", "S2", "S3"], "sparse")
        fused = reciprocal_rank_fusion(dense, sparse)
        # D2 at rank 2 dense + rank 1 sparse should outscore D1 at rank 1 dense only
        d2_score = next(d.score for d in fused if d.doc_id == "D2")
        d1_score = next(d.score for d in fused if d.doc_id == "D1")
        assert d2_score > d1_score

    def test_empty_lists(self):
        assert reciprocal_rank_fusion([], []) == []

    def test_one_empty_list(self):
        dense = self._make_docs(["D1", "D2"], "dense")
        fused = reciprocal_rank_fusion(dense, [])
        assert len(fused) == 2
        fused_ids = {d.doc_id for d in fused}
        assert fused_ids == {"D1", "D2"}

    def test_scores_are_positive(self):
        dense = self._make_docs(["A", "B", "C"], "dense")
        sparse = self._make_docs(["B", "C", "D"], "sparse")
        fused = reciprocal_rank_fusion(dense, sparse)
        for doc in fused:
            assert doc.score > 0


# ── 4. HybridRetriever: End-to-End ────────────────────────────────────────────

class TestHybridRetriever:
    def test_basic_search_returns_results(self, retriever):
        retriever.index_ticket("acme-corp", "TKT-001", "API 500 error on checkout", {})
        results = retriever.search("acme-corp", "checkout error", k=3)
        assert len(results) >= 1

    def test_results_are_sorted_by_score(self, retriever):
        for i in range(5):
            retriever.index_ticket("acme-corp", f"TKT-SORT-{i}",
                                   f"billing billing billing issue {i}", {})
        results = retriever.search("acme-corp", "billing issue", k=5)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True), "Results must be sorted by score descending"

    def test_k_limits_results(self, retriever):
        _index_tenant_a(retriever)
        results = retriever.search("acme-corp", "API error billing", k=3)
        assert len(results) <= 3

    def test_k1_returns_exactly_one(self, retriever):
        _index_tenant_a(retriever)
        results = retriever.search("acme-corp", "checkout error", k=1)
        assert len(results) == 1


# ── 5. Cross-Tenant Isolation in HybridRetriever ──────────────────────────────

class TestHybridRetrieverIsolation:
    def test_acme_cannot_see_globex_results(self, retriever):
        _index_tenant_a(retriever)
        _index_tenant_b(retriever)

        results = retriever.search("acme-corp", "confidential globex billing latency", k=10)
        tenant_ids = {r.tenant_id for r in results}
        assert "globex-inc" not in tenant_ids, \
            f"SECURITY BREACH: globex-inc data leaked to acme-corp! Results: {[r.ticket_id for r in results]}"

    def test_globex_cannot_see_acme_results(self, retriever):
        _index_tenant_a(retriever)
        _index_tenant_b(retriever)

        results = retriever.search("globex-inc", "checkout API admin dashboard payment", k=10)
        tenant_ids = {r.tenant_id for r in results}
        assert "acme-corp" not in tenant_ids, \
            f"SECURITY BREACH: acme-corp data leaked to globex-inc! Results: {[r.ticket_id for r in results]}"

    def test_all_results_belong_to_queried_tenant(self, retriever):
        _index_tenant_a(retriever)
        _index_tenant_b(retriever)

        for tenant in ["acme-corp", "globex-inc"]:
            results = retriever.search(tenant, "billing error API", k=10)
            for doc in results:
                assert doc.tenant_id == tenant, \
                    f"ISOLATION FAILURE: expected tenant={tenant}, got {doc.tenant_id}"


# ── 6. doc_count() ────────────────────────────────────────────────────────────

class TestDocCount:
    def test_count_per_tenant(self, retriever):
        _index_tenant_a(retriever)  # 7 tickets
        _index_tenant_b(retriever)  # 3 tickets
        assert retriever.doc_count("acme-corp") == 7
        assert retriever.doc_count("globex-inc") == 3
        assert retriever.doc_count() == 10

    def test_empty_tenant_count(self, retriever):
        assert retriever.doc_count("nonexistent-tenant") == 0


# ── 7. Idempotent Indexing ────────────────────────────────────────────────────

class TestIdempotentIndexing:
    def test_duplicate_ticket_not_double_indexed(self, retriever):
        retriever.index_ticket("acme-corp", "TKT-IDEM", "duplicate ticket text", {})
        retriever.index_ticket("acme-corp", "TKT-IDEM", "duplicate ticket text", {})
        assert retriever.doc_count("acme-corp") == 1

    def test_different_ticket_ids_both_indexed(self, retriever):
        retriever.index_ticket("acme-corp", "TKT-X1", "first ticket different content", {})
        retriever.index_ticket("acme-corp", "TKT-X2", "second ticket different content", {})
        assert retriever.doc_count("acme-corp") == 2


# ── 8. Empty Index Search ─────────────────────────────────────────────────────

class TestEmptyIndex:
    def test_search_empty_returns_empty_list(self, retriever):
        results = retriever.search("fresh-tenant", "any query at all", k=5)
        assert results == []
        assert isinstance(results, list)
