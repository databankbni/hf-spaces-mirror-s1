from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from threading import RLock

from app.services.funnel_metadata import warm_funnel_metadata
from app.services.media_taxonomy import parent_species_name
from app.version import SEARCH_RUNTIME_FORMAT_VERSION

SIDECAR_FORMAT_VERSION = "search-runtime-sidecar-v3"
CLIMATE_VARIABLES = ("bio01", "bio05", "bio06", "bio12", "bio15")
CLIMATE_GROUPS = {"bio01": "V", "bio05": "M", "bio06": "M", "bio12": "E", "bio15": "E"}
CLIMATE_WEIGHTS = {"bio01": 1.0, "bio05": 1.0, "bio06": 1.2, "bio12": 0.8, "bio15": 0.7}
CLIMATE_FIELDS = ("hard_low", "optimum_low", "optimum_high", "hard_high", "weight", "fatal")
LIFE_MASKS = {
    "TREE": 1 << 0,
    "SHRUB": 1 << 1,
    "HERB": 1 << 2,
    "CLIMBER": 1 << 3,
    "PALM": 1 << 4,
    "OTHER": 1 << 5,
    "UNKNOWN": 1 << 6,
}
_MAX_FUNCTION_BITS = 63
_SIDECAR_LOCK = RLock()


def _catalog_identity(db_path: Path) -> dict[str, str | int]:
    stat = db_path.stat()
    return {
        "catalog_path": str(db_path.resolve()),
        "catalog_size": stat.st_size,
        "catalog_mtime_ns": stat.st_mtime_ns,
    }


