"""Seed the demo worldview (study + news + meta-analysis), write the debug
visualization, and probe everything we need to verify (attribution, entry
shapes, ask()). The retraction notice is NOT seeded — it arrives live via the
UI's "A retraction notice arrives..." button so the conflict card lands on camera.

Usage: python scripts/seed.py [--with-retraction] [--probe-only]
  --with-retraction  also ingest the retraction notice (skips the live-demo beat)
  --probe-only       skip re-ingestion; run the probes against already-seeded data
"""
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import memory, sources
from backend.seed_data import DEMO_QUESTION


async def main(include_retraction: bool, probe_only: bool) -> None:
    if probe_only:
        print("=== PROBE-ONLY: using existing seeded data ===")
    else:
        print("=== SEED: resetting + ingesting sources (strictly sequential) ===")
        await sources.seed_demo(include_retraction=include_retraction)

    print("\n=== REGISTRY ===")
    registry = {s["id"]: s for s in sources.list_sources()}
    for s in registry.values():
        print(
            f"  {s['id']:<16} kind={s['kind']:<13} trust={s['trust']:<8} "
            f"status={s['status']:<6} nodes={len(s['node_ids'])} color={s['color_index']}"
        )

    print("\n=== LEDGER CHECK (exact attribution vs registry) ===")
    graph_ids = await sources.graph_node_ids()
    for s in registry.values():
        ledger = await sources._ledger_nodes(s["dataset"])
        if ledger is None:
            print(f"  {s['id']}: ledger UNAVAILABLE")
        else:
            lids = {n["id"] for n in ledger}
            reg_ids = set(s["node_ids"])
            print(
                f"  {s['id']}: ledger={len(lids)} registry={len(reg_ids)} "
                f"ledger-in-graph={len(lids & graph_ids)} ledger-vs-registry-overlap={len(lids & reg_ids)}"
            )

    print("\n=== GRAPH SNAPSHOT (normalized) ===")
    snap = await sources.graph_snapshot()
    print(f"  nodes={len(snap['nodes'])} links={len(snap['links'])}")
    type_census = Counter(n["type"] for n in snap["nodes"])
    print(f"  node types: {dict(type_census)}")
    unattributed = [
        n for n in snap["nodes"] if n["source_id"] is None and n["type"] not in sources.STRUCTURAL_TYPES
    ]
    print(f"  non-structural nodes without a source: {len(unattributed)}")
    for n in unattributed[:8]:
        print(f"    ? {n['type']:<20} {n['label'][:60]}")

    print("\n=== DEBUG VISUALIZATION (cognee built-in) ===")
    html_path = memory.REPO_ROOT / "debug_graph.html"
    await memory.write_debug_visualization(str(html_path), dataset=None)
    print(f"  wrote {html_path} ({html_path.stat().st_size:,} bytes)")

    print("\n=== PROBE: ask(DEMO_QUESTION) ===")
    print(f"  Q: {DEMO_QUESTION}")
    raw_entries = await memory.recall_raw(
        DEMO_QUESTION,
        [s["dataset"] for s in sources.trusted_sources()],
        system_prompt=sources.ANSWER_SYSTEM_PROMPT,
    )
    print(f"  recall returned {len(raw_entries)} entries:")
    for e in raw_entries:
        print(
            f"    kind={getattr(e, 'kind', '?'):<18} dataset={getattr(e, 'dataset_name', None)!s:<22} "
            f"text={memory.entry_text(e)[:90]!r}"
        )

    result = await sources.ask(DEMO_QUESTION)
    print(f"\n  ANSWER: {result['answer']}")
    print(f"  cited: {[c['id'] for c in result['cited_sources']]}")
    print(f"  highlight nodes: {len(result['highlight_node_ids'])}")
    print(f"  scoped datasets: {result['scoped_datasets']}")

    print("\nSEED COMPLETE")


if __name__ == "__main__":
    asyncio.run(
        main(
            include_retraction="--with-retraction" in sys.argv,
            probe_only="--probe-only" in sys.argv,
        )
    )
