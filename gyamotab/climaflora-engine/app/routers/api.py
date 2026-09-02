from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.domain.models import Horizon, PlantSummary, RecommendationResponse, Scenario, TrajectoryPoint, TrajectoryResponse
from app.domain.scoring import METHOD_VERSION, score_plant
from app.services.bootstrap import get_master_bootstrap
from app.services.catalog_enrichment import get_catalog_enrichment
from app.services.climate import make_climate_provider
from app.services.plants import make_plant_repository
from app.services.scientific_build import ScientificBuildService, METHOD as SCIENTIFIC_METHOD, METHOD_VERSION as SCIENTIFIC_METHOD_VERSION
from app.services.soil import make_soil_provider
from app.version import APP_VERSION, CATALOG_SCHEMA_VERSION

router = APIRouter()


def _catalog_path(settings: Settings) -> str:
    return settings.catalog_db if settings.catalog_enrichment_enabled else settings.master_db


def _catalog_service(settings: Settings):
    return get_catalog_enrichment(
        settings.master_db, settings.catalog_db, settings.catalog_snapshot_zst,
        settings.catalog_enrichment_seed, settings.catalog_enrichment_status,
        settings.master_bootstrap_status, settings.catalog_enrichment_zstd_level,
    )


def _analysis_readiness(settings: Settings) -> dict:
    climate = make_climate_provider(settings.climate_provider, settings.climate_manifest).readiness()
    soil = make_soil_provider(settings.soil_provider, settings.soilgrids_wcs_base).readiness()
    plants = make_plant_repository(_catalog_path(settings)).readiness()
    prior_safe = int(plants.get("soil_geographic_prior_scoring_rows", 0) or 0) == 0
    infrastructure_ready = bool(climate.get("ready") and plants.get("ready"))
    scientific_ready = bool(
        infrastructure_ready
        and settings.climate_provider.lower() != "demo"
        and plants.get("scientific_ready", False)
        and prior_safe
    )
    public_analysis_ready = bool(
        infrastructure_ready
        and (settings.env.lower() != "production" or settings.allow_nonscientific_public or scientific_ready)
    )
    return {
        "infrastructure_ready": infrastructure_ready,
        "scientific_ready": scientific_ready,
        "public_analysis_ready": public_analysis_ready,
        "climate": climate,
        "soil": soil,
        "plants": plants,
        "soil_geographic_prior_scoring_safe": prior_safe,
    }


def _require_climate_ready(settings: Settings) -> None:
    climate = make_climate_provider(settings.climate_provider, settings.climate_manifest).readiness()
    if not climate.get("ready") or settings.climate_provider.lower() == "demo":
        raise HTTPException(status_code=503, detail="ClimaFlora climate provider is not production-ready.")


def _require_public_analysis(settings: Settings) -> None:
    state = _analysis_readiness(settings)
    if not state["public_analysis_ready"]:
        raise HTTPException(status_code=503, detail="ClimaFlora plant analysis is not public-ready: the scientific catalog is not ready or a safety guardrail failed.")


def _soil_overrides(ph, clay, sand, silt, cec, coarse, soc, nitrogen, drainage) -> dict:
    return {
        "ph": ph,
        "clay_pct": clay,
        "sand_pct": sand,
        "silt_pct": silt,
        "cec_cmol_kg": cec,
        "coarse_fragments_pct": coarse,
        "soc_g_kg": soc,
        "nitrogen_g_kg": nitrogen,
        "drainage": drainage,
    }


def _soil_profile(settings: Settings, lat: float, lon: float, overrides: dict):
    provider = make_soil_provider(settings.soil_provider, settings.soilgrids_wcs_base)
    return provider.profile(lat, lon, overrides)


