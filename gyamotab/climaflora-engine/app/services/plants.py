import json
import math
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, quote_plus

from app.services.media_taxonomy import parent_species_name

from app.domain.models import (
    Confidence,
    EnvelopeLimit,
    PlantImageAsset,
    PlantSummary,
    SoilCategoricalPreference,
    SoilGeographicContext,
    SoilIndicatorPreference,
)

RANKABLE_VARIABLES = ("bio01", "bio05", "bio06", "bio12", "bio15")
RANKABLE_SOIL_VARIABLES = (
    "ph",
    "cec_cmol_kg",
    "clay_pct",
    "sand_pct",
    "coarse_fragments_pct",
    "soc_g_kg",
    "nitrogen_g_kg",
)

_INHERITED_CONFIDENCE = {
    Confidence.A: Confidence.B,
    Confidence.B: Confidence.C,
    Confidence.C: Confidence.D,
    Confidence.D: Confidence.D,
    Confidence.UNKNOWN: Confidence.UNKNOWN,
}


def _confidence(value: str | None, *, inherited: bool = False) -> Confidence:
    confidence = (
        Confidence(value)
        if value in Confidence._value2member_map_
        else Confidence.UNKNOWN
    )
    return _INHERITED_CONFIDENCE[confidence] if inherited else confidence


def _chunks(values: list[str], size: int = 800) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _powo_url(
    scientific_name: str,
    powo_id: str | None,
    scientific_name_id: str | None,
    references_url: str | None,
) -> str:
    for value in (powo_id, scientific_name_id):
        token = str(value or "").strip()
        if token:
            return "https://powo.science.kew.org/taxon/" + quote(token, safe="")
    if references_url and "powo.science.kew.org/" in references_url:
        return references_url
    return "https://powo.science.kew.org/results?q=" + quote_plus(scientific_name)


def taxon_links(
    scientific_name: str,
    powo_id: str | None = None,
    scientific_name_id: str | None = None,
    references_url: str | None = None,
) -> dict[str, str]:
    return {
        "wikipedia": "https://fr.wikipedia.org/wiki/Special:Search?search="
        + quote_plus(scientific_name)
        + "&go=Go",
        "powo": _powo_url(scientific_name, powo_id, scientific_name_id, references_url),
        "qwant": "https://www.qwant.com/?q=" + quote_plus(scientific_name),
    }


class PlantRepository:
    def iter_candidates(self, functions=None, limit=100, climate_variables=None, soil_variables=None) -> list[dict]:
        raise NotImplementedError

    def search(self, query: str, limit: int = 20) -> list[PlantSummary]:
        raise NotImplementedError

    def get(self, taxon_id: str) -> dict | None:
        raise NotImplementedError

    def readiness(self) -> dict:
        raise NotImplementedError


class UnavailablePlantRepository(PlantRepository):
    def __init__(self, path: str):
        self.path = path

    def iter_candidates(self, functions=None, limit=100, climate_variables=None, soil_variables=None) -> list[dict]:
        return []

    def search(self, query: str, limit: int = 20) -> list[PlantSummary]:
        return []

    def get(self, taxon_id: str) -> dict | None:
        return None

    def readiness(self) -> dict:
        return {
            "ready": False,
            "scientific_ready": False,
            "mode": "UNAVAILABLE",
            "path": self.path,
            "reason": "scientific catalog not ready",
        }


