#!/usr/bin/env python3
"""
Finger Outer Diameter Measurement Tool

Measures the outer width (diameter) of a finger at the ring-wearing zone
using a single RGB image with a credit card as a physical size reference.

Usage:
    python measure_finger.py --input image.jpg --output result.json [--debug]
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List, Literal, Tuple

import cv2
import numpy as np

from src import cli_display
from src.logging_config import configure_logging, log_phase, log_phase_summary
from src.image_quality import assess_image_quality
from src.card_detection import detect_credit_card, compute_scale_factor
from src.sam_card_detection import (
    detect_credit_card_sam_prompt,
    suggest_card_seeds,
)
from src.finger_segmentation import segment_hand, isolate_finger, clean_mask, get_finger_contour
from src.geometry import estimate_finger_axis, localize_ring_zone, localize_ring_zone_from_landmarks
from src.edge_refinement import refine_edges_sobel, MIN_MASK_SAMPLES
from src.confidence import (
    compute_card_confidence,
    compute_finger_confidence,
    compute_measurement_confidence,
    compute_edge_quality_confidence,
    compute_overall_confidence,
)
from src.debug_observer import draw_comprehensive_edge_overlay, draw_hand_skeleton
from src.visualization import draw_card_overlay
from src.viz_constants import Color
from src.ring_size import recommend_ring_size, aggregate_ring_sizes, VALID_RING_MODELS, DEFAULT_RING_MODEL
from src.image_quality import (
    check_card_in_frame,
    check_finger_spacing,
    check_lighting_uniformity,
)

logger = logging.getLogger(__name__)

# Calibration coefficients (from regression on 60 measurements)
_CALIBRATION_PATH = Path(__file__).parent / "src" / "calibration.json"

def _load_calibration() -> dict:
    """Load calibration coefficients from JSON."""
    with open(_CALIBRATION_PATH) as f:
        return json.load(f)

def apply_calibration(raw_diameter_cm: float) -> float:
    """Apply linear regression calibration: actual = slope * raw + intercept."""
    cal = _load_calibration()
    return cal["slope"] * raw_diameter_cm + cal["intercept"]

# Minimum ratio of (longer card side) / (shorter image side). Below this
# the camera is too far from the table: the card and finger occupy so few
# pixels that edge refinement noise and calibration extrapolation both
# start to dominate. See doc/report/framing_ratio_survey.md — calibration
# was fit at ~0.48, production median is ~0.33; 0.33 cuts at the historical
# median (~50% rejection on the existing kol_success snapshot).
MIN_CARD_LONG_SIDE_RATIO = 0.33

# Type alias for finger selection
FingerIndex = Literal["auto", "index", "middle", "ring", "pinky"]


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Measure finger outer diameter from an image with credit card reference.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python measure_finger.py --input photo.jpg --output result.json
    python measure_finger.py --input photo.jpg --output result.json --debug
    python measure_finger.py --input photo.jpg --output result.json --finger-index ring
    python measure_finger.py --input photo.jpg --output result.json --finger-index middle
        """,
    )

    # Required arguments
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Path to input image (JPG/PNG)",
    )
    parser.add_argument(
        "--output",
        type=str,
        required=True,
        help="Path to output JSON file",
    )

    # Optional arguments
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Save intermediate debug images (card_detection_debug/, edge_refinement_debug/, etc.)",
    )
    parser.add_argument(
        "--save-intermediate",
        action="store_true",
        help="Save intermediate processing artifacts",
    )
    parser.add_argument(
        "--finger-index",
        type=str,
        choices=["auto", "index", "middle", "ring", "pinky"],
        default="index",
        help="Which finger to measure (default: index). 'auto' detects the most extended finger.",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.7,
        help="Minimum confidence threshold (default: 0.7)",
    )

    parser.add_argument(
        "--edge-method",
        type=str,
        default="mask",
        choices=["mask", "sobel"],
        help="Edge detection method: 'mask' (SAM boundary directly, default) or 'sobel' (subpixel gradient refinement anchored on SAM boundary)",
    )
    parser.add_argument(
        "--sobel-threshold",
        type=float,
        default=15.0,
        help="Minimum gradient magnitude for valid edge (default: 15.0)",
    )
    parser.add_argument(
        "--sobel-kernel-size",
        type=int,
        default=3,
        choices=[3, 5, 7],
        help="Sobel kernel size (default: 3)",
    )
    parser.add_argument(
        "--no-subpixel",
        action="store_true",
        help="Disable sub-pixel edge refinement",
    )

    # Measurement mode
    parser.add_argument(
        "--mode",
        type=str,
        choices=["single", "multi"],
        default="single",
        help="Measurement mode: single (one finger) or multi (index+middle+ring at once) (default: single)",
    )

    # Ring model
    parser.add_argument(
        "--ring-model",
        type=str,
        choices=VALID_RING_MODELS,
        default=DEFAULT_RING_MODEL,
        help=f"Ring model for size recommendation (default: {DEFAULT_RING_MODEL})",
    )

    # Calibration
    parser.add_argument(
        "--no-calibration",
        action="store_true",
        help="Disable regression calibration (output raw measurement only)",
    )

    # Testing/debugging options
    parser.add_argument(
        "--skip-card-detection",
        action="store_true",
        help="[TESTING ONLY] Skip card detection and use dummy scale (allows testing finger segmentation without card)",
    )
    parser.add_argument(
        "--card-method",
        type=str,
        choices=["classic", "sam"],
        default="classic",
        help="Card detection backend: 'classic' (Canny/adaptive/Otsu/color waterfall) or 'sam' (SAM 2.1 mask segmentation). Default: classic.",
    )

    return parser.parse_args()


def validate_input(input_path: str) -> Optional[str]:
    """
    Validate input file exists and is a supported image format.

    Args:
        input_path: Path to input image

    Returns:
        Error message if validation fails, None if valid
    """
    path = Path(input_path)

    if not path.exists():
        return f"Input file not found: {input_path}"

    if not path.is_file():
        return f"Input path is not a file: {input_path}"

    suffix = path.suffix.lower()
    if suffix not in [".jpg", ".jpeg", ".png"]:
        return f"Unsupported image format: {suffix}. Use JPG or PNG."

    return None


def load_image(input_path: str) -> Optional[np.ndarray]:
    """
    Load image from file.

    Args:
        input_path: Path to input image

    Returns:
        BGR image as numpy array, or None if load fails
    """
    image = cv2.imread(input_path)
    return image