def _score_candidate(candidate: dict, climate, soil, settings: Settings):
    return score_plant(
        taxon_id=candidate["taxon_id"], scientific_name=candidate["scientific_name"],
        common_name=candidate.get("common_name"), functions=candidate.get("functions", []),
        limits=candidate["limits"], climate=climate, soil=soil, soil_limits=candidate.get("soil_limits", []),
        soil_categorical_preferences=candidate.get("soil_categorical_preferences", []),
        soil_indicators=candidate.get("soil_indicators", []),
        soil_geographic_context=candidate.get("soil_geographic_context"),
        soil_inheritance=candidate.get("soil_inheritance"),
        regulatory_veto=candidate.get("regulatory_veto", False), regulatory_reason=candidate.get("regulatory_reason"),
        evidence=candidate.get("evidence", []), links=candidate.get("links", {}), image=candidate.get("image"),
        min_known_weight=settings.min_known_weight,
    )


def _sort_key(result):
    # Climate RED can never be rescued by a good soil score, and climate UNKNOWN
    # cannot outrank a taxon with a known compatible climate. Within the known
    # GREEN/ORANGE climate band, the exact bi-axis score is the navigation order.
    climate_gate_rank = {"GREEN": 0, "ORANGE": 0, "UNKNOWN": 1, "RED": 2}
    combined_rank = {"GREEN": 0, "ORANGE": 1, "UNKNOWN": 2, "RED": 3}
    combined_score = result.combined_score if result.combined_score is not None else -1.0
    climate_score = result.overall_score if result.overall_score is not None else -1.0
    return (
        bool(result.regulatory_veto),
        climate_gate_rank.get(result.overall_status.value, 9),
        combined_rank.get(result.combined_status.value, 9),
        -combined_score,
        -climate_score,
        result.scientific_name,
    )


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    bootstrap = get_master_bootstrap(settings.master_db, settings.master_bootstrap_status, settings.master_audit_path, settings.master_source_url_list, settings.master_expected_sha256, settings.master_required_table_list, settings.master_expected_catalog_version).status()
    catalog = _catalog_service(settings).status() if settings.catalog_enrichment_enabled else {"phase": "master", "ready": bootstrap.get("ready")}
    return {
        "status": "ok", "service": "climaflora-api", "version": APP_VERSION, "environment": settings.env,
        "climate_provider": settings.climate_provider, "soil_provider": settings.soil_provider,
        "master_phase": bootstrap.get("phase"), "catalog_phase": catalog.get("phase"),
    }


@router.get("/readiness")
def readiness(settings: Settings = Depends(get_settings)) -> dict:
    state = _analysis_readiness(settings)
    master_path = Path(settings.master_db)
    bootstrap = get_master_bootstrap(settings.master_db, settings.master_bootstrap_status, settings.master_audit_path, settings.master_source_url_list, settings.master_expected_sha256, settings.master_required_table_list, settings.master_expected_catalog_version)
    master = bootstrap.status()
    master.update({"present": master_path.exists(), "path": settings.master_db})
    catalog = _catalog_service(settings).status() if settings.catalog_enrichment_enabled else {
        "phase": "master", "ready": bool(master.get("ready")), "catalog_db": settings.master_db,
        "catalog_present": master_path.exists(),
    }
    return {
        "ready": state["public_analysis_ready"], "infrastructure_ready": state["infrastructure_ready"],
        "scientific_mode": state["scientific_ready"], "scientific_ready": state["scientific_ready"],
        "climate": state["climate"], "soil": state["soil"], "plants": state["plants"], "master": master, "catalog": catalog,
        "soil_geographic_prior_scoring_safe": state["soil_geographic_prior_scoring_safe"],
        "method_version": METHOD_VERSION, "catalog_schema_version": CATALOG_SCHEMA_VERSION,
    }


@router.get("/master/status")
def master_status(settings: Settings = Depends(get_settings)) -> dict:
    return get_master_bootstrap(settings.master_db, settings.master_bootstrap_status, settings.master_audit_path, settings.master_source_url_list, settings.master_expected_sha256, settings.master_required_table_list, settings.master_expected_catalog_version).status()


