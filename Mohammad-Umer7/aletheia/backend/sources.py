"""Source engine: registry, ingestion with per-source node attribution, trust-scoped
ask, and surgical retraction. The heart of Aletheia.

Attribution strategy (verified against cognee 1.2.2):
- PRIMARY: cognee's own relational graph ledger (`nodes` table) maps every graph
  node to the dataset that produced it — exact even when entities are shared.
- FALLBACK + cross-check: snapshot diff of graph node IDs (after − before ingest).
Trust scoping: ask() only ever recalls from datasets whose source is trusted, so
retracted knowledge is structurally unreachable, not merely deleted.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from backend import changelog, llm_direct, memory
from backend.seed_data import DEMO_QUESTION, SEED_SOURCES  # noqa: F401 (re-exported)

REGISTRY_PATH = memory.DATA_DIR / "registry.json"
SOURCE_HUE_COUNT = 4  # frontend cycles 4 source hues by color_index

# Node types that are document plumbing rather than knowledge — the frontend dims
# them and they carry source_id=null in /api/graph. Tuned from real seed output.
STRUCTURAL_TYPES = {
    "TextDocument",
    "Document",
    "DocumentChunk",
    "TextSummary",
    "NodeSet",
}

ANSWER_SYSTEM_PROMPT = (
    "You are Aletheia, a research assistant that answers strictly from the memory "
    "context you are given. Answer in 2-4 plain sentences. If the context indicates "
    "a claim was retracted, fabricated, or unsupported, say so plainly and do not "
    "repeat the discredited figures as if they were credible. If the context does "
    "not cover the question, say you have no supporting memories."
)

_mutation_lock = asyncio.Lock()  # ingest/retract are strictly one-at-a-time


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:40] or "source"


# --- registry ---------------------------------------------------------------

def _load_registry() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(registry: dict[str, dict]) -> None:
    """Atomic write — the API serves reads while background ingestion mutates."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=REGISTRY_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, REGISTRY_PATH)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def list_sources() -> list[dict]:
    return list(_load_registry().values())


def backfill_raw_text() -> None:
    """Older registry entries predate raw_text; recover it from the seed content.
    Runs once at API startup — a no-op unless something is missing."""
    registry = _load_registry()
    changed = False
    for sid, source in registry.items():
        if not source.get("raw_text"):
            spec = next((s for s in SEED_SOURCES if s["id"] == sid), None)
            if spec:
                source["raw_text"] = spec["text"]
                changed = True
    if changed:
        _save_registry(registry)


def get_source(source_id: str) -> Optional[dict]:
    return _load_registry().get(source_id)


def trusted_sources(registry: Optional[dict] = None) -> list[dict]:
    registry = registry if registry is not None else _load_registry()
    return [s for s in registry.values() if s["trust"] == "trusted" and s["status"] == "ready"]


# --- cognee graph ledger (exact node -> dataset attribution) -----------------

async def _dataset_ids_by_name() -> dict[str, str]:
    from sqlalchemy import select
    from cognee.infrastructure.databases.relational import get_relational_engine
    from cognee.modules.data.models.Dataset import Dataset

    engine = get_relational_engine()
    async with engine.get_async_session() as session:
        rows = (await session.execute(select(Dataset))).scalars().all()
    return {row.name: str(row.id) for row in rows}


async def _ledger_nodes(dataset_name: str) -> Optional[list[dict]]:
    """[{id, label, type}] for one dataset from cognee's relational graph ledger.
    Returns None if the ledger is unavailable so callers fall back to snapshot diff.
    """
    try:
        from sqlalchemy import select
        from cognee.infrastructure.databases.relational import get_relational_engine
        from cognee.modules.graph.models.Node import Node as NodeRow

        dataset_id = (await _dataset_ids_by_name()).get(dataset_name)
        if dataset_id is None:
            return None
        engine = get_relational_engine()
        async with engine.get_async_session() as session:
            rows = (
                (
                    await session.execute(
                        select(NodeRow).where(NodeRow.dataset_id == uuid.UUID(dataset_id))
                    )
                )
                .scalars()
                .all()
            )
        return [
            {"id": str(row.slug), "label": row.label or "", "type": row.type or "Node"}
            for row in rows
        ]
    except Exception as exc:
        print(f"  [ledger] unavailable ({type(exc).__name__}: {exc}); using snapshot diff")
        return None


