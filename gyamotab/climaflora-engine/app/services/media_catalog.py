from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.media import (
    _canonical_source_name,
    _license_url_from_name,
    canonical_open_license,
    load_media_assets,
    safe_external_media_url,
)

MAX_IMAGES_PER_TAXON = 3

_SOURCE_LABELS = {
    "plantnet_gbif": "Pl@ntNet / GBIF",
    "atlas_living_australia_apii": "Australian Plant Image Index / ALA",
    "dryades_flora_italia": "Dryades / Flora d’Italia",
    "world_flora_online": "World Flora Online",
    "wikimedia_commons": "Wikimedia Commons",
}


def _chunks(values: list[str], size: int = 800):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _row_asset(row: sqlite3.Row) -> dict | None:
    licence = canonical_open_license(row["license"])
    image = safe_external_media_url(row["image_url"])
    thumb = safe_external_media_url(row["thumbnail_url"]) or image
    page = safe_external_media_url(row["attribution_url"]) or image
    if not licence or not image or not thumb or not page:
        return None

    source_raw = " ".join(str(row["source"] or "").split()).strip()
    source_name = _canonical_source_name(source_raw)
    author = " ".join(str(row["author"] or "").split()).strip() or None
    source_label = _SOURCE_LABELS.get(source_name, source_raw or "Source botanique")
    attribution = " · ".join(value for value in (author, licence, source_label) if value)
    return {
        "asset_id": row["asset_id"],
        "position": int(row["position"]),
        "thumbnail_url": thumb,
        "image_url": image,
        "source_name": source_name,
        "source_page_url": page,
        "license": licence,
        "license_url": _license_url_from_name(licence),
        "author": author,
        "attribution": attribution or None,
        "width": None,
        "height": None,
        "mime_type": None,
        "materialized": bool(row["materialized"]),
        "display_blurred": False,
        "ambiguity_reason": None,
        "match_method": "exact_scientific_name",
        "match_confidence": 1.0,
        "retrieved_at": None,
        "last_checked_at": None,
        "verified_taxon_name": row["verified_taxon_name"],
    }


def load_media_asset_sets(path: str | Path, taxon_ids: list[str]) -> dict[str, list[dict]]:
    """Return zero-to-three normalized image assets for each requested taxon.

    Media v2.4 sidecars expose explicit positions. Older sidecars are supported
    during rolling deployment by wrapping the legacy primary image as position 1.
    The function never uses the network and never participates in scoring.
    """
    db = Path(path)
    ids = list(dict.fromkeys(str(value).strip() for value in taxon_ids if str(value).strip()))
    if not db.exists() or not ids:
        return {}

    uri = f"file:{db.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "plant_image_asset" not in tables:
            return {}
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(plant_image_asset)")}
        required = {
            "taxon_id",
            "asset_id",
            "position",
            "thumbnail_url",
            "image_url",
            "source",
            "license",
            "author",
            "attribution_url",
            "materialized",
            "verified_taxon_name",
        }
        if required <= columns:
            out: dict[str, list[dict]] = {}
            for batch in _chunks(ids):
                marks = ",".join("?" for _ in batch)
                rows = conn.execute(
                    f"""
                    SELECT taxon_id,asset_id,position,thumbnail_url,image_url,source,license,author,
                           attribution_url,materialized,verified_taxon_name
                    FROM plant_image_asset
                    WHERE taxon_id IN ({marks}) AND position BETWEEN 1 AND ?
                    ORDER BY taxon_id,position,quality_rank DESC,asset_id DESC
                    """,
                    [*batch, MAX_IMAGES_PER_TAXON],
                ).fetchall()
                for row in rows:
                    asset = _row_asset(row)
                    if asset is None:
                        continue
                    taxon_id = str(row["taxon_id"])
                    bucket = out.setdefault(taxon_id, [])
                    if len(bucket) < MAX_IMAGES_PER_TAXON:
                        bucket.append(asset)
            return out

    primary = load_media_assets(db, ids)
    return {
        taxon_id: [{**asset, "position": 1}]
        for taxon_id, asset in primary.items()
        if asset
    }
