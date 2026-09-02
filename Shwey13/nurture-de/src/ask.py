"""Ask NurtureDE a question — the interactive CLI, for using the system as a user
instead of reading JSON.

    py src/ask.py "Wann beginnt die Mutterschutzfrist?"
    py src/ask.py "How much maternity pay will I get?" --user-type employee --insurance-type statutory
    py src/ask.py "..." --rerank            # add the cross-encoder rerank (the best eval config)
    py src/ask.py "..." --trace             # full pipeline detail (dense/sparse/RRF ranks, timings)
    py src/ask.py                            # interactive loop

Shows the answer (with its inline citations and Sources block) AND the chunks that were
retrieved, with scores — so when the answer is wrong you can see whether retrieval was the
cause. Generation is a real Claude Opus 5 call, so each question costs a few cents.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

# load the key from .env if the environment doesn't already have it (never printed)
if not os.environ.get("ANTHROPIC_API_KEY"):
    envf = _ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()

import generate  # noqa: E402
from retrieval import Retriever, RERANK_POOL  # noqa: E402  (RERANK_POOL=100, see retrieval.py)

K_RETRIEVE = 10
_reranker = None


def _rerank(question, hits):
    global _reranker
    if _reranker is None:
        from retrieval import Reranker
        _reranker = Reranker()
    return _reranker.rerank(question, hits)


def ask(R: Retriever, question: str, filters: dict, rerank: bool, trace: bool) -> None:
    # On the rerank path, pull a wide RERANK_POOL of candidates so the cross-encoder can reach a
    # correct chunk that RRF buried below the default top-10 (the cross-lingual case). Then rerank
    # and keep the top K_RETRIEVE. Without rerank, retrieve the normal top-K_RETRIEVE.
    k = RERANK_POOL if rerank else K_RETRIEVE
    result = R.search(question, k=k, filters=filters or None, mode="hybrid",
                      pool=(RERANK_POOL if rerank else None), trace=trace)
    hits, tr = (result if trace else (result, None))
    if rerank:
        hits = _rerank(question, hits)[:K_RETRIEVE]

    print("\n" + "─" * 78)
    print(f"RETRIEVED (top {min(K_RETRIEVE, len(hits))}{' · reranked' if rerank else ''}"
          + (f" · filters={filters}" if filters else "") + "):")
    for i, h in enumerate(hits):
        print(f"  {i:>2}. {h.score:.3f}  [{h.metadata.get('language','?')}] "
              f"{h.source_id:30.30} {h.heading_path[:46]}")

    ctx = hits[:generate.K_CONTEXT]
    res = generate.answer(question, ctx)

    print("\n" + "─" * 78 + "\nANSWER:\n")
    print("[declined by the safety classifier]" if res.refused_by_classifier else res.answer)
    print("\n" + "─" * 78)
    print(f"context: {len(res.context_chunk_ids)} chunks / {res.context_tokens} cl100k tokens"
          f"  |  usage in/out={res.usage['input_tokens']}/{res.usage['output_tokens']}"
          f"  |  cost=${res.cost_usd:.4f}  |  stop={res.stop_reason}")

    if trace and tr is not None:
        print("\nTRACE:")
        print("  dense top-5:  " + ", ".join(f"{d['similarity']:.3f}@{d['rank']}" for d in tr.dense[:5]))
        print("  sparse top-5: " + ", ".join(f"{s['bm25']:.2f}@{s['rank']}" for s in tr.sparse[:5]))
        print(f"  in both indexes: {len(tr.both)}   filtered out: {len(tr.filter_exclusions)}"
              + (f"   UNDERFILLED: {tr.underfilled}" if tr.underfilled else ""))
        t = tr.timings_ms
        print("  timings ms: " + "  ".join(f"{k}={t[k]:.0f}" for k in
              ("dense_ms", "sparse_ms", "filter_ms", "fusion_ms", "total_ms") if k in t))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Ask NurtureDE a grounded, cited question.")
    ap.add_argument("question", nargs="*", help="the question (omit for an interactive loop)")
    ap.add_argument("--user-type", help="filter: employee | self-employed | civil-servant | student | unemployed")
    ap.add_argument("--insurance-type", help="filter: statutory | non-statutory | private | none")
    ap.add_argument("--rerank", action="store_true", help="apply the cross-encoder reranker")
    ap.add_argument("--trace", action="store_true", help="print full pipeline detail")
    args = ap.parse_args()

    filters = {}
    if args.user_type:
        filters["user_type"] = args.user_type
    if args.insurance_type:
        filters["insurance_type"] = args.insurance_type

    R = Retriever()  # one model load, reused across questions
    if args.question:
        ask(R, " ".join(args.question), filters, args.rerank, args.trace)
        return
    print("NurtureDE — ask a question (empty line or Ctrl-C to quit). Not medical/legal advice.")
    try:
        while True:
            q = input("\nAsk> ").strip()
            if not q:
                break
            ask(R, q, filters, args.rerank, args.trace)
    except (EOFError, KeyboardInterrupt):
        print()


if __name__ == "__main__":
    main()
