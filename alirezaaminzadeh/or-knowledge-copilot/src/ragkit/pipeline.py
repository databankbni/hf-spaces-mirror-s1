"""End-to-end hybrid RAG pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ragkit.generator import generate_answer
from ragkit.models import QueryResult
from ragkit.query import detect_language
from ragkit.retriever import HybridRetriever, KnowledgeIndex


class RAGPipeline:
    def __init__(
        self,
        chunks_path: str | Path,
        model_path: str | Path,
        top_k: int = 6,
        synonyms: dict[str, list[str]] | None = None,
        reranker: Callable | None = None,
        abstain_threshold: float = 0.18,
        product: str = "Knowledge Assistant",
        router: Callable[[str], tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        self.index = KnowledgeIndex(chunks_path=chunks_path, model_path=model_path)
        self.retriever = HybridRetriever(
            self.index,
            top_k=top_k,
            synonyms=synonyms,
            reranker=reranker,
            abstain_threshold=abstain_threshold,
        )
        self.abstain_threshold = abstain_threshold
        self.product = product
        self.router = router
        self.chunks_path = Path(chunks_path)
        self.model_path = Path(model_path)

    def rebuild(self) -> dict[str, Any]:
        self.index.persist_chunks()
        stats = self.index.rebuild_embeddings()
        self.retriever = HybridRetriever(
            self.index,
            top_k=self.retriever.top_k,
            synonyms=self.retriever.synonyms,
            reranker=self.retriever.reranker,
            abstain_threshold=self.abstain_threshold,
        )
        return stats

    def ask(
        self,
        question: str,
        language: str | None = None,
        filters: dict[str, Any] | None = None,
        extras: dict[str, Any] | None = None,
    ) -> QueryResult:
        if not question or not question.strip():
            raise ValueError("Question cannot be empty.")
        lang = language or detect_language(question)
        route = "document"
        layer_boosts: dict[str, float] = {}
        if self.router:
            route, routed = self.router(question)
            filters = {**(filters or {}), **routed.get("filters", {})}
            layer_boosts = routed.get("layer_boosts", {})
            extras = {**(extras or {}), **routed.get("extras", {})}
        hits, rewritten = self.retriever.retrieve(question, filters=filters, layer_boosts=layer_boosts)
        return generate_answer(
            question,
            hits,
            language=lang,
            rewritten_query=rewritten,
            abstain_threshold=self.abstain_threshold,
            extras=extras or {},
            route=route,
            product=self.product,
        )
