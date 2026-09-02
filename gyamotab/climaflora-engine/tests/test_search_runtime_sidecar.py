import json
import sqlite3

from app.services.search_runtime_sidecar import (
    CLIMATE_GROUPS,
    CLIMATE_VARIABLES,
    CLIMATE_WEIGHTS,
    LIFE_MASKS,
    search_runtime_sidecar_summary,
    warm_search_runtime_sidecar,
)


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE plant_index (
            taxon_id TEXT PRIMARY KEY,
            scientific_name TEXT NOT NULL,
            functions_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE plant_profile (
            taxon_id TEXT PRIMARY KEY,
            family TEXT,
            life_form TEXT
        );
        CREATE TABLE climate_envelope (
            taxon_id TEXT NOT NULL,
            variable TEXT NOT NULL,
            hard_low REAL,
            optimum_low REAL,
            optimum_high REAL,
            hard_high REAL,
            weight REAL NOT NULL,
            group_code TEXT NOT NULL,
            fatal INTEGER NOT NULL DEFAULT 0
        );
        """
    )


def _climate(conn: sqlite3.Connection, taxon_id: str, shift: float = 0.0) -> None:
    for index, variable in enumerate(CLIMATE_VARIABLES):
        base = float(index * 10) + shift
        conn.execute(
            """
            INSERT INTO climate_envelope(
                taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,weight,group_code,fatal
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                taxon_id,
                variable,
                base,
                base + 1.0,
                base + 2.0,
                base + 3.0,
                CLIMATE_WEIGHTS[variable],
                CLIMATE_GROUPS[variable],
                0,
            ),
        )


def _plant(
    conn: sqlite3.Connection,
    taxon_id: str,
    life_form: str,
    functions: list[str],
    family: str | None = None,
    *,
    climate_shift: float = 0.0,
) -> None:
    conn.execute(
        "INSERT INTO plant_index(taxon_id,scientific_name,functions_json) VALUES(?,?,?)",
        (taxon_id, f"Plant {taxon_id}", json.dumps(functions)),
    )
    conn.execute(
        "INSERT INTO plant_profile(taxon_id,family,life_form) VALUES(?,?,?)",
        (taxon_id, family, life_form),
    )
    _climate(conn, taxon_id, climate_shift)


def test_runtime_sidecar_has_stable_ordinals_masks_and_climate_wide_projection(tmp_path, monkeypatch):
    db = tmp_path / "catalog.sqlite"
    cache_root = tmp_path / "runtime-cache"
    funnel_root = tmp_path / "funnel-cache"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(cache_root))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(funnel_root))

    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "10", "tree", ["FOOD_HUMAN", "MATERIALS"], climate_shift=0.1)
        _plant(conn, "2", "annual", ["FOOD_HUMAN"], climate_shift=0.2)
        _plant(conn, "a", "tree", ["MEDICINAL"], family="Arecaceae", climate_shift=0.3)

    sidecar = warm_search_runtime_sidecar(db)
    assert sidecar.exists()

    with sqlite3.connect(sidecar) as conn:
        rows = conn.execute(
            "SELECT taxon_id,ordinal,life_category,life_mask,function_mask FROM taxon_runtime ORDER BY ordinal"
        ).fetchall()
        codes = dict(conn.execute("SELECT code,bit_index FROM function_code ORDER BY bit_index"))
        climate_rows = conn.execute(
            """
            SELECT ordinal,taxon_id,bio01_hard_low,bio01_optimum_low,bio06_weight,bio15_fatal
            FROM climate_runtime_wide ORDER BY ordinal
            """
        ).fetchall()

    assert [row[0] for row in rows] == ["10", "2", "a"]
    assert [row[1] for row in rows] == [0, 1, 2]
    assert rows[0][2:4] == ("TREE", LIFE_MASKS["TREE"])
    assert rows[1][2:4] == ("HERB", LIFE_MASKS["HERB"])
    assert rows[2][2:4] == ("PALM", LIFE_MASKS["PALM"])
    assert codes == {"FOOD_HUMAN": 0, "MATERIALS": 1, "MEDICINAL": 2}

    food = 1 << codes["FOOD_HUMAN"]
    materials = 1 << codes["MATERIALS"]
    medicinal = 1 << codes["MEDICINAL"]
    assert rows[0][4] == food | materials
    assert rows[1][4] == food
    assert rows[2][4] == medicinal

    assert climate_rows[0] == (0, "10", 0.1, 1.1, 1.2, 0)
    assert climate_rows[1][0:2] == (1, "2")
    assert climate_rows[2][0:2] == (2, "a")

    first_mtime = sidecar.stat().st_mtime_ns
    assert warm_search_runtime_sidecar(db) == sidecar
    assert sidecar.stat().st_mtime_ns == first_mtime

    summary = search_runtime_sidecar_summary(db)
    assert summary["catalog_taxa"] == 3
    assert summary["function_code_count"] == 3
    assert summary["ordinal_order"] == "taxon_id_asc_text"
    assert summary["climate_envelope_rows"] == 15
    assert summary["climate_envelope_taxa"] == 3
    assert summary["climate_wide_rows"] == 3
    assert summary["climate_projection_layout"] == "wide_float64_sqlite_real_v1"


def test_runtime_sidecar_identity_changes_when_catalog_changes(tmp_path, monkeypatch):
    db = tmp_path / "catalog.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime-cache"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel-cache"))

    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "1", "tree", ["FOOD_HUMAN"])

    first = warm_search_runtime_sidecar(db)
    with sqlite3.connect(db) as conn:
        _plant(conn, "2", "annual", ["MEDICINAL"])
    second = warm_search_runtime_sidecar(db)

    assert first != second
    assert search_runtime_sidecar_summary(db)["catalog_taxa"] == 2


def test_runtime_sidecar_rejects_duplicate_climate_scoring_envelopes(tmp_path, monkeypatch):
    db = tmp_path / "catalog.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime-cache"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel-cache"))

    with sqlite3.connect(db) as conn:
        _schema(conn)
        _plant(conn, "1", "tree", ["FOOD_HUMAN"])
        conn.execute(
            """
            INSERT INTO climate_envelope(
                taxon_id,variable,hard_low,optimum_low,optimum_high,hard_high,weight,group_code,fatal
            ) VALUES('1','bio01',0,1,2,3,1.0,'V',0)
            """
        )

    try:
        warm_search_runtime_sidecar(db)
    except RuntimeError as exc:
        assert "exactly one scoring envelope" in str(exc)
    else:
        raise AssertionError("duplicate climate envelope should be rejected")
