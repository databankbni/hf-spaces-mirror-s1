"""Phase 4 — build the dense (Chroma) + sparse (BM25) indexes over data/chunks.jsonl.

    py src/index.py            # build both, print report
    py src/index.py --report   # report only (token stats), skip (re)building

Idempotent: Chroma upserts keyed on chunk_id, so re-running never duplicates.
Dense vectors come from `embed_text` (prefixed "passage: "); BM25 is built over the
displayed `text` (see retrieval.py for why). Prints embedding dimension, vector
count, and the E5-vs-cl100k token comparison the chunking phase asked to confirm.
"""

from __future__ import annotations

import sys
import json
import statistics as stats
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # umlauts to a Windows console

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from retrieval import (  # noqa: E402
    E5Embedder, ChromaStore, SparseIndex, PASSAGE_PREFIX, MODEL_NAME,
)

CHUNKS = _ROOT / "data" / "chunks.jsonl"

# scalar metadata persisted per vector (Chroma rejects None / lists — heading_path
# is joined, and every chunk field is non-null so nothing needs a fallback).
META_FIELDS = [
    "topic", "subtopic", "user_type", "insurance_type",
    "source_id", "authority", "authority_tier", "language", "url",
    "last_verified_date", "content_kind", "parent_section_id", "section_slug",
]


def load_chunks() -> list[dict]:
    return [json.loads(l) for l in CHUNKS.open(encoding="utf-8") if l.strip()]


def build_metadata(chunk: dict) -> dict:
    m = {k: chunk[k] for k in META_FIELDS}
    m["heading_path"] = " › ".join(chunk["heading_path"])
    m["embedding_model"] = MODEL_NAME
    m["embed_prefix"] = PASSAGE_PREFIX.strip()  # recorded so prefixing is verifiable
    return m


def token_report(chunks: list[dict], embedder: E5Embedder) -> None:
    tok = embedder.model.tokenizer
    max_seq = embedder.model.max_seq_length

    def e5_tokens(s: str) -> int:
        # what the model actually sees: the prefixed embed_text, with special tokens
        return len(tok(PASSAGE_PREFIX + s, add_special_tokens=True)["input_ids"])

    e5 = [e5_tokens(c["embed_text"]) for c in chunks]
    cl = [c["token_count"] for c in chunks]  # stored cl100k count from chunking

    de = [t for c, t in zip(chunks, e5) if c["language"] == "de"]
    en = [t for c, t in zip(chunks, e5) if c["language"] == "en"]

    print("\n" + "=" * 66)
    print("E5 TOKEN DISTRIBUTION vs cl100k (chunking used cl100k)")
    print("=" * 66)
    print(f"E5 model max_seq_length: {max_seq} tokens (input is truncated above this)")
    print(f"{'':14s}{'median':>8s}{'p90':>8s}{'max':>8s}")
    p90 = lambda xs: sorted(xs)[int(0.9 * (len(xs) - 1))]
    print(f"{'E5 (all)':14s}{stats.median(e5):8.0f}{p90(e5):8d}{max(e5):8d}")
    print(f"{'cl100k (all)':14s}{stats.median(cl):8.0f}{p90(cl):8d}{max(cl):8d}")
    ratio = stats.mean(e / c for e, c in zip(e5, cl) if c)
    print(f"\nmean E5/cl100k ratio: {ratio:.2f}  "
          f"(<1 => E5 counts FEWER, as expected for German compounds)")
    print(f"E5 median  DE={stats.median(de):.0f}  EN={stats.median(en):.0f}")

    for cap in (250, 500, 512, 800):
        over = sum(1 for t in e5 if t > cap)
        tag = "  <-- E5 TRUNCATION LIMIT" if cap == 512 else ""
        print(f"  E5 tokens > {cap:3d}: {over:3d} chunks{tag}")
    trunc = sum(1 for t in e5 if t > max_seq)
    verdict = "OK — no chunk is truncated" if trunc == 0 else f"WARNING — {trunc} chunks TRUNCATED"
    print(f"\nSizing check ([250/500/800] windows were cl100k heuristics): {verdict}")


def build(chunks: list[dict], embedder: E5Embedder) -> None:
    print(f"Embedding {len(chunks)} chunks with {MODEL_NAME} (passage: prefix)…")
    vecs = embedder.embed_passages([c["embed_text"] for c in chunks])
    dim = vecs.shape[1]

    store = ChromaStore()
    store.upsert(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=vecs,
        documents=[c["text"] for c in chunks],
        metadatas=[build_metadata(c) for c in chunks],
    )
    print(f"Dense: embedding dimension = {dim}, vectors stored = {store.count()}")

    sparse = SparseIndex.build(
        chunk_ids=[c["chunk_id"] for c in chunks],
        texts=[c["text"] for c in chunks],           # NOT embed_text
        metadatas=[build_metadata(c) for c in chunks],
    )
    sparse.save()
    print(f"Sparse: BM25 over `text` built for {len(chunks)} chunks, saved -> data/bm25.pkl")
    print("  tokenizer: Unicode word tokens, casefold (ß->ss), umlauts kept, "
          "compounds NOT split (whole-token matching; dense index covers sub-compounds)")


def main() -> None:
    report_only = "--report" in sys.argv
    chunks = load_chunks()
    embedder = E5Embedder()  # loads the model on first embed / tokenizer access
    if not report_only:
        build(chunks, embedder)
    token_report(chunks, embedder)


if __name__ == "__main__":
    main()