@router.get("/master/audit")
def master_audit(settings: Settings = Depends(get_settings)) -> dict:
    service = get_master_bootstrap(settings.master_db, settings.master_bootstrap_status, settings.master_audit_path, settings.master_source_url_list, settings.master_expected_sha256, settings.master_required_table_list, settings.master_expected_catalog_version)
    report = service.audit()
    if report is None:
        raise HTTPException(status_code=503, detail="Master audit is not ready yet")
    return report


@router.get("/master/schema-summary")
def master_schema_summary(settings: Settings = Depends(get_settings)) -> dict:
    service = get_master_bootstrap(settings.master_db, settings.master_bootstrap_status, settings.master_audit_path, settings.master_source_url_list, settings.master_expected_sha256, settings.master_required_table_list, settings.master_expected_catalog_version)
    report = service.audit()
    if report is None:
        raise HTTPException(status_code=503, detail="Master audit is not ready yet")
    tables = report.get("tables", {})
    return {
        "database": report.get("database"), "size_bytes": report.get("size_bytes"), "audited_at": report.get("audited_at"),
        "summary": report.get("summary", {}),
        "tables": {name: {"row_count": info.get("row_count", 0), "columns": [
            {"name": col.get("name"), "type": col.get("type"), "notnull": col.get("notnull"), "pk": col.get("pk")}
            for col in info.get("columns", [])], "foreign_keys": info.get("foreign_keys", [])} for name, info in tables.items()},
    }


@router.get("/master/distribution-profile")
def master_distribution_profile(settings: Settings = Depends(get_settings)) -> dict:
    master = Path(settings.master_db)
    if not master.exists():
        raise HTTPException(status_code=503, detail="Master database is not ready yet")
    with sqlite3.connect(":memory:") as conn:
        conn.execute("ATTACH DATABASE ? AS master", (f"file:{master.resolve()}?mode=ro",))
        return ScientificBuildService._distribution_profile(conn)


@router.get("/scientific/status")
def scientific_status(settings: Settings = Depends(get_settings)) -> dict:
    plants = make_plant_repository(_catalog_path(settings)).readiness()
    bootstrap = get_master_bootstrap(
        settings.master_db, settings.master_bootstrap_status, settings.master_audit_path,
        settings.master_source_url_list, settings.master_expected_sha256,
        settings.master_required_table_list, settings.master_expected_catalog_version,
    ).status()
    catalog = _catalog_service(settings).status() if settings.catalog_enrichment_enabled else {"phase": "master", "ready": bootstrap.get("ready"), "error": None}
    master_gate = True if settings.catalog_enrichment_enabled and catalog.get("ready") else bool(bootstrap.get("ready"))
    prior_safe = int(plants.get("soil_geographic_prior_scoring_rows", 0) or 0) == 0
    ready = bool(plants.get("scientific_ready") and master_gate and catalog.get("ready") and prior_safe)
    return {
        "phase": "ready" if ready else catalog.get("phase", bootstrap.get("phase", "starting")),
        "ready": ready,
        "error": catalog.get("error") or bootstrap.get("error"),
        "catalog": Path(_catalog_path(settings)).name,
        "catalog_schema_version": CATALOG_SCHEMA_VERSION,
        "mode": plants.get("mode"),
        "plants": plants,
        "catalog_enrichment": catalog,
        "soil_geographic_prior_scoring_safe": prior_safe,
        "rebuild_required": False,
    }


