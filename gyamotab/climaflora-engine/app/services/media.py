from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlparse

IMAGE_HOSTS = {"upload.wikimedia.org"}
SOURCE_HOSTS = {"commons.wikimedia.org"}
LICENSE_HOSTS = {"creativecommons.org", "www.creativecommons.org", "commons.wikimedia.org"}
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_MATCH_METHODS = {"exact_taxon_id", "exact_scientific_name"}
PLANTNET_UNVERIFIED_LICENSE = "Pl@ntNet : licence non renseignée"

_WIKIMEDIA_REQUIRED = {
    "taxon_id", "asset_id", "source_name", "source_page_url", "thumbnail_url",
    "license", "is_primary", "match_method", "match_confidence", "retrieved_at",
}
_CATALOG_MEDIA_REQUIRED = {
    "taxon_id", "asset_id", "image_url", "license", "is_primary", "quality_rank",
}


def canonical_open_license(value: str | None) -> str | None:
    """Return an accepted media licence, including the explicit Pl@ntNet exception."""
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return None
    if raw == PLANTNET_UNVERIFIED_LICENSE:
        return raw
    upper = raw.upper()
    if "NC" in upper or "ND" in upper or "NONCOMMERCIAL" in upper or "NO DERIV" in upper:
        return None
    if upper in {"PUBLIC DOMAIN", "PUBLIC DOMAIN MARK", "PD"}:
        return "Public domain"
    if upper.startswith("CC0"):
        return raw
    if upper.startswith("CC BY-SA "):
        return raw
    if upper.startswith("CC BY "):
        return raw
    return None


