import json

from app.domain.models import Horizon, Scenario
from app.services.climate import ChelsaCogProvider
from app.services.plants import make_plant_repository
from app.services.soil import make_soil_provider


def test_soil_factory_reuses_provider_and_cache() -> None:
    make_soil_provider.cache_clear()
    first = make_soil_provider("soilgrids_wcs", "https://maps.isric.org/mapserv")
    second = make_soil_provider("soilgrids_wcs", "https://maps.isric.org/mapserv")
    assert first is second


def test_plant_repository_factory_reuses_instance(tmp_path) -> None:
    database = tmp_path / "catalog.sqlite"
    database.touch()
    first = make_plant_repository(str(database))
    second = make_plant_repository(str(database))
    assert first is second


def test_chelsa_profile_is_bounded_cached(tmp_path, monkeypatch) -> None:
    profiles = {h.value: {} for h in Horizon}
    profiles[Horizon.Y2050.value][Scenario.MEDIUM.value] = {
        "period": "2041-2070",
        "model": "TEST",
        "scenario": "ssp370",
        "variables": {"bio01": {"path": "unused", "unit": "C"}},
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"profiles": profiles}))
    provider = ChelsaCogProvider(str(manifest))
    calls = {"count": 0}

    def fake_sample(spec, longitude, latitude):
        calls["count"] += 1
        return 12.5

    monkeypatch.setattr(provider, "_sample", fake_sample)
    first = provider.profile(47.16, -1.27, Horizon.Y2050, Scenario.MEDIUM)
    second = provider.profile(47.16, -1.27, Horizon.Y2050, Scenario.MEDIUM)
    assert first.variables == second.variables == {"bio01": 12.5}
    assert calls["count"] == 1


def test_readonly_sqlite_tuning_keeps_connection_queryable(tmp_path) -> None:
    import sqlite3
    from app.services.plants import DerivedSqlitePlantRepository

    database = tmp_path / "catalog.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE sample(value INTEGER)")
        conn.execute("INSERT INTO sample VALUES (1)")
    repository = DerivedSqlitePlantRepository(str(database))
    with repository._connect() as conn:
        assert conn.execute("SELECT value FROM sample").fetchone()[0] == 1
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1


def test_plant_repository_does_not_cache_missing_bootstrap_state(tmp_path) -> None:
    import sqlite3
    from app.services.plants import DerivedSqlitePlantRepository, UnavailablePlantRepository

    database = tmp_path / "appearing-catalog.sqlite"
    missing = make_plant_repository(str(database))
    assert isinstance(missing, UnavailablePlantRepository)

    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE marker(value INTEGER)")
    available = make_plant_repository(str(database))
    assert isinstance(available, DerivedSqlitePlantRepository)
    assert available is make_plant_repository(str(database))


def test_candidate_pool_cache_reuses_identical_rank_and_hydration(monkeypatch, tmp_path) -> None:
    from contextlib import nullcontext
    from app.services.plants import DerivedSqlitePlantRepository

    database = tmp_path / "catalog.sqlite"
    database.touch()
    repository = DerivedSqlitePlantRepository(str(database))
    calls = {"rank": 0, "hydrate": 0}

    monkeypatch.setattr(repository, "_connect", lambda: nullcontext(object()))

    def ranked(conn, functions, limit, climate_variables, soil_variables):
        calls["rank"] += 1
        return [object()]

    def hydrate(conn, plants):
        calls["hydrate"] += 1
        return [{"taxon_id": "t1", "marker": calls["hydrate"]}]

    monkeypatch.setattr(repository, "_ranked_plant_rows", ranked)
    monkeypatch.setattr(repository, "_hydrate", hydrate)

    kwargs = {
        "functions": ["FOOD_HUMAN"],
        "limit": 1000,
        "climate_variables": {"bio01": 12.5, "bio12": 850.0},
        "soil_variables": {"ph": 6.5, "cec_cmol_kg": 15.0},
    }
    first = repository.iter_candidates(**kwargs)
    second = repository.iter_candidates(**kwargs)
    assert first == second
    assert calls == {"rank": 1, "hydrate": 1}

    repository.iter_candidates(**{**kwargs, "soil_variables": {"ph": 7.0, "cec_cmol_kg": 15.0}})
    assert calls == {"rank": 2, "hydrate": 2}


def test_candidate_cache_key_normalizes_nonfinite_values() -> None:
    from app.services.plants import DerivedSqlitePlantRepository, RANKABLE_VARIABLES

    key = DerivedSqlitePlantRepository._numeric_cache_key(
        {"bio01": float("nan"), "bio05": float("inf"), "bio06": 3},
        RANKABLE_VARIABLES,
    )
    values = dict(key)
    assert values["bio01"] is None
    assert values["bio05"] is None
    assert values["bio06"] == 3.0
