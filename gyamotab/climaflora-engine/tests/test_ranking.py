from types import SimpleNamespace

from app.domain.models import Status
from app.routers.api import _sort_key


def result(
    name: str,
    climate_status: Status,
    climate_score: float | None,
    combined_status: Status,
    combined_score: float | None,
    *,
    veto: bool = False,
):
    return SimpleNamespace(
        scientific_name=name,
        overall_status=climate_status,
        overall_score=climate_score,
        combined_status=combined_status,
        combined_score=combined_score,
        regulatory_veto=veto,
    )


def test_orange_climate_can_outrank_green_when_bi_axis_fit_is_better() -> None:
    green_climate_poor_soil = result(
        "Alpha",
        Status.GREEN,
        80.0,
        Status.ORANGE,
        60.0,
    )
    orange_climate_good_soil = result(
        "Beta",
        Status.ORANGE,
        70.0,
        Status.GREEN,
        78.0,
    )
    ordered = sorted([green_climate_poor_soil, orange_climate_good_soil], key=_sort_key)
    assert ordered[0].scientific_name == "Beta"


def test_red_climate_cannot_be_rescued_by_combined_score() -> None:
    acceptable = result("Alpha", Status.ORANGE, 55.0, Status.ORANGE, 55.0)
    red = result("Beta", Status.RED, 30.0, Status.GREEN, 99.0)
    ordered = sorted([red, acceptable], key=_sort_key)
    assert ordered[0].scientific_name == "Alpha"


def test_unknown_climate_stays_below_known_compatible_climate() -> None:
    known = result("Alpha", Status.ORANGE, 50.0, Status.ORANGE, 50.0)
    unknown = result("Beta", Status.UNKNOWN, None, Status.UNKNOWN, 100.0)
    ordered = sorted([unknown, known], key=_sort_key)
    assert ordered[0].scientific_name == "Alpha"


def test_regulatory_veto_is_always_deprioritized() -> None:
    allowed = result("Alpha", Status.ORANGE, 45.0, Status.ORANGE, 45.0)
    vetoed = result("Beta", Status.GREEN, 100.0, Status.GREEN, 100.0, veto=True)
    ordered = sorted([vetoed, allowed], key=_sort_key)
    assert ordered[0].scientific_name == "Alpha"
