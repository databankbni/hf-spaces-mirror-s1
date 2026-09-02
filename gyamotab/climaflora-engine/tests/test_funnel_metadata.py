import sqlite3

from app.services import exhaustive_search as exhaustive_module
from app.services.exhaustive_search import exhaustive_search
from app.services.funnel_metadata import (
    canonical_function_counts,
    install_exhaustive_metadata_patch,
    prepare_life_categories,
    warm_funnel_metadata,
)


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
        CREATE TABLE evidence (
            taxon_id TEXT NOT NULL, claim_type TEXT, claim_value TEXT, source_id TEXT,
            source_reference TEXT, source_version TEXT, extraction_method TEXT,
            confidence TEXT, notes TEXT
        );
        CREATE TABLE plant_use (taxon_id TEXT NOT NULL, use_code TEXT NOT NULL);
        """
    )


def _plant(conn, taxon_id, name, life_form, functions="[]", family=None):
    conn.execute(
        "INSERT INTO plant_index(taxon_id,scientific_name,functions_json) VALUES(?,?,?)",
        (taxon_id, name, functions),
    )
    conn.execute("INSERT INTO plant_profile VALUES(?,?,?)", (taxon_id, family, life_form))
    conn.execute(
        "INSERT INTO climate_envelope VALUES(?, 'bio01', 0, 10, 20, 40, 1, 'M', 0, 'A', 'TEST')",
        (taxon_id,),
    )


def test_wcvp_navigation_life_forms_are_normalized(tmp_path):
    db = tmp_path / "life.sqlite"
    with sqlite3.connect(db) as conn:
        _schema(conn)
        values = {
            "annual": "HERB",
            "perennial": "HERB",
            "tuberous geophyte": "HERB",
            "pseudobulbous epiphyte": "HERB",
            "bamboo": "HERB",
            "subshrub": "SHRUB",
            "scrambling shrub": "CLIMBER",
            "shrub or tree": "SHRUB",
            "tree": "TREE",
            "liana": "CLIMBER",
        }
        for index, (value, _) in enumerate(values.items()):
            _plant(conn, str(index), value, value)
        _plant(conn, "palm", "Documented palm", "tree", family="Arecaceae")
        values["Documented palm"] = "PALM"
        conn.commit()
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        prepare_life_categories(conn, tables)
        got = dict(
            conn.execute(
                "SELECT p.scientific_name,lc.category FROM plant_index p JOIN life_category lc USING(taxon_id)"
            )
        )
        assert got == values


def test_public_function_code_uses_functions_json_not_wcups_native_code(tmp_path):
    db = tmp_path / "functions.sqlite"
    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "food", "Food tree", "tree", '["FOOD_HUMAN"]')
        conn.execute("INSERT INTO plant_use VALUES('food','HF')")
        _plant(conn, "med", "Medicinal tree", "tree", '["MEDICINAL"]')
        conn.execute("INSERT INTO plant_use VALUES('med','ME')")

    install_exhaustive_metadata_patch()
    result = exhaustive_search(
        str(db),
        climate_variables={"bio01": 15.0},
        soil_variables={},
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        limit=10,
    )
    assert result["metrics"]["after_type"] == 2
    assert result["metrics"]["after_function"] == 1
    assert result["candidates"][0]["scientific_name"] == "Food tree"
    assert canonical_function_counts(db, "TREE") == {"FOOD_HUMAN": 1, "MEDICINAL": 1}
    assert exhaustive_module._function_predicate.__module__ == "app.services.funnel_metadata"


def test_funnel_sidecar_is_reused_for_life_and_function_facets(tmp_path, monkeypatch):
    db = tmp_path / "cached.sqlite"
    cache_dir = tmp_path / "funnel-cache"
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(cache_dir))
    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "food", "Food tree", "tree", '["FOOD_HUMAN","MATERIALS"]')
        _plant(conn, "herb", "Food herb", "annual", '["FOOD_HUMAN"]')
        _plant(conn, "palm", "Palm", "tree", '["MATERIALS"]', family="Arecaceae")

    sidecar = warm_funnel_metadata(db)
    first_mtime = sidecar.stat().st_mtime_ns
    assert sidecar.exists()
    assert canonical_function_counts(db, "ALL") == {"FOOD_HUMAN": 2, "MATERIALS": 2}
    assert canonical_function_counts(db, "TREE") == {"FOOD_HUMAN": 1, "MATERIALS": 1}
    assert canonical_function_counts(db, "PALM") == {"MATERIALS": 1}

    with sqlite3.connect(db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        prepare_life_categories(conn, tables)
        counts = dict(conn.execute("SELECT category,COUNT(*) FROM life_category GROUP BY category"))
        assert counts == {"HERB": 1, "PALM": 1, "TREE": 1}

    assert warm_funnel_metadata(db) == sidecar
    assert sidecar.stat().st_mtime_ns == first_mtime
