from app.domain.models import (
    ClimateProfile,
    Confidence,
    EnvelopeLimit,
    Horizon,
    Scenario,
    SoilGeographicContext,
    SoilIndicatorPreference,
    SoilProfile,
    Status,
)
from app.domain.scoring import score_plant


def climate(variables: dict[str, float | None]) -> ClimateProfile:
    return ClimateProfile(
        latitude=47.16,
        longitude=-1.27,
        horizon=Horizon.Y2050,
        scenario=Scenario.MEDIUM,
        provider="TEST",
        period="2041-2070",
        variables=variables,
    )


def soil(**properties: float) -> SoilProfile:
    return SoilProfile(
        latitude=47.16,
        longitude=-1.27,
        provider="TEST",
        properties=properties,
        confidence=Confidence.C,
    )


def soil_limits() -> list[EnvelopeLimit]:
    return [
        EnvelopeLimit(
            variable="ph",
            hard_low=4.0,
            optimum_low=6.0,
            optimum_high=7.5,
            hard_high=9.0,
            weight=0.6,
            group="E",
            confidence=Confidence.C,
        ),
        EnvelopeLimit(
            variable="cec_cmol_kg",
            hard_low=2.0,
            optimum_low=8.0,
            optimum_high=30.0,
            hard_high=60.0,
            weight=0.4,
            group="E",
            confidence=Confidence.C,
        ),
    ]


def test_good_soil_cannot_rescue_red_climate() -> None:
    result = score_plant(
        taxon_id="t1",
        scientific_name="Testa fatalis",
        common_name=None,
        functions=[],
        limits=[
            EnvelopeLimit(
                variable="bio01",
                hard_low=0.0,
                optimum_low=10.0,
                optimum_high=30.0,
                hard_high=35.0,
                weight=1.0,
                group="M",
                fatal=True,
                confidence=Confidence.C,
            )
        ],
        climate=climate({"bio01": 40.0}),
        soil=soil(ph=7.0, cec_cmol_kg=15.0),
        soil_limits=soil_limits(),
    )
    assert result.overall_status == Status.RED
    assert result.soil.status == Status.GREEN
    assert result.combined_status == Status.RED


def test_unknown_climate_cannot_be_promoted_by_soil() -> None:
    result = score_plant(
        taxon_id="t2",
        scientific_name="Testa incerta",
        common_name=None,
        functions=[],
        limits=[
            EnvelopeLimit(variable="bio01", optimum_low=10, optimum_high=20, weight=0.8, group="M"),
            EnvelopeLimit(variable="bio12", optimum_low=800, optimum_high=1200, weight=0.2, group="M"),
        ],
        climate=climate({"bio01": None, "bio12": 1000.0}),
        soil=soil(ph=7.0, cec_cmol_kg=15.0),
        soil_limits=soil_limits(),
    )
    assert result.overall_status == Status.UNKNOWN
    assert result.soil.status == Status.GREEN
    assert result.combined_status == Status.UNKNOWN


def test_eive_and_geographic_prior_are_context_only() -> None:
    kwargs = dict(
        taxon_id="t3",
        scientific_name="Testa contextualis",
        common_name=None,
        functions=[],
        limits=[
            EnvelopeLimit(
                variable="bio01",
                hard_low=0,
                optimum_low=15,
                optimum_high=25,
                hard_high=35,
                weight=1.0,
                group="M",
                confidence=Confidence.C,
            )
        ],
        climate=climate({"bio01": 20.0}),
        soil=soil(ph=7.0, cec_cmol_kg=15.0),
        soil_limits=soil_limits(),
    )
    baseline = score_plant(**kwargs)
    contextual = score_plant(
        **kwargs,
        soil_indicators=[
            SoilIndicatorPreference(
                indicator="R",
                optimum=10.0,
                niche_width=0.1,
                confidence=Confidence.C,
                source_ref="EIVE",
            )
        ],
        soil_geographic_context=SoilGeographicContext(
            native_region_count=2,
            covered_region_count=2,
            variables={
                "ph": {
                    "outer_low": 2.0,
                    "central_low": 2.5,
                    "region_median": 3.0,
                    "central_high": 3.5,
                    "outer_high": 4.0,
                    "regions": 2,
                }
            },
            scoring_enabled=True,
            source_ref="TEST PRIOR",
        ),
    )
    assert contextual.overall_score == baseline.overall_score
    assert contextual.soil.score == baseline.soil.score
    assert contextual.combined_score == baseline.combined_score
    assert contextual.soil_geographic_context is not None
    assert contextual.soil_geographic_context.scoring_enabled is False
