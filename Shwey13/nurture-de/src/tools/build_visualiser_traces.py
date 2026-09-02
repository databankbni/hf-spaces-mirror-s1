"""Phase-12 offline generator. Runs the four canonical scenarios + the cross-lingual hero, extracts
the strip figures from the eval run files, and writes docs/visualiser/{traces.json,index.html}.

    py src/tools/build_visualiser_traces.py            # full: API (~$0.23) + ~10 min CPU rerank
    py src/tools/build_visualiser_traces.py --reuse    # re-inject existing traces.json into the page (no API)
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "src" / "tools"))

from visualiser_serialize import (serialize_graph_trace, chunk_summary, assemble_hero,   # noqa: E402
                                  strip_metrics, inject)
_VIZ = _ROOT / "docs" / "visualiser"

# canonical scenarios (mirror the graph-decision verification plan)
SCENARIOS = {
    "medical":  ("Is cramping at 30 weeks normal?", None),
    "missing":  ("How much Mutterschaftsgeld will I get?", None),
    "full":     ("When does Mutterschutz start if I'm due 2027-03-15 and employed?",
                 {"employment_status": "employed", "due_date": "2027-03-15"}),
    "retry":    ("What are the specific Mutterschutz rules for civil servants (Beamtinnen) in Bavaria?",
                 {"employment_status": "civil-servant", "due_date": "2027-03-15"}),
}
HERO_QUERY = "When do I have to tell my employer I'm pregnant?"
HERO_ANSWER_SOURCE = "fam_mutterschutz"
HERO_FALLBACKS = [   # golden cross-lingual cases, if the primary query doesn't reproduce rank-6
    ("When do I notify my employer about my pregnancy?", "fam_mutterschutz"),
    ("employer notification pregnancy deadline", "fam_mutterschutz"),
]


def _scenario_dict(state: dict) -> dict:
    tr = state["trace"]; g = serialize_graph_trace(tr)
    term = None
    if tr.final_node in ("safe_referral", "request_attributes"):
        term = len([n for n in tr.nodes])            # nodes visited before ending
    resp = state.get("response") or {}
    answer = None
    if resp.get("kind") == "plan":
        pl = resp["plan"]; answer = {"summary": pl.get("summary", ""),
                                     "citations": [c["chunk_id"] for c in pl.get("citations", [])]}
    return {"path": state["path"], "node_timings": g["node_timings"], "final_node": tr.final_node,
            "terminated_after": term, "retries": tr.retries,
            "retrievals": [{"query": r["query"], "final_context": r["final_context"]}
                           for r in g["retrievals"]],
            "answer": answer}


def _build_hero() -> dict:
    import graph
    from retrieval import Retriever
    R = graph.generate._get_retriever()
    for q, ans in [(HERO_QUERY, HERO_ANSWER_SOURCE)] + HERO_FALLBACKS:
        before, brt = R.search(q, k=20, filters=None, mode="hybrid", pool=20, trace=True)
        brt._chunks = {c.chunk_id: c for c in before}     # attach for pure assemble_hero
        after, _ = graph._retrieve_reranked(q, None)
        try:
            cap = ("Retrieved at rank {r}, cut by the top-4 window. The system reported no "
                   "information while it was holding the answer.")
            hero = assemble_hero(q, brt, after, ans, cap)
            hero["caption"] = cap.format(r=hero["before"]["answer_rank"])
            return hero
        except ValueError:
            continue
    raise SystemExit("no hero query reproduced the rank-6 discard; inspect traces manually")


def build_traces() -> dict:
    import graph
    scenarios = {}
    for key, (q, profile) in SCENARIOS.items():
        scenarios[key] = _scenario_dict(graph.run(q, profile=profile))
    hero = _build_hero()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT,
                            capture_output=True, text=True).stdout.strip()
    return {"scenarios": scenarios, "hero": hero, "metrics": strip_metrics(),
            "generated_at": str(date.today()), "commit": commit, "max_retries": graph.MAX_RETRIES}


def write_outputs(traces: dict, out_dir=None) -> None:
    viz = out_dir or _VIZ
    viz.mkdir(parents=True, exist_ok=True)
    (viz / "traces.json").write_text(json.dumps(traces, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    tpl = (_VIZ / "template.html").read_text(encoding="utf-8")
    (viz / "index.html").write_text(inject(tpl, traces), encoding="utf-8")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true", help="re-inject existing traces.json (no API)")
    args = ap.parse_args(argv)
    if args.reuse:
        traces = json.loads((_VIZ / "traces.json").read_text(encoding="utf-8"))
        import graph as _g
        traces.setdefault("max_retries", _g.MAX_RETRIES)
    else:
        traces = build_traces()
    write_outputs(traces)
    print("wrote", _VIZ / "traces.json", "and", _VIZ / "index.html")


if __name__ == "__main__":
    main()