@router.get("/scientific/method")
def scientific_method(settings: Settings = Depends(get_settings)) -> dict:
    state = make_plant_repository(_catalog_path(settings)).readiness()
    metadata = state.get("build_metadata", {})
    return {
        "method": metadata.get("scientific_method", SCIENTIFIC_METHOD),
        "method_version": metadata.get("scientific_method_version", SCIENTIFIC_METHOD_VERSION),
        "mode": metadata.get("mode", state.get("mode")), "scientific_ready": state.get("scientific_ready", False),
        "source_ref": metadata.get("scientific_source_ref"), "limitations": metadata.get("scientific_limitations"),
        "coverage": metadata.get("envelope_coverage"), "confidence_ceiling": "C",
        "soil_preference_envelopes": state.get("soil_envelopes", 0),
        "soil_categorical_preferences": state.get("soil_categorical_preferences", 0),
        "soil_indicator_preferences": state.get("soil_indicator_preferences", 0),
        "soil_indicator_taxa": state.get("soil_indicator_taxa", 0),
        "soil_geographic_prior_taxa": state.get("soil_geographic_prior_taxa", 0),
        "soil_geographic_prior_scoring_rows": state.get("soil_geographic_prior_scoring_rows", 0),
        "soil_note": (
            "Local SoilGrids values are compared only with sourced numeric/categorical preferences. "
            "EIVE M/N/R remain native 0–10 expert indicators and native-range geographic priors are context-only, never scored."
        ),
        "ranking": (
            "Bi-axis candidate pool = union of top climate and top climate+soil rough ranks; "
            "final exact rank keeps climate RED/UNKNOWN as conservative gates."
        ),
    }


@router.get("/catalog/status")
def catalog_status(settings: Settings = Depends(get_settings)) -> dict:
    if not settings.catalog_enrichment_enabled:
        return {"phase": "master", "ready": Path(settings.master_db).exists(), "catalog_db": settings.master_db}
    return _catalog_service(settings).status()


@router.get("/catalog/download")
def catalog_download(settings: Settings = Depends(get_settings)):
    if not settings.catalog_enrichment_enabled:
        raise HTTPException(status_code=410, detail="No runtime enrichment snapshot is configured; use the canonical production catalog.")
    service = _catalog_service(settings)
    status = service.status()
    path = Path(settings.catalog_snapshot_zst)
    if not status.get("snapshot_present") or not path.exists():
        raise HTTPException(status_code=503, detail="The enriched catalog snapshot is not ready yet.")
    return FileResponse(path, media_type="application/zstd", filename=path.name)


@router.get("/consolidation/status")
def consolidation_status(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "phase": "retired", "ready": True, "enabled": False,
        "detail": "ClimaFlora consumes a prebuilt canonical scientific catalog; runtime consolidation is disabled.",
        "catalog": settings.master_db,
    }


@router.get("/consolidation/download")
def consolidation_download():
    raise HTTPException(status_code=410, detail="Runtime consolidation is retired; use the canonical production catalog snapshot.")


@router.get("/meta")
def meta(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "service": "ClimaFlora", "version": APP_VERSION, "mode": "PRODUCTION", "method_version": METHOD_VERSION,
        "catalog": {"filename": Path(_catalog_path(settings)).name, "catalog_version": CATALOG_SCHEMA_VERSION, "single_master": True},
        "root_path": settings.normalized_root_path, "public_url": settings.public_url,
        "horizons": [{"value": h.value, "label": "Aujourd’hui" if h == Horizon.NOW else h.value} for h in Horizon],
        "scenarios": [
            {"value": "LOW", "label": "Faible", "ssp": "SSP1-2.6"},
            {"value": "MEDIUM", "label": "Intermédiaire CHELSA", "ssp": "SSP3-7.0"},
            {"value": "HIGH", "label": "Élevé", "ssp": "SSP5-8.5"},
        ],
        "functions": [
            {"value": "FOOD_HUMAN", "label": "Alimentation humaine"}, {"value": "FOOD_ANIMAL", "label": "Alimentation animale"},
            {"value": "MEDICINAL", "label": "Médicinale"}, {"value": "MATERIALS", "label": "Matériaux"},
            {"value": "FUEL", "label": "Énergie / combustible"}, {"value": "N_FIXER", "label": "Fixatrice d’azote"},
            {"value": "POLLINATOR", "label": "Intérêt pollinisateurs"}, {"value": "SOIL_FUNCTION", "label": "Fonction du sol"},
        ],
        "soil": {
            "provider": "SoilGrids 2.0 / ISRIC", "resolution_m": 250, "depth": "5-15cm", "manual_override": True,
            "properties": ["ph", "clay_pct", "sand_pct", "silt_pct", "cec_cmol_kg", "coarse_fragments_pct", "soc_g_kg", "nitrogen_g_kg"],
            "expert_indicators": "EIVE M/N/R 0–10, context only",
            "geographic_prior": "WCVP native-range × SoilGrids, scoring disabled",
        },
        "ranking": {
            "policy": "bi_axis_conservative",
            "navigation_blend": {"climate": 0.75, "soil": 0.25},
            "climate_red_rescuable": False,
            "climate_unknown_promotable": False,
        },
        "media": {"illustrative_only": True, "identification_evidence": False},
        "map": {"tile_url": settings.map_tile_url, "attribution": settings.map_attribution, "max_zoom": settings.map_max_zoom},
    }


