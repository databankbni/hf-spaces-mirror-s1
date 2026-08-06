"""Pure ownership-graph logic over `ownership_edges` rows.

No DB / Streamlit deps (mirrors lib/sectors.py): `lib.data_loader` supplies the
edge list and `lib.cache` caches it. An *edge* is a dict::

    {"child": id, "parent": id, "share": float, "is_internal": bool, "parent_name": str|None}

meaning ``child`` is owned BY ``parent`` (``share`` %). ``is_internal`` is True
iff the parent itself files with us (so it has a company page / appears in
aggregates). Data is companyinfo.ge registry ownership — current snapshot, and
patchy for offshore/holding structures — so callers should treat absence as
"unknown", never "no parent".
"""
from __future__ import annotations

from collections import defaultdict

# >50% of shares = control → the parent (if it files consolidated accounts)
# already contains the subsidiary. The threshold that separates a subsidiary
# (consolidated) from an associate/JV (equity method, NOT consolidated).
CONTROL_THRESHOLD = 50.0


def parents_of(idcode: str, edges: list[dict]) -> list[dict]:
    """Corporate shareholders of ``idcode`` (highest share first)."""
    out = [e for e in edges if e["child"] == str(idcode)]
    return sorted(out, key=lambda e: -(e.get("share") or 0))


def children_of(idcode: str, edges: list[dict]) -> list[dict]:
    """Companies directly owned by ``idcode`` (highest share first)."""
    out = [e for e in edges if e["parent"] == str(idcode)]
    return sorted(out, key=lambda e: -(e.get("share") or 0))


def controlling_parent(idcode: str, edges: list[dict],
                       threshold: float = CONTROL_THRESHOLD) -> dict | None:
    """The single INTERNAL shareholder that controls ``idcode`` (>threshold), or
    None. If several qualify (rare), the largest stake wins."""
    best = None
    for e in parents_of(idcode, edges):
        if not e.get("is_internal"):
            continue
        if (e.get("share") or 0) <= threshold:
            continue
        if best is None or (e.get("share") or 0) > (best.get("share") or 0):
            best = e
    return best


def build_control_map(edges: list[dict],
                      threshold: float = CONTROL_THRESHOLD) -> dict[str, str]:
    """``{child -> parent}`` for INTERNAL controlling edges (>threshold, non-self).

    A child with multiple qualifying corporate owners keeps its largest-stake
    parent. This is the map that drives ultimate-parent resolution and the
    consolidation de-dup candidate set.
    """
    best: dict[str, dict] = {}
    for e in edges:
        if not e.get("is_internal") or e["child"] == e["parent"]:
            continue
        if (e.get("share") or 0) <= threshold:
            continue
        cur = best.get(e["child"])
        if cur is None or (e.get("share") or 0) > (cur.get("share") or 0):
            best[e["child"]] = e
    return {child: e["parent"] for child, e in best.items()}


def ultimate_parent(idcode: str, control_map: dict[str, str]) -> str:
    """Walk ``child -> parent`` to the top of the control chain (cycle-safe).

    Returns ``idcode`` itself when it has no controlling parent in the map.
    """
    idc = str(idcode)
    seen = {idc}
    while idc in control_map:
        nxt = control_map[idc]
        if nxt in seen:  # defensive: ownership cycle in the registry
            break
        seen.add(nxt)
        idc = nxt
    return idc


def group_members(root: str, control_map: dict[str, str]) -> list[str]:
    """All companies (transitively) controlled by ``root`` — its subtree.

    Excludes ``root`` itself. Cycle-safe.
    """
    kids: dict[str, list[str]] = defaultdict(list)
    for child, parent in control_map.items():
        kids[parent].append(child)
    out: list[str] = []
    seen: set[str] = set()
    stack = list(kids.get(str(root), []))
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
        stack.extend(kids.get(x, []))
    return out
