import sqlite3

import numpy as np

from app.services.exhaustive_search import _CACHE, _cache_key, _status_filter, exhaustive_search
from app.services.funnel_metadata import install_exhaustive_metadata_patch
from app.services.search_runtime_sidecar import CLIMATE_GROUPS, CLIMATE_VARIABLES, CLIMATE_WEIGHTS
from app.services.search_vector import load_climate_runtime_matrix, score_climate_vector


PROFILE = {
    "bio01": 15.0,
    "bio05": 30.0,
    "bio06": 5.0,
    "bio12": 800.0,
    "bio15": 30.0,
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
        CREATE TABLE plant_trait_evidence (
            taxon_id TEXT NOT NULL,
            trait_name TEXT NOT NULL,
            trait_value TEXT,
            confidence TEXT,
            source_id TEXT
        );
        CREATE TABLE climate_envelope (
            taxon_id TEXT NOT NULL,
            variable TEXT NOT NULL,
            hard_low REAL,
            optimum_low REAL,
            optimum_high REAL,
            hard_high REAL,
            weight REAL NOT NULL,
            group_code TEXT,
            fatal INTEGER NOT NULL DEFAULT 0,
            confidence TEXT,
            source_ref TEXT
        );
        CREATE TABLE soil_envelope (
            taxon_id TEXT NOT NULL,
            variable TEXT NOT NULL,
            hard_low REAL,
            optimum_low REAL,
            optimum_high REAL,
            hard_high REAL,
            weight REAL NOT NULL,
            group_code TEXT,
            fatal INTEGER NOT NULL DEFAULT 0,
            confidence TEXT,
            source_ref TEXT
        );
        CREATE TABLE soil_categorical_preference (
            taxon_id TEXT NOT NULL,
            variable TEXT NOT NULL,
            optimum_values_json TEXT NOT NULL,
            accepted_values_json TEXT NOT NULL,
            weight REAL NOT NULL,
            confidence TEXT,
            source_ref TEXT
        );
        CREATE TABLE evidence (
            taxon_id TEXT NOT NULL,
            claim_type TEXT,
            claim_value TEXT,
            source_id TEXT,
            source_reference TEXT,
            source_version TEXT,
            extraction_method TEXT,
            confidence TEXT,
            notes TEXT
        );
        """
    )


def _plant(conn: sqlite3.Connection, taxon_id: str) -> None:
    conn.execute(
        "INSERT INTO plant_index(taxon_id,scientific_name) VALUES(?,?)",
        (taxon_id, f"Plant {taxon_id}"),
    )
    conn.execute(
        "INSERT INTO plant_trait_evidence VALUES(?,?,?,?,?)",
        (taxon_id, "life_form", "tree", "A", "TEST"),
    )


def _envelope(
    conn: sqlite3.Connection,
    taxon_id: str,
    variable: str,
    *,
    center: float,
    width: float = 10.0,
    fatal: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO climate_envelope(
            taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,
            weight,group_code,fatal,confidence,source_ref
        ) VALUES(?,?,?,?,?,?,?,?,?,'A','TEST')
        """,
        (
            taxon_id,
            variable,
            center - width,
            center - width / 2.0,
            center + width / 2.0,
            center + width,
            CLIMATE_WEIGHTS[variable],
            CLIMATE_GROUPS[variable],
            fatal,
        ),
    )


def _all_envelopes(conn: sqlite3.Connection, taxon_id: str, shifts: dict[str, float] | None = None) -> None:
    shifts = shifts or {}
    for variable in CLIMATE_VARIABLES:
        _envelope(
            conn,
            taxon_id,
            variable,
            center=PROFILE[variable] + shifts.get(variable, 0.0),
            width=10.0 if variable not in {"bio12"} else 500.0,
        )


def test_vector_climate_status_and_full_ranking_match_current_sql_on_mixed_catalog(tmp_path, monkeypatch):
    db = tmp_path / "catalog.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime-cache"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel-cache"))

    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "centered")
        _all_envelopes(conn, "centered")

        _plant(conn, "warm-edge")
        _all_envelopes(
            conn,
            "warm-edge",
            {"bio01": 8.0, "bio05": 8.0, "bio06": 8.0},
        )

        _plant(conn, "red")
        _all_envelopes(
            conn,
            "red",
            {"bio01": 50.0, "bio05": 50.0, "bio06": 50.0, "bio12": 2000.0, "bio15": 50.0},
        )

        _plant(conn, "fatal")
        _all_envelopes(conn, "fatal")
        conn.execute(
            "UPDATE climate_envelope SET hard_low=20,optimum_low=25,optimum_high=30,hard_high=35,fatal=1 "
            "WHERE taxon_id='fatal' AND variable='bio06'"
        )

        _plant(conn, "unknown")
        # Deliberately no climate rows: current SQL and vector runtime must both
        # keep this taxon UNKNOWN rather than infer compatibility.

        _plant(conn, "tie-a")
        _all_envelopes(conn, "tie-a")
        _plant(conn, "tie-b")
        _all_envelopes(conn, "tie-b")

    install_exhaustive_metadata_patch()
    result = exhaustive_search(
        str(db),
        climate_variables=PROFILE,
        soil_variables={},
        life_form="ALL",
        functions=[],
        statuses=[],
        soil_statuses=[],
        offset=0,
        limit=1,
        min_known_weight=0.50,
    )
    key = _cache_key(
        db,
        life_form="ALL",
        functions=(),
        climate=PROFILE,
        soil={},
        statuses=_status_filter([]),
        soil_statuses=_status_filter([]),
        min_known_weight=0.50,
    )
    snapshot = _CACHE.get(key)
    assert snapshot is not None

    matrix = load_climate_runtime_matrix(db)
    vector = score_climate_vector(matrix, PROFILE, min_known_weight=0.50)
    vector_ids = tuple(str(matrix.taxon_ids[index]) for index in vector.order)

    assert vector_ids == snapshot.ranked_ids
    vector_counts = {
        status: int(np.count_nonzero(vector.status_names == status))
        for status in ("GREEN", "ORANGE", "RED", "UNKNOWN")
    }
    assert vector_counts == result["facets"]["climate_status"]
    assert vector.status_names[np.where(matrix.taxon_ids == "unknown")[0][0]] == "UNKNOWN"
    assert vector.status_names[np.where(matrix.taxon_ids == "fatal")[0][0]] == "RED"


def test_vector_missing_profile_variable_reduces_known_fraction_without_guessing(tmp_path, monkeypatch):
    db = tmp_path / "catalog.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime-cache"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel-cache"))

    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "one")
        _all_envelopes(conn, "one")

    matrix = load_climate_runtime_matrix(db)
    missing = dict(PROFILE)
    missing["bio05"] = None
    missing["bio06"] = None
    missing["bio12"] = None
    missing["bio15"] = None
    vector = score_climate_vector(matrix, missing, min_known_weight=0.50)

    assert vector.known_fraction[0] < 0.50
    assert vector.status_names[0] == "UNKNOWN"
