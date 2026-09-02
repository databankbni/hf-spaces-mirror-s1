from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import sqlite3
from time import perf_counter
from typing import Mapping

import numpy as np

from app.services.search_runtime_sidecar import (
    CLIMATE_GROUPS,
    CLIMATE_VARIABLES,
    warm_search_runtime_sidecar,
)

GROUP_WEIGHTS = {"M": 0.30, "V": 0.20, "E": 0.35, "A": 0.15}
# This order reproduces the compensated SQLite SUM traversal validated by the
# Phase -1 full-catalog parity gate. Do not reorder without rerunning that gate.
GROUP_ORDER = ("A", "E", "M", "V")
STATUS_NAMES = np.asarray(["GREEN", "ORANGE", "RED", "UNKNOWN"], dtype=object)


@dataclass(frozen=True)
class ClimateRuntimeMatrix:
    sidecar_path: str
    taxon_ids: np.ndarray
    data: dict[str, np.ndarray]
    load_seconds: float

    @property
    def size(self) -> int:
        return int(self.taxon_ids.shape[0])


@dataclass(frozen=True)
class ClimateScoreVector:
    overall: np.ndarray
    known_fraction: np.ndarray
    centrality: np.ndarray
    fatal_red: np.ndarray
    status_codes: np.ndarray
    order: np.ndarray
    elapsed_seconds: float

    @property
    def status_names(self) -> np.ndarray:
        return STATUS_NAMES[self.status_codes]


def _kbn_sum(arrays: list[np.ndarray], n: int) -> np.ndarray:
    """Vectorized Kahan-Babuska-Neumaier sum matching SQLite SUM(REAL) parity."""
    total = np.zeros(n, dtype=np.float64)
    error = np.zeros(n, dtype=np.float64)
    for value in arrays:
        t = total + value
        correction = np.where(
            np.abs(total) > np.abs(value),
            (total - t) + value,
            (value - t) + total,
        )
        error += correction
        total = t
    return total + error


def _score_component(
    value: float | None,
    hard_low: np.ndarray,
    optimum_low: np.ndarray,
    optimum_high: np.ndarray,
    hard_high: np.ndarray,
    weight: np.ndarray,
) -> np.ndarray:
    present = np.isfinite(weight)
    score = np.full(weight.shape, np.nan, dtype=np.float64)
    if value is None or not np.isfinite(float(value)):
        return score
    value = float(value)
    score[present] = 100.0

    below_hard = present & np.isfinite(hard_low) & (value < hard_low)
    above_hard = present & np.isfinite(hard_high) & (value > hard_high)
    score[below_hard | above_hard] = 0.0

    lower = present & ~below_hard & ~above_hard & np.isfinite(optimum_low) & (value < optimum_low)
    lower_fallback = lower & (~np.isfinite(hard_low) | (optimum_low == hard_low))
    score[lower_fallback] = 50.0
    lower_linear = lower & ~lower_fallback
    score[lower_linear] = 100.0 * (
        (value - hard_low[lower_linear])
        / (optimum_low[lower_linear] - hard_low[lower_linear])
    )

    upper = (
        present
        & ~below_hard
        & ~above_hard
        & ~lower
        & np.isfinite(optimum_high)
        & (value > optimum_high)
    )
    upper_fallback = upper & (~np.isfinite(hard_high) | (hard_high == optimum_high))
    score[upper_fallback] = 50.0
    upper_linear = upper & ~upper_fallback
    score[upper_linear] = 100.0 * (
        (hard_high[upper_linear] - value)
        / (hard_high[upper_linear] - optimum_high[upper_linear])
    )
    return score


def _centrality(
    value: float | None,
    optimum_low: np.ndarray,
    optimum_high: np.ndarray,
    weight: np.ndarray,
) -> np.ndarray:
    present = np.isfinite(weight)
    centrality = np.full(weight.shape, np.nan, dtype=np.float64)
    if value is None or not np.isfinite(float(value)):
        return centrality
    value = float(value)

    invalid = present & (
        ~np.isfinite(optimum_low)
        | ~np.isfinite(optimum_high)
        | (optimum_high <= optimum_low)
    )
    centrality[invalid] = 50.0
    valid = present & ~invalid
    inside = valid & (value >= optimum_low) & (value <= optimum_high)
    centrality[valid & ~inside] = 0.0
    if np.any(inside):
        midpoint = (optimum_low[inside] + optimum_high[inside]) / 2.0
        half = np.maximum(
            (optimum_high[inside] - optimum_low[inside]) / 2.0,
            0.000001,
        )
        centrality[inside] = np.maximum(
            0.0,
            100.0 - 100.0 * np.abs(value - midpoint) / half,
        )
    return centrality


