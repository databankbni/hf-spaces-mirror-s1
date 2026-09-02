from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np

from app.services.exhaustive_search import _CACHE, _cache_key, _status_filter, exhaustive_search
from app.services.funnel_metadata import install_exhaustive_metadata_patch, warm_funnel_metadata
from app.services.search_runtime_sidecar import search_runtime_sidecar_summary, warm_search_runtime_sidecar
from app.services.search_vector import load_climate_runtime_matrix, score_climate_vector

REFERENCE_PROFILE = {
    "bio01": 13.95,
    "bio05": 27.45,
    "bio06": 3.75,
    "bio12": 823.5,
    "bio15": 26.0,
}


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 6)


def _current_sql_baseline(db: Path) -> dict:
    install_exhaustive_metadata_patch()
    warm_funnel_metadata(db)
    started = time.perf_counter()
    result = exhaustive_search(
        str(db),
        climate_variables=REFERENCE_PROFILE,
        soil_variables={},
        life_form="ALL",
        functions=[],
        statuses=[],
        soil_statuses=[],
        offset=0,
        limit=1,
        min_known_weight=0.50,
    )
    seconds = _elapsed(started)
    key = _cache_key(
        db,
        life_form="ALL",
        functions=(),
        climate=REFERENCE_PROFILE,
        soil={},
        statuses=_status_filter([]),
        soil_statuses=_status_filter([]),
        min_known_weight=0.50,
    )
    snapshot = _CACHE.get(key)
    if snapshot is None:
        raise RuntimeError("Current exhaustive SQL snapshot unavailable after baseline run")
    return {
        "seconds": seconds,
        "result": result,
        "snapshot": snapshot,
    }


def verify(db: Path) -> dict:
    report: dict = {
        "gate": "search-v0.10-production-vector-parity",
        "catalog": str(db),
        "profile": REFERENCE_PROFILE,
    }

    started = time.perf_counter()
    runtime_sidecar = warm_search_runtime_sidecar(db)
    report["runtime_sidecar_build_seconds"] = _elapsed(started)
    report["runtime_sidecar"] = search_runtime_sidecar_summary(db)

    started = time.perf_counter()
    matrix = load_climate_runtime_matrix(db)
    report["matrix_access_seconds"] = _elapsed(started)
    report["matrix_initial_load_seconds"] = round(float(matrix.load_seconds), 6)
    report["matrix_taxa"] = matrix.size

    vector = score_climate_vector(matrix, REFERENCE_PROFILE, min_known_weight=0.50)
    report["vector_score_seconds"] = round(float(vector.elapsed_seconds), 6)

    current = _current_sql_baseline(db)
    snapshot = current["snapshot"]
    report["current_sql_seconds"] = current["seconds"]

    current_ids = snapshot.ranked_ids
    vector_ids = tuple(str(matrix.taxon_ids[index]) for index in vector.order)
    if len(current_ids) != len(vector_ids):
        ranking_differences = None
        first_rank_difference = {
            "current_length": len(current_ids),
            "vector_length": len(vector_ids),
        }
    else:
        positions = [
            index
            for index, (left, right) in enumerate(zip(current_ids, vector_ids, strict=True))
            if left != right
        ]
        ranking_differences = len(positions)
        first_rank_difference = None
        if positions:
            index = positions[0]
            first_rank_difference = {
                "position": index,
                "current": current_ids[index],
                "vector": vector_ids[index],
            }

    vector_status_by_taxon = {
        str(taxon_id): str(status)
        for taxon_id, status in zip(matrix.taxon_ids, vector.status_names, strict=True)
    }
    status_differences = []
    unknown_differences = 0
    for taxon_id, climate_status, _soil_status in snapshot.ranked_rows:
        candidate = vector_status_by_taxon.get(str(taxon_id))
        if candidate != climate_status:
            if len(status_differences) < 20:
                status_differences.append(
                    {
                        "taxon_id": str(taxon_id),
                        "current": climate_status,
                        "vector": candidate,
                    }
                )
            if (climate_status == "UNKNOWN") != (candidate == "UNKNOWN"):
                unknown_differences += 1

    current_facets = {
        key: int(value)
        for key, value in current["result"]["facets"]["climate_status"].items()
    }
    vector_facets = {
        status: int(np.count_nonzero(vector.status_names == status))
        for status in ("GREEN", "ORANGE", "RED", "UNKNOWN")
    }

    report["parity"] = {
        "ranking_differences": ranking_differences,
        "first_rank_difference": first_rank_difference,
        "status_differences": sum(
            1
            for taxon_id, climate_status, _soil_status in snapshot.ranked_rows
            if vector_status_by_taxon.get(str(taxon_id)) != climate_status
        ),
        "status_difference_examples": status_differences,
        "unknown_differences": unknown_differences,
        "current_status_counts": current_facets,
        "vector_status_counts": vector_facets,
        "status_counts_equal": current_facets == vector_facets,
    }

    go = (
        matrix.size == len(current_ids)
        and ranking_differences == 0
        and report["parity"]["status_differences"] == 0
        and unknown_differences == 0
        and current_facets == vector_facets
        and vector.elapsed_seconds <= 1.5
    )
    report["decision"] = {
        "status": "GO_CLEAR" if go else "NO_GO",
        "full_ranking_exact": ranking_differences == 0,
        "status_exact": report["parity"]["status_differences"] == 0,
        "unknown_exact": unknown_differences == 0,
        "vector_under_1_5_seconds": vector.elapsed_seconds <= 1.5,
        "scientific_prelimit": False,
        "sort_key_rounding": False,
        "sum_semantics": "SQLite-compatible Kahan-Babuska-Neumaier",
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = verify(Path(args.db).resolve())
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["decision"], ensure_ascii=False, indent=2))
    print(json.dumps(report["parity"], ensure_ascii=False, indent=2))
    print(f"REPORT={output}")
    return 0 if report["decision"]["status"] == "GO_CLEAR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
