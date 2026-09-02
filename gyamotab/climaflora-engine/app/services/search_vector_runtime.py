from __future__ import annotations

from pathlib import Path
from time import perf_counter

from app.domain.models import ClimateProfile, SoilProfile
from app.services.exhaustive_search import _hydrate_page
from app.services.search_genus_facets import apply_genus_initial_facet, split_genus_navigation
from app.services.search_vector_cache import (
    get_climate_score_vector,
    get_combined_score_vector,
    get_soil_score_vector,
    vector_cache_stats,
)
from app.services.search_vector_navigation import (
    load_navigation_runtime_matrix,
    ranking_view,
)


def vector_runtime_search(
    catalog_path: str | Path,
    *,
    climate: ClimateProfile,
    soil: SoilProfile,
    life_form: str = "ALL",
    functions: list[str] | None = None,
    statuses: list[str] | None = None,
    soil_statuses: list[str] | None = None,
    offset: int = 0,
    limit: int = 50,
    min_known_weight: float = 0.50,
) -> dict:
    """Run the v0.10 global-vector search without changing scientific scoring.

    Scientific vectors are global and cacheable. Type/function/status selections
    and the v10.10 genus-initial selection are navigation masks only. Detailed
    plant evidence is hydrated only for the visible page.
    """
    started = perf_counter()
    path = Path(catalog_path)

    matrix, climate_cached = get_climate_score_vector(
        path,
        climate,
        min_known_weight=min_known_weight,
    )
    soil_cached = get_soil_score_vector(
        path,
        matrix,
        soil,
        min_known_weight=min_known_weight,
    )
    combined_cached = get_combined_score_vector(matrix, climate_cached, soil_cached)
    navigation = load_navigation_runtime_matrix(path)

    scientific_functions, genus_initial = split_genus_navigation(functions)
    view = ranking_view(
        navigation,
        matrix,
        climate_cached.value,
        soil_cached.value,
        combined_cached.value,
        life_form=life_form,
        functions=scientific_functions,
        statuses=statuses or [],
        soil_statuses=soil_statuses or [],
        offset=0,
        limit=1,
    )

    genus_ordered, genus_page, genus_facets, genus_seconds = apply_genus_initial_facet(
        path,
        matrix.taxon_ids,
        view.ordered_ordinals,
        genus_initial=genus_initial,
        offset=offset,
        limit=limit,
    )

    page_ids = tuple(str(matrix.taxon_ids[index]) for index in genus_page)
    hydration_started = perf_counter()
    candidates = _hydrate_page(path, page_ids)
    hydration_seconds = perf_counter() - hydration_started

    metrics = dict(view.metrics)
    metrics["total_results"] = int(genus_ordered.shape[0])
    facets = dict(view.facets)
    facets["genus_initial"] = genus_facets
    total = int(metrics["total_results"])
    returned = len(candidates)

    cache_hits = {
        "climate": climate_cached.cache_hit,
        "soil": soil_cached.cache_hit,
        "ranking": combined_cached.cache_hit,
    }
    return {
        "candidates": candidates,
        "metrics": metrics,
        "facets": facets,
        "pagination": {
            "offset": max(0, int(offset)),
            "limit": max(1, int(limit)),
            "returned": returned,
            "has_previous": int(offset) > 0,
            "has_next": max(0, int(offset)) + returned < total,
        },
        "search_token": combined_cached.key[:20],
        "cache_hit": all(cache_hits.values()),
        "vector_runtime": {
            "cache_hits": cache_hits,
            "cache_keys": {
                "climate": climate_cached.key[:20],
                "soil": soil_cached.key[:20],
                "ranking": combined_cached.key[:20],
            },
            "climate_score_seconds": climate_cached.value.elapsed_seconds,
            "soil_score_seconds": soil_cached.value.elapsed_seconds,
            "combine_sort_seconds": combined_cached.value.elapsed_seconds,
            "navigation_seconds": view.elapsed_seconds,
            "genus_navigation_seconds": genus_seconds,
            "page_hydration_seconds": hydration_seconds,
            "request_runtime_seconds": perf_counter() - started,
            "cache": vector_cache_stats(),
            "genus_initial": genus_initial,
            "genus_facet_scope": "all_matching_taxa_before_pagination",
        },
    }
