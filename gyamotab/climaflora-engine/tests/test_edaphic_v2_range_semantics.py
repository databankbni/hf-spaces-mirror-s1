from app.domain.models import Confidence, EnvelopeLimit, Status
from app.domain.scoring import score_soil_limit


def test_range_only_soil_limit_is_compatible_without_claiming_optimum():
    limit = EnvelopeLimit(variable="ph", hard_low=4.8, hard_high=7.2, optimum_low=None, optimum_high=None, group="E", confidence=Confidence.B, source_ref="USDA")
    result = score_soil_limit(6.4, limit)
    assert result.score == 100.0
    assert result.status == Status.GREEN
    assert "plage de compatibilité" in result.explanation
    assert "aucun optimum" in result.explanation


def test_range_only_soil_limit_rejects_value_outside_documented_bounds():
    limit = EnvelopeLimit(variable="ph", hard_low=4.8, hard_high=7.2, optimum_low=None, optimum_high=None, group="E", confidence=Confidence.B, source_ref="USDA")
    result = score_soil_limit(7.8, limit)
    assert result.score == 0.0
    assert result.status == Status.RED
