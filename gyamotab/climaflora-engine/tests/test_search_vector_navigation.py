import sqlite3

from app.services.exhaustive_search import exhaustive_search
from app.services.funnel_metadata import canonical_function_counts, install_exhaustive_metadata_patch
from app.services.search_soil_vector import combine_score_vectors, score_soil_vector
from app.services.search_vector import load_climate_runtime_matrix, score_climate_vector
from app.services.search_vector_navigation import load_navigation_runtime_matrix, ranking_view


CLIMATE_LAYOUT = {
    "bio01": ("V", 1.0),
    "bio05": ("M", 1.0),
    "bio06": ("M", 1.2),
    "bio12": ("E", 0.8),
    "bio15": ("E", 0.7),
}
CLIMATE = {name: 15.0 for name in CLIMATE_LAYOUT}


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
    life_form: str,
    functions_json: str,
    envelope: tuple[float, float, float, float] | None,
) -> None:
    conn.execute(
        "INSERT INTO plant_index(taxon_id,scientific_name,functions_json) VALUES(?,?,?)",
        (taxon_id, f"Plant {taxon_id}", functions_json),
    )
    conn.execute("INSERT INTO plant_profile VALUES(?,?,?)", (taxon_id, None, life_form))
    if envelope is None:
        return
    hard_low, optimum_low, optimum_high, hard_high = envelope
    for variable, (group, weight) in CLIMATE_LAYOUT.items():
        conn.execute(
            "INSERT INTO climate_envelope VALUES(?,?,?,?,?,?,?,?,0,'A','TEST')",
            (
                taxon_id,
                variable,
                hard_low,
                optimum_low,
                optimum_high,
                hard_high,
                weight,
                group,
            ),
        )


def test_navigation_masks_preserve_exhaustive_order_metrics_and_facets(tmp_path, monkeypatch):
    db = tmp_path / "navigation.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel"))
    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "tree_food", "tree", '["FOOD_HUMAN"]', (0, 10, 20, 40))
        _plant(conn, "tree_food_med", "tree", '["FOOD_HUMAN","MEDICINAL"]', (0, 10, 20, 40))
        _plant(conn, "tree_mat", "tree", '["MATERIALS"]', (0, 20, 30, 40))
        _plant(conn, "herb_food", "annual", '["FOOD_HUMAN"]', (20, 30, 40, 50))
        _plant(conn, "herb_unknown", "annual", '[]', None)
        _plant(conn, "shrub_med", "shrub", '["MEDICINAL"]', (0, 10, 20, 40))
        conn.commit()

    install_exhaustive_metadata_patch()
    matrix = load_climate_runtime_matrix(db)
    navigation = load_navigation_runtime_matrix(db)
    climate = score_climate_vector(matrix, CLIMATE)
    soil = score_soil_vector(db, matrix, {})
    combined = combine_score_vectors(matrix, climate, soil)

    cases = [
        ("ALL", [], [], []),
        ("TREE", [], [], []),
        ("TREE", ["FOOD_HUMAN"], [], []),
        ("TREE", ["FOOD_HUMAN", "MEDICINAL"], [], []),
        ("HERB", ["FOOD_HUMAN"], [], []),
        ("TREE", [], ["GREEN"], []),
        ("TREE", [], ["ORANGE"], []),
        ("ALL", [], ["UNKNOWN"], []),
        ("ALL", [], [], ["GREEN"]),
    ]

    for life_form, functions, statuses, soil_statuses in cases:
        reference = exhaustive_search(
            str(db),
            climate_variables=CLIMATE,
            soil_variables={},
            life_form=life_form,
            functions=functions,
            statuses=statuses,
            soil_statuses=soil_statuses,
            limit=100,
        )
        view = ranking_view(
            navigation,
            matrix,
            climate,
            soil,
            combined,
            life_form=life_form,
            functions=functions,
            statuses=statuses,
            soil_statuses=soil_statuses,
            limit=100,
        )
        reference_ids = [item["taxon_id"] for item in reference["candidates"]]
        vector_ids = [str(matrix.taxon_ids[index]) for index in view.page_ordinals]
        assert vector_ids == reference_ids
        assert view.metrics == reference["metrics"]
        assert view.facets["life_form"] == reference["facets"]["life_form"]
        assert view.facets["climate_status"] == reference["facets"]["climate_status"]
        assert view.facets["soil_status"] == reference["facets"]["soil_status"]
        assert view.facets["functions"] == canonical_function_counts(db, life_form)


def test_unknown_function_code_yields_empty_eligible_population(tmp_path, monkeypatch):
    db = tmp_path / "navigation-unknown-function.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel"))
    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "tree", "tree", '["FOOD_HUMAN"]', (0, 10, 20, 40))
        conn.commit()

    matrix = load_climate_runtime_matrix(db)
    navigation = load_navigation_runtime_matrix(db)
    climate = score_climate_vector(matrix, CLIMATE)
    soil = score_soil_vector(db, matrix, {})
    combined = combine_score_vectors(matrix, climate, soil)
    view = ranking_view(
        navigation,
        matrix,
        climate,
        soil,
        combined,
        life_form="TREE",
        functions=["NOT_A_REAL_FUNCTION"],
    )
    assert view.metrics["after_type"] == 1
    assert view.metrics["after_function"] == 0
    assert view.metrics["evaluated_candidates"] == 0
    assert view.metrics["total_results"] == 0
    assert view.page_ordinals.size == 0
