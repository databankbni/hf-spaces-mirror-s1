from typing import Dict, List

from sentence_transformers import CrossEncoder


DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def load_reranker(model_name: str = DEFAULT_RERANKER_MODEL) -> CrossEncoder:
    """Load the cross-encoder model used to rerank retrieved chunks."""
    return CrossEncoder(model_name)


def rerank_chunks(
    query: str,
    chunks: List[Dict],
    reranker: CrossEncoder,
    top_k: int = 5,
) -> List[Dict]:
    """
    Rerank retrieved chunks using a cross-encoder.

    The cross-encoder reads the query and chunk together, so it is slower than
    vector search but usually more accurate for final evidence selection.
    """
    if not chunks:
        return []

    pairs = [(query, chunk["text"]) for chunk in chunks]
    scores = reranker.predict(pairs)

    reranked = []

    for chunk, score in zip(chunks, scores):
        updated_chunk = dict(chunk)
        updated_chunk["rerank_score"] = float(score)
        reranked.append(updated_chunk)

    reranked.sort(key=lambda item: item["rerank_score"], reverse=True)

    return reranked[:top_k]
