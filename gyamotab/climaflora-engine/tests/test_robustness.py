import math
import random

from app.domain.models import ClimateProfile, Confidence, EnvelopeLimit, Horizon, Scenario, SoilProfile, Status
from app.domain.scoring import score_limit, score_plant, score_soil


def climate(value: float | None) -> ClimateProfile:
    return ClimateProfile(
        latitude=47.16,
        longitude=-1.27,
        horizon=Horizon.Y2050,
        scenario=Scenario.MEDIUM,
        provider="ROBUSTNESS",
        period="2041-2070",
        variables={"bio01": value},
    )


def limit(*, fatal: bool = False) -> EnvelopeLimit:
    return EnvelopeLimit(
        variable="bio01",
        hard_low=0.0,
        optimum_low=10.0,
        optimum_high=30.0,
        hard_high=40.0,
        weight=1.0,
        group="M",
        fatal=fatal,
        confidence=Confidence.C,
    )


def test_score_is_bounded_and_deterministic_for_random_finite_inputs() -> None:
    rng = random.Random(20260819)
    spec = limit()
    for _ in range(5000):
        value = rng.uniform(-1000.0, 1000.0)
        first = score_limit(value, spec)
        second = score_limit(value, spec)
        assert first == second
        assert first.score is not None
        assert math.isfinite(first.score)
        assert 0.0 <= first.score <= 100.0


def test_exact_and_adjacent_envelope_boundaries_remain_bounded() -> None:
    spec = limit()
    values = [-1e-12, 0.0, 1e-12, 10.0 - 1e-12, 10.0, 30.0, 30.0 + 1e-12, 40.0, 40.0 + 1e-12]
    scores = [score_limit(value, spec).score for value in values]
    assert all(score is not None and 0.0 <= score <= 100.0 for score in scores)
    assert score_limit(10.0, spec).score == 100.0
    assert score_limit(30.0, spec).score == 100.0
    assert score_limit(-1e-12, spec).score == 0.0
    assert score_limit(40.0 + 1e-12, spec).score == 0.0


def test_fatal_climate_failure_cannot_be_rescued_across_soil_extremes() -> None:
    soil_limits = [
        EnvelopeLimit(
            variable="ph",
            hard_low=3.0,
            optimum_low=6.0,
            optimum_high=8.0,
            hard_high=10.0,
            weight=1.0,
            group="E",
            confidence=Confidence.C,
        )
    ]
    for ph in (3.0, 6.0, 7.0, 8.0, 10.0):
        result = score_plant(
            taxon_id="fatal",
            scientific_name="Testa fatalis",
            common_name=None,
            functions=[],
            limits=[limit(fatal=True)],
            climate=climate(100.0),
            soil=SoilProfile(
                latitude=47.16,
                longitude=-1.27,
                provider="ROBUSTNESS",
                properties={"ph": ph},
                confidence=Confidence.C,
            ),
            soil_limits=soil_limits,
        )
        assert result.overall_status == Status.RED
        assert result.combined_status == Status.RED


def test_missing_climate_stays_unknown_even_with_perfect_soil() -> None:
    result = score_plant(
        taxon_id="unknown",
        scientific_name="Testa incerta",
        common_name=None,
        functions=[],
        limits=[limit()],
        climate=climate(None),
        soil=SoilProfile(
            latitude=47.16,
            longitude=-1.27,
            provider="ROBUSTNESS",
            properties={"ph": 7.0, "cec_cmol_kg": 20.0},
            confidence=Confidence.C,
        ),
        soil_limits=[
            EnvelopeLimit(variable="ph", optimum_low=6.0, optimum_high=8.0, weight=0.5, group="E"),
            EnvelopeLimit(variable="cec_cmol_kg", optimum_low=10.0, optimum_high=30.0, weight=0.5, group="E"),
        ],
    )
    assert result.overall_status == Status.UNKNOWN
    assert result.combined_status == Status.UNKNOWN


def test_soil_requires_sufficient_known_evidence() -> None:
    profile = SoilProfile(
        latitude=47.16,
        longitude=-1.27,
        provider="ROBUSTNESS",
        properties={"ph": 7.0},
        confidence=Confidence.C,
    )
    limits = [
        EnvelopeLimit(variable="ph", optimum_low=6.0, optimum_high=8.0, weight=0.5, group="E"),
        EnvelopeLimit(variable="cec_cmol_kg", optimum_low=10.0, optimum_high=30.0, weight=0.5, group="E"),
    ]
    result = score_soil(profile, limits)
    assert result.score == 100.0
    assert result.known_weight_fraction == 0.5
    assert result.status == Status.UNKNOWN


def test_nan_climate_is_not_treated_as_compatible() -> None:
    component = score_limit(float("nan"), limit())
    assert component.status == Status.UNKNOWN
    assert component.score is None


def test_nan_soil_is_not_treated_as_compatible() -> None:
    profile = SoilProfile(
        latitude=47.16,
        longitude=-1.27,
        provider="ROBUSTNESS",
        properties={"ph": float("nan"), "cec_cmol_kg": 20.0},
        confidence=Confidence.C,
    )
    result = score_soil(
        profile,
        [
            EnvelopeLimit(variable="ph", hard_low=3.0, optimum_low=6.0, optimum_high=8.0, hard_high=10.0, weight=0.5, group="E"),
            EnvelopeLimit(variable="cec_cmol_kg", hard_low=2.0, optimum_low=10.0, optimum_high=30.0, hard_high=60.0, weight=0.5, group="E"),
        ],
    )
    ph = next(component for component in result.components if component.variable == "ph")
    assert ph.status == Status.UNKNOWN
    assert ph.score is None
    assert result.status == Status.UNKNOWN
