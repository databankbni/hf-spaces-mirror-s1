"""Hybrid embedder: word TF-IDF + character TF-IDF. CPU-only, no neural training."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from ragkit.models import Chunk
from ragkit.text import BM25Index, tokenize


class HybridEmbedder:
    """Fits lexical indexes only — no GPU, no downloaded transformer weights."""

    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path = Path(model_path) if model_path else Path("model") / "hybrid_index.joblib"
        self.word_vectorizer: TfidfVectorizer | None = None
        self.char_vectorizer: TfidfVectorizer | None = None
        self.word_matrix = None
        self.char_matrix = None
        self.bm25: BM25Index | None = None
        self.chunk_ids: list[str] = []
        self.stats: dict[str, Any] = {}
        self.backend = "unfitted"
        if self.model_path.exists():
            self.load()

    @property
    def is_fitted(self) -> bool:
        return self.word_vectorizer is not None and self.word_matrix is not None

    def fit(self, chunks: list[Chunk]) -> dict[str, Any]:
        texts = [c.text for c in chunks]
        self.chunk_ids = [c.chunk_id for c in chunks]
        self.word_vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),
            min_df=1,
            max_df=0.98,
            sublinear_tf=True,
            token_pattern=r"(?u)[\w\u0600-\u06FF]+",
        )
        self.char_vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=1,
            max_df=0.98,
            sublinear_tf=True,
        )
        self.word_matrix = normalize(self.word_vectorizer.fit_transform(texts), norm="l2")
        self.char_matrix = normalize(self.char_vectorizer.fit_transform(texts), norm="l2")
        self.bm25 = BM25Index([tokenize(t) for t in texts])
        self.backend = "hybrid_tfidf_bm25"
        self.stats = {
            "backend": self.backend,
            "n_chunks": len(chunks),
            "word_vocab": int(len(self.word_vectorizer.vocabulary_)),
            "char_vocab": int(len(self.char_vectorizer.vocabulary_)),
        }
        self.save()
        return self.stats

    def save(self) -> None:
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "word_vectorizer": self.word_vectorizer,
                "char_vectorizer": self.char_vectorizer,
                "word_matrix": self.word_matrix,
                "char_matrix": self.char_matrix,
                "bm25": self.bm25,
                "chunk_ids": self.chunk_ids,
                "stats": self.stats,
            },
            self.model_path,
        )
        config_path = self.model_path.parent / "config.json"
        payload = dict(self.stats)
        payload["index_file"] = self.model_path.name
        config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> None:
        payload = joblib.load(self.model_path)
        self.word_vectorizer = payload["word_vectorizer"]
        self.char_vectorizer = payload["char_vectorizer"]
        self.word_matrix = payload["word_matrix"]
        self.char_matrix = payload["char_matrix"]
        self.bm25 = payload["bm25"]
        self.chunk_ids = payload["chunk_ids"]
        self.stats = payload.get("stats", {})
        self.backend = self.stats.get("backend", "hybrid_tfidf_bm25")

    def similarity(self, query: str) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        if not self.is_fitted or self.word_vectorizer is None or self.char_vectorizer is None:
            raise RuntimeError("Embedder is not fitted.")
        word_q = normalize(self.word_vectorizer.transform([query]), norm="l2")
        char_q = normalize(self.char_vectorizer.transform([query]), norm="l2")
        word_s = (self.word_matrix @ word_q.T).toarray().ravel()
        char_s = (self.char_matrix @ char_q.T).toarray().ravel()
        bm25_raw = np.array(self.bm25.scores(tokenize(query)) if self.bm25 else [0.0] * len(self.chunk_ids))
        if bm25_raw.max() > 0:
            bm25_s = bm25_raw / bm25_raw.max()
        else:
            bm25_s = bm25_raw
        combined = 0.42 * word_s + 0.28 * char_s + 0.30 * bm25_s
        return combined, {"word": word_s, "char": char_s, "bm25": bm25_s}