# --- graph snapshots + normalization -----------------------------------------

def _node_parts(node: Any) -> tuple[str, dict]:
    """get_graph_data() nodes are (id, props) tuples; be tolerant of variants."""
    if isinstance(node, (tuple, list)) and len(node) >= 2:
        return str(node[0]), dict(node[1] or {})
    if isinstance(node, dict):
        return str(node.get("id")), node
    return str(getattr(node, "id", node)), dict(getattr(node, "properties", {}) or {})


def _edge_parts(edge: Any) -> tuple[str, str, str]:
    if isinstance(edge, (tuple, list)) and len(edge) >= 3:
        return str(edge[0]), str(edge[1]), str(edge[2])
    if isinstance(edge, dict):
        return str(edge.get("source")), str(edge.get("target")), str(edge.get("label", "related"))
    return (
        str(getattr(edge, "source", "")),
        str(getattr(edge, "target", "")),
        str(getattr(edge, "label", "related")),
    )


async def graph_node_ids() -> set[str]:
    nodes, _ = await memory.graph_data()
    return {_node_parts(n)[0] for n in nodes}


def _node_label(props: dict, node_id: str) -> str:
    label = props.get("name") or props.get("title")
    if not label:
        text = props.get("text") or props.get("description") or ""
        label = (text[:48] + "...") if len(text) > 48 else text
    return str(label) if label else node_id[:8]


async def graph_snapshot() -> dict:
    """Normalized graph for the frontend: nodes hue-attributed to their source."""
    nodes, edges = await memory.graph_data()
    registry = _load_registry()
    node_to_source: dict[str, str] = {}
    for source in registry.values():
        for nid in source.get("node_ids", []):
            node_to_source.setdefault(nid, source["id"])

    out_nodes = []
    for raw in nodes:
        nid, props = _node_parts(raw)
        ntype = str(props.get("type") or "Node")
        source_id = None if ntype in STRUCTURAL_TYPES else node_to_source.get(nid)
        source = registry.get(source_id) if source_id else None
        out_nodes.append(
            {
                "id": nid,
                "label": _node_label(props, nid),
                "type": ntype,
                "description": str(props.get("description") or "")[:280],
                "source_id": source_id,
                "trust": source["trust"] if source else None,
            }
        )

    known = {n["id"] for n in out_nodes}
    out_links = []
    for raw in edges:
        s, t, label = _edge_parts(raw)
        if s in known and t in known:
            out_links.append({"source": s, "target": t, "label": label})
    return {"nodes": out_nodes, "links": out_links}


# --- ingest -------------------------------------------------------------------

