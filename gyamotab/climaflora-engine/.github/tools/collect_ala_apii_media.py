#!/usr/bin/env python3
"""Collect open Australian Plant Image Index media for ClimaFlora Media v2.

Only ALA metadata are downloaded. Images remain remotely hosted. Matching is
strict scientific-name equality against the ClimaFlora catalog, and the
individual image licence is authoritative when present.
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

IMAGES_SEARCH = "https://api.ala.org.au/images/ws/search"
RESOURCE_UID = "dr413"
SOURCE = "atlas_living_australia_apii"
DATASET_ID = "ALA:dr413:Australian Plant Image Index"


def clean(value) -> str:
    return " ".join(str(value or "").strip().split())


def canonical_open_license(raw_value: str | None, recognised_value: str | None) -> str | None:
    raw = clean(raw_value)
    low = raw.lower()
    if raw:
        if any(token in low for token in ("by-nc", "by-nd", "noncommercial", "no derivatives", "all rights reserved")):
            return None
        if "creativecommons.org/publicdomain/zero/1.0" in low or low in {"cc0", "cc0 1.0"}:
            return "CC0 1.0"
        if "creativecommons.org/publicdomain/mark" in low or "public domain" in low:
            return "Public domain"
        if "creativecommons.org/licenses/by-sa/4.0" in low:
            return "CC BY-SA 4.0"
        if "creativecommons.org/licenses/by-sa/3.0" in low:
            return "CC BY-SA 3.0"
        if "creativecommons.org/licenses/by/4.0" in low:
            return "CC BY 4.0"
        if "creativecommons.org/licenses/by/3.0/au" in low:
            return "CC BY 3.0 AU"
        if "creativecommons.org/licenses/by/3.0" in low:
            return "CC BY 3.0"
        return None
    recognised = clean(recognised_value)
    if recognised in {"CC BY 4.0 AU", "CC BY 3.0 AU", "CC BY 4.0", "CC BY-SA 4.0", "CC0 1.0"}:
        return recognised
    return None


def load_catalog(path: Path) -> tuple[dict[str, str | None], int]:
    by_name: dict[str, str | None] = {}
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0])
        for tid, scientific_name in conn.execute("SELECT taxon_id, scientific_name FROM plant_index"):
            name = clean(scientific_name)
            if not name:
                continue
            tid = str(tid)
            if name in by_name and by_name[name] != tid:
                by_name[name] = None
            elif name not in by_name:
                by_name[name] = tid
    return by_name, total


def get_json(params: list[tuple[str, str]], retries: int = 12) -> dict:
    url = IMAGES_SEARCH + "?" + urllib.parse.urlencode(params)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "ClimaFlora-MediaV2/2.1 (+https://shugoan.com/climaflora/)",
                },
            )
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after else 0.0
            except ValueError:
                delay = 0.0
            if delay <= 0:
                delay = min(2 ** attempt, 60) + random.uniform(0.2, 1.2)
            time.sleep(delay)
        except Exception as exc:
            last = exc
            time.sleep(min(2 ** attempt, 60) + random.uniform(0.2, 1.2))
    raise RuntimeError(f"ALA request failed after {retries} attempts: {last}; url={url}")


def int_value(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def candidate_rank(row: dict) -> float:
    score = 150.0
    if clean(row.get("creator")) and clean(row.get("creator")).lower() != "unknown":
        score += 5.0
    width, height = int_value(row.get("width")), int_value(row.get("height"))
    if width >= 600 and height >= 600:
        score += 3.0
    if width >= 1000 or height >= 1000:
        score += 2.0
    if clean(row.get("references")):
        score += 1.0
    return score


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--resource", default=RESOURCE_UID)
    ap.add_argument("--page-size", type=int, default=200)
    ap.add_argument("--sleep", type=float, default=0.08)
    args = ap.parse_args()
    if not 1 <= args.page_size <= 200:
        raise SystemExit("ALA image search page-size must be between 1 and 200")

    catalog, catalog_total = load_catalog(args.catalog)
    best: dict[str, dict] = {}
    stats = Counter()
    canonical_licenses = Counter()
    recognised_licenses = Counter()
    raw_licenses = Counter()
    expected_total: int | None = None
    seen_ids: set[str] = set()
    offset = 0

    while expected_total is None or offset < expected_total:
        payload = get_json([
            ("q", f"dataResourceUid:{args.resource}"),
            ("fq", "fileType:image"),
            ("max", str(args.page_size)),
            ("offset", str(offset)),
            ("sort", "dateUploaded"),
            ("order", "desc"),
        ])
        rows = payload.get("images") or []
        if expected_total is None:
            expected_total = int(payload.get("totalImageCount") or 0)
        if not rows:
            break

        for row in rows:
            stats["rows"] += 1
            image_id = clean(row.get("imageIdentifier"))
            if not image_id or image_id in seen_ids:
                stats["duplicate_or_missing_id_rows"] += 1
                continue
            seen_ids.add(image_id)
            if clean(row.get("dataResourceUid")) != args.resource:
                stats["wrong_resource_rows"] += 1
                continue

            raw_license = clean(row.get("license"))
            recognised = clean(row.get("recognisedLicence"))
            raw_licenses[raw_license or "<blank>"] += 1
            recognised_licenses[recognised or "<blank>"] += 1
            licence = canonical_open_license(raw_license, recognised)
            if not licence:
                stats["rejected_license_rows"] += 1
                continue
            canonical_licenses[licence] += 1
            stats["open_license_rows"] += 1

            name = clean(row.get("title"))
            taxon_id = catalog.get(name)
            if not taxon_id:
                stats["unmatched_catalog_rows"] += 1
                continue
            stats["exact_catalog_rows"] += 1
            author = clean(row.get("creator")) or None
            reference = clean(row.get("references"))
            attribution_url = reference if reference.startswith("https://") else f"https://images.ala.org.au/image/{image_id}"
            original_url = f"https://api.ala.org.au/images/image/{image_id}/original"
            candidate = {
                "asset_id": f"ala-apii:{image_id}",
                "taxon_id": taxon_id,
                "thumbnail_url": original_url,
                "image_url": original_url,
                "source": SOURCE,
                "source_record_id": image_id,
                "source_dataset_id": DATASET_ID,
                "license": licence,
                "license_raw": raw_license or recognised,
                "author": author,
                "attribution_url": attribution_url,
                "is_primary": 0,
                "quality_rank": candidate_rank(row),
                "verified_taxon_name": name,
                "local_filename": None,
                "materialized": 0,
                "materialization_error": None,
                "width": int_value(row.get("width")) or None,
                "height": int_value(row.get("height")) or None,
                "rights_holder": clean(row.get("rightsHolder")) or None,
                "recognised_license": recognised or None,
            }
            current = best.get(taxon_id)
            if current is None or (candidate["quality_rank"], candidate["asset_id"]) > (current["quality_rank"], current["asset_id"]):
                best[taxon_id] = candidate

        offset += len(rows)
        if args.sleep:
            time.sleep(args.sleep)

    # Builder sidecar schema is intentionally narrower than the audit payload.
    asset_keys = (
        "asset_id", "taxon_id", "thumbnail_url", "image_url", "source", "source_record_id",
        "source_dataset_id", "license", "license_raw", "author", "attribution_url", "is_primary",
        "quality_rank", "verified_taxon_name", "local_filename", "materialized", "materialization_error",
    )
    assets = [{key: row.get(key) for key in asset_keys} for row in best.values()]
    assets.sort(key=lambda row: (row["taxon_id"], row["asset_id"]))
    payload = {
        "schema_version": "1.0",
        "source": SOURCE,
        "data_resource_uid": args.resource,
        "matching_policy": "exact_scientific_name_from_image_title",
        "license_policy": "individual raw image licence authoritative; open fallback only when raw licence absent",
        "catalog_taxa_total": catalog_total,
        "expected_resource_images": expected_total,
        "assets": assets,
    }
    report = {
        "status": "ready",
        "source": SOURCE,
        "catalog_taxa_total": catalog_total,
        "expected_resource_images": expected_total,
        "rows_scanned": stats["rows"],
        "distinct_image_ids": len(seen_ids),
        "open_license_rows": stats["open_license_rows"],
        "rejected_license_rows": stats["rejected_license_rows"],
        "wrong_resource_rows": stats["wrong_resource_rows"],
        "exact_catalog_rows": stats["exact_catalog_rows"],
        "unmatched_catalog_rows": stats["unmatched_catalog_rows"],
        "eligible_unique_taxa": len(assets),
        "canonical_license_counts": dict(canonical_licenses.most_common()),
        "recognised_license_counts": dict(recognised_licenses.most_common()),
        "raw_license_counts": dict(raw_licenses.most_common()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