class DerivedSqlitePlantRepository(PlantRepository):
    def __init__(self, path: str):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{Path(self.path).resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-16384")
        conn.execute("PRAGMA mmap_size=268435456")
        return conn

    @staticmethod
    def _score_case(alias: str, variables: tuple[str, ...], parameter_prefix: str) -> str:
        value_expr = (
            f"CASE {alias}.variable "
            + " ".join(
                f"WHEN '{name}' THEN :{parameter_prefix}{name}"
                for name in variables
            )
            + " ELSE NULL END"
        )
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

    def _ranked_plant_rows(self, conn, functions, limit, climate_variables, soil_variables=None):
        params = {
            f"climate_{name}": (climate_variables or {}).get(name)
            for name in RANKABLE_VARIABLES
        }
        numeric_soil = {
            name: (
                float((soil_variables or {}).get(name))
                if isinstance((soil_variables or {}).get(name), (int, float))
                else None
            )
            for name in RANKABLE_SOIL_VARIABLES
        }
        params.update({f"soil_{name}": value for name, value in numeric_soil.items()})
        params["limit"] = max(1, int(limit))

        function_where = ""
        if functions:
            clauses = []
            for index, function in enumerate(functions):
                key = f"fn{index}"
                params[key] = function
                clauses.append(
                    f"EXISTS (SELECT 1 FROM json_each(p.functions_json) jf WHERE jf.value = :{key})"
                )
            function_where = " AND " + " AND ".join(clauses)

        climate_case = self._score_case("e", RANKABLE_VARIABLES, "climate_")
        climate_variable_sql = ",".join(repr(v) for v in RANKABLE_VARIABLES)
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        soil_available = "soil_envelope" in tables and any(value is not None for value in numeric_soil.values())

        if not soil_available:
            sql = f"""
            WITH raw AS (
                SELECT e.taxon_id, e.weight, {climate_case} AS rough_score
                FROM climate_envelope e
                WHERE e.variable IN ({climate_variable_sql})
            ), ranked AS (
                SELECT taxon_id,
                       SUM(CASE WHEN rough_score IS NOT NULL THEN weight ELSE 0 END) AS known_weight,
                       SUM(CASE WHEN rough_score IS NOT NULL THEN rough_score*weight ELSE 0 END) AS weighted_score
                FROM raw GROUP BY taxon_id
            )
            SELECT p.taxon_id, p.scientific_name, p.common_name, p.functions_json,
                   p.regulatory_veto, p.regulatory_reason, p.confidence,
                   p.powo_id, p.scientific_name_id, p.references_url,
                   CASE WHEN r.known_weight > 0 THEN r.weighted_score/r.known_weight ELSE -1 END AS rough_score
            FROM plant_index p
            LEFT JOIN ranked r ON r.taxon_id=p.taxon_id
            WHERE 1=1 {function_where}
            ORDER BY rough_score DESC, p.scientific_name ASC
            LIMIT :limit
            """
            return conn.execute(sql, params).fetchall()

        soil_case = self._score_case("s", RANKABLE_SOIL_VARIABLES, "soil_")
        soil_variable_sql = ",".join(repr(v) for v in RANKABLE_SOIL_VARIABLES)
        sql = f"""
        WITH climate_raw AS (
            SELECT e.taxon_id, e.weight, {climate_case} AS rough_score
            FROM climate_envelope e
            WHERE e.variable IN ({climate_variable_sql})
        ), climate_ranked AS (
            SELECT taxon_id,
                   SUM(CASE WHEN rough_score IS NOT NULL THEN weight ELSE 0 END) AS known_weight,
                   SUM(CASE WHEN rough_score IS NOT NULL THEN rough_score*weight ELSE 0 END) AS weighted_score
            FROM climate_raw GROUP BY taxon_id
        ), soil_raw AS (
            SELECT s.taxon_id, s.weight, {soil_case} AS rough_score
            FROM soil_envelope s
            WHERE s.variable IN ({soil_variable_sql})
        ), soil_ranked AS (
            SELECT taxon_id,
                   SUM(CASE WHEN rough_score IS NOT NULL THEN weight ELSE 0 END) AS known_weight,
                   SUM(CASE WHEN rough_score IS NOT NULL THEN rough_score*weight ELSE 0 END) AS weighted_score
            FROM soil_raw GROUP BY taxon_id
        ), base AS (
            SELECT p.taxon_id, p.scientific_name, p.common_name, p.functions_json,
                   p.regulatory_veto, p.regulatory_reason, p.confidence,
                   p.powo_id, p.scientific_name_id, p.references_url,
                   CASE WHEN c.known_weight > 0 THEN c.weighted_score/c.known_weight ELSE -1 END AS climate_rough,
                   CASE WHEN s.known_weight > 0 THEN s.weighted_score/s.known_weight ELSE -1 END AS soil_rough,
                   CASE
                       WHEN c.known_weight > 0 AND s.known_weight > 0
                           THEN 0.75*(c.weighted_score/c.known_weight) + 0.25*(s.weighted_score/s.known_weight)
                       WHEN c.known_weight > 0 THEN c.weighted_score/c.known_weight
                       ELSE -1
                   END AS combined_rough
            FROM plant_index p
            LEFT JOIN climate_ranked c ON c.taxon_id=p.taxon_id
            LEFT JOIN soil_ranked s ON s.taxon_id=p.taxon_id
            WHERE 1=1 {function_where}
        ), top_climate AS (
            SELECT taxon_id FROM base
            WHERE climate_rough >= 0
            ORDER BY climate_rough DESC, scientific_name ASC
            LIMIT :limit
        ), top_combined AS (
            SELECT taxon_id FROM base
            WHERE climate_rough >= 0
            ORDER BY combined_rough DESC, climate_rough DESC, scientific_name ASC
            LIMIT :limit
        ), selected AS (
            SELECT taxon_id FROM top_climate
            UNION
            SELECT taxon_id FROM top_combined
        )
        SELECT b.taxon_id, b.scientific_name, b.common_name, b.functions_json,
               b.regulatory_veto, b.regulatory_reason, b.confidence,
               b.powo_id, b.scientific_name_id, b.references_url,
               b.combined_rough AS rough_score,
               b.climate_rough, b.soil_rough
        FROM base b
        JOIN selected x ON x.taxon_id=b.taxon_id
        ORDER BY
            CASE
                WHEN b.climate_rough < 0 THEN 1
                WHEN b.climate_rough < 40 THEN 2
                ELSE 0
            END ASC,
            b.combined_rough DESC,
            b.climate_rough DESC,
            b.scientific_name ASC
        """
        return conn.execute(sql, params).fetchall()

    @staticmethod
    def _image_map(conn: sqlite3.Connection, tables: set[str], ids: list[str]) -> dict[str, PlantImageAsset]:
        if "plant_image_asset" not in tables or not ids:
            return {}
        columns = {str(r[1]) for r in conn.execute("PRAGMA table_info(plant_image_asset)")}
        required = {"taxon_id", "thumbnail_url"}
        if not required <= columns:
            return {}
        select_cols = [
            col
            for col in (
                "taxon_id",
                "asset_id",
                "thumbnail_url",
                "image_url",
                "source",
                "license",
                "author",
                "attribution_url",
                "is_primary",
            )
            if col in columns
        ]
        out: dict[str, PlantImageAsset] = {}
        for batch in _chunks(ids):
            marks = ",".join("?" for _ in batch)
            order = " ORDER BY COALESCE(is_primary,0) DESC" if "is_primary" in columns else ""
            for row in conn.execute(
                f"SELECT {','.join(select_cols)} FROM plant_image_asset WHERE taxon_id IN ({marks}){order}",
                batch,
            ):
                taxon_id = str(row["taxon_id"])
                if taxon_id in out:
                    continue
                values = dict(row)
                out[taxon_id] = PlantImageAsset(
                    asset_id=values.get("asset_id"),
                    thumbnail_url=values.get("thumbnail_url"),
                    image_url=values.get("image_url"),
                    source=values.get("source"),
                    license=values.get("license"),
                    author=values.get("author"),
                    attribution_url=values.get("attribution_url"),
                )
        return out

    def _hydrate(self, conn: sqlite3.Connection, plants: list[sqlite3.Row]) -> list[dict]:
        if not plants:
            return []
        ids = [str(row["taxon_id"]) for row in plants]
        envelopes: dict[str, list[sqlite3.Row]] = {taxon_id: [] for taxon_id in ids}
        soil_envelopes: dict[str, list[sqlite3.Row]] = {taxon_id: [] for taxon_id in ids}
        soil_categorical: dict[str, list[sqlite3.Row]] = {taxon_id: [] for taxon_id in ids}
        soil_indicators: dict[str, list[sqlite3.Row]] = {taxon_id: [] for taxon_id in ids}
        soil_priors: dict[str, sqlite3.Row] = {}
        evidences: dict[str, list[sqlite3.Row]] = {taxon_id: [] for taxon_id in ids}
        tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        for batch in _chunks(ids):
            marks = ",".join("?" for _ in batch)
            for row in conn.execute(
                f"SELECT taxon_id, variable, hard_low, optimum_low, optimum_high, hard_high, weight, "
                f"group_code, fatal, confidence, source_ref FROM climate_envelope WHERE taxon_id IN ({marks})",
                batch,
            ):
                envelopes[str(row["taxon_id"])].append(row)
            if "soil_envelope" in tables:
                for row in conn.execute(
                    f"SELECT taxon_id, variable, hard_low, optimum_low, optimum_high, hard_high, weight, "
                    f"group_code, fatal, confidence, source_ref FROM soil_envelope WHERE taxon_id IN ({marks})",
                    batch,
                ):
                    soil_envelopes[str(row["taxon_id"])].append(row)
            if "soil_categorical_preference" in tables:
                for row in conn.execute(
                    f"SELECT taxon_id, variable, optimum_values_json, accepted_values_json, weight, confidence, "
                    f"source_ref FROM soil_categorical_preference WHERE taxon_id IN ({marks})",
                    batch,
                ):
                    soil_categorical[str(row["taxon_id"])].append(row)
            if "soil_indicator_preference" in tables:
                for row in conn.execute(
                    f"SELECT taxon_id, region_scope, indicator, optimum, niche_width, source_systems, scale_min, "
                    f"scale_max, weight, confidence, source_ref, method, method_version "
                    f"FROM soil_indicator_preference WHERE taxon_id IN ({marks})",
                    batch,
                ):
                    soil_indicators[str(row["taxon_id"])].append(row)
            if "soil_geographic_prior" in tables:
                for row in conn.execute(
                    f"SELECT taxon_id, native_region_count, covered_region_count, variables_json, confidence, "
                    f"scoring_enabled, source_ref, method, method_version "
                    f"FROM soil_geographic_prior WHERE taxon_id IN ({marks})",
                    batch,
                ):
                    soil_priors[str(row["taxon_id"])] = row
            for row in conn.execute(
                f"SELECT taxon_id, claim_type, claim_value, source_id, source_reference, source_version, "
                f"extraction_method, confidence, notes FROM evidence WHERE taxon_id IN ({marks})",
                batch,
            ):
                evidences[str(row["taxon_id"])].append(row)

        soil_inheritance: dict[str, dict[str, str]] = {}
        missing_scoring = [
            str(plant["taxon_id"])
            for plant in plants
            if not soil_envelopes.get(str(plant["taxon_id"]))
            and not soil_categorical.get(str(plant["taxon_id"]))
        ]
        requested_names = {
            str(plant["taxon_id"]): " ".join(str(plant["scientific_name"] or "").split())
            for plant in plants
            if str(plant["taxon_id"]) in missing_scoring
        }
        parent_names = sorted(
            {
                parent
                for name in requested_names.values()
                if (parent := parent_species_name(name)) is not None
            }
        )
        parent_by_name: dict[str, tuple[str, str]] = {}
        if parent_names:
            marks = ",".join("?" for _ in parent_names)
            candidates_by_name: dict[str, list[str]] = {}
            for row in conn.execute(
                f"SELECT taxon_id,scientific_name FROM plant_index WHERE scientific_name IN ({marks})",
                parent_names,
            ):
                name = " ".join(str(row["scientific_name"] or "").split())
                candidates_by_name.setdefault(name, []).append(str(row["taxon_id"]))
            parent_by_name = {
                name: (taxon_ids[0], name)
                for name, taxon_ids in candidates_by_name.items()
                if len(taxon_ids) == 1
            }

        fallback_parent_ids = sorted(
            {
                parent_by_name[parent_name][0]
                for child_name in requested_names.values()
                if (parent_name := parent_species_name(child_name)) in parent_by_name
            }
        )
        parent_soil_envelopes: dict[str, list[sqlite3.Row]] = {
            taxon_id: [] for taxon_id in fallback_parent_ids
        }
        parent_soil_categorical: dict[str, list[sqlite3.Row]] = {
            taxon_id: [] for taxon_id in fallback_parent_ids
        }
        for batch in _chunks(fallback_parent_ids):
            marks = ",".join("?" for _ in batch)
            if "soil_envelope" in tables:
                for row in conn.execute(
                    f"SELECT taxon_id, variable, hard_low, optimum_low, optimum_high, hard_high, weight, "
                    f"group_code, fatal, confidence, source_ref FROM soil_envelope WHERE taxon_id IN ({marks})",
                    batch,
                ):
                    parent_soil_envelopes[str(row["taxon_id"])].append(row)
            if "soil_categorical_preference" in tables:
                for row in conn.execute(
                    f"SELECT taxon_id, variable, optimum_values_json, accepted_values_json, weight, confidence, "
                    f"source_ref FROM soil_categorical_preference WHERE taxon_id IN ({marks})",
                    batch,
                ):
                    parent_soil_categorical[str(row["taxon_id"])].append(row)

        for child_id, child_name in requested_names.items():
            parent_name = parent_species_name(child_name)
            parent = parent_by_name.get(parent_name or "")
            if not parent:
                continue
            parent_id, resolved_parent_name = parent
            inherited_limits = parent_soil_envelopes.get(parent_id, [])
            inherited_categorical = parent_soil_categorical.get(parent_id, [])
            if not inherited_limits and not inherited_categorical:
                continue
            soil_envelopes[child_id] = inherited_limits
            soil_categorical[child_id] = inherited_categorical
            soil_inheritance[child_id] = {
                "taxon_id": parent_id,
                "scientific_name": resolved_parent_name,
            }

        images = self._image_map(conn, tables, ids)

        def limits_from(rows: list[sqlite3.Row], *, inherited: bool = False) -> list[EnvelopeLimit]:
            return [
                EnvelopeLimit(
                    variable=row["variable"],
                    hard_low=row["hard_low"],
                    optimum_low=row["optimum_low"],
                    optimum_high=row["optimum_high"],
                    hard_high=row["hard_high"],
                    weight=row["weight"],
                    group=row["group_code"],
                    fatal=bool(row["fatal"]),
                    confidence=_confidence(row["confidence"], inherited=inherited),
                    source_ref=row["source_ref"],
                )
                for row in rows
            ]

        def categorical_from(
            rows: list[sqlite3.Row],
            *,
            inherited: bool = False,
        ) -> list[SoilCategoricalPreference]:
            return [
                SoilCategoricalPreference(
                    variable=row["variable"],
                    optimum_values=json.loads(row["optimum_values_json"] or "[]"),
                    accepted_values=json.loads(row["accepted_values_json"] or "[]"),
                    weight=float(row["weight"] or 1.0),
                    confidence=_confidence(row["confidence"], inherited=inherited),
                    source_ref=row["source_ref"],
                )
                for row in rows
            ]

        def indicators_from(rows: list[sqlite3.Row]) -> list[SoilIndicatorPreference]:
            return [
                SoilIndicatorPreference(
                    indicator=str(row["indicator"]),
                    optimum=float(row["optimum"]),
                    niche_width=row["niche_width"],
                    source_systems=row["source_systems"],
                    scale_min=float(row["scale_min"]),
                    scale_max=float(row["scale_max"]),
                    region_scope=str(row["region_scope"]),
                    weight=float(row["weight"] or 1.0),
                    confidence=(
                        Confidence(row["confidence"])
                        if row["confidence"] in Confidence._value2member_map_
                        else Confidence.UNKNOWN
                    ),
                    source_ref=row["source_ref"],
                    method=row["method"],
                    method_version=row["method_version"],
                )
                for row in rows
            ]

        def prior_from(row: sqlite3.Row | None) -> SoilGeographicContext | None:
            if row is None:
                return None
            try:
                variables = json.loads(row["variables_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                variables = {}
            return SoilGeographicContext(
                native_region_count=int(row["native_region_count"]),
                covered_region_count=int(row["covered_region_count"]),
                variables=variables if isinstance(variables, dict) else {},
                confidence=str(row["confidence"] or "PRIOR"),
                scoring_enabled=False,
                source_ref=row["source_ref"],
                method=row["method"],
                method_version=row["method_version"],
            )

        output = []
        for plant in plants:
            taxon_id = str(plant["taxon_id"])
            links = taxon_links(
                plant["scientific_name"],
                plant["powo_id"],
                plant["scientific_name_id"],
                plant["references_url"],
            )
            output.append(
                {
                    "taxon_id": taxon_id,
                    "scientific_name": plant["scientific_name"],
                    "common_name": plant["common_name"],
                    "functions": json.loads(plant["functions_json"] or "[]"),
                    "regulatory_veto": bool(plant["regulatory_veto"]),
                    "regulatory_reason": (
                        plant["regulatory_reason"] if "regulatory_reason" in plant.keys() else None
                    ),
                    "limits": limits_from(envelopes.get(taxon_id, [])),
                    "soil_limits": limits_from(
                        soil_envelopes.get(taxon_id, []),
                        inherited=taxon_id in soil_inheritance,
                    ),
                    "soil_categorical_preferences": categorical_from(
                        soil_categorical.get(taxon_id, []),
                        inherited=taxon_id in soil_inheritance,
                    ),
                    "soil_inheritance": soil_inheritance.get(taxon_id),
                    "soil_indicators": indicators_from(soil_indicators.get(taxon_id, [])),
                    "soil_geographic_context": prior_from(soil_priors.get(taxon_id)),
                    "links": links,
                    "image": images.get(taxon_id),
                    "evidence": [
                        {key: value for key, value in dict(row).items() if key != "taxon_id"}
                        for row in evidences.get(taxon_id, [])[:50]
                    ],
                }
            )
        return output

    @staticmethod
    def _numeric_cache_key(values: dict | None, names: tuple[str, ...]) -> tuple[tuple[str, float | None], ...]:
        source = values or {}
        normalized = []
        for name in names:
            value = source.get(name)
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                normalized.append((name, float(value)))
            else:
                normalized.append((name, None))
        return tuple(normalized)

    @lru_cache(maxsize=4)
    def _cached_candidates(
        self,
        functions_key: tuple[str, ...],
        limit: int,
        climate_key: tuple[tuple[str, float | None], ...],
        soil_key: tuple[tuple[str, float | None], ...],
    ) -> tuple[dict, ...]:
        climate_variables = dict(climate_key)
        soil_variables = dict(soil_key)
        with self._connect() as conn:
            plants = self._ranked_plant_rows(
                conn,
                list(functions_key),
                limit,
                climate_variables,
                soil_variables,
            )
            return tuple(self._hydrate(conn, plants))

    def iter_candidates(self, functions=None, limit=100, climate_variables=None, soil_variables=None) -> list[dict]:
        functions_key = tuple(sorted(str(value) for value in (functions or [])))
        climate_key = self._numeric_cache_key(climate_variables, RANKABLE_VARIABLES)
        soil_key = self._numeric_cache_key(soil_variables, RANKABLE_SOIL_VARIABLES)
        return list(self._cached_candidates(functions_key, max(1, int(limit)), climate_key, soil_key))

    def search(self, query: str, limit: int = 20) -> list[PlantSummary]:
        q = query.strip()
        if not q:
            return []
        escaped = q.replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT taxon_id, scientific_name, common_name, functions_json, regulatory_veto, "
                "powo_id, scientific_name_id, references_url "
                "FROM plant_index WHERE scientific_name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR common_name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "ORDER BY CASE WHEN scientific_name LIKE ? COLLATE NOCASE THEN 0 ELSE 1 END, "
                "scientific_name LIMIT ?",
                (pattern, pattern, f"{escaped}%", limit),
            ).fetchall()
            tables = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            images = self._image_map(conn, tables, [str(row["taxon_id"]) for row in rows])
        return [
            PlantSummary(
                taxon_id=str(row["taxon_id"]),
                scientific_name=row["scientific_name"],
                common_name=row["common_name"],
                functions=json.loads(row["functions_json"] or "[]"),
                regulatory_veto=bool(row["regulatory_veto"]),
                links=taxon_links(
                    row["scientific_name"],
                    row["powo_id"],
                    row["scientific_name_id"],
                    row["references_url"],
                ),
                image=images.get(str(row["taxon_id"])),
            )
            for row in rows
        ]

    def get(self, taxon_id: str) -> dict | None:
        with self._connect() as conn:
            plant = conn.execute(
                "SELECT taxon_id, scientific_name, common_name, functions_json, regulatory_veto, "
                "regulatory_reason, confidence, powo_id, scientific_name_id, references_url "
                "FROM plant_index WHERE taxon_id=?",
                (taxon_id,),
            ).fetchone()
            return self._hydrate(conn, [plant])[0] if plant else None

    def readiness(self) -> dict:
        path = Path(self.path)
        if not path.exists():
            return {"ready": False, "mode": "DERIVED_SQLITE", "path": self.path, "reason": "missing"}
        try:
            with self._connect() as conn:
                tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                required = {"plant_index", "climate_envelope", "evidence"}
                missing = sorted(required - tables)
                count = conn.execute("SELECT COUNT(*) FROM plant_index").fetchone()[0] if not missing else 0
                envelope_count = (
                    conn.execute("SELECT COUNT(*) FROM climate_envelope").fetchone()[0]
                    if not missing
                    else 0
                )
                soil_envelope_count = (
                    conn.execute("SELECT COUNT(*) FROM soil_envelope").fetchone()[0]
                    if "soil_envelope" in tables
                    else 0
                )
                soil_categorical_count = (
                    conn.execute("SELECT COUNT(*) FROM soil_categorical_preference").fetchone()[0]
                    if "soil_categorical_preference" in tables
                    else 0
                )
                soil_indicator_count = (
                    conn.execute("SELECT COUNT(*) FROM soil_indicator_preference").fetchone()[0]
                    if "soil_indicator_preference" in tables
                    else 0
                )
                soil_indicator_taxa = (
                    conn.execute("SELECT COUNT(DISTINCT taxon_id) FROM soil_indicator_preference").fetchone()[0]
                    if "soil_indicator_preference" in tables
                    else 0
                )
                soil_prior_taxa = (
                    conn.execute("SELECT COUNT(*) FROM soil_geographic_prior").fetchone()[0]
                    if "soil_geographic_prior" in tables
                    else 0
                )
                soil_prior_scoring_rows = (
                    conn.execute(
                        "SELECT COUNT(*) FROM soil_geographic_prior WHERE scoring_enabled<>0"
                    ).fetchone()[0]
                    if "soil_geographic_prior" in tables
                    else 0
                )
                image_assets = (
                    conn.execute("SELECT COUNT(*) FROM plant_image_asset").fetchone()[0]
                    if "plant_image_asset" in tables
                    else 0
                )
                metadata = (
                    {row[0]: row[1] for row in conn.execute("SELECT key,value FROM build_metadata")}
                    if "build_metadata" in tables
                    else {}
                )
                mode = metadata.get("mode", "DERIVED_SQLITE")
                scientific_ready = not missing and count > 0 and envelope_count > 0 and (
                    mode == "SCIENTIFIC"
                    or (
                        mode.startswith("SCIENTIFIC_PROXY_")
                        and metadata.get("scientific_ready", "false").lower() == "true"
                    )
                )
                return {
                    "ready": not missing and count > 0 and envelope_count > 0,
                    "scientific_ready": scientific_ready,
                    "mode": mode,
                    "path": self.path,
                    "plants": count,
                    "envelopes": envelope_count,
                    "soil_envelopes": soil_envelope_count,
                    "soil_categorical_preferences": soil_categorical_count,
                    "soil_indicator_preferences": soil_indicator_count,
                    "soil_indicator_taxa": soil_indicator_taxa,
                    "soil_geographic_prior_taxa": soil_prior_taxa,
                    "soil_geographic_prior_scoring_rows": soil_prior_scoring_rows,
                    "image_assets": image_assets,
                    "soil_preferences_ready": (soil_envelope_count + soil_categorical_count) > 0,
                    "soil_context_ready": (
                        soil_envelope_count
                        + soil_categorical_count
                        + soil_indicator_count
                        + soil_prior_taxa
                    )
                    > 0,
                    "missing_tables": missing,
                    "build_metadata": metadata,
                }
        except sqlite3.Error as exc:
            return {"ready": False, "mode": "DERIVED_SQLITE", "path": self.path, "reason": str(exc)}


@lru_cache(maxsize=8)
def _make_available_plant_repository(derived_db: str) -> PlantRepository:
    return DerivedSqlitePlantRepository(str(Path(derived_db)))


def make_plant_repository(derived_db: str) -> PlantRepository:
    path = Path(derived_db)
    if path.exists():
        return _make_available_plant_repository(str(path))
    # Do not cache a negative bootstrap state: the canonical catalog may appear
    # moments later after download/decompression/audit completes.
    return UnavailablePlantRepository(str(path))
