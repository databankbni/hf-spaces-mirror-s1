from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings, get_settings
from app.domain.models import Horizon, Scenario
from app.services.climate import make_climate_provider
from app.services.life_form_candidates import iter_candidates_by_life_form
from app.services.media import media_status
from app.services.media_taxonomy import load_media_assets_with_species_fallback
from app.services.plants import make_plant_repository

router = APIRouter()


def _catalog_path(settings: Settings) -> Path:
    return Path(settings.catalog_db if settings.catalog_enrichment_enabled else settings.master_db)


def _chunks(values: list[str], size: int = 800):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _classify_life_form(value: str | None) -> str:
    """Map documented life-form text to the coarse UI categories.

    This is descriptive taxonomy only; it never changes a suitability score.
    Missing life-form evidence stays UNKNOWN and is never guessed.
    """
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "UNKNOWN"
    if any(token in normalized for token in ("palm", "palmae", "palmier")):
        return "PALM"
    if any(token in normalized for token in ("climb", "liana", "vine", "grimp")):
        return "CLIMBER"
    if any(token in normalized for token in ("shrub", "bush", "arbust")):
        return "SHRUB"
    if any(token in normalized for token in ("tree", "arbores", "arbre")):
        return "TREE"
    if any(token in normalized for token in ("herb", "forb", "graminoid", "grass", "herbac")):
        return "HERB"
    return "OTHER"


def _life_form_map(path: Path, ids: list[str]) -> dict[str, str]:
    if not ids or not path.exists():
        return {}
    uri = f"file:{path.resolve()}?mode=ro"
    out: dict[str, str] = {}
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for batch in _chunks(ids):
            marks = ",".join("?" for _ in batch)
            if "plant_profile" in tables:
                for row in conn.execute(
                    f"SELECT taxon_id,life_form FROM plant_profile WHERE taxon_id IN ({marks})",
                    batch,
                ):
                    value = str(row["life_form"] or "").strip()
                    if value:
                        out[str(row["taxon_id"])] = value
            if "plant_trait_evidence" in tables:
                missing = [taxon_id for taxon_id in batch if taxon_id not in out]
                if missing:
                    missing_marks = ",".join("?" for _ in missing)
                    for row in conn.execute(
                        f"""
                        SELECT taxon_id,trait_value
                        FROM plant_trait_evidence
                        WHERE trait_name='life_form' AND taxon_id IN ({missing_marks})
                        ORDER BY taxon_id, confidence DESC, source_id
                        """,
                        missing,
                    ):
                        taxon_id = str(row["taxon_id"])
                        value = str(row["trait_value"] or "").strip()
                        if value and taxon_id not in out:
                            out[taxon_id] = value
    return out


