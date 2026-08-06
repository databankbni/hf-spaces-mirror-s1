from typing import Dict, List, Tuple

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


def load_embedding_model(model_name: str = DEFAULT_EMBEDDING_MODEL) -> SentenceTransformer:
    """Load the sentence-transformer model used for retrieval."""
    return SentenceTransformer(model_name)


def embed_texts(
    texts: List[str],
    model: SentenceTransformer,
    batch_size: int = 32,
) -> np.ndarray:
    """Create normalized embeddings for a list of texts."""
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    return embeddings.astype("float32")


def build_search_index(embeddings: np.ndarray) -> faiss.Index:
    """
    Build a FAISS index for cosine-style similarity search.

    Because embeddings are normalized, inner product behaves like cosine similarity.
    """
    if embeddings.ndim != 2:
        raise ValueError("embeddings must be a 2D array")

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)

    return index


def search_chunks(
    query: str,
    chunks: List[Dict],
    model: SentenceTransformer,
    index: faiss.Index,
    top_k: int = 5,
) -> List[Dict]:
    """Search the chunk index and return the most relevant chunks."""
    query_embedding = embed_texts([query], model=model)
    scores, indices = index.search(query_embedding, top_k)

    results = []

    for score, chunk_index in zip(scores[0], indices[0]):
        if chunk_index == -1:
            continue

        chunk = dict(chunks[chunk_index])
        chunk["search_score"] = float(score)
        results.append(chunk)

    return results