"""
Credit card detection and scale calibration utilities.

This module handles:
- Detecting credit card contour in an image
- Verifying aspect ratio matches standard credit card
- Perspective rectification
- Computing pixels-per-cm scale factor
"""

import logging

import cv2
import numpy as np
from typing import Optional, Tuple, Dict, Any, List
from pathlib import Path

# Import debug observer and drawing functions
from .debug_observer import DebugObserver, draw_contours_overlay, draw_candidates_with_scores

logger = logging.getLogger(__name__)

# Import shared visualization constants
from .viz_constants import (
    FONT_FACE,
    Color,
    StrategyColor,
    FontScale,
    FontThickness,
    Size,
    Layout,
)

# Standard credit card dimensions (ISO/IEC 7810 ID-1)
CARD_WIDTH_MM = 85.60
CARD_HEIGHT_MM = 53.98
CARD_WIDTH_CM = CARD_WIDTH_MM / 10
CARD_HEIGHT_CM = CARD_HEIGHT_MM / 10
CARD_ASPECT_RATIO = CARD_WIDTH_MM / CARD_HEIGHT_MM  # ~1.586

# Detection parameters
MIN_CARD_AREA_RATIO = 0.01  # Card must be at least 1% of image area
MAX_CARD_AREA_RATIO = 0.5   # Card must be at most 50% of image area


def order_corners(corners: np.ndarray) -> np.ndarray:
    """
    Order corners as: top-left, top-right, bottom-right, bottom-left.

    Args:
        corners: 4x2 array of corner points

    Returns:
        Ordered 4x2 array of corners
    """
    corners = corners.reshape(4, 2).astype(np.float32)

    # Sort by sum (x+y): smallest = top-left, largest = bottom-right
    s = corners.sum(axis=1)
    tl_idx = np.argmin(s)
    br_idx = np.argmax(s)

    # Sort by diff (y-x): smallest = top-right, largest = bottom-left
    d = np.diff(corners, axis=1).flatten()
    tr_idx = np.argmin(d)
    bl_idx = np.argmax(d)

    return np.array([
        corners[tl_idx],
        corners[tr_idx],
        corners[br_idx],
        corners[bl_idx],
    ], dtype=np.float32)


def get_quad_dimensions(corners: np.ndarray) -> Tuple[float, float]:
    """
    Get width and height of a quadrilateral from ordered corners.

    Args:
        corners: Ordered 4x2 array (TL, TR, BR, BL)

    Returns:
        Tuple of (width, height) in pixels
    """
    # Width: average of top and bottom edges
    top_width = np.linalg.norm(corners[1] - corners[0])
    bottom_width = np.linalg.norm(corners[2] - corners[3])
    width = (top_width + bottom_width) / 2

    # Height: average of left and right edges
    left_height = np.linalg.norm(corners[3] - corners[0])
    right_height = np.linalg.norm(corners[2] - corners[1])
    height = (left_height + right_height) / 2

    return width, height