@router.get("/plants/enrichment")
def plant_enrichment(
    taxon_id: list[str] = Query(default=[]),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Return descriptive catalog metadata that never participates in suitability scoring."""
    ids = list(dict.fromkeys(str(value).strip() for value in taxon_id if str(value).strip()))
    if not ids:
        return {"taxa": {}, "scoring_effect": False, "image_scoring_effect": False}
    if len(ids) > 250:
        raise HTTPException(status_code=400, detail="At most 250 taxon_id values are allowed per request")

    path = _catalog_path(settings)
    if not path.exists():
        raise HTTPException(status_code=503, detail="Scientific catalog is not ready")

    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        marks = ",".join("?" for _ in ids)
        out = {
            taxon: {
                "life_form": None,
                "life_form_category": "UNKNOWN",
                "vernacular_name_fr": None,
                "vernacular_name_en": None,
                "uses": [],
                "image": None,
                "image_scoring_effect": False,
            }
            for taxon in ids
        }

        life_forms = _life_form_map(path, ids)
        for taxon, value in life_forms.items():
            out[taxon]["life_form"] = value
            out[taxon]["life_form_category"] = _classify_life_form(value)

        if "plant_vernacular_name" in tables:
            rows = conn.execute(
                f"""
                SELECT taxon_id,name,language,is_preferred
                FROM plant_vernacular_name
                WHERE taxon_id IN ({marks}) AND language IN ('fr','en')
                ORDER BY taxon_id,
                         CASE language WHEN 'fr' THEN 0 ELSE 1 END,
                         is_preferred DESC,
                         name COLLATE NOCASE
                """,
                ids,
            ).fetchall()
            for row in rows:
                taxon = str(row["taxon_id"])
                language = str(row["language"] or "")
                key = "vernacular_name_fr" if language == "fr" else "vernacular_name_en"
                if out[taxon][key] is None:
                    out[taxon][key] = str(row["name"])

        if "plant_use" in tables:
            rows = conn.execute(
                f"""
                SELECT taxon_id,use_code,use_category_en,use_category_fr,source_id,
                       source_reference,source_license,taxonomy_match_method,
                       taxonomy_match_confidence,evidence_level,refinement_status
                FROM plant_use
                WHERE taxon_id IN ({marks})
                ORDER BY taxon_id,use_code
                """,
                ids,
            ).fetchall()
            for row in rows:
                out[str(row["taxon_id"])]["uses"].append(
                    {
                        "code": row["use_code"],
                        "label_fr": row["use_category_fr"],
                        "label_en": row["use_category_en"],
                        "source_id": row["source_id"],
                        "source_reference": row["source_reference"],
                        "source_license": row["source_license"],
                        "taxonomy_match_method": row["taxonomy_match_method"],
                        "taxonomy_match_confidence": row["taxonomy_match_confidence"],
                        "evidence_level": row["evidence_level"],
                        "refinement_status": row["refinement_status"],
                    }
                )

    media = load_media_assets_with_species_fallback(settings.media_db, path, ids)
    for taxon, image in media.items():
        if taxon in out:
            out[taxon]["image"] = image

    return {
        "taxa": out,
        "scoring_effect": False,
        "image_scoring_effect": False,
        "interpretation": "Descriptive metadata only; uses are reported categories and images are illustrative, never scoring or identification evidence.",
    }


@router.get("/media/status")
def media_layer_status(settings: Settings = Depends(get_settings)) -> dict:
    """Expose auditable non-scientific media coverage and legal integrity metrics."""
    return media_status(settings.media_db)


@router.get("/recommendations/by-life-form")
def recommendations_by_life_form(
    life_form: str = Query(pattern="^(TREE|SHRUB|HERB|CLIMBER|PALM|OTHER)$"),
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    horizon: Horizon = Horizon.Y2050,
    scenario: Scenario = Scenario.MEDIUM,
    function: list[str] = Query(default=[]),
    limit: int = Query(default=50, ge=1, le=1000),
    soil_ph: float | None = Query(default=None, ge=0, le=14),
    soil_clay: float | None = Query(default=None, ge=0, le=100),
    soil_sand: float | None = Query(default=None, ge=0, le=100),
    soil_silt: float | None = Query(default=None, ge=0, le=100),
    soil_cec: float | None = Query(default=None, ge=0, le=200),
    soil_coarse_fragments: float | None = Query(default=None, ge=0, le=100),
    soil_soc: float | None = Query(default=None, ge=0, le=1000),
    soil_nitrogen: float | None = Query(default=None, ge=0, le=100),
    soil_drainage: str | None = Query(default=None, pattern="^(well_drained|moderate|poor|excessive)?$"),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Rank candidates with life form applied before rough climate/soil pagination.

    Life form is a documented descriptive eligibility filter only. It never
    contributes to the numerical score. The full catalog is first restricted
    to the requested documented life-form category, then the existing rough
    climate/soil ranking constructs the candidate pool, then exact scoring and
    public pagination are applied.
    """
    from app.routers.api import (
        _require_public_analysis,
        _score_candidate,
        _soil_overrides,
        _soil_profile,
        _sort_key,
    )
    from app.version import METHOD_VERSION

    _require_public_analysis(settings)
    path = _catalog_path(settings)
    repository = make_plant_repository(str(path))
    climate = make_climate_provider(settings.climate_provider, settings.climate_manifest).profile(
        lat, lon, horizon, scenario
    )
    overrides = _soil_overrides(
        soil_ph,
        soil_clay,
        soil_sand,
        soil_silt,
        soil_cec,
        soil_coarse_fragments,
        soil_soc,
        soil_nitrogen,
        soil_drainage,
    )
    warnings: list[str] = []
    try:
        soil = _soil_profile(settings, lat, lon, overrides)
        warnings.extend(getattr(soil, "warnings", []) or [])
    except Exception as exc:  # noqa: BLE001
        from app.services.soil import make_soil_provider

        soil = make_soil_provider("unavailable").profile(lat, lon, overrides)
        warnings.append(
            f"SoilGrids indisponible pour ce calcul ({type(exc).__name__}); le classement climatique reste valide."
        )

    pool_limit = max(limit, settings.candidate_pool_limit)
    candidates, eligible_count = iter_candidates_by_life_form(
        repository,
        life_form=life_form,
        functions=function,
        limit=pool_limit,
        climate_variables=climate.variables,
        soil_variables=soil.properties,
    )
    scored = [_score_candidate(candidate, climate, soil, settings) for candidate in candidates]
    scored.sort(key=_sort_key)

    return {
        "climate": climate,
        "soil": soil,
        "recommendations": scored[:limit],
        "method_version": METHOD_VERSION,
        "evaluated_candidates": len(scored),
        "life_form_catalog_candidates": eligible_count,
        "candidate_pool_before_life_form": eligible_count,
        "candidate_pool_after_life_form_ranking": len(candidates),
        "life_form_filter": life_form,
        "life_form_filter_stage": "before_rough_ranking",
        "life_form_scoring_effect": False,
        "warnings": warnings,
    }
