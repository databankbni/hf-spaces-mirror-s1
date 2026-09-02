"""Confidence scoring utilities (card / finger / measurement / edge-quality).

Weights and thresholds are imported from confidence_constants.py.
"""

import logging
import numpy as np
from typing import Dict, Any, Optional

from .confidence_constants import (
    # Card confidence
    CARD_IDEAL_ASPECT_RATIO,
    CARD_MAX_ASPECT_DEVIATION,
    CARD_WEIGHT_DETECTION,
    CARD_WEIGHT_ASPECT,
    CARD_WEIGHT_SCALE,
    # Finger confidence
    FINGER_IDEAL_MIN_AREA_FRACTION,
    FINGER_IDEAL_MAX_AREA_FRACTION,
    FINGER_WEIGHT_HAND_DETECTION,
    FINGER_WEIGHT_MASK_VALIDITY,
    # Measurement confidence
    MEASUREMENT_CV_POOR,
    MEASUREMENT_CONSISTENCY_THRESHOLD,
    MEASUREMENT_OUTLIER_STD_MULTIPLIER,
    MEASUREMENT_WIDTH_TYPICAL_MIN,
    MEASUREMENT_WIDTH_TYPICAL_MAX,
    MEASUREMENT_WIDTH_ABSOLUTE_MIN,
    MEASUREMENT_WIDTH_ABSOLUTE_MAX,
    MEASUREMENT_WEIGHT_VARIANCE,
    MEASUREMENT_WEIGHT_CONSISTENCY,
    MEASUREMENT_WEIGHT_OUTLIERS,
    MEASUREMENT_WEIGHT_RANGE,
    MEASUREMENT_RANGE_SCORE_IDEAL,
    MEASUREMENT_RANGE_SCORE_BORDERLINE,
    MEASUREMENT_RANGE_SCORE_OUTSIDE,
    # Overall confidence
    WEIGHT_CARD,
    WEIGHT_FINGER,
    WEIGHT_EDGE_QUALITY,
    WEIGHT_MEASUREMENT,
    CONFIDENCE_LEVEL_HIGH_THRESHOLD,
    CONFIDENCE_LEVEL_MEDIUM_THRESHOLD,
)

logger = logging.getLogger(__name__)


def compute_card_confidence(
    card_result: Dict[str, Any],
    scale_confidence: float,
) -> float:
    """
    Compute confidence score from card detection.

    Uses constants:
    - CARD_IDEAL_ASPECT_RATIO: ISO/IEC 7810 ID-1 aspect ratio
    - CARD_MAX_ASPECT_DEVIATION: Maximum acceptable deviation (0.15)
    - CARD_WEIGHT_*: Component weights (detection: 50%, aspect: 25%, scale: 25%)

    Args:
        card_result: Output from detect_credit_card()
        scale_confidence: Scale calibration confidence

    Returns:
        Card confidence score [0, 1]
    """
    # Base confidence from card detection
    detection_conf = card_result.get("confidence", 0.0)

    # Aspect ratio deviation penalty
    aspect_ratio = card_result.get("aspect_ratio", 0.0)
    aspect_deviation = abs(aspect_ratio - CARD_IDEAL_ASPECT_RATIO) / CARD_IDEAL_ASPECT_RATIO

    # Penalize deviation beyond threshold
    aspect_score = max(0, 1.0 - (aspect_deviation / CARD_MAX_ASPECT_DEVIATION))

    # Combine components with weights
    card_conf = (
        CARD_WEIGHT_DETECTION * detection_conf +
        CARD_WEIGHT_ASPECT * aspect_score +
        CARD_WEIGHT_SCALE * scale_confidence
    )

    return float(np.clip(card_conf, 0, 1))


def compute_finger_confidence(
    hand_data: Dict[str, Any],
    finger_data: Dict[str, Any],
    mask_area: int,
    image_area: int,
) -> float:
    """
    Compute confidence score from finger detection.

    Uses constants:
    - FINGER_IDEAL_MIN_AREA_FRACTION: Minimum ideal mask area (0.5% of image)
    - FINGER_IDEAL_MAX_AREA_FRACTION: Maximum ideal mask area (5% of image)
    - FINGER_WEIGHT_*: Component weights (hand: 70%, mask: 30%)

    Args:
        hand_data: Output from segment_hand()
        finger_data: Output from isolate_finger()
        mask_area: Area of cleaned finger mask in pixels
        image_area: Total image area in pixels

    Returns:
        Finger confidence score [0, 1]
    """
    # Hand landmark detection confidence from MediaPipe
    hand_conf = hand_data.get("confidence", 0.0)

    # Mask area validity (should be reasonable fraction of image)
    mask_fraction = mask_area / image_area
    # Ideal range: FINGER_IDEAL_MIN_AREA_FRACTION to FINGER_IDEAL_MAX_AREA_FRACTION
    if mask_fraction < FINGER_IDEAL_MIN_AREA_FRACTION:
        area_score = mask_fraction / FINGER_IDEAL_MIN_AREA_FRACTION
    elif mask_fraction > FINGER_IDEAL_MAX_AREA_FRACTION:
        area_score = max(0, 1.0 - (mask_fraction - FINGER_IDEAL_MAX_AREA_FRACTION) / FINGER_IDEAL_MAX_AREA_FRACTION)
    else:
        area_score = 1.0

    # Combine components with weights
    finger_conf = FINGER_WEIGHT_HAND_DETECTION * hand_conf + FINGER_WEIGHT_MASK_VALIDITY * area_score

    return float(np.clip(finger_conf, 0, 1))


