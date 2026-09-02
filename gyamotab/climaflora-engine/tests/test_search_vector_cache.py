import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.domain.models import ClimateProfile, Confidence, Horizon, Scenario, SoilProfile
from app.services.search_vector_cache import (
    ScientificVectorCache,
    clear_vector_cache,
    get_climate_score_vector,
    get_combined_score_vector,
    get_soil_score_vector,
    vector_cache_stats,
)


CLIMATE_LAYOUT = {
    "bio01": ("V", 1.0),
    "bio05": ("M", 1.0),
    "bio06": ("M", 1.2),
    "bio12": ("E", 0.8),
    "bio15": ("E", 0.7),
}


def _catalog(path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE plant_index (
                taxon_id TEXT PRIMARY KEY,
                scientific_name TEXT NOT NULL,
                functions_json TEXT NOT NULL DEFAULT '[]'
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
            """
        )
        for taxon_id in ("a", "b"):
            conn.execute(
                "INSERT INTO plant_index(taxon_id,scientific_name) VALUES(?,?)",
                (taxon_id, f"Plant {taxon_id}"),
            )
            conn.execute("INSERT INTO plant_profile VALUES(?,?,?)", (taxon_id, None, "tree"))
            for variable, (group, weight) in CLIMATE_LAYOUT.items():
                conn.execute(
                    "INSERT INTO climate_envelope VALUES(?,?,0,10,20,40,?,?,0,'A','TEST')",
                    (taxon_id, variable, weight, group),
                )
        conn.execute(
            "INSERT INTO soil_envelope VALUES('a','ph',4,5,7,8,1,'E',0,'A','TEST')"
        )
        conn.execute(
            "INSERT INTO soil_envelope VALUES('a','clay_pct',0,10,30,60,1,'E',0,'A','TEST')"
        )
        conn.commit()


def _climate() -> ClimateProfile:
    return ClimateProfile(
        latitude=47.16,
        longitude=-1.27,
        horizon=Horizon.Y2050,
        scenario=Scenario.MEDIUM,
        provider="CHELSA",
        model="ensemble-test",
        period="2041-2070",
        variables={variable: 15.0 for variable in CLIMATE_LAYOUT},
        provenance={
            "dataset": "CHELSA-bioclim",
            "version": "2.1",
            "manifest_revision": "test-revision",
            "scenario_mapping": "ssp370",
        },
    )


def _soil(ph: float) -> SoilProfile:
    return SoilProfile(
        latitude=47.16,
        longitude=-1.27,
        provider="SoilGrids 2.0 / ISRIC",
        depth="5-15cm",
        resolution_m=250,
        properties={"ph": ph, "clay_pct": 20.0},
        confidence=Confidence.C,
        provenance={
            "access": "WCS 2.0.1",
            "prediction": "Q0.5",
            "wcs_base": "https://maps.isric.org/mapserv",
        },
    )


def test_climate_soil_and_combined_caches_are_independent(tmp_path, monkeypatch):
    db = tmp_path / "catalog.sqlite"
    monkeypatch.setenv("CLIMAFLORA_SEARCH_RUNTIME_CACHE_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("CLIMAFLORA_FUNNEL_CACHE_DIR", str(tmp_path / "funnel"))
    _catalog(db)
    clear_vector_cache()

    matrix, climate1 = get_climate_score_vector(db, _climate())
    soil1 = get_soil_score_vector(db, matrix, _soil(6.5))
    combined1 = get_combined_score_vector(matrix, climate1, soil1)
    assert climate1.cache_hit is False
    assert soil1.cache_hit is False
    assert combined1.cache_hit is False

    matrix2, climate2 = get_climate_score_vector(db, _climate())
    soil2 = get_soil_score_vector(db, matrix2, _soil(6.5))
    combined2 = get_combined_score_vector(matrix2, climate2, soil2)
    assert climate2.cache_hit is True
    assert soil2.cache_hit is True
    assert combined2.cache_hit is True
    assert climate2.key == climate1.key
    assert soil2.key == soil1.key

    # A soil-only change reuses climate but creates a new soil and ranking entry.
    matrix3, climate3 = get_climate_score_vector(db, _climate())
    soil3 = get_soil_score_vector(db, matrix3, _soil(5.5))
    combined3 = get_combined_score_vector(matrix3, climate3, soil3)
    assert climate3.cache_hit is True
    assert soil3.cache_hit is False
    assert combined3.cache_hit is False
    assert climate3.key == climate1.key
    assert soil3.key != soil1.key
    assert vector_cache_stats()["entries"] >= 5


def test_single_flight_computes_same_key_once():
    cache = ScientificVectorCache(max_bytes=1024 * 1024)
    barrier = threading.Barrier(4)
    calls = 0
    calls_lock = threading.Lock()

    def compute():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return 42

    def worker():
        barrier.wait()
        return cache.get_or_compute("same", compute)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = [future.result() for future in [executor.submit(worker) for _ in range(4)]]

    assert calls == 1
    assert [value for value, _ in results] == [42, 42, 42, 42]
    assert sum(1 for _, hit in results if not hit) == 1
    assert cache.stats()["single_flight_waits"] == 3


def test_byte_budget_evicts_lru_numpy_payload():
    import numpy as np

    cache = ScientificVectorCache(max_bytes=100)
    cache.put("a", np.zeros(10, dtype=np.float64))  # 80 bytes
    assert cache.get("a") is not None
    cache.put("b", np.zeros(10, dtype=np.float64))
    assert cache.get("a") is None
    assert cache.get("b") is not None
    assert cache.stats()["evictions"] == 1
