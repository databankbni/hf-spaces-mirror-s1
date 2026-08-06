"""Hybrid 檢索管線（D7，參數寫死保證可重現）：

BM25 top-20 + 向量 top-20 → RRF(k=60) 融合 → bge-reranker 對前 20 重排 → top-5。
rerank 分數保留於結果（P3 拒答門檻使用）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .config import DATA_DIR, get_settings
from .embeddings import STEmbeddings

# D7 固定參數
BM25_TOP_K = 20
VECTOR_TOP_K = 20
RRF_K = 60
RERANK_POOL = 20
FINAL_TOP_K = 5

USERDICT_PATH = Path(__file__).resolve().parent / "legal_userdict.txt"
STOPWORDS = set("的之及或與其於者所如各由並而亦均即因此惟另嗣後暨等到自從、，。；：（）「」")


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    law_name: str
    pcode: str
    article_no: str
    chapter: str
    url: str
    parent_id: str
    part: int
    rrf_score: float
    rerank_score: float | None = None
    sources: list[str] = field(default_factory=list)  # ["bm25", "vector"]
    bm25_score: float | None = None
    bm25_rank: int | None = None
    dense_score: float | None = None
    dense_rank: int | None = None


@dataclass
class RetrievalDiagnostics:
    queries: list[str] = field(default_factory=list)
    bm25_candidate_ids: list[str] = field(default_factory=list)
    dense_candidate_ids: list[str] = field(default_factory=list)
    bm25_dense_overlap_ids: list[str] = field(default_factory=list)
    bm25_dense_overlap_count: int = 0
    bm25_dense_overlap_jaccard: float = 0.0
    top1_top2_margin: float | None = None

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


def jieba_cut(text: str) -> list[str]:
    import jieba

    if USERDICT_PATH.exists() and not getattr(jieba_cut, "_userdict_loaded", False):
        jieba.load_userdict(str(USERDICT_PATH))
        jieba_cut._userdict_loaded = True
    return [t for t in jieba.lcut(text) if t.strip() and t not in STOPWORDS]


def rrf_fuse(rankings: dict[str, list[str]], k: int = RRF_K) -> list[tuple[str, float, list[str]]]:
    """多路排名 → RRF 融合。rankings: {來源名: [chunk_id 依名次排序]}。

    回傳 [(chunk_id, rrf_score, 命中來源)]，分數高在前。
    """
    scores: dict[str, float] = {}
    hit_sources: dict[str, list[str]] = {}
    for source, ranked_ids in rankings.items():
        for rank, cid in enumerate(ranked_ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            hit_sources.setdefault(cid, []).append(source)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [(cid, s, hit_sources[cid]) for cid, s in ordered]


class HybridRetriever:
    def __init__(
        self,
        embedding_key: str = "gtaide",
        dim: int | None = None,
        contextual: bool = True,
        use_rerank: bool = True,
        use_bm25: bool = True,
        device: str | None = None,
    ) -> None:
        import bm25s
        import chromadb

        settings = get_settings()
        self.use_rerank = use_rerank
        self.use_bm25 = use_bm25
        self._settings = settings

        model_id = (
            settings.embedding_model if embedding_key == "gtaide"
            else settings.embedding_baseline_model
        )
        self._embedder = STEmbeddings(
            model_id, device=device, truncate_dim=dim, hf_token=settings.hf_token
        )
        probe_dim = len(self._embedder.embed_query("試"))
        ctx = "ctx" if contextual else "noctx"
        legacy_collection_name = f"{embedding_key}_{probe_dim}_{ctx}"
        client = chromadb.PersistentClient(path=str(DATA_DIR / "chroma"))
        legacy_bm25_dir = DATA_DIR / "bm25s" / ctx
        active_collection_name = legacy_collection_name
        active_bm25_dir = legacy_bm25_dir
        active_version = "legacy-unversioned"
        manifest_path = DATA_DIR / "index_manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (
                    manifest.get("state") == "ready"
                    and manifest.get("embedding_key") == embedding_key
                    and int(manifest.get("dimension", -1)) == probe_dim
                    and bool(manifest.get("contextual")) == contextual
                ):
                    active_collection_name = manifest["collection_name"]
                    active_version = str(
                        manifest.get("active_version") or manifest.get("version")
                    )
                    candidate_bm25 = Path(manifest["bm25_path"])
                    active_bm25_dir = (
                        candidate_bm25
                        if candidate_bm25.is_absolute()
                        else DATA_DIR / candidate_bm25
                    )
            except (OSError, ValueError, KeyError, TypeError):
                # An unreadable pointer is not allowed to hide the last known
                # legacy index; loading below still validates both stores.
                active_collection_name = legacy_collection_name
                active_bm25_dir = legacy_bm25_dir

        def _load(collection_name: str, bm25_dir: Path):
            collection = client.get_collection(collection_name)
            bm25 = bm25s.BM25.load(str(bm25_dir))
            bm25_ids = json.loads(
                (bm25_dir / "chunk_ids.json").read_text(encoding="utf-8")
            )
            return collection, bm25, bm25_ids

        try:
            self._collection, self._bm25, self._bm25_ids = _load(
                active_collection_name, active_bm25_dir
            )
            self.index_version = active_version
        except Exception:
            try:
                # Active pointer may refer to a locally unavailable version
                # (for example a fresh HF Space disk); try the last legacy copy.
                self._collection, self._bm25, self._bm25_ids = _load(
                    legacy_collection_name, legacy_bm25_dir
                )
                self.index_version = "legacy-unversioned"
            except Exception:
                # 索引不存在：用已載入的 embedder 自動建一次，避免重複載入。
                from .index_build import build_index

                build_index(
                    embedding_key=embedding_key, dim=dim, contextual=contextual,
                    confirm_cost=False, embedder=self._embedder,
                )
                self._collection, self._bm25, self._bm25_ids = _load(
                    legacy_collection_name, legacy_bm25_dir
                )
                self.index_version = "legacy-unversioned"
        self._reranker = None
        self._device = device
        self.last_diagnostics = RetrievalDiagnostics()

    def _rerank(self, query: str, candidates: list[RetrievedChunk]) -> None:
        if self._reranker is None:
            from sentence_transformers import CrossEncoder

            self._reranker = CrossEncoder(
                self._settings.reranker_model,
                max_length=1024,
                device=self._device,
            )
        logits = self._reranker.predict(
            [(query, c.text) for c in candidates], show_progress_bar=False
        )
        for c, logit in zip(candidates, logits):
            c.rerank_score = 1.0 / (1.0 + math.exp(-float(logit)))  # Sigmoid

    def retrieve(self, query: str) -> list[RetrievedChunk]:
        return self.retrieve_multi([query])

    def retrieve_multi(
        self, queries: list[str], rerank_query: str | None = None
    ) -> list[RetrievedChunk]:
        """多查詢檢索（D10）：每個查詢各走 BM25+向量，全部排名一起 RRF 融合。

        典型用法是 [原問題, 改寫後查詢]——改寫品質不穩時原問題仍能保底，
        兩個查詢都命中的條文會被 RRF 自然加權。rerank_query 未指定時用
        第一個查詢（呼叫端慣例：原問題放最前面，rerank 以真實意圖為準）。
        """
        queries = [q for q in dict.fromkeys(q.strip() for q in queries) if q]
        if not queries:
            return []

        rankings: dict[str, list[str]] = {}
        doc_by_id: dict[str, str] = {}
        meta_by_id: dict[str, dict] = {}
        bm25_scores: dict[str, float] = {}
        bm25_ranks: dict[str, int] = {}
        dense_scores: dict[str, float] = {}
        dense_ranks: dict[str, int] = {}
        for qi, query in enumerate(queries):
            if self.use_bm25:
                q_tokens = jieba_cut(query)
                if q_tokens:
                    results, scores = self._bm25.retrieve(
                        [q_tokens], k=min(BM25_TOP_K, len(self._bm25_ids))
                    )
                    ranked_ids = [self._bm25_ids[int(i)] for i in results[0]]
                    rankings[f"bm25:{qi}"] = ranked_ids
                    for rank, (cid, score) in enumerate(
                        zip(ranked_ids, scores[0]), start=1
                    ):
                        numeric_score = float(score)
                        if (
                            cid not in bm25_scores
                            or numeric_score > bm25_scores[cid]
                        ):
                            bm25_scores[cid] = numeric_score
                            bm25_ranks[cid] = rank

            q_vec = self._embedder.embed_query(query)
            res = self._collection.query(
                query_embeddings=[q_vec],
                n_results=VECTOR_TOP_K,
                include=["documents", "metadatas", "distances"],
            )
            rankings[f"vector:{qi}"] = res["ids"][0]
            doc_by_id.update(zip(res["ids"][0], res["documents"][0]))
            meta_by_id.update(zip(res["ids"][0], res["metadatas"][0]))
            distances = (res.get("distances") or [[]])[0]
            for rank, (cid, distance) in enumerate(
                zip(res["ids"][0], distances), start=1
            ):
                similarity = 1.0 - float(distance)
                if cid not in dense_scores or similarity > dense_scores[cid]:
                    dense_scores[cid] = similarity
                    dense_ranks[cid] = rank

        fused = rrf_fuse(rankings)

        # 補齊 BM25-only 命中的 document/metadata
        missing = [cid for cid, _, _ in fused if cid not in doc_by_id]
        if missing:
            got = self._collection.get(ids=missing, include=["documents", "metadatas"])
            for cid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"]):
                doc_by_id[cid] = doc
                meta_by_id[cid] = meta

        candidates = []
        for cid, score, sources in fused[:RERANK_POOL]:
            meta = meta_by_id[cid]
            candidates.append(RetrievedChunk(
                chunk_id=cid,
                text=doc_by_id[cid],
                law_name=meta["law_name"],
                pcode=meta["pcode"],
                article_no=meta["article_no"],
                chapter=meta.get("chapter", ""),
                url=meta["url"],
                parent_id=meta["parent_id"],
                part=int(meta["part"]),
                rrf_score=score,
                sources=sources,
                bm25_score=bm25_scores.get(cid),
                bm25_rank=bm25_ranks.get(cid),
                dense_score=dense_scores.get(cid),
                dense_rank=dense_ranks.get(cid),
            ))

        if self.use_rerank and candidates:
            self._rerank(rerank_query or queries[0], candidates)
            candidates.sort(key=lambda c: c.rerank_score, reverse=True)
        final = candidates[:FINAL_TOP_K]
        bm25_ids = set(bm25_scores)
        dense_ids = set(dense_scores)
        overlap = sorted(bm25_ids & dense_ids)
        union = bm25_ids | dense_ids
        margin = None
        if (
            len(final) > 1
            and final[0].rerank_score is not None
            and final[1].rerank_score is not None
        ):
            margin = final[0].rerank_score - final[1].rerank_score
        self.last_diagnostics = RetrievalDiagnostics(
            queries=list(queries),
            bm25_candidate_ids=sorted(bm25_ids),
            dense_candidate_ids=sorted(dense_ids),
            bm25_dense_overlap_ids=overlap,
            bm25_dense_overlap_count=len(overlap),
            bm25_dense_overlap_jaccard=len(overlap) / len(union) if union else 0.0,
            top1_top2_margin=margin,
        )
        return final
