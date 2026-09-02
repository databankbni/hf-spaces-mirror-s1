from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from app.services.exhaustive_search import _CACHE, _cache_key, _status_filter, exhaustive_search
from app.services.funnel_metadata import (
    canonical_function_counts,
    install_exhaustive_metadata_patch,
    warm_funnel_metadata,
)
from app.services.search_soil_vector import combine_score_vectors, score_soil_vector
from app.services.search_vector import load_climate_runtime_matrix, score_climate_vector
from app.services.search_vector_navigation import load_navigation_runtime_matrix, ranking_view

CLIMATE = {
    "bio01": 13.95,
    "bio05": 27.45,
    "bio06": 3.75,
    "bio12": 823.5,
    "bio15": 26.0,
}
SOIL = {
    "ph": 6.5,
    "clay_pct": 20.0,
    "sand_pct": 45.0,
    "silt_pct": 35.0,
    "cec_cmol_kg": 14.0,
    "coarse_fragments_pct": 5.0,
    "soc_g_kg": 20.0,
    "nitrogen_g_kg": 1.5,
    "texture": "texture mixte",
    "texture_class": "medium",
    "drainage": "well_drained",
}
STATUS_NAMES = ("GREEN", "ORANGE", "RED", "UNKNOWN")
EXPECTED_NAVIGATION_COUNTS = {
    "ALL": 420_532,
    "TREE": 42_528,
    "HERB": 155_841,
    "PALM": 2_846,
    "TREE_FOOD_HUMAN": 1_907,
}


def _status_counts(names: np.ndarray) -> dict[str, int]:
    return {name: int(np.count_nonzero(names == name)) for name in STATUS_NAMES}


