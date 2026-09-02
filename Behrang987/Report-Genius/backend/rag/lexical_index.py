"""Sparse lexical retrieval (BM25) and rank fusion for hybrid RAG.

The vector store provides the *dense* arm of retrieval. This module provides the
*sparse* arm — a self-contained BM25-Okabe scorer over the same corpus — plus a
Reciprocal Rank Fusion (RRF) helper to merge the two ranked lists. Fusing dense
and sparse candidates at *retrieval* time (not just rerank time) is what makes
the pipeline genuinely hybrid: a chunk that is a strong lexical match but a weak
embedding match (e.g. a rare RICS term, a measurement, a section code) still
enters the candidate pool instead of being silently dropped before reranking.

Implemented in-house (no ``rank_bm25`` dependency) so tokenisation stays aligned
with the rest of the pipeline and the scorer can be unit-tested deterministically.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

__all__ = ["tokenize", "BM25Index", "reciprocal_rank_fusion"]

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Minimal, high-frequency English stop set. BM25's IDF already discounts common
# terms, so this only trims obvious noise; it is intentionally small to avoid
# dropping domain tokens (e.g. "wc", "rcd", "no" as in "no damp").
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "and",
        "or",
        "to",
        "in",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "for",
        "with",
        "on",
        "at",
        "by",
        "as",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "from",
        "we",
    }
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens with stopwords removed (term order kept).

    Numbers and short codes are preserved (measurements and section identifiers
    such as ``e2`` / ``150`` carry signal in survey text). Duplicates are kept so
    BM25 term frequencies are accurate.
    """
    if not text:
        return []
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


class BM25Index:
    """BM25-Okapi over a fixed corpus of pre-tokenised documents.

    Scores are computed with a non-negative IDF variant so that fusion never has
    to reason about negative contributions. The index is immutable; rebuild it
    when the underlying corpus changes (the vector store keys this off the meta
    length).
    """

    def __init__(
        self, corpus_tokens: list[list[str]], *, k1: float = 1.5, b: float = 0.75
    ) -> None:
        self._k1 = float(k1)
        self._b = float(b)
        self._n = len(corpus_tokens)
        self._doc_len = [len(d) for d in corpus_tokens]
        self._avgdl = (sum(self._doc_len) / self._n) if self._n else 0.0

        # term -> list of (doc_index, term_frequency)
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        df: dict[str, int] = defaultdict(int)
        for i, doc in enumerate(corpus_tokens):
            freqs: dict[str, int] = defaultdict(int)
            for tok in doc:
                freqs[tok] += 1
            for tok, f in freqs.items():
                self._postings[tok].append((i, f))
                df[tok] += 1

        self._idf: dict[str, float] = {}
        for tok, n_q in df.items():
            # BM25+ IDF: log(1 + (N - df + 0.5)/(df + 0.5)) >= 0 always.
            self._idf[tok] = math.log(1.0 + (self._n - n_q + 0.5) / (n_q + 0.5))

    def __len__(self) -> int:
        return self._n

    def scores(self, query_tokens: list[str]) -> list[float]:
        """Dense vector of BM25 scores, one per document (0.0 where no overlap)."""
        out = [0.0] * self._n
        if not self._n or not self._avgdl:
            return out
        seen: set[str] = set()
        for tok in query_tokens:
            if tok in seen:
                continue
            seen.add(tok)
            idf = self._idf.get(tok)
            if idf is None:
                continue
            for doc_i, f in self._postings[tok]:
                dl = self._doc_len[doc_i]
                denom = f + self._k1 * (1.0 - self._b + self._b * dl / self._avgdl)
                out[doc_i] += idf * (f * (self._k1 + 1.0)) / denom
        return out

    def top_n(self, query_tokens: list[str], n: int) -> list[tuple[int, float]]:
        """Top ``n`` ``(doc_index, score)`` pairs with score > 0, best first."""
        scored = [(i, s) for i, s in enumerate(self.scores(query_tokens)) if s > 0.0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]


def reciprocal_rank_fusion(
    rank_lists: list[list[int]], *, k: int = 60
) -> list[tuple[int, float]]:
    """Fuse multiple ranked id lists via Reciprocal Rank Fusion.

    Each list is ordered best-first. A document at 0-based rank ``r`` in a list
    contributes ``1 / (k + r + 1)``; contributions sum across lists. Returns
    ``(doc_id, fused_score)`` pairs sorted by score (desc). RRF is scale-free, so
    it merges cosine and BM25 rankings without score normalisation.
    """
    fused: dict[int, float] = defaultdict(float)
    for ranked in rank_lists:
        for r, doc_id in enumerate(ranked):
            fused[doc_id] += 1.0 / (k + r + 1)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)
