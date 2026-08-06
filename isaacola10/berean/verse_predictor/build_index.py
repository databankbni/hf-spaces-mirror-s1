"""Embed every verse once and cache the vectors to disk (int8-quantized).

Multilingual model so English and Spanish (and any future language) share one
index. Embeddings are L2-normalized then symmetrically quantized to int8,
which shrinks the on-disk index ~4x (≈190MB float32 -> ≈48MB int8) with
negligible ranking impact. Re-run after changing the model or the corpus.
"""
import time
from pathlib import Path

import numpy as np

from corpus import load_verses

# Multilingual (handles en, es, +50 languages); 384-dim like the old model.
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CACHE_DIR = Path(__file__).parent / "data"
EMB_FILE = CACHE_DIR / "verse_emb_int8.npy"
SCALE_FILE = CACHE_DIR / "verse_scale.npy"
META_FILE = CACHE_DIR / "verse_meta.npy"


def quantize(emb: np.ndarray):
    """Symmetric int8 quantization. Returns (int8 matrix, dequant scale)."""
    max_abs = float(np.abs(emb).max())
    scale = max_abs / 127.0
    q = np.round(emb / scale).clip(-127, 127).astype(np.int8)
    return q, np.float32(scale)


def build():
    from sentence_transformers import SentenceTransformer

    verses = load_verses()
    texts = [v["text"] for v in verses]
    print(f"Embedding {len(texts)} verses with {MODEL_NAME} (one-time)...")

    model = SentenceTransformer(MODEL_NAME)
    t0 = time.time()
    emb = model.encode(
        texts,
        batch_size=256,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,  # so dot product == cosine similarity
    ).astype("float32")
    print(f"Embedded in {time.time() - t0:.1f}s. Shape: {emb.shape}")

    q, scale = quantize(emb)
    np.save(EMB_FILE, q)
    np.save(SCALE_FILE, scale)
    np.save(META_FILE, np.array(verses, dtype=object), allow_pickle=True)
    mb = EMB_FILE.stat().st_size / 1e6
    print(f"Saved int8 index ({mb:.0f} MB) -> {EMB_FILE.name}, {SCALE_FILE.name}, {META_FILE.name}")


if __name__ == "__main__":
    build()
