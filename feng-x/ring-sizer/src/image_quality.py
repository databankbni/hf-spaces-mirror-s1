"""
Image quality assessment utilities.

This module handles:
- Blur detection using Laplacian variance
- Exposure/contrast analysis
- Overall quality scoring
"""

import cv2
import numpy as np
from typing import Dict, Any, Tuple


# Quality thresholds
BLUR_THRESHOLD = 20.0  # Laplacian variance below this is considered blurry
MIN_BRIGHTNESS = 40  # Mean brightness below this is underexposed
MAX_BRIGHTNESS = 220  # Mean brightness above this is overexposed
MIN_CONTRAST = 30  # Std dev below this indicates low contrast


def detect_blur(image: np.ndarray) -> Tuple[float, bool]:
    """
    Detect image blur using Laplacian variance method.

    The Laplacian operator highlights regions of rapid intensity change,
    so a well-focused image will have high variance in Laplacian response.

    Args:
        image: Input BGR image

    Returns:
        Tuple of (blur_score, is_sharp)
        - blur_score: Laplacian variance (higher = sharper)
        - is_sharp: True if image passes sharpness threshold
    """
    # Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    # Compute Laplacian
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)

    # Variance of Laplacian indicates focus quality
    blur_score = laplacian.var()

    is_sharp = blur_score >= BLUR_THRESHOLD

    return blur_score, is_sharp


def check_exposure(image: np.ndarray) -> Dict[str, Any]:
    """
    Check image exposure and contrast using histogram analysis.

    Args:
        image: Input BGR image

    Returns:
        Dictionary containing:
        - brightness: Mean brightness (0-255)
        - contrast: Standard deviation of brightness
        - is_underexposed: True if image is too dark
        - is_overexposed: True if image is too bright
        - has_good_contrast: True if contrast is sufficient
    """
    # Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    # Calculate statistics
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))

    # Check exposure conditions
    is_underexposed = brightness < MIN_BRIGHTNESS
    is_overexposed = brightness > MAX_BRIGHTNESS
    has_good_contrast = contrast >= MIN_CONTRAST

    return {
        "brightness": brightness,
        "contrast": contrast,
        "is_underexposed": is_underexposed,
        "is_overexposed": is_overexposed,
        "has_good_contrast": has_good_contrast,
    }


def check_resolution(image: np.ndarray, min_dimension: int = 720) -> Dict[str, Any]:
    """
    Check if image resolution is sufficient.

    Args:
        image: Input BGR image
        min_dimension: Minimum acceptable dimension (default 720 for 720p)

    Returns:
        Dictionary containing:
        - width: Image width in pixels
        - height: Image height in pixels
        - is_sufficient: True if resolution meets minimum
    """
    height, width = image.shape[:2]
    min_dim = min(width, height)

    return {
        "width": width,
        "height": height,
        "is_sufficient": min_dim >= min_dimension,
    }


def assess_image_quality(image: np.ndarray) -> Dict[str, Any]:
    """
    Comprehensive image quality assessment.

    Combines blur detection, exposure check, and resolution check
    to determine if image is suitable for processing.

    Args:
        image: Input BGR image

    Returns:
        Dictionary containing:
        - passed: True if image passes all quality checks
        - blur_score: Laplacian variance score
        - brightness: Mean brightness
        - contrast: Standard deviation
        - resolution: (width, height)
        - issues: List of quality issues found
        - fail_reason: Primary failure reason if failed, else None
    """
    issues = []
    fail_reason = None

    # Check blur
    blur_score, is_sharp = detect_blur(image)
    if not is_sharp:
        issues.append(f"Image is blurry (score: {blur_score:.1f}, threshold: {BLUR_THRESHOLD})")
        if fail_reason is None:
            fail_reason = "image_too_blurry"

    # Check exposure
    exposure = check_exposure(image)
    if exposure["is_underexposed"]:
        issues.append(f"Image is underexposed (brightness: {exposure['brightness']:.1f})")
        if fail_reason is None:
            fail_reason = "image_underexposed"
    if exposure["is_overexposed"]:
        issues.append(f"Image is overexposed (brightness: {exposure['brightness']:.1f})")
        if fail_reason is None:
            fail_reason = "image_overexposed"
    if not exposure["has_good_contrast"]:
        issues.append(f"Image has low contrast (std: {exposure['contrast']:.1f})")
        if fail_reason is None:
            fail_reason = "image_low_contrast"

    # Check resolution
    resolution = check_resolution(image)
    if not resolution["is_sufficient"]:
        issues.append(
            f"Resolution too low ({resolution['width']}x{resolution['height']})"
        )
        if fail_reason is None:
            fail_reason = "image_resolution_too_low"

    passed = len(issues) == 0

    return {
        "passed": passed,
        "blur_score": round(blur_score, 2),
        "brightness": round(exposure["brightness"], 2),
        "contrast": round(exposure["contrast"], 2),
        "resolution": (resolution["width"], resolution["height"]),
        "issues": issues,
        "fail_reason": fail_reason,
    }