@router.get("/climate/profile")
def climate_profile(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), horizon: Horizon = Horizon.Y2050, scenario: Scenario = Scenario.MEDIUM, settings: Settings = Depends(get_settings)):
    _require_climate_ready(settings)
    provider = make_climate_provider(settings.climate_provider, settings.climate_manifest)
    try:
        return provider.profile(lat, lon, horizon, scenario)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Climate source sampling failed: {type(exc).__name__}: {exc}") from exc


@router.get("/climate/smoke")
def climate_smoke(settings: Settings = Depends(get_settings)) -> dict:
    _require_climate_ready(settings)
    provider = make_climate_provider(settings.climate_provider, settings.climate_manifest)
    try:
        now = provider.profile(47.16, -1.27, Horizon.NOW, Scenario.MEDIUM)
        future = provider.profile(47.16, -1.27, Horizon.Y2050, Scenario.MEDIUM)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"CHELSA smoke test failed: {type(exc).__name__}: {exc}") from exc
    return {
        "status": "ok", "provider": future.provider, "location": {"lat": 47.16, "lon": -1.27},
        "now": {"period": now.period, "model": now.model, "variables": now.variables},
        "future_2050": {"period": future.period, "scenario": future.scenario, "model": future.model, "variables": future.variables,
                        "uncertainty": {key: value.model_dump() for key, value in future.uncertainty.items()}},
    }


@router.get("/soil/profile")
def soil_profile(
    lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
    soil_ph: float | None = Query(default=None, ge=0, le=14),
    soil_clay: float | None = Query(default=None, ge=0, le=100), soil_sand: float | None = Query(default=None, ge=0, le=100),
    soil_silt: float | None = Query(default=None, ge=0, le=100), soil_cec: float | None = Query(default=None, ge=0, le=200),
    soil_coarse_fragments: float | None = Query(default=None, ge=0, le=100),
    soil_soc: float | None = Query(default=None, ge=0, le=1000), soil_nitrogen: float | None = Query(default=None, ge=0, le=100),
    soil_drainage: str | None = Query(default=None, pattern="^(well_drained|moderate|poor|excessive)?$"),
    settings: Settings = Depends(get_settings),
):
    try:
        return _soil_profile(settings, lat, lon, _soil_overrides(soil_ph, soil_clay, soil_sand, soil_silt, soil_cec, soil_coarse_fragments, soil_soc, soil_nitrogen, soil_drainage))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"SoilGrids sampling failed: {type(exc).__name__}: {exc}") from exc


@router.get("/soil/smoke")
def soil_smoke(settings: Settings = Depends(get_settings)) -> dict:
    """Operational SoilGrids point test; no plant data is involved."""
    try:
        profile = _soil_profile(settings, 47.16, -1.27, {})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"SoilGrids smoke test failed: {type(exc).__name__}: {exc}") from exc
    return {"status": "ok", "profile": profile}


