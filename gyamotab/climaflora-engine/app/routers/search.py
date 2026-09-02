from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, wait
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings, get_settings
from app.domain.models import Horizon, Scenario
from app.routers.api import (
    _catalog_path,
    _require_public_analysis,
    _score_candidate,
    _soil_overrides,
    _soil_profile,
)
from app.services.climate import make_climate_provider
from app.services.funnel_metadata import (
    canonical_function_counts,
    install_exhaustive_metadata_patch,
)
from app.services.search_runtime import (
    climate_scientific_signature,
    elapsed_ms,
    soil_scientific_signature,
    timed_call,
)
from app.services.search_vector_runtime import vector_runtime_search

# Install the catalog-navigation normalization before the exhaustive function is
# used. The scoring formula itself is untouched; only eligibility metadata and
# facet labels are normalized to the public Type/Function vocabulary.
install_exhaustive_metadata_patch()

from app.services.exhaustive_search import exhaustive_search  # noqa: E402
from app.services.plants import make_plant_repository
from app.services.soil import make_soil_provider
from app.version import (
    CATALOG_SCHEMA_VERSION,
    METHOD_VERSION,
    SEARCH_CACHE_FORMAT_VERSION,
    SEARCH_RUNTIME_FORMAT_VERSION,
)

router = APIRouter()
_PROFILE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="climaflora-profile")
_PROFILE_ACQUISITION_TIMEOUT_SECONDS = 75.0


