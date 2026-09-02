from app.config import Settings
from app.domain.models import ClimateProfile, Confidence, Horizon, Scenario, SoilProfile
from app.services.search_runtime import (
    climate_scientific_signature,
    soil_scientific_signature,
    timed_call,
)
from app.version import (
    METHOD_VERSION,
    SEARCH_CACHE_FORMAT_VERSION,
    SEARCH_RUNTIME_FORMAT_VERSION,
)


def test_search_runtime_versions_are_independent_from_scientific_method():
    assert METHOD_VERSION == "climaflora-score-0.6.0"
    assert SEARCH_RUNTIME_FORMAT_VERSION.startswith("search-runtime-")
    assert SEARCH_CACHE_FORMAT_VERSION.startswith("search-cache-")
    assert SEARCH_RUNTIME_FORMAT_VERSION != METHOD_VERSION
    assert SEARCH_CACHE_FORMAT_VERSION != METHOD_VERSION


def test_vector_runtime_is_guarded_off_by_default():
    settings = Settings(_env_file=None)
    assert settings.search_vector_enabled is False
    assert settings.search_vector_fallback_enabled is True


def test_timed_call_returns_value_and_timing():
    value, elapsed_ms, error = timed_call(lambda x: x + 1, 41)
    assert value == 42
    assert elapsed_ms >= 0.0
    assert error is None


def test_timed_call_captures_provider_failure_for_caller_fallback():
    def fail():
        raise RuntimeError("provider unavailable")

    value, elapsed_ms, error = timed_call(fail)
    assert value is None
    assert elapsed_ms >= 0.0
    assert isinstance(error, RuntimeError)
    assert str(error) == "provider unavailable"


def _climate(latitude: float, longitude: float, *, bio01: float = 13.95, revision: str = "r1") -> ClimateProfile:
    return ClimateProfile(
        latitude=latitude,
        longitude=longitude,
        horizon=Horizon.Y2050,
        scenario=Scenario.MEDIUM,
        provider="CHELSA",
        model="ensemble-median-3-members",
        period="2041-2070",
        variables={
            "bio01": bio01,
            "bio05": 27.45,
            "bio06": 3.75,
            "bio12": 823.5,
            "bio15": 26.0,
        },
        provenance={
            "dataset": "CHELSA-bioclim",
            "version": "2.1",
            "manifest_revision": revision,
            "scenario_mapping": "ssp370",
        },
    )


def _soil(latitude: float, longitude: float, *, ph: float = 6.5, fallback: float = 0.0) -> SoilProfile:
    return SoilProfile(
        latitude=latitude,
        longitude=longitude,
        provider="SoilGrids 2.0 / ISRIC",
        depth="5-15cm",
        resolution_m=250,
        properties={
            "ph": ph,
            "clay_pct": 20.0,
            "sand_pct": 45.0,
            "silt_pct": 35.0,
            "cec_cmol_kg": 14.0,
            "coarse_fragments_pct": 4.0,
            "soc_g_kg": 18.0,
            "nitrogen_g_kg": 1.5,
            "drainage": "well_drained",
            "texture": "texture mixte",
            "texture_class": "medium",
        },
        confidence=Confidence.C,
        provenance={
            "access": "WCS 2.0.1",
            "prediction": "Q0.5",
            "wcs_base": "https://maps.isric.org/mapserv",
            "fallback_distance_m": {"ph": fallback},
        },
    )


def test_climate_signature_uses_resolved_scoring_vector_not_coordinate_rounding():
    first = _climate(47.1601, -1.2701)
    same_scientific_input_elsewhere = _climate(47.1609, -1.2709)
    assert climate_scientific_signature(first) == climate_scientific_signature(same_scientific_input_elsewhere)

    changed_value = _climate(47.1601, -1.2701, bio01=13.950000000000001)
    assert climate_scientific_signature(first) != climate_scientific_signature(changed_value)

    changed_source = _climate(47.1601, -1.2701, revision="r2")
    assert climate_scientific_signature(first) != climate_scientific_signature(changed_source)


def test_soil_signature_uses_resolved_properties_not_coordinate_or_fallback_distance():
    first = _soil(47.1601, -1.2701, fallback=0.0)
    same_scientific_input_elsewhere = _soil(47.1619, -1.2719, fallback=1200.0)
    assert soil_scientific_signature(first) == soil_scientific_signature(same_scientific_input_elsewhere)

    changed_ph = _soil(47.1601, -1.2701, ph=6.6)
    assert soil_scientific_signature(first) != soil_scientific_signature(changed_ph)
