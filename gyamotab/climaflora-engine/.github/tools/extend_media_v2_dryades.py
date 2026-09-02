#!/usr/bin/env python3
"""Extend a validated Media v2.1 sidecar with Dryades / Flora d'Italia media.

Dryades is used only as a gap-filling source after Pl@ntNet, APII and WFO.
The collector is expected to have skipped every taxon already present in the
sidecar, so this stage cannot replace an existing primary image. Scientific
recommendation scoring is never modified.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

SOURCE = "dryades_flora_italia"
SOURCE_ORDER = "plantnet_gbif+atlas_living_australia_apii+dryades_flora_italia+world_flora_online"
ASSET_COLUMNS = (
    "asset_id", "taxon_id", "thumbnail_url", "image_url", "source", "source_record_id",
    "source_dataset_id", "license", "license_raw", "author", "attribution_url", "is_primary",
    "quality_rank", "verified_taxon_name", "local_filename", "materialized", "materialization_error",
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_taxa(conn: sqlite3.Connection, source: str | None = None) -> set[str]:
    if source is None:
        rows = conn.execute("SELECT DISTINCT taxon_id FROM plant_image_asset")
    else:
        rows = conn.execute("SELECT DISTINCT taxon_id FROM plant_image_asset WHERE source=?", (source,))
    return {str(row[0]) for row in rows}


def upsert_metadata(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    conn.executemany(
        "INSERT INTO media_metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        sorted((str(k), str(v)) for k, v in values.items()),
    )


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
    ap.add_argument("--dryades", required=True, type=Path)
    ap.add_argument("--dryades-report", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    args = ap.parse_args()

    base_report = read_json(args.base_report)
    payload = read_json(args.dryades)
    dryades_report = read_json(args.dryades_report)
    if base_report.get("status") != "ready" or dryades_report.get("status") != "ready":
        raise RuntimeError("Base or Dryades audit report is not ready")
    if payload.get("source") != SOURCE or dryades_report.get("source") != SOURCE:
        raise RuntimeError("Unexpected Dryades source")
    assets = list(payload.get("assets") or [])
    if len(assets) != int(dryades_report.get("eligible_unique_taxa") or -1):
        raise RuntimeError("Dryades asset/report count mismatch")

    with sqlite3.connect(args.sidecar) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Media v2.1 sidecar integrity failure")
        baseline_taxa = source_taxa(conn)
        expected_baseline = int(dryades_report.get("baseline_taxa") or -1)
        if expected_baseline != len(baseline_taxa):
            raise RuntimeError(
                f"Dryades baseline mismatch: collector={expected_baseline}, sidecar={len(baseline_taxa)}"
            )

        baseline_sources = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                "SELECT source,COUNT(DISTINCT taxon_id) FROM plant_image_asset GROUP BY source"
            )
        }
        rows = []
        incoming_taxa: set[str] = set()
        for asset in assets:
            if asset.get("source") != SOURCE:
                raise RuntimeError(f"Foreign source inside Dryades payload: {asset.get('source')}")
            taxon_id = str(asset.get("taxon_id") or "")
            if not taxon_id or taxon_id in baseline_taxa:
                raise RuntimeError(f"Dryades attempted to replace an existing taxon: {taxon_id}")
            if taxon_id in incoming_taxa:
                raise RuntimeError(f"Duplicate Dryades taxon in payload: {taxon_id}")
            incoming_taxa.add(taxon_id)
            image_url = str(asset.get("image_url") or "")
            thumb = str(asset.get("thumbnail_url") or "")
            if not image_url.startswith("https://") or not thumb.startswith("https://"):
                raise RuntimeError("Dryades asset without HTTPS image URL")
            licence = str(asset.get("license") or "")
            upper = licence.upper()
            if not licence or "NC" in upper or "ND" in upper or "ALL RIGHTS" in upper:
                raise RuntimeError(f"Rejected Dryades licence reached merge stage: {licence}")
            if not (
                upper.startswith("CC BY ")
                or upper.startswith("CC BY-SA ")
                or upper == "PUBLIC DOMAIN"
            ):
                raise RuntimeError(f"Unrecognised Dryades licence reached merge stage: {licence}")
            rows.append([asset.get(col) for col in ASSET_COLUMNS])

        marks = ",".join("?" for _ in ASSET_COLUMNS)
        conn.executemany(
            f"INSERT INTO plant_image_asset({','.join(ASSET_COLUMNS)}) VALUES({marks})",
            rows,
        )
        recompute_primaries(conn)

        dryades_taxa = source_taxa(conn, SOURCE)
        all_taxa = source_taxa(conn)
        catalog_total = int(base_report.get("catalog_taxa_total") or 0)
        primary_count = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1").fetchone()[0])
        primary_distinct = int(conn.execute(
            "SELECT COUNT(DISTINCT taxon_id) FROM plant_image_asset WHERE is_primary=1"
        ).fetchone()[0])
        if primary_count != primary_distinct or primary_distinct != len(all_taxa):
            raise RuntimeError("Primary image invariant failed after Dryades merge")
        invalid = int(conn.execute(
            "SELECT COUNT(*) FROM plant_image_asset WHERE upper(license) LIKE '%NC%' OR upper(license) LIKE '%ND%' OR upper(license) LIKE '%ALL RIGHTS%' OR trim(license)=''"
        ).fetchone()[0])
        if invalid:
            raise RuntimeError(f"Invalid media licences after Dryades merge: {invalid}")
        source_primary = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                "SELECT source,COUNT(*) FROM plant_image_asset WHERE is_primary=1 GROUP BY source"
            )
        }
        license_primary = {
            str(row[0]): int(row[1])
            for row in conn.execute(
                "SELECT license,COUNT(*) FROM plant_image_asset WHERE is_primary=1 GROUP BY license ORDER BY COUNT(*) DESC"
            )
        }
        coverage = round(len(all_taxa) / catalog_total * 100.0, 4) if catalog_total else 0.0
        upsert_metadata(conn, {
            "media_version": "2.2.0",
            "source": SOURCE_ORDER,
            "image_scoring_effect": "false",
            "catalog_taxa_total": str(catalog_total),
            "media_primary_taxa": str(len(all_taxa)),
            "dryades_taxa": str(len(dryades_taxa)),
            "dryades_new_taxa": str(len(incoming_taxa)),
            "coverage_pct": str(coverage),
            "dryades_matching_policy": str(payload.get("matching_policy") or "exact_no_fuzzy"),
            "dryades_dataset_id": str(payload.get("dataset_id") or "Dryades:Flora-d-Italia"),
        })
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Media v2.2 sidecar integrity failure")

    report = dict(base_report)
    report["status"] = "ready"
    report["media_version"] = "2.2.0"
    report["scoring_effect"] = False
    report["dryades_flora_italia"] = {
        **{key: dryades_report.get(key) for key in (
            "source", "accepted_index_links", "index_exact_catalog", "index_unmatched_catalog",
            "index_ambiguous_catalog", "already_covered_taxa", "uncovered_candidates_considered",
            "taxon_pages_requested", "media_rows_seen", "eligible_media", "rejected_license_media",
            "rejected_url_media", "eligible_unique_taxa", "taxa_without_open_media", "license_counts",
        )},
        "baseline_media_taxa": len(baseline_taxa),
        "net_new_taxa": len(incoming_taxa),
        "net_new_coverage_pct": round(len(incoming_taxa) / catalog_total * 100.0, 4) if catalog_total else 0.0,
    }
    report["matrix"] = {
        **dict(base_report.get("matrix") or {}),
        "pre_dryades_unique_taxa": len(baseline_taxa),
        "dryades_new_taxa": len(incoming_taxa),
        "cumulative_unique_taxa": len(all_taxa),
        "cumulative_coverage_pct": coverage,
        "primary_source_counts": source_primary,
        "primary_license_counts": license_primary,
        "source_taxa_counts_before_dryades": baseline_sources,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