def score_card_candidate(
    contour: np.ndarray,
    corners: np.ndarray,
    image_area: float,
    aspect_ratio_tolerance: float = 0.15,
) -> Tuple[float, Dict[str, Any]]:
    """
    Score a quadrilateral candidate for being a credit card.

    Since candidates come from minAreaRect, corners are always a perfect
    rectangle. Scoring focuses on aspect ratio match and area coverage.

    Args:
        contour: Original contour (minAreaRect box points)
        corners: 4 corner points
        image_area: Total image area for relative sizing
        aspect_ratio_tolerance: Allowed deviation from standard ratio

    Returns:
        Tuple of (score, details_dict)
    """
    ordered = order_corners(corners)
    width, height = get_quad_dimensions(ordered)
    area = cv2.contourArea(corners)

    details = {
        "corners": ordered,
        "width": width,
        "height": height,
        "area": area,
    }

    # Check area ratio
    area_ratio = area / image_area
    if area_ratio < MIN_CARD_AREA_RATIO or area_ratio > MAX_CARD_AREA_RATIO:
        details["reject_reason"] = f"area_ratio={area_ratio:.3f}"
        return 0.0, details

    # Safeguard against zero dimensions
    if width <= 0 or height <= 0:
        details["reject_reason"] = "invalid_dimensions"
        return 0.0, details

    # Calculate aspect ratio (always use larger/smaller for consistency)
    if width > height:
        aspect_ratio = width / height
    else:
        aspect_ratio = height / width
    details["aspect_ratio"] = aspect_ratio

    # Check aspect ratio against credit card standard
    ratio_diff = abs(aspect_ratio - CARD_ASPECT_RATIO) / CARD_ASPECT_RATIO
    if ratio_diff > aspect_ratio_tolerance:
        details["reject_reason"] = f"aspect_ratio={aspect_ratio:.3f}, expected~{CARD_ASPECT_RATIO:.3f}"
        return 0.0, details

    # Compute score (higher is better)
    # minAreaRect always produces perfect rectangles, so no angle check needed.
    # Score based on area size and aspect ratio match.
    area_score = min(area_ratio / 0.1, 1.0)  # Normalize to max at 10% of image
    ratio_score = 1.0 - ratio_diff / aspect_ratio_tolerance

    score = 0.5 * area_score + 0.5 * ratio_score
    details["score_components"] = {
        "area": area_score,
        "ratio": ratio_score,
    }

    return score, details


