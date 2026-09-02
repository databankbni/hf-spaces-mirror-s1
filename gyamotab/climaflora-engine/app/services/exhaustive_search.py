from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock
from time import monotonic

from app.services.media_taxonomy import parent_species_name
from app.services.plants import DerivedSqlitePlantRepository

CLIMATE_VARIABLES = ("bio01", "bio05", "bio06", "bio12", "bio15")
STATUS_VALUES = ("GREEN", "ORANGE", "RED", "UNKNOWN")
LIFE_FORM_VALUES = ("TREE", "SHRUB", "HERB", "CLIMBER", "PALM", "OTHER", "UNKNOWN")
GROUP_WEIGHT_SQL = "CASE {alias}.group_code WHEN 'M' THEN 0.30 WHEN 'V' THEN 0.20 WHEN 'E' THEN 0.35 WHEN 'A' THEN 0.15 ELSE 0.0 END"


@dataclass(frozen=True)
class SearchSnapshot:
    created_at: float
    ranked_rows: tuple[tuple[str, str, str], ...]
    metrics: dict
    facets: dict
    token: str

    @property
    def ranked_ids(self) -> tuple[str, ...]:
        # Compatibility accessor for diagnostics; presentation filtering uses
        # ranked_rows so climate/soil status changes do not trigger rescoring.
        return tuple(row[0] for row in self.ranked_rows)


class _SnapshotCache:
    def __init__(self, max_entries: int = 3, ttl_seconds: float = 900.0):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._lock = RLock()
        self._items: OrderedDict[str, SearchSnapshot] = OrderedDict()

    def get(self, key: str) -> SearchSnapshot | None:
        now = monotonic()
        with self._lock:
            stale = [k for k, item in self._items.items() if now - item.created_at > self.ttl_seconds]
            for k in stale:
                self._items.pop(k, None)
            item = self._items.get(key)
            if item is None:
                return None
            self._items.move_to_end(key)
            return item

    def put(self, key: str, snapshot: SearchSnapshot) -> None:
        with self._lock:
            self._items[key] = snapshot
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


_CACHE = _SnapshotCache()


