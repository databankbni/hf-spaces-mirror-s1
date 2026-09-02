import sqlite3

import numpy as np

from app.services.exhaustive_search import exhaustive_search
from app.services.plants import DerivedSqlitePlantRepository
from app.services.search_soil_vector import combine_score_vectors, score_soil_vector
from app.services.search_vector import load_climate_runtime_matrix, score_climate_vector


CLIMATE_FIXTURE = {
    "bio01": ("V", 1.0),
    "bio05": ("M", 1.0),
    "bio06": ("M", 1.2),
    "bio12": ("E", 0.8),
    "bio15": ("E", 0.7),
}


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE plant_index (
            taxon_id TEXT PRIMARY KEY,
            scientific_name TEXT NOT NULL,
            common_name TEXT,
            functions_json TEXT NOT NULL DEFAULT '[]',
            regulatory_veto INTEGER NOT NULL DEFAULT 0,
            regulatory_reason TEXT,
            confidence TEXT,
            powo_id TEXT,
            scientific_name_id TEXT,
            references_url TEXT
        );
        CREATE TABLE plant_profile (taxon_id TEXT PRIMARY KEY, family TEXT, life_form TEXT);
        CREATE TABLE climate_envelope (
            taxon_id TEXT NOT NULL, variable TEXT NOT NULL,
            hard_low REAL, optimum_low REAL, optimum_high REAL, hard_high REAL,
            weight REAL NOT NULL, group_code TEXT, fatal INTEGER NOT NULL DEFAULT 0,
            confidence TEXT, source_ref TEXT
        );
        CREATE TABLE soil_envelope (
            taxon_id TEXT NOT NULL, variable TEXT NOT NULL,
            hard_low REAL, optimum_low REAL, optimum_high REAL, hard_high REAL,
            weight REAL NOT NULL, group_code TEXT, fatal INTEGER NOT NULL DEFAULT 0,
            confidence TEXT, source_ref TEXT
        );
        CREATE TABLE soil_categorical_preference (
            taxon_id TEXT NOT NULL, variable TEXT NOT NULL,
            optimum_values_json TEXT NOT NULL, accepted_values_json TEXT NOT NULL,
            weight REAL NOT NULL, confidence TEXT, source_ref TEXT
        );
        CREATE TABLE evidence (
            taxon_id TEXT NOT NULL, claim_type TEXT, claim_value TEXT, source_id TEXT,
            source_reference TEXT, source_version TEXT, extraction_method TEXT,
            confidence TEXT, notes TEXT
        );
        """
    )


def _plant(
    conn: sqlite3.Connection,
    taxon_id: str,
    scientific_name: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO plant_index(taxon_id,scientific_name) VALUES(?,?)",
        (taxon_id, scientific_name or f"Plant {taxon_id}"),
    )
    conn.execute("INSERT INTO plant_profile VALUES(?,?,?)", (taxon_id, None, "tree"))
    for variable, (group, weight) in CLIMATE_FIXTURE.items():
        conn.execute(
            "INSERT INTO climate_envelope VALUES(?,?,0,10,20,40,?,?,0,'A','TEST')",
            (taxon_id, variable, weight, group),
        )


def _numeric_soil(
    conn: sqlite3.Connection,
    taxon_id: str,
    variable: str,
    hard_low: float,
    optimum_low: float,
    optimum_high: float,
    hard_high: float,
    weight: float = 1.0,
) -> None:
    conn.execute(
        "INSERT INTO soil_envelope VALUES(?,?,?,?,?,?,?,?,0,'A','TEST')",
        (taxon_id, variable, hard_low, optimum_low, optimum_high, hard_high, weight, "E"),
    )


def _categorical_soil(
    conn: sqlite3.Connection,
    taxon_id: str,
    variable: str,
    optimum: str,
    accepted: str,
    weight: float = 1.0,
) -> None:
    conn.execute(
        "INSERT INTO soil_categorical_preference VALUES(?,?,?,?,?,?,?)",
        (taxon_id, variable, f'["{optimum}"]', f'["{accepted}"]', weight, "A", "TEST"),
    )


def test_global_soil_vector_and_combined_ranking_match_exhaustive_sql(tmp_path, monkeypatch):
    db = tmp_path / "soil-vector.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel"))

    with sqlite3.connect(db) as conn:
        _schema(conn)
        for taxon_id in ("green", "orange", "red", "unknown", "categorical"):
            _plant(conn, taxon_id)

        # GREEN: two fully optimal numeric components.
        _numeric_soil(conn, "green", "ph", 4, 5, 7, 8)
        _numeric_soil(conn, "green", "clay_pct", 0, 10, 30, 60)

        # ORANGE: both local values score 50.
        _numeric_soil(conn, "orange", "ph", 0, 10, 20, 30)
        _numeric_soil(conn, "orange", "clay_pct", 15, 25, 35, 45)

        # RED: both local values are outside hard limits.
        _numeric_soil(conn, "red", "ph", 0, 1, 2, 3)
        _numeric_soil(conn, "red", "clay_pct", 70, 80, 90, 100)

        # UNKNOWN: one documented component is not enough for operational soil status.
        _numeric_soil(conn, "unknown", "ph", 4, 5, 7, 8)

        # Categorical scoring exercises optimum=100 and accepted=65.
        _categorical_soil(conn, "categorical", "texture_class", "medium", "light")
        _categorical_soil(conn, "categorical", "drainage", "well_drained", "moderate")
        conn.commit()

    climate_values = {variable: 15.0 for variable in CLIMATE_FIXTURE}
    soil_values = {
        "ph": 5.0,
        "clay_pct": 20.0,
        "texture_class": "medium",
        "drainage": "moderate",
    }

    sql = exhaustive_search(
        str(db),
        climate_variables=climate_values,
        soil_variables=soil_values,
        life_form="ALL",
        limit=100,
    )
    sql_order = [item["taxon_id"] for item in sql["candidates"]]

    matrix = load_climate_runtime_matrix(db)
    climate = score_climate_vector(matrix, climate_values)
    soil = score_soil_vector(db, matrix, soil_values)
    combined = combine_score_vectors(matrix, climate, soil)
    vector_order = [str(matrix.taxon_ids[index]) for index in combined.order]

    assert vector_order == sql_order
    assert dict(zip(matrix.taxon_ids.tolist(), soil.status_names.tolist(), strict=True)) == {
        "categorical": "GREEN",
        "green": "GREEN",
        "orange": "ORANGE",
        "red": "RED",
        "unknown": "UNKNOWN",
    }
    vector_soil_counts = {
        name: int(np.count_nonzero(soil.status_names == name))
        for name in ("GREEN", "ORANGE", "RED", "UNKNOWN")
    }
    assert vector_soil_counts == sql["facets"]["soil_status"]
    assert soil.known_components[matrix.taxon_ids.tolist().index("unknown")] == 1


def test_soil_vector_without_documented_preferences_is_unknown(tmp_path, monkeypatch):
    db = tmp_path / "soil-unknown.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel"))
    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "x")
        conn.commit()

    matrix = load_climate_runtime_matrix(db)
    soil = score_soil_vector(db, matrix, {"ph": 6.5})
    assert soil.status_names.tolist() == ["UNKNOWN"]
    assert np.isnan(soil.score[0])
    assert soil.known_fraction.tolist() == [0.0]
    assert soil.known_components.tolist() == [0]



def test_infraspecific_taxa_inherit_only_from_unique_parent_species(tmp_path, monkeypatch):
    db = tmp_path / "soil-parent-species.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel"))

    with sqlite3.connect(db) as conn:
        _schema(conn)
        taxa = {
            "parent": "Acer campestre",
            "inherited": "Acer campestre subsp. campestre",
            "exact": "Acer campestre var. exacta",
            "genus": "Acer",
            "hybrid": "Acer × martinii",
            "cultivar": "Acer campestre 'Nanum'",
        }
        for taxon_id, scientific_name in taxa.items():
            _plant(conn, taxon_id, scientific_name)

        _numeric_soil(conn, "parent", "ph", 4, 5, 7, 8)
        _numeric_soil(conn, "parent", "clay_pct", 0, 10, 30, 60)
        _numeric_soil(conn, "exact", "ph", 0, 1, 2, 3)
        _numeric_soil(conn, "exact", "clay_pct", 70, 80, 90, 100)
        conn.commit()

    climate_values = {variable: 15.0 for variable in CLIMATE_FIXTURE}
    soil_values = {"ph": 6.0, "clay_pct": 20.0}

    matrix = load_climate_runtime_matrix(db)
    vector = score_soil_vector(db, matrix, soil_values)
    statuses = dict(zip(matrix.taxon_ids.tolist(), vector.status_names.tolist(), strict=True))

    assert statuses["parent"] == "GREEN"
    assert statuses["inherited"] == "GREEN"
    assert statuses["exact"] == "RED"
    assert statuses["genus"] == "UNKNOWN"
    assert statuses["hybrid"] == "UNKNOWN"
    assert statuses["cultivar"] == "UNKNOWN"

    legacy = exhaustive_search(
        str(db),
        climate_variables=climate_values,
        soil_variables=soil_values,
        life_form="ALL",
        limit=100,
    )
    assert legacy["facets"]["soil_status"] == {
        "GREEN": 2,
        "ORANGE": 0,
        "RED": 1,
        "UNKNOWN": 3,
    }

    repository = DerivedSqlitePlantRepository(str(db))
    inherited = repository.get("inherited")
    assert inherited is not None
    assert inherited["soil_inheritance"] == {
        "taxon_id": "parent",
        "scientific_name": "Acer campestre",
    }
    assert {limit.confidence.value for limit in inherited["soil_limits"]} == {"B"}

    exact = repository.get("exact")
    assert exact is not None
    assert exact["soil_inheritance"] is None
    assert {limit.confidence.value for limit in exact["soil_limits"]} == {"A"}
