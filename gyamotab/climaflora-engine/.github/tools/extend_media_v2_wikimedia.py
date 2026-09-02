#!/usr/bin/env python3
"""Extend validated Media v2.2 with Wikimedia Commons P18 gap-fill media."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

SOURCE = "wikimedia_commons"
SOURCE_ORDER = (
    "plantnet_gbif+atlas_living_australia_apii+dryades_flora_italia+"
    "world_flora_online+wikimedia_commons"
)
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


def scoped_wikimedia_asset_id(asset_id: str, taxon_id: str) -> str:
    """Make a Commons asset reference unique to a taxon assignment.

    A single Commons file can legitimately be attached to more than one exact
    taxon record. `source_record_id` keeps the original Commons filename; the
    internal asset id therefore identifies the assignment, not the file alone.
    """
    base = str(asset_id or "").strip()
    taxon = str(taxon_id or "").strip()
    if not base or not taxon:
        raise RuntimeError("Cannot scope Wikimedia asset id without asset and taxon ids")
    return f"{base}:{taxon}"


def recompute_primaries(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE plant_image_asset SET is_primary=0")
    best_by_taxon: dict[str, str] = {}
    for taxon_id, asset_id in conn.execute(
        "SELECT taxon_id,asset_id FROM plant_image_asset ORDER BY taxon_id,quality_rank DESC,asset_id DESC"
    ):
        best_by_taxon.setdefault(str(taxon_id), str(asset_id))
    conn.executemany(
        "UPDATE plant_image_asset SET is_primary=1 WHERE taxon_id=? AND asset_id=?",
        [(taxon_id, asset_id) for taxon_id, asset_id in best_by_taxon.items()],
    )


def licence_allowed(value: str | None) -> bool:
    raw = " ".join(str(value or "").strip().split())
    upper = raw.upper()
    if not raw or "NC" in upper or "ND" in upper or "ALL RIGHTS" in upper:
        return False
    return (
        upper.startswith("CC0")
        or upper == "PUBLIC DOMAIN"
        or upper.startswith("CC BY ")
        or upper.startswith("CC BY-SA ")
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", required=True, type=Path)
    ap.add_argument("--base-report", required=True, type=Path)
    ap.add_argument("--wikimedia", required=True, type=Path)
    ap.add_argument("--wikimedia-report", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    args = ap.parse_args()

    base_report = read_json(args.base_report)
    payload = read_json(args.wikimedia)
    wiki_report = read_json(args.wikimedia_report)
    if base_report.get("status") != "ready" or wiki_report.get("status") != "ready":
        raise RuntimeError("Base or Wikimedia report is not ready")
    if payload.get("source") != SOURCE or wiki_report.get("source") != SOURCE:
        raise RuntimeError("Unexpected Wikimedia source")
    assets = list(payload.get("assets") or [])
    if len(assets) != int(wiki_report.get("eligible_unique_taxa") or -1):
        raise RuntimeError("Wikimedia asset/report count mismatch")

    with sqlite3.connect(args.sidecar) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Media v2.2 sidecar integrity failure")
        baseline_taxa = source_taxa(conn)
        expected_baseline = int(wiki_report.get("baseline_taxa") or -1)
        if expected_baseline != len(baseline_taxa):
            raise RuntimeError(
                f"Wikimedia baseline mismatch: collector={expected_baseline}, sidecar={len(baseline_taxa)}"
            )

        rows = []
        incoming_taxa: set[str] = set()
        incoming_asset_ids: set[str] = set()
        for asset in assets:
            if asset.get("source") != SOURCE:
                raise RuntimeError(f"Foreign source in Wikimedia payload: {asset.get('source')}")
            taxon_id = str(asset.get("taxon_id") or "")
            if not taxon_id or taxon_id in baseline_taxa:
                raise RuntimeError(f"Wikimedia attempted to replace an existing taxon: {taxon_id}")
            if taxon_id in incoming_taxa:
                raise RuntimeError(f"Duplicate Wikimedia taxon in payload: {taxon_id}")
            incoming_taxa.add(taxon_id)
            image_url = str(asset.get("image_url") or "")
            thumb = str(asset.get("thumbnail_url") or "")
            attribution = str(asset.get("attribution_url") or "")
            if not all(value.startswith("https://") for value in (image_url, thumb, attribution)):
                raise RuntimeError("Wikimedia asset without HTTPS URL")
            licence = str(asset.get("license") or "")
            if not licence_allowed(licence):
                raise RuntimeError(f"Rejected Wikimedia licence reached merge stage: {licence}")
            verified = " ".join(str(asset.get("verified_taxon_name") or "").split())
            if not verified:
                raise RuntimeError("Wikimedia asset without verified taxon name")

            normalized = dict(asset)
            normalized["asset_id"] = scoped_wikimedia_asset_id(str(asset.get("asset_id") or ""), taxon_id)
            if normalized["asset_id"] in incoming_asset_ids:
                raise RuntimeError(f"Duplicate scoped Wikimedia assignment id: {normalized['asset_id']}")
            incoming_asset_ids.add(normalized["asset_id"])
            rows.append([normalized.get(col) for col in ASSET_COLUMNS])

        marks = ",".join("?" for _ in ASSET_COLUMNS)
        conn.executemany(
            f"INSERT INTO plant_image_asset({','.join(ASSET_COLUMNS)}) VALUES({marks})",
            rows,
        )
        recompute_primaries(conn)

        all_taxa = source_taxa(conn)
        wiki_taxa = source_taxa(conn, SOURCE)
        catalog_total = int(base_report.get("catalog_taxa_total") or 0)
        primary_count = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1").fetchone()[0])
        primary_distinct = int(conn.execute(
            "SELECT COUNT(DISTINCT taxon_id) FROM plant_image_asset WHERE is_primary=1"
        ).fetchone()[0])
        if primary_count != primary_distinct or primary_distinct != len(all_taxa):
            raise RuntimeError("Primary image invariant failed after Wikimedia merge")
        invalid = int(conn.execute(
            "SELECT COUNT(*) FROM plant_image_asset WHERE upper(license) LIKE '%NC%' OR upper(license) LIKE '%ND%' OR upper(license) LIKE '%ALL RIGHTS%' OR trim(license)=''"
        ).fetchone()[0])
        if invalid:
            raise RuntimeError(f"Invalid media licences after Wikimedia merge: {invalid}")
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
            "media_version": "2.3.0",
            "source": SOURCE_ORDER,
            "image_scoring_effect": "false",
            "catalog_taxa_total": str(catalog_total),
            "media_primary_taxa": str(len(all_taxa)),
            "wikimedia_taxa": str(len(wiki_taxa)),
            "wikimedia_new_taxa": str(len(incoming_taxa)),
            "coverage_pct": str(coverage),
            "wikimedia_matching_policy": str(payload.get("matching_policy") or "exact_unique_wikidata_p225_plus_p18_no_fuzzy"),
            "wikimedia_dataset_id": str(payload.get("dataset_id") or "Wikidata:P225+P18/Wikimedia-Commons"),
        })
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Media v2.3 sidecar integrity failure")

    report = dict(base_report)
    report["status"] = "ready"
    report["media_version"] = "2.3.0"
    report["scoring_effect"] = False
    report["wikimedia_commons"] = {
        **{key: wiki_report.get(key) for key in (
            "source", "dataset_id", "candidate_species_gaps", "processed_taxa", "eligible_unique_taxa",
            "no_p18", "rejected_taxonomy", "rejected_license_taxa", "rejected_uncertain_taxa",
            "network_failure_taxa", "license_counts", "rules",
        )},
        "baseline_media_taxa": len(baseline_taxa),
        "net_new_taxa": len(incoming_taxa),
        "net_new_coverage_pct": round(len(incoming_taxa) / catalog_total * 100.0, 4) if catalog_total else 0.0,
    }
    report["matrix"] = {
        **dict(base_report.get("matrix") or {}),
        "pre_wikimedia_unique_taxa": len(baseline_taxa),
        "wikimedia_new_taxa": len(incoming_taxa),
        "cumulative_unique_taxa": len(all_taxa),
        "cumulative_coverage_pct": coverage,
        "primary_source_counts": source_primary,
        "primary_license_counts": license_primary,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
