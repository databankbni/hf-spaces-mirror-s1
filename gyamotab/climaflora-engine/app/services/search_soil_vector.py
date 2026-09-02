from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from time import perf_counter
from typing import Mapping

import numpy as np

from app.services.search_vector import ClimateRuntimeMatrix, ClimateScoreVector

STATUS_NAMES = np.asarray(["GREEN", "ORANGE", "RED", "UNKNOWN"], dtype=object)
_STATUS_CODE = {"GREEN": 0, "ORANGE": 1, "RED": 2, "UNKNOWN": 3}


@dataclass(frozen=True)
class SoilScoreVector:
    score: np.ndarray
    known_fraction: np.ndarray
    known_components: np.ndarray
    status_codes: np.ndarray
    elapsed_seconds: float

    @property
    def status_names(self) -> np.ndarray:
        return STATUS_NAMES[self.status_codes]


@dataclass(frozen=True)
class CombinedScoreVector:
    score: np.ndarray
    status_codes: np.ndarray
    order: np.ndarray
    elapsed_seconds: float

    @property
    def status_names(self) -> np.ndarray:
        return STATUS_NAMES[self.status_codes]


def _case_value(
    alias: str,
    values: Mapping[str, float | str | None],
    params: dict[str, float | str],
    prefix: str,
    *,
    numeric: bool,
) -> str:
    parts = [f"CASE {alias}.variable"]
    index = 0
    for key in sorted(values):
        value = values.get(key)
        if value is None:
            continue
        if numeric and not isinstance(value, (int, float)):
            continue
        param = f"{prefix}{index}"
        params[param] = float(value) if numeric else str(value)
        safe_key = str(key).replace("'", "''")
        parts.append(f"WHEN '{safe_key}' THEN :{param}")
        index += 1
    if index == 0:
        return "NULL"
    parts.append("ELSE NULL END")
    return " ".join(parts)


def _score_sql(alias: str, value_expr: str) -> str:
    # Kept byte-for-byte equivalent in meaning to exhaustive_search._score_sql.
    return f"""CASE
        WHEN ({value_expr}) IS NULL THEN NULL
        WHEN {alias}.hard_low IS NOT NULL AND ({value_expr}) < {alias}.hard_low THEN 0.0
        WHEN {alias}.hard_high IS NOT NULL AND ({value_expr}) > {alias}.hard_high THEN 0.0
        WHEN {alias}.optimum_low IS NOT NULL AND ({value_expr}) < {alias}.optimum_low THEN
            CASE WHEN {alias}.hard_low IS NULL OR {alias}.optimum_low={alias}.hard_low THEN 50.0
                 ELSE 100.0*((({value_expr})-{alias}.hard_low)/({alias}.optimum_low-{alias}.hard_low)) END
        WHEN {alias}.optimum_high IS NOT NULL AND ({value_expr}) > {alias}.optimum_high THEN
            CASE WHEN {alias}.hard_high IS NULL OR {alias}.hard_high={alias}.optimum_high THEN 50.0
                 ELSE 100.0*(({alias}.hard_high-({value_expr}))/({alias}.hard_high-{alias}.optimum_high)) END
        ELSE 100.0 END"""


