from __future__ import annotations

from functools import lru_cache
import hashlib
import os
from pathlib import Path
import sqlite3
from threading import RLock


HERBACEOUS_TOKENS = (
    "herb",
    "forb",
    "graminoid",
    "grass",
    "herbac",
    "annual",
    "biennial",
    "perennial",
    "geophyte",
    "epiphyte",
    "lithophyte",
    "helophyte",
    "hydrophyte",
    "bamboo",
    "parasite",
    "mycotroph",
)
CLIMBER_TOKENS = ("climb", "liana", "vine", "grimp", "scrambl", "scandent")
SHRUB_TOKENS = ("shrub", "subshrub", "bush", "arbust")
TREE_TOKENS = ("tree", "arbores", "arbre")
PALM_TOKENS = ("palm", "palmae", "palmier")

_CACHE_FORMAT_VERSION = "funnel-metadata-v3"
_SIDECAR_LOCK = RLock()


def _contains(expr: str, tokens: tuple[str, ...]) -> str:
    return "(" + " OR ".join(f"{expr} LIKE '%{token}%'" for token in tokens) + ")"


def _catalog_path_from_connection(conn: sqlite3.Connection) -> Path:
    for _, name, filename in conn.execute("PRAGMA database_list"):
        if name == "main" and filename:
            return Path(str(filename)).resolve()
    raise RuntimeError("Unable to resolve ClimaFlora catalog path from SQLite connection")


def _sidecar_path(db_path: Path) -> Path:
    stat = db_path.stat()
    raw = (
        f"{db_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{_CACHE_FORMAT_VERSION}"
    ).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    cache_root = Path(os.environ.get("CLIMAFLORA_FUNNEL_CACHE_DIR", "/tmp"))
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root / f"climaflora-funnel-{digest}.sqlite"


def _sidecar_valid(sidecar: Path, db_path: Path) -> bool:
    if not sidecar.exists():
        return False
    stat = db_path.stat()
    try:
        with sqlite3.connect(f"file:{sidecar.resolve()}?mode=ro", uri=True) as conn:
            meta = dict(conn.execute("SELECT key,value FROM metadata"))
            if meta.get("format_version") != _CACHE_FORMAT_VERSION:
                return False
            if int(meta.get("catalog_size", "-1")) != stat.st_size:
                return False
            if int(meta.get("catalog_mtime_ns", "-1")) != stat.st_mtime_ns:
                return False
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            if conn.execute("SELECT COUNT(*) FROM life_category").fetchone()[0] <= 0:
                return False
        return True
    except (sqlite3.Error, OSError, ValueError):
        return False


def _build_sidecar(db_path: Path, target: Path) -> None:
    stat = db_path.stat()
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    source_uri = f"file:{db_path.resolve()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    source.row_factory = sqlite3.Row
    try:
        source.execute("PRAGMA temp_store=MEMORY")
        tables = {
            str(row[0])
            for row in source.execute(
                "SELECT name FROM main.sqlite_master WHERE type='table'"
            )
        }
        source.execute(
            "CREATE TEMP TABLE life_lookup(taxon_id TEXT PRIMARY KEY, life_value TEXT NOT NULL)"
        )
        if "plant_profile" in tables:
            source.execute(
                """
                INSERT OR REPLACE INTO life_lookup(taxon_id,life_value)
                SELECT taxon_id,TRIM(life_form)
                FROM main.plant_profile
                WHERE TRIM(COALESCE(life_form,''))<>''
                """
            )
        if "plant_trait_evidence" in tables:
            source.execute(
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

        source.execute("ATTACH DATABASE ? AS funnel_build", (str(tmp),))
        source.execute(
            "CREATE TABLE funnel_build.metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)"
        )
        source.executemany(
            "INSERT INTO funnel_build.metadata(key,value) VALUES(?,?)",
            (
                ("format_version", _CACHE_FORMAT_VERSION),
                ("catalog_size", str(stat.st_size)),
                ("catalog_mtime_ns", str(stat.st_mtime_ns)),
            ),
        )

        value = "LOWER(COALESCE(ll.life_value,''))"
        textual_palm = _contains(value, PALM_TOKENS)
        family_palm = (
            "EXISTS (SELECT 1 FROM main.plant_profile pp "
            "WHERE pp.taxon_id=p.taxon_id AND LOWER(TRIM(COALESCE(pp.family,'')))='arecaceae')"
            if "plant_profile" in tables
            else "0"
        )
        palm = f"({family_palm} OR {textual_palm})"
        climber = _contains(value, CLIMBER_TOKENS)
        shrub = _contains(value, SHRUB_TOKENS)
        tree = _contains(value, TREE_TOKENS)
        herb = _contains(value, HERBACEOUS_TOKENS)
        source.execute(
            f"""
            CREATE TABLE funnel_build.life_category AS
            SELECT p.taxon_id,
                   CASE
                     WHEN {palm} THEN 'PALM'
                     WHEN ll.life_value IS NULL OR TRIM(ll.life_value)='' THEN 'UNKNOWN'
                     WHEN {climber} THEN 'CLIMBER'
                     WHEN {shrub} THEN 'SHRUB'
                     WHEN {tree} THEN 'TREE'
                     WHEN {herb} THEN 'HERB'
                     ELSE 'OTHER'
                   END AS category
            FROM main.plant_index p
            LEFT JOIN life_lookup ll ON ll.taxon_id=p.taxon_id
            """
        )
        source.execute(
            "CREATE UNIQUE INDEX funnel_build.idx_life_category_taxon "
            "ON life_category(taxon_id)"
        )
        source.execute(
            "CREATE INDEX funnel_build.idx_life_category_value "
            "ON life_category(category)"
        )
        source.execute(
            """
            CREATE TABLE funnel_build.life_counts AS
            SELECT category,COUNT(*) AS n
            FROM funnel_build.life_category
            GROUP BY category
            """
        )
        source.execute(
            "CREATE UNIQUE INDEX funnel_build.idx_life_counts_category "
            "ON life_counts(category)"
        )
        source.execute(
            """
            CREATE TABLE funnel_build.function_counts AS
            SELECT lc.category AS category,
                   CAST(jf.value AS TEXT) AS code,
                   COUNT(DISTINCT p.taxon_id) AS n
            FROM main.plant_index p
            JOIN funnel_build.life_category lc ON lc.taxon_id=p.taxon_id,
                 json_each(COALESCE(p.functions_json,'[]')) jf
            GROUP BY lc.category,jf.value
            """
        )
        source.execute(
            """
            INSERT INTO funnel_build.function_counts(category,code,n)
            SELECT 'ALL',
                   CAST(jf.value AS TEXT) AS code,
                   COUNT(DISTINCT p.taxon_id) AS n
            FROM main.plant_index p,
                 json_each(COALESCE(p.functions_json,'[]')) jf
            GROUP BY jf.value
            """
        )
        source.execute(
            "CREATE UNIQUE INDEX funnel_build.idx_function_counts "
            "ON function_counts(category,code)"
        )
        source.commit()
        source.execute("DETACH DATABASE funnel_build")
    finally:
        source.close()

    with sqlite3.connect(str(tmp)) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            tmp.unlink(missing_ok=True)
            raise RuntimeError("ClimaFlora funnel sidecar failed integrity_check")
    os.replace(tmp, target)


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


def _ensure_sidecar(path: str | Path) -> Path:
    db_path = Path(path).resolve()
    stat = db_path.stat()
    return Path(
        _ensure_sidecar_cached(
            str(db_path),
            stat.st_size,
            stat.st_mtime_ns,
        )
    )


def warm_funnel_metadata(path: str | Path) -> Path:
    """Materialize static Type/Function navigation metadata before user queries."""
    return _ensure_sidecar(path)


def _attach_sidecar(conn: sqlite3.Connection, sidecar: Path) -> None:
    attached = {str(row[1]): str(row[2]) for row in conn.execute("PRAGMA database_list")}
    if "funnel_cache" not in attached:
        conn.execute("ATTACH DATABASE ? AS funnel_cache", (str(sidecar),))
    conn.execute("DROP VIEW IF EXISTS temp.life_category")
    conn.execute(
        "CREATE TEMP VIEW life_category AS "
        "SELECT taxon_id,category FROM funnel_cache.life_category"
    )


def _prepare_life_categories_direct(conn: sqlite3.Connection, tables: set[str]) -> None:
    """Fallback used only if the reusable sidecar cannot be built."""
    conn.execute(
        "CREATE TEMP TABLE life_lookup(taxon_id TEXT PRIMARY KEY, life_value TEXT NOT NULL)"
    )
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

    value = "LOWER(COALESCE(ll.life_value,''))"
    textual_palm = _contains(value, PALM_TOKENS)
    family_palm = (
        "EXISTS (SELECT 1 FROM main.plant_profile pp "
        "WHERE pp.taxon_id=p.taxon_id AND LOWER(TRIM(COALESCE(pp.family,'')))='arecaceae')"
        if "plant_profile" in tables
        else "0"
    )
    palm = f"({family_palm} OR {textual_palm})"
    climber = _contains(value, CLIMBER_TOKENS)
    shrub = _contains(value, SHRUB_TOKENS)
    tree = _contains(value, TREE_TOKENS)
    herb = _contains(value, HERBACEOUS_TOKENS)
    conn.execute(
        f"""
        CREATE TEMP TABLE life_category AS
        SELECT p.taxon_id,
               CASE
                 WHEN {palm} THEN 'PALM'
                 WHEN ll.life_value IS NULL OR TRIM(ll.life_value)='' THEN 'UNKNOWN'
                 WHEN {climber} THEN 'CLIMBER'
                 WHEN {shrub} THEN 'SHRUB'
                 WHEN {tree} THEN 'TREE'
                 WHEN {herb} THEN 'HERB'
                 ELSE 'OTHER'
               END AS category
        FROM main.plant_index p
        LEFT JOIN life_lookup ll ON ll.taxon_id=p.taxon_id
        """
    )
    conn.execute("CREATE UNIQUE INDEX temp.idx_life_category_taxon ON life_category(taxon_id)")
    conn.execute("CREATE INDEX temp.idx_life_category_value ON life_category(category)")


def prepare_life_categories(conn: sqlite3.Connection, tables: set[str]) -> None:
    """Expose cached life-form categories to one exhaustive-search connection."""
    try:
        sidecar = _ensure_sidecar(_catalog_path_from_connection(conn))
        _attach_sidecar(conn, sidecar)
    except (OSError, sqlite3.Error, RuntimeError, ValueError):
        _prepare_life_categories_direct(conn, tables)


def canonical_function_predicate(
    tables: set[str], alias: str, functions: tuple[str, ...], params: dict
) -> str:
    """Filter on public canonical function codes stored in functions_json."""
    del tables
    if not functions:
        return "1=1"
    clauses = []
    for index, function in enumerate(functions):
        key = f"function_{index}"
        params[key] = function
        clauses.append(
            f"EXISTS (SELECT 1 FROM json_each(COALESCE({alias}.functions_json,'[]')) jf "
            f"WHERE jf.value=:{key})"
        )
    return " AND ".join(clauses)


def install_exhaustive_metadata_patch() -> None:
    """Install deterministic metadata helpers in the exhaustive search module."""
    from app.services import exhaustive_search as module

    module._prepare_life_categories = prepare_life_categories
    module._function_predicate = canonical_function_predicate


@lru_cache(maxsize=64)
def _canonical_function_counts_cached(
    path: str,
    size: int,
    mtime_ns: int,
    life_form: str,
) -> tuple[tuple[str, int], ...]:
    del size, mtime_ns
    sidecar = _ensure_sidecar(path)
    category = life_form if life_form != "ALL" else "ALL"
    with sqlite3.connect(f"file:{sidecar.resolve()}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            """
            SELECT code,n
            FROM function_counts
            WHERE category=?
            ORDER BY n DESC,code ASC
            """,
            (category,),
        ).fetchall()
    return tuple((str(code), int(n)) for code, n in rows)


def canonical_function_counts(path: str | Path, life_form: str) -> dict[str, int]:
    db_path = Path(path)
    if not db_path.exists():
        return {}
    normalized = str(life_form or "ALL").upper()
    stat = db_path.stat()
    return dict(
        _canonical_function_counts_cached(
            str(db_path.resolve()),
            stat.st_size,
            stat.st_mtime_ns,
            normalized,
        )
    )
