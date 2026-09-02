#!/usr/bin/env python3
"""Finalize ClimaFlora Media v2 into the normalized Media v2.4 sidecar.

The source collectors remain independent. This finalizer is the single storage
boundary consumed by the application:
- every canonical ClimaFlora taxon is represented exactly once in ``media_taxon``;
- zero to three validated image assets are retained per taxon, regardless of source;
- position 1 is the primary image and positions 2/3 are alternates;
- provenance, author and licence stay attached to every asset;
- media never participates in scientific scoring.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from collections import Counter
from pathlib import Path

MAX_IMAGES_PER_TAXON = 3
MEDIA_VERSION = "2.4.0"
PLANTNET_UNVERIFIED_LICENSE = "Pl@ntNet : licence non renseignée"

ASSET_COLUMNS = (
    "asset_id",
    "taxon_id",
    "thumbnail_url",
    "image_url",
    "source",
    "source_record_id",
    "source_dataset_id",
    "license",
    "license_raw",
    "author",
    "attribution_url",
    "is_primary",
    "quality_rank",
    "verified_taxon_name",
    "local_filename",
    "materialized",
    "materialization_error",
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def licence_allowed(value: str | None) -> bool:
    raw = " ".join(str(value or "").strip().split())
    if raw == PLANTNET_UNVERIFIED_LICENSE:
        return True
    upper = raw.upper()
    if not raw or "NC" in upper or "ND" in upper or "ALL RIGHTS" in upper:
        return False
    return (
        upper.startswith("CC0")
        or upper == "PUBLIC DOMAIN"
        or upper.startswith("CC BY ")
        or upper.startswith("CC BY-SA ")
    )


def catalog_rows(path: Path) -> list[tuple[str, str]]:
    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        rows = [
            (str(row[0]), " ".join(str(row[1] or "").split()))
            for row in conn.execute("SELECT taxon_id,scientific_name FROM plant_index ORDER BY taxon_id")
        ]
    if not rows:
        raise RuntimeError("Canonical catalog has no plant_index rows")
    if len({taxon_id for taxon_id, _ in rows}) != len(rows):
        raise RuntimeError("Canonical catalog contains duplicate taxon_id values")
    return rows


def validate_input_sidecar(conn: sqlite3.Connection, catalog_ids: set[str]) -> None:
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("Input media sidecar integrity failure")
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "plant_image_asset" not in tables or "media_metadata" not in tables:
        raise RuntimeError("Input media sidecar is missing required tables")
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(plant_image_asset)")}
    missing = set(ASSET_COLUMNS) - cols
    if missing:
        raise RuntimeError(f"Input plant_image_asset columns missing: {sorted(missing)}")

    foreign_taxa = [
        str(row[0])
        for row in conn.execute("SELECT DISTINCT taxon_id FROM plant_image_asset")
        if str(row[0]) not in catalog_ids
    ]
    if foreign_taxa:
        raise RuntimeError(f"Media contains taxon ids absent from catalog: {foreign_taxa[:5]}")

    bad_licenses = [
        (str(row[0]), str(row[1] or ""))
        for row in conn.execute("SELECT asset_id,license FROM plant_image_asset")
        if not licence_allowed(row[1])
    ]
    if bad_licenses:
        raise RuntimeError(f"Invalid media licences reached finalizer: {bad_licenses[:5]}")

    invalid_urls = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM plant_image_asset
            WHERE image_url IS NULL OR trim(image_url) NOT LIKE 'https://%'
               OR thumbnail_url IS NULL OR trim(thumbnail_url) NOT LIKE 'https://%'
               OR attribution_url IS NULL OR trim(attribution_url) NOT LIKE 'https://%'
            """
        ).fetchone()[0]
    )
    if invalid_urls:
        raise RuntimeError(f"Non-HTTPS or missing media URLs reached finalizer: {invalid_urls}")


