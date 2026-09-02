import sqlite3

from app.domain.models import ClimateProfile, Confidence, Horizon, Scenario, SoilProfile
from app.services.exhaustive_search import exhaustive_search
from app.services.search_vector_cache import clear_vector_cache
from app.services.search_vector_runtime import vector_runtime_search


LAYOUT = {
    "bio01": ("V", 1.0),
    "bio05": ("M", 1.0),
    "bio06": ("M", 1.2),
    "bio12": ("E", 0.8),
    "bio15": ("E", 0.7),
}


def _build(db):
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE plant_index (
                taxon_id TEXT PRIMARY KEY, scientific_name TEXT NOT NULL, common_name TEXT,
                functions_json TEXT NOT NULL DEFAULT '[]', regulatory_veto INTEGER NOT NULL DEFAULT 0,
                regulatory_reason TEXT, confidence TEXT, powo_id TEXT, scientific_name_id TEXT,
                references_url TEXT
            );
            CREATE TABLE plant_profile (taxon_id TEXT PRIMARY KEY, family TEXT, life_form TEXT);
            CREATE TABLE climate_envelope (
                taxon_id TEXT NOT NULL, variable TEXT NOT NULL, hard_low REAL, optimum_low REAL,
                optimum_high REAL, hard_high REAL, weight REAL NOT NULL, group_code TEXT,
                fatal INTEGER NOT NULL DEFAULT 0, confidence TEXT, source_ref TEXT
            );
            CREATE TABLE soil_envelope (
                taxon_id TEXT NOT NULL, variable TEXT NOT NULL, hard_low REAL, optimum_low REAL,
                optimum_high REAL, hard_high REAL, weight REAL NOT NULL, group_code TEXT,
                fatal INTEGER NOT NULL DEFAULT 0, confidence TEXT, source_ref TEXT
            );
            CREATE TABLE evidence (
                taxon_id TEXT NOT NULL, claim_type TEXT, claim_value TEXT, source_id TEXT,
                source_reference TEXT, source_version TEXT, extraction_method TEXT,
                confidence TEXT, notes TEXT
            );
            """
        )
        rows = [
            ("food", "Food tree", '["FOOD_HUMAN"]', "tree", (0, 10, 20, 40)),
            ("other", "Other tree", '["MATERIALS"]', "tree", (0, 20, 30, 40)),
            ("herb", "Food herb", '["FOOD_HUMAN"]', "annual", (20, 30, 40, 50)),
        ]
        for taxon_id, name, functions, life, envelope in rows:
            conn.execute(
                "INSERT INTO plant_index(taxon_id,scientific_name,functions_json) VALUES(?,?,?)",
                (taxon_id, name, functions),
            )
            conn.execute("INSERT INTO plant_profile VALUES(?,?,?)", (taxon_id, None, life))
            for variable, (group, weight) in LAYOUT.items():
                conn.execute(
                    "INSERT INTO climate_envelope VALUES(?,?,?,?,?,?,?,?,0,'A','TEST')",
                    (taxon_id, variable, *envelope, weight, group),
                )
        conn.execute("INSERT INTO soil_envelope VALUES('food','ph',4,5,7,8,1,'E',0,'A','TEST')")
        conn.execute("INSERT INTO soil_envelope VALUES('food','clay_pct',0,10,30,60,1,'E',0,'A','TEST')")
        conn.commit()


def _climate():
    return ClimateProfile(
        latitude=47.16,
        longitude=-1.27,
        horizon=Horizon.Y2050,
        scenario=Scenario.MEDIUM,
        provider="CHELSA",
        model="test",
        period="2041-2070",
        variables={variable: 15.0 for variable in LAYOUT},
        provenance={"dataset": "CHELSA-bioclim", "version": "2.1", "manifest_revision": "test"},
    )


def _soil():
    return SoilProfile(
        latitude=47.16,
        longitude=-1.27,
        provider="SoilGrids 2.0 / ISRIC",
        properties={"ph": 6.5, "clay_pct": 20.0},
        confidence=Confidence.C,
        provenance={"access": "WCS 2.0.1", "prediction": "Q0.5"},
    )


def test_vector_runtime_matches_exhaustive_and_reuses_status_filter(tmp_path, monkeypatch):
    db = tmp_path / "runtime.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime-cache"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel-cache"))
    _build(db)
    clear_vector_cache()
    climate = _climate()
    soil = _soil()

    reference = exhaustive_search(
        str(db),
        climate_variables=climate.variables,
        soil_variables=soil.properties,
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        limit=100,
    )
    first = vector_runtime_search(
        db,
        climate=climate,
        soil=soil,
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        limit=100,
    )
    assert [item["taxon_id"] for item in first["candidates"]] == [
        item["taxon_id"] for item in reference["candidates"]
    ]
    assert first["metrics"] == reference["metrics"]
    for facet_name, expected in reference["facets"].items():
        assert first["facets"][facet_name] == expected
    assert first["facets"]["genus_initial"] == {"ALL": 1, "F": 1}
    assert first["cache_hit"] is False

    green_reference = exhaustive_search(
        str(db),
        climate_variables=climate.variables,
        soil_variables=soil.properties,
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        statuses=["GREEN"],
        limit=100,
    )
    green = vector_runtime_search(
        db,
        climate=climate,
        soil=soil,
        life_form="TREE",
        functions=["FOOD_HUMAN"],
        statuses=["GREEN"],
        limit=100,
    )
    assert green["cache_hit"] is True
    assert green["vector_runtime"]["cache_hits"] == {
        "climate": True,
        "soil": True,
        "ranking": True,
    }
    assert [item["taxon_id"] for item in green["candidates"]] == [
        item["taxon_id"] for item in green_reference["candidates"]
    ]
    assert green["metrics"] == green_reference["metrics"]
