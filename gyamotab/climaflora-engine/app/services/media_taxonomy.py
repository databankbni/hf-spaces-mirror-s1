from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.media_catalog import load_media_asset_sets

_INFRASPECIFIC_RANKS = {"subsp.", "ssp.", "var.", "subvar.", "f.", "forma"}


def parent_species_name(scientific_name: str | None) -> str | None:
    """Return the binomial parent for an explicitly infraspecific canonical name.

    This helper is intentionally conservative. It never guesses a parent for hybrids,
    cultivars, bare genus names, or names without an explicit infraspecific rank.
    The result is used for illustration only and never participates in scoring or
    taxonomic identification.
    """
    name = " ".join(str(scientific_name or "").strip().split())
    if not name or "×" in name or "'" in name or '"' in name:
        return None
    parts = name.split()
    if len(parts) < 4:
        return None
    for index, token in enumerate(parts):
        if token.lower() not in _INFRASPECIFIC_RANKS:
            continue
        parent = parts[:index]
        if len(parent) != 2:
            return None
        genus, epithet = parent
        if not genus or not epithet or not genus[0].isupper() or not epithet[0].islower():
            return None
        return f"{genus} {epithet}"
    return None


def _catalog_names_and_parent_ids(
    catalog_path: str | Path,
    requested_ids: list[str],
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Return requested names and unambiguous parent (taxon_id, scientific_name)."""
    db = Path(catalog_path)
    if not db.exists() or not requested_ids:
        return {}, {}

    ids = list(dict.fromkeys(str(value).strip() for value in requested_ids if str(value).strip()))
    marks = ",".join("?" for _ in ids)
    uri = f"file:{db.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "plant_index" not in tables:
            return {}, {}

        requested_names = {
            str(row["taxon_id"]): " ".join(str(row["scientific_name"] or "").split())
            for row in conn.execute(
                f"SELECT taxon_id,scientific_name FROM plant_index WHERE taxon_id IN ({marks})",
                ids,
            )
        }
        wanted_parent_names = {
            parent
            for name in requested_names.values()
            if (parent := parent_species_name(name)) is not None
        }
        if not wanted_parent_names:
            return requested_names, {}

        parent_list = sorted(wanted_parent_names)
        parent_marks = ",".join("?" for _ in parent_list)
        by_name: dict[str, list[str]] = {}
        for row in conn.execute(
            f"SELECT taxon_id,scientific_name FROM plant_index WHERE scientific_name IN ({parent_marks})",
            parent_list,
        ):
            name = " ".join(str(row["scientific_name"] or "").split())
            by_name.setdefault(name, []).append(str(row["taxon_id"]))

    parents: dict[str, tuple[str, str]] = {}
    for requested_id, requested_name in requested_names.items():
        parent_name = parent_species_name(requested_name)
        if not parent_name:
            continue
        parent_ids = by_name.get(parent_name, [])
        if len(parent_ids) == 1:
            parents[requested_id] = (parent_ids[0], parent_name)
    return requested_names, parents


def _exact_asset(image: dict, taxon_id: str) -> dict:
    out = dict(image)
    out.setdefault("taxonomic_fallback", False)
    out.setdefault("requested_taxon_id", taxon_id)
    return out


def _parent_asset(
    image: dict,
    *,
    requested_id: str,
    requested_name: str | None,
    parent_id: str,
    parent_name: str,
) -> dict:
    out = dict(image)
    out.update(
        {
            "taxonomic_fallback": True,
            "taxonomic_fallback_level": "parent_species",
            "requested_taxon_id": requested_id,
            "requested_taxon_name": requested_name,
            "illustrated_taxon_id": parent_id,
            "illustrated_taxon_name": parent_name,
            "match_method": "parent_species_illustration",
            "match_confidence": None,
        }
    )
    original_attribution = str(out.get("attribution") or "").strip()
    prefix = f"Photo de l’espèce de référence {parent_name}"
    out["attribution"] = f"{prefix} · {original_attribution}" if original_attribution else prefix
    return out


def load_media_asset_sets_with_species_fallback(
    media_path: str | Path,
    catalog_path: str | Path,
    taxon_ids: list[str],
) -> dict[str, list[dict]]:
    """Load up to three exact images, then use parent-species sets for explicit infraspecific gaps.

    Exact images always win. Parent fallback remains illustration-only and every
    copied asset carries explicit provenance showing that it depicts the parent
    species rather than the requested infraspecific taxon.
    """
    ids = list(dict.fromkeys(str(value).strip() for value in taxon_ids if str(value).strip()))
    if not ids:
        return {}

    raw = load_media_asset_sets(media_path, ids)
    out = {
        taxon_id: [_exact_asset(image, taxon_id) for image in images]
        for taxon_id, images in raw.items()
        if images
    }
    missing = [taxon_id for taxon_id in ids if taxon_id not in out]
    if not missing:
        return out

    requested_names, parent_map = _catalog_names_and_parent_ids(catalog_path, missing)
    if not parent_map:
        return out

    parent_ids = list(dict.fromkeys(parent_id for parent_id, _ in parent_map.values()))
    parent_sets = load_media_asset_sets(media_path, parent_ids)
    for requested_id, (parent_id, parent_name) in parent_map.items():
        images = parent_sets.get(parent_id) or []
        if not images:
            continue
        requested_name = requested_names.get(requested_id)
        out[requested_id] = [
            _parent_asset(
                image,
                requested_id=requested_id,
                requested_name=requested_name,
                parent_id=parent_id,
                parent_name=parent_name,
            )
            for image in images
        ]
    return out


def load_media_assets_with_species_fallback(
    media_path: str | Path,
    catalog_path: str | Path,
    taxon_ids: list[str],
) -> dict[str, dict]:
    """Compatibility view: primary image plus up to two alternate images.

    The existing API/frontend continues to read the primary fields directly.
    Media v2.4 additionally exposes ``image_count`` and ``alternates`` so plant
    sheets can render a gallery without a second storage lookup.
    """
    sets = load_media_asset_sets_with_species_fallback(media_path, catalog_path, taxon_ids)
    out: dict[str, dict] = {}
    for taxon_id, images in sets.items():
        if not images:
            continue
        primary = dict(images[0])
        primary["image_count"] = len(images)
        primary["alternates"] = [dict(image) for image in images[1:3]]
        out[taxon_id] = primary
    return out
