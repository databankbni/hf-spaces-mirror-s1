"""Phase-12 pure helpers: serialise traces, extract eval figures, assemble the hero, inject the
page data. No API and no models — all unit-testable. The generator (build_visualiser_traces.py)
is the only thing that touches the graph, the retriever, and the eval run files."""
from __future__ import annotations
from dataclasses import asdict


def chunk_summary(chunk) -> dict:
    m = chunk.metadata or {}
    return {"chunk_id": chunk.chunk_id, "source_id": m.get("source_id", ""),
            "language": m.get("language", ""), "authority": m.get("authority", ""),
            "last_verified": m.get("last_verified_date", ""), "score": round(float(chunk.score), 4)}


def serialize_retrieval_trace(rt) -> dict:
    d = asdict(rt)                       # RetrievalTrace is a plain dataclass of lists/dicts
    return d


def serialize_graph_trace(tr) -> dict:
    return {"nodes": tr.nodes, "branch_intent": tr.branch_intent,
            "branch_profile": tr.branch_profile, "retries": tr.retries,
            "final_node": tr.final_node, "filter_starved": tr.filter_starved,
            "node_timings": tr.node_timings,
            "retrievals": [serialize_retrieval_trace(r) for r in tr.retrievals]}


import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "eval"))     # reuse rescore's pass/label logic, do not reimplement


def answerable_figures(run_path, config: str | None = None, corrected: bool = False) -> dict:
    recs = json.loads(Path(run_path).read_text(encoding="utf-8"))
    rows = [r for r in recs if r.get("answerable")]
    if config is not None:
        rows = [r for r in rows if r.get("config") == config]
    if corrected:
        from rescore import current_labels, recompute_pass       # eval/rescore.py
        labels = current_labels()
        passes = sum(recompute_pass(r, labels.get(r["id"], r["expected"])) for r in rows)
    else:
        passes = sum(bool(r["pass"]) for r in rows)
    recalls = [r["recall"] for r in rows if r.get("recall") is not None]
    recall = round(sum(recalls) / len(recalls), 2) if recalls else 0.0
    n = len(rows)
    return {"n": n, "passes": passes, "pct": round(100 * passes / n) if n else 0, "recall": recall}


def strip_metrics() -> dict:
    base = answerable_figures(_ROOT / "eval" / "last_run.json", config="hybrid_rerank")
    p8b = answerable_figures(_ROOT / "eval" / "last_run_phase8b.json")
    p8b_c = answerable_figures(_ROOT / "eval" / "last_run_phase8b.json", corrected=True)
    src_base = "eval/last_run.json (hybrid_rerank, answerable, n=%d)" % base["n"]
    src_after = "eval/last_run_phase8b.json (answerable, n=%d); py eval/rescore.py" % p8b["n"]
    bm = {"before": base["pct"], "after": p8b["pct"], "source": src_base + " -> " + src_after}
    bl = {"before": p8b["pct"], "after": p8b_c["pct"],
          "source": "eval/phase8b_findings.md l.89; py eval/rescore.py"}
    return {
        "basis": "hybrid_rerank, answerable subset, n=%d (same ids both runs)" % base["n"],
        "recall": {"before": base["recall"], "after": p8b["recall"],
                   "source": src_base + " -> " + src_after},
        "behaviour_measured": bm,
        "behaviour_labels_fixed": bl,
        "cross_lingual_recovery": {"recovered": 5, "of": 6,
                                   "source": "BUILD_JOURNAL.md pool-probe (P8 retraction)"},
    }


_PLACEHOLDER = "/*__TRACES__*/"


def _rank_of_source(items_source_ids: list[str], source_id: str) -> int:
    for i, sid in enumerate(items_source_ids):
        if sid == source_id:
            return i
    return -1


def assemble_hero(query: str, before_rt, after_chunks, answer_source_id: str, caption: str) -> dict:
    # `before_rt._chunks` maps chunk_id -> RetrievedChunk (attached by the generator so this stays
    # pure). Build a ranked, display-only view; find the answer by source_id (chunk suffix varies).
    def item(rank, cid):
        c = before_rt._chunks.get(cid)
        base = chunk_summary(c) if c else {"chunk_id": cid, "source_id": "", "language": "",
                                           "authority": "", "last_verified": "", "score": 0.0}
        return {"rank": rank, **base}
    before_items = [item(i, f["chunk_id"]) for i, f in enumerate(before_rt.fused)]
    before_rank = _rank_of_source([it["source_id"] for it in before_items], answer_source_id)
    after_items = [{"rank": i, **chunk_summary(c)} for i, c in enumerate(after_chunks)]
    after_rank = _rank_of_source([it["source_id"] for it in after_items], answer_source_id)
    if not (before_rank > 3 and after_rank == 0):
        raise ValueError(f"hero invariant failed: before_rank={before_rank} (want >3), "
                         f"after_rank={after_rank} (want 0) for {answer_source_id!r}")
    return {"query": query, "answer_source_id": answer_source_id, "caption": caption,
            "before": {"pool": 20, "cutoff": 4, "answer_rank": before_rank,
                       "items": before_items[:max(before_rank + 1, 4)]},
            "after": {"pool": 100, "reranked": True, "answer_rank": after_rank,
                      "items": after_items[:4]}}


def inject(template: str, traces: dict) -> str:
    if _PLACEHOLDER not in template:
        raise ValueError("template is missing the /*__TRACES__*/ placeholder")
    return template.replace(_PLACEHOLDER, json.dumps(traces, ensure_ascii=False))