def compute_measurement_confidence(
    width_data: Dict[str, Any],
    median_width_cm: float,
) -> float:
    """Score measurement stability from per-sample width distribution."""
    widths_px = np.array(width_data.get("widths_px", []))

    if len(widths_px) == 0:
        return 0.0

    median_px = width_data.get("median_width_px", 0.0)
    mean_px = width_data.get("mean_width_px", 0.0)
    std_px = width_data.get("std_width_px", 0.0)

    # 1. Variance score (lower variance = higher confidence)
    coefficient_of_variation = std_px / (median_px + 1e-8)
    # CV < MEASUREMENT_CV_POOR is acceptable
    variance_score = max(0, 1.0 - coefficient_of_variation / MEASUREMENT_CV_POOR)

    # 2. Median-Mean consistency
    median_mean_diff = abs(median_px - mean_px) / (median_px + 1e-8)
    consistency_score = max(0, 1.0 - median_mean_diff / MEASUREMENT_CONSISTENCY_THRESHOLD)

    # 3. Outlier ratio (measurements far from median)
    outlier_threshold = MEASUREMENT_OUTLIER_STD_MULTIPLIER * std_px
    outliers = np.sum(np.abs(widths_px - median_px) > outlier_threshold)
    outlier_ratio = outliers / len(widths_px)
    outlier_score = max(0, 1.0 - outlier_ratio)

    # 4. Realistic range check
    if MEASUREMENT_WIDTH_TYPICAL_MIN <= median_width_cm <= MEASUREMENT_WIDTH_TYPICAL_MAX:
        range_score = MEASUREMENT_RANGE_SCORE_IDEAL
    elif MEASUREMENT_WIDTH_ABSOLUTE_MIN <= median_width_cm <= MEASUREMENT_WIDTH_ABSOLUTE_MAX:
        # Borderline acceptable
        range_score = MEASUREMENT_RANGE_SCORE_BORDERLINE
    else:
        # Outside realistic range
        range_score = MEASUREMENT_RANGE_SCORE_OUTSIDE

    # Combine components with weights
    measurement_conf = (
        MEASUREMENT_WEIGHT_VARIANCE * variance_score +
        MEASUREMENT_WEIGHT_CONSISTENCY * consistency_score +
        MEASUREMENT_WEIGHT_OUTLIERS * outlier_score +
        MEASUREMENT_WEIGHT_RANGE * range_score
    )

    return float(np.clip(measurement_conf, 0, 1))


def compute_edge_quality_confidence(
    edge_quality_data: Optional[Dict[str, Any]] = None
) -> float:
    """Return the SAM/Sobel edge-quality overall score clipped to [0, 1].

    Returns 1.0 when no edge-quality data is attached (shouldn't happen in the
    mask/sobel paths, but keeps the call site branch-free).
    """
    if edge_quality_data is None:
        return 1.0
    return float(np.clip(edge_quality_data.get("overall_score", 0.0), 0, 1))


def compute_overall_confidence(
    card_confidence: float,
    finger_confidence: float,
    measurement_confidence: float,
    edge_quality_confidence: float,
) -> Dict[str, Any]:
    """Combine the four component confidences into an overall score.

    Weights (from confidence_constants): card 25%, finger 25%, edge 20%,
    measurement 30%. Returns component scores + overall + HIGH/MEDIUM/LOW level.
    """
    overall = (
        WEIGHT_CARD * card_confidence
        + WEIGHT_FINGER * finger_confidence
        + WEIGHT_EDGE_QUALITY * edge_quality_confidence
        + WEIGHT_MEASUREMENT * measurement_confidence
    )
    overall = float(np.clip(overall, 0, 1))

    if overall > CONFIDENCE_LEVEL_HIGH_THRESHOLD:
        level = "high"
    elif overall >= CONFIDENCE_LEVEL_MEDIUM_THRESHOLD:
        level = "medium"
    else:
        level = "low"

    return {
        "card": float(card_confidence),
        "finger": float(finger_confidence),
        "measurement": float(measurement_confidence),
        "edge_quality": float(edge_quality_confidence),
        "overall": overall,
        "level": level,
    }
