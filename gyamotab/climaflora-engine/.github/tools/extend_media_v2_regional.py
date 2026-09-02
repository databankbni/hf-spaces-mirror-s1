#!/usr/bin/env python3
"""Extend a validated ClimaFlora Media v2 sidecar with regional open media.

The script never changes scientific data or scoring. It inserts already audited
media assets, recomputes exactly one primary image per taxon from quality_rank,
and emits an auditable coverage matrix.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

ALA_SOURCE = "atlas_living_australia_apii"
SOURCE_ORDER = "plantnet_gbif+atlas_living_australia_apii+world_flora_online"
ASSET_COLUMNS = (
    "asset_id", "taxon_id", "thumbnail_url", "image_url", "source", "source_record_id",
    "source_dataset_id", "license", "license_raw", "author", "attribution_url", "is_primary",
    "quality_rank", "verified_taxon_name", "local_filename", "materialized", "materialization_error",
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def upsert_metadata(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    conn.executemany(
        "INSERT INTO media_metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        sorted((str(k), str(v)) for k, v in values.items()),
    )


def source_taxa(conn: sqlite3.Connection, source: str | None = None) -> set[str]:
    if source is None:
        rows = conn.execute("SELECT DISTINCT taxon_id FROM plant_image_asset")
    else:
        rows = conn.execute("SELECT DISTINCT taxon_id FROM plant_image_asset WHERE source=?", (source,))
    return {str(row[0]) for row in rows}


def recompute_primaries(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE plant_image_asset SET is_primary=0")
    best_by_taxon: dict[str, str] = {}
    for taxon_id, asset_id in conn.execute(
        "SELECT taxon_id,asset_id FROM plant_image_asset ORDER BY taxon_id,quality_rank DESC,asset_id DESC"
    ):
        best_by_taxon.setdefault(str(taxon_id), str(asset_id))
    conn.executemany(
        "UPDATE plant_image_asset SET is_primary=1 WHERE asset_id=?",
        [(asset_id,) for asset_id in best_by_taxon.values()],
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", required=True, type=Path)
    ap.add_argument("--base-report", required=True, type=Path)
    ap.add_argument("--ala-apii", required=True, type=Path)
    ap.add_argument("--ala-report", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    args = ap.parse_args()

    base_report = read_json(args.base_report)
    ala_payload = read_json(args.ala_apii)
    ala_report = read_json(args.ala_report)
    if base_report.get("status") != "ready" or ala_report.get("status") != "ready":
        raise RuntimeError("Base or ALA audit report is not ready")
    if ala_payload.get("source") != ALA_SOURCE:
        raise RuntimeError(f"Unexpected ALA source: {ala_payload.get('source')}")
    assets = list(ala_payload.get("assets") or [])
    if len(assets) != int(ala_report.get("eligible_unique_taxa") or -1):
        raise RuntimeError("ALA asset/report taxon count mismatch")

    with sqlite3.connect(args.sidecar) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Base media sidecar integrity failure")
        baseline_taxa = source_taxa(conn)
        baseline_count = len(baseline_taxa)

        source_counts_before = dict(conn.execute(
            "SELECT source,COUNT(DISTINCT taxon_id) FROM plant_image_asset GROUP BY source"
        ))
        rows = []
        for asset in assets:
            if asset.get("source") != ALA_SOURCE:
                raise RuntimeError(f"Foreign source inside ALA payload: {asset.get('source')}")
            if not str(asset.get("image_url") or "").startswith("https://"):
                raise RuntimeError("ALA asset without HTTPS image URL")
            licence = str(asset.get("license") or "").upper()
            if not licence or "NC" in licence or "ND" in licence or "ALL RIGHTS" in licence:
                raise RuntimeError(f"Rejected ALA licence reached merge stage: {asset.get('license')}")
            rows.append([asset.get(col) for col in ASSET_COLUMNS])

        marks = ",".join("?" for _ in ASSET_COLUMNS)
        conn.executemany(
            f"INSERT OR REPLACE INTO plant_image_asset({','.join(ASSET_COLUMNS)}) VALUES({marks})",
            rows,
        )
        recompute_primaries(conn)

        ala_taxa = source_taxa(conn, ALA_SOURCE)
        all_taxa = source_taxa(conn)
        ala_new = ala_taxa - baseline_taxa
        ala_overlap = ala_taxa & baseline_taxa
        catalog_total = int(base_report.get("catalog_taxa_total") or 0)
        primary_count = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1").fetchone()[0])
        primary_distinct = int(conn.execute(
            "SELECT COUNT(DISTINCT taxon_id) FROM plant_image_asset WHERE is_primary=1"
        ).fetchone()[0])
        if primary_count != primary_distinct or primary_distinct != len(all_taxa):
            raise RuntimeError("Primary image invariant failed after regional merge")
        source_primary = dict(conn.execute(
            "SELECT source,COUNT(*) FROM plant_image_asset WHERE is_primary=1 GROUP BY source"
        ))
        license_primary = dict(conn.execute(
            "SELECT license,COUNT(*) FROM plant_image_asset WHERE is_primary=1 GROUP BY license ORDER BY COUNT(*) DESC"
        ))
        invalid = int(conn.execute(
            "SELECT COUNT(*) FROM plant_image_asset WHERE upper(license) LIKE '%NC%' OR upper(license) LIKE '%ND%' OR upper(license) LIKE '%ALL RIGHTS%' OR trim(license)=''"
        ).fetchone()[0])
        if invalid:
            raise RuntimeError(f"Invalid media licences after merge: {invalid}")

        coverage = round(len(all_taxa) / catalog_total * 100.0, 4) if catalog_total else 0.0
        upsert_metadata(conn, {
            "media_version": "2.1.0",
            "source": SOURCE_ORDER,
            "image_scoring_effect": "false",
            "catalog_taxa_total": str(catalog_total),
            "media_primary_taxa": str(len(all_taxa)),
            "ala_apii_taxa": str(len(ala_taxa)),
            "ala_apii_new_taxa": str(len(ala_new)),
            "coverage_pct": str(coverage),
            "matching_policy": "exact_canonical_scientific_name",
            "regional_matching_policy": "exact_scientific_name_from_image_title",
            "ala_apii_resource_uid": str(ala_payload.get("data_resource_uid") or "dr413"),
        })
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Extended media sidecar integrity failure")

    report = dict(base_report)
    report["status"] = "ready"
    report["media_version"] = "2.1.0"
    report["scoring_effect"] = False
    report["atlas_living_australia_apii"] = {
        **{key: ala_report.get(key) for key in (
            "source", "expected_resource_images", "rows_scanned", "distinct_image_ids",
            "open_license_rows", "rejected_license_rows", "exact_catalog_rows",
            "unmatched_catalog_rows", "eligible_unique_taxa", "canonical_license_counts",
            "recognised_license_counts", "raw_license_counts",
        )},
        "overlap_with_previous_media_taxa": len(ala_overlap),
        "net_new_taxa": len(ala_new),
        "net_new_coverage_pct": round(len(ala_new) / int(base_report["catalog_taxa_total"]) * 100.0, 4),
    }
    report["matrix"] = {
        **dict(base_report.get("matrix") or {}),
        "baseline_unique_taxa": baseline_count,
        "ala_apii_taxa": len(ala_taxa),
        "ala_apii_overlap_taxa": len(ala_overlap),
        "ala_apii_new_taxa": len(ala_new),
        "cumulative_unique_taxa": len(all_taxa),
        "cumulative_coverage_pct": coverage,
        "primary_source_counts": source_primary,
        "primary_license_counts": license_primary,
        "source_taxa_counts_before_ala": source_counts_before,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