@router.get("/soil/validation")
def soil_validation(settings: Settings = Depends(get_settings)) -> dict:
    """On-demand multi-region operational check for position-sensitive SoilGrids sampling."""
    locations = [
        {"id": "vallet_fr", "label": "Vallet, France", "lat": 47.16, "lon": -1.27},
        {"id": "amazonas_br", "label": "Amazonas, Brésil", "lat": -3.4653, "lon": -62.2159},
        {"id": "cusco_pe", "label": "Cusco, Pérou", "lat": -13.5319, "lon": -71.9675},
        {"id": "andalusia_es", "label": "Andalousie, Espagne", "lat": 37.3891, "lon": -5.9845},
    ]
    provider = make_soil_provider(settings.soil_provider, settings.soilgrids_wcs_base)
    profiles: dict[str, dict] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(provider.profile, item["lat"], item["lon"], {}): item for item in locations}
        for future in as_completed(futures):
            item = futures[future]
            try:
                profiles[item["id"]] = future.result().model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001
                errors[item["id"]] = f"{type(exc).__name__}: {exc}"
    ordered = [{**item, "profile": profiles.get(item["id"]), "error": errors.get(item["id"])} for item in locations]
    valid_profiles = [
        p for p in ordered
        if p.get("profile") and bool(p["profile"].get("provenance", {}).get("profile_plausible"))
    ]
    invalid_ids = [p["id"] for p in ordered if p.get("profile") and p not in valid_profiles]
    signatures = {
        (
            p["profile"]["properties"].get("ph"),
            p["profile"]["properties"].get("clay_pct"),
            p["profile"]["properties"].get("sand_pct"),
            p["profile"]["properties"].get("texture_class"),
        )
        for p in valid_profiles
    }
    all_valid = len(valid_profiles) == len(locations)
    position_sensitive = len(signatures) >= 3
    return {
        "status": "ok" if all_valid and position_sensitive else "degraded",
        "provider": "SoilGrids 2.0 / ISRIC",
        "locations": ordered,
        "checks": {
            "successful_locations": len(valid_profiles),
            "failed_locations": len(errors),
            "invalid_profiles": invalid_ids,
            "distinct_profile_signatures": len(signatures),
            "position_sensitive": position_sensitive,
            "all_profiles_plausible": all_valid,
        },
    }


@router.get("/plants/search", response_model=list[PlantSummary])
def plant_search(q: str = Query(min_length=2, max_length=100), limit: int = Query(default=20, ge=1, le=50), settings: Settings = Depends(get_settings)):
    return make_plant_repository(_catalog_path(settings)).search(q, limit)


@router.get("/plants/{taxon_id}/trajectory", response_model=TrajectoryResponse)
def plant_trajectory(
    taxon_id: str, lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), scenario: Scenario = Scenario.MEDIUM,
    soil_ph: float | None = Query(default=None, ge=0, le=14),
    soil_clay: float | None = Query(default=None, ge=0, le=100), soil_sand: float | None = Query(default=None, ge=0, le=100),
    soil_silt: float | None = Query(default=None, ge=0, le=100), soil_cec: float | None = Query(default=None, ge=0, le=200),
    soil_coarse_fragments: float | None = Query(default=None, ge=0, le=100),
    soil_soc: float | None = Query(default=None, ge=0, le=1000), soil_nitrogen: float | None = Query(default=None, ge=0, le=100),
    soil_drainage: str | None = Query(default=None, pattern="^(well_drained|moderate|poor|excessive)?$"),
    settings: Settings = Depends(get_settings),
) -> TrajectoryResponse:
    _require_public_analysis(settings)
    repository = make_plant_repository(_catalog_path(settings))
    plant = repository.get(taxon_id)
    if plant is None:
        raise HTTPException(status_code=404, detail="Taxon not found")
    provider = make_climate_provider(settings.climate_provider, settings.climate_manifest)
    overrides = _soil_overrides(soil_ph, soil_clay, soil_sand, soil_silt, soil_cec, soil_coarse_fragments, soil_soc, soil_nitrogen, soil_drainage)
    try:
        soil = _soil_profile(settings, lat, lon, overrides)
    except Exception:
        soil = make_soil_provider("unavailable").profile(lat, lon, overrides)
    points = []
    for horizon in Horizon:
        climate = provider.profile(lat, lon, horizon, scenario)
        points.append(TrajectoryPoint(horizon=horizon, climate=climate, result=_score_candidate(plant, climate, soil, settings)))
    return TrajectoryResponse(
        taxon_id=plant["taxon_id"], scientific_name=plant["scientific_name"], scenario=scenario,
        soil=soil, links=plant.get("links", {}), image=plant.get("image"), points=points, method_version=METHOD_VERSION,
    )


