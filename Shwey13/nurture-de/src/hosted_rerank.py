"""Phase-13 (thin slice) — the ONE production swap: the cross-encoder reranker.

On the local box, `bge-reranker-v2-m3` reranks the 100-candidate pool on CPU and that is 86–89 %
of query latency (measured, Phase 11) — genuinely unusable for a stranger. This offloads *only*
the reranker to a hosted API, behind the exact interface the local `retrieval.Reranker` exposes
(`.rerank(query, hits) -> hits`), so the graph is unchanged. Everything else (E5 query embedding,
Chroma, BM25) still runs in-container.

Provider: Jina (`jina-reranker-v2-base-multilingual`) by default — a multilingual cross-encoder in
the same family as bge, chosen because it's the best bet the EN→DE cross-lingual ranking reproduces
(the headline finding). Cohere is the fallback if the verification cases don't reproduce; switch
with RERANK_PROVIDER=cohere. Keys come from env (HF Spaces secrets), never from code.

    from hosted_rerank import make_reranker
    r = make_reranker()          # HostedReranker if a key is set, else the local bge Reranker
    reranked = r.rerank(query, hits)   # hits: objects with .text; returns them reordered, best first
"""
from __future__ import annotations

import os
from typing import Any

import httpx

JINA_URL = "https://api.jina.ai/v1/rerank"
JINA_MODEL = "jina-reranker-v2-base-multilingual"
COHERE_URL = "https://api.cohere.com/v2/rerank"
COHERE_MODEL = "rerank-v3.5"
_TIMEOUT = 30.0


class HostedReranker:
    """Reorders (query, passage) hits via a hosted cross-encoder. Same surface as
    `retrieval.Reranker`: `.rerank(query, hits) -> hits` (best first). Reads its key from env."""

    def __init__(self, provider: str | None = None, top_n: int | None = None):
        self.provider = (provider or os.getenv("RERANK_PROVIDER") or "jina").lower()
        self.top_n = top_n
        if self.provider == "jina":
            self.key = os.getenv("JINA_API_KEY")
            self.url, self.model = JINA_URL, JINA_MODEL
        elif self.provider == "cohere":
            self.key = os.getenv("COHERE_API_KEY")
            self.url, self.model = COHERE_URL, COHERE_MODEL
        else:
            raise ValueError(f"unknown RERANK_PROVIDER {self.provider!r} (jina|cohere)")
        if not self.key:
            raise RuntimeError(
                f"{self.provider} reranker selected but its API key env var is unset "
                f"({'JINA_API_KEY' if self.provider == 'jina' else 'COHERE_API_KEY'})")

    def rerank(self, query: str, hits: list) -> list:
        if not hits:
            return hits
        docs = [h.text for h in hits]
        top_n = self.top_n or len(hits)
        payload = {"model": self.model, "query": query, "documents": docs, "top_n": top_n}
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        resp = httpx.post(self.url, json=payload, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        results = resp.json()["results"]        # both APIs: [{index, relevance_score}, ...] desc
        order = [r["index"] for r in results]
        # results are already sorted best-first; map back to the original hit objects
        return [hits[i] for i in order]


def make_reranker(prefer_hosted: bool = True) -> Any:
    """Return a HostedReranker when a hosted key is configured, else the local bge Reranker.
    Lets the same code run locally (no key → local model) and on the Space (key → hosted)."""
    if prefer_hosted and (os.getenv("JINA_API_KEY") or os.getenv("COHERE_API_KEY")):
        return HostedReranker()
    from retrieval import Reranker
    return Reranker()
