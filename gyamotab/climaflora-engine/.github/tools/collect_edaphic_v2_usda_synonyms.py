from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from collect_edaphic_v2_sources import (
    canonical_species_name,
    collect_one,
    sha256_file,
    summarize,
    utcnow,
    write_jsonl,
)


def load_taxonomy(db: Path) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]], set[str]]:
    """Return exact accepted names and exact unambiguous WCVP synonyms.

    Avoid a CAST-based SQL join over ~1.45M WCVP names: load the 420k
    accepted plant ids once, then resolve WCVP rows through an in-memory id map.
    The taxonomic semantics are identical but the scan remains linear/index-free.
    """
    accepted: dict[str, tuple[str, str]] = {}
    accepted_by_id: dict[str, str] = {}
    synonym_targets: dict[str, set[tuple[str, str]]] = defaultdict(set)
    with sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True) as con:
        for taxon_id, scientific_name in con.execute(
            "SELECT taxon_id, scientific_name FROM plant_index WHERE scientific_name IS NOT NULL"
        ):
            tid = str(taxon_id)
            name = str(scientific_name).strip()
            accepted[name.casefold()] = (tid, name)
            accepted_by_id[tid] = name

        rows = con.execute(
            "SELECT scientific_name, accepted_name_usage_id, taxon_id "
            "FROM wcvp_names WHERE scientific_name IS NOT NULL"
        )
        for source_name, accepted_usage_id, taxon_id in rows:
            accepted_id = str(accepted_usage_id if accepted_usage_id is not None else taxon_id)
            accepted_name = accepted_by_id.get(accepted_id)
            if not accepted_name:
                continue
            key = str(source_name).strip().casefold()
            if key:
                synonym_targets[key].add((accepted_id, accepted_name))

    ambiguous = {name for name, targets in synonym_targets.items() if len(targets) != 1}
    synonyms = {name: next(iter(targets)) for name, targets in synonym_targets.items() if len(targets) == 1}
    return accepted, synonyms, ambiguous


def load_synonym_candidates(
    plant_list: Path,
    accepted: dict[str, tuple[str, str]],
    synonyms: dict[str, tuple[str, str]],
    ambiguous_synonyms: set[str],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    candidates: list[dict[str, str]] = []
    seen_symbols: set[str] = set()
    stats = Counter()
    with plant_list.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("Synonym Symbol") or "").strip():
                continue
            stats["accepted_usda_rows"] += 1
            symbol = (row.get("Symbol") or "").strip()
            canonical = canonical_species_name(row.get("Scientific Name with Author") or "")
            if not symbol or symbol in seen_symbols or not canonical:
                continue
            key = canonical.casefold()
            if key in accepted:
                stats["already_exact_accepted"] += 1
                continue
            if key in ambiguous_synonyms:
                stats["ambiguous_synonym_skipped"] += 1
                continue
            target = synonyms.get(key)
            if not target:
                stats["unmatched"] += 1
                continue
            taxon_id, accepted_name = target
            seen_symbols.add(symbol)
            stats["exact_wcvp_synonym_candidates"] += 1
            candidates.append({
                "symbol": symbol,
                "scientific_name": accepted_name,
                "source_scientific_name": canonical,
                "taxon_id": taxon_id,
                "family": (row.get("Family") or "").strip(),
                "source_name": (row.get("Scientific Name with Author") or "").strip(),
                "match_strategy": "exact_unambiguous_wcvp_synonym",
            })
    return candidates, dict(stats)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--plant-list", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=15)
    ap.add_argument("--tries", type=int, default=2)
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--shard-count", type=int, default=1)
    args = ap.parse_args()
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("invalid shard configuration")

    catalog = Path(args.catalog)
    plant_list = Path(args.plant_list)
    output = Path(args.output)
    report_path = Path(args.report)

    accepted, synonyms, ambiguous = load_taxonomy(catalog)
    all_candidates, candidate_stats = load_synonym_candidates(plant_list, accepted, synonyms, ambiguous)
    all_candidates.sort(key=lambda c: (str(c.get("taxon_id")), str(c.get("symbol"))))
    candidates = [c for i, c in enumerate(all_candidates) if i % args.shard_count == args.shard_index]
    candidate_stats.update({
        "ambiguous_wcvp_synonym_names": len(ambiguous),
        "total_synonym_candidates": len(all_candidates),
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "shard_candidates": len(candidates),
    })

    started = time.monotonic()
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(collect_one, c, timeout=args.timeout, tries=args.tries): c
            for c in candidates
        }
        for i, future in enumerate(as_completed(futures), 1):
            candidate = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                record = {**candidate, "outcome": "UNHANDLED_ERROR", "error": repr(exc)}
            records.append(record)
            if i % 100 == 0 or i == len(candidates):
                print(
                    f"USDA synonym shard {args.shard_index + 1}/{args.shard_count}: "
                    f"{i}/{len(candidates)} elapsed={time.monotonic() - started:.1f}s",
                    flush=True,
                )

    records.sort(key=lambda r: (str(r.get("scientific_name")), str(r.get("symbol"))))
    write_jsonl(output, records)
    summary = summarize(records, candidate_stats)
    report = {
        "status": "ready",
        "source": "USDA_PLANTS",
        "source_api": "https://plantsservices.sc.egov.usda.gov/api",
        "accessed_at": utcnow(),
        "catalog_sha256": sha256_file(catalog),
        "plant_list_sha256": sha256_file(plant_list),
        "output_sha256": sha256_file(output),
        "workers": args.workers,
        "request_timeout_seconds": args.timeout,
        "request_tries": args.tries,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "stats": summary,
        "matching_policy": "USDA accepted species symbol -> exact unambiguous WCVP synonym -> current ClimaFlora accepted taxon; accepted-name matches excluded because primary collector handles them; no fuzzy matching",
        "row_policy": "Growth Requirements only; cultivar-specific and synonym-specific characteristic rows excluded",
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
