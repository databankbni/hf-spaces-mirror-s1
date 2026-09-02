import sqlite3

from app.services.exhaustive_search import exhaustive_search


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
        CREATE TABLE plant_use (taxon_id TEXT NOT NULL, use_code TEXT NOT NULL);
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


def _plant(conn, taxon_id: str, name: str, life_form: str, *, use: str | None = None) -> None:
    conn.execute(
        "INSERT INTO plant_index(taxon_id,scientific_name,functions_json) VALUES(?,?, '[]')",
        (taxon_id, name),
    )
    conn.execute(
        "INSERT INTO plant_trait_evidence VALUES(?,?,?,?,?)",
        (taxon_id, "life_form", life_form, "A", "TEST"),
    )
    if use:
        conn.execute("INSERT INTO plant_use VALUES(?,?)", (taxon_id, use))


def _climate(conn, taxon_id: str, optimum_low: float, optimum_high: float) -> None:
    conn.execute(
        """
        INSERT INTO climate_envelope(
            taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,
            weight,group_code,fatal,confidence,source_ref
        ) VALUES(?, 'bio01', 0, ?, ?, 40, 1, 'M', 0, 'A', 'TEST')
        """,
        (taxon_id, optimum_low, optimum_high),
    )


def test_exhaustive_search_has_no_1000_taxon_prelimit_and_no_alphabetic_tie_bias(tmp_path):
    db = tmp_path / "catalog.sqlite"
    with sqlite3.connect(db) as conn:
        _schema(conn)
        for index in range(1100):
            taxon_id = f"a{index:04d}"
            _plant(conn, taxon_id, f"Aaa {index:04d}", "tree", use="FOOD_HUMAN")
            _climate(conn, taxon_id, 5, 25)
        _plant(conn, "z", "Zeta centered", "tree", use="FOOD_HUMAN")
        _climate(conn, "z", 15, 25)
        _plant(conn, "shrub", "Shrub control", "shrub")
        _climate(conn, "shrub", 15, 25)

    result = exhaustive_search(
        str(db),
        climate_variables={"bio01": 20.0},
        soil_variables={},
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        limit=10,
    )

    assert result["metrics"]["catalog_total"] == 1102
    assert result["metrics"]["after_type"] == 1101
    assert result["metrics"]["after_function"] == 1101
    assert result["metrics"]["evaluated_candidates"] == 1101
    assert result["metrics"]["total_results"] == 1101
    assert result["facets"]["climate_status"]["GREEN"] == 1101
    assert result["facets"]["life_form"]["TREE"] == 1101
    assert result["facets"]["life_form"]["SHRUB"] == 1
    assert result["candidates"][0]["scientific_name"] == "Zeta centered"

    second_page = exhaustive_search(
        str(db),
        climate_variables={"bio01": 20.0},
        soil_variables={},
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        offset=10,
        limit=10,
    )
    assert second_page["cache_hit"] is True
    assert second_page["pagination"]["offset"] == 10
    assert second_page["pagination"]["returned"] == 10


def test_soil_facets_are_counted_over_the_full_evaluated_population(tmp_path):
    db = tmp_path / "soil.sqlite"
    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "green", "Green soil", "tree")
        _plant(conn, "red", "Red soil", "tree")
        for taxon_id in ("green", "red"):
            _climate(conn, taxon_id, 10, 20)
        conn.execute(
            "INSERT INTO soil_envelope VALUES('green','ph',4,5,7,8,1,'E',0,'A','S')"
        )
        conn.execute(
            "INSERT INTO soil_envelope VALUES('green','clay_pct',0,10,30,60,1,'E',0,'A','S')"
        )
        conn.execute(
            "INSERT INTO soil_envelope VALUES('red','ph',0,1,2,3,1,'E',0,'A','S')"
        )
        conn.execute(
            "INSERT INTO soil_envelope VALUES('red','clay_pct',70,80,90,100,1,'E',0,'A','S')"
        )

    result = exhaustive_search(
        str(db),
        climate_variables={"bio01": 15.0},
        soil_variables={"ph": 6.5, "clay_pct": 20.0},
        life_form="TREE",
        limit=1,
    )

    assert result["pagination"]["returned"] == 1
    assert result["metrics"]["evaluated_candidates"] == 2
    assert result["facets"]["soil_status"]["GREEN"] == 1
    assert result["facets"]["soil_status"]["RED"] == 1


def test_status_only_filter_change_reuses_scientific_snapshot(tmp_path):
    db = tmp_path / "status-cache.sqlite"
    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "green", "Green climate", "tree")
        _plant(conn, "red", "Red climate", "tree")
        _climate(conn, "green", 10, 20)
        _climate(conn, "red", 30, 35)

    base = exhaustive_search(
        str(db),
        climate_variables={"bio01": 15.0},
        soil_variables={},
        life_form="TREE",
        limit=10,
    )
    assert base["cache_hit"] is False
    assert base["metrics"]["total_results"] == 2

    green_only = exhaustive_search(
        str(db),
        climate_variables={"bio01": 15.0},
        soil_variables={},
        life_form="TREE",
        statuses=["GREEN"],
        limit=10,
    )
    assert green_only["cache_hit"] is True
    assert green_only["metrics"]["evaluated_candidates"] == 2
    assert green_only["metrics"]["total_results"] == 1
    assert green_only["pagination"]["returned"] == 1
    assert green_only["candidates"][0]["taxon_id"] == "green"
    assert green_only["facets"]["climate_status"]["GREEN"] == 1
    assert green_only["facets"]["climate_status"]["ORANGE"] == 1

