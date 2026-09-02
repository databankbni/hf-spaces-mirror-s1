import sqlite3

from app.routers.enrichment import _classify_life_form
from app.services.life_form_candidates import iter_candidates_by_life_form
from app.services.plants import DerivedSqlitePlantRepository


def test_classify_life_form_categories():
    assert _classify_life_form("tree") == "TREE"
    assert _classify_life_form("evergreen shrub") == "SHRUB"
    assert _classify_life_form("herbaceous perennial") == "HERB"
    assert _classify_life_form("woody climber / liana") == "CLIMBER"
    assert _classify_life_form("palm") == "PALM"
    assert _classify_life_form("succulent") == "OTHER"
    assert _classify_life_form(None) == "UNKNOWN"


def _make_catalog(path):
    with sqlite3.connect(path) as conn:
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
            CREATE TABLE plant_trait_evidence (
                taxon_id TEXT NOT NULL,
                trait_name TEXT NOT NULL,
                trait_value TEXT,
                confidence TEXT,
                source_id TEXT
            );
            """
        )
        plants = [
            ("t1", "Aaa alpha", "tree"),
            ("t2", "Aab beta", "shrub"),
            ("t3", "Zeta climber", "woody climber / liana"),
        ]
        for taxon_id, name, life_form in plants:
            conn.execute(
                "INSERT INTO plant_index(taxon_id,scientific_name,functions_json,regulatory_veto,confidence) "
                "VALUES(?,?, '[]', 0, 'A')",
                (taxon_id, name),
            )
            conn.execute(
                "INSERT INTO climate_envelope(taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,"
                "weight,group_code,fatal,confidence,source_ref) VALUES(?, 'bio01', 0, 5, 25, 40, 1, 'temp', 0, 'A', 'TEST')",
                (taxon_id,),
            )
            conn.execute(
                "INSERT INTO plant_trait_evidence(taxon_id,trait_name,trait_value,confidence,source_id) "
                "VALUES(?, 'life_form', ?, 'A', 'TEST')",
                (taxon_id, life_form),
            )


def test_life_form_is_applied_before_rough_limit(tmp_path):
    db = tmp_path / "catalog.sqlite"
    _make_catalog(db)
    repository = DerivedSqlitePlantRepository(str(db))

    candidates, eligible_count = iter_candidates_by_life_form(
        repository,
        life_form="CLIMBER",
        functions=[],
        limit=1,
        climate_variables={"bio01": 15.0},
        soil_variables={},
    )

    assert eligible_count == 1
    assert [candidate["taxon_id"] for candidate in candidates] == ["t3"]
    assert candidates[0]["scientific_name"] == "Zeta climber"


def test_other_excludes_known_life_form_tokens(tmp_path):
    db = tmp_path / "catalog.sqlite"
    _make_catalog(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO plant_index(taxon_id,scientific_name,functions_json,regulatory_veto,confidence) "
            "VALUES('t4','Zzz succulent','[]',0,'A')"
        )
        conn.execute(
            "INSERT INTO climate_envelope(taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,"
            "weight,group_code,fatal,confidence,source_ref) "
            "VALUES('t4','bio01',0,5,25,40,1,'temp',0,'A','TEST')"
        )
        conn.execute(
            "INSERT INTO plant_trait_evidence(taxon_id,trait_name,trait_value,confidence,source_id) "
            "VALUES('t4','life_form','succulent','A','TEST')"
        )

    repository = DerivedSqlitePlantRepository(str(db))
    candidates, eligible_count = iter_candidates_by_life_form(
        repository,
        life_form="OTHER",
        functions=[],
        limit=10,
        climate_variables={"bio01": 15.0},
        soil_variables={},
    )

    assert eligible_count == 1
    assert [candidate["taxon_id"] for candidate in candidates] == ["t4"]