def _ids(matrix, ordinals: np.ndarray) -> list[str]:
    return [str(matrix.taxon_ids[index]) for index in ordinals]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    db = Path(args.db).resolve()
    output = Path(args.output).resolve()

    install_exhaustive_metadata_patch()
    warm_funnel_metadata(db)

    baseline_started = perf_counter()
    baseline = exhaustive_search(
        str(db),
        climate_variables=CLIMATE,
        soil_variables=SOIL,
        life_form="ALL",
        functions=[],
        statuses=[],
        soil_statuses=[],
        offset=0,
        limit=1,
        min_known_weight=0.50,
    )
    baseline_seconds = perf_counter() - baseline_started
    key = _cache_key(
        db,
        life_form="ALL",
        functions=(),
        climate=CLIMATE,
        soil=SOIL,
        statuses=_status_filter([]),
        soil_statuses=_status_filter([]),
        min_known_weight=0.50,
    )
    snapshot = _CACHE.get(key)
    if snapshot is None:
        raise RuntimeError("Unable to recover exhaustive baseline snapshot")
    baseline_order = snapshot.ranked_ids

    matrix_started = perf_counter()
    matrix = load_climate_runtime_matrix(db)
    matrix_seconds = perf_counter() - matrix_started
    navigation = load_navigation_runtime_matrix(db)
    climate = score_climate_vector(matrix, CLIMATE, min_known_weight=0.50)
    soil = score_soil_vector(db, matrix, SOIL, min_known_weight=0.50)
    combined = combine_score_vectors(matrix, climate, soil)
    vector_order = tuple(str(matrix.taxon_ids[index]) for index in combined.order)

    ranking_differences = sum(
        1 for left, right in zip(baseline_order, vector_order, strict=True) if left != right
    )
    first_difference = next(
        (
            {"position": index, "baseline": left, "vector": right}
            for index, (left, right) in enumerate(
                zip(baseline_order, vector_order, strict=True)
            )
            if left != right
        ),
        None,
    )

    climate_counts = _status_counts(climate.status_names)
    soil_counts = _status_counts(soil.status_names)
    combined_counts = _status_counts(combined.status_names)
    baseline_climate_counts = {
        name: int(baseline["facets"]["climate_status"].get(name, 0)) for name in STATUS_NAMES
    }
    baseline_soil_counts = {
        name: int(baseline["facets"]["soil_status"].get(name, 0)) for name in STATUS_NAMES
    }

    navigation_cases = {
        "ALL": ranking_view(navigation, matrix, climate, soil, combined, life_form="ALL", limit=100),
        "TREE": ranking_view(navigation, matrix, climate, soil, combined, life_form="TREE", limit=100),
        "HERB": ranking_view(navigation, matrix, climate, soil, combined, life_form="HERB", limit=100),
        "PALM": ranking_view(navigation, matrix, climate, soil, combined, life_form="PALM", limit=100),
        "TREE_FOOD_HUMAN": ranking_view(
            navigation,
            matrix,
            climate,
            soil,
            combined,
            life_form="TREE",
            functions=["FOOD_HUMAN"],
            limit=100,
        ),
    }
    navigation_counts = {
        "ALL": navigation_cases["ALL"].metrics["after_function"],
        "TREE": navigation_cases["TREE"].metrics["after_function"],
        "HERB": navigation_cases["HERB"].metrics["after_function"],
        "PALM": navigation_cases["PALM"].metrics["after_function"],
        "TREE_FOOD_HUMAN": navigation_cases["TREE_FOOD_HUMAN"].metrics["after_function"],
    }

    # Independent legacy reference for the principal function-filtered case.
    tree_food_reference = exhaustive_search(
        str(db),
        climate_variables=CLIMATE,
        soil_variables=SOIL,
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        limit=100,
    )
    tree_food_ids = [item["taxon_id"] for item in tree_food_reference["candidates"]]
    vector_tree_food_ids = _ids(matrix, navigation_cases["TREE_FOOD_HUMAN"].page_ordinals)
    tree_food_functions = canonical_function_counts(db, "TREE")

    # Multiple function selections must retain the existing logical-AND meaning.
    tree_food_med_reference = exhaustive_search(
        str(db),
        climate_variables=CLIMATE,
        soil_variables=SOIL,
        life_form="TREE",
        functions=["FOOD_HUMAN", "MEDICINAL"],
        limit=100,
    )
    tree_food_med_view = ranking_view(
        navigation,
        matrix,
        climate,
        soil,
        combined,
        life_form="TREE",
        functions=["FOOD_HUMAN", "MEDICINAL"],
        limit=100,
    )

    # Status changes must be pure presentation operations over the same ranking.
    tree_food_green_reference = exhaustive_search(
        str(db),
        climate_variables=CLIMATE,
        soil_variables=SOIL,
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        statuses=["GREEN"],
        limit=100,
    )
    tree_food_green_view = ranking_view(
        navigation,
        matrix,
        climate,
        soil,
        combined,
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        statuses=["GREEN"],
        limit=100,
    )

    navigation_parity = {
        "expected_counts": EXPECTED_NAVIGATION_COUNTS,
        "observed_counts": navigation_counts,
        "counts_equal": navigation_counts == EXPECTED_NAVIGATION_COUNTS,
        "tree_food_first_page_equal": vector_tree_food_ids == tree_food_ids,
        "tree_food_metrics_equal": (
            navigation_cases["TREE_FOOD_HUMAN"].metrics == tree_food_reference["metrics"]
        ),
        "tree_food_climate_facets_equal": (
            navigation_cases["TREE_FOOD_HUMAN"].facets["climate_status"]
            == tree_food_reference["facets"]["climate_status"]
        ),
        "tree_food_soil_facets_equal": (
            navigation_cases["TREE_FOOD_HUMAN"].facets["soil_status"]
            == tree_food_reference["facets"]["soil_status"]
        ),
        "tree_function_facets_equal": (
            navigation_cases["TREE_FOOD_HUMAN"].facets["functions"] == tree_food_functions
        ),
        "tree_food_med_first_page_equal": (
            _ids(matrix, tree_food_med_view.page_ordinals)
            == [item["taxon_id"] for item in tree_food_med_reference["candidates"]]
        ),
        "tree_food_med_metrics_equal": tree_food_med_view.metrics == tree_food_med_reference["metrics"],
        "status_filter_first_page_equal": (
            _ids(matrix, tree_food_green_view.page_ordinals)
            == [item["taxon_id"] for item in tree_food_green_reference["candidates"]]
        ),
        "status_filter_metrics_equal": tree_food_green_view.metrics == tree_food_green_reference["metrics"],
        "legacy_status_filter_cache_hit": bool(tree_food_green_reference["cache_hit"]),
        "view_seconds": {
            name: round(view.elapsed_seconds, 6) for name, view in navigation_cases.items()
        },
        "tree_food_med_view_seconds": round(tree_food_med_view.elapsed_seconds, 6),
        "tree_food_green_view_seconds": round(tree_food_green_view.elapsed_seconds, 6),
    }
    max_navigation_seconds = max(
        [view.elapsed_seconds for view in navigation_cases.values()]
        + [tree_food_med_view.elapsed_seconds, tree_food_green_view.elapsed_seconds]
    )

    report = {
        "gate": "search-v0.10-soil-combined-navigation-parity",
        "catalog": str(db),
        "catalog_taxa": matrix.size,
        "baseline": {
            "seconds": round(baseline_seconds, 6),
            "climate_status_counts": baseline_climate_counts,
            "soil_status_counts": baseline_soil_counts,
        },
        "runtime": {
            "matrix_load_seconds": round(matrix_seconds, 6),
            "navigation_load_seconds": round(navigation.load_seconds, 6),
            "climate_score_seconds": round(climate.elapsed_seconds, 6),
            "soil_score_seconds": round(soil.elapsed_seconds, 6),
            "combine_sort_seconds": round(combined.elapsed_seconds, 6),
            "score_and_combine_seconds": round(
                climate.elapsed_seconds + soil.elapsed_seconds + combined.elapsed_seconds,
                6,
            ),
            "max_navigation_view_seconds": round(max_navigation_seconds, 6),
        },
        "parity": {
            "same_length": len(baseline_order) == len(vector_order),
            "ranking_differences": ranking_differences,
            "first_rank_difference": first_difference,
            "climate_status_counts": climate_counts,
            "soil_status_counts": soil_counts,
            "combined_status_counts": combined_counts,
            "climate_status_counts_equal": climate_counts == baseline_climate_counts,
            "soil_status_counts_equal": soil_counts == baseline_soil_counts,
            "navigation": navigation_parity,
        },
    }

    runtime_seconds = float(report["runtime"]["score_and_combine_seconds"])
    navigation_ok = all(
        bool(navigation_parity[key])
        for key in (
            "counts_equal",
            "tree_food_first_page_equal",
            "tree_food_metrics_equal",
            "tree_food_climate_facets_equal",
            "tree_food_soil_facets_equal",
            "tree_function_facets_equal",
            "tree_food_med_first_page_equal",
            "tree_food_med_metrics_equal",
            "status_filter_first_page_equal",
            "status_filter_metrics_equal",
            "legacy_status_filter_cache_hit",
        )
    )
    go = (
        matrix.size == 420_532
        and len(baseline_order) == matrix.size
        and ranking_differences == 0
        and climate_counts == baseline_climate_counts
        and soil_counts == baseline_soil_counts
        and runtime_seconds <= 5.0
        and max_navigation_seconds <= 0.50
        and navigation_ok
    )
    report["decision"] = {
        "status": "GO_CLEAR" if go else "NO_GO_PARITY_OR_PERFORMANCE",
        "max_score_and_combine_seconds": 5.0,
        "max_navigation_view_seconds": 0.50,
        "ranking_parity": ranking_differences == 0,
        "climate_status_parity": climate_counts == baseline_climate_counts,
        "soil_status_parity": soil_counts == baseline_soil_counts,
        "navigation_parity": navigation_ok,
        "scientific_prelimit": False,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if go else 2


if __name__ == "__main__":
    raise SystemExit(main())