def find_card_contours(
    image: np.ndarray,
    image_area: float,
    aspect_ratio_tolerance: float = 0.15,
    min_score: float = 0.3,
    debug_dir: Optional[str] = None,
) -> List[np.ndarray]:
    """
    Find potential card contours using a waterfall of detection strategies.

    Strategies are tried in order: Canny → Adaptive → Otsu → Color.
    If a strategy produces a candidate scoring above min_score, subsequent
    strategies are skipped.

    Args:
        image: Input BGR image
        image_area: Total image area in pixels
        aspect_ratio_tolerance: Allowed deviation from standard aspect ratio
        min_score: Minimum score to accept a strategy's candidates
        debug_dir: Optional directory to save debug images

    Returns:
        List of 4-point contour approximations from the first successful strategy
    """
    # Create debug observer if debug mode enabled
    observer = DebugObserver(debug_dir) if debug_dir else None

    h, w = image.shape[:2]
    min_area = h * w * 0.01  # At least 1% of image
    max_area = h * w * 0.5   # At most 50% of image

    # Save original image
    if observer:
        observer.save_stage("01_original", image)

    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if observer:
        observer.save_stage("02_grayscale", gray)

    # Apply bilateral filter to reduce noise while keeping edges
    filtered = cv2.bilateralFilter(gray, 11, 75, 75)
    if observer:
        observer.save_stage("03_bilateral_filtered", filtered)

    def extract_quads(contours, epsilon_factor=0.02, min_rectangularity=0.7,
                       aspect_tolerance=0.15):
        """Extract quadrilaterals from contours using minAreaRect.

        Shape constraints:
        - Rectangularity (contour_area / rect_area): rejects irregular shapes
        - Aspect ratio: rejects rectangles that don't match card proportions
        """
        quads = []
        for contour in contours:
            contour_area = cv2.contourArea(contour)
            if contour_area < min_area or contour_area > max_area:
                continue

            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon_factor * peri, True)

            if len(approx) < 4:
                continue

            rect = cv2.minAreaRect(contour)
            box = cv2.boxPoints(rect).astype(np.float32)

            rect_area = cv2.contourArea(box)
            if rect_area <= 0:
                continue
            rectangularity = contour_area / rect_area
            if rectangularity < min_rectangularity:
                continue

            (_, _), (bw, bh), _ = rect
            if bw <= 0 or bh <= 0:
                continue
            aspect = max(bw, bh) / min(bw, bh)
            if abs(aspect - CARD_ASPECT_RATIO) / CARD_ASPECT_RATIO > aspect_tolerance:
                continue

            quads.append(box.reshape(4, 1, 2))

        return quads

    def dedup_quads(quads, center_threshold=50):
        """Remove near-duplicate boxes, keeping the largest when centers overlap.

        Two boxes are considered duplicates if their centers are within
        center_threshold pixels of each other.
        """
        if len(quads) <= 1:
            return quads

        # Sort by area descending so largest comes first
        quads_with_area = [(q, cv2.contourArea(q)) for q in quads]
        quads_with_area.sort(key=lambda x: x[1], reverse=True)

        kept = []
        for quad, area in quads_with_area:
            center = quad.reshape(4, 2).mean(axis=0)
            is_dup = False
            for kept_quad in kept:
                kept_center = kept_quad.reshape(4, 2).mean(axis=0)
                dist = np.linalg.norm(center - kept_center)
                if dist < center_threshold:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(quad)

        return kept

    def score_best(quads):
        """Return the best score among quads."""
        best = 0.0
        for q in quads:
            corners = q.reshape(4, 2)
            score, _ = score_card_candidate(
                q, corners, image_area, aspect_ratio_tolerance
            )
            best = max(best, score)
        return best

    # --- Waterfall: try strategies in order, stop on first success ---

    # Strategy 1: Canny edge detection with various thresholds
    canny_candidates = []
    canny_configs = [(20, 60), (30, 100), (50, 150), (75, 200), (100, 250)]
    saved_canny_indices = [0, 2, 4]

    for idx, (canny_low, canny_high) in enumerate(canny_configs):
        edges = cv2.Canny(filtered, canny_low, canny_high)

        if idx in saved_canny_indices and observer:
            observer.save_stage(f"04_canny_{canny_low}_{canny_high}", edges)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        edges_morphed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        if idx == 2 and observer:
            observer.save_stage("07_canny_morphology", edges_morphed)

        contours, _ = cv2.findContours(edges_morphed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        canny_candidates.extend(extract_quads(contours))

    canny_candidates = dedup_quads(canny_candidates)

    if observer and canny_candidates:
        observer.draw_and_save("08_canny_contours", image,
                             draw_contours_overlay, canny_candidates, "Canny Edge Detection", StrategyColor.CANNY)

    if canny_candidates and score_best(canny_candidates) >= min_score:
        return canny_candidates

    # Strategy 2: Adaptive thresholding (for varying lighting)
    adaptive_candidates = []
    adaptive_configs = [(11, 2), (21, 5), (31, 10), (51, 10)]
    saved_adaptive = [0, 2]

    for idx, (block_size, C) in enumerate(adaptive_configs):
        thresh = cv2.adaptiveThreshold(
            filtered, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, block_size, C
        )

        if idx in saved_adaptive and observer:
            if idx == 0:
                observer.save_stage("09_adaptive_11_2", thresh)
            elif idx == 2:
                observer.save_stage("10_adaptive_31_10", thresh)

        for img in [thresh, 255 - thresh]:
            contours, _ = cv2.findContours(img, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            adaptive_candidates.extend(extract_quads(contours))

    adaptive_candidates = dedup_quads(adaptive_candidates)

    if observer and adaptive_candidates:
        observer.draw_and_save("11_adaptive_contours", image,
                             draw_contours_overlay, adaptive_candidates, "Adaptive Thresholding", StrategyColor.ADAPTIVE)

    if adaptive_candidates and score_best(adaptive_candidates) >= min_score:
        return adaptive_candidates

    # Strategy 3: Otsu's thresholding
    otsu_candidates = []
    _, otsu = cv2.threshold(filtered, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if observer:
        observer.save_stage("12_otsu_binary", otsu)

    otsu_inverted = 255 - otsu
    if observer:
        observer.save_stage("13_otsu_inverted", otsu_inverted)

    for img in [otsu, otsu_inverted]:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        img_morphed = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(img_morphed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        otsu_candidates.extend(extract_quads(contours))

    otsu_candidates = dedup_quads(otsu_candidates)

    if observer and otsu_candidates:
        observer.draw_and_save("14_otsu_contours", image,
                             draw_contours_overlay, otsu_candidates, "Otsu Thresholding", StrategyColor.OTSU)

    if otsu_candidates and score_best(otsu_candidates) >= min_score:
        return otsu_candidates

    # Strategy 4: Color-based segmentation (gray card on light background)
    color_candidates = []
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    if observer:
        observer.save_stage("15_hsv_saturation", sat)

    _, low_sat_mask = cv2.threshold(sat, 30, 255, cv2.THRESH_BINARY_INV)
    if observer:
        observer.save_stage("16_low_sat_mask", low_sat_mask)

    val = hsv[:, :, 2]
    gray_mask = cv2.bitwise_and(low_sat_mask, cv2.inRange(val, 80, 200))

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    gray_mask = cv2.morphologyEx(gray_mask, cv2.MORPH_CLOSE, kernel)
    gray_mask = cv2.morphologyEx(gray_mask, cv2.MORPH_OPEN, kernel)
    if observer:
        observer.save_stage("17_gray_mask", gray_mask)

    contours, _ = cv2.findContours(gray_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    color_candidates = dedup_quads(extract_quads(contours, epsilon_factor=0.03))

    if observer and color_candidates:
        observer.draw_and_save("18_color_contours", image,
                             draw_contours_overlay, color_candidates, "Color-Based Detection", StrategyColor.COLOR_BASED)

    if color_candidates and score_best(color_candidates) >= min_score:
        return color_candidates

    # No strategy succeeded — return all collected candidates as last resort
    all_candidates = canny_candidates + adaptive_candidates + otsu_candidates + color_candidates
    if observer and all_candidates:
        observer.draw_and_save("19_all_candidates", image,
                             draw_contours_overlay, all_candidates, "All Candidates (fallback)", StrategyColor.ALL_CANDIDATES)
    return all_candidates


def detect_credit_card(
    image: np.ndarray,
    aspect_ratio_tolerance: float = 0.15,
    debug_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Detect a credit card in the image.

    Args:
        image: Input BGR image
        aspect_ratio_tolerance: Allowed deviation from standard aspect ratio
        debug_dir: Optional directory to save debug images

    Returns:
        Dictionary containing:
        - corners: 4x2 array of corner points (ordered)
        - contour: Full contour points
        - confidence: Detection confidence score
        - width_px, height_px: Detected dimensions
        - aspect_ratio: Detected aspect ratio
        Or None if no card detected
    """
    # Create debug observer if debug mode enabled
    observer = DebugObserver(debug_dir) if debug_dir else None
    
    if observer:
        logger.info("card detection debug → %s", debug_dir)

    h, w = image.shape[:2]
    image_area = h * w

    # Find candidate contours (waterfall: stops after first successful strategy)
    candidates = find_card_contours(
        image, image_area=image_area,
        aspect_ratio_tolerance=aspect_ratio_tolerance,
        debug_dir=debug_dir,
    )

    if not candidates:
        logger.debug("classic card: no candidates found")
        return None

    # Score each candidate
    best_score = 0.0
    best_result = None
    all_scored = []

    for contour in candidates:
        corners = contour.reshape(4, 2)
        score, details = score_card_candidate(
            contour, corners, image_area, aspect_ratio_tolerance
        )

        all_scored.append((corners, score, details))

        if score > best_score:
            best_score = score
            best_result = details

    # Sort by score (descending) and take top 5
    all_scored.sort(key=lambda x: x[1], reverse=True)
    top_candidates = all_scored[:5]

    # Save scored candidates visualization
    if observer and top_candidates:
        observer.draw_and_save("20_scored_candidates", image,
                             draw_candidates_with_scores, top_candidates, "Top 5 Candidates")

    if best_result is None or best_score < 0.3:
        logger.debug("classic card: best score %.2f below threshold 0.3", best_score)
        return None

    # Save final detection
    if observer:
        final_overlay = image.copy()
        corners = best_result["corners"].astype(np.int32)
        cv2.polylines(final_overlay, [corners], True, Color.GREEN, Size.CONTOUR_THICK)

        # Draw corners
        for pt in corners:
            cv2.circle(final_overlay, tuple(pt), Size.CORNER_RADIUS + 2, Color.RED, -1)

        # Add details text
        text_y = Layout.TITLE_Y
        details_text = [
            "Final Detection",
            f"Score: {best_score:.3f}",
            f"Aspect Ratio: {best_result['aspect_ratio']:.3f}",
            f"Dimensions: {best_result['width']:.0f}x{best_result['height']:.0f}px",
        ]

        for text in details_text:
            cv2.putText(
                final_overlay, text, (Layout.TEXT_OFFSET_X, text_y),
                FONT_FACE, FontScale.SUBTITLE, Color.WHITE,
                FontThickness.SUBTITLE_OUTLINE, cv2.LINE_AA
            )
            cv2.putText(
                final_overlay, text, (Layout.TEXT_OFFSET_X, text_y),
                FONT_FACE, FontScale.SUBTITLE, Color.GREEN,
                FontThickness.SUBTITLE, cv2.LINE_AA
            )
            text_y += Layout.LINE_SPACING

        observer.save_stage("21_final_detection", final_overlay)

    return {
        "corners": best_result["corners"],
        "contour": best_result["corners"],
        "confidence": best_score,
        "width_px": best_result["width"],
        "height_px": best_result["height"],
        "aspect_ratio": best_result["aspect_ratio"],
    }


def rectify_card(
    image: np.ndarray,
    corners: np.ndarray,
    output_width: int = 856,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply perspective transform to rectify the card region.

    Args:
        image: Input BGR image
        corners: Ordered 4x2 array of corner points (TL, TR, BR, BL)
        output_width: Width of output image (height computed from aspect ratio)

    Returns:
        Tuple of (rectified_image, transform_matrix)
    """
    corners = corners.astype(np.float32)

    # Determine if card is in portrait or landscape orientation
    width, height = get_quad_dimensions(corners)

    if width > height:
        # Landscape orientation
        out_w = output_width
        out_h = int(output_width / CARD_ASPECT_RATIO)
    else:
        # Portrait orientation (rotated 90°)
        out_h = output_width
        out_w = int(output_width / CARD_ASPECT_RATIO)

    # Destination points
    dst = np.array([
        [0, 0],
        [out_w - 1, 0],
        [out_w - 1, out_h - 1],
        [0, out_h - 1],
    ], dtype=np.float32)

    # Compute perspective transform
    M = cv2.getPerspectiveTransform(corners, dst)

    # Apply transform
    rectified = cv2.warpPerspective(image, M, (out_w, out_h))

    return rectified, M


def compute_scale_factor(
    corners: np.ndarray,
) -> Tuple[float, float]:
    """
    Compute pixels-per-cm scale factor from detected card corners.

    Args:
        corners: Ordered 4x2 array of corner points

    Returns:
        Tuple of (px_per_cm, confidence)
    """
    width_px, height_px = get_quad_dimensions(corners)

    # Determine orientation and compute scale
    if width_px > height_px:
        # Landscape: width corresponds to card width (8.56 cm)
        px_per_cm_w = width_px / CARD_WIDTH_CM
        px_per_cm_h = height_px / CARD_HEIGHT_CM
    else:
        # Portrait: width corresponds to card height (5.398 cm)
        px_per_cm_w = width_px / CARD_HEIGHT_CM
        px_per_cm_h = height_px / CARD_WIDTH_CM

    # Average the two estimates
    px_per_cm = (px_per_cm_w + px_per_cm_h) / 2

    # Confidence based on consistency between width and height estimates
    consistency = 1.0 - abs(px_per_cm_w - px_per_cm_h) / max(px_per_cm_w, px_per_cm_h)
    confidence = max(0.0, min(1.0, consistency))

    return px_per_cm, confidence