def _sidecar_path(db_path: Path) -> Path:
    identity = _catalog_identity(db_path)
    raw = json.dumps(
        {
            **identity,
            "sidecar_format": SIDECAR_FORMAT_VERSION,
            "runtime_format": SEARCH_RUNTIME_FORMAT_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:20]
    cache_root = Path(os.environ.get("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", "/tmp"))
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root / f"climaflora-search-runtime-{digest}.sqlite"


def _function_codes(source: sqlite3.Connection) -> list[str]:
    codes = [
        str(row[0])
        for row in source.execute(
            """
            SELECT DISTINCT CAST(jf.value AS TEXT) AS code
            FROM main.plant_index p,
                 json_each(COALESCE(p.functions_json,'[]')) jf
            WHERE TRIM(CAST(jf.value AS TEXT))<>''
            ORDER BY code
            """
        )
    ]
    if len(codes) > _MAX_FUNCTION_BITS:
        raise RuntimeError(
            f"Search runtime function mask supports at most {_MAX_FUNCTION_BITS} canonical codes; found {len(codes)}"
        )
    return codes


def _function_code_digest(codes: list[str]) -> str:
    return hashlib.sha256("\0".join(codes).encode("utf-8")).hexdigest()


def _life_mask_case(alias: str = "lc") -> str:
    clauses = " ".join(
        f"WHEN '{category}' THEN {mask}"
        for category, mask in LIFE_MASKS.items()
    )
    return f"CASE {alias}.category {clauses} ELSE {LIFE_MASKS['UNKNOWN']} END"


def _climate_audit(source: sqlite3.Connection) -> dict[str, int]:
    tables = {str(row[0]) for row in source.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
    if "climate_envelope" not in tables:
        raise RuntimeError("Search runtime sidecar requires climate_envelope")

    variable_marks = ",".join("?" for _ in CLIMATE_VARIABLES)
    duplicate = source.execute(
        f"""
        SELECT taxon_id,variable,COUNT(*) AS n
        FROM main.climate_envelope
        WHERE variable IN ({variable_marks})
        GROUP BY taxon_id,variable
        HAVING COUNT(*)<>1
        LIMIT 1
        """,
        CLIMATE_VARIABLES,
    ).fetchone()
    if duplicate is not None:
        raise RuntimeError(
            "Search runtime climate projection requires exactly one scoring envelope per taxon/variable; "
            f"found taxon={duplicate[0]} variable={duplicate[1]} rows={duplicate[2]}"
        )

    for variable in CLIMATE_VARIABLES:
        rows = source.execute(
            """
            SELECT DISTINCT COALESCE(group_code,''),weight
            FROM main.climate_envelope
            WHERE variable=?
            """,
            (variable,),
        ).fetchall()
        if not rows:
            raise RuntimeError(f"Search runtime climate projection missing variable {variable}")
        for group_code, weight in rows:
            if str(group_code) != CLIMATE_GROUPS[variable]:
                raise RuntimeError(
                    f"Unexpected group for {variable}: {group_code!r} != {CLIMATE_GROUPS[variable]!r}"
                )
            if weight is None or not math.isclose(float(weight), CLIMATE_WEIGHTS[variable], rel_tol=0.0, abs_tol=1e-12):
                raise RuntimeError(
                    f"Unexpected weight for {variable}: {weight!r} != {CLIMATE_WEIGHTS[variable]!r}"
                )

    envelope_rows = int(
        source.execute(
            f"SELECT COUNT(*) FROM main.climate_envelope WHERE variable IN ({variable_marks})",
            CLIMATE_VARIABLES,
        ).fetchone()[0]
    )
    envelope_taxa = int(
        source.execute(
            f"SELECT COUNT(DISTINCT taxon_id) FROM main.climate_envelope WHERE variable IN ({variable_marks})",
            CLIMATE_VARIABLES,
        ).fetchone()[0]
    )
    return {"rows": envelope_rows, "taxa": envelope_taxa}


def _climate_wide_columns() -> list[str]:
    columns: list[str] = []
    for variable in CLIMATE_VARIABLES:
        for field in CLIMATE_FIELDS:
            columns.append(
                f"MAX(CASE WHEN e.variable='{variable}' THEN e.{field} END) AS {variable}_{field}"
            )
    return columns


def _build_sidecar(db_path: Path, target: Path) -> None:
    funnel_sidecar = warm_funnel_metadata(db_path)
    identity = _catalog_identity(db_path)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)

    source = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    source.create_function(
        "climaflora_parent_species_name",
        1,
        parent_species_name,
        deterministic=True,
    )
    try:
        source.execute("PRAGMA temp_store=MEMORY")
        source.execute("ATTACH DATABASE ? AS funnel_cache", (str(funnel_sidecar),))
        source.execute("ATTACH DATABASE ? AS runtime_build", (str(tmp),))

        codes = _function_codes(source)
        climate_audit = _climate_audit(source)
        catalog_taxa = int(source.execute("SELECT COUNT(*) FROM main.plant_index").fetchone()[0])

        source.execute(
            "CREATE TABLE runtime_build.metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        metadata = {
            "format_version": SIDECAR_FORMAT_VERSION,
            "runtime_format_version": SEARCH_RUNTIME_FORMAT_VERSION,
            "catalog_path": identity["catalog_path"],
            "catalog_size": str(identity["catalog_size"]),
            "catalog_mtime_ns": str(identity["catalog_mtime_ns"]),
            "catalog_taxa": str(catalog_taxa),
            "ordinal_order": "taxon_id_asc_text",
            "life_mask_mapping": json.dumps(LIFE_MASKS, sort_keys=True, separators=(",", ":")),
            "function_code_count": str(len(codes)),
            "function_code_sha256": _function_code_digest(codes),
            "climate_variables": json.dumps(CLIMATE_VARIABLES, separators=(",", ":")),
            "climate_group_mapping": json.dumps(CLIMATE_GROUPS, sort_keys=True, separators=(",", ":")),
            "climate_weight_mapping": json.dumps(CLIMATE_WEIGHTS, sort_keys=True, separators=(",", ":")),
            "climate_envelope_rows": str(climate_audit["rows"]),
            "climate_envelope_taxa": str(climate_audit["taxa"]),
            "climate_projection_layout": "wide_float64_sqlite_real_v1",
        }
        source.executemany(
            "INSERT INTO runtime_build.metadata(key,value) VALUES(?,?)",
            tuple(metadata.items()),
        )

        source.execute(
            "CREATE TABLE runtime_build.function_code(code TEXT PRIMARY KEY,bit_index INTEGER NOT NULL UNIQUE)"
        )
        source.executemany(
            "INSERT INTO runtime_build.function_code(code,bit_index) VALUES(?,?)",
            tuple((code, index) for index, code in enumerate(codes)),
        )

        life_mask = _life_mask_case("lc")
        source.execute(
            f"""
            CREATE TABLE runtime_build.taxon_runtime AS
            WITH unique_scientific_name AS (
                SELECT scientific_name,MIN(taxon_id) AS taxon_id
                FROM main.plant_index
                GROUP BY scientific_name
                HAVING COUNT(*)=1
            )
            SELECT p.taxon_id AS taxon_id,
                   ROW_NUMBER() OVER (ORDER BY p.taxon_id) - 1 AS ordinal,
                   lc.category AS life_category,
                   {life_mask} AS life_mask,
                   0 AS function_mask,
                   parent.taxon_id AS parent_species_taxon_id
            FROM main.plant_index p
            JOIN funnel_cache.life_category lc ON lc.taxon_id=p.taxon_id
            LEFT JOIN unique_scientific_name parent
              ON parent.scientific_name=climaflora_parent_species_name(p.scientific_name)
            ORDER BY p.taxon_id
            """
        )
        source.execute(
            "CREATE UNIQUE INDEX runtime_build.idx_taxon_runtime_taxon ON taxon_runtime(taxon_id)"
        )
        source.execute(
            "CREATE UNIQUE INDEX runtime_build.idx_taxon_runtime_ordinal ON taxon_runtime(ordinal)"
        )
        source.execute(
            "CREATE INDEX runtime_build.idx_taxon_runtime_life ON taxon_runtime(life_category)"
        )

        for bit_index, code in enumerate(codes):
            bit = 1 << bit_index
            source.execute(
                """
                UPDATE runtime_build.taxon_runtime
                SET function_mask = function_mask | ?
                WHERE taxon_id IN (
                    SELECT p.taxon_id
                    FROM main.plant_index p,
                         json_each(COALESCE(p.functions_json,'[]')) jf
                    WHERE CAST(jf.value AS TEXT)=?
                )
                """,
                (bit, code),
            )

        wide_columns = ",\n                   ".join(_climate_wide_columns())
        source.execute(
            f"""
            CREATE TABLE runtime_build.climate_runtime_wide AS
            SELECT tr.ordinal AS ordinal,
                   tr.taxon_id AS taxon_id,
                   {wide_columns}
            FROM runtime_build.taxon_runtime tr
            LEFT JOIN main.climate_envelope e
              ON e.taxon_id=tr.taxon_id
             AND e.variable IN ('bio01','bio05','bio06','bio12','bio15')
            GROUP BY tr.ordinal,tr.taxon_id
            ORDER BY tr.ordinal
            """
        )
        source.execute(
            "CREATE UNIQUE INDEX runtime_build.idx_climate_runtime_wide_ordinal ON climate_runtime_wide(ordinal)"
        )
        source.execute(
            "CREATE UNIQUE INDEX runtime_build.idx_climate_runtime_wide_taxon ON climate_runtime_wide(taxon_id)"
        )

        source.commit()
        source.execute("DETACH DATABASE runtime_build")
        source.execute("DETACH DATABASE funnel_cache")
    finally:
        source.close()

    with sqlite3.connect(str(tmp)) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            tmp.unlink(missing_ok=True)
            raise RuntimeError("ClimaFlora search runtime sidecar failed integrity_check")
        meta = dict(check.execute("SELECT key,value FROM metadata"))
        expected_taxa = int(meta["catalog_taxa"])
        row = check.execute(
            "SELECT COUNT(*),COUNT(DISTINCT ordinal),MIN(ordinal),MAX(ordinal),SUM(CASE WHEN life_mask<=0 THEN 1 ELSE 0 END) FROM taxon_runtime"
        ).fetchone()
        count, ordinal_count, minimum, maximum, invalid_life = (int(v or 0) for v in row)
        if count != expected_taxa or ordinal_count != expected_taxa:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("ClimaFlora search runtime sidecar ordinal coverage mismatch")
        if expected_taxa and (minimum != 0 or maximum != expected_taxa - 1):
            tmp.unlink(missing_ok=True)
            raise RuntimeError("ClimaFlora search runtime sidecar ordinal range mismatch")
        if invalid_life:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("ClimaFlora search runtime sidecar contains invalid life masks")

        wide_count, wide_ordinals = check.execute(
            "SELECT COUNT(*),COUNT(DISTINCT ordinal) FROM climate_runtime_wide"
        ).fetchone()
        if int(wide_count) != expected_taxa or int(wide_ordinals) != expected_taxa:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("ClimaFlora search runtime climate-wide coverage mismatch")
        mismatch = check.execute(
            """
            SELECT 1
            FROM climate_runtime_wide cw
            JOIN taxon_runtime tr ON tr.ordinal=cw.ordinal
            WHERE cw.taxon_id<>tr.taxon_id
            LIMIT 1
            """
        ).fetchone()
        if mismatch is not None:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("ClimaFlora search runtime wide projection ordinal mismatch")

    os.replace(tmp, target)


def _sidecar_valid(sidecar: Path, db_path: Path) -> bool:
    if not sidecar.exists():
        return False
    identity = _catalog_identity(db_path)
    try:
        with sqlite3.connect(f"file:{sidecar.resolve()}?mode=ro", uri=True) as conn:
            meta = dict(conn.execute("SELECT key,value FROM metadata"))
            if meta.get("format_version") != SIDECAR_FORMAT_VERSION:
                return False
            if meta.get("runtime_format_version") != SEARCH_RUNTIME_FORMAT_VERSION:
                return False
            if int(meta.get("catalog_size", "-1")) != int(identity["catalog_size"]):
                return False
            if int(meta.get("catalog_mtime_ns", "-1")) != int(identity["catalog_mtime_ns"]):
                return False
            taxa = int(meta.get("catalog_taxa", "-1"))
            if conn.execute("SELECT COUNT(*) FROM taxon_runtime").fetchone()[0] != taxa:
                return False
            if conn.execute("SELECT COUNT(*) FROM climate_runtime_wide").fetchone()[0] != taxa:
                return False
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
        return True
    except (sqlite3.Error, OSError, ValueError, KeyError):
        return False


@lru_cache(maxsize=8)
def _ensure_sidecar_cached(path: str, size: int, mtime_ns: int) -> str:
    del size, mtime_ns
    db_path = Path(path)
    sidecar = _sidecar_path(db_path)
    if _sidecar_valid(sidecar, db_path):
        return str(sidecar)
    with _SIDECAR_LOCK:
        if not _sidecar_valid(sidecar, db_path):
            _build_sidecar(db_path, sidecar)
    return str(sidecar)


def warm_search_runtime_sidecar(path: str | Path) -> Path:
    db_path = Path(path).resolve()
    stat = db_path.stat()
    return Path(_ensure_sidecar_cached(str(db_path), stat.st_size, stat.st_mtime_ns))


def search_runtime_sidecar_summary(path: str | Path) -> dict[str, object]:
    sidecar = warm_search_runtime_sidecar(path)
    with sqlite3.connect(f"file:{sidecar.resolve()}?mode=ro", uri=True) as conn:
        meta = dict(conn.execute("SELECT key,value FROM metadata"))
        return {
            "path": str(sidecar),
            "bytes": sidecar.stat().st_size,
            "format_version": meta["format_version"],
            "runtime_format_version": meta["runtime_format_version"],
            "catalog_taxa": int(meta["catalog_taxa"]),
            "function_code_count": int(meta["function_code_count"]),
            "function_code_sha256": meta["function_code_sha256"],
            "ordinal_order": meta["ordinal_order"],
            "climate_envelope_rows": int(meta["climate_envelope_rows"]),
            "climate_envelope_taxa": int(meta["climate_envelope_taxa"]),
            "climate_projection_layout": meta["climate_projection_layout"],
            "climate_wide_rows": int(conn.execute("SELECT COUNT(*) FROM climate_runtime_wide").fetchone()[0]),
        }
