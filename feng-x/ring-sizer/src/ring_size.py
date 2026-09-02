"""Ring size recommendation from calibrated finger width."""

from decimal import Decimal
from typing import Dict, List, Literal, Optional, Tuple

# Ring model definitions: model name → {size: inner_diameter_mm}
RING_MODELS: Dict[str, Dict[int, float]] = {
    "gen": {
        6: 16.9,
        7: 17.7,
        8: 18.6,
        9: 19.4,
        10: 20.3,
        11: 21.1,
        12: 21.9,
        13: 22.7,
    },
    "air": {
        6: 16.6,
        7: 17.4,
        8: 18.2,
        9: 19.0,
        10: 19.9,
        11: 20.7,
        12: 21.5,
        13: 22.3,
    },
}

VALID_RING_MODELS = list(RING_MODELS.keys())
DEFAULT_RING_MODEL = "gen"

# Backwards-compatible alias
RING_SIZE_CHART = RING_MODELS[DEFAULT_RING_MODEL]

# Diameter bounds for the ring-size lookup. Below MIN or above MAX,
# recommend_ring_size() returns None and aggregate_ring_sizes() tags the
# per-finger row as failed with diameter_below_chart_min / diameter_above_chart_max.
MIN_DIAMETER_MM = 12.0
MAX_DIAMETER_MM = 26.0


def _get_sorted_sizes(ring_model: str) -> List[Tuple[int, float]]:
    chart = RING_MODELS.get(ring_model, RING_MODELS[DEFAULT_RING_MODEL])
    return sorted(chart.items(), key=lambda x: x[1])


def recommend_ring_size(
    diameter_cm: float,
    ring_model: str = DEFAULT_RING_MODEL,
    *,
    prefer_smaller_on_tie: bool = False,
) -> Optional[Dict]:
    """Recommend ring size from calibrated finger outer diameter.

    When ``prefer_smaller_on_tie`` is true, exact midpoint ties are compared
    with decimal arithmetic and resolve to the smaller size. The default keeps
    the legacy per-photo lookup behavior.

    Returns dict with:
        - best_match: nearest ring size (int)
        - best_match_inner_mm: inner diameter of best match
        - range_min / range_max: recommended 2-size range
        - diameter_mm: input converted to mm
        - ring_model: which model chart was used
    Returns None if diameter is out of reasonable range.
    """
    diameter_mm = diameter_cm * 10.0

    if diameter_mm < MIN_DIAMETER_MM or diameter_mm > MAX_DIAMETER_MM:
        return None

    sorted_sizes = _get_sorted_sizes(ring_model)
    if prefer_smaller_on_tie:
        decision_mm = Decimal(str(diameter_cm)) * Decimal("10")

        def distance_key(size_and_diameter: Tuple[int, float]):
            size, inner_mm = size_and_diameter
            return abs(Decimal(str(inner_mm)) - decision_mm), size
    else:
        def distance_key(size_and_diameter: Tuple[int, float]):
            _, inner_mm = size_and_diameter
            return abs(inner_mm - diameter_mm)

    # Find nearest size
    # Session recommendations opt into a smaller-size exact-tie policy.
    # Decimal distances keep binary-float noise from turning a mathematical
    # tie into an upper-size result. Other callers retain the legacy lookup.
    best_size, best_inner = min(sorted_sizes, key=distance_key)

    # Find second nearest size
    second_size, second_inner = min(
        (s for s in sorted_sizes if s[0] != best_size),
        key=distance_key,
    )

    range_min = min(best_size, second_size)
    range_max = max(best_size, second_size)

    return {
        "best_match": best_size,
        "best_match_inner_mm": best_inner,
        "range_min": range_min,
        "range_max": range_max,
        "diameter_mm": round(diameter_mm, 2),
        "ring_model": ring_model,
    }