def score_soil_vector(
    catalog_path: str | Path,
    matrix: ClimateRuntimeMatrix,
    soil_variables: Mapping[str, float | str | None],
    *,
    min_known_weight: float = 0.50,
) -> SoilScoreVector:
    """Score soil for the complete catalog using SQLite's exact SUM semantics.

    Soil scoring coverage is sparse in catalog v2.0, so this phase deliberately
    keeps SQLite aggregation while removing life-form/function/presentation
    filters. The resulting vector can be cached independently of climate.
    """
    started = perf_counter()
    catalog = Path(catalog_path).resolve()
    sidecar = Path(matrix.sidecar_path).resolve()

    conn = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-32768")
        conn.execute("ATTACH DATABASE ? AS runtime_cache", (str(sidecar),))
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table'")
        }
        conn.execute(
            "CREATE TEMP TABLE soil_component(ordinal INTEGER NOT NULL,weight REAL,score REAL)"
        )

        if "soil_envelope" in tables:
            numeric_params: dict[str, float | str] = {}
            numeric_value = _case_value(
                "s", soil_variables, numeric_params, "soil_num_", numeric=True
            )
            numeric_score = _score_sql("s", numeric_value)
            conn.execute(
                f"""
                INSERT INTO soil_component(ordinal,weight,score)
                SELECT tr.ordinal,s.weight,{numeric_score}
                FROM main.soil_envelope s
                JOIN runtime_cache.taxon_runtime tr ON tr.taxon_id=s.taxon_id
                """,
                numeric_params,
            )

        if "soil_categorical_preference" in tables:
            categorical_params: dict[str, float | str] = {}
            categorical_value = _case_value(
                "s", soil_variables, categorical_params, "soil_cat_", numeric=False
            )
            conn.execute(
                f"""
                INSERT INTO soil_component(ordinal,weight,score)
                SELECT tr.ordinal,s.weight,
                       CASE WHEN ({categorical_value}) IS NULL THEN NULL
                            WHEN EXISTS (
                                SELECT 1 FROM json_each(COALESCE(s.optimum_values_json,'[]')) j
                                WHERE LOWER(TRIM(CAST(j.value AS TEXT)))=
                                      LOWER(TRIM(CAST(({categorical_value}) AS TEXT)))
                            ) THEN 100.0
                            WHEN EXISTS (
                                SELECT 1 FROM json_each(COALESCE(s.accepted_values_json,'[]')) j
                                WHERE LOWER(TRIM(CAST(j.value AS TEXT)))=
                                      LOWER(TRIM(CAST(({categorical_value}) AS TEXT)))
                            ) THEN 65.0
                            ELSE 0.0 END
                FROM main.soil_categorical_preference s
                JOIN runtime_cache.taxon_runtime tr ON tr.taxon_id=s.taxon_id
                """,
                categorical_params,
            )

        # The exact-component index must exist before the inheritance anti-join.
        # Without it, the full-catalog NOT EXISTS check becomes quadratic.
        conn.execute("CREATE INDEX temp.idx_soil_component_ordinal ON soil_component(ordinal)")
        conn.execute(
            """
            INSERT INTO soil_component(ordinal,weight,score)
            SELECT child.ordinal,parent_component.weight,parent_component.score
            FROM runtime_cache.taxon_runtime child
            JOIN runtime_cache.taxon_runtime parent
              ON parent.taxon_id=child.parent_species_taxon_id
            JOIN soil_component parent_component ON parent_component.ordinal=parent.ordinal
            WHERE child.parent_species_taxon_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM soil_component own WHERE own.ordinal=child.ordinal
              )
            """
        )
        rows = conn.execute(
            """
            WITH soil_score AS (
                SELECT tr.ordinal,
                       COUNT(CASE WHEN sc.score IS NOT NULL THEN 1 END) AS known_components,
                       CASE WHEN COALESCE(SUM(CASE WHEN sc.weight>0 THEN sc.weight ELSE 0 END),0)>0
                            THEN COALESCE(SUM(CASE WHEN sc.score IS NOT NULL THEN sc.weight ELSE 0 END),0) /
                                 SUM(CASE WHEN sc.weight>0 THEN sc.weight ELSE 0 END)
                            ELSE 0.0 END AS known_fraction,
                       CASE WHEN COALESCE(SUM(CASE WHEN sc.score IS NOT NULL THEN sc.weight ELSE 0 END),0)>0
                            THEN SUM(COALESCE(sc.score,0)*sc.weight) /
                                 SUM(CASE WHEN sc.score IS NOT NULL THEN sc.weight ELSE 0 END)
                            ELSE NULL END AS soil_score
                FROM runtime_cache.taxon_runtime tr
                LEFT JOIN soil_component sc ON sc.ordinal=tr.ordinal
                GROUP BY tr.ordinal
            )
            SELECT ordinal,known_components,known_fraction,soil_score,
                   CASE WHEN soil_score IS NULL OR known_fraction<:min_known OR known_components<2 THEN 'UNKNOWN'
                        WHEN soil_score>=75 THEN 'GREEN'
                        WHEN soil_score>=40 THEN 'ORANGE'
                        ELSE 'RED' END AS soil_status
            FROM soil_score
            ORDER BY ordinal
            """,
            {"min_known": float(min_known_weight)},
        ).fetchall()
    finally:
        conn.close()

    if len(rows) != matrix.size:
        raise RuntimeError(
            f"Soil vector coverage mismatch: expected {matrix.size}, got {len(rows)}"
        )
    ordinals = np.asarray([int(row[0]) for row in rows], dtype=np.int64)
    if not np.array_equal(ordinals, np.arange(matrix.size, dtype=np.int64)):
        raise RuntimeError("Soil vector ordinals are not contiguous/aligned with climate matrix")

    known_components = np.asarray([int(row[1]) for row in rows], dtype=np.uint16)
    known_fraction = np.asarray([float(row[2]) for row in rows], dtype=np.float64)
    score = np.asarray(
        [np.nan if row[3] is None else float(row[3]) for row in rows],
        dtype=np.float64,
    )
    status_codes = np.asarray([_STATUS_CODE[str(row[4])] for row in rows], dtype=np.uint8)
    return SoilScoreVector(
        score=score,
        known_fraction=known_fraction,
        known_components=known_components,
        status_codes=status_codes,
        elapsed_seconds=perf_counter() - started,
    )


