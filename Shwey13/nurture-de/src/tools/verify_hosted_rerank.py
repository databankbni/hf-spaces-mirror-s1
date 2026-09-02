"""Pre-ship gate — does the HOSTED reranker still recover the cross-lingual cases?

The headline finding is that reranking pulls the correct German chunk into the top-4 on English
questions about German-only rules. If a hosted reranker ranks differently from bge-reranker-v2-m3,
that finding stops reproducing — and we need to know BEFORE the URL is public, not after.

This runs the four EN→DE golden cases (L24, L28, L29, L30 — all expect `fam_mutterschutz`) through
the real hybrid retrieval (pool 100) + the hosted reranker, and asserts the German source reaches
the reranked top-4. Exits non-zero if any case fails (so it gates a deploy).

    # JINA_API_KEY (or COHERE_API_KEY + RERANK_PROVIDER=cohere) must be set in the env
    py src/tools/verify_hosted_rerank.py
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "src" / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import graph                                   # noqa: E402
from hosted_rerank import make_reranker        # noqa: E402

CASES = ("L24", "L28", "L29", "L30")
EXPECT_SOURCE = "fam_mutterschutz"


def _queries() -> dict[str, str]:
    out = {}
    for line in (_ROOT / "eval" / "golden.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("id") in CASES:
            out[r["id"]] = r["question"]
    return out


def main() -> None:
    graph._reranker = make_reranker()          # hosted if a key is set (else local bge)
    rr = type(graph._reranker).__name__
    provider = getattr(graph._reranker, "provider", "local-bge")
    print(f"reranker: {rr} (provider={provider})\n")

    qs = _queries()
    failed = []
    for cid in CASES:
        q = qs.get(cid)
        chunks, _ = graph._retrieve_reranked(q, None)   # no filters — test the reranker itself
        top = [c.metadata.get("source_id") for c in chunks]
        ok = EXPECT_SOURCE in top
        rank = top.index(EXPECT_SOURCE) if ok else None
        print(f"{cid}: {'PASS' if ok else 'FAIL'}  {EXPECT_SOURCE} "
              f"{'at rank ' + str(rank) if ok else 'NOT in top-' + str(len(top))}")
        print(f"     top-{len(top)}: {top}")
        if not ok:
            failed.append(cid)

    print()
    if failed:
        print(f"❌ {len(failed)}/{len(CASES)} cross-lingual cases did NOT recover into top-4: "
              f"{failed}. The hosted reranker does not reproduce the finding — switch provider "
              f"(RERANK_PROVIDER=cohere) and re-run, or do not ship.")
        sys.exit(1)
    print(f"✅ all {len(CASES)} cross-lingual cases recovered {EXPECT_SOURCE} into the top-4. "
          f"The headline finding reproduces on the hosted reranker.")


if __name__ == "__main__":
    main()
