# ---------------------------------------------------------------------------
# ingestion/embedder.py
#
# Turns text into a 384-dim vector so verses can be searched by *meaning*
# (used only by the optional chat panel's semantic search). Same MiniLM
# wrapper proven in kanikatestmodel/phase-3-rag — build once, call many.
# ---------------------------------------------------------------------------

from sentence_transformers import SentenceTransformer

from config import EMBED_MODEL_ID


class Embedder:
    """Wraps a sentence-transformers model. Build once, call many times."""

    def __init__(self, model_id: str = EMBED_MODEL_ID):
        self.model = SentenceTransformer(model_id)
        self.dim: int = self.model.get_embedding_dimension()

    def embed(self, text: str) -> list[float]:
        """Embed a single string → unit-norm vector as a plain list."""
        vec = self.model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many strings at once (much faster than a Python loop)."""
        if not texts:
            return []
        vecs = self.model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vecs.tolist()