def rebuild_asset_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS plant_image_asset_v24;
        CREATE TABLE plant_image_asset_v24(
          asset_id TEXT PRIMARY KEY,
          taxon_id TEXT NOT NULL,
          position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 3),
          thumbnail_url TEXT NOT NULL,
          image_url TEXT NOT NULL,
          source TEXT NOT NULL,
          source_record_id TEXT,
          source_dataset_id TEXT,
          license TEXT NOT NULL,
          license_raw TEXT,
          author TEXT,
          attribution_url TEXT NOT NULL,
          is_primary INTEGER NOT NULL CHECK(is_primary IN (0,1)),
          quality_rank REAL NOT NULL DEFAULT 0,
          verified_taxon_name TEXT NOT NULL,
          local_filename TEXT,
          materialized INTEGER NOT NULL DEFAULT 0 CHECK(materialized IN (0,1)),
          materialization_error TEXT,
          UNIQUE(taxon_id, position)
        );
        """
    )
    select_cols = ",".join(ASSET_COLUMNS)
    rows = conn.execute(
        f"""
        WITH ranked AS (
          SELECT {select_cols},
                 ROW_NUMBER() OVER (
                   PARTITION BY taxon_id
                   ORDER BY quality_rank DESC, is_primary DESC, asset_id DESC
                 ) AS media_position
          FROM plant_image_asset
        )
        SELECT {select_cols}, media_position
        FROM ranked
        WHERE media_position <= ?
        ORDER BY taxon_id, media_position
        """,
        (MAX_IMAGES_PER_TAXON,),
    ).fetchall()

    insert_cols = (
        "asset_id,taxon_id,position,thumbnail_url,image_url,source,source_record_id,source_dataset_id,"
        "license,license_raw,author,attribution_url,is_primary,quality_rank,verified_taxon_name,"
        "local_filename,materialized,materialization_error"
    )
    prepared = []
    for row in rows:
        values = dict(zip((*ASSET_COLUMNS, "media_position"), row, strict=True))
        position = int(values["media_position"])
        prepared.append(
            (
                values["asset_id"],
                values["taxon_id"],
                position,
                values["thumbnail_url"],
                values["image_url"],
                values["source"],
                values["source_record_id"],
                values["source_dataset_id"],
                values["license"],
                values["license_raw"],
                values["author"],
                values["attribution_url"],
                1 if position == 1 else 0,
                values["quality_rank"],
                values["verified_taxon_name"],
                values["local_filename"],
                values["materialized"],
                values["materialization_error"],
            )
        )
    if prepared:
        conn.executemany(
            f"INSERT INTO plant_image_asset_v24({insert_cols}) VALUES({','.join('?' for _ in range(18))})",
            prepared,
        )

    conn.executescript(
        """
        DROP TABLE plant_image_asset;
        ALTER TABLE plant_image_asset_v24 RENAME TO plant_image_asset;
        CREATE INDEX idx_media_v24_taxon ON plant_image_asset(taxon_id,position);
        CREATE INDEX idx_media_v24_source ON plant_image_asset(source,taxon_id);
        CREATE INDEX idx_media_v24_primary ON plant_image_asset(is_primary,taxon_id);
        """
    )


def rebuild_taxon_table(conn: sqlite3.Connection, catalog: list[tuple[str, str]], generated_at: str) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS media_taxon;
        CREATE TABLE media_taxon(
          taxon_id TEXT PRIMARY KEY,
          scientific_name TEXT NOT NULL,
          image_count INTEGER NOT NULL DEFAULT 0 CHECK(image_count BETWEEN 0 AND 3),
          status TEXT NOT NULL CHECK(status IN ('ready','no_image')),
          updated_at TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO media_taxon(taxon_id,scientific_name,image_count,status,updated_at) VALUES(?,?,0,'no_image',?)",
        [(taxon_id, name, generated_at) for taxon_id, name in catalog],
    )
    conn.execute(
        """
        UPDATE media_taxon
        SET image_count=(
              SELECT COUNT(*) FROM plant_image_asset a WHERE a.taxon_id=media_taxon.taxon_id
            ),
            status=CASE WHEN EXISTS(
              SELECT 1 FROM plant_image_asset a WHERE a.taxon_id=media_taxon.taxon_id
            ) THEN 'ready' ELSE 'no_image' END
        """
    )
    conn.executescript(
        """
        CREATE INDEX idx_media_taxon_status ON media_taxon(status,taxon_id);
        CREATE INDEX idx_media_taxon_image_count ON media_taxon(image_count,taxon_id);
        """
    )


def upsert_metadata(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    conn.executemany(
        "INSERT INTO media_metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        sorted((str(key), str(value)) for key, value in values.items()),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--sidecar", required=True, type=Path)
    ap.add_argument("--base-report", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    args = ap.parse_args()

    if not args.catalog.exists() or not args.sidecar.exists():
        raise RuntimeError("Catalog or media sidecar is missing")
    base_report = read_json(args.base_report)
    if base_report.get("status") != "ready":
        raise RuntimeError("Input Media v2 report is not ready")

    catalog = catalog_rows(args.catalog)
    catalog_ids = {taxon_id for taxon_id, _ in catalog}
    generated_at = utc_now()

    with sqlite3.connect(args.sidecar) as conn:
        conn.row_factory = sqlite3.Row
        validate_input_sidecar(conn, catalog_ids)
        before_assets = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset").fetchone()[0])
        before_taxa = int(conn.execute("SELECT COUNT(DISTINCT taxon_id) FROM plant_image_asset").fetchone()[0])

        rebuild_asset_table(conn)
        rebuild_taxon_table(conn, catalog, generated_at)

        total_assets = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset").fetchone()[0])
        with_images = int(conn.execute("SELECT COUNT(*) FROM media_taxon WHERE image_count>0").fetchone()[0])
        without_images = int(conn.execute("SELECT COUNT(*) FROM media_taxon WHERE image_count=0").fetchone()[0])
        primary = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE position=1 AND is_primary=1").fetchone()[0])
        bad_primary = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE (position=1)!=(is_primary=1)").fetchone()[0])
        over_cap = int(conn.execute("SELECT COUNT(*) FROM (SELECT taxon_id FROM plant_image_asset GROUP BY taxon_id HAVING COUNT(*)>3)").fetchone()[0])
        taxon_rows = int(conn.execute("SELECT COUNT(*) FROM media_taxon").fetchone()[0])
        orphan_assets = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset a LEFT JOIN media_taxon t USING(taxon_id) WHERE t.taxon_id IS NULL").fetchone()[0])
        distribution = Counter({
            str(row[0]): int(row[1])
            for row in conn.execute("SELECT image_count,COUNT(*) FROM media_taxon GROUP BY image_count ORDER BY image_count")
        })
        source_assets = {
            str(row[0]): int(row[1])
            for row in conn.execute("SELECT source,COUNT(*) FROM plant_image_asset GROUP BY source ORDER BY source")
        }

        if taxon_rows != len(catalog):
            raise RuntimeError(f"media_taxon count mismatch: {taxon_rows} != {len(catalog)}")
        if with_images != before_taxa or primary != with_images:
            raise RuntimeError(
                f"Coverage changed during normalization: before={before_taxa}, with_images={with_images}, primary={primary}"
            )
        if bad_primary or over_cap or orphan_assets:
            raise RuntimeError(
                f"Media v2.4 invariants failed: bad_primary={bad_primary}, over_cap={over_cap}, orphan={orphan_assets}"
            )

        coverage = round(with_images / len(catalog) * 100.0, 4) if catalog else 0.0
        upsert_metadata(
            conn,
            {
                "media_version": MEDIA_VERSION,
                "image_scoring_effect": "false",
                "catalog_taxa_total": str(len(catalog)),
                "media_taxa_indexed": str(taxon_rows),
                "media_primary_taxa": str(with_images),
                "media_taxa_without_images": str(without_images),
                "media_assets_total": str(total_assets),
                "max_images_per_taxon": str(MAX_IMAGES_PER_TAXON),
                "coverage_pct": str(coverage),
                "storage_model": "media_taxon+plant_image_asset_top3",
                "normalized_at": generated_at,
            },
        )
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Media v2.4 sidecar integrity failure")

    report = dict(base_report)
    report.update(
        {
            "status": "ready",
            "media_version": MEDIA_VERSION,
            "scoring_effect": False,
            "storage": {
                "model": "media_taxon+plant_image_asset_top3",
                "catalog_taxa_rows": len(catalog),
                "max_images_per_taxon": MAX_IMAGES_PER_TAXON,
                "input_asset_rows": before_assets,
                "retained_asset_rows": total_assets,
                "pruned_asset_rows": before_assets - total_assets,
                "taxa_with_images": with_images,
                "taxa_without_images": without_images,
                "image_count_distribution": dict(sorted(distribution.items(), key=lambda item: int(item[0]))),
                "asset_source_counts": source_assets,
                "coverage_pct": coverage,
                "normalized_at": generated_at,
            },
        }
    )
    report.setdefault("matrix", {})["cumulative_unique_taxa"] = with_images
    report["matrix"]["cumulative_coverage_pct"] = coverage
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