def create_output(
    finger_diameter_cm: Optional[float] = None,
    confidence: float = 0.0,
    scale_px_per_cm: Optional[float] = None,
    card_detected: bool = False,
    finger_detected: bool = False,
    view_angle_ok: bool = True,
    fail_reason: Optional[str] = None,
    edge_method_used: Optional[str] = None,
    card_metrics: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Create output dictionary matching the PRD specification."""
    output = {
        "finger_outer_diameter_cm": float(finger_diameter_cm) if finger_diameter_cm is not None else None,
        "confidence": float(round(confidence, 3)),
        "scale_px_per_cm": round(float(scale_px_per_cm), 2) if scale_px_per_cm is not None else None,
        "quality_flags": {
            "card_detected": bool(card_detected),
            "finger_detected": bool(finger_detected),
            "view_angle_ok": bool(view_angle_ok),
        },
        "fail_reason": fail_reason,
    }

    if edge_method_used is not None:
        output["edge_method_used"] = edge_method_used
    if card_metrics is not None:
        output["card_metrics"] = card_metrics

    return output


def _build_card_metrics(
    card_result: Dict[str, Any],
    scale_confidence: float,
    image_canonical_shape: Tuple[int, int],
) -> Dict[str, float]:
    """Diagnostic metrics for the SAM-detected card. Same definitions as
    doc/report/aspect_and_scale_survey.md and doc/report/framing_ratio_survey.md.
    """
    longer_card_px = max(float(card_result["width_px"]), float(card_result["height_px"]))
    shorter_image_px = float(min(image_canonical_shape[0], image_canonical_shape[1]))
    return {
        "aspect_ratio": round(float(card_result["aspect_ratio"]), 4),
        "framing_ratio": round(longer_card_px / shorter_image_px, 4),
        "scale_confidence": round(float(scale_confidence), 4),
    }


def save_output(output: Dict[str, Any], output_path: str) -> None:
    """Save output dictionary to JSON file."""
    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    def _numpy_json_default(value: Any) -> Any:
        """Normalize NumPy values emitted by multi-finger geometry helpers."""
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=_numpy_json_default)


# Debug visualisations are for human inspection, so there's no reason to
# write a 12-megapixel PNG (encoding alone can take 1–2s on CPU). Cap the
# long side and encode as JPEG — the on-disk path keeps its .png extension
# for backwards compat with existing callers, but we write JPEG bytes when
# the downscale is active to keep encoding well under ~100ms.
_DEBUG_VIS_MAX_LONG_SIDE = 1600


def _overlay_hand_skeleton(
    image: np.ndarray,
    landmarks: Optional[np.ndarray],
    rotation_matrix: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Draw the 21-point MediaPipe hand skeleton onto a debug image.

    Landmarks are assumed to be in the canonical-image frame. If a precise
    rotation was applied to align the finger vertically, pass the same
    rotation_matrix so the skeleton lands on the rotated image.
    """
    if landmarks is None or len(landmarks) < 21:
        return image
    pts = np.asarray(landmarks, dtype=np.float64)
    if rotation_matrix is not None:
        from src.geometry import transform_points_rotation
        pts = transform_points_rotation(pts, rotation_matrix)
    return draw_hand_skeleton(image, pts)


def _overlay_sam_masks(
    image: np.ndarray,
    hand_mask: Optional[np.ndarray] = None,
    card_mask: Optional[np.ndarray] = None,
    rotation_matrix: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Tint the SAM hand and card masks onto a debug image.

    Both the hand and the card are rendered in Color.CONTOUR (the shared
    default object-outline color, distinct from the per-finger band colors)
    as semi-transparent fills plus a solid contour so the pixel-accurate SAM
    silhouettes remain visible underneath downstream finger/edge overlays.

    If ``rotation_matrix`` is supplied (because the caller applied a precise
    finger-alignment rotation to the canonical image before this call), the
    masks are rotated to match so they stay aligned with the image.
    """
    if hand_mask is None and card_mask is None:
        return image

    h, w = image.shape[:2]
    out = image.copy()

    def _prepare(mask: np.ndarray) -> Optional[np.ndarray]:
        if mask is None:
            return None
        if mask.dtype != np.uint8:
            m = (mask > 0).astype(np.uint8) * 255
        else:
            m = mask.copy()
        if m.shape[:2] != (h, w):
            m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
        if rotation_matrix is not None:
            m = cv2.warpAffine(
                m, rotation_matrix, (w, h),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )
        return m

    hand_u8 = _prepare(hand_mask)
    card_u8 = _prepare(card_mask)

    # Solid contours only — no tinted fill, so the underlying photo stays
    # at full brightness inside the SAM silhouettes. Drawn at thickness 4
    # so the silhouette reads as the primary outline; the internal hand
    # skeleton uses a thinner stroke so it stays a supporting reference.
    if hand_u8 is not None:
        contours, _ = cv2.findContours(hand_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, contours, -1, Color.CONTOUR, 4, cv2.LINE_AA)
    if card_u8 is not None:
        contours, _ = cv2.findContours(card_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, contours, -1, Color.CONTOUR, 4, cv2.LINE_AA)

    return out


def _overlay_card_seeds(
    image: np.ndarray,
    seed_debug: Optional[Dict[str, Any]],
    rotation_matrix: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Draw SAM card-detection prompt points on a debug image.

    Positive seeds in green, palm-center negative in red, middle-PIP anchor
    as a cyan cross. All points are assumed to be in the canonical (pre-
    precise-rotation) frame; pass ``rotation_matrix`` to align with an image
    that had the finger rotation applied.
    """

    # temprary bypass by Feng
    return image

    if not seed_debug:
        return image
    from src.geometry import transform_points_rotation

    def _xform(points: List[Tuple[int, int]]) -> np.ndarray:
        arr = np.asarray(points, dtype=np.float32)
        if rotation_matrix is not None and len(arr) > 0:
            arr = transform_points_rotation(arr, rotation_matrix)
        return arr

    out = image
    h, w = out.shape[:2]
    # Thin, map-style reference crosses: small, single-pixel-wide, softened.
    marker_size = max(14, int(round(0.012 * max(h, w))))
    thickness = 2

    # Pastel variants so the markers read as reference lines rather than
    # high-contrast callouts.
    DROP_COLOR = (120, 220, 220)   # soft yellow
    KEEP_COLOR = (120, 220, 120)   # soft green
    NEG_COLOR = (120, 120, 220)    # soft red
    ANCHOR_COLOR = (220, 220, 120)  # soft cyan

    def _plus(pt, color):
        cv2.drawMarker(
            out, (int(pt[0]), int(pt[1])), color,
            markerType=cv2.MARKER_CROSS,
            markerSize=marker_size,
            thickness=thickness,
            line_type=cv2.LINE_AA,
        )

    # Seeds dropped by the hand-mask filter. Drawn first so any coincident
    # kept seed paints on top.
    dropped = seed_debug.get("dropped") or []
    if dropped:
        for pt in _xform(dropped).astype(int):
            _plus(pt, DROP_COLOR)

    seeds = seed_debug.get("seeds") or []
    if seeds:
        for pt in _xform(seeds).astype(int):
            _plus(pt, KEEP_COLOR)

    #negatives = seed_debug.get("negatives") or []
    #if negatives:
    #    for pt in _xform(negatives).astype(int):
    #        _plus(pt, NEG_COLOR)

    #anchor = seed_debug.get("anchor")
    #if anchor is not None:
    #    ax, ay = _xform([anchor])[0].astype(int)
    #    # Tilted cross (X) to distinguish the anchor from the plus-shaped seeds.
    #    cv2.drawMarker(
    #        out, (int(ax), int(ay)), ANCHOR_COLOR,
    #        markerType=cv2.MARKER_TILTED_CROSS,
    #        markerSize=marker_size,
    #        thickness=thickness,
    #        line_type=cv2.LINE_AA,
    #    )
    return out


def _save_debug_visualization(path: str, image: np.ndarray) -> None:
    """Downscale + fast-encode a debug overlay image.

    The web demo and validation scripts all consume this just for display,
    so we trade 12 MP PNG encoding (~1–2s) for a ~1600 px JPEG (~50ms)
    without changing the output file path.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    h, w = image.shape[:2]
    long_side = max(h, w)
    if long_side > _DEBUG_VIS_MAX_LONG_SIDE:
        scale = _DEBUG_VIS_MAX_LONG_SIDE / long_side
        new_size = (int(round(w * scale)), int(round(h * scale)))
        image = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)
    # JPEG is ~20× faster than PNG to encode at this size and visually
    # indistinguishable for debug overlays.
    ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        cv2.imwrite(path, image)  # fallback to whatever imwrite picks from ext
        return
    with open(path, "wb") as f:
        f.write(buf.tobytes())


def _write_card_failure_viz(
    result_png_path: Optional[str],
    image_canonical: np.ndarray,
    hand_data: Dict[str, Any],
    card_result: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a diagnostic overlay for card-phase failures.

    Shows the hand mask + skeleton on the canonical image, plus either the
    detected card corner quadrilateral (when the card was found but rejected,
    e.g. card_not_parallel) or the card-prompt seed points (when detection
    itself failed). Uses the same corner-quad rendering as the success path
    (draw_card_overlay) rather than the raw SAM card mask, which can have
    stray blobs outside the true card boundary.
    """
    if result_png_path is None:
        return
    vis = image_canonical.copy()
    vis = _overlay_sam_masks(vis, hand_mask=hand_data.get("mask"))
    vis = _overlay_hand_skeleton(vis, landmarks=hand_data.get("landmarks"))
    if card_result is not None:
        vis = draw_card_overlay(vis, card_result)
    else:
        vis = _overlay_card_seeds(vis, hand_data.get("_sam_card_seed_debug"))
    _save_debug_visualization(result_png_path, vis)
    logger.info("card-failure viz saved: %s", result_png_path)


def _sam_card_detect(
    image_canonical: np.ndarray,
    hand_data: Dict[str, Any],
    save_debug: bool,
    result_png_path: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Run prompt-based SAM card detection.

    No AMG fallback: empirically, if the 5x5 prompt grid doesn't find the
    card, AMG won't either, and the ~20s AMG retry is pure cost. Returns
    the card dict or None on failure.
    """
    debug_root = (
        Path(result_png_path).parent if (save_debug and result_png_path is not None) else None
    )
    hand_mask = hand_data.get("mask")
    landmarks = hand_data.get("landmarks")

    if hand_mask is None or landmarks is None or len(landmarks) <= 9:
        return None

    middle_mcp = landmarks[9, :2]
    y_limit = int(round(middle_mcp[1]))

    seed_info = suggest_card_seeds(hand_mask, image_canonical.shape[:2], y_limit)
    seeds = seed_info["kept"]
    dropped_seeds = seed_info["dropped"]
    if not seeds:
        return None

    palm_idx = [0, 5, 9, 13, 17]
    palm_c = np.mean(landmarks[palm_idx, :2], axis=0)
    negatives: List[Tuple[int, int]] = [
        (int(round(palm_c[0])), int(round(palm_c[1])))
    ]

    prompt_debug = str(debug_root / "sam_card_prompt_debug") if debug_root else None
    card_result = detect_credit_card_sam_prompt(
        image_canonical,
        seed_points=seeds,
        negative_points=negatives,
        debug_dir=prompt_debug,
        hand_mask=hand_mask,
    )
    # Stash seed geometry so the final result PNG can visualize what was
    # prompted into SAM, even when card detection fails.
    seed_debug = {
        "seeds": list(seeds),
        "dropped": list(dropped_seeds),
        "negatives": list(negatives),
    }
    if card_result is not None:
        card_result["seed_debug"] = seed_debug
    else:
        # Return a sentinel-less None as before, but tuck seeds where the
        # caller can still find them via hand_data for the failure overlay.
        hand_data["_sam_card_seed_debug"] = seed_debug
    return card_result


def measure_finger(
    image: np.ndarray,
    finger_index: FingerIndex = "index",
    confidence_threshold: float = 0.7,
    save_intermediate: bool = False,
    result_png_path: Optional[str] = None,
    save_debug: bool = False,
    edge_method: str = "mask",
    sobel_threshold: float = 15.0,
    sobel_kernel_size: int = 3,
    use_subpixel: bool = True,
    skip_card_detection: bool = False,
    card_method: str = "classic",
    ring_model: str = DEFAULT_RING_MODEL,
) -> Dict[str, Any]:
    """Main measurement pipeline.

    edge_method is 'mask' (default, SAM boundary direct) or 'sobel'
    (subpixel gradient refinement anchored on the SAM boundary).
    """
    timings: Dict[str, float] = {}

    # Phase 2: Image quality metrics (informational only — no hard fail)
    with log_phase("image_quality", timings):
        quality = assess_image_quality(image)
    logger.info(
        "image quality: blur=%.1f brightness=%.1f contrast=%.1f",
        quality["blur_score"], quality["brightness"], quality["contrast"],
    )
    if not quality["passed"]:
        for issue in quality["issues"]:
            logger.info("  quality note: %s", issue)

    # Phase 3: Hand & finger segmentation runs before card detection so we
    # can rotate the image to canonical orientation first.
    finger_debug_dir = None
    if save_debug and result_png_path is not None:
        finger_debug_dir = str(Path(result_png_path).parent / "finger_segmentation_debug")

    with log_phase("hand_segment", timings):
        hand_data = segment_hand(
            image,
            finger=finger_index,
            debug_dir=finger_debug_dir,
        )

    if hand_data is None:
        logger.warning("no hand detected in image")
        return create_output(
            card_detected=False,
            finger_detected=False,
            fail_reason="hand_not_detected",
        )

    logger.info(
        "hand detected: %s, confidence=%.2f",
        hand_data["handedness"], hand_data["confidence"],
    )
    if "orientation_rotation" in hand_data:
        logger.info("hand orientation normalized: %s° rotation applied",
                    hand_data["orientation_rotation"])

    # Use canonical image for all downstream processing so finger edges are vertical.
    if "canonical_image" in hand_data:
        image_canonical = hand_data["canonical_image"]
        logger.info("canonical image: %dx%d",
                    image_canonical.shape[1], image_canonical.shape[0])
    else:
        image_canonical = image
        logger.warning("canonical image not available, using original")

    # Phase 4: Credit card detection & scale calibration.
    card_debug_dir = None
    if save_debug and result_png_path is not None:
        card_debug_dir = str(Path(result_png_path).parent / "card_detection_debug")

    card_metrics: Optional[Dict[str, float]] = None

    if skip_card_detection:
        cli_display.print_skip_card_warning()
        card_result = None
        px_per_cm = 100.0  # dummy scale — measurements will be inaccurate
        scale_confidence = 0.5
        view_angle_ok = True
        card_detected = False
    else:
        with log_phase(f"card_detect[{card_method}]", timings):
            if card_method == "sam":
                card_result = _sam_card_detect(
                    image_canonical, hand_data, save_debug, result_png_path
                )
            else:
                card_result = detect_credit_card(image_canonical, debug_dir=card_debug_dir)

        if card_result is None:
            logger.warning("card not detected in image")
            _write_card_failure_viz(result_png_path, image_canonical, hand_data)
            return create_output(
                card_detected=False,
                fail_reason="card_not_detected",
            )

        px_per_cm, scale_confidence = compute_scale_factor(card_result["corners"])
        card_metrics = _build_card_metrics(card_result, scale_confidence, image_canonical.shape[:2])
        logger.info(
            "card detected: %.0fx%.0fpx, aspect=%.3f, confidence=%.2f",
            card_result["width_px"], card_result["height_px"],
            card_result["aspect_ratio"], card_result["confidence"],
        )
        logger.info("scale: %.2f px/cm (confidence=%.2f)", px_per_cm, scale_confidence)

        view_angle_ok = scale_confidence > 0.95
        card_detected = True

        if not view_angle_ok:
            logger.warning("card not parallel to camera (scale_confidence=%.2f, required>0.95)",
                           scale_confidence)
            _write_card_failure_viz(
                result_png_path, image_canonical, hand_data, card_result=card_result
            )
            return create_output(
                card_detected=True,
                finger_detected=False,
                scale_px_per_cm=px_per_cm,
                view_angle_ok=False,
                fail_reason="card_not_parallel",
                card_metrics=card_metrics,
            )

        logger.info("card framing: long_side/short_image=%.3f", card_metrics["framing_ratio"])
        if card_metrics["framing_ratio"] < MIN_CARD_LONG_SIDE_RATIO:
            logger.warning(
                "card too small in frame (ratio=%.3f, required>=%.2f)",
                card_metrics["framing_ratio"], MIN_CARD_LONG_SIDE_RATIO,
            )
            _write_card_failure_viz(
                result_png_path, image_canonical, hand_data, card_result=card_result
            )
            return create_output(
                card_detected=True,
                finger_detected=False,
                scale_px_per_cm=px_per_cm,
                view_angle_ok=view_angle_ok,
                fail_reason="card_too_small",
                card_metrics=card_metrics,
            )

    # Phase 5: Finger isolation (hand already segmented in Phase 3).
    h_can, w_can = image_canonical.shape[:2]
    # Keep a reference to the raw SAM hand mask (pre-isolation polygon clip).
    # mask_only edge detection needs the untrimmed silhouette — the isolation
    # polygon in _create_finger_roi_mask is only ~1.08x the landmark segment
    # length and can cut into a wider-than-average finger, which would make
    # the mask boundary narrower than the true SAM boundary.
    raw_hand_mask = hand_data.get("mask")
    with log_phase("finger_isolate", timings):
        finger_data = isolate_finger(hand_data, finger=finger_index, image_shape=(h_can, w_can))

    if finger_data is None:
        logger.warning("could not isolate finger: %s", finger_index)
        return create_output(
            card_detected=card_detected,
            finger_detected=False,
            scale_px_per_cm=px_per_cm,
            view_angle_ok=view_angle_ok,
            fail_reason="finger_isolation_failed",
            card_metrics=card_metrics,
        )

    logger.info("finger isolated: %s", finger_data["finger_name"])

    # Clean the finger mask
    cleaned_mask = clean_mask(finger_data["mask"])

    if cleaned_mask is None:
        logger.warning("finger mask too small or invalid")
        return create_output(
            card_detected=card_detected,
            finger_detected=False,
            scale_px_per_cm=px_per_cm,
            view_angle_ok=view_angle_ok,
            fail_reason="finger_mask_too_small",
            card_metrics=card_metrics,
        )

    contour = get_finger_contour(cleaned_mask)

    if contour is None:
        logger.warning("could not extract finger contour")
        return create_output(
            card_detected=card_detected,
            finger_detected=False,
            scale_px_per_cm=px_per_cm,
            view_angle_ok=view_angle_ok,
            fail_reason="contour_extraction_failed",
            card_metrics=card_metrics,
        )

    logger.info("finger contour extracted: %d points", len(contour))

    # Phase 5: Estimate finger axis from MediaPipe landmarks.
    try:
        axis_data = estimate_finger_axis(finger_data.get("landmarks"))
        logger.info(
            "finger axis: length=%.1fpx, center=(%.0f, %.0f)",
            axis_data["length"], axis_data["center"][0], axis_data["center"][1],
        )
    except Exception as e:
        logger.error("failed to estimate finger axis: %s", e)
        return create_output(
            card_detected=card_detected,
            finger_detected=True,
            scale_px_per_cm=px_per_cm,
            view_angle_ok=view_angle_ok,
            fail_reason="axis_estimation_failed",
            card_metrics=card_metrics,
        )

    # Phase 5b: Precise finger alignment rotation
    # Rotate image to make finger axis perfectly vertical for accurate width measurement
    from src.geometry import (
        calculate_angle_from_vertical,
        rotate_image_precise,
        rotate_axis_data,
        rotate_contour,
        transform_points_rotation
    )

    angle_from_vertical = calculate_angle_from_vertical(axis_data["direction"])
    #rotation_threshold = 2.0  # Only rotate if > 2° off vertical
    rotation_threshold = 0.0  # always rorate to upright

    rotation_matrix = None  # Track rotation for card corner transform in debug

    if abs(angle_from_vertical) >= rotation_threshold:
        logger.info("finger axis %.1f° from vertical, applying precise rotation",
                    angle_from_vertical)

        # Rotate image
        h_can, w_can = image_canonical.shape[:2]
        rotation_center = (w_can / 2.0, h_can / 2.0)
        image_canonical, rotation_matrix = rotate_image_precise(
            image_canonical, angle_from_vertical, rotation_center
        )

        # Update axis data
        axis_data = rotate_axis_data(axis_data, rotation_matrix)

        # Update contour
        contour = rotate_contour(contour, rotation_matrix)

        # Update landmarks if available
        if finger_data.get("landmarks") is not None:
            landmarks_rotated = transform_points_rotation(
                finger_data["landmarks"], rotation_matrix
            )
            finger_data["landmarks"] = landmarks_rotated

        # Update cleaned mask
        cleaned_mask = cv2.warpAffine(
            cleaned_mask, rotation_matrix, (w_can, h_can),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0
        )

        # Also warp the raw SAM hand mask so mask_only mode can read the
        # untrimmed silhouette in the same rotated frame as the image.
        if raw_hand_mask is not None:
            raw_hand_mask = cv2.warpAffine(
                raw_hand_mask, rotation_matrix, (w_can, h_can),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )

        logger.info("rotation applied: %.1f° CW, finger now vertical", angle_from_vertical)
    else:
        logger.info("finger axis %.1f° from vertical (within %.1f° threshold, no rotation)",
                    angle_from_vertical, rotation_threshold)

    # Phase 6: Localize ring-wearing zone
    try:
        landmarks = finger_data.get("landmarks")
        if landmarks is not None and len(landmarks) == 4:
            zone_data = localize_ring_zone_from_landmarks(
                landmarks=landmarks,
                axis_data=axis_data,
                zone_type="anatomical",
            )
            zone_length_cm = zone_data["length"] / px_per_cm
            logger.info(
                "ring zone (anatomical): length=%.1fpx (%.2fcm)",
                zone_data["length"], zone_length_cm,
            )
        else:
            zone_data = localize_ring_zone(axis_data)
            zone_length_cm = zone_data["length"] / px_per_cm
            logger.info(
                "ring zone (percentage %.0f%%-%.0f%%): length=%.1fpx (%.2fcm)",
                zone_data["start_pct"] * 100, zone_data["end_pct"] * 100,
                zone_data["length"], zone_length_cm,
            )
    except Exception as e:
        logger.error("failed to localize ring zone: %s", e)
        return create_output(
            card_detected=card_detected,
            finger_detected=True,
            scale_px_per_cm=px_per_cm,
            view_angle_ok=view_angle_ok,
            fail_reason="zone_localization_failed",
            card_metrics=card_metrics,
        )

    # Phase 7: Measure finger width at ring zone.
    # mask mode reads the SAM mask boundary directly; sobel mode runs
    # subpixel gradient refinement anchored on the SAM boundary.
    mask_mode = "mask_only" if edge_method == "mask" else "sobel_only"
    logger.info(
        "edge refinement mode=%s threshold=%.1f kernel=%d",
        mask_mode, sobel_threshold, sobel_kernel_size,
    )

    edge_debug_dir = None
    if save_debug and result_png_path is not None:
        edge_debug_dir = str(Path(result_png_path).parent / "edge_refinement_debug")

    # mask_only reads boundaries directly from the mask, so it needs the
    # *raw* SAM silhouette. sobel_only uses the isolation-trimmed mask it
    # was validated against.
    if mask_mode == "mask_only" and raw_hand_mask is not None:
        edge_mask_input = raw_hand_mask
    else:
        edge_mask_input = cleaned_mask

    try:
        with log_phase(f"edge_refine[{mask_mode}]", timings):
            sobel_measurement = refine_edges_sobel(
                image=image_canonical,
                axis_data=axis_data,
                zone_data=zone_data,
                scale_px_per_cm=px_per_cm,
                finger_landmarks=finger_data.get("landmarks"),
                sobel_threshold=sobel_threshold,
                kernel_size=sobel_kernel_size,
                use_subpixel=use_subpixel,
                finger_mask=edge_mask_input,
                debug_dir=edge_debug_dir,
                mask_mode=mask_mode,
                finger_name=finger_data.get("finger_name"),
            )
    except Exception as e:
        logger.error("edge refinement failed: %s", e)
        return create_output(
            card_detected=card_detected,
            finger_detected=True,
            scale_px_per_cm=px_per_cm,
            view_angle_ok=view_angle_ok,
            fail_reason="sobel_edge_refinement_failed",
            edge_method_used=edge_method,
            card_metrics=card_metrics,
        )

    logger.info(
        "edge width: %.4fcm (%d samples, std=%.2fpx, quality=%.3f)",
        sobel_measurement["median_width_cm"],
        sobel_measurement["num_samples"],
        sobel_measurement["std_width_px"],
        sobel_measurement["edge_quality"]["overall_score"],
    )

    # Hard-fail mask mode when there aren't enough valid rows to trust the
    # median. Without this gate a single surviving row still produces a
    # "valid" measurement.
    if edge_method == "mask":
        num_samples = int(sobel_measurement.get("num_samples", 0))
        if num_samples < MIN_MASK_SAMPLES:
            logger.warning("insufficient valid edge samples: %d < %d",
                           num_samples, MIN_MASK_SAMPLES)
            return create_output(
                card_detected=card_detected,
                finger_detected=True,
                scale_px_per_cm=px_per_cm,
                view_angle_ok=view_angle_ok,
                fail_reason=f"insufficient_edge_samples_{num_samples}",
                edge_method_used="mask",
                card_metrics=card_metrics,
            )

    final_measurement = sobel_measurement
    median_width_cm = sobel_measurement["median_width_cm"]
    edge_method_used = edge_method

    if median_width_cm < 1.0 or median_width_cm > 3.0:
        logger.warning("measured width %.2fcm is outside realistic range", median_width_cm)

    # Phase 8: Comprehensive confidence scoring
    # Calculate component confidences
    if card_result is not None:
        card_conf = compute_card_confidence(card_result, scale_confidence)
    else:
        # Dummy card confidence when card detection skipped (testing mode)
        card_conf = scale_confidence  # Use dummy scale confidence (0.5)

    # Calculate mask area for finger confidence
    mask_area = np.sum(cleaned_mask > 0)
    image_area = image.shape[0] * image.shape[1]
    finger_conf = compute_finger_confidence(hand_data, finger_data, mask_area, image_area)

    # Calculate measurement confidence
    measurement_conf = compute_measurement_confidence(final_measurement, median_width_cm)

    edge_quality_conf = compute_edge_quality_confidence(
        final_measurement.get("edge_quality")
    )

    confidence_breakdown = compute_overall_confidence(
        card_conf,
        finger_conf,
        measurement_conf,
        edge_quality_conf,
    )

    conf_parts = [
        f"card={confidence_breakdown['card']:.2f}",
        f"finger={confidence_breakdown['finger']:.2f}",
        f"measurement={confidence_breakdown['measurement']:.2f}",
        f"edge={confidence_breakdown['edge_quality']:.2f}",
    ]
    logger.info(
        "confidence: %.3f (%s) [%s]",
        confidence_breakdown["overall"], confidence_breakdown["level"],
        ", ".join(conf_parts),
    )
    if confidence_breakdown["overall"] < confidence_threshold:
        logger.warning(
            "confidence %.3f below threshold %.3f",
            confidence_breakdown["overall"], confidence_threshold,
        )

    # Phase 9: Result visualization (always generated)
    if result_png_path is not None:
        with log_phase("visualization", timings):
            logger.info("generating result visualization")

            edge_data = sobel_measurement["edge_data"]
            roi_bounds = sobel_measurement["roi_data"]["roi_bounds"]
            width_data = sobel_measurement["width_data"]
            width_data["median_width_cm"] = sobel_measurement["median_width_cm"]

            raw_cm = width_data["median_width_cm"]
            cal_cm = apply_calibration(raw_cm)
            width_data["median_width_cm"] = cal_cm
            width_data["raw_width_cm"] = raw_cm

            rec = recommend_ring_size(cal_cm, ring_model=ring_model)
            if rec:
                width_data["ring_size_rec"] = rec

            debug_image = draw_comprehensive_edge_overlay(
                full_image=image_canonical,
                edge_data=edge_data,
                roi_bounds=roi_bounds,
                axis_data=axis_data,
                zone_data=zone_data,
                width_data=width_data,
                scale_px_per_cm=px_per_cm,
            )

            # Only the hand SAM mask gets tinted as an underlay. The card SAM
            # mask often has stray blobs outside the actual card rectangle;
            # the detected corners already give us a clean quadrilateral, so
            # draw_card_overlay below shades that instead.
            debug_image = _overlay_sam_masks(
                debug_image,
                hand_mask=hand_data.get("mask") if hand_data else None,
                card_mask=None,
                rotation_matrix=rotation_matrix,
            )

            debug_image = _overlay_hand_skeleton(
                debug_image,
                landmarks=hand_data.get("landmarks") if hand_data else None,
                rotation_matrix=rotation_matrix,
            )

            if card_result is not None and card_result.get("corners") is not None:
                pts = np.asarray(card_result["corners"], dtype=np.float32)
                if rotation_matrix is not None:
                    pts = transform_points_rotation(pts, rotation_matrix)
                draw_card_overlay(
                    debug_image,
                    {"corners": pts},
                    scale_px_per_cm=px_per_cm,
                )

            # SAM card-detection seed points. Falls back to the hand_data slot
            # when card detection returned None so we can still see what was
            # prompted into SAM.
            seed_debug = None
            if card_result is not None:
                seed_debug = card_result.get("seed_debug")
            if seed_debug is None and hand_data is not None:
                seed_debug = hand_data.get("_sam_card_seed_debug")
            debug_image = _overlay_card_seeds(
                debug_image, seed_debug, rotation_matrix=rotation_matrix
            )

            _save_debug_visualization(result_png_path, debug_image)
            logger.info("result visualization saved: %s", result_png_path)

    log_phase_summary(timings)

    output = create_output(
        finger_diameter_cm=median_width_cm,
        confidence=confidence_breakdown['overall'],
        card_detected=card_detected,
        finger_detected=True,
        scale_px_per_cm=px_per_cm,
        view_angle_ok=view_angle_ok,
        fail_reason=None,
        edge_method_used=edge_method_used,
        card_metrics=card_metrics,
    )
    # Additive metadata used by the web session aggregator. Keeping it in the
    # core result also makes CLI/debug JSON explicit about which physical hand
    # was measured.
    output["handedness"] = hand_data.get("handedness", "Unknown")
    return output


MULTI_FINGERS = ["index", "middle", "ring"]


def _measure_single_finger_from_shared(
    image_canonical: np.ndarray,
    hand_data: Dict[str, Any],
    finger_name: str,
    px_per_cm: float,
    card_detected: bool,
    view_angle_ok: bool,
    card_result: Optional[Dict[str, Any]],
    scale_confidence: float,
    edge_method: str = "mask",
    sobel_threshold: float = 15.0,
    sobel_kernel_size: int = 3,
    use_subpixel: bool = True,
) -> Dict[str, Any]:
    """Measure a single finger using pre-computed hand/card data.

    Internal helper for measure_multi_finger(). Runs phases 4-8 only.
    """
    from src.geometry import (
        calculate_angle_from_vertical,
        rotate_image_precise,
        rotate_axis_data,
        rotate_contour,
        transform_points_rotation,
    )

    h_can, w_can = image_canonical.shape[:2]
    raw_hand_mask = hand_data.get("mask")
    finger_data = isolate_finger(hand_data, finger=finger_name, image_shape=(h_can, w_can))

    if finger_data is None:
        return create_output(
            card_detected=card_detected, finger_detected=False,
            scale_px_per_cm=px_per_cm, view_angle_ok=view_angle_ok,
            fail_reason="finger_isolation_failed",
        )

    cleaned_mask = clean_mask(finger_data["mask"])
    if cleaned_mask is None:
        return create_output(
            card_detected=card_detected, finger_detected=False,
            scale_px_per_cm=px_per_cm, view_angle_ok=view_angle_ok,
            fail_reason="finger_mask_too_small",
        )

    contour = get_finger_contour(cleaned_mask)
    if contour is None:
        return create_output(
            card_detected=card_detected, finger_detected=False,
            scale_px_per_cm=px_per_cm, view_angle_ok=view_angle_ok,
            fail_reason="contour_extraction_failed",
        )

    # Axis estimation
    try:
        axis_data = estimate_finger_axis(finger_data.get("landmarks"))
    except Exception:
        return create_output(
            card_detected=card_detected, finger_detected=True,
            scale_px_per_cm=px_per_cm, view_angle_ok=view_angle_ok,
            fail_reason="axis_estimation_failed",
        )

    # Precise rotation to vertical
    img_work = image_canonical.copy()
    angle_from_vertical = calculate_angle_from_vertical(axis_data["direction"])
    if abs(angle_from_vertical) >= 0.0:
        rot_center = (w_can / 2.0, h_can / 2.0)
        img_work, rotation_matrix = rotate_image_precise(img_work, angle_from_vertical, rot_center)
        axis_data = rotate_axis_data(axis_data, rotation_matrix)
        contour = rotate_contour(contour, rotation_matrix)
        if finger_data.get("landmarks") is not None:
            finger_data["landmarks"] = transform_points_rotation(finger_data["landmarks"], rotation_matrix)
        cleaned_mask = cv2.warpAffine(
            cleaned_mask, rotation_matrix, (w_can, h_can),
            flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
        )
        if raw_hand_mask is not None:
            raw_hand_mask = cv2.warpAffine(
                raw_hand_mask, rotation_matrix, (w_can, h_can),
                flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
            )

    # Ring zone
    try:
        landmarks = finger_data.get("landmarks")
        if landmarks is not None and len(landmarks) == 4:
            zone_data = localize_ring_zone_from_landmarks(
                landmarks=landmarks, axis_data=axis_data, zone_type="anatomical",
            )
        else:
            zone_data = localize_ring_zone(axis_data)
    except Exception:
        return create_output(
            card_detected=card_detected, finger_detected=True,
            scale_px_per_cm=px_per_cm, view_angle_ok=view_angle_ok,
            fail_reason="zone_localization_failed",
        )

    mask_mode = "mask_only" if edge_method == "mask" else "sobel_only"
    edge_mask_input = raw_hand_mask if (mask_mode == "mask_only" and raw_hand_mask is not None) else cleaned_mask
    try:
        sobel_measurement = refine_edges_sobel(
            image=img_work, axis_data=axis_data, zone_data=zone_data,
            scale_px_per_cm=px_per_cm, finger_landmarks=finger_data.get("landmarks"),
            sobel_threshold=sobel_threshold, kernel_size=sobel_kernel_size,
            use_subpixel=use_subpixel,
            finger_mask=edge_mask_input,
            mask_mode=mask_mode,
            finger_name=finger_name,
        )
    except Exception:
        return create_output(
            card_detected=card_detected, finger_detected=True,
            scale_px_per_cm=px_per_cm, view_angle_ok=view_angle_ok,
            fail_reason="sobel_edge_refinement_failed", edge_method_used=edge_method,
        )

    if edge_method == "mask":
        num_samples = int(sobel_measurement.get("num_samples", 0))
        if num_samples < MIN_MASK_SAMPLES:
            return create_output(
                card_detected=card_detected, finger_detected=True,
                scale_px_per_cm=px_per_cm, view_angle_ok=view_angle_ok,
                fail_reason=f"insufficient_edge_samples_{num_samples}",
                edge_method_used="mask",
            )

    final_measurement = sobel_measurement
    median_width_cm = sobel_measurement["median_width_cm"]
    edge_method_used = edge_method

    # Confidence
    if card_result is not None:
        card_conf = compute_card_confidence(card_result, scale_confidence)
    else:
        card_conf = scale_confidence
    mask_area = int(np.sum(cleaned_mask > 0))
    image_area = image_canonical.shape[0] * image_canonical.shape[1]
    finger_conf = compute_finger_confidence(hand_data, finger_data, mask_area, image_area)
    measurement_conf = compute_measurement_confidence(final_measurement, median_width_cm)
    edge_quality_conf = compute_edge_quality_confidence(final_measurement.get("edge_quality"))
    confidence_breakdown = compute_overall_confidence(
        card_conf, finger_conf, measurement_conf, edge_quality_conf,
    )

    result = create_output(
        finger_diameter_cm=median_width_cm,
        confidence=confidence_breakdown["overall"],
        card_detected=card_detected, finger_detected=True,
        scale_px_per_cm=px_per_cm, view_angle_ok=view_angle_ok,
        edge_method_used=edge_method_used,
    )
    # Attach intermediate data for debug viz
    result["_internal"] = {
        "contour": contour, "axis_data": axis_data, "zone_data": zone_data,
        "finger_data": finger_data, "cleaned_mask": cleaned_mask,
        "sobel_measurement": sobel_measurement,
        "final_measurement": final_measurement, "image_work": img_work,
        "rotation_matrix": rotation_matrix,
    }
    return result


def measure_multi_finger(
    image: np.ndarray,
    confidence_threshold: float = 0.7,
    result_png_path: Optional[str] = None,
    save_debug: bool = False,
    edge_method: str = "mask",
    sobel_threshold: float = 15.0,
    sobel_kernel_size: int = 3,
    use_subpixel: bool = True,
    skip_card_detection: bool = False,
    no_calibration: bool = False,
    card_method: str = "classic",
    ring_model: str = DEFAULT_RING_MODEL,
) -> Dict[str, Any]:
    """Measure index, middle, and ring fingers from a single image.

    Runs shared setup (image quality, hand detection, card detection) once,
    then measures each finger independently.

    Returns:
        Dict with aggregated ring size recommendation + per-finger breakdown.
    """
    from src.finger_segmentation import FINGER_LANDMARKS

    timings: Dict[str, float] = {}

    # Phase 1: Image quality metrics (informational only — no hard fail)
    with log_phase("image_quality", timings):
        quality = assess_image_quality(image)
    logger.info(
        "[multi] image quality: blur=%.1f brightness=%.1f contrast=%.1f",
        quality["blur_score"], quality["brightness"], quality["contrast"],
    )
    if not quality["passed"]:
        for issue in quality["issues"]:
            logger.info("  quality note: %s", issue)

    lighting = check_lighting_uniformity(image)
    if not lighting["uniform"]:
        logger.warning("[multi] uneven lighting (range=%.1f)", lighting["brightness_range"])

    # Phase 2: Hand detection (use "index" for orientation — canonical for all)
    finger_debug_dir = None
    if save_debug and result_png_path is not None:
        finger_debug_dir = str(Path(result_png_path).parent / "finger_segmentation_debug")

    with log_phase("hand_segment", timings):
        hand_data = segment_hand(
            image,
            finger="index",
            debug_dir=finger_debug_dir,
        )
    if hand_data is None:
        logger.warning("[multi] no hand detected")
        return {"fail_reason": "hand_not_detected", "per_finger": {}, "fingers_measured": 0, "fingers_succeeded": 0}

    logger.info("[multi] hand detected: %s, confidence=%.2f",
                hand_data["handedness"], hand_data["confidence"])
    image_canonical = hand_data.get("canonical_image", image)

    # Phase 3: Card detection
    card_debug_dir = None
    if save_debug and result_png_path is not None:
        card_debug_dir = str(Path(result_png_path).parent / "card_detection_debug")

    card_metrics: Optional[Dict[str, float]] = None

    if skip_card_detection:
        card_result = None
        px_per_cm = 100.0
        scale_confidence = 0.5
        view_angle_ok = True
        card_detected = False
    else:
        with log_phase(f"card_detect[{card_method}]", timings):
            if card_method == "sam":
                card_result = _sam_card_detect(
                    image_canonical, hand_data, save_debug, result_png_path
                )
            else:
                card_result = detect_credit_card(image_canonical, debug_dir=card_debug_dir)
        if card_result is None:
            _write_card_failure_viz(result_png_path, image_canonical, hand_data)
            return {"fail_reason": "card_not_detected", "per_finger": {}, "fingers_measured": 0, "fingers_succeeded": 0}
        px_per_cm, scale_confidence = compute_scale_factor(card_result["corners"])
        card_metrics = _build_card_metrics(card_result, scale_confidence, image_canonical.shape[:2])
        view_angle_ok = scale_confidence > 0.95
        card_detected = True

        if not view_angle_ok:
            _write_card_failure_viz(
                result_png_path, image_canonical, hand_data, card_result=card_result
            )
            return {
                "fail_reason": "card_not_parallel",
                "per_finger": {},
                "fingers_measured": 0,
                "fingers_succeeded": 0,
                "card_metrics": card_metrics,
            }

        logger.info("[multi] card framing: long_side/short_image=%.3f", card_metrics["framing_ratio"])
        if card_metrics["framing_ratio"] < MIN_CARD_LONG_SIDE_RATIO:
            logger.warning(
                "[multi] card too small in frame (ratio=%.3f, required>=%.2f)",
                card_metrics["framing_ratio"], MIN_CARD_LONG_SIDE_RATIO,
            )
            _write_card_failure_viz(
                result_png_path, image_canonical, hand_data, card_result=card_result
            )
            return {
                "fail_reason": "card_too_small",
                "per_finger": {},
                "fingers_measured": 0,
                "fingers_succeeded": 0,
                "card_metrics": card_metrics,
            }

        card_frame = check_card_in_frame(card_result["corners"], image_canonical.shape)
        if not card_frame["in_frame"]:
            logger.warning("[multi] card near edge (min_margin=%.0fpx)",
                           card_frame["min_margin_px"])

    # Multi-finger quality: check spacing
    h_can, w_can = image_canonical.shape[:2]
    all_finger_landmarks = {}
    for fn in MULTI_FINGERS:
        indices = FINGER_LANDMARKS[fn]
        lm = hand_data["landmarks"][indices]
        all_finger_landmarks[fn] = lm

    spacing = check_finger_spacing(all_finger_landmarks, image_canonical.shape)
    if not spacing["well_spaced"]:
        pair = spacing.get("closest_pair", ("", ""))
        logger.warning(
            "[multi] fingers too close (%s, %s, %.0fpx)",
            pair[0], pair[1], spacing["min_spacing_px"],
        )

    # Measure each finger
    per_finger_raw: Dict[str, Dict] = {}
    for fn in MULTI_FINGERS:
        logger.info("[multi] measuring %s finger", fn)
        with log_phase(f"measure_finger[{fn}]", timings):
            result = _measure_single_finger_from_shared(
                image_canonical=image_canonical,
                hand_data=hand_data,
                finger_name=fn,
                px_per_cm=px_per_cm,
                card_detected=card_detected,
                view_angle_ok=view_angle_ok,
                card_result=card_result,
                scale_confidence=scale_confidence,
                edge_method=edge_method,
                sobel_threshold=sobel_threshold,
                sobel_kernel_size=sobel_kernel_size,
                use_subpixel=use_subpixel,
            )

        # Apply calibration
        raw_diam = result.get("finger_outer_diameter_cm")
        if raw_diam is not None and not no_calibration:
            calibrated = apply_calibration(raw_diam)
            result["finger_outer_diameter_cm"] = round(calibrated, 4)
            result["raw_diameter_cm"] = round(raw_diam, 4)
            result["calibration_applied"] = True
        else:
            result["calibration_applied"] = False

        # Ring size per finger
        diam = result.get("finger_outer_diameter_cm")
        if diam is not None:
            rec = recommend_ring_size(diam, ring_model=ring_model)
            if rec:
                result["ring_size"] = rec

        per_finger_raw[fn] = result

    # Aggregate
    aggregated = aggregate_ring_sizes(per_finger_raw)

    # Build debug visualization
    if result_png_path is not None:
        with log_phase("visualization", timings):
            _draw_multi_finger_debug(
                image_canonical=image_canonical,
                per_finger_raw=per_finger_raw,
                aggregated=aggregated,
                card_result=card_result,
                px_per_cm=px_per_cm,
                result_png_path=result_png_path,
                hand_mask=hand_data.get("mask") if hand_data else None,
                hand_landmarks=hand_data.get("landmarks") if hand_data else None,
            )

    # Clean internal data from output
    for fn, r in per_finger_raw.items():
        r.pop("_internal", None)

    aggregated["scale_px_per_cm"] = round(px_per_cm, 2)
    aggregated["handedness"] = hand_data.get("handedness", "Unknown")
    aggregated["quality_flags"] = {
        "card_detected": card_detected,
        "view_angle_ok": view_angle_ok,
        "lighting_uniform": lighting.get("uniform", True),
        "fingers_well_spaced": spacing.get("well_spaced", True),
    }
    if card_metrics is not None:
        aggregated["card_metrics"] = card_metrics

    log_phase_summary(timings)

    return aggregated


def _draw_multi_finger_debug(
    image_canonical: np.ndarray,
    per_finger_raw: Dict[str, Dict],
    aggregated: Dict[str, Any],
    card_result: Optional[Dict[str, Any]],
    px_per_cm: float,
    result_png_path: str,
    hand_mask: Optional[np.ndarray] = None,
    hand_landmarks: Optional[np.ndarray] = None,
) -> None:
    """Generate debug visualization for multi-finger measurement.

    Draws per-finger Sobel edge detection overlays (edge dots, width lines,
    ROI boxes) on the canonical image, matching single-finger viz quality.
    """
    from src.visualization import draw_card_overlay
    from src.viz_constants import Color

    # BGR values matched to the mobile result-card top-border colors in
    # web_demo/static/mobile/steps/result.js so each band on the overlay
    # visually links to its card: index #00dddd, middle #3b82f6, ring #dd44dd.
    FINGER_COLORS = {
        "index": (221, 221, 0),    # cyan
        "middle": (246, 130, 59),  # blue
        "ring": (221, 68, 221),    # magenta
    }

    vis = image_canonical.copy()
    h, w = vis.shape[:2]

    # Hand SAM silhouette as a tinted underlay. The card is shaded via its
    # clean corner rectangle in draw_card_overlay() below rather than the
    # raw SAM mask (which often has stray blobs outside the card boundary).
    vis = _overlay_sam_masks(
        vis,
        hand_mask=hand_mask,
        card_mask=None,
    )

    # MediaPipe hand skeleton (canonical frame — no rotation needed since the
    # multi-finger viz composes per-finger overlays via inverse rotation).
    vis = _overlay_hand_skeleton(vis, landmarks=hand_landmarks)

    # Draw card bounding box / dimensions on top of the tinted card mask
    if card_result is not None:
        vis = draw_card_overlay(vis, card_result, px_per_cm)

    # SAM card-detection seed points (prompt geometry). Multi-finger viz
    # runs in the canonical frame with no precise-rotation applied, so no
    # rotation matrix is needed here.
    seed_debug = None
    if card_result is not None:
        seed_debug = card_result.get("seed_debug")
    vis = _overlay_card_seeds(vis, seed_debug)

    # Draw per-finger Sobel edge overlays
    for fn, result in per_finger_raw.items():
        internal = result.get("_internal")
        if internal is None:
            continue
        color = FINGER_COLORS.get(fn, Color.FINGER)
        sobel = internal.get("sobel_measurement")
        rot_mat = internal.get("rotation_matrix")
        axis_data = internal["axis_data"]
        zone_data = internal["zone_data"]
        contour = internal["contour"]

        # Compute inverse rotation to map per-finger coords back to canonical
        inv_mat = None
        if rot_mat is not None:
            inv_mat = cv2.invertAffineTransform(rot_mat)

        def to_canonical(pt):
            """Transform a point from per-finger rotated coords to canonical."""
            if inv_mat is None:
                return pt
            p = np.array([pt[0], pt[1], 1.0], dtype=np.float64)
            return inv_mat @ p

        # Draw Sobel edge detection details if available
        if sobel is not None and "edge_data" in sobel and "roi_data" in sobel:
            edge_data = sobel["edge_data"]
            roi_bounds = sobel["roi_data"]["roi_bounds"]
            left_edges = edge_data["left_edges"]
            right_edges = edge_data["right_edges"]
            valid_rows = edge_data["valid_rows"]
            x_min, y_min, x_max, y_max = roi_bounds

            # Edge dots and width measurement lines
            valid_count = int(np.sum(valid_rows))
            line_spacing = max(1, valid_count // 20)
            count = 0
            for row_idx, valid in enumerate(valid_rows):
                if not valid:
                    continue
                gy = y_min + row_idx
                lx = x_min + int(left_edges[row_idx])
                rx = x_min + int(right_edges[row_idx])

                left_can = to_canonical(np.array([lx, gy])).astype(np.int32)
                right_can = to_canonical(np.array([rx, gy])).astype(np.int32)

                # Edge dots in the per-finger color so left/right boundaries
                # match the band lines and the result card.
                cv2.circle(vis, tuple(left_can), 2, color, -1)
                cv2.circle(vis, tuple(right_can), 2, color, -1)

                # Width measurement lines (every Nth row) in the per-finger
                # color so the band visually matches its result card. Drawn
                # at thickness 2 so they read as boldly as the dot-stacked
                # left/right boundary bars rather than fading into the skin.
                if count % line_spacing == 0:
                    cv2.line(vis, tuple(left_can), tuple(right_can),
                             color, 2, cv2.LINE_AA)
                count += 1

    _save_debug_visualization(result_png_path, vis)
    logger.info("[multi] debug visualization saved: %s", result_png_path)


def main() -> int:
    """Main entry point."""
    configure_logging()
    args = parse_args()

    error = validate_input(args.input)
    if error:
        cli_display.print_error(error)
        return 1

    image = load_image(args.input)
    if image is None:
        cli_display.print_error(f"Failed to load image: {args.input}")
        return 1

    cli_display.print_image_loaded(args.input, image.shape)

    result_png_path = str(Path(args.output).with_suffix(".png"))

    if args.mode == "multi":
        result = measure_multi_finger(
            image=image,
            confidence_threshold=args.confidence_threshold,
            result_png_path=result_png_path,
            save_debug=args.debug,
            edge_method=args.edge_method,
            sobel_threshold=args.sobel_threshold,
            sobel_kernel_size=args.sobel_kernel_size,
            use_subpixel=not args.no_subpixel,
            skip_card_detection=args.skip_card_detection,
            no_calibration=args.no_calibration,
            card_method=args.card_method,
            ring_model=args.ring_model,
        )

        save_output(result, args.output)
        cli_display.print_result_path(args.output)
        cli_display.print_multi_result(result)
        return 1 if result.get("fail_reason") else 0

    # Single-finger mode
    result = measure_finger(
        image=image,
        finger_index=args.finger_index,
        confidence_threshold=args.confidence_threshold,
        save_intermediate=args.save_intermediate,
        result_png_path=result_png_path,
        save_debug=args.debug,
        edge_method=args.edge_method,
        sobel_threshold=args.sobel_threshold,
        sobel_kernel_size=args.sobel_kernel_size,
        use_subpixel=not args.no_subpixel,
        skip_card_detection=args.skip_card_detection,
        card_method=args.card_method,
        ring_model=args.ring_model,
    )

    # Apply calibration (post-processing)
    raw_diameter = result.get("finger_outer_diameter_cm")
    if raw_diameter is not None and not args.no_calibration:
        calibrated = apply_calibration(raw_diameter)
        result["finger_outer_diameter_cm"] = round(calibrated, 4)
        result["raw_diameter_cm"] = round(raw_diameter, 4)
        result["calibration_applied"] = True
    else:
        result["calibration_applied"] = False

    diameter = result.get("finger_outer_diameter_cm")
    if diameter is not None:
        rec = recommend_ring_size(diameter, ring_model=args.ring_model)
        if rec:
            result["ring_size"] = rec

    save_output(result, args.output)
    cli_display.print_result_path(args.output)
    cli_display.print_single_result(result)
    return 1 if result["fail_reason"] else 0


if __name__ == "__main__":
    sys.exit(main())
