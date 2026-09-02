from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import sqlite3
from time import perf_counter

import numpy as np

from app.services.search_runtime_sidecar import LIFE_MASKS, warm_search_runtime_sidecar
from app.services.search_soil_vector import CombinedScoreVector, SoilScoreVector
from app.services.search_vector import ClimateRuntimeMatrix, ClimateScoreVector, STATUS_NAMES

STATUS_VALUES = ("GREEN", "ORANGE", "RED", "UNKNOWN")
LIFE_FORM_VALUES = ("TREE", "SHRUB", "HERB", "CLIMBER", "PALM", "OTHER", "UNKNOWN")


@dataclass(frozen=True)
class NavigationRuntimeMatrix:
    sidecar_path: str
    taxon_ids: np.ndarray
    life_categories: np.ndarray
    life_masks: np.ndarray
    function_masks: np.ndarray
    function_bits: dict[str, int]
    load_seconds: float

    @property
    def size(self) -> int:
        return int(self.taxon_ids.shape[0])


@dataclass(frozen=True)
class RankingView:
    ordered_ordinals: np.ndarray
    page_ordinals: np.ndarray
    metrics: dict[str, int]
    facets: dict[str, dict[str, int]]
    elapsed_seconds: float


def _load_navigation_uncached(sidecar: Path) -> NavigationRuntimeMatrix:
    started = perf_counter()
    with sqlite3.connect(f"file:{sidecar.resolve()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            "SELECT ordinal,taxon_id,life_category,life_mask,function_mask "
            "FROM taxon_runtime ORDER BY ordinal"
        ).fetchall()
        function_bits = {
            str(code): int(bit_index)
            for code, bit_index in conn.execute(
                "SELECT code,bit_index FROM function_code ORDER BY bit_index"
            )
        }
    ordinals = np.asarray([int(row[0]) for row in rows], dtype=np.int64)
    if not np.array_equal(ordinals, np.arange(len(rows), dtype=np.int64)):
        raise RuntimeError("Navigation runtime ordinals are not contiguous")
    return NavigationRuntimeMatrix(
        sidecar_path=str(sidecar),
        taxon_ids=np.asarray([str(row[1]) for row in rows], dtype=object),
        life_categories=np.asarray([str(row[2]) for row in rows], dtype=object),
        life_masks=np.asarray([int(row[3]) for row in rows], dtype=np.uint16),
        function_masks=np.asarray([int(row[4]) for row in rows], dtype=np.uint64),
        function_bits=function_bits,
        load_seconds=perf_counter() - started,
    )


@lru_cache(maxsize=4)
def _load_navigation_cached(
    sidecar_path: str,
    size: int,
    mtime_ns: int,
) -> NavigationRuntimeMatrix:
    del size, mtime_ns
    return _load_navigation_uncached(Path(sidecar_path))


def load_navigation_runtime_matrix(catalog_path: str | Path) -> NavigationRuntimeMatrix:
    sidecar = warm_search_runtime_sidecar(catalog_path)
    stat = sidecar.stat()
    return _load_navigation_cached(str(sidecar.resolve()), stat.st_size, stat.st_mtime_ns)


def _status_filter(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    selected = tuple(
        dict.fromkeys(
            str(value).upper()
            for value in (values or [])
            if str(value).upper() in STATUS_VALUES
        )
    )
    return selected or STATUS_VALUES


def _required_function_mask(
    functions: list[str] | tuple[str, ...] | None,
    function_bits: dict[str, int],
) -> tuple[int, bool]:
    required = 0
    for code in dict.fromkeys(str(value) for value in (functions or [])):
        bit_index = function_bits.get(code)
        if bit_index is None:
            return 0, False
        required |= 1 << bit_index
    return required, True


def ranking_view(
    navigation: NavigationRuntimeMatrix,
    climate_matrix: ClimateRuntimeMatrix,
    climate: ClimateScoreVector,
    soil: SoilScoreVector,
    combined: CombinedScoreVector,
    *,
    life_form: str = "ALL",
    functions: list[str] | tuple[str, ...] | None = None,
    statuses: list[str] | tuple[str, ...] | None = None,
    soil_statuses: list[str] | tuple[str, ...] | None = None,
    offset: int = 0,
    limit: int = 50,
) -> RankingView:
    """Apply navigation/presentation masks to one already-scored global ranking."""
    started = perf_counter()
    n = navigation.size
    if climate_matrix.size != n or climate.overall.shape[0] != n or soil.score.shape[0] != n:
        raise ValueError("Search runtime vector length mismatch")
    if combined.score.shape[0] != n:
        raise ValueError("Combined ranking length mismatch")
    if not np.array_equal(navigation.taxon_ids, climate_matrix.taxon_ids):
        raise RuntimeError("Navigation and scientific runtime ordinals are misaligned")

    normalized_life = str(life_form or "ALL").upper()
    if normalized_life not in (*LIFE_FORM_VALUES, "ALL"):
        normalized_life = "ALL"

    life_counts = {
        category: int(np.count_nonzero(navigation.life_categories == category))
        for category in LIFE_FORM_VALUES
    }
    if normalized_life == "ALL":
        type_mask = np.ones(n, dtype=bool)
    else:
        type_mask = (navigation.life_masks & np.uint16(LIFE_MASKS[normalized_life])) != 0
    after_type = int(np.count_nonzero(type_mask))

    function_counts: dict[str, int] = {}
    for code, bit_index in navigation.function_bits.items():
        bit = np.uint64(1 << bit_index)
        count = int(np.count_nonzero(type_mask & ((navigation.function_masks & bit) != 0)))
        # canonical_function_counts omits codes that have no taxon in the
        # selected life-form population; preserve that API contract exactly.
        if count:
            function_counts[code] = count

    required_mask, functions_known = _required_function_mask(functions, navigation.function_bits)
    if not functions_known:
        eligible = np.zeros(n, dtype=bool)
    elif required_mask == 0:
        eligible = type_mask.copy()
    else:
        required = np.uint64(required_mask)
        eligible = type_mask & ((navigation.function_masks & required) == required)
    after_function = int(np.count_nonzero(eligible))

    climate_names = STATUS_NAMES[climate.status_codes]
    soil_names = STATUS_NAMES[soil.status_codes]
    climate_counts = {
        name: int(np.count_nonzero(eligible & (climate_names == name)))
        for name in STATUS_VALUES
    }
    soil_counts = {
        name: int(np.count_nonzero(eligible & (soil_names == name)))
        for name in STATUS_VALUES
    }

    allowed_climate = _status_filter(statuses)
    allowed_soil = _status_filter(soil_statuses)
    presentation = eligible & np.isin(climate_names, allowed_climate) & np.isin(soil_names, allowed_soil)

    ordered = combined.order[presentation[combined.order]]
    safe_offset = max(0, int(offset))
    safe_limit = max(1, int(limit))
    page = ordered[safe_offset : safe_offset + safe_limit]

    return RankingView(
        ordered_ordinals=ordered,
        page_ordinals=page,
        metrics={
            "catalog_total": n,
            "after_type": after_type,
            "after_function": after_function,
            # Public funnel semantics remain the same even though the internal
            # scientific vectors were scored globally once.
            "evaluated_candidates": after_function,
            "total_results": int(ordered.shape[0]),
        },
        facets={
            "life_form": life_counts,
            "functions": function_counts,
            "climate_status": climate_counts,
            "soil_status": soil_counts,
        },
        elapsed_seconds=perf_counter() - started,
    )