def _safe_https_url(value: str | None, hosts: set[str] | None = None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    if hosts is not None and parsed.hostname not in hosts:
        return None
    if parsed.username or parsed.password:
        return None
    return raw


def safe_image_url(value: str | None) -> str | None:
    return _safe_https_url(value, IMAGE_HOSTS)


def safe_source_url(value: str | None) -> str | None:
    return _safe_https_url(value, SOURCE_HOSTS)


def safe_license_url(value: str | None) -> str | None:
    return _safe_https_url(value, LICENSE_HOSTS)


def safe_external_media_url(value: str | None) -> str | None:
    """Allow catalog/sidecar media only over HTTPS; the SQLite build is the trust boundary."""
    return _safe_https_url(value)


def _license_url_from_name(value: str | None) -> str | None:
    name = canonical_open_license(value)
    if not name or name == PLANTNET_UNVERIFIED_LICENSE:
        return None
    upper = name.upper()
    if upper.startswith("CC0"):
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    if upper.startswith("CC BY-SA "):
        parts = name.split()
        version = parts[2] if len(parts) > 2 else ""
        jurisdiction = parts[3].lower() if len(parts) > 3 else ""
        suffix = f"{version}/" + (f"{jurisdiction}/" if jurisdiction else "")
        return f"https://creativecommons.org/licenses/by-sa/{suffix}"
    if upper.startswith("CC BY "):
        parts = name.split()
        version = parts[2] if len(parts) > 2 else ""
        jurisdiction = parts[3].lower() if len(parts) > 3 else ""
        suffix = f"{version}/" + (f"{jurisdiction}/" if jurisdiction else "")
        return f"https://creativecommons.org/licenses/by/{suffix}"
    return None


def _canonical_source_name(value: str | None) -> str:
    """Normalize legacy and Media v2 provider labels without changing attribution text."""
    source = " ".join(str(value or "").strip().split())
    low = source.lower()
    if "plantnet" in low or "pl@ntnet" in low or low == "plantnet_gbif":
        return "plantnet_gbif"
    if "world_flora_online" in low or "world flora online" in low or "mbg floras images" in low:
        return "world_flora_online"
    if "atlas_living_australia_apii" in low or "australian plant image index" in low or low == "ala_apii":
        return "atlas_living_australia_apii"
    if "dryades_flora_italia" in low or "dryades" in low or "flora d'italia" in low or "flora d’italia" in low:
        return "dryades_flora_italia"
    if "wikimedia" in low or "commons" in low:
        return "wikimedia_commons"
    return "gbif_backbone"


def media_quality_rank(
    *,
    exact_taxon_id: bool = False,
    exact_scientific_name: bool = False,
    width: int | None = None,
    height: int | None = None,
    author: str | None = None,
    license_url: str | None = None,
    mime_type: str | None = None,
) -> int:
    score = 0
    if exact_taxon_id:
        score += 100
    if exact_scientific_name:
        score += 80
    if str(mime_type or "").lower() in ALLOWED_MIME:
        score += 20
    if (width or 0) >= 800:
        score += 10
    if (height or 0) >= 600:
        score += 10
    if str(author or "").strip():
        score += 5
    if safe_license_url(license_url):
        score += 5
    return score


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _chunks(values: list[str], size: int = 800):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _load_wikimedia_assets(
    conn: sqlite3.Connection,
    ids: list[str],
    columns: set[str],
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    blur_expr = "display_blurred" if "display_blurred" in columns else "0 AS display_blurred"
    reason_expr = "ambiguity_reason" if "ambiguity_reason" in columns else "NULL AS ambiguity_reason"
    image_expr = "image_url" if "image_url" in columns else "NULL AS image_url"
    license_url_expr = "license_url" if "license_url" in columns else "NULL AS license_url"
    author_expr = "author" if "author" in columns else "NULL AS author"
    attribution_expr = "attribution" if "attribution" in columns else "NULL AS attribution"
    width_expr = "width" if "width" in columns else "NULL AS width"
    height_expr = "height" if "height" in columns else "NULL AS height"
    mime_expr = "mime_type" if "mime_type" in columns else "NULL AS mime_type"
    materialized_expr = "materialized" if "materialized" in columns else "0 AS materialized"
    checked_expr = "last_checked_at" if "last_checked_at" in columns else "NULL AS last_checked_at"
    quality_expr = "quality_rank" if "quality_rank" in columns else "0 AS quality_rank"

    for batch in _chunks(ids):
        marks = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"""
            SELECT taxon_id,asset_id,source_name,source_page_url,{image_expr},thumbnail_url,
                   license,{license_url_expr},{author_expr},{attribution_expr},{width_expr},{height_expr},
                   {mime_expr},is_primary,{materialized_expr},match_method,match_confidence,retrieved_at,
                   {checked_expr},{blur_expr},{reason_expr},{quality_expr}
            FROM plant_image_asset
            WHERE is_primary=1 AND taxon_id IN ({marks})
            ORDER BY taxon_id, quality_rank DESC, asset_id
            """,
            batch,
        ).fetchall()
        for row in rows:
            taxon_id = str(row["taxon_id"])
            if taxon_id in out:
                continue
            if str(row["source_name"] or "") != "wikimedia_commons":
                continue
            if str(row["match_method"] or "") not in ALLOWED_MATCH_METHODS:
                continue
            mime = str(row["mime_type"] or "").lower()
            if mime and mime not in ALLOWED_MIME:
                continue
            licence = canonical_open_license(row["license"])
            thumb = safe_image_url(row["thumbnail_url"])
            page = safe_source_url(row["source_page_url"])
            if not licence or not thumb or not page:
                continue
            image = safe_image_url(row["image_url"]) or thumb
            license_url = safe_license_url(row["license_url"])
            out[taxon_id] = {
                "asset_id": row["asset_id"],
                "thumbnail_url": thumb,
                "image_url": image,
                "source_name": "wikimedia_commons",
                "source_page_url": page,
                "license": licence,
                "license_url": license_url,
                "author": row["author"],
                "attribution": row["attribution"],
                "width": row["width"],
                "height": row["height"],
                "mime_type": mime or None,
                "materialized": bool(row["materialized"]),
                "display_blurred": bool(row["display_blurred"]),
                "ambiguity_reason": row["ambiguity_reason"],
                "match_method": row["match_method"],
                "match_confidence": row["match_confidence"],
                "retrieved_at": row["retrieved_at"],
                "last_checked_at": row["last_checked_at"],
            }
    return out


def _load_catalog_media_assets(
    conn: sqlite3.Connection,
    ids: list[str],
    columns: set[str],
) -> dict[str, dict]:
    """Expose v1.7+ and Media v2 catalog-like media through one descriptive contract."""
    out: dict[str, dict] = {}
    thumb_expr = "thumbnail_url" if "thumbnail_url" in columns else "NULL AS thumbnail_url"
    source_expr = "source" if "source" in columns else "'GBIF' AS source"
    author_expr = "author" if "author" in columns else "NULL AS author"
    attribution_expr = "attribution_url" if "attribution_url" in columns else "NULL AS attribution_url"
    materialized_expr = "materialized" if "materialized" in columns else "0 AS materialized"
    verified_expr = "verified_taxon_name" if "verified_taxon_name" in columns else "NULL AS verified_taxon_name"

    for batch in _chunks(ids):
        marks = ",".join("?" for _ in batch)
        rows = conn.execute(
            f"""
            SELECT taxon_id,asset_id,{thumb_expr},image_url,{source_expr},license,{author_expr},
                   {attribution_expr},is_primary,quality_rank,{materialized_expr},{verified_expr}
            FROM plant_image_asset
            WHERE is_primary=1 AND taxon_id IN ({marks})
            ORDER BY taxon_id, quality_rank DESC, asset_id
            """,
            batch,
        ).fetchall()
        for row in rows:
            taxon_id = str(row["taxon_id"])
            if taxon_id in out:
                continue
            licence = canonical_open_license(row["license"])
            image = safe_external_media_url(row["image_url"])
            thumb = safe_external_media_url(row["thumbnail_url"]) or image
            page = safe_external_media_url(row["attribution_url"]) or image
            if not licence or not thumb or not image or not page:
                continue
            source = " ".join(str(row["source"] or "GBIF").split()).strip() or "GBIF"
            source_name = _canonical_source_name(source)
            author = " ".join(str(row["author"] or "").split()).strip() or None
            display_source = {
                "plantnet_gbif": "Pl@ntNet / GBIF",
                "atlas_living_australia_apii": "Australian Plant Image Index / ALA",
                "dryades_flora_italia": "Dryades / Flora d’Italia",
                "world_flora_online": "World Flora Online",
                "wikimedia_commons": "Wikimedia Commons",
                "gbif_backbone": source,
            }.get(source_name, source)
            attribution = " · ".join(x for x in (author, licence, display_source) if x)
            out[taxon_id] = {
                "asset_id": row["asset_id"],
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
    return out


def load_media_assets(path: str | Path, taxon_ids: list[str]) -> dict[str, dict]:
    """Read primary illustrative media; never use the network and never affect scoring."""
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
        columns = _columns(conn, "plant_image_asset")
        if _WIKIMEDIA_REQUIRED <= columns:
            return _load_wikimedia_assets(conn, ids, columns)
        if _CATALOG_MEDIA_REQUIRED <= columns:
            return _load_catalog_media_assets(conn, ids, columns)
    return {}


def _base_status(db: Path) -> dict:
    return {
        "ready": False,
        "path": str(db),
        "source": "unavailable",
        "scoring_effect": False,
        "uncertain_media_policy": "retain_blurred",
        "media_taxa_total": 0,
        "media_catalog_taxa_total": 0,
        "media_primary_taxa": 0,
        "media_clear_primary": 0,
        "media_blurred_primary": 0,
        "media_coverage_pct": 0.0,
        "media_source_wikimedia": 0,
        "media_source_gbif": 0,
        "media_source_plantnet_gbif": 0,
        "media_source_atlas_living_australia_apii": 0,
        "media_source_dryades_flora_italia": 0,
        "media_source_world_flora_online": 0,
        "media_unverified_license": 0,
        "media_rejected_license": 0,
        "media_rejected_taxonomy": 0,
        "media_missing": 0,
        "media_broken_thumbnail": 0,
        "media_primary_duplicate_taxa": 0,
        "licenses": {},
    }


def _wikimedia_status(conn: sqlite3.Connection, db: Path, columns: set[str]) -> dict:
    base = _base_status(db)
    primary = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1").fetchone()[0])
    taxa = int(conn.execute("SELECT COUNT(DISTINCT taxon_id) FROM plant_image_asset").fetchone()[0])
    blurred = int(conn.execute(
        "SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1 AND display_blurred=1"
    ).fetchone()[0]) if "display_blurred" in columns else 0
    duplicates = int(conn.execute(
        "SELECT COUNT(*) FROM (SELECT taxon_id FROM plant_image_asset WHERE is_primary=1 GROUP BY taxon_id HAVING COUNT(*)>1)"
    ).fetchone()[0])
    broken = int(conn.execute(
        "SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1 AND (thumbnail_url IS NULL OR trim(thumbnail_url)='')"
    ).fetchone()[0])
    invalid_legal = int(conn.execute(
        """
        SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1 AND (
          license IS NULL OR trim(license)='' OR upper(license) LIKE '%NC%' OR upper(license) LIKE '%ND%'
        )
        """
    ).fetchone()[0])
    invalid_match = int(conn.execute(
        "SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1 AND match_method NOT IN ('exact_taxon_id','exact_scientific_name')"
    ).fetchone()[0])
    wrong_source = int(conn.execute(
        "SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1 AND source_name<>'wikimedia_commons'"
    ).fetchone()[0])
    licenses = {
        str(row[0]): int(row[1])
        for row in conn.execute(
            "SELECT license,COUNT(*) FROM plant_image_asset WHERE is_primary=1 GROUP BY license ORDER BY license"
        )
    }
    attempts = {}
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "media_ingest_attempt" in tables:
        attempts = {
            str(row[0]): int(row[1])
            for row in conn.execute("SELECT result,COUNT(*) FROM media_ingest_attempt GROUP BY result")
        }
    requested = sum(attempts.values()) or taxa
    base.update({
        "ready": duplicates == 0 and broken == 0 and invalid_legal == 0 and invalid_match == 0 and wrong_source == 0,
        "source": "wikimedia_commons",
        "media_taxa_total": taxa,
        "media_primary_taxa": primary,
        "media_clear_primary": primary - blurred,
        "media_blurred_primary": blurred,
        "media_coverage_pct": round((primary / requested * 100.0), 3) if requested else 0.0,
        "media_source_wikimedia": primary - wrong_source,
        "media_rejected_license": attempts.get("rejected_license", 0),
        "media_rejected_taxonomy": attempts.get("rejected_taxonomy", 0),
        "media_missing": attempts.get("no_result", 0),
        "media_broken_thumbnail": broken,
        "media_primary_duplicate_taxa": duplicates,
        "licenses": licenses,
    })
    return base


def _metadata(conn: sqlite3.Connection) -> dict[str, str]:
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "media_metadata" not in tables:
        return {}
    return {str(row[0]): str(row[1]) for row in conn.execute("SELECT key,value FROM media_metadata")}


def _catalog_media_status(conn: sqlite3.Connection, db: Path, columns: set[str]) -> dict:
    base = _base_status(db)
    primary = int(conn.execute("SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1").fetchone()[0])
    taxa = int(conn.execute("SELECT COUNT(DISTINCT taxon_id) FROM plant_image_asset").fetchone()[0])
    duplicates = int(conn.execute(
        "SELECT COUNT(*) FROM (SELECT taxon_id FROM plant_image_asset WHERE is_primary=1 GROUP BY taxon_id HAVING COUNT(*)>1)"
    ).fetchone()[0])
    broken_expr = "(image_url IS NULL OR trim(image_url)='')"
    if "thumbnail_url" in columns:
        broken_expr = "((thumbnail_url IS NULL OR trim(thumbnail_url)='') AND (image_url IS NULL OR trim(image_url)=''))"
    broken = int(conn.execute(
        f"SELECT COUNT(*) FROM plant_image_asset WHERE is_primary=1 AND {broken_expr}"
    ).fetchone()[0])
    licenses = {
        str(row[0]): int(row[1])
        for row in conn.execute(
            "SELECT license,COUNT(*) FROM plant_image_asset WHERE is_primary=1 GROUP BY license ORDER BY license"
        )
    }
    invalid_legal = sum(count for name, count in licenses.items() if canonical_open_license(name) is None)
    unverified = licenses.get(PLANTNET_UNVERIFIED_LICENSE, 0)
    source_counts: dict[str, int] = {}
    if "source" in columns:
        for raw_source, count in conn.execute(
            "SELECT source,COUNT(*) FROM plant_image_asset WHERE is_primary=1 GROUP BY source"
        ):
            key = _canonical_source_name(raw_source)
            source_counts[key] = source_counts.get(key, 0) + int(count)
    else:
        source_counts["gbif_backbone"] = primary
    meta = _metadata(conn)
    try:
        catalog_total = int(meta.get("catalog_taxa_total", "0") or 0)
    except ValueError:
        catalog_total = 0
    denominator = catalog_total or taxa
    declared_source = meta.get("source") or (
        "media_v2" if source_counts.get("plantnet_gbif") or source_counts.get("atlas_living_australia_apii") or source_counts.get("dryades_flora_italia") or source_counts.get("world_flora_online") else "catalog_gbif"
    )
    base.update({
        "ready": duplicates == 0 and broken == 0 and invalid_legal == 0,
        "source": declared_source,
        "uncertain_media_policy": "plantnet_unverified_allowed",
        "media_taxa_total": taxa,
        "media_catalog_taxa_total": catalog_total,
        "media_primary_taxa": primary,
        "media_clear_primary": primary,
        "media_blurred_primary": 0,
        "media_coverage_pct": round((primary / denominator * 100.0), 3) if denominator else 0.0,
        "media_source_gbif": source_counts.get("gbif_backbone", 0),
        "media_source_plantnet_gbif": source_counts.get("plantnet_gbif", 0),
        "media_source_atlas_living_australia_apii": source_counts.get("atlas_living_australia_apii", 0),
        "media_source_dryades_flora_italia": source_counts.get("dryades_flora_italia", 0),
        "media_source_world_flora_online": source_counts.get("world_flora_online", 0),
        "media_unverified_license": unverified,
        "media_rejected_license": invalid_legal,
        "media_broken_thumbnail": broken,
        "media_primary_duplicate_taxa": duplicates,
        "licenses": licenses,
    })
    return base


def media_status(path: str | Path) -> dict:
    db = Path(path)
    base = _base_status(db)
    if not db.exists():
        return base
    uri = f"file:{db.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "plant_image_asset" not in tables:
            return base
        columns = _columns(conn, "plant_image_asset")
        if _WIKIMEDIA_REQUIRED <= columns:
            return _wikimedia_status(conn, db, columns)
        if _CATALOG_MEDIA_REQUIRED <= columns:
            return _catalog_media_status(conn, db, columns)
    return base
