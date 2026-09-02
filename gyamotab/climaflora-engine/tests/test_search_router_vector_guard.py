import importlib

import pytest

from app.config import Settings
from app.domain.models import ClimateProfile, Confidence, Horizon, Scenario, SoilProfile


class _ClimateProvider:
    def profile(self, lat, lon, horizon, scenario):
        return ClimateProfile(
            latitude=lat,
            longitude=lon,
            horizon=horizon,
            scenario=scenario,
            provider="CHELSA",
            model="test",
            period="2041-2070",
            variables={
                "bio01": 13.95,
                "bio05": 27.45,
                "bio06": 3.75,
                "bio12": 823.5,
                "bio15": 26.0,
            },
            provenance={"dataset": "CHELSA-bioclim", "version": "2.1", "manifest_revision": "test"},
        )


class _Repository:
    def readiness(self):
        return {"build_metadata": {}, "soil_preferences_ready": True}


def _soil(lat, lon):
    return SoilProfile(
        latitude=lat,
        longitude=lon,
        provider="SoilGrids 2.0 / ISRIC",
        properties={"ph": 6.5},
        confidence=Confidence.C,
        provenance={"access": "WCS 2.0.1", "prediction": "Q0.5"},
    )


def _legacy_result():
    return {
        "candidates": [],
        "metrics": {
            "catalog_total": 10,
            "after_type": 10,
            "after_function": 10,
            "evaluated_candidates": 10,
            "total_results": 10,
        },
        "facets": {
            "life_form": {},
            "functions": {},
            "climate_status": {},
            "soil_status": {},
        },
        "pagination": {
            "offset": 0,
            "limit": 50,
            "returned": 0,
            "has_previous": False,
            "has_next": True,
        },
        "search_token": "legacy-token",
        "cache_hit": False,
    }


def _search_router():
    # Import lazily so the router's legacy metadata patch cannot affect tests
    # collected/executed before this dedicated route-guard test module.
    return importlib.import_module("app.routers.search")


def _call(search_router, settings):
    return search_router.exhaustive_recommendations(
        lat=47.16,
        lon=-1.27,
        horizon=Horizon.Y2050,
        scenario=Scenario.MEDIUM,
        life_form="ALL",
        function=[],
        status=[],
        soil_status=[],
        offset=0,
        limit=50,
        soil_ph=None,
        soil_clay=None,
        soil_sand=None,
        soil_silt=None,
        soil_cec=None,
        soil_coarse_fragments=None,
        soil_soc=None,
        soil_nitrogen=None,
        soil_drainage=None,
        settings=settings,
    )


def test_vector_failure_falls_back_to_legacy_sql(monkeypatch):
    search_router = _search_router()
    legacy_calls = []
    monkeypatch.setattr(search_router, "_require_public_analysis", lambda settings: None)
    monkeypatch.setattr(search_router, "make_plant_repository", lambda path: _Repository())
    monkeypatch.setattr(search_router, "make_climate_provider", lambda *args: _ClimateProvider())
    monkeypatch.setattr(
        search_router,
        "_soil_profile",
        lambda settings, lat, lon, overrides: _soil(lat, lon),
    )
    monkeypatch.setattr(
        search_router,
        "vector_runtime_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("vector failed")),
    )
    monkeypatch.setattr(
        search_router,
        "exhaustive_search",
        lambda *args, **kwargs: legacy_calls.append(True) or _legacy_result(),
    )
    monkeypatch.setattr(search_router, "canonical_function_counts", lambda *args: {})

    result = _call(
        search_router,
        Settings(
            _env_file=None,
            search_vector_enabled=True,
            search_vector_fallback_enabled=True,
            master_bootstrap_enabled=False,
        ),
    )
    assert legacy_calls == [True]
    assert result["search_runtime"]["engine"] == "sqlite-exhaustive-fallback"
    assert any("repli automatique" in warning for warning in result["warnings"])


def test_vector_failure_is_not_hidden_when_fallback_disabled(monkeypatch):
    search_router = _search_router()
    monkeypatch.setattr(search_router, "_require_public_analysis", lambda settings: None)
    monkeypatch.setattr(search_router, "make_plant_repository", lambda path: _Repository())
    monkeypatch.setattr(search_router, "make_climate_provider", lambda *args: _ClimateProvider())
    monkeypatch.setattr(
        search_router,
        "_soil_profile",
        lambda settings, lat, lon, overrides: _soil(lat, lon),
    )
    monkeypatch.setattr(
        search_router,
        "vector_runtime_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("vector failed")),
    )

    with pytest.raises(RuntimeError, match="vector failed"):
        _call(
            search_router,
            Settings(
                _env_file=None,
                search_vector_enabled=True,
                search_vector_fallback_enabled=False,
                master_bootstrap_enabled=False,
            ),
        )