def check_card_in_frame(
    card_corners: np.ndarray,
    image_shape: tuple,
    margin_pct: float = 0.02,
) -> Dict[str, Any]:
    """Check if credit card is fully within the image frame.

    Args:
        card_corners: 4x2 array of card corner coordinates (x, y)
        image_shape: (height, width) of image
        margin_pct: minimum margin from edge as fraction of image dimension

    Returns:
        Dict with:
            - in_frame: bool
            - min_margin_px: float (smallest distance from any corner to any edge)
            - fail_reason: str or None
    """
    h, w = image_shape[:2]
    margin_x = w * margin_pct
    margin_y = h * margin_pct

    min_margin_px = float("inf")
    in_frame = True

    for corner in card_corners:
        x, y = float(corner[0]), float(corner[1])
        dist_left = x
        dist_right = w - x
        dist_top = y
        dist_bottom = h - y
        corner_min = min(dist_left, dist_right, dist_top, dist_bottom)
        min_margin_px = min(min_margin_px, corner_min)

        if x < margin_x or x > w - margin_x or y < margin_y or y > h - margin_y:
            in_frame = False

    fail_reason = None if in_frame else "card_near_edge"

    return {
        "in_frame": in_frame,
        "min_margin_px": min_margin_px,
        "fail_reason": fail_reason,
    }


def check_finger_spacing(
    all_landmarks: Dict[str, np.ndarray],
    image_shape: tuple,
    min_spacing_pct: float = 0.03,
) -> Dict[str, Any]:
    """Check if fingers are spread apart enough for accurate measurement.

    Args:
        all_landmarks: Dict mapping finger name to 4x2 landmarks array
        image_shape: (height, width) of image
        min_spacing_pct: minimum spacing between adjacent fingers as fraction of image width

    Returns:
        Dict with:
            - well_spaced: bool
            - min_spacing_px: float
            - closest_pair: tuple of finger names or None
            - fail_reason: str or None
    """
    min_spacing = image_shape[1] * min_spacing_pct
    finger_names = list(all_landmarks.keys())

    min_spacing_px = float("inf")
    closest_pair = None
    well_spaced = True

    for i in range(len(finger_names) - 1):
        name_a = finger_names[i]
        name_b = finger_names[i + 1]
        pip_a = np.array(all_landmarks[name_a][1], dtype=float)
        pip_b = np.array(all_landmarks[name_b][1], dtype=float)
        dist = float(np.linalg.norm(pip_a - pip_b))

        if dist < min_spacing_px:
            min_spacing_px = dist
            closest_pair = (name_a, name_b)

    if min_spacing_px < min_spacing:
        well_spaced = False

    fail_reason = None if well_spaced else "fingers_too_close"

    return {
        "well_spaced": well_spaced,
        "min_spacing_px": min_spacing_px,
        "closest_pair": closest_pair,
        "fail_reason": fail_reason,
    }


def check_lighting_uniformity(
    image: np.ndarray,
    threshold: float = 0.4,
) -> Dict[str, Any]:
    """Check for even lighting across the image.

    Args:
        image: Input BGR image
        threshold: maximum allowed ratio between darkest and brightest quadrant means

    Returns:
        Dict with:
            - uniform: bool
            - brightness_range: float (max_quadrant - min_quadrant)
            - fail_reason: str or None
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    h, w = gray.shape[:2]
    mid_y, mid_x = h // 2, w // 2

    quadrants = [
        gray[:mid_y, :mid_x],
        gray[:mid_y, mid_x:],
        gray[mid_y:, :mid_x],
        gray[mid_y:, mid_x:],
    ]
    means = [float(np.mean(q)) for q in quadrants]

    max_mean = max(means)
    min_mean = min(means)
    brightness_range = max_mean - min_mean

    uniform = True
    if max_mean > 0 and brightness_range / max_mean > threshold:
        uniform = False

    fail_reason = None if uniform else "image_quality_low_lighting"

    return {
        "uniform": uniform,
        "brightness_range": brightness_range,
        "fail_reason": fail_reason,
    }
