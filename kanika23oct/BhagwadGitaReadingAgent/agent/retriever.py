# ---------------------------------------------------------------------------
# agent/retriever.py
#
# Read side of the verse vector store. Embeds a query with the SAME MiniLM
# model used at ingestion and pulls the top-K most semantically similar
# verses from the `gita_verses` Chroma collection.
#
# Used only by the chat panel's `verse_search` tool — the core reading loop
# never touches this.
# ---------------------------------------------------------------------------

import chromadb

from config import CHROMA_DIR, COLLECTION_NAME
from ingestion.embedder import Embedder


class VerseRetriever:
    """Top-K semantic search over the persisted verse embeddings."""

    def __init__(self, embedder: Embedder | None = None):
        self.embedder = embedder if embedder is not None else Embedder()
        self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        # chromadb >=0.6.0 returns collection *names* (strings) from
        # list_collections(); older releases returned Collection objects.
        existing = {c if isinstance(c, str) else c.name for c in self.client.list_collections()}
        if COLLECTION_NAME not in existing:
            raise RuntimeError(
                f"Chroma collection '{COLLECTION_NAME}' not found at "
                f"{CHROMA_DIR}. Did you run ingestion.build_corpus?"
            )
        self.collection = self.client.get_collection(COLLECTION_NAME)

    def query(
        self, question: str, k: int = 3, allowed_ids: list[str] | None = None
    ) -> list[dict]:
        """Return up to K hits, each: {verse_id, chapter, verse, text, score}.
        Higher score = closer (we report 1 - cosine distance).

        If `allowed_ids` is given, the search is restricted to those verse_ids
        — used to ground answers in only the verses the seeker has heard so
        far. An empty list means "nothing allowed" → no hits."""
        if not question or not question.strip():
            return []
        if allowed_ids is not None and len(allowed_ids) == 0:
            return []
        q_vec = self.embedder.embed(question)
        where = {"verse_id": {"$in": allowed_ids}} if allowed_ids else None
        raw = self.collection.query(
            query_embeddings=[q_vec],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        documents = raw["documents"][0]
        metadatas = raw["metadatas"][0]
        distances = raw["distances"][0]

        hits: list[dict] = []
        for text, meta, dist in zip(documents, metadatas, distances):
            hits.append(
                {
                    "verse_id": meta.get("verse_id", "?"),
                    "chapter": meta.get("chapter", -1),
                    "verse": meta.get("verse", -1),
                    "text": text,
                    "score": 1.0 - float(dist),
                }
            )
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits
