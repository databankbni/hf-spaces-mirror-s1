from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.plants import DerivedSqlitePlantRepository, PlantRepository

LIFE_FORM_CATEGORIES = {"TREE", "SHRUB", "HERB", "CLIMBER", "PALM", "OTHER"}


def _effective_life_form_expr(tables: set[str], plant_alias: str = "p") -> str:
    """Return the SQL expression matching the documented life-form precedence.

    plant_profile is authoritative when present and non-empty. Otherwise the
    highest-confidence life_form trait evidence is used, matching the public
    enrichment endpoint. No taxonomic inference or fuzzy matching is performed.
    """
    trait_expr = "NULL"
    if "plant_trait_evidence" in tables:
        trait_expr = f"""(
            SELECT pte.trait_value
            FROM main.plant_trait_evidence pte
            WHERE pte.taxon_id={plant_alias}.taxon_id
              AND pte.trait_name='life_form'
              AND TRIM(COALESCE(pte.trait_value,''))<>''
            ORDER BY pte.confidence DESC, pte.source_id
            LIMIT 1
        )"""

    profile_expr = "NULL"
    if "plant_profile" in tables:
        profile_expr = f"""(
            SELECT pp.life_form
            FROM main.plant_profile pp
            WHERE pp.taxon_id={plant_alias}.taxon_id
              AND TRIM(COALESCE(pp.life_form,''))<>''
            LIMIT 1
        )"""

    if profile_expr != "NULL" and trait_expr != "NULL":
        return f"COALESCE(NULLIF(TRIM({profile_expr}),''), NULLIF(TRIM({trait_expr}),''))"
    if profile_expr != "NULL":
        return f"NULLIF(TRIM({profile_expr}),'')"
    if trait_expr != "NULL":
        return f"NULLIF(TRIM({trait_expr}),'')"
    return "NULL"


def _contains(expr: str, tokens: tuple[str, ...]) -> str:
    return "(" + " OR ".join(f"{expr} LIKE '%{token}%'" for token in tokens) + ")"


def _life_form_condition(expr: str, category: str) -> str:
    """Translate the UI life-form classifier into deterministic SQL.

    The precedence is intentionally identical to _classify_life_form in the
    enrichment router: PALM, CLIMBER, SHRUB, TREE, HERB, then OTHER.
    """
    if category not in LIFE_FORM_CATEGORIES:
        raise ValueError(f"Unsupported life-form category: {category}")

    normalized = f"LOWER(COALESCE({expr},''))"
    palm = _contains(normalized, ("palm", "palmae", "palmier"))
    climber = _contains(normalized, ("climb", "liana", "vine", "grimp"))
    shrub = _contains(normalized, ("shrub", "bush", "arbust"))
    tree = _contains(normalized, ("tree", "arbores", "arbre"))
    herb = _contains(normalized, ("herb", "forb", "graminoid", "grass", "herbac"))

    if category == "PALM":
        return palm
    if category == "CLIMBER":
        return f"NOT {palm} AND {climber}"
    if category == "SHRUB":
        return f"NOT {palm} AND NOT {climber} AND {shrub}"
    if category == "TREE":
        return f"NOT {palm} AND NOT {climber} AND NOT {shrub} AND {tree}"
    if category == "HERB":
        return f"NOT {palm} AND NOT {climber} AND NOT {shrub} AND NOT {tree} AND {herb}"
    return (
        f"TRIM(COALESCE({expr},''))<>'' "
        f"AND NOT {palm} AND NOT {climber} AND NOT {shrub} AND NOT {tree} AND NOT {herb}"
    )


def iter_candidates_by_life_form(
    repository: PlantRepository,
    *,
    life_form: str,
    functions: list[str] | None,
    limit: int,
    climate_variables: dict | None,
    soil_variables: dict | None,
) -> tuple[list[dict], int]:
    """Build the rough candidate pool *after* filtering by documented life form.

    For the production SQLite repository, a TEMP view shadows plant_index and
    contains only taxa matching the requested documented life form. The existing
    climate/soil rough-ranking implementation is then reused unchanged, so the
    type filter is applied before top-climate/top-combined LIMIT clauses.

    Returns (ranked_hydrated_candidates, total_catalog_taxa_matching_life_form).
    Life form never enters any score; it only constrains the eligible set.
    """
    if life_form not in LIFE_FORM_CATEGORIES:
        raise ValueError(f"Unsupported life-form category: {life_form}")

    if not isinstance(repository, DerivedSqlitePlantRepository):
        # Production uses DerivedSqlitePlantRepository. A non-SQLite repository
        # cannot safely apply the full-catalog filter without inventing metadata.
        return [], 0

    path = Path(repository.path)
    if not path.exists():
        return [], 0

    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-16384")
        conn.execute("PRAGMA mmap_size=268435456")

        tables = {str(row[0]) for row in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
        expr = _effective_life_form_expr(tables, "p")
        condition = _life_form_condition(expr, life_form)

        # TEMP objects live outside the read-only main DB. Naming the view
        # plant_index intentionally shadows main.plant_index for the existing
        # ranking SQL, avoiding a second, divergent implementation of scoring.
        conn.execute(
            f"CREATE TEMP VIEW plant_index AS "
            f"SELECT p.* FROM main.plant_index p WHERE {condition}"
        )
        eligible_count = int(conn.execute("SELECT COUNT(*) FROM temp.plant_index").fetchone()[0])

        rows = repository._ranked_plant_rows(  # noqa: SLF001 - deliberate internal reuse
            conn,
            functions or [],
            max(1, int(limit)),
            climate_variables or {},
            soil_variables or {},
        )
        hydrated = repository._hydrate(conn, rows)  # noqa: SLF001 - same repository transaction
        return hydrated, eligible_count
