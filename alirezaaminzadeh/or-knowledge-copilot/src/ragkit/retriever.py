"""Hybrid retriever with metadata filters, layer boosts, and parent expansion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ragkit.embedder import HybridEmbedder
from ragkit.models import Chunk, RetrievalHit
from ragkit.query import apply_filters, rewrite_query
from ragkit.text import tokenize


class KnowledgeIndex:
    def __init__(
        self,
        chunks_path: str | Path | None = None,
        model_path: str | Path | None = None,
    ) -> None:
        self.chunks_path = Path(chunks_path) if chunks_path else Path("dataset") / "chunks.jsonl"
        self.embedder = HybridEmbedder(model_path)
        self._chunks: dict[str, Chunk] = {}
        self._load_chunks()

    def _load_chunks(self) -> None:
        if not self.chunks_path.exists():
            return
        with self.chunks_path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    chunk = Chunk.from_dict(json.loads(line))
                    self._chunks[chunk.chunk_id] = chunk

    @property
    def chunks(self) -> list[Chunk]:
        return list(self._chunks.values())

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        return self._chunks.get(chunk_id)

    def add_chunks(self, new_chunks: list[Chunk]) -> None:
        for chunk in new_chunks:
            self._chunks[chunk.chunk_id] = chunk

    def persist_chunks(self) -> None:
        self.chunks_path.parent.mkdir(parents=True, exist_ok=True)
        with self.chunks_path.open("w", encoding="utf-8") as fh:
            for chunk in self.chunks:
                fh.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    def rebuild_embeddings(self) -> dict[str, Any]:
        return self.embedder.fit(self.chunks)


class HybridRetriever:
    def __init__(
        self,
        index: KnowledgeIndex,
        top_k: int = 6,
        synonyms: dict[str, list[str]] | None = None,
        reranker: Callable[[str, list[RetrievalHit]], list[RetrievalHit]] | None = None,
        abstain_threshold: float = 0.18,
    ) -> None:
        self.index = index
        self.top_k = top_k
        self.synonyms = synonyms or {}
        self.reranker = reranker
        self.abstain_threshold = abstain_threshold

    def retrieve(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        layer_boosts: dict[str, float] | None = None,
        rewritten: str | None = None,
    ) -> tuple[list[RetrievalHit], str]:
        if not self.index.embedder.is_fitted:
            raise RuntimeError("Retriever index is not built.")
        rewritten = rewritten if rewritten is not None else rewrite_query(query, self.synonyms)
        combined, components = self.index.embedder.similarity(rewritten)
        chunk_ids = self.index.embedder.chunk_ids
        keyword = self._keyword_overlap(query, chunk_ids)
        scores = 0.88 * combined + 0.12 * keyword

        hits: list[RetrievalHit] = []
        ranked = np.argsort(scores)[::-1]
        for rank, idx in enumerate(ranked, start=1):
            chunk = self.index.get_chunk(chunk_ids[idx])
            if chunk is None:
                continue
            meta = {**chunk.metadata, "layer": chunk.layer, "modality": chunk.modality, "doc_id": chunk.doc_id}
            if not apply_filters(meta, filters):
                continue
            score = float(scores[idx])
            if layer_boosts and chunk.layer in layer_boosts:
                score *= layer_boosts[chunk.layer]
            hits.append(
                RetrievalHit(
                    chunk=chunk,
                    score=score,
                    rank=rank,
                    components={
                        "word": float(components["word"][idx]),
                        "char": float(components["char"][idx]),
                        "bm25": float(components["bm25"][idx]),
                        "keyword": float(keyword[idx]),
                    },
                )
            )
            if len(hits) >= self.top_k * 4:
                break

        if self.reranker:
            hits = self.reranker(query, hits)
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[: self.top_k]
        for i, hit in enumerate(hits, start=1):
            hit.rank = i
        return hits, rewritten

    def _keyword_overlap(self, query: str, chunk_ids: list[str]) -> np.ndarray:
        q = set(tokenize(query))
        scores = np.zeros(len(chunk_ids))
        if not q:
            return scores
        for i, chunk_id in enumerate(chunk_ids):
            chunk = self.index.get_chunk(chunk_id)
            if not chunk:
                continue
            tokens = set(tokenize(chunk.text))
            scores[i] = len(q & tokens) / len(q)
        return scores