def _status_codes(
    overall: np.ndarray,
    known_fraction: np.ndarray,
    fatal_red: np.ndarray,
    *,
    min_known_weight: float,
) -> np.ndarray:
    status = np.full(overall.shape, 3, dtype=np.uint8)  # UNKNOWN
    known = np.isfinite(overall) & (known_fraction >= float(min_known_weight)) & ~fatal_red
    status[known & (overall >= 75.0)] = 0
    status[known & (overall >= 40.0) & (overall < 75.0)] = 1
    status[known & (overall < 40.0)] = 2
    status[fatal_red] = 2
    return status


def _load_matrix_uncached(sidecar: Path) -> ClimateRuntimeMatrix:
    started = perf_counter()
    with sqlite3.connect(f"file:{sidecar.resolve()}?mode=ro", uri=True) as conn:
        cursor = conn.execute("SELECT * FROM climate_runtime_wide ORDER BY ordinal")
        names = [item[0] for item in cursor.description]
        rows = cursor.fetchall()

    if not names or names[:2] != ["ordinal", "taxon_id"]:
        raise RuntimeError("Invalid ClimaFlora climate runtime projection layout")

    ordinals = np.asarray([int(row[0]) for row in rows], dtype=np.int64)
    expected = np.arange(len(rows), dtype=np.int64)
    if not np.array_equal(ordinals, expected):
        raise RuntimeError("Climate runtime projection ordinals are not contiguous")

    taxon_ids = np.asarray([str(row[1]) for row in rows], dtype=object)
    data: dict[str, np.ndarray] = {}
    for column_index, name in enumerate(names[2:], start=2):
        if name.endswith("_fatal"):
            data[name] = np.asarray(
                [0 if row[column_index] is None else int(row[column_index]) for row in rows],
                dtype=np.uint8,
            )
        else:
            data[name] = np.asarray(
                [np.nan if row[column_index] is None else float(row[column_index]) for row in rows],
                dtype=np.float64,
            )

    return ClimateRuntimeMatrix(
        sidecar_path=str(sidecar),
        taxon_ids=taxon_ids,
        data=data,
        load_seconds=perf_counter() - started,
    )


@lru_cache(maxsize=4)
def _load_matrix_cached(sidecar_path: str, size: int, mtime_ns: int) -> ClimateRuntimeMatrix:
    del size, mtime_ns
    return _load_matrix_uncached(Path(sidecar_path))


def load_climate_runtime_matrix(catalog_path: str | Path) -> ClimateRuntimeMatrix:
    sidecar = warm_search_runtime_sidecar(catalog_path)
    stat = sidecar.stat()
    return _load_matrix_cached(str(sidecar.resolve()), stat.st_size, stat.st_mtime_ns)


