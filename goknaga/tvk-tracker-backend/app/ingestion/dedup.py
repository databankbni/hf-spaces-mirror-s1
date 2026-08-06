"""Retroactive duplicate merger.

The live ingestion gate keys dedup on category+location+date, so the SAME
event written with a different location string ('Gummidipoondi' vs
'Thiruvallur' vs blank for one Tiruvallur event) slipped through as 2-3
separate incidents — inflating the crime counts the meter reads.

This pass finds those clusters in the existing corpus and merges each into a
single keeper, RETRACTING the rest (never deleting). It reuses the exact same
title-similarity guard as live ingestion (_title_jaccard), so two genuinely
DIFFERENT events in the same district on the same day are never merged —
over-merging would HIDE a real incident, which is worse than a duplicate.

Keeper selection: the most-verified row (multi-source > press/admin > single >
pending), then the one with the most sources. The keeper inherits the union of
all sources in the cluster (so it can even upgrade to multi-source-verified).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from app.database import get_db
from app.ingestion.ai_processor import _title_jaccard, _GENERIC_TITLE_CATS

logger = logging.getLogger(__name__)

# Verification rank for picking the keeper in a duplicate cluster.
_VRANK = {
    "multi_source_verified": 5,
    "press_verified": 4,
    "admin_verified": 4,
    "single_source": 2,
    "pending_verification": 1,
}


def _within_a_day(a_date: str, b_date: str) -> bool:
    da, db_ = (a_date or "")[:10], (b_date or "")[:10]
    if not da or not db_:
        return False
    try:
        return abs((date.fromisoformat(da) - date.fromisoformat(db_)).days) <= 1
    except Exception:
        return False


def _are_duplicates(a: dict, b: dict) -> bool:
    """Same event? Same category + within ±1 day + similar headline. The
    title threshold relaxes only when the district matches."""
    if a.get("category") != b.get("category"):
        return False
    # Generic-title infra categories (power cuts etc.) recur with the same
    # wording for different events — don't fuzzy-merge them (see ai_processor).
    if a.get("category") in _GENERIC_TITLE_CATS:
        return False
    if not _within_a_day(a.get("incident_date"), b.get("incident_date")):
        return False
    sim = _title_jaccard(a.get("title") or "", b.get("title") or "")
    same_dist = bool(a.get("district")) and a.get("district") == b.get("district")
    return sim >= (0.45 if same_dist else 0.65)


def dedup_existing(*, days: int = 21, dry_run: bool = False) -> dict:
    """Merge duplicate incident clusters created in the last `days`.

    dry_run=True reports the clusters it WOULD merge without touching anything
    (use this to eyeball before committing)."""
    db = get_db()
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

    # Page the full approved set (past the 1000-row cap).
    rows: list[dict] = []
    offset = 0
    while True:
        batch = (db.table("incidents")
                 .select("id, title, category, district, incident_date, "
                         "source_urls, source_count, verification_status, created_at")
                 .eq("status", "approved")
                 .gte("incident_date", cutoff_date)
                 .range(offset, offset + 999).execute().data or [])
        rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r.get("category") or "other"].append(r)

    used: set[str] = set()
    clusters: list[dict] = []

    for _cat, items in by_cat.items():
        items.sort(key=lambda x: (x.get("incident_date") or ""))
        for i, a in enumerate(items):
            if a["id"] in used:
                continue
            cluster = [a]
            for b in items[i + 1:]:
                if b["id"] in used:
                    continue
                # compare against the anchor a (transitivity is fine here —
                # all share a's category and are within a day of it)
                if _are_duplicates(a, b):
                    cluster.append(b)
            if len(cluster) < 2:
                continue
            for c in cluster:
                used.add(c["id"])
            keeper = max(cluster, key=lambda x: (
                _VRANK.get(x.get("verification_status"), 0),
                len(x.get("source_urls") or []),
            ))
            dups = [c for c in cluster if c["id"] != keeper["id"]]
            all_sources = sorted({u for c in cluster for u in (c.get("source_urls") or [])})
            clusters.append({
                "keeper_id": keeper["id"],
                "keeper_title": (keeper.get("title") or "")[:70],
                "merged_ids": [d["id"] for d in dups],
                "cluster_size": len(cluster),
                "combined_sources": len(all_sources),
            })

            if dry_run:
                continue

            # Give the keeper the union of sources (may upgrade verification).
            try:
                upd = {"source_urls": all_sources, "source_count": len(all_sources)}
                if len(all_sources) >= 2 and _VRANK.get(keeper.get("verification_status"), 0) < 5:
                    upd["verification_status"] = "multi_source_verified"
                db.table("incidents").update(upd).eq("id", keeper["id"]).execute()
            except Exception:
                logger.exception("dedup: keeper update failed for %s", keeper["id"])

            for d in dups:
                try:
                    db.table("incidents").update({
                        # status=rejected is what actually removes it from the
                        # dashboard / incidents list / counts (the approved-only
                        # queries); verification_status + reason keep the audit
                        # trail and surface it on the Corrections page.
                        "status": "rejected",
                        "verification_status": "retracted",
                        "retraction_reason": f"Merged duplicate of {keeper['id']} "
                                             f"(same event, different source/location wording)",
                        "retracted_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", d["id"]).execute()
                    try:
                        db.table("incident_audit").insert({
                            "incident_id": d["id"], "action": "merged_duplicate",
                            "to_value": "retracted", "actor": "dedup_pass",
                            "reason": f"Merged into {keeper['id']}",
                        }).execute()
                    except Exception:
                        pass
                except Exception:
                    logger.exception("dedup: retract failed for %s", d["id"])

    total_dups = sum(len(c["merged_ids"]) for c in clusters)
    out = {
        "scanned": len(rows),
        "clusters": len(clusters),
        "duplicates_retracted": total_dups if not dry_run else 0,
        "duplicates_found": total_dups,
        "dry_run": dry_run,
        "sample": clusters[:20],
    }
    logger.info("dedup_existing: scanned=%d clusters=%d dups=%d dry_run=%s",
                len(rows), len(clusters), total_dups, dry_run)
    return out
