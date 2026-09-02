"""Session-level median recommendations for repeated web measurements.

The computer-vision pipeline continues to produce one raw result per photo.
This module accumulates the successful calibrated diameters returned by those
results and derives a separate recommendation from their per-finger median.
It is deliberately independent of Flask and Supabase so local/offline runs use
the same logic as production.
"""

from __future__ import annotations

import hashlib
import math
import re
import statistics
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Mapping, Optional, Tuple

from src.ring_size import aggregate_ring_sizes, recommend_ring_size

SESSION_STATE_VERSION = 1
MAX_SESSION_SHOTS = 20
MIN_STATE_DIAMETER_CM = 1.0
MAX_STATE_DIAMETER_CM = 3.0

FINGER_ORDER = ("index", "middle", "ring", "pinky")
VALID_FINGERS = set(FINGER_ORDER)
VALID_HANDEDNESS = {"Left", "Right", "Unknown"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _size_decision_diameter_mm(median_cm: float) -> float:
    """Quantize a session median to the supported 0.1 mm decision precision."""
    median_mm = Decimal(str(median_cm)) * Decimal("10")
    return float(median_mm.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def image_sha256(data: bytes) -> str:
    """Return a stable content fingerprint for duplicate-shot detection."""
    return hashlib.sha256(data).hexdigest()


def normalize_session_id(value: Any) -> Optional[str]:
    """Return a canonical UUID string, or None for absent/malformed input."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return str(uuid.UUID(value.strip()))
    except (ValueError, AttributeError):
        return None


def _empty_state(session_id: str, ring_model: str) -> Dict[str, Any]:
    return {
        "version": SESSION_STATE_VERSION,
        "session_id": session_id,
        "ring_model": ring_model,
        "attempt_count": 0,
        "shots": [],
    }


def _finite_diameter(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    diameter = float(value)
    if not math.isfinite(diameter):
        return None
    if diameter < MIN_STATE_DIAMETER_CM or diameter > MAX_STATE_DIAMETER_CM:
        return None
    return round(diameter, 4)


def _sanitize_state(
    previous_state: Any,
    *,
    session_id: str,
    ring_model: str,
) -> Dict[str, Any]:
    """Validate untrusted browser-returned state and enforce a small bound."""
    fresh = _empty_state(session_id, ring_model)
    if not isinstance(previous_state, Mapping):
        return fresh
    if previous_state.get("version") != SESSION_STATE_VERSION:
        return fresh
    if normalize_session_id(previous_state.get("session_id")) != session_id:
        return fresh
    if previous_state.get("ring_model") != ring_model:
        return fresh

    attempt_count = previous_state.get("attempt_count", 0)
    if isinstance(attempt_count, bool) or not isinstance(attempt_count, int):
        attempt_count = 0
    fresh["attempt_count"] = max(0, min(attempt_count, 10_000))

    raw_shots = previous_state.get("shots")
    if not isinstance(raw_shots, list):
        return fresh

    shots = []
    for raw_shot in raw_shots[-MAX_SESSION_SHOTS:]:
        if not isinstance(raw_shot, Mapping):
            continue
        handedness = raw_shot.get("handedness")
        if handedness not in VALID_HANDEDNESS:
            continue
        digest = raw_shot.get("image_sha256")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            continue
        raw_per_finger = raw_shot.get("per_finger")
        if not isinstance(raw_per_finger, Mapping):
            continue
        per_finger: Dict[str, float] = {}
        for finger, value in raw_per_finger.items():
            if finger not in VALID_FINGERS:
                continue
            diameter = _finite_diameter(value)
            if diameter is not None:
                per_finger[finger] = diameter
        if not per_finger:
            continue
        shots.append({
            "run_id": str(raw_shot.get("run_id") or "")[:64],
            "image_sha256": digest,
            "handedness": handedness,
            "per_finger": per_finger,
        })

    fresh["shots"] = shots[-MAX_SESSION_SHOTS:]
    return fresh


def _result_handedness(result: Mapping[str, Any]) -> str:
    handedness = result.get("handedness")
    return handedness if handedness in VALID_HANDEDNESS else "Unknown"


def _successful_current_samples(
    result: Mapping[str, Any],
    *,
    mode: str,
    finger_index: str,
) -> Dict[str, float]:
    samples: Dict[str, float] = {}
    if mode == "multi":
        per_finger = result.get("per_finger")
        if not isinstance(per_finger, Mapping):
            return samples
        for finger in FINGER_ORDER:
            item = per_finger.get(finger)
            if not isinstance(item, Mapping) or item.get("status") != "ok":
                continue
            diameter = _finite_diameter(item.get("diameter_cm"))
            if diameter is not None:
                samples[finger] = diameter
        return samples

    if result.get("fail_reason") is not None:
        return samples
    finger = finger_index if finger_index in VALID_FINGERS else "index"
    diameter = _finite_diameter(result.get("finger_outer_diameter_cm"))
    if diameter is not None:
        samples[finger] = diameter
    return samples


def _recommend_for_hand(
    state: Mapping[str, Any],
    *,
    handedness: str,
    ring_model: str,
    current_result: Mapping[str, Any],
    mode: str,
    finger_index: str,
    current_shot_included: bool,
    duplicate_image: bool,
) -> Optional[Dict[str, Any]]:
    values: Dict[str, list] = {finger: [] for finger in FINGER_ORDER}
    successful_shots = 0
    for shot in state.get("shots", []):
        if shot.get("handedness") != handedness:
            continue
        successful_shots += 1
        for finger, diameter in shot.get("per_finger", {}).items():
            if finger in values:
                values[finger].append(float(diameter))

    synthetic: Dict[str, Dict[str, Any]] = {}
    stats: Dict[str, Dict[str, Any]] = {}
    for finger in FINGER_ORDER:
        finger_values = values[finger]
        if not finger_values:
            continue
        # Inputs are stored to 4 decimal places in cm, so an even-sized median
        # can contain one additional decimal place. Preserve that value for
        # auditability, but quantize the value used for discrete size lookup to
        # 0.1 mm. This avoids invisible hundredths of a millimetre flipping a
        # recommendation while the UI displays the same one-decimal diameter.
        median_cm = round(float(statistics.median(finger_values)), 5)
        decision_diameter_mm = _size_decision_diameter_mm(median_cm)
        spread_mm = round((max(finger_values) - min(finger_values)) * 10.0, 2)
        ring_size = recommend_ring_size(
            decision_diameter_mm / 10.0,
            ring_model=ring_model,
            prefer_smaller_on_tie=True,
        )
        synthetic[finger] = {
            "finger_outer_diameter_cm": median_cm,
            # Session confidence is intentionally not invented. Equal weights
            # keep the legacy cross-finger aggregator deterministic without
            # reusing the non-predictive per-shot confidence score.
            "confidence": 1.0,
            "ring_size": ring_size,
            "fail_reason": None,
        }
        stats[finger] = {
            "sample_count": len(finger_values),
            "spread_mm": spread_mm,
            "decision_diameter_mm": decision_diameter_mm,
        }

    if not synthetic:
        return None

    aggregated = aggregate_ring_sizes(synthetic)
    per_finger = aggregated.get("per_finger", {})
    for finger, finger_stats in stats.items():
        if finger in per_finger:
            # The equal weight above is only an internal tie-breaker for the
            # legacy cross-finger aggregator, not a claim of 100% confidence.
            per_finger[finger].pop("confidence", None)
            per_finger[finger].update(finger_stats)

    # Preserve a failed current-finger card when no earlier success exists,
    # keeping first-shot rendering equivalent to the raw multi result.
    if mode == "multi":
        current_per_finger = current_result.get("per_finger")
        if isinstance(current_per_finger, Mapping):
            for finger in FINGER_ORDER:
                current_item = current_per_finger.get(finger)
                if finger not in per_finger and isinstance(current_item, Mapping):
                    per_finger[finger] = dict(current_item)
                    per_finger[finger]["sample_count"] = 0
                    per_finger[finger]["spread_mm"] = None
                    per_finger[finger]["decision_diameter_mm"] = None

        aggregated["fingers_measured"] = len(per_finger)
        aggregated["fingers_succeeded"] = sum(
            item.get("status") == "ok" for item in per_finger.values()
        )

    recommendation: Dict[str, Any] = {
        **aggregated,
        "basis": "session_median",
        "session_id": state["session_id"],
        "attempt_index": state["attempt_count"],
        "handedness": handedness,
        "successful_shots": successful_shots,
        "current_shot_included": current_shot_included,
        "duplicate_image": duplicate_image,
    }

    if mode != "multi":
        finger = finger_index if finger_index in VALID_FINGERS else "index"
        finger_rec = per_finger.get(finger)
        if finger_rec and finger_rec.get("status") == "ok":
            recommendation["finger_index"] = finger
            recommendation["finger_outer_diameter_cm"] = finger_rec["diameter_cm"]
            recommendation["ring_size"] = synthetic[finger]["ring_size"]
    return recommendation


def update_session_recommendation(
    previous_state: Any,
    *,
    session_id: str,
    ring_model: str,
    run_id: str,
    image_digest: str,
    result: Mapping[str, Any],
    mode: str,
    finger_index: str = "index",
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Add one attempt and return `(updated_state, recommendation)`.

    `result` must be the calibrated raw result for the current photo. The
    returned recommendation is for the current detected hand only. A total
    current-shot failure increments the attempt counter but returns no stale
    recommendation to the UI.
    """
    canonical_id = normalize_session_id(session_id)
    if canonical_id is None:
        raise ValueError("session_id must be a valid UUID")
    if not _SHA256_RE.fullmatch(image_digest or ""):
        raise ValueError("image_digest must be a SHA-256 hex digest")

    state = _sanitize_state(
        previous_state,
        session_id=canonical_id,
        ring_model=ring_model,
    )
    state["attempt_count"] += 1

    current_samples = _successful_current_samples(
        result,
        mode=mode,
        finger_index=finger_index,
    )
    handedness = _result_handedness(result)
    duplicate = any(
        shot.get("image_sha256") == image_digest for shot in state["shots"]
    )
    included = bool(current_samples) and not duplicate
    if included:
        state["shots"].append({
            "run_id": str(run_id or "")[:64],
            "image_sha256": image_digest,
            "handedness": handedness,
            "per_finger": current_samples,
        })
        state["shots"] = state["shots"][-MAX_SESSION_SHOTS:]

    # Do not surface an old recommendation on top of a total current failure.
    if not current_samples:
        return state, None

    recommendation = _recommend_for_hand(
        state,
        handedness=handedness,
        ring_model=ring_model,
        current_result=result,
        mode=mode,
        finger_index=finger_index,
        current_shot_included=included,
        duplicate_image=duplicate,
    )
    return state, recommendation