async def ingest_source(
    title: str,
    kind: str,
    text: str,
    *,
    source_id: Optional[str] = None,
    check_conflicts: bool = True,
) -> dict:
    """Ingest one source into its own dataset and attribute its graph nodes.
    LLM-heavy: 20-90s. Strictly serialized via the mutation lock.
    After ingestion, one direct Groq call checks whether the new source disputes
    any trusted source (skipped during demo seeding — the seed sources are the
    baseline worldview, conflicts are for what arrives afterwards).
    """
    async with _mutation_lock:
        registry = _load_registry()
        sid = source_id or _slugify(title)
        if sid in registry:
            raise ValueError(f"source '{sid}' already exists")
        dataset = f"src_{sid}"

        source = {
            "id": sid,
            "title": title,
            "kind": kind,
            "dataset": dataset,
            "trust": "trusted",
            "status": "ingesting",
            "node_ids": [],
            "color_index": len(registry) % SOURCE_HUE_COUNT,
            "added_at": _now(),
            "retracted_at": None,
            "reason": None,
            "error": None,
            "raw_text": text,
            "conflicts": [],
        }
        registry[sid] = source
        _save_registry(registry)

        try:
            before = await graph_node_ids()
            await memory.remember(text, dataset)
            after = await graph_node_ids()
            diff_ids = after - before

            ledger = await _ledger_nodes(dataset)
            if ledger:
                ledger_ids = {n["id"] for n in ledger}
                overlap = len(ledger_ids & after)
                print(
                    f"  [attribution] {sid}: ledger={len(ledger_ids)} diff={len(diff_ids)} "
                    f"ledger-in-graph={overlap}"
                )
                # The ledger is exact per-dataset membership — but only trust it if
                # its IDs actually live in the graph engine's ID space.
                node_ids = ledger_ids if overlap > 0 else diff_ids
            else:
                node_ids = diff_ids

            source["node_ids"] = sorted(node_ids)
            source["status"] = "ready"
        except Exception as exc:
            source["status"] = "error"
            source["error"] = f"{type(exc).__name__}: {exc}"
            registry[sid] = source
            _save_registry(registry)
            raise

        # THE wow factor: does this new source dispute anything Aletheia trusts?
        # detect_conflicts never raises — a failed check must not fail ingestion.
        if check_conflicts and os.getenv("ALETHEIA_CONFLICT_CHECK", "1") != "0":
            others = [
                s
                for s in registry.values()
                if s["id"] != sid and s["trust"] == "trusted" and s["status"] == "ready"
            ]
            source["conflicts"] = await llm_direct.detect_conflicts(source, others)
            if source["conflicts"]:
                print(f"  [conflicts] {sid} disputes: {source['conflicts']}")

        registry[sid] = source
        _save_registry(registry)

    changelog.append_entry(
        {
            "type": "ingested",
            "source_id": sid,
            "title": title,
            "kind": kind,
            "nodes_added": len(source["node_ids"]),
        }
    )
    return source


# --- retract (the money shot) ---------------------------------------------------

async def retract_source(source_id: str, reason: str, *, reenrich: bool = True) -> dict:
    """forget() the source's dataset, measure which nodes actually died, log the
    belief change. With reenrich=True, improve() runs over each remaining trusted
    dataset inline; the API instead schedules reenrich_remaining() in the background
    so the retraction animation is never blocked.
    """
    async with _mutation_lock:
        registry = _load_registry()
        source = registry.get(source_id)
        if source is None:
            raise KeyError(f"unknown source '{source_id}'")
        if source["trust"] == "retracted":
            raise ValueError(f"source '{source_id}' is already retracted")

        before_nodes, before_edges = await memory.graph_data()
        before = {_node_parts(n)[0] for n in before_nodes}
        await memory.forget_dataset(source["dataset"])
        after = await graph_node_ids()
        removed = sorted(before - after)
        removed_set = set(removed)
        links_removed = 0
        for raw in before_edges:
            s, t, _ = _edge_parts(raw)
            if s in removed_set or t in removed_set:
                links_removed += 1

        source["trust"] = "retracted"
        source["retracted_at"] = _now()
        source["reason"] = reason
        registry[source_id] = source
        _save_registry(registry)

    entry = changelog.append_entry(
        {
            "type": "retraction",
            "source_id": source_id,
            "title": source["title"],
            "reason": reason,
            "nodes_removed": len(removed),
            "links_removed": links_removed,
            "answers_rederived": True,
        }
    )

    if reenrich:
        await reenrich_remaining()

    return {
        "source": source,
        "removed_node_ids": removed,
        "nodes_removed": len(removed),
        "links_removed": links_removed,
        "changelog_entry": entry,
    }


async def reenrich_remaining() -> None:
    """Re-enrichment pass after a retraction: improve() every remaining trusted
    dataset so the surviving knowledge re-settles. Failures are non-fatal (a rate
    limit here must not un-retract anything).
    """
    for source in trusted_sources():
        try:
            await memory.improve(source["dataset"])
        except Exception as exc:
            print(f"  [improve] {source['id']} skipped: {type(exc).__name__}: {exc}")