@router.get("/recommendations", response_model=RecommendationResponse)
def recommendations(
    lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), horizon: Horizon = Horizon.Y2050,
    scenario: Scenario = Scenario.MEDIUM, function: list[str] = Query(default=[]), limit: int = Query(default=50, ge=1, le=1000),
    soil_ph: float | None = Query(default=None, ge=0, le=14),
    soil_clay: float | None = Query(default=None, ge=0, le=100), soil_sand: float | None = Query(default=None, ge=0, le=100),
    soil_silt: float | None = Query(default=None, ge=0, le=100), soil_cec: float | None = Query(default=None, ge=0, le=200),
    soil_coarse_fragments: float | None = Query(default=None, ge=0, le=100),
    soil_soc: float | None = Query(default=None, ge=0, le=1000), soil_nitrogen: float | None = Query(default=None, ge=0, le=100),
    soil_drainage: str | None = Query(default=None, pattern="^(well_drained|moderate|poor|excessive)?$"),
    settings: Settings = Depends(get_settings),
) -> RecommendationResponse:
    _require_public_analysis(settings)
    climate_provider = make_climate_provider(settings.climate_provider, settings.climate_manifest)
    repository = make_plant_repository(_catalog_path(settings))
    climate = climate_provider.profile(lat, lon, horizon, scenario)
    overrides = _soil_overrides(soil_ph, soil_clay, soil_sand, soil_silt, soil_cec, soil_coarse_fragments, soil_soc, soil_nitrogen, soil_drainage)
    warnings: list[str] = []
    try:
        soil = _soil_profile(settings, lat, lon, overrides)
        warnings.extend(soil.warnings)
    except Exception as exc:  # noqa: BLE001
        soil = make_soil_provider("unavailable").profile(lat, lon, overrides)
        warnings.append(f"SoilGrids indisponible pour ce calcul ({type(exc).__name__}); le classement climatique reste valide.")

    pool_limit = max(limit, settings.candidate_pool_limit)
    candidates = repository.iter_candidates(
        functions=function, limit=pool_limit, climate_variables=climate.variables, soil_variables=soil.properties,
    )
    scored = [_score_candidate(candidate, climate, soil, settings) for candidate in candidates]
    scored.sort(key=_sort_key)
    readiness_state = repository.readiness()
    metadata = readiness_state.get("build_metadata", {})
    if str(metadata.get("mode", "")).startswith("SCIENTIFIC_PROXY_"):
        warnings.append("Enveloppe climatique régionale WCVP/TDWG-3 : proxy de niche réalisée, confiance plafonnée à C; ce n’est pas une limite physiologique ni un modèle d’occurrences ponctuelles.")
    if not readiness_state.get("soil_preferences_ready"):
        warnings.append("Le profil local SoilGrids est actif, mais aucun critère édaphique directement scoré n’est disponible pour certains taxons; leur compatibilité sol reste UNKNOWN.")
    if int(readiness_state.get("soil_geographic_prior_scoring_rows", 0) or 0):
        warnings.append("Garde-fou scientifique : des priors géographiques sont marqués scorables dans le catalogue; ClimaFlora les ignore et ferme le mode scientifique public.")
    return RecommendationResponse(
        climate=climate, soil=soil, recommendations=scored[:limit], method_version=METHOD_VERSION,
        evaluated_candidates=len(scored), warnings=warnings,
    )