@router.get("/recommendations/search")
def exhaustive_recommendations(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    horizon: Horizon = Horizon.Y2050,
    scenario: Scenario = Scenario.MEDIUM,
    life_form: str = Query(
        default="ALL",
        pattern="^(ALL|TREE|SHRUB|HERB|CLIMBER|PALM|OTHER|UNKNOWN)$",
    ),
    function: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]),
    soil_status: list[str] = Query(default=[]),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    soil_ph: float | None = Query(default=None, ge=0, le=14),
    soil_clay: float | None = Query(default=None, ge=0, le=100),
    soil_sand: float | None = Query(default=None, ge=0, le=100),
    soil_silt: float | None = Query(default=None, ge=0, le=100),
    soil_cec: float | None = Query(default=None, ge=0, le=200),
    soil_coarse_fragments: float | None = Query(default=None, ge=0, le=100),
    soil_soc: float | None = Query(default=None, ge=0, le=1000),
    soil_nitrogen: float | None = Query(default=None, ge=0, le=100),
    soil_drainage: str | None = Query(
        default=None,
        pattern="^(well_drained|moderate|poor|excessive)?$",
    ),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Exhaustive funnel: type -> documented function -> climate -> soil -> facets."""
    request_started = perf_counter()
    timings_ms: dict[str, float] = {}

    stage = perf_counter()
    _require_public_analysis(settings)
    timings_ms["readiness_gate"] = elapsed_ms(stage)

    catalog_path = _catalog_path(settings)
    stage = perf_counter()
    repository = make_plant_repository(catalog_path)
    timings_ms["repository_init"] = elapsed_ms(stage)

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

    # CHELSA and SoilGrids are independent acquisitions. Run both concurrently
    # so request latency approaches max(climate, soil) instead of their sum.
    climate_provider = make_climate_provider(
        settings.climate_provider,
        settings.climate_manifest,
    )
    acquisition_started = perf_counter()
    climate_future = _PROFILE_EXECUTOR.submit(
        timed_call,
        climate_provider.profile,
        lat,
        lon,
        horizon,
        scenario,
    )
    soil_future = _PROFILE_EXECUTOR.submit(
        timed_call,
        _soil_profile,
        settings,
        lat,
        lon,
        overrides,
    )

    done, _pending = wait(
        (climate_future, soil_future),
        timeout=_PROFILE_ACQUISITION_TIMEOUT_SECONDS,
    )
    if climate_future not in done:
        climate_future.cancel()
        soil_future.cancel()
        timings_ms["profile_acquisition_wall"] = elapsed_ms(acquisition_started)
        raise HTTPException(
            status_code=503,
            detail=(
                "Acquisition climatique CHELSA trop longue; réessayez dans quelques instants. "
                f"Timeout {_PROFILE_ACQUISITION_TIMEOUT_SECONDS:.0f}s."
            ),
        )

    climate, climate_ms, climate_error = climate_future.result()
    if soil_future in done:
        soil, soil_ms, soil_error = soil_future.result()
    else:
        soil_future.cancel()
        soil = None
        soil_ms = _PROFILE_ACQUISITION_TIMEOUT_SECONDS * 1000.0
        soil_error = FuturesTimeoutError("SoilGrids profile acquisition timeout")

    timings_ms["climate_profile"] = climate_ms
    timings_ms["soil_profile"] = soil_ms
    timings_ms["profile_acquisition_wall"] = elapsed_ms(acquisition_started)

    if climate_error is not None:
        raise climate_error

    if soil_error is not None:
        soil = make_soil_provider("unavailable").profile(lat, lon, overrides)
        warnings.append(
            f"SoilGrids indisponible pour ce calcul ({type(soil_error).__name__}); "
            "le classement climatique reste valide."
        )
    else:
        warnings.extend(soil.warnings)

    stage = perf_counter()
    climate_signature = climate_scientific_signature(climate)
    soil_signature = soil_scientific_signature(soil)
    timings_ms["scientific_signatures"] = elapsed_ms(stage)

    stage = perf_counter()
    search_engine = "sqlite-exhaustive"
    vector_details: dict | None = None
    if settings.search_vector_enabled:
        try:
            result = vector_runtime_search(
                catalog_path,
                climate=climate,
                soil=soil,
                life_form=life_form,
                functions=function,
                statuses=status,
                soil_statuses=soil_status,
                offset=offset,
                limit=limit,
                min_known_weight=settings.min_known_weight,
            )
            search_engine = "vector-v0.10"
            vector_details = result.get("vector_runtime")
        except Exception as exc:  # noqa: BLE001 - guarded rollout keeps legacy path available
            if not settings.search_vector_fallback_enabled:
                raise
            warnings.append(
                f"Runtime vectoriel v0.10 indisponible ({type(exc).__name__}); "
                "repli automatique sur le moteur exhaustif SQLite."
            )
            result = exhaustive_search(
                catalog_path,
                climate_variables=climate.variables,
                soil_variables=soil.properties,
                life_form=life_form,
                functions=function,
                statuses=status,
                soil_statuses=soil_status,
                offset=offset,
                limit=limit,
                min_known_weight=settings.min_known_weight,
            )
            search_engine = "sqlite-exhaustive-fallback"
    else:
        result = exhaustive_search(
            catalog_path,
            climate_variables=climate.variables,
            soil_variables=soil.properties,
            life_form=life_form,
            functions=function,
            statuses=status,
            soil_statuses=soil_status,
            offset=offset,
            limit=limit,
            min_known_weight=settings.min_known_weight,
        )
    timings_ms["scientific_ranking"] = elapsed_ms(stage)

    # Legacy SQL uses source-native plant_use internally and needs the canonical
    # sidecar facet replacement. The vector path already derives the same facet
    # directly from canonical function bit masks.
    stage = perf_counter()
    if not search_engine.startswith("vector-"):
        result["facets"]["functions"] = canonical_function_counts(catalog_path, life_form)
    timings_ms["canonical_function_facets"] = elapsed_ms(stage)

    stage = perf_counter()
    recommendations = [
        _score_candidate(candidate, climate, soil, settings)
        for candidate in result["candidates"]
    ]
    timings_ms["hydrate_and_explain_page"] = elapsed_ms(stage)

    stage = perf_counter()
    readiness_state = repository.readiness()
    metadata = readiness_state.get("build_metadata", {})
    if str(metadata.get("mode", "")).startswith("SCIENTIFIC_PROXY_"):
        warnings.append(
            "Enveloppe climatique régionale WCVP/TDWG-3 : proxy de niche réalisée, "
            "confiance plafonnée à C."
        )
    if not readiness_state.get("soil_preferences_ready"):
        warnings.append(
            "Certaines plantes n'ont pas de préférence édaphique directement comparable ; "
            "leur compatibilité sol reste UNKNOWN."
        )
    timings_ms["response_metadata"] = elapsed_ms(stage)
    timings_ms["total"] = elapsed_ms(request_started)

    runtime_payload = {
        "format_version": SEARCH_RUNTIME_FORMAT_VERSION,
        "cache_format_version": SEARCH_CACHE_FORMAT_VERSION,
        "engine": search_engine,
        "vector_enabled": bool(settings.search_vector_enabled),
        "fallback_enabled": bool(settings.search_vector_fallback_enabled),
        "timings_ms": timings_ms,
        "profile_acquisition": "parallel-bounded-v0.10.1",
        "scientific_signatures": {
            "climate": climate_signature,
            "soil": soil_signature,
            "basis": "resolved_scoring_inputs",
        },
    }
    if vector_details is not None:
        runtime_payload["vector"] = vector_details

    return {
        "climate": climate,
        "soil": soil,
        "recommendations": recommendations,
        "method_version": METHOD_VERSION,
        "catalog_schema_version": CATALOG_SCHEMA_VERSION,
        "search_runtime": runtime_payload,
        "evaluated_candidates": result["metrics"]["evaluated_candidates"],
        "metrics": result["metrics"],
        "facets": result["facets"],
        "pagination": result["pagination"],
        "search_token": result["search_token"],
        "cache_hit": result["cache_hit"],
        "active_filters": {
            "life_form": life_form,
            "functions": list(dict.fromkeys(function)),
            "climate_status": status,
            "soil_status": soil_status,
        },
        "funnel": [
            "life_form",
            "documented_function",
            "climate_exhaustive",
            "soil",
            "facets",
            "pagination",
        ],
        "search_scope": "all_catalog_taxa_after_type_and_function",
        "alphabetical_prelimit": False,
        "function_code_space": "canonical_public",
        "life_form_mapping": "wcvp_normalized_v2",
        "warnings": warnings,
    }
