"""Persistent Chroma vector store management."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from threading import RLock
from typing import Iterable

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


class VectorStoreManager:
    """Manage a persistent Chroma collection."""

    def __init__(
        self,
        embeddings: Embeddings,
        persist_directory: str | Path = "./chroma_db",
        collection_name: str = "alloftech_rag",
    ) -> None:
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._store = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=str(self.persist_directory),
            collection_metadata={"hnsw:space": "cosine"},
        )

        logger.info("Initialized Chroma collection '%s' at %s.", collection_name, self.persist_directory)

    def add_documents(self, documents: list[Document]) -> int:
        """Add or update documents in Chroma using deterministic IDs."""
        if not documents:
            logger.info("No chunks to add to the vector store.")
            return 0

        ids = [self._document_id(document) for document in documents]
        with self._lock:
            self._store.add_documents(documents=documents, ids=ids)

        logger.info("Indexed %d chunk(s) into Chroma.", len(documents))
        return len(documents)

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[tuple[Document, float]]:
        """Return the top-k similar chunks whose cosine similarity meets the threshold.

        Chroma cosine *distance* is converted to similarity with ``1 - distance``.
        LangChain relevance scores are not used; they can be negative and drop
        valid chunks below a 0.4 cutoff.
        """
        if not query.strip():
            return []

        with self._lock:
            raw_results = self._store.similarity_search_with_score(query, k=k)

        scored: list[tuple[Document, float]] = []
        for document, distance in raw_results:
            similarity = 1.0 - float(distance)
            if similarity >= score_threshold:
                scored.append((document, similarity))

        logger.info(
            "Similarity search returned %d result(s) above threshold %.2f.",
            len(scored),
            score_threshold,
        )
        return scored

    def get_overview_chunks(self, max_chunks: int = 20) -> list[tuple[Document, float]]:
        """Return indexed chunks in document order for summarize/overview questions."""
        with self._lock:
            data = self._store.get(include=["documents", "metadatas"])

        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []
        chunks: list[tuple[Document, float]] = []
        for content, metadata in zip(documents, metadatas):
            if not content or not str(content).strip():
                continue
            chunks.append(
                (
                    Document(page_content=str(content), metadata=metadata or {}),
                    1.0,
                )
            )

        chunks.sort(
            key=lambda item: (
                str((item[0].metadata or {}).get("source_file") or ""),
                int((item[0].metadata or {}).get("page") or 0),
                int((item[0].metadata or {}).get("start_index") or 0),
            )
        )
        selected = chunks[:max_chunks]
        logger.info("Loaded %d overview chunk(s) from the indexed documents.", len(selected))
        return selected

    def list_sources(self) -> list[str]:
        """Return the distinct source filenames currently indexed."""
        with self._lock:
            data = self._store.get(include=["metadatas"])

        metadatas = data.get("metadatas") or []
        sources = {
            str(metadata.get("source_file") or Path(str(metadata.get("source", "unknown"))).name)
            for metadata in metadatas
            if metadata
        }
        return sorted(sources)

    @staticmethod
    def _document_id(document: Document) -> str:
        metadata = document.metadata or {}
        identity_parts: Iterable[str] = (
            str(metadata.get("source", "")),
            str(metadata.get("page", "")),
            str(metadata.get("row", "")),
            str(metadata.get("start_index", "")),
            document.page_content,
        )
        digest = hashlib.sha256("::".join(identity_parts).encode("utf-8")).hexdigest()
        return digest