def score_climate_vector(
    matrix: ClimateRuntimeMatrix,
    climate_variables: Mapping[str, float | None],
    *,
    min_known_weight: float = 0.50,
) -> ClimateScoreVector:
    """Score the complete catalog climate projection without scientific prelimit."""
    started = perf_counter()
    n = matrix.size
    component_scores: dict[str, np.ndarray] = {}
    component_centrality: dict[str, np.ndarray] = {}

    for variable in CLIMATE_VARIABLES:
        component_scores[variable] = _score_component(
            climate_variables.get(variable),
            matrix.data[f"{variable}_hard_low"],
            matrix.data[f"{variable}_optimum_low"],
            matrix.data[f"{variable}_optimum_high"],
            matrix.data[f"{variable}_hard_high"],
            matrix.data[f"{variable}_weight"],
        )
        component_centrality[variable] = _centrality(
            climate_variables.get(variable),
            matrix.data[f"{variable}_optimum_low"],
            matrix.data[f"{variable}_optimum_high"],
            matrix.data[f"{variable}_weight"],
        )

    documented_terms: list[np.ndarray] = []
    known_terms: list[np.ndarray] = []
    centrality_num_terms: list[np.ndarray] = []
    centrality_den_terms: list[np.ndarray] = []
    fatal_red = np.zeros(n, dtype=bool)

    for variable in CLIMATE_VARIABLES:
        weights = matrix.data[f"{variable}_weight"]
        weight0 = np.nan_to_num(weights, nan=0.0)
        positive = np.isfinite(weights) & (weights > 0)
        scored = np.isfinite(component_scores[variable])
        c_known = np.isfinite(component_centrality[variable])

        documented_terms.append(np.where(positive, weight0, 0.0))
        known_terms.append(np.where(positive & scored, weight0, 0.0))
        centrality_num_terms.append(
            np.where(
                c_known,
                np.nan_to_num(component_centrality[variable], nan=0.0) * weight0,
                0.0,
            )
        )
        centrality_den_terms.append(np.where(c_known, weight0, 0.0))
        fatal_red |= (
            matrix.data[f"{variable}_fatal"].astype(bool)
            & scored
            & (component_scores[variable] < 40.0)
        )

    documented_weight = _kbn_sum(documented_terms, n)
    known_weight = _kbn_sum(known_terms, n)
    centrality_num = _kbn_sum(centrality_num_terms, n)
    centrality_den = _kbn_sum(centrality_den_terms, n)

    known_fraction = np.divide(
        known_weight,
        documented_weight,
        out=np.zeros(n, dtype=np.float64),
        where=documented_weight > 0,
    )
    centrality = np.divide(
        centrality_num,
        centrality_den,
        out=np.zeros(n, dtype=np.float64),
        where=centrality_den > 0,
    )

    group_scores: dict[str, np.ndarray] = {}
    for group in GROUP_ORDER:
        num_terms: list[np.ndarray] = []
        den_terms: list[np.ndarray] = []
        for variable in CLIMATE_VARIABLES:
            if CLIMATE_GROUPS[variable] != group:
                continue
            weights = matrix.data[f"{variable}_weight"]
            weight0 = np.nan_to_num(weights, nan=0.0)
            scores = component_scores[variable]
            known = np.isfinite(scores) & np.isfinite(weights)
            num_terms.append(
                np.where(known, np.nan_to_num(scores, nan=0.0) * weight0, 0.0)
            )
            den_terms.append(np.where(known, weight0, 0.0))
        if not num_terms:
            group_scores[group] = np.full(n, np.nan, dtype=np.float64)
            continue
        group_num = _kbn_sum(num_terms, n)
        group_den = _kbn_sum(den_terms, n)
        group_scores[group] = np.divide(
            group_num,
            group_den,
            out=np.full(n, np.nan, dtype=np.float64),
            where=group_den > 0,
        )

    overall_num_terms: list[np.ndarray] = []
    overall_den_terms: list[np.ndarray] = []
    for group in GROUP_ORDER:
        group_score = group_scores[group]
        group_weight = float(GROUP_WEIGHTS[group])
        known = np.isfinite(group_score)
        overall_num_terms.append(
            np.where(known, np.nan_to_num(group_score, nan=0.0) * group_weight, 0.0)
        )
        overall_den_terms.append(np.where(known, group_weight, 0.0))

    overall_num = _kbn_sum(overall_num_terms, n)
    overall_den = _kbn_sum(overall_den_terms, n)
    overall = np.divide(
        overall_num,
        overall_den,
        out=np.full(n, np.nan, dtype=np.float64),
        where=overall_den > 0,
    )
    status = _status_codes(
        overall,
        known_fraction,
        fatal_red,
        min_known_weight=min_known_weight,
    )

    # Climate-only ranking is deliberately identical to the current exhaustive
    # SQL ranking when soil is UNKNOWN for every taxon. Soil blending is added in
    # a later phase, after this vector has passed full-catalog parity on its own.
    climate_gate = np.where(
        (status == 0) | (status == 1),
        0,
        np.where(status == 3, 1, 2),
    )
    combined_rank = np.where(
        status == 0,
        0,
        np.where(status == 1, 1, np.where(status == 3, 2, 3)),
    )
    score_key = np.where(np.isfinite(overall), -overall, np.inf)
    centrality_key = np.where(np.isfinite(centrality), -centrality, np.inf)
    order = np.lexsort(
        (
            matrix.taxon_ids,
            centrality_key,
            score_key,
            score_key,
            combined_rank,
            climate_gate,
        )
    )

    return ClimateScoreVector(
        overall=overall,
        known_fraction=known_fraction,
        centrality=centrality,
        fatal_red=fatal_red,
        status_codes=status,
        order=order,
        elapsed_seconds=perf_counter() - started,
    )
