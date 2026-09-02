"""NurtureDE retrieval layer — one interface, swappable parts.

`search(query, k, filters) -> list[RetrievedChunk]` is the single entry point the
rest of the system (and Phase 12's visualiser) sees. Behind it, the embedding model
and the vector store are each hidden behind a small surface so the production swap
(local E5 -> hosted endpoint; Chroma -> Supabase pgvector) is a contained change,
not a rewrite. A 2.2GB local model will not fit in a serverless function, so this
seam is load-bearing, not speculative.

Dense + sparse are complementary on this corpus:
  * dense (multilingual-E5) carries the cross-lingual and compound *semantics* — an
    English query must retrieve a German passage with zero shared words.
  * BM25 over the *displayed* `text` carries exact rare-token matching, including
    whole German compounds ("Mutterschutzfrist") that the dense space blurs.
They are fused with Reciprocal Rank Fusion (rank-based, so the two incomparable
score scales never have to be normalised against each other).
"""

from __future__ import annotations

import re
import time
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

# --- paths / constants -------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
CHROMA_DIR = _ROOT / "chroma_db"
BM25_PATH = _ROOT / "data" / "bm25.pkl"
COLLECTION = "nurture_chunks"

MODEL_NAME = "intfloat/multilingual-e5-large"
# E5 is asymmetric: documents and queries are embedded with different prefixes.
# Omitting these does NOT error — it silently degrades retrieval — so the prefix
# actually applied is recorded in each vector's metadata (embed_prefix) and can be
# verified rather than assumed (see index.py + validation Test 2).
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

RRF_K = 60  # standard Reciprocal Rank Fusion damping constant


# --- German-aware tokenizer for BM25 ----------------------------------------
# Unicode word tokens, keeping umlauts (ä ö ü) as themselves. `casefold()` lowercases
# AND folds ß -> ss, which is the right German normalisation (many sources write
# "Strasse" for "Straße"). Deliberately does NOT decompose compounds:
# "Beschäftigungsverbot" stays one token. That is a known BM25 limitation, accepted
# here on purpose — BM25's job is exact whole-token / rare-term matching (a query
# term "Mutterschutzfrist" hits the compound directly); the dense E5 index is what
# handles sub-compound semantics. The two indexes cover each other's weakness.
_TOKEN_RE = re.compile(r"[0-9a-zA-ZÀ-ɏ]+")


def tokenize_de(text: str) -> list[str]:
    """Tokenize for BM25. Same function used at index and query time (must match)."""
    return [t.casefold() for t in _TOKEN_RE.findall(text)]


# --- result + trace types ----------------------------------------------------
@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    score: float           # fused score (or single-index score in dense/sparse mode)
    metadata: dict

    @property
    def heading_path(self) -> str:
        return self.metadata.get("heading_path", "")

    @property
    def source_id(self) -> str:
        return self.metadata.get("source_id", "")


@dataclass
class RetrievalTrace:
    """Optional, off by default. Every stage the Phase-12 visualiser will render.

    Built as data is produced so instrumentation never has to be retrofitted into
    working retrieval code later.
    """
    query: str
    mode: str
    filters: dict | None = None
    dense: list[dict] = field(default_factory=list)     # {chunk_id, similarity, rank}
    sparse: list[dict] = field(default_factory=list)    # {chunk_id, bm25, rank}
    fused: list[dict] = field(default_factory=list)     # {chunk_id, rrf, dense_rank, sparse_rank}
    filter_exclusions: list[dict] = field(default_factory=list)  # {chunk_id, reason}
    both: list[str] = field(default_factory=list)       # chunk_ids retrieved by BOTH indexes
    rerank: list[dict] | None = None                    # populated when a reranker lands (Phase 5+)
    final_context: list[str] = field(default_factory=list)       # chunk_ids returned, in order
    context_tokens: int = 0                             # cl100k tokens of the assembled context
    underfilled: dict | None = None                     # set when the filtered pool is < k
    timings_ms: dict = field(default_factory=dict)


