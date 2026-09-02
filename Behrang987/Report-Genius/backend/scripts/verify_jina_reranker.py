"""One-off check that jina-reranker-v3 loads and reorders a shortlist.

Run from repo root:  python -m backend.scripts.verify_jina_reranker
First run downloads the weights (network + trust_remote_code). Disables the
free-RAM guard so the load is actually attempted on memory-tight dev hosts.
"""

import os

os.environ.setdefault("REFERENCE_CROSS_ENCODER_MIN_FREE_GB", "0")

from backend.config import settings  # noqa: E402
from backend.llm.reranker import (  # noqa: E402
    _get_cross_encoder,
    cross_encoder_rerank,
)
from backend.rag.types import SearchHit  # noqa: E402


def main() -> int:
    print("model:", settings.reference_cross_encoder_model)

    # Optional: co-resident GPU check. Loads the MiniLM embedder onto the GPU
    # first (as the server does at startup), then loads jina alongside it under
    # the shared GPU lock — the historical 4 GB OOM-abort scenario.
    if os.environ.get("VERIFY_WITH_EMBEDDER") == "1":
        from backend.llm.embeddings import get_embedder

        emb = get_embedder()
        emb.embed_query("warm the embedder onto the GPU")
        print("embedder warmed (co-resident GPU load follows)")

    reranker = _get_cross_encoder()
    print(
        "loaded:", reranker is not None, type(reranker).__name__ if reranker else None
    )
    if reranker is None:
        print("FAIL: reranker did not load")
        return 1

    query = "slipped slate tiles to rear roof slope"
    off_topic = SearchHit(
        text="The kitchen units are modern with laminate worktops and appear in good order.",
        section_id="X",
        doc_id="a",
        tier="REFERENCE",
        score=0.50,
        is_scrubbed=True,
    )
    on_topic = SearchHit(
        text="Several slate tiles have slipped on the rear roof slope and require refixing.",
        section_id="X",
        doc_id="b",
        tier="REFERENCE",
        score=0.40,
        is_scrubbed=True,
    )

    out = cross_encoder_rerank(query, [off_topic, on_topic])
    for h in out:
        print(f"  rerank_score={h.rerank_score:.4f}  {h.text[:60]}")

    top = out[0]
    ok_order = top.text.startswith("Several slate")
    ok_range = all(0.0 <= h.rerank_score <= 1.0 for h in out)
    ok_spread = out[0].rerank_score > out[1].rerank_score
    if ok_order and ok_range and ok_spread:
        print("OK: matching hit reordered to front; all rerank_score in [0,1]")
        return 0
    print(f"FAIL: ok_order={ok_order} ok_range={ok_range} ok_spread={ok_spread}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