# --- ask ------------------------------------------------------------------------

def _completion_text(entries: list[Any]) -> Optional[str]:
    for e in entries:
        if getattr(e, "kind", None) == "graph_completion" and getattr(e, "text", None):
            return e.text
    for e in entries:
        text = memory.entry_text(e)
        if text:
            return text
    return None


async def ask(question: str) -> dict:
    """recall() scoped to trusted datasets only. Citations come from per-entry
    dataset provenance plus the label-match heuristic; the cited sources' nodes
    are returned for the constellation's green pulse.
    """
    registry = _load_registry()
    scoped = trusted_sources(registry)
    datasets = [s["dataset"] for s in scoped]
    empty = {
        "answer": None,
        "cited_sources": [],
        "highlight_node_ids": [],
        "scoped_datasets": datasets,
    }
    if not datasets:
        return empty

    try:
        entries = await memory.recall_raw(
            question, datasets, system_prompt=ANSWER_SYSTEM_PROMPT
        )
    except Exception as exc:
        if type(exc).__name__ == "DatasetNotFoundError":
            return empty
        raise

    answer = _completion_text(entries)
    if not answer:
        return empty

    provenance = {
        getattr(e, "dataset_name", None) for e in entries if getattr(e, "dataset_name", None)
    }

    answer_lower = answer.lower()
    cited, highlight = [], []
    for source in scoped:
        via_provenance = source["dataset"] in provenance
        via_labels = await _labels_match(source, answer_lower)
        if via_provenance or via_labels:
            cited.append(
                {
                    "id": source["id"],
                    "title": source["title"],
                    "kind": source["kind"],
                    "color_index": source["color_index"],
                }
            )
            highlight.extend(source["node_ids"])

    return {
        "answer": answer,
        "cited_sources": cited,
        "highlight_node_ids": sorted(set(highlight)),
        "scoped_datasets": datasets,
    }


async def _labels_match(source: dict, answer_lower: str) -> bool:
    """Does any of this source's node labels (entity names) appear in the answer?"""
    ledger = await _ledger_nodes(source["dataset"])
    labels = (
        [n["label"] for n in ledger]
        if ledger
        else await _graph_labels_for(source.get("node_ids", []))
    )
    for label in labels:
        label = (label or "").strip().lower()
        if len(label) >= 4 and label in answer_lower:
            return True
    return False


async def _graph_labels_for(node_ids: list[str]) -> list[str]:
    wanted = set(node_ids)
    nodes, _ = await memory.graph_data()
    labels = []
    for raw in nodes:
        nid, props = _node_parts(raw)
        if nid in wanted:
            labels.append(_node_label(props, nid))
    return labels


# --- demo seed --------------------------------------------------------------------

async def reset_all() -> None:
    """Wipe cognee memory + registry + changelog. Full clean slate."""
    async with _mutation_lock:
        try:
            await memory.forget_everything()
        except Exception as exc:
            print(f"  [reset] cognee wipe skipped ({type(exc).__name__}: {exc})")
        for path in (REGISTRY_PATH, changelog.CHANGELOG_PATH):
            if path.exists():
                path.unlink()


async def seed_demo(
    include_retraction: bool = False,
    progress: Callable[[str], None] = print,
) -> list[dict]:
    """Reset, then ingest the demo worldview strictly one at a time. By default
    the retraction notice is NOT included — it arrives live so Aletheia's
    conflict detection happens on camera."""
    await reset_all()
    chosen = [
        s for s in SEED_SOURCES if include_retraction or s["id"] != "jch_retraction"
    ]
    seeded = []
    for i, spec in enumerate(chosen, 1):
        progress(f"[seed {i}/{len(chosen)}] ingesting '{spec['title']}' (20-90s)...")
        source = await ingest_source(
            spec["title"], spec["kind"], spec["text"], source_id=spec["id"],
            check_conflicts=False,
        )
        progress(f"[seed {i}/{len(chosen)}] done — {len(source['node_ids'])} nodes attributed")
        seeded.append(source)
    return seeded