def aggregate_ring_sizes(per_finger_results: Dict[str, Dict]) -> Dict:
    """Aggregate ring size recommendations from multiple fingers.

    Args:
        per_finger_results: Dict mapping finger name to measurement result dict.
            Each value must have keys:
                - "finger_outer_diameter_cm": float or None
                - "confidence": float
                - "ring_size": dict from recommend_ring_size() or None
                - "fail_reason": str or None

    Returns:
        Dict with:
            - overall_best_size: int (consensus size if one exists in all
              fingers' ranges, otherwise confidence-weighted best size)
            - overall_range_min: int (min of all per-finger range_min)
            - overall_range_max: int (max of all per-finger range_max)
            - fingers_measured: int (total attempted)
            - fingers_succeeded: int (with valid measurement)
            - per_finger: dict of per-finger details
            - fail_reason: str or None (only if ALL fingers failed)
    """
    fingers_measured = len(per_finger_results)

    # Build per_finger summary
    per_finger: Dict[str, Dict] = {}
    for name, result in per_finger_results.items():
        rs = result.get("ring_size")
        upstream_reason = result.get("fail_reason")
        failed = upstream_reason is not None or rs is None

        # If the measurement succeeded but ring_size is None, the diameter
        # fell outside the chart bounds — surface that as a fail_reason so
        # the dashboard does not show "failed, reason unknown".
        derived_reason = upstream_reason
        if derived_reason is None and rs is None:
            diameter_cm = result.get("finger_outer_diameter_cm")
            if diameter_cm is None:
                derived_reason = "ring_size_lookup_failed"
            elif diameter_cm * 10.0 < MIN_DIAMETER_MM:
                derived_reason = "diameter_below_chart_min"
            elif diameter_cm * 10.0 > MAX_DIAMETER_MM:
                derived_reason = "diameter_above_chart_max"
            else:
                derived_reason = "ring_size_lookup_failed"

        per_finger[name] = {
            "diameter_cm": result.get("finger_outer_diameter_cm"),
            "confidence": result.get("confidence", 0.0),
            "best_match": rs["best_match"] if rs else None,
            "range": [rs["range_min"], rs["range_max"]] if rs else None,
            "status": "failed" if failed else "ok",
            "fail_reason": derived_reason,
        }

    # Filter to succeeded fingers
    succeeded = {
        name: info for name, info in per_finger.items() if info["status"] == "ok"
    }

    if not succeeded:
        return {
            "fail_reason": "all_fingers_failed",
            "fingers_measured": fingers_measured,
            "fingers_succeeded": 0,
            "per_finger": per_finger,
        }

    # Confidence-weighted voting for best size
    vote_tally: Dict[int, float] = {}
    for info in succeeded.values():
        size = info["best_match"]
        vote_tally[size] = vote_tally.get(size, 0.0) + info["confidence"]

    weighted_best_size = max(vote_tally, key=lambda s: vote_tally[s])

    # Intersection-first override: if a size falls in every finger's range, prefer it
    all_ranges = [set(range(info["range"][0], info["range"][1] + 1))
                  for info in succeeded.values()]
    consensus_sizes = set.intersection(*all_ranges) if all_ranges else set()

    if consensus_sizes:
        # Pick the consensus size closest to the confidence-weighted winner
        overall_best_size = min(consensus_sizes,
                                key=lambda s: abs(s - weighted_best_size))
    else:
        overall_best_size = weighted_best_size

    # Aggregate range
    overall_range_min = min(info["range"][0] for info in succeeded.values())
    overall_range_max = max(info["range"][1] for info in succeeded.values())

    # Ensure range covers best size
    if overall_best_size < overall_range_min:
        overall_range_min = overall_best_size
    if overall_best_size > overall_range_max:
        overall_range_max = overall_best_size

    return {
        "overall_best_size": overall_best_size,
        "overall_range_min": overall_range_min,
        "overall_range_max": overall_range_max,
        "fingers_measured": fingers_measured,
        "fingers_succeeded": len(succeeded),
        "per_finger": per_finger,
        "fail_reason": None,
    }
