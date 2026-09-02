#!/usr/bin/env python3
"""Collect exact Wikimedia Commons P18 images for Media v2 gaps.

This collector is intentionally conservative and scalable:
- only unique binomial scientific names from the canonical ClimaFlora catalog;
- only taxa not already illustrated in the validated Media v2 sidecar;
- exact Wikidata P225 match, with homonyms rejected;
- only Wikidata P18 images (high-confidence direct taxon image);
- CC0/Public domain/CC BY/CC BY-SA only, checked on the Commons file metadata;
- no fuzzy matching, no scoring effect, no image download/materialisation.

Wikidata P373 Commons-category crawling is deliberately left for a later pass
because it requires at least one additional request per taxon and is much less
scalable than P18. The existing parent-species illustration fallback covers
infraspecific taxa when the parent species obtains a Commons image here.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import media_ingest_wikimedia_v1_1 as wiki  # noqa: E402

SOURCE = "wikimedia_commons"
DATASET = "Wikidata:P225+P18/Wikimedia-Commons"
BINOMIAL_RE = re.compile(r"^[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.-]+\s+[a-z][A-Za-zÀ-ÖØ-öø-ÿ.-]+$")


def is_binomial_species(name: str | None) -> bool:
    value = " ".join(str(name or "").strip().split())
    return bool(value and "×" not in value and BINOMIAL_RE.fullmatch(value))


def baseline_taxa(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "plant_image_asset" not in tables:
            return set()
        return {str(row[0]) for row in conn.execute("SELECT DISTINCT taxon_id FROM plant_image_asset")}


def select_species_gaps(
    catalog: Path,
    baseline: set[str],
    *,
    taxon: str | None = None,
    limit: int = 0,
    offset: int = 0,
) -> list[tuple[str, str]]:
    with sqlite3.connect(f"file:{catalog.resolve()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        if taxon:
            rows = conn.execute(
                "SELECT taxon_id,scientific_name FROM plant_index WHERE scientific_name=?",
                (" ".join(taxon.strip().split()),),
            ).fetchall()
            if len(rows) != 1:
                raise RuntimeError(f"Exact catalog taxon must resolve once, got {len(rows)} for {taxon!r}")
            row = rows[0]
            pair = (str(row["taxon_id"]), str(row["scientific_name"]))
            if pair[0] in baseline:
                return []
            if not is_binomial_species(pair[1]):
                raise RuntimeError(f"Requested Wikimedia probe is not a non-hybrid binomial species: {pair[1]}")
            return [pair]

        rows = conn.execute(
            """
            SELECT MIN(taxon_id) AS taxon_id, scientific_name
            FROM plant_index
            WHERE scientific_name IS NOT NULL AND trim(scientific_name)<>''
            GROUP BY scientific_name
            HAVING COUNT(*)=1
            ORDER BY scientific_name COLLATE NOCASE, scientific_name
            """
        ).fetchall()

    candidates = [
        (str(row["taxon_id"]), " ".join(str(row["scientific_name"]).split()))
        for row in rows
        if str(row["taxon_id"]) not in baseline and is_binomial_species(row["scientific_name"])
    ]
    start = max(0, int(offset))
    if limit and int(limit) > 0:
        return candidates[start:start + int(limit)]
    return candidates[start:]


def media_v2_asset(taxon_id: str, scientific_name: str, selected: dict) -> dict:
    return {
        "asset_id": str(selected["asset_id"]),
        "taxon_id": taxon_id,
        "thumbnail_url": str(selected["thumbnail_url"]),
        "image_url": str(selected["image_url"]),
        "source": SOURCE,
        "source_record_id": str(selected.get("filename") or selected["asset_id"]),
        "source_dataset_id": DATASET,
        "license": str(selected["license"]),
        "license_raw": str(selected["license"]),
        "author": selected.get("author"),
        "attribution_url": str(selected["source_page_url"]),
        "is_primary": 1,
        "quality_rank": float(selected.get("quality_rank") or 0.0),
        "verified_taxon_name": scientific_name,
        "local_filename": None,
        "materialized": 0,
        "materialization_error": None,
    }


def collect(args: argparse.Namespace) -> dict:
    catalog = Path(args.catalog)
    sidecar = Path(args.baseline)
    if not catalog.exists():
        raise RuntimeError(f"Catalog not found: {catalog}")
    if not sidecar.exists():
        raise RuntimeError(f"Baseline Media v2 sidecar not found: {sidecar}")

    covered = baseline_taxa(sidecar)
    taxa = select_species_gaps(
        catalog,
        covered,
        taxon=args.taxon,
        limit=args.limit,
        offset=args.offset,
    )
    started = wiki.now_iso()
    stats: Counter[str] = Counter()
    licenses: Counter[str] = Counter()
    assets_out: list[dict] = []

    client = wiki.WikimediaClient(
        timeout=float(args.timeout_seconds),
        max_retries=int(args.max_retries),
        request_delay_ms=int(args.request_delay_ms),
    )
    try:
        batch_size = max(1, min(int(args.batch_size), 250))
        for start in range(0, len(taxa), batch_size):
            batch = taxa[start:start + batch_size]
            names = [name for _, name in batch]
            try:
                exact, ambiguous = client.exact_assets(names)
            except Exception as exc:  # noqa: BLE001
                stats["network_failure_taxa"] += len(batch)
                stats[f"network_{type(exc).__name__}"] += len(batch)
                continue

            filenames: list[str] = []
            per_name_files: dict[str, list[str]] = {}
            for name in names:
                if name in ambiguous:
                    continue
                p18 = sorted((exact.get(name) or {}).get("p18") or [])
                per_name_files[name] = p18
                filenames.extend(p18)

            try:
                info480 = client.commons_info(filenames, 480) if filenames else {}
                info960 = client.commons_info(filenames, 960) if filenames else {}
            except Exception as exc:  # noqa: BLE001
                stats["network_failure_taxa"] += len(batch)
                stats[f"commons_{type(exc).__name__}"] += len(batch)
                continue

            for taxon_id, name in batch:
                stats["processed_taxa"] += 1
                if name in ambiguous:
                    stats["rejected_taxonomy"] += 1
                    continue
                p18 = per_name_files.get(name) or []
                if not p18:
                    stats["no_p18"] += 1
                    continue
                candidates: list[dict] = []
                rejected_license = 0
                rejected_uncertain = 0
                for filename in p18:
                    info = info480.get(filename)
                    if not info:
                        continue
                    candidate = wiki.candidate_from_info(
                        filename,
                        info,
                        info960.get(filename),
                        wiki.now_iso(),
                        name,
                        "wikidata_p18",
                        None,
                    )
                    if candidate is None:
                        rejected_license += 1
                        continue
                    # Media v2 does not display blurred/uncertain exact images.
                    if candidate.get("display_blurred"):
                        rejected_uncertain += 1
                        continue
                    candidates.append(candidate)
                if not candidates:
                    if rejected_license:
                        stats["rejected_license_taxa"] += 1
                    if rejected_uncertain:
                        stats["rejected_uncertain_taxa"] += 1
                    continue
                candidates.sort(
                    key=lambda item: (
                        -int(item.get("quality_rank") or 0),
                        int(item.get("permissive_rank") or 9),
                        -(int(item.get("width") or 0) * int(item.get("height") or 0)),
                        str(item.get("asset_id") or ""),
                    )
                )
                selected = candidates[0]
                assets_out.append(media_v2_asset(taxon_id, name, selected))
                stats["eligible_unique_taxa"] += 1
                licenses[str(selected["license"])] += 1
    finally:
        client.close()

    finished = wiki.now_iso()
    payload = {
        "status": "ready",
        "source": SOURCE,
        "dataset_id": DATASET,
        "matching_policy": "exact_unique_wikidata_p225_plus_p18_no_fuzzy",
        "scoring_effect": False,
        "generated_at": finished,
        "baseline_taxa": len(covered),
        "candidate_species_gaps": len(taxa),
        "assets": assets_out,
    }
    report = {
        "status": "ready",
        "source": SOURCE,
        "dataset_id": DATASET,
        "started_at": started,
        "finished_at": finished,
        "baseline_taxa": len(covered),
        "candidate_species_gaps": len(taxa),
        "processed_taxa": stats["processed_taxa"],
        "eligible_unique_taxa": stats["eligible_unique_taxa"],
        "no_p18": stats["no_p18"],
        "rejected_taxonomy": stats["rejected_taxonomy"],
        "rejected_license_taxa": stats["rejected_license_taxa"],
        "rejected_uncertain_taxa": stats["rejected_uncertain_taxa"],
        "network_failure_taxa": stats["network_failure_taxa"],
        "license_counts": dict(sorted(licenses.items())),
        "rules": {
            "species_only": True,
            "exact_wikidata_p225": True,
            "wikidata_p18_only": True,
            "wikidata_p373_category": False,
            "fuzzy_matching": False,
            "homonyms_rejected": True,
            "allowed_licenses": ["CC0", "Public domain", "CC BY", "CC BY-SA"],
            "uncertain_media_rejected": True,
            "scoring_effect": False,
            "materialized": False,
        },
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--taxon")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--request-delay-ms", type=int, default=50)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--batch-size", type=int, default=150)
    return parser.parse_args()


def main() -> None:
    started = time.monotonic()
    report = collect(parse_args())
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)


if __name__ == "__main__":
    main()
