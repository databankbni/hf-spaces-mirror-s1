"""Rebuild the Chroma + BM25 index in-container from committed TEXT files.

HuggingFace rejects binary files in normal git (they must go to LFS/Xet), so the built index is
NOT committed. Instead the vectors are precomputed offline into `data/embeddings.jsonl` (plain
text), and this rebuilds Chroma + BM25 from `chunks.jsonl` + `embeddings.jsonl` at container
startup. No E5 embedding runs here — the vectors already exist — so it's seconds, not the ~45-minute
build, and it sidesteps the Windows→Linux binary-portability question entirely (text is portable).

Idempotent: if the index is already present (count matches, bm25 exists), it does nothing.

    from space_index import ensure_index
    ensure_index()   # call once at app startup, before any retrieval
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from retrieval import ChromaStore, SparseIndex, BM25_PATH   # noqa: E402
from index import build_metadata, load_chunks               # noqa: E402  (reuse the exact metadata)

EMB_PATH = _ROOT / "data" / "embeddings.jsonl"


def _load_embeddings() -> dict:
    out = {}
    with EMB_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                e = json.loads(line)
                out[e["chunk_id"]] = e["embedding"]
    return out


def ensure_index() -> None:
    chunks = load_chunks()
    n = len(chunks)

    store = ChromaStore()
    if store.count() < n:                       # dense: upsert precomputed vectors (no E5)
        embs = _load_embeddings()
        missing = [c["chunk_id"] for c in chunks if c["chunk_id"] not in embs]
        if missing:
            raise RuntimeError(f"embeddings.jsonl missing {len(missing)} vectors, e.g. {missing[:3]}")
        store.upsert(
            ids=[c["chunk_id"] for c in chunks],
            embeddings=[np.asarray(embs[c["chunk_id"]], dtype=np.float32) for c in chunks],
            documents=[c["text"] for c in chunks],
            metadatas=[build_metadata(c) for c in chunks],
        )

    if not BM25_PATH.exists():                  # sparse: rebuild BM25 over the displayed text (fast)
        SparseIndex.build(
            chunk_ids=[c["chunk_id"] for c in chunks],
            texts=[c["text"] for c in chunks],
            metadatas=[build_metadata(c) for c in chunks],
        ).save()


if __name__ == "__main__":
    ensure_index()
    print(f"index ready: {ChromaStore().count()} vectors, bm25 exists={BM25_PATH.exists()}")
