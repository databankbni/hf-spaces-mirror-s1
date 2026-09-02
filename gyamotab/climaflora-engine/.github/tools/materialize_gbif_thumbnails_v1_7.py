#!/usr/bin/env python3
"""Materialize licensed primary plant illustrations as local WebP thumbnails.

This step mutates only plant_image_asset thumbnail/materialization fields and
catalog metadata. The scientific climate/soil evidence is untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

USER_AGENT = "ClimaFlora/0.9.24 plant-media materializer; contact via shugoan.com"
DEFAULT_MAX_SOURCE_BYTES = 20 * 1024 * 1024


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def safe_asset_filename(asset_id: str) -> Path:
    digest = hashlib.sha256(asset_id.encode("utf-8")).hexdigest()
    return Path(digest[:2]) / f"{asset_id}.webp"


def _priority_sql(conn: sqlite3.Connection) -> str:
    tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    direct_parts = []
    for table in ("soil_envelope", "soil_categorical_preference", "soil_indicator_preference"):
        if table in tables:
            direct_parts.append(f"EXISTS (SELECT 1 FROM {table} s WHERE s.taxon_id=a.taxon_id)")
    direct = " OR ".join(direct_parts) or "0"
    columns = {str(r[1]) for r in conn.execute("PRAGMA table_info(plant_index)")}
    function = (
        "COALESCE(p.functions_json,'[]') NOT IN ('[]','null','')"
        if "functions_json" in columns
        else "0"
    )
    return f"""
        SELECT a.asset_id,a.taxon_id,a.image_url,a.license,a.author,a.attribution_url,
               a.verified_taxon_name,a.quality_rank
        FROM plant_image_asset a
        JOIN plant_index p ON p.taxon_id=a.taxon_id
        WHERE a.is_primary=1 AND a.materialized=0 AND a.thumbnail_url IS NULL
        ORDER BY
          CASE WHEN ({direct}) THEN 0 WHEN ({function}) THEN 1 ELSE 2 END,
          a.quality_rank DESC,
          p.scientific_name ASC
    """


def download_thumbnail(client: httpx.Client, url: str, *, width: int, max_bytes: int) -> tuple[bytes, int, int]:
    with client.stream("GET", url) as response:
        response.raise_for_status()
        content_type = str(response.headers.get("content-type", "")).lower()
        if content_type and not content_type.startswith("image/") and "octet-stream" not in content_type:
            raise ValueError(f"unexpected content-type {content_type}")
        declared = response.headers.get("content-length")
        if declared and int(declared) > max_bytes:
            raise ValueError("source image exceeds byte limit")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes(256 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("source image exceeds byte limit")
            chunks.append(chunk)
    payload = b"".join(chunks)
    if not payload:
        raise ValueError("empty image response")

    Image.MAX_IMAGE_PIXELS = 60_000_000
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image = ImageOps.exif_transpose(image)
            if min(image.size) < 64:
                raise ValueError("source image is too small")
            image.thumbnail((width, width), Image.Resampling.LANCZOS)
            if "A" in image.getbands():
                image = image.convert("RGBA")
            else:
                image = image.convert("RGB")
            out = io.BytesIO()
            image.save(out, format="WEBP", quality=82, method=6)
            return out.getvalue(), int(image.width), int(image.height)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"unsupported/corrupt image: {exc}") from exc


def materialize(
    db: Path,
    output_dir: Path,
    manifest_path: Path,
    *,
    public_prefix: str,
    limit: int,
    width: int,
    max_source_bytes: int,
    delay_seconds: float,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    public_prefix = public_prefix.rstrip("/") + "/"
    successes: list[dict] = []
    failures: list[dict] = []

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "plant_image_asset" not in tables:
            raise RuntimeError("catalog lacks plant_image_asset")
        rows = conn.execute(_priority_sql(conn) + " LIMIT ?", (max(0, int(limit)),)).fetchall()

        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(35.0, connect=15.0),
            headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.5"},
        ) as client:
            for index, row in enumerate(rows, start=1):
                asset_id = str(row["asset_id"])
                rel = safe_asset_filename(asset_id)
                target = output_dir / rel
                try:
                    webp, image_width, image_height = download_thumbnail(
                        client,
                        str(row["image_url"]),
                        width=width,
                        max_bytes=max_source_bytes,
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(webp)
                    digest = sha256_bytes(webp)
                    local_name = rel.as_posix()
                    thumbnail_url = urljoin(public_prefix, local_name)
                    conn.execute(
                        """UPDATE plant_image_asset
                           SET thumbnail_url=?, local_filename=?, materialized=1, materialization_error=NULL
                           WHERE asset_id=?""",
                        (thumbnail_url, local_name, asset_id),
                    )
                    successes.append(
                        {
                            "asset_id": asset_id,
                            "taxon_id": str(row["taxon_id"]),
                            "scientific_name": str(row["verified_taxon_name"]),
                            "local_filename": local_name,
                            "thumbnail_url": thumbnail_url,
                            "thumbnail_sha256": digest,
                            "thumbnail_bytes": len(webp),
                            "width": image_width,
                            "height": image_height,
                            "source_url": str(row["image_url"]),
                            "license": str(row["license"]),
                            "author": row["author"],
                            "attribution_url": row["attribution_url"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - one remote media failure must not abort the batch
                    message = f"{type(exc).__name__}: {exc}"[:500]
                    conn.execute(
                        "UPDATE plant_image_asset SET materialization_error=? WHERE asset_id=?",
                        (message, asset_id),
                    )
                    failures.append(
                        {
                            "asset_id": asset_id,
                            "taxon_id": str(row["taxon_id"]),
                            "source_url": str(row["image_url"]),
                            "error": message,
                        }
                    )
                if index % 50 == 0:
                    conn.commit()
                if delay_seconds > 0:
                    time.sleep(delay_seconds)
        conn.commit()

        materialized_total = int(
            conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE materialized=1").fetchone()[0]
        )
        materialized_taxa = int(
            conn.execute("SELECT COUNT(DISTINCT taxon_id) FROM plant_image_asset WHERE materialized=1").fetchone()[0]
        )
        conn.execute(
            "INSERT INTO climaflora_catalog_metadata(key,value) VALUES('image_materialized_taxa',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(materialized_taxa),),
        )
        conn.execute(
            "INSERT INTO climaflora_catalog_metadata(key,value) VALUES('image_materialization_complete','partial') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
        conn.commit()

    report = {
        "requested": len(rows),
        "successful_this_run": len(successes),
        "failed_this_run": len(failures),
        "materialized_total": materialized_total,
        "materialized_taxa": materialized_taxa,
        "thumbnail_width_max": width,
        "public_prefix": public_prefix,
        "successes": successes,
        "failures": failures[:500],
    }
    manifest_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--public-prefix", default="https://shugoan.com/climaflora/media/plants/")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--width", type=int, default=300)
    parser.add_argument("--max-source-bytes", type=int, default=DEFAULT_MAX_SOURCE_BYTES)
    parser.add_argument("--delay-seconds", type=float, default=0.05)
    args = parser.parse_args()
    report = materialize(
        args.db,
        args.output_dir,
        args.manifest,
        public_prefix=args.public_prefix,
        limit=args.limit,
        width=args.width,
        max_source_bytes=args.max_source_bytes,
        delay_seconds=args.delay_seconds,
    )
    print(json.dumps({key: value for key, value in report.items() if key not in {"successes", "failures"}}, indent=2))


if __name__ == "__main__":
    main()
