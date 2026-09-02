#!/usr/bin/env python3
"""Migrate an existing production Media v2 sidecar to Media v2.4.

This is the fast production path: reuse the already validated published sidecar,
add the Wikimedia P18 gap fill when it is not present yet, then normalize the
canonical 420,532-taxon media index and retain at most three assets per taxon.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def metadata(sidecar: Path) -> dict[str, str]:
    with sqlite3.connect(sidecar) as conn:
        return {str(k): str(v) for k, v in conn.execute("SELECT key,value FROM media_metadata")}


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, check=True)


def ensure_wikimedia(catalog: Path, sidecar: Path, matrix: Path, workdir: Path) -> Path:
    meta = metadata(sidecar)
    version = meta.get("media_version", "0")
    source = meta.get("source", "")
    if version.startswith("2.4.") or "wikimedia_commons" in source:
        print(f"Wikimedia merge skipped: media_version={version}, source={source}", flush=True)
        return matrix

    wikimedia_media = workdir / "wikimedia_media.json"
    wikimedia_report = workdir / "wikimedia_report.json"
    pre_normalize = workdir / "pre_normalize_matrix.json"
    run(
        sys.executable,
        str(TOOLS / "collect_wikimedia_media_v2.py"),
        "--catalog",
        str(catalog),
        "--baseline",
        str(sidecar),
        "--output",
        str(wikimedia_media),
        "--report",
        str(wikimedia_report),
        "--batch-size",
        "150",
        "--request-delay-ms",
        "50",
    )
    report = read_json(wikimedia_report)
    if report.get("status") != "ready":
        raise RuntimeError(f"Wikimedia collection not ready: {report}")
    if int(report.get("network_failure_taxa") or 0) != 0:
        raise RuntimeError(f"Wikimedia collection had network failures: {report}")
    if int(report.get("eligible_unique_taxa") or 0) <= 0:
        raise RuntimeError(f"Wikimedia collection produced no new taxa: {report}")
    print(f"Wikimedia new taxa: {report['eligible_unique_taxa']}", flush=True)

    run(
        sys.executable,
        str(TOOLS / "extend_media_v2_wikimedia.py"),
        "--sidecar",
        str(sidecar),
        "--base-report",
        str(matrix),
        "--wikimedia",
        str(wikimedia_media),
        "--wikimedia-report",
        str(wikimedia_report),
        "--report",
        str(pre_normalize),
    )
    return pre_normalize


def normalize(catalog: Path, sidecar: Path, matrix: Path, output_report: Path) -> None:
    if metadata(sidecar).get("media_version", "").startswith("2.4."):
        shutil.copy2(matrix, output_report)
        return
    run(
        sys.executable,
        str(TOOLS / "finalize_media_v2_catalog.py"),
        "--catalog",
        str(catalog),
        "--sidecar",
        str(sidecar),
        "--base-report",
        str(matrix),
        "--report",
        str(output_report),
    )


def validate(catalog: Path, sidecar: Path, report_path: Path) -> dict:
    report = read_json(report_path)
    with sqlite3.connect(sidecar) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Media v2.4 integrity_check failed")
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"media_taxon", "plant_image_asset", "media_metadata"} <= tables:
            raise RuntimeError(f"Media v2.4 tables missing: {tables}")
        meta = {str(k): str(v) for k, v in conn.execute("SELECT key,value FROM media_metadata")}
        expected_meta = {
            "media_version": "2.4.0",
            "storage_model": "media_taxon+plant_image_asset_top3",
            "media_taxa_indexed": "420532",
            "max_images_per_taxon": "3",
            "image_scoring_effect": "false",
        }
        for key, expected in expected_meta.items():
            if meta.get(key) != expected:
                raise RuntimeError(f"Media v2.4 metadata mismatch {key}: {meta.get(key)!r} != {expected!r}")

        indexed = int(conn.execute("SELECT COUNT(*) FROM media_taxon").fetchone()[0])
        with_images = int(conn.execute("SELECT COUNT(*) FROM media_taxon WHERE image_count>0").fetchone()[0])
        without_images = int(conn.execute("SELECT COUNT(*) FROM media_taxon WHERE image_count=0").fetchone()[0])
        assets = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset").fetchone()[0])
        primary = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE position=1 AND is_primary=1").fetchone()[0])
        over_cap = int(conn.execute("SELECT COUNT(*) FROM (SELECT taxon_id FROM plant_image_asset GROUP BY taxon_id HAVING COUNT(*)>3)").fetchone()[0])
        bad_positions = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE position NOT BETWEEN 1 AND 3 OR (position=1)!=(is_primary=1)").fetchone()[0])
        duplicate_positions = int(conn.execute("SELECT COUNT(*) FROM (SELECT taxon_id,position FROM plant_image_asset GROUP BY taxon_id,position HAVING COUNT(*)>1)").fetchone()[0])
        invalid = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM plant_image_asset
                WHERE (trim(license)='' OR upper(license) LIKE '%NC%' OR upper(license) LIKE '%ND%' OR upper(license) LIKE '%ALL RIGHTS%')
                  AND license<>'Pl@ntNet : licence non renseignée'
                """
            ).fetchone()[0]
        )
        orphans = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset a LEFT JOIN media_taxon t USING(taxon_id) WHERE t.taxon_id IS NULL").fetchone()[0])
        if indexed != 420532 or with_images + without_images != indexed or with_images != primary:
            raise RuntimeError(
                f"Media v2.4 count mismatch indexed={indexed} with={with_images} without={without_images} primary={primary}"
            )
        if any((over_cap, bad_positions, duplicate_positions, invalid, orphans)):
            raise RuntimeError(
                f"Media v2.4 invariants failed cap={over_cap} positions={bad_positions} duplicates={duplicate_positions} legal={invalid} orphans={orphans}"
            )

        with sqlite3.connect(catalog) as cat:
            rows = cat.execute("SELECT taxon_id FROM plant_index WHERE scientific_name='Acer nigrum'").fetchall()
        if len(rows) != 1:
            raise RuntimeError(f"Acer nigrum catalog resolution is not unique: {rows}")
        acer_id = str(rows[0][0])
        taxon = conn.execute("SELECT image_count,status FROM media_taxon WHERE taxon_id=?", (acer_id,)).fetchone()
        image = conn.execute(
            "SELECT source,license,verified_taxon_name,position,attribution_url FROM plant_image_asset WHERE taxon_id=? ORDER BY position LIMIT 1",
            (acer_id,),
        ).fetchone()
        if not taxon or int(taxon[0]) < 1 or str(taxon[1]) != "ready":
            raise RuntimeError(f"Acer nigrum media_taxon not ready: {taxon}")
        if not image or str(image[0]) != "wikimedia_commons" or str(image[2]) != "Acer nigrum" or int(image[3]) != 1:
            raise RuntimeError(f"Acer nigrum primary image mismatch: {image}")
        if not str(image[4]).startswith("https://commons.wikimedia.org/wiki/File:"):
            raise RuntimeError(f"Acer nigrum attribution URL mismatch: {image}")

        summary = {
            "media_version": meta["media_version"],
            "indexed_taxa": indexed,
            "taxa_with_images": with_images,
            "taxa_without_images": without_images,
            "assets": assets,
            "coverage_pct": round(with_images / indexed * 100.0, 4),
            "image_count_distribution": {
                str(row[0]): int(row[1])
                for row in conn.execute("SELECT image_count,COUNT(*) FROM media_taxon GROUP BY image_count ORDER BY image_count")
            },
            "acer_nigrum": {
                "taxon_id": acer_id,
                "source": str(image[0]),
                "license": str(image[1]),
            },
        }

    if report.get("status") != "ready" or report.get("media_version") != "2.4.0":
        raise RuntimeError(f"Media v2.4 report mismatch: {report.get('status')} {report.get('media_version')}")
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--sidecar", required=True, type=Path)
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--output-report", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()

    for path in (args.catalog, args.sidecar, args.matrix):
        if not path.exists():
            raise RuntimeError(f"Required migration input missing: {path}")
    workdir = args.output_report.parent
    workdir.mkdir(parents=True, exist_ok=True)
    print("Starting production media migration from", metadata(args.sidecar), flush=True)
    pre_normalize = ensure_wikimedia(args.catalog, args.sidecar, args.matrix, workdir)
    normalize(args.catalog, args.sidecar, pre_normalize, args.output_report)
    summary = validate(args.catalog, args.sidecar, args.output_report)
    args.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
