from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from app.domain.models import ClimateProfile, Confidence, Horizon, Scenario, SoilProfile
from app.services.search_runtime_sidecar import warm_search_runtime_sidecar
from app.services.search_vector import load_climate_runtime_matrix
from app.services.search_vector_cache import clear_vector_cache, vector_cache_stats
from app.services.search_vector_navigation import load_navigation_runtime_matrix
from app.services.search_vector_runtime import vector_runtime_search

CLIMATE_VALUES = {
    "bio01": 13.95,
    "bio05": 27.45,
    "bio06": 3.75,
    "bio12": 823.5,
    "bio15": 26.0,
}
SOIL_VALUES = {
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


def _climate() -> ClimateProfile:
    return ClimateProfile(
        latitude=47.16,
        longitude=-1.27,
        horizon=Horizon.Y2050,
        scenario=Scenario.MEDIUM,
        provider="CHELSA",
        model="ensemble-median-3-members",
        period="2041-2070",
        variables=CLIMATE_VALUES,
        provenance={
            "dataset": "CHELSA-bioclim",
            "version": "2.1",
            "manifest_revision": "climaflora-prod-0.6.0",
            "scenario_mapping": "ssp370",
        },
    )


def _soil() -> SoilProfile:
    return SoilProfile(
        latitude=47.16,
        longitude=-1.27,
        provider="SoilGrids 2.0 / ISRIC",
        depth="5-15cm",
        resolution_m=250,
        properties=SOIL_VALUES,
        confidence=Confidence.C,
        provenance={
            "access": "WCS 2.0.1",
            "prediction": "Q0.5",
            "wcs_base": "https://maps.isric.org/mapserv",
        },
    )


def _run(db: Path, climate: ClimateProfile, soil: SoilProfile, **kwargs) -> dict:
    started = perf_counter()
    result = vector_runtime_search(
        db,
        climate=climate,
        soil=soil,
        min_known_weight=0.50,
        limit=50,
        **kwargs,
    )
    elapsed = perf_counter() - started
    return {
        "seconds": round(elapsed, 6),
        "cache_hit": bool(result["cache_hit"]),
        "cache_hits": result["vector_runtime"]["cache_hits"],
        "metrics": result["metrics"],
        "pagination": result["pagination"],
        "runtime": result["vector_runtime"],
        "first_taxa": [item["taxon_id"] for item in result["candidates"][:5]],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    db = Path(args.db).resolve()
    output = Path(args.output).resolve()
    climate = _climate()
    soil = _soil()

    warm_started = perf_counter()
    sidecar = warm_search_runtime_sidecar(db)
    matrix = load_climate_runtime_matrix(db)
    navigation = load_navigation_runtime_matrix(db)
    warm_seconds = perf_counter() - warm_started

    clear_vector_cache()
    cold_all = _run(db, climate, soil, life_form="ALL")
    warm_tree = _run(db, climate, soil, life_form="TREE")
    warm_tree_food = _run(db, climate, soil, life_form="TREE", functions=["FOOD_HUMAN"])
    warm_tree_food_green = _run(
        db,
        climate,
        soil,
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        statuses=["GREEN"],
    )
    warm_tree_food_page2 = _run(
        db,
        climate,
        soil,
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        offset=50,
    )

    cases = {
        "cold_all": cold_all,
        "warm_tree": warm_tree,
        "warm_tree_food": warm_tree_food,
        "warm_tree_food_green": warm_tree_food_green,
        "warm_tree_food_page2": warm_tree_food_page2,
    }
    warm_names = [name for name in cases if name.startswith("warm_")]
    all_warm_hits = all(
        all(bool(value) for value in cases[name]["cache_hits"].values())
        for name in warm_names
    )
    max_warm_seconds = max(float(cases[name]["seconds"]) for name in warm_names)

    report = {
        "benchmark": "search-v0.10-vector-runtime",
        "catalog": str(db),
        "catalog_taxa": matrix.size,
        "sidecar": str(sidecar),
        "prewarm": {
            "seconds": round(warm_seconds, 6),
            "matrix_load_seconds": round(matrix.load_seconds, 6),
            "navigation_load_seconds": round(navigation.load_seconds, 6),
        },
        "cases": cases,
        "cache_after": vector_cache_stats(),
        "targets": {
            "cold_scientific_request_max_seconds": 5.0,
            "warm_navigation_request_max_seconds": 1.0,
        },
    }
    go = (
        matrix.size == 420_532
        and cold_all["seconds"] <= 5.0
        and not cold_all["cache_hit"]
        and all_warm_hits
        and max_warm_seconds <= 1.0
        and warm_tree["metrics"]["after_function"] == 42_528
        and warm_tree_food["metrics"]["after_function"] == 1_907
        and warm_tree_food_page2["pagination"]["offset"] == 50
    )
    report["decision"] = {
        "status": "GO_CLEAR" if go else "NO_GO_RUNTIME_PERFORMANCE",
        "all_warm_scientific_cache_hits": all_warm_hits,
        "max_warm_seconds": round(max_warm_seconds, 6),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if go else 2


if __name__ == "__main__":
    raise SystemExit(main())
