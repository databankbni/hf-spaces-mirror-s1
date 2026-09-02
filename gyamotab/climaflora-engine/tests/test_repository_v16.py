import json
import sqlite3

from app.services.plants import DerivedSqlitePlantRepository


def build_catalog(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE plant_index (
              taxon_id TEXT PRIMARY KEY,
              scientific_name TEXT NOT NULL,
              common_name TEXT,
              functions_json TEXT,
              regulatory_veto INTEGER NOT NULL DEFAULT 0,
              regulatory_reason TEXT,
              confidence TEXT,
              powo_id TEXT,
              scientific_name_id TEXT,
              references_url TEXT
            );
            CREATE TABLE climate_envelope (
              taxon_id TEXT, variable TEXT, hard_low REAL, optimum_low REAL,
              optimum_high REAL, hard_high REAL, weight REAL, group_code TEXT,
              fatal INTEGER, confidence TEXT, source_ref TEXT
            );
            CREATE TABLE soil_envelope (
              taxon_id TEXT, variable TEXT, hard_low REAL, optimum_low REAL,
              optimum_high REAL, hard_high REAL, weight REAL, group_code TEXT,
              fatal INTEGER, confidence TEXT, source_ref TEXT
            );
            CREATE TABLE evidence (
              taxon_id TEXT, claim_type TEXT, claim_value TEXT, source_id TEXT,
              source_reference TEXT, source_version TEXT, extraction_method TEXT,
              confidence TEXT, notes TEXT
            );
            CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE soil_indicator_preference (
              preference_id INTEGER PRIMARY KEY,
              taxon_id TEXT,
              region_scope TEXT,
              indicator TEXT,
              optimum REAL,
              niche_width REAL,
              source_systems INTEGER,
              scale_min REAL,
              scale_max REAL,
              weight REAL,
              confidence TEXT,
              source_ref TEXT,
              method TEXT,
              method_version TEXT
            );
            CREATE TABLE soil_geographic_prior (
              taxon_id TEXT PRIMARY KEY,
              native_region_count INTEGER,
              covered_region_count INTEGER,
              variables_json TEXT,
              confidence TEXT,
              scoring_enabled INTEGER,
              source_ref TEXT,
              method TEXT,
              method_version TEXT
            );
            CREATE TABLE plant_image_asset (
              asset_id TEXT PRIMARY KEY,
              taxon_id TEXT,
              thumbnail_url TEXT,
              image_url TEXT,
              source TEXT,
              license TEXT,
              author TEXT,
              attribution_url TEXT,
              is_primary INTEGER DEFAULT 0
            );
            """
        )
        conn.executemany(
            "INSERT INTO build_metadata(key,value) VALUES(?,?)",
            [
                ("mode", "SCIENTIFIC_PROXY_WCVP_TEST"),
                ("scientific_ready", "true"),
            ],
        )
        conn.executemany(
            """INSERT INTO plant_index(
              taxon_id,scientific_name,common_name,functions_json,regulatory_veto,
              regulatory_reason,confidence,powo_id,scientific_name_id,references_url
            ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [
                ("A", "Alpha climatica", "Alpha", "[]", 0, None, "C", None, None, None),
                ("B", "Beta edaphica", "Beta", "[]", 0, None, "C", None, None, None),
            ],
        )
        conn.executemany(
            "INSERT INTO climate_envelope VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("A", "bio01", 0, 19, 21, 30, 1.0, "M", 0, "C", "TEST"),
                ("B", "bio01", 0, 18, 19, 29, 1.0, "M", 0, "C", "TEST"),
            ],
        )
        conn.executemany(
            "INSERT INTO soil_envelope VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("A", "ph", 3, 4, 5, 6, 1.0, "E", 0, "C", "TEST"),
                ("B", "ph", 4, 6, 8, 9, 1.0, "E", 0, "C", "TEST"),
            ],
        )
        conn.execute(
            """INSERT INTO soil_indicator_preference VALUES(
              1,'A','EUROPE','R',6.5,1.2,3,0,10,0.3,'C','EIVE','EIVE_1_0_EUROPE_CONSENSUS','1.0'
            )"""
        )
        conn.execute(
            "INSERT INTO soil_geographic_prior VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "A",
                2,
                2,
                json.dumps(
                    {
                        "ph": {
                            "outer_low": 4.5,
                            "central_low": 5.0,
                            "region_median": 6.0,
                            "central_high": 7.0,
                            "outer_high": 7.5,
                            "regions": 2,
                        }
                    }
                ),
                "PRIOR",
                1,
                "TEST PRIOR",
                "WCVP_NATIVE_TDWG3_SOILGRIDS_GEOGRAPHIC_PRIOR",
                "1.0",
            ),
        )
        conn.execute(
            "INSERT INTO plant_image_asset VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "img-a",
                "A",
                "/media/plants/a.webp",
                "https://example.invalid/original.jpg",
                "TEST",
                "CC BY 4.0",
                "Botanist",
                "https://example.invalid/credit",
                1,
            ),
        )


def test_v16_context_hydration_and_image_contract(tmp_path) -> None:
    db = tmp_path / "catalog.sqlite"
    build_catalog(db)
    repo = DerivedSqlitePlantRepository(str(db))

    plant = repo.get("A")
    assert plant is not None
    assert plant["soil_indicators"][0].indicator == "R"
    assert plant["soil_indicators"][0].optimum == 6.5
    assert plant["soil_geographic_context"].scoring_enabled is False
    assert plant["soil_geographic_context"].variables["ph"]["region_median"] == 6.0
    assert plant["image"].thumbnail_url == "/media/plants/a.webp"
    assert plant["image"].license == "CC BY 4.0"

    state = repo.readiness()
    assert state["soil_indicator_taxa"] == 1
    assert state["soil_geographic_prior_taxa"] == 1
    assert state["soil_geographic_prior_scoring_rows"] == 1
    assert state["image_assets"] == 1


def test_bi_axis_preselection_keeps_best_climate_and_best_combined(tmp_path) -> None:
    db = tmp_path / "catalog.sqlite"
    build_catalog(db)
    repo = DerivedSqlitePlantRepository(str(db))
    with repo._connect() as conn:
        rows = repo._ranked_plant_rows(
            conn,
            functions=[],
            limit=1,
            climate_variables={"bio01": 20.0},
            soil_variables={"ph": 7.0},
        )
    ids = {row["taxon_id"] for row in rows}
    assert ids == {"A", "B"}
    by_id = {row["taxon_id"]: row for row in rows}
    assert by_id["A"]["climate_rough"] > by_id["B"]["climate_rough"]
    assert by_id["B"]["rough_score"] > by_id["A"]["rough_score"]