# --- embedder ---------------------------------------------------------------
class Embedder(Protocol):
    def embed_passages(self, texts: Sequence[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class E5Embedder:
    """multilingual-e5-large with the required asymmetric prefixes.

    The model (~2.2GB fp32) is loaded lazily on first use so importing this module
    is cheap. On this memory-constrained box it is loaded directly in **fp16**
    (~1.1GB) via `model_kwargs={"torch_dtype": float16}` — loading straight into
    fp16 avoids the transient fp32 peak that a post-hoc `.half()` would incur.
    fp16 vs fp32 is negligible for embedding quality. Vectors are cast back to
    fp32 for storage/scoring (tiny arrays; better downstream precision) and are
    L2-normalised, so cosine == inner product. Passages AND queries go through the
    same model/dtype, so their vectors are directly comparable.
    """

    def __init__(self, model_name: str = MODEL_NAME, dtype: str = "float16",
                 batch_size: int = 8):
        self.model_name = model_name
        self.dtype = dtype
        self.batch_size = batch_size
        self._model = None

    @property
    def model(self):
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            kwargs = {}
            if self.dtype:
                kwargs["model_kwargs"] = {"torch_dtype": getattr(torch, self.dtype)}
            self._model = SentenceTransformer(self.model_name, **kwargs)
        return self._model

    def _encode(self, texts: Sequence[str], batch_size: int | None = None) -> np.ndarray:
        emb = self.model.encode(
            list(texts),
            batch_size=batch_size or self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return emb.astype(np.float32)  # store/score in fp32 regardless of compute dtype

    def embed_passages(self, texts: Sequence[str], batch_size: int | None = None) -> np.ndarray:
        return self._encode([PASSAGE_PREFIX + t for t in texts], batch_size)

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([QUERY_PREFIX + text])[0]


# --- vector store -----------------------------------------------------------
class ChromaStore:
    """Chroma persistent collection, cosine space. Swap target: Supabase pgvector."""

    def __init__(self, path: Path = CHROMA_DIR, collection: str = COLLECTION):
        import chromadb
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, ids, embeddings, documents, metadatas):
        # upsert keyed on id => re-running the build never duplicates a chunk.
        self.collection.upsert(
            ids=list(ids),
            embeddings=[e.tolist() for e in embeddings],
            documents=list(documents),
            metadatas=list(metadatas),
        )

    def count(self) -> int:
        return self.collection.count()

    def query(self, embedding: np.ndarray, n: int) -> list[dict]:
        """Return up to n candidates as {chunk_id, similarity, text, metadata}.

        Filters are applied client-side by the Retriever (only 201 chunks) so that
        the trace can record *why* each excluded candidate was dropped — Chroma's
        server-side `where` would hide that.
        """
        res = self.collection.query(
            query_embeddings=[embedding.tolist()],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        out = []
        for cid, doc, meta, dist in zip(
            res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            out.append(
                {"chunk_id": cid, "similarity": 1.0 - dist, "text": doc, "metadata": meta}
            )
        return out


# --- sparse index -----------------------------------------------------------
class SparseIndex:
    """BM25 over the displayed `text` (never embed_text — its bracketed authority/
    heading prefix would inflate term frequencies with authority names)."""

    def __init__(self, bm25, chunk_ids, texts, metadatas):
        self.bm25 = bm25
        self.chunk_ids = chunk_ids
        self.texts = texts
        self.metadatas = metadatas

    @classmethod
    def build(cls, chunk_ids, texts, metadatas) -> "SparseIndex":
        from rank_bm25 import BM25Okapi
        corpus = [tokenize_de(t) for t in texts]
        return cls(BM25Okapi(corpus), list(chunk_ids), list(texts), list(metadatas))

    def save(self, path: Path = BM25_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(
                {"bm25": self.bm25, "chunk_ids": self.chunk_ids,
                 "texts": self.texts, "metadatas": self.metadatas}, fh
            )

    @classmethod
    def load(cls, path: Path = BM25_PATH) -> "SparseIndex":
        with open(path, "rb") as fh:
            d = pickle.load(fh)
        return cls(d["bm25"], d["chunk_ids"], d["texts"], d["metadatas"])

    def query(self, text: str, n: int) -> list[dict]:
        scores = self.bm25.get_scores(tokenize_de(text))
        order = np.argsort(scores)[::-1][:n]
        out = []
        for i in order:
            out.append({
                "chunk_id": self.chunk_ids[i],
                "bm25": float(scores[i]),
                "text": self.texts[i],
                "metadata": self.metadatas[i],
            })
        return out


# --- reranker (Phase 8) ------------------------------------------------------
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"   # multilingual cross-encoder (XLM-R-large); handles DE

# Width of the candidate pool handed to the cross-encoder on the rerank path. 100, not the
# retrieval default of 20, and not 50 — this is load-bearing and measured, not a round number:
# on the English->German cross-lingual cases the correct German chunk can sit at fused rank ~43
# (case L30). A 50-wide pool leaves it at reranked rank 4 — one short of K_CONTEXT=4, so it never
# reaches the model. A 100-wide pool recovers it to rank 0. (The earlier Phase-8 eval reranked
# only the top-10 fused, so the cross-encoder never saw these chunks — see BUILD_JOURNAL P8
# retraction.) Cost: ~5x the cross-encoder compute of a 20-pool (see Phase-13 latency note).
RERANK_POOL = 100


class Reranker:
    """Cross-encoder reranker: scores each (query, passage) pair jointly and reorders.
    Unlike the bi-encoder retriever (query and passage embedded separately), a cross-encoder
    reads both together, so it is more accurate but too slow to run over the whole corpus —
    it reranks a small candidate pool from hybrid retrieval. Loaded lazily. Swap target: a
    hosted reranker endpoint (the interface is just `rerank(query, hits) -> hits`)."""

    def __init__(self, model_name: str = RERANKER_MODEL, batch_size: int = 16):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)  # ~2.2GB, downloaded once to HF cache
        return self._model

    def rerank(self, query: str, hits: list) -> list:
        """Reorder RetrievedChunk hits by cross-encoder relevance (descending). Scores the
        query against each chunk's displayed `text` (what a reader would read)."""
        if not hits:
            return hits
        scores = self.model.predict([(query, h.text) for h in hits],
                                    batch_size=self.batch_size, show_progress_bar=False)
        return [h for _, h in sorted(zip(scores, hits), key=lambda p: p[0], reverse=True)]


# --- reciprocal rank fusion --------------------------------------------------
def rrf_fuse(dense_ids: Sequence[str], sparse_ids: Sequence[str],
             k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. Each argument is chunk_ids in rank order (best first).
    A chunk's fused score is the sum, over the lists it appears in, of 1/(k + rank).

    Why k=60 (standard): the constant DAMPENS the top of each list. A rank-0 hit
    contributes 1/(60+0)=0.0167, not 1.0, and rank-1 contributes 0.0164 — nearly the
    same. So one index's single #1 outlier can't dominate the fusion; a chunk that both
    indexes rank *reasonably* (two 1/(k+rank) terms) outscores one that either index
    ranks #1 alone. Larger k => flatter weighting (rank matters less); smaller k =>
    the very top rank dominates. Rank-based, so BM25's unbounded scores and cosine's
    [-1,1] are never normalised against each other."""
    scores: dict[str, float] = {}
    for ranked in (dense_ids, sparse_ids):
        for rank, cid in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# --- filters ----------------------------------------------------------------
# `any` is the no-constraint value for these fields (Phase-3 taxonomy): a chunk tagged
# user_type=any / insurance_type=any applies REGARDLESS of the caller's persona, so it
# must survive a filter for any *specific* value. Omitting this silently halves recall
# (user_type=any is 59% of the corpus; insurance_type=any is 95%). topic/language have
# no `any` bucket and stay exact-match.
ANY_PASSTHROUGH_FIELDS = {"user_type", "insurance_type"}


def _passes(meta: dict, filters: dict | None) -> tuple[bool, str]:
    """Metadata pre-filter. Returns (passed, reason_if_excluded). For the
    any-passthrough fields, a chunk passes if it matches the requested value OR is
    tagged `any`."""
    if not filters:
        return True, ""
    for key, want in filters.items():
        got = meta.get(key)
        wants = set(want) if isinstance(want, (list, tuple, set)) else {want}
        if key in ANY_PASSTHROUGH_FIELDS:
            wants = wants | {"any"}     # no-constraint chunks are always eligible
        if got not in wants:
            return False, f"{key}={got!r} not in {sorted(wants)!r}"
    return True, ""


# --- assembled-context token count (for the trace / Phase-12 visualiser) -----
_cl100k = None


def _context_tokens(texts: Sequence[str]) -> int:
    """cl100k token count of the assembled context (chunk texts joined). Lazily imports
    the vendored encoder so importing this module stays cheap. cl100k (not E5) is the
    right unit here — this counts the budget of what gets handed to the answering LLM,
    not what the embedder saw."""
    global _cl100k
    if _cl100k is None:
        import os
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from vendor import cl100k as _c
        _cl100k = _c
    return _cl100k.count("\n\n".join(texts))


# --- the interface ----------------------------------------------------------
class Retriever:
    """The one retrieval interface. Construct once, reuse (holds the loaded model)."""

    POOL = 20  # candidates pulled from EACH index before filtering + fusion (spec: top-20)

    def __init__(self, embedder: Embedder | None = None,
                 store: ChromaStore | None = None,
                 sparse: SparseIndex | None = None):
        self.embedder = embedder or E5Embedder()
        self.store = store or ChromaStore()
        self.sparse = sparse  # loaded lazily; not needed for dense-only mode

    def _sparse_index(self) -> SparseIndex:
        if self.sparse is None:
            self.sparse = SparseIndex.load()
        return self.sparse

    def search(self, query: str, k: int = 10, filters: dict | None = None,
               mode: str = "hybrid", trace: bool = False, pool: int | None = None):
        """mode: 'hybrid' (RRF of dense+sparse) | 'dense' | 'sparse'.

        `pool` overrides how many candidates are pulled from EACH index before filtering +
        fusion (default `self.POOL`=20). The rerank path passes a larger pool (RERANK_POOL)
        so the cross-encoder can reach a correct chunk that RRF buried below the default cut.

        Metadata filtering is a PRE-filter: candidates are dropped before fusion, so an
        aggressive filter can leave the fused pool below k (unlike a post-filter, which
        can't). That case is recorded on the trace (`underfilled`) rather than silently
        returning short. Returns list[RetrievedChunk]; if trace=True, (list, trace).
        """
        pool = pool or self.POOL
        tr = RetrievalTrace(query=query, mode=mode, filters=filters) if trace else None
        t0 = time.perf_counter()

        dense_hits: list[dict] = []
        if mode in ("hybrid", "dense"):
            ts = time.perf_counter()
            qv = self.embedder.embed_query(query)          # "query: " prefix (asymmetric E5)
            dense_hits = self.store.query(qv, pool)
            if tr:
                tr.timings_ms["dense_ms"] = (time.perf_counter() - ts) * 1000

        sparse_hits: list[dict] = []
        if mode in ("hybrid", "sparse"):
            ts = time.perf_counter()
            sparse_hits = self._sparse_index().query(query, pool)
            if tr:
                tr.timings_ms["sparse_ms"] = (time.perf_counter() - ts) * 1000

        # --- pre-filter (records exclusions + reasons for the trace) ---
        tf = time.perf_counter()

        def keep(hits):
            kept = []
            for h in hits:
                ok, why = _passes(h["metadata"], filters)
                if ok:
                    kept.append(h)
                elif tr:
                    tr.filter_exclusions.append({"chunk_id": h["chunk_id"], "reason": why})
            return kept

        if filters:
            dense_hits, sparse_hits = keep(dense_hits), keep(sparse_hits)
        if tr:
            tr.timings_ms["filter_ms"] = (time.perf_counter() - tf) * 1000

        dense_ids = [h["chunk_id"] for h in dense_hits]
        sparse_ids = [h["chunk_id"] for h in sparse_hits]
        dense_rank = {cid: i for i, cid in enumerate(dense_ids)}
        sparse_rank = {cid: i for i, cid in enumerate(sparse_ids)}
        meta_by_id = {h["chunk_id"]: h for h in (*dense_hits, *sparse_hits)}
        both = [cid for cid in dense_ids if cid in sparse_rank]

        if tr:
            tr.dense = [{"chunk_id": h["chunk_id"], "similarity": round(h["similarity"], 4),
                         "rank": i} for i, h in enumerate(dense_hits)]
            tr.sparse = [{"chunk_id": h["chunk_id"], "bm25": round(h["bm25"], 4),
                          "rank": i} for i, h in enumerate(sparse_hits)]
            tr.both = both

        # --- fuse ---
        tfu = time.perf_counter()
        if mode == "dense":
            ranked = [(h["chunk_id"], h["similarity"]) for h in dense_hits]
        elif mode == "sparse":
            ranked = [(h["chunk_id"], h["bm25"]) for h in sparse_hits]
        else:
            ranked = rrf_fuse(dense_ids, sparse_ids)
            if tr:
                tr.fused = [{"chunk_id": cid, "rrf": round(s, 6),
                             "dense_rank": dense_rank.get(cid),
                             "sparse_rank": sparse_rank.get(cid)} for cid, s in ranked[:k]]
        if tr:
            tr.timings_ms["fusion_ms"] = (time.perf_counter() - tfu) * 1000

        # pre-filtering can shrink the pool below k — surface it, don't hide it
        if tr and len(ranked) < k:
            tr.underfilled = {
                "requested": k, "available": len(ranked),
                "reason": ("pre-filtering left fewer than k candidates" if filters
                           else "index pool yielded fewer than k candidates"),
            }

        results = []
        for cid, score in ranked[:k]:
            h = meta_by_id[cid]
            results.append(RetrievedChunk(cid, h["text"], float(score), h["metadata"]))

        if tr:
            tr.final_context = [r.chunk_id for r in results]
            tr.context_tokens = _context_tokens([r.text for r in results])
            tr.timings_ms["total_ms"] = (time.perf_counter() - t0) * 1000
            return results, tr
        return results


# --- module-level entry point -----------------------------------------------
_DEFAULT_RETRIEVER: Retriever | None = None


def search(query: str, k: int = 10, filters: dict | None = None, trace: bool = False):
    """The single retrieval entry point every caller goes through. Hybrid dense+sparse
    with RRF and optional metadata pre-filtering. Reuses one Retriever (which holds the
    loaded E5 model + both indexes) so repeated calls don't reload 1 GB of weights."""
    global _DEFAULT_RETRIEVER
    if _DEFAULT_RETRIEVER is None:
        _DEFAULT_RETRIEVER = Retriever()
    return _DEFAULT_RETRIEVER.search(query, k=k, filters=filters, mode="hybrid", trace=trace)