def combine_score_vectors(
    matrix: ClimateRuntimeMatrix,
    climate: ClimateScoreVector,
    soil: SoilScoreVector,
) -> CombinedScoreVector:
    """Reproduce the current 75/25 blend, climate gate and deterministic sort."""
    started = perf_counter()
    if climate.overall.shape[0] != matrix.size or soil.score.shape[0] != matrix.size:
        raise ValueError("Climate/soil vector length mismatch")

    climate_known = np.isfinite(climate.overall)
    soil_known = np.isfinite(soil.score)
    soil_usable = soil_known & (soil.status_codes != _STATUS_CODE["UNKNOWN"])

    combined = np.full(matrix.size, np.nan, dtype=np.float64)
    only_soil = ~climate_known & soil_known
    combined[only_soil] = soil.score[only_soil]
    climate_without_usable_soil = climate_known & ~soil_usable
    combined[climate_without_usable_soil] = climate.overall[climate_without_usable_soil]
    blended = climate_known & soil_usable
    combined[blended] = 0.75 * climate.overall[blended] + 0.25 * soil.score[blended]

    status = np.full(matrix.size, _STATUS_CODE["UNKNOWN"], dtype=np.uint8)
    climate_red = climate.status_codes == _STATUS_CODE["RED"]
    climate_unknown = climate.status_codes == _STATUS_CODE["UNKNOWN"]
    eligible = ~climate_red & ~climate_unknown & np.isfinite(combined)
    status[climate_red] = _STATUS_CODE["RED"]
    status[eligible & (combined >= 75.0)] = _STATUS_CODE["GREEN"]
    status[eligible & (combined >= 40.0) & (combined < 75.0)] = _STATUS_CODE["ORANGE"]
    status[eligible & (combined < 40.0)] = _STATUS_CODE["RED"]

    climate_gate = np.where(
        (climate.status_codes == _STATUS_CODE["GREEN"])
        | (climate.status_codes == _STATUS_CODE["ORANGE"]),
        0,
        np.where(climate.status_codes == _STATUS_CODE["UNKNOWN"], 1, 2),
    )
    combined_rank = np.where(
        status == _STATUS_CODE["GREEN"],
        0,
        np.where(
            status == _STATUS_CODE["ORANGE"],
            1,
            np.where(status == _STATUS_CODE["UNKNOWN"], 2, 3),
        ),
    )
    combined_key = np.where(np.isfinite(combined), -combined, np.inf)
    climate_key = np.where(np.isfinite(climate.overall), -climate.overall, np.inf)
    centrality_key = np.where(np.isfinite(climate.centrality), -climate.centrality, np.inf)
    order = np.lexsort(
        (
            matrix.taxon_ids,
            centrality_key,
            climate_key,
            combined_key,
            combined_rank,
            climate_gate,
        )
    )
    return CombinedScoreVector(
        score=combined,
        status_codes=status,
        order=order,
        elapsed_seconds=perf_counter() - started,
    )
