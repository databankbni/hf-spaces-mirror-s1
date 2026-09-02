"""
Module tạo embedding văn bản.
Dùng paraphrase-multilingual-MiniLM-L12-v2 — đa ngôn ngữ, hỗ trợ tiếng Việt, dim 384, nhanh trên CPU.
Model được load một lần duy nhất (singleton) để tránh khởi động lại nhiều lần.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from config import EMBEDDING_MODEL

logger = logging.getLogger(__name__)

# Trên HF Spaces dùng HF_HOME (/tmp/hf_cache); local fallback về ../models
_MODEL_CACHE_DIR = Path(os.getenv("SENTENCE_TRANSFORMERS_HOME") or os.getenv("HF_HOME") or (Path(__file__).parent.parent / "models"))
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        t0 = time.perf_counter()
        _model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(_MODEL_CACHE_DIR))
        logger.info("[EMBED] load model %s in %.2fs", EMBEDDING_MODEL, time.perf_counter() - t0)
    return _model


def embed_texts(texts: list[str], batch_size: int = 32) -> np.ndarray:
    """Embed danh sách đoạn văn bản. Trả về float32 array shape (N, 384), đã chuẩn hóa."""
    model = _get_model()
    t0 = time.perf_counter()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    logger.info("[EMBED] %d texts in %.2fs (%.1f ms/text)",
                len(texts), time.perf_counter() - t0,
                1000 * (time.perf_counter() - t0) / max(len(texts), 1))
    return embeddings.astype(np.float32)


def embed_query(query: str) -> np.ndarray:
    """Embed câu hỏi của người dùng. Trả về float32 array shape (1, 384)."""
    model = _get_model()
    t0 = time.perf_counter()
    embedding = model.encode([query], convert_to_numpy=True, normalize_embeddings=True)
    logger.info("[EMBED] query in %.0f ms", 1000 * (time.perf_counter() - t0))
    return embedding.astype(np.float32)