def _status_filter(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    selected = tuple(
        dict.fromkeys(str(v).upper() for v in (values or []) if str(v).upper() in STATUS_VALUES)
    )
    return selected or STATUS_VALUES


def _life_form(value: str | None) -> str:
    normalized = str(value or "ALL").upper()
    return normalized if normalized in (*LIFE_FORM_VALUES, "ALL") else "ALL"


def _score_sql(alias: str, value_expr: str) -> str:
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


def _case_value(alias: str, values: dict, params: dict, prefix: str, *, numeric: bool) -> str:
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


def _prepare_life_categories(conn: sqlite3.Connection, tables: set[str]) -> None:
    conn.execute("CREATE TEMP TABLE life_lookup(taxon_id TEXT PRIMARY KEY, life_value TEXT NOT NULL)")
    if "plant_profile" in tables:
        conn.execute(
            """
            INSERT OR REPLACE INTO life_lookup(taxon_id,life_value)
            SELECT taxon_id,TRIM(life_form)
            FROM main.plant_profile
            WHERE TRIM(COALESCE(life_form,''))<>''
            """
        )
    if "plant_trait_evidence" in tables:
        conn.execute(
            """
            INSERT OR IGNORE INTO life_lookup(taxon_id,life_value)
            SELECT taxon_id,TRIM(trait_value)
            FROM (
                SELECT taxon_id,trait_value,
                       ROW_NUMBER() OVER (
                           PARTITION BY taxon_id
                           ORDER BY CASE UPPER(COALESCE(confidence,''))
                                      WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2 WHEN 'D' THEN 3 ELSE 4 END,
                                    source_id
                       ) AS rn
                FROM main.plant_trait_evidence
                WHERE trait_name='life_form' AND TRIM(COALESCE(trait_value,''))<>''
            ) ranked
            WHERE rn=1
            """
        )
    conn.execute(
        """
        CREATE TEMP TABLE life_category AS
        SELECT p.taxon_id,
               CASE
                 WHEN ll.life_value IS NULL OR TRIM(ll.life_value)='' THEN 'UNKNOWN'
                 WHEN LOWER(ll.life_value) LIKE '%palm%' OR LOWER(ll.life_value) LIKE '%palmae%' OR LOWER(ll.life_value) LIKE '%palmier%' THEN 'PALM'
                 WHEN LOWER(ll.life_value) LIKE '%climb%' OR LOWER(ll.life_value) LIKE '%liana%' OR LOWER(ll.life_value) LIKE '%vine%' OR LOWER(ll.life_value) LIKE '%grimp%' THEN 'CLIMBER'
                 WHEN LOWER(ll.life_value) LIKE '%shrub%' OR LOWER(ll.life_value) LIKE '%bush%' OR LOWER(ll.life_value) LIKE '%arbust%' THEN 'SHRUB'
                 WHEN LOWER(ll.life_value) LIKE '%tree%' OR LOWER(ll.life_value) LIKE '%arbores%' OR LOWER(ll.life_value) LIKE '%arbre%' THEN 'TREE'
                 WHEN LOWER(ll.life_value) LIKE '%herb%' OR LOWER(ll.life_value) LIKE '%forb%' OR LOWER(ll.life_value) LIKE '%graminoid%' OR LOWER(ll.life_value) LIKE '%grass%' OR LOWER(ll.life_value) LIKE '%herbac%' THEN 'HERB'
                 ELSE 'OTHER'
               END AS category
        FROM main.plant_index p
        LEFT JOIN life_lookup ll ON ll.taxon_id=p.taxon_id
        """
    )
    conn.execute("CREATE UNIQUE INDEX temp.idx_life_category_taxon ON life_category(taxon_id)")
    conn.execute("CREATE INDEX temp.idx_life_category_value ON life_category(category)")


def _function_predicate(
    tables: set[str], alias: str, functions: tuple[str, ...], params: dict
) -> str:
    if not functions:
        return "1=1"
    clauses = []
    for index, function in enumerate(functions):
        key = f"function_{index}"
        params[key] = function
        if "plant_use" in tables:
            clauses.append(
                f"EXISTS (SELECT 1 FROM main.plant_use pu WHERE pu.taxon_id={alias}.taxon_id AND pu.use_code=:{key})"
            )
        else:
            clauses.append(
                f"EXISTS (SELECT 1 FROM json_each(COALESCE({alias}.functions_json,'[]')) jf WHERE jf.value=:{key})"
            )
    return " AND ".join(clauses)


def _hydrate_page(path: Path, ids: tuple[str, ...]) -> list[dict]:
    if not ids:
        return []
    repository = DerivedSqlitePlantRepository(str(path))
    with repository._connect() as conn:  # noqa: SLF001 - deliberate repository reuse
        marks = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""
            SELECT taxon_id,scientific_name,common_name,functions_json,
                   regulatory_veto,regulatory_reason,confidence,powo_id,scientific_name_id,references_url
            FROM plant_index WHERE taxon_id IN ({marks})
            """,
            ids,
        ).fetchall()
        by_id = {str(row["taxon_id"]): row for row in rows}
        ordered = [by_id[taxon_id] for taxon_id in ids if taxon_id in by_id]
        return repository._hydrate(conn, ordered)  # noqa: SLF001 - deliberate repository reuse


def _cache_key(
    path: Path,
    *,
    life_form: str,
    functions: tuple[str, ...],
    climate: dict,
    soil: dict,
    statuses: tuple[str, ...],
    soil_statuses: tuple[str, ...],
    min_known_weight: float,
) -> str:
    payload = {
        "path": str(path.resolve()),
        "mtime": path.stat().st_mtime_ns if path.exists() else 0,
        "life_form": life_form,
        "functions": functions,
        "climate": climate,
        "soil": soil,
        # Climate/soil status selections are presentation filters. They are
        # intentionally excluded from the scientific snapshot identity.
        "min_known_weight": min_known_weight,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def exhaustive_search(
    path: str,
    *,
    climate_variables: dict,
    soil_variables: dict,
    life_form: str = "ALL",
    functions: list[str] | None = None,
    statuses: list[str] | None = None,
    soil_statuses: list[str] | None = None,
    offset: int = 0,
    limit: int = 50,
    min_known_weight: float = 0.50,
) -> dict:
    db_path = Path(path)
    if not db_path.exists():
        return {
            "candidates": [],
            "metrics": {
                "catalog_total": 0,
                "after_type": 0,
                "after_function": 0,
                "evaluated_candidates": 0,
                "total_results": 0,
            },
            "facets": {
                "life_form": {},
                "functions": {},
                "climate_status": {},
                "soil_status": {},
            },
            "pagination": {
                "offset": 0,
                "limit": limit,
                "has_previous": False,
                "has_next": False,
            },
            "search_token": None,
            "cache_hit": False,
        }

    normalized_life = _life_form(life_form)
    normalized_functions = tuple(sorted(dict.fromkeys(str(v) for v in (functions or []) if str(v))))
    normalized_statuses = _status_filter(statuses)
    normalized_soil_statuses = _status_filter(soil_statuses)
    offset = max(0, int(offset))
    limit = max(1, min(100, int(limit)))

    key = _cache_key(
        db_path,
        life_form=normalized_life,
        functions=normalized_functions,
        climate=climate_variables or {},
        soil=soil_variables or {},
        statuses=normalized_statuses,
        soil_statuses=normalized_soil_statuses,
        min_known_weight=float(min_known_weight),
    )
    snapshot = _CACHE.get(key)
    cache_hit = snapshot is not None

    if snapshot is None:
        uri = f"file:{db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.create_function(
            "climaflora_parent_species_name",
            1,
            parent_species_name,
            deterministic=True,
        )
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-32768")
        conn.execute("PRAGMA mmap_size=268435456")
        try:
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table'")
            }
            catalog_total = int(conn.execute("SELECT COUNT(*) FROM main.plant_index").fetchone()[0])
            _prepare_life_categories(conn, tables)
            life_counts = {
                row["category"]: int(row["n"])
                for row in conn.execute(
                    "SELECT category,COUNT(*) AS n FROM life_category GROUP BY category"
                )
            }

            params: dict = {}
            life_clause = "1=1" if normalized_life == "ALL" else "lc.category=:life_form"
            if normalized_life != "ALL":
                params["life_form"] = normalized_life
            conn.execute(
                f"""
                CREATE TEMP TABLE typed AS
                SELECT p.taxon_id
                FROM main.plant_index p
                JOIN life_category lc ON lc.taxon_id=p.taxon_id
                WHERE {life_clause}
                """,
                params,
            )
            conn.execute("CREATE UNIQUE INDEX temp.idx_typed_taxon ON typed(taxon_id)")
            after_type = int(conn.execute("SELECT COUNT(*) FROM typed").fetchone()[0])

            if "plant_use" in tables:
                function_counts = {
                    str(row["code"]): int(row["n"])
                    for row in conn.execute(
                        """
                        SELECT pu.use_code AS code,COUNT(DISTINCT pu.taxon_id) AS n
                        FROM main.plant_use pu JOIN typed t ON t.taxon_id=pu.taxon_id
                        GROUP BY pu.use_code
                        """
                    )
                }
            else:
                function_counts = {
                    str(row["code"]): int(row["n"])
                    for row in conn.execute(
                        """
                        SELECT jf.value AS code,COUNT(DISTINCT p.taxon_id) AS n
                        FROM main.plant_index p JOIN typed t ON t.taxon_id=p.taxon_id,
                             json_each(COALESCE(p.functions_json,'[]')) jf
                        GROUP BY jf.value
                        """
                    )
                }

            fn_params: dict = {}
            fn_clause = _function_predicate(tables, "p", normalized_functions, fn_params)
            conn.execute(
                f"""
                CREATE TEMP TABLE eligible AS
                SELECT p.taxon_id
                FROM main.plant_index p JOIN typed t ON t.taxon_id=p.taxon_id
                WHERE {fn_clause}
                """,
                fn_params,
            )
            conn.execute("CREATE UNIQUE INDEX temp.idx_eligible_taxon ON eligible(taxon_id)")
            after_function = int(conn.execute("SELECT COUNT(*) FROM eligible").fetchone()[0])

            climate_params: dict = {}
            climate_value = _case_value(
                "e", climate_variables or {}, climate_params, "climate_", numeric=True
            )
            climate_score = _score_sql("e", climate_value)
            centrality = f"""CASE
                WHEN ({climate_value}) IS NULL THEN NULL
                WHEN e.optimum_low IS NULL OR e.optimum_high IS NULL OR e.optimum_high<=e.optimum_low THEN 50.0
                WHEN ({climate_value}) BETWEEN e.optimum_low AND e.optimum_high THEN
                    MAX(0.0, 100.0 - 100.0*ABS(({climate_value})-((e.optimum_low+e.optimum_high)/2.0)) /
                        MAX((e.optimum_high-e.optimum_low)/2.0, 0.000001))
                ELSE 0.0 END"""
            variable_sql = ",".join(repr(v) for v in CLIMATE_VARIABLES)
            conn.execute(
                f"""
                CREATE TEMP TABLE climate_component AS
                SELECT e.taxon_id,e.group_code,e.weight,e.fatal,
                       {climate_score} AS score,
                       {centrality} AS centrality
                FROM main.climate_envelope e JOIN eligible x ON x.taxon_id=e.taxon_id
                WHERE e.variable IN ({variable_sql})
                """,
                climate_params,
            )
            conn.execute("CREATE INDEX temp.idx_climate_component_taxon ON climate_component(taxon_id)")
            conn.execute(
                """
                CREATE TEMP TABLE climate_group AS
                SELECT taxon_id,group_code,
                       SUM(score*weight)/NULLIF(SUM(weight),0) AS group_score
                FROM climate_component
                WHERE score IS NOT NULL
                GROUP BY taxon_id,group_code
                """
            )
            conn.execute("CREATE INDEX temp.idx_climate_group_taxon ON climate_group(taxon_id)")
            conn.execute(
                """
                CREATE TEMP TABLE climate_aux AS
                SELECT x.taxon_id,
                       CASE WHEN COALESCE(SUM(CASE WHEN c.weight>0 THEN c.weight ELSE 0 END),0)>0
                            THEN COALESCE(SUM(CASE WHEN c.score IS NOT NULL THEN c.weight ELSE 0 END),0) /
                                 SUM(CASE WHEN c.weight>0 THEN c.weight ELSE 0 END)
                            ELSE 0.0 END AS known_fraction,
                       MAX(CASE WHEN c.fatal=1 AND c.score IS NOT NULL AND c.score<40 THEN 1 ELSE 0 END) AS fatal_red,
                       CASE WHEN COALESCE(SUM(CASE WHEN c.centrality IS NOT NULL THEN c.weight ELSE 0 END),0)>0
                            THEN SUM(COALESCE(c.centrality,0)*c.weight) /
                                 SUM(CASE WHEN c.centrality IS NOT NULL THEN c.weight ELSE 0 END)
                            ELSE 0.0 END AS climate_centrality
                FROM eligible x LEFT JOIN climate_component c ON c.taxon_id=x.taxon_id
                GROUP BY x.taxon_id
                """
            )
            group_weight = GROUP_WEIGHT_SQL.format(alias="g")
            conn.execute(
                f"""
                CREATE TEMP TABLE climate_score AS
                SELECT a.taxon_id,a.known_fraction,a.fatal_red,a.climate_centrality,
                       CASE WHEN SUM({group_weight})>0
                            THEN SUM(g.group_score*({group_weight}))/SUM({group_weight})
                            ELSE NULL END AS overall_score
                FROM climate_aux a LEFT JOIN climate_group g ON g.taxon_id=a.taxon_id
                GROUP BY a.taxon_id,a.known_fraction,a.fatal_red,a.climate_centrality
                """
            )
            conn.execute(
                """
                CREATE TEMP TABLE climate_rank AS
                SELECT taxon_id,known_fraction,fatal_red,climate_centrality,overall_score,
                       CASE WHEN fatal_red=1 THEN 'RED'
                            WHEN known_fraction<:min_known OR overall_score IS NULL THEN 'UNKNOWN'
                            WHEN overall_score>=75 THEN 'GREEN'
                            WHEN overall_score>=40 THEN 'ORANGE'
                            ELSE 'RED' END AS climate_status
                FROM climate_score
                """,
                {"min_known": float(min_known_weight)},
            )
            conn.execute("CREATE UNIQUE INDEX temp.idx_climate_rank_taxon ON climate_rank(taxon_id)")
            climate_status_counts = {
                row["climate_status"]: int(row["n"])
                for row in conn.execute(
                    "SELECT climate_status,COUNT(*) AS n FROM climate_rank GROUP BY climate_status"
                )
            }

            soil_params: dict = {}
            soil_numeric_value = _case_value(
                "s", soil_variables or {}, soil_params, "soil_num_", numeric=True
            )
            soil_numeric_score = _score_sql("s", soil_numeric_value)
            conn.execute(
                "CREATE TEMP TABLE soil_component(taxon_id TEXT,weight REAL,score REAL)"
            )
            if "soil_envelope" in tables:
                conn.execute(
                    f"""
                    INSERT INTO soil_component(taxon_id,weight,score)
                    SELECT s.taxon_id,s.weight,{soil_numeric_score}
                    FROM main.soil_envelope s JOIN eligible x ON x.taxon_id=s.taxon_id
                    """,
                    soil_params,
                )
            if "soil_categorical_preference" in tables:
                cat_params: dict = {}
                cat_value = _case_value(
                    "s", soil_variables or {}, cat_params, "soil_cat_", numeric=False
                )
                conn.execute(
                    f"""
                    INSERT INTO soil_component(taxon_id,weight,score)
                    SELECT s.taxon_id,s.weight,
                           CASE WHEN ({cat_value}) IS NULL THEN NULL
                                WHEN EXISTS (
                                    SELECT 1 FROM json_each(COALESCE(s.optimum_values_json,'[]')) j
                                    WHERE LOWER(TRIM(CAST(j.value AS TEXT)))=LOWER(TRIM(CAST(({cat_value}) AS TEXT)))
                                ) THEN 100.0
                                WHEN EXISTS (
                                    SELECT 1 FROM json_each(COALESCE(s.accepted_values_json,'[]')) j
                                    WHERE LOWER(TRIM(CAST(j.value AS TEXT)))=LOWER(TRIM(CAST(({cat_value}) AS TEXT)))
                                ) THEN 65.0
                                ELSE 0.0 END
                    FROM main.soil_categorical_preference s JOIN eligible x ON x.taxon_id=s.taxon_id
                    """,
                    cat_params,
                )
            own_soil_absence = [
                "NOT EXISTS (SELECT 1 FROM main.soil_envelope own_num WHERE own_num.taxon_id=child.taxon_id)"
            ] if "soil_envelope" in tables else []
            if "soil_categorical_preference" in tables:
                own_soil_absence.append(
                    "NOT EXISTS (SELECT 1 FROM main.soil_categorical_preference own_cat "
                    "WHERE own_cat.taxon_id=child.taxon_id)"
                )
            fallback_guard = " AND ".join(own_soil_absence) or "1=1"
            unique_parent = """
                SELECT scientific_name,MIN(taxon_id) AS taxon_id
                FROM main.plant_index
                GROUP BY scientific_name
                HAVING COUNT(*)=1
            """
            if "soil_envelope" in tables:
                conn.execute(
                    f"""
                    INSERT INTO soil_component(taxon_id,weight,score)
                    SELECT child.taxon_id,s.weight,{soil_numeric_score}
                    FROM eligible child
                    JOIN main.plant_index child_index ON child_index.taxon_id=child.taxon_id
                    JOIN ({unique_parent}) parent
                      ON parent.scientific_name=
                         climaflora_parent_species_name(child_index.scientific_name)
                    JOIN main.soil_envelope s ON s.taxon_id=parent.taxon_id
                    WHERE {fallback_guard}
                    """,
                    soil_params,
                )
            if "soil_categorical_preference" in tables:
                conn.execute(
                    f"""
                    INSERT INTO soil_component(taxon_id,weight,score)
                    SELECT child.taxon_id,s.weight,
                           CASE WHEN ({cat_value}) IS NULL THEN NULL
                                WHEN EXISTS (
                                    SELECT 1 FROM json_each(COALESCE(s.optimum_values_json,'[]')) j
                                    WHERE LOWER(TRIM(CAST(j.value AS TEXT)))=
                                          LOWER(TRIM(CAST(({cat_value}) AS TEXT)))
                                ) THEN 100.0
                                WHEN EXISTS (
                                    SELECT 1 FROM json_each(COALESCE(s.accepted_values_json,'[]')) j
                                    WHERE LOWER(TRIM(CAST(j.value AS TEXT)))=
                                          LOWER(TRIM(CAST(({cat_value}) AS TEXT)))
                                ) THEN 65.0
                                ELSE 0.0 END
                    FROM eligible child
                    JOIN main.plant_index child_index ON child_index.taxon_id=child.taxon_id
                    JOIN ({unique_parent}) parent
                      ON parent.scientific_name=
                         climaflora_parent_species_name(child_index.scientific_name)
                    JOIN main.soil_categorical_preference s ON s.taxon_id=parent.taxon_id
                    WHERE {fallback_guard}
                    """,
                    cat_params,
                )
            conn.execute("CREATE INDEX temp.idx_soil_component_taxon ON soil_component(taxon_id)")
            conn.execute(
                """
                CREATE TEMP TABLE soil_score AS
                SELECT x.taxon_id,
                       COUNT(CASE WHEN sc.score IS NOT NULL THEN 1 END) AS known_components,
                       CASE WHEN COALESCE(SUM(CASE WHEN sc.weight>0 THEN sc.weight ELSE 0 END),0)>0
                            THEN COALESCE(SUM(CASE WHEN sc.score IS NOT NULL THEN sc.weight ELSE 0 END),0) /
                                 SUM(CASE WHEN sc.weight>0 THEN sc.weight ELSE 0 END)
                            ELSE 0.0 END AS known_fraction,
                       CASE WHEN COALESCE(SUM(CASE WHEN sc.score IS NOT NULL THEN sc.weight ELSE 0 END),0)>0
                            THEN SUM(COALESCE(sc.score,0)*sc.weight) /
                                 SUM(CASE WHEN sc.score IS NOT NULL THEN sc.weight ELSE 0 END)
                            ELSE NULL END AS soil_score
                FROM eligible x LEFT JOIN soil_component sc ON sc.taxon_id=x.taxon_id
                GROUP BY x.taxon_id
                """
            )
            conn.execute(
                """
                CREATE TEMP TABLE soil_rank AS
                SELECT taxon_id,known_components,known_fraction,soil_score,
                       CASE WHEN soil_score IS NULL OR known_fraction<:min_known OR known_components<2 THEN 'UNKNOWN'
                            WHEN soil_score>=75 THEN 'GREEN'
                            WHEN soil_score>=40 THEN 'ORANGE'
                            ELSE 'RED' END AS soil_status
                FROM soil_score
                """,
                {"min_known": float(min_known_weight)},
            )
            conn.execute("CREATE UNIQUE INDEX temp.idx_soil_rank_taxon ON soil_rank(taxon_id)")
            soil_status_counts = {
                row["soil_status"]: int(row["n"])
                for row in conn.execute(
                    "SELECT soil_status,COUNT(*) AS n FROM soil_rank GROUP BY soil_status"
                )
            }

            conn.execute(
                """
                CREATE TEMP TABLE ranked AS
                SELECT c.taxon_id,c.overall_score,c.climate_status,c.climate_centrality,
                       s.soil_score,s.soil_status,
                       CASE WHEN c.overall_score IS NULL THEN s.soil_score
                            WHEN s.soil_score IS NULL OR s.soil_status='UNKNOWN' THEN c.overall_score
                            ELSE 0.75*c.overall_score+0.25*s.soil_score END AS combined_score,
                       CASE WHEN c.climate_status='RED' THEN 'RED'
                            WHEN c.climate_status='UNKNOWN' THEN 'UNKNOWN'
                            WHEN (CASE WHEN s.soil_score IS NULL OR s.soil_status='UNKNOWN' THEN c.overall_score
                                       ELSE 0.75*c.overall_score+0.25*s.soil_score END)>=75 THEN 'GREEN'
                            WHEN (CASE WHEN s.soil_score IS NULL OR s.soil_status='UNKNOWN' THEN c.overall_score
                                       ELSE 0.75*c.overall_score+0.25*s.soil_score END)>=40 THEN 'ORANGE'
                            ELSE 'RED' END AS combined_status
                FROM climate_rank c JOIN soil_rank s ON s.taxon_id=c.taxon_id
                """
            )
            conn.execute("CREATE UNIQUE INDEX temp.idx_ranked_taxon ON ranked(taxon_id)")

            ranked_rows = tuple(
                (str(row[0]), str(row[1]), str(row[2]))
                for row in conn.execute(
                    """
                    SELECT taxon_id,climate_status,soil_status FROM ranked
                    ORDER BY
                        CASE climate_status WHEN 'GREEN' THEN 0 WHEN 'ORANGE' THEN 0 WHEN 'UNKNOWN' THEN 1 ELSE 2 END,
                        CASE combined_status WHEN 'GREEN' THEN 0 WHEN 'ORANGE' THEN 1 WHEN 'UNKNOWN' THEN 2 ELSE 3 END,
                        combined_score DESC,
                        overall_score DESC,
                        climate_centrality DESC,
                        taxon_id ASC
                    """
                )
            )
            metrics = {
                "catalog_total": catalog_total,
                "after_type": after_type,
                "after_function": after_function,
                "evaluated_candidates": after_function,
                # This base value is overwritten after presentation filtering.
                "total_results": len(ranked_rows),
            }
            facets = {
                "life_form": {key: int(life_counts.get(key, 0)) for key in LIFE_FORM_VALUES},
                "functions": function_counts,
                "climate_status": {
                    key: int(climate_status_counts.get(key, 0)) for key in STATUS_VALUES
                },
                "soil_status": {
                    key: int(soil_status_counts.get(key, 0)) for key in STATUS_VALUES
                },
            }
            token = key[:20]
            snapshot = SearchSnapshot(monotonic(), ranked_rows, metrics, facets, token)
            _CACHE.put(key, snapshot)
        finally:
            conn.close()

    # Status selections are cheap presentation masks over the already-scored
    # population. A status-only UI change therefore reuses the same snapshot.
    filtered_ids = tuple(
        taxon_id
        for taxon_id, climate_status, soil_status in snapshot.ranked_rows
        if climate_status in normalized_statuses and soil_status in normalized_soil_statuses
    )
    page_ids = filtered_ids[offset : offset + limit]
    candidates = _hydrate_page(db_path, page_ids)
    total = len(filtered_ids)
    metrics = dict(snapshot.metrics)
    metrics["total_results"] = total
    return {
        "candidates": candidates,
        "metrics": metrics,
        "facets": dict(snapshot.facets),
        "pagination": {
            "offset": offset,
            "limit": limit,
            "returned": len(candidates),
            "has_previous": offset > 0,
            "has_next": offset + len(candidates) < total,
        },
        "search_token": snapshot.token,
        "cache_hit": cache_hit,
    }
