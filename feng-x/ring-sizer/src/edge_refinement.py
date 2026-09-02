"""Edge refinement anchored on the SAM finger mask.

Supports two modes:
- ``mask_only``: measure width directly from the SAM mask boundary.
- ``sobel_only``: subpixel gradient refinement anchored on the SAM boundary.
"""

import cv2
import numpy as np
import logging
from typing import Dict, Any, Optional, Tuple, List

from src.edge_refinement_constants import (
    # Sobel Filter
    DEFAULT_KERNEL_SIZE,
    VALID_KERNEL_SIZES,
    # Edge Detection
    DEFAULT_GRADIENT_THRESHOLD,
    MIN_FINGER_WIDTH_CM,
    MAX_FINGER_WIDTH_CM,
    WIDTH_TOLERANCE_FACTOR,
    # Sub-Pixel Refinement
    MAX_SUBPIXEL_OFFSET,
    MIN_PARABOLA_DENOMINATOR,
    # Outlier Filtering
    MAD_OUTLIER_THRESHOLD,
    # Edge Quality Scoring
    GRADIENT_STRENGTH_NORMALIZER,
    SMOOTHNESS_VARIANCE_NORMALIZER,
    QUALITY_WEIGHT_GRADIENT,
    QUALITY_WEIGHT_CONSISTENCY,
    QUALITY_WEIGHT_SMOOTHNESS,
    QUALITY_WEIGHT_SYMMETRY,
)

# Configure logging
logger = logging.getLogger(__name__)

# Minimum valid cross-sections required for a trustworthy mask-based width
# measurement. Below this the median is too sensitive to individual row
# errors (webbing leakage, axis drift, finger tilt), so callers should fail
# the measurement rather than report a potentially-wrong number. 20 keeps
# parity with the contour path's 20-sample target.
MIN_MASK_SAMPLES = 20


# =============================================================================
# Helper Functions (extracted from nested scope)
# =============================================================================

def _get_axis_x_at_row(row_y: float, axis_center: Optional[np.ndarray],
                       axis_direction: Optional[np.ndarray], width: int) -> float:
    """
    Get axis x-coordinate at given row y-coordinate.

    Args:
        row_y: Row y-coordinate
        axis_center: Axis center point (x, y)
        axis_direction: Axis direction vector (dx, dy)
        width: Image width (for fallback)

    Returns:
        X-coordinate of axis at given row
    """
    if axis_center is None or axis_direction is None:
        return width / 2  # Fallback to center

    if abs(axis_direction[1]) < 1e-6:
        # Nearly horizontal axis
        return axis_center[0]
    else:
        # Parametric line: P = axis_center + t * axis_direction
        t = (row_y - axis_center[1]) / axis_direction[1]
        return axis_center[0] + t * axis_direction[0]


def _find_edges_from_axis(
    row_gradient: np.ndarray,
    row_y: float,
    axis_x: float,
    threshold: float,
    min_width_px: Optional[float],
    max_width_px: Optional[float],
    row_mask: Optional[np.ndarray] = None,
    row_gradient_left_to_right: Optional[np.ndarray] = None,
    row_gradient_right_to_left: Optional[np.ndarray] = None,
    mask_only: bool = False,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Find left and right edges by expanding from axis position.

    Strategy:
    - MASK-CONSTRAINED MODE (when row_mask provided):
      1. Find leftmost/rightmost mask pixels (finger boundaries)
      2. Search for strongest gradient within ±10px of mask boundaries
      3. Combines anatomical accuracy (mask) with sub-pixel precision (gradient)

    - AXIS-EXPANSION MODE (when row_mask is None):
      1. Start at axis x-coordinate (INSIDE the finger)
      2. Search LEFT/RIGHT from axis for closest salient edge
      3. Validate width is within realistic range

    Args:
        row_gradient: Gradient magnitude for this row
        row_y: Row y-coordinate
        axis_x: Axis x-coordinate at this row
        threshold: Gradient threshold for valid edge
        min_width_px: Minimum valid width in pixels (None to skip)
        max_width_px: Maximum valid width in pixels (None to skip)
        row_mask: Optional mask row (True = finger pixel) for constrained search
        row_gradient_left_to_right: Optional directional gradient map for right edge search
        row_gradient_right_to_left: Optional directional gradient map for left edge search

    Returns:
        Tuple of (left_x, right_x, left_strength, right_strength) or None if invalid
    """
    if axis_x < 0 or axis_x >= len(row_gradient):
        return None

    # Direction-aware gradient maps (preferred when available):
    # - left boundary should come from right-to-left transition
    # - right boundary should come from left-to-right transition
    left_search_gradient = row_gradient_right_to_left if row_gradient_right_to_left is not None else row_gradient
    right_search_gradient = row_gradient_left_to_right if row_gradient_left_to_right is not None else row_gradient

    # In mask_only mode a row with no mask pixels (or a mask that doesn't
    # contain the finger axis) must be dropped. Otherwise we would fall
    # through to the gradient axis-expansion path below, which routinely
    # returns ROI-edge coordinates as "edges" on empty rows and poisons the
    # width median.
    if mask_only and (row_mask is None or not np.any(row_mask)):
        return None

    # MASK-CONSTRAINED MODE (preferred when available)
    if row_mask is not None and np.any(row_mask):
        # Strategy: the SAM mask already knows where the finger boundary is
        # to pixel accuracy. We anchor to the mask boundary by default, and
        # only snap to a nearby gradient peak when one exceeds the threshold
        # (for sub-pixel refinement). When contrast is weak (pale finger on
        # light background) the gradient search yields nothing, so trusting
        # the mask directly is what prevents "no valid widths" failures.

        mask_indices = np.where(row_mask)[0]
        if len(mask_indices) < 2:
            return None  # Mask too small

        # Pick the contiguous run of mask pixels that contains the finger
        # axis. This matters when the raw SAM hand mask is passed in (mask_only
        # path): at the ring-zone rows the mask may include adjacent fingers,
        # and np.where(...)[0][0]/[-1] would then span across fingers.
        axis_col = int(round(axis_x))
        axis_col = max(0, min(len(row_mask) - 1, axis_col))
        if not row_mask[axis_col]:
            # Axis is off the mask on this row — the ROI is clipping into
            # background (e.g. ring/pinky ROI reaching the MCP webbing).
            # Treat the row as invalid rather than snapping to whatever mask
            # run happens to be nearest; otherwise the wrong run can pull
            # the median width up.
            return None

        # Expand left/right from the axis until we leave the mask run.
        left_mask_boundary = axis_col
        while left_mask_boundary > 0 and row_mask[left_mask_boundary - 1]:
            left_mask_boundary -= 1
        right_mask_boundary = axis_col
        max_col = len(row_mask) - 1
        while right_mask_boundary < max_col and row_mask[right_mask_boundary + 1]:
            right_mask_boundary += 1

        # If the contiguous run reaches either ROI edge the mask has bled
        # out of the ROI laterally — almost always via the webbing into the
        # adjacent finger. The column we stopped at is the ROI edge, not
        # the true finger boundary, so the row is unreliable.
        if mask_only and (left_mask_boundary == 0 or right_mask_boundary == max_col):
            return None

        SEARCH_RANGE = 10  # px on either side of mask boundary to refine

        def _snap_to_peak(
            boundary: int,
            gradient: np.ndarray,
        ) -> Tuple[float, float]:
            """Return (edge_x, strength). Snap to local gradient peak if
            it exceeds threshold, otherwise fall back to boundary itself."""
            lo = max(0, boundary - SEARCH_RANGE)
            hi = min(len(gradient) - 1, boundary + SEARCH_RANGE)
            if hi < lo:
                return float(boundary), 0.0
            window = gradient[lo:hi + 1]
            best_rel = int(np.argmax(window))
            best_val = float(window[best_rel])
            if best_val > threshold:
                return float(lo + best_rel), best_val
            # Weak gradient: trust the SAM mask boundary directly.
            return float(boundary), float(gradient[boundary])

        if mask_only:
            # Trust the SAM mask boundary exactly; no gradient snapping.
            left_edge_x = float(left_mask_boundary)
            right_edge_x = float(right_mask_boundary)
            left_strength = float(left_search_gradient[left_mask_boundary])
            right_strength = float(right_search_gradient[right_mask_boundary])
        else:
            left_edge_x, left_strength = _snap_to_peak(
                left_mask_boundary, left_search_gradient
            )
            right_edge_x, right_strength = _snap_to_peak(
                right_mask_boundary, right_search_gradient
            )

    else:
        # AXIS-EXPANSION MODE (fallback when no mask)
        # Search LEFT from axis (go leftward)
        left_edge_x = None
        left_strength = 0
        for x in range(int(axis_x), -1, -1):
            if left_search_gradient[x] > threshold:
                # Found a salient edge - this is our left boundary
                left_edge_x = x
                left_strength = left_search_gradient[x]
                break

        # Search RIGHT from axis (go rightward)
        right_edge_x = None
        right_strength = 0
        for x in range(int(axis_x), len(row_gradient)):
            if right_search_gradient[x] > threshold:
                # Found a salient edge - this is our right boundary
                right_edge_x = x
                right_strength = right_search_gradient[x]
                break

        if left_edge_x is None or right_edge_x is None:
            return None

    # Validate width is within realistic finger range
    width = right_edge_x - left_edge_x
    if min_width_px is not None and max_width_px is not None:
        if width < min_width_px or width > max_width_px:
            return None  # Width out of realistic range

    return (left_edge_x, right_edge_x, left_strength, right_strength)


# =============================================================================
# Main Functions
# =============================================================================

def extract_ring_zone_roi(
    image: np.ndarray,
    axis_data: Dict[str, Any],
    zone_data: Dict[str, Any],
    rotate_align: bool = False,
    finger_mask: Optional[np.ndarray] = None,
    finger_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract ROI around ring zone.

    The ROI is sized from the zone length (|DIP - PIP|): 1.5x wide, 0.5x tall,
    centered on the ring zone center. This scales naturally with camera
    distance since it's derived from anatomical landmarks.

    Args:
        image: Input BGR image
        axis_data: Output from estimate_finger_axis()
        zone_data: Output from localize_ring_zone()
        rotate_align: If True, rotate ROI so finger axis is vertical

    Returns:
        Dictionary containing:
        - roi_image: Extracted ROI (grayscale)
        - roi_mask: Full ROI mask (all 255)
        - roi_bounds: (x_min, y_min, x_max, y_max) in original image
        - transform_matrix: 3x3 matrix to map ROI coords -> original coords
        - inverse_transform: 3x3 matrix to map original -> ROI coords
        - rotation_angle: Rotation angle applied (degrees)
        - roi_width: ROI width in pixels
        - roi_height: ROI height in pixels
    """
    h, w = image.shape[:2]

    # ROI centered on ring zone center, sized from |DIP - PIP| distance:
    #   height = 0.5x zone length (along finger axis)
    #   width  = 1.5x zone length (perpendicular, wider to capture full finger edges)
    zone_length = zone_data["length"]
    center = zone_data["center_point"]
    direction = axis_data["direction"]
    # Ring and pinky have their proximal phalanx set lower on the palm than
    # index/middle, so an ROI sized for the latter reaches down into the
    # MCP webbing — those rows bleed into the adjacent finger's mask. Use
    # half the vertical span (0.25x zone length) for those fingers.
    if finger_name in ("ring", "pinky"):
        half_height = zone_length * 0.25   # 0.25x / 2
    else:
        half_height = zone_length * 0.25   # 0.5x / 2
    # ROI width = 1.6x zone_length. zone_length = |DIP-PIP| can be close to
    # finger width on chubby/short proximal phalanxes; 1.2x left almost no
    # margin and the SAM mask hit the ROI wall on slightly off-axis fingers,
    # which the right_mask_boundary == max_col guard then rejected as bleed.
    half_width = zone_length * 0.8

    x_min = int(np.clip(center[0] - half_width, 0, w - 1))
    x_max = int(np.clip(center[0] + half_width, 0, w - 1))
    y_min = int(np.clip(center[1] - half_height, 0, h - 1))
    y_max = int(np.clip(center[1] + half_height, 0, h - 1))

    roi_width = x_max - x_min
    roi_height = y_max - y_min

    if roi_width < 10 or roi_height < 10:
        raise ValueError(f"ROI too small: {roi_width}x{roi_height}")

    # Extract ROI
    roi_bgr = image[y_min:y_max, x_min:x_max].copy()

    # Convert to grayscale for edge detection
    roi_gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)

    # Build the per-row search constraint. Prefer a pixel-accurate finger mask
    # when one is supplied (e.g. SAM 2.1 output). Falling back to a full-rect
    # all-ones mask preserves legacy behaviour.
    if finger_mask is not None:
        fm = finger_mask
        if fm.dtype != np.uint8:
            fm = (fm > 0).astype(np.uint8) * 255
        if fm.shape[:2] != image.shape[:2]:
            fm = cv2.resize(
                fm, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST
            )
        roi_mask = fm[y_min:y_max, x_min:x_max].copy()
        if not np.any(roi_mask):
            roi_mask = np.ones((roi_height, roi_width), dtype=np.uint8) * 255
    else:
        roi_mask = np.ones((roi_height, roi_width), dtype=np.uint8) * 255

    # Create transform matrix (ROI coords -> original coords)
    # Simple translation for non-rotated case
    transform = np.eye(3, dtype=np.float32)
    transform[0, 2] = x_min  # Translation in x
    transform[1, 2] = y_min  # Translation in y

    inverse_transform = np.linalg.inv(transform)

    rotation_angle = 0.0

    # Optional rotation alignment
    if rotate_align:
        # Calculate rotation angle to make finger vertical
        # Finger direction -> make it point upward (0, -1)
        # Current direction is (dx, dy), want to rotate to (0, -1)
        rotation_angle = np.degrees(np.arctan2(-direction[0], direction[1]))

        # Get rotation matrix
        roi_center = (roi_width / 2.0, roi_height / 2.0)
        rotation_matrix = cv2.getRotationMatrix2D(roi_center, rotation_angle, 1.0)

        # Rotate ROI
        roi_gray = cv2.warpAffine(
            roi_gray, rotation_matrix, (roi_width, roi_height),
            flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        )

        # Update transform matrices
        # Rotation matrix is 2x3, convert to 3x3 for composition
        rotation_matrix_3x3 = np.eye(3, dtype=np.float32)
        rotation_matrix_3x3[:2, :] = rotation_matrix

        # Compose: translate then rotate
        transform = np.dot(rotation_matrix_3x3, transform)
        inverse_transform = np.linalg.inv(transform)

    # Convert axis center point and direction to ROI coordinates
    axis_center = axis_data.get("center", center)
    roi_offset = np.array([x_min, y_min], dtype=np.float32)
    axis_center_in_roi = axis_center - roi_offset

    # Direction vector stays the same (it's not affected by translation)
    axis_direction_in_roi = direction.copy()

    zone_start = zone_data["start_point"]
    zone_end = zone_data["end_point"]

    return {
        "roi_image": roi_gray,
        "roi_mask": roi_mask,
        "roi_bgr": roi_bgr,  # Keep BGR for debug visualization
        "roi_bounds": (x_min, y_min, x_max, y_max),
        "transform_matrix": transform,
        "inverse_transform": inverse_transform,
        "rotation_angle": rotation_angle,
        "roi_width": roi_width,
        "roi_height": roi_height,
        "zone_start_in_roi": zone_start - roi_offset,
        "zone_end_in_roi": zone_end - roi_offset,
        "axis_center_in_roi": axis_center_in_roi,
        "axis_direction_in_roi": axis_direction_in_roi,
    }


def apply_sobel_filters(
    roi_image: np.ndarray,
    kernel_size: int = DEFAULT_KERNEL_SIZE,
    axis_direction: str = "auto"
) -> Dict[str, Any]:
    """
    Apply bidirectional Sobel filters to detect edges.

    For vertical finger (axis_direction="vertical"):
    - Use horizontal Sobel kernels (detect left/right edges)

    For horizontal finger (axis_direction="horizontal"):
    - Use vertical Sobel kernels (detect top/bottom edges)

    Auto mode detects orientation from ROI aspect ratio.

    Args:
        roi_image: Grayscale ROI image
        kernel_size: Sobel kernel size (3, 5, or 7)
        axis_direction: Finger axis direction ("auto", "vertical", "horizontal")

    Returns:
        Dictionary containing:
        - gradient_x: Horizontal gradient (Sobel X)
        - gradient_y: Vertical gradient (Sobel Y)
        - gradient_left_to_right: Positive X-gradient map (right-half gated in horizontal mode)
        - gradient_right_to_left: Negative X-gradient map (left-half gated in horizontal mode)
        - gradient_magnitude: Combined gradient magnitude
        - gradient_direction: Edge orientation (radians)
        - kernel_size: Kernel size used
        - filter_orientation: "horizontal" or "vertical"
    """
    if kernel_size not in VALID_KERNEL_SIZES:
        raise ValueError(f"Invalid kernel_size: {kernel_size}. Use {VALID_KERNEL_SIZES}")

    h, w = roi_image.shape

    # Determine filter orientation
    if axis_direction == "auto":
        # After rotation normalization, finger is always vertical (upright)
        # Finger runs vertically → detect left/right edges → use horizontal filter
        #
        # NOTE: ROI aspect ratio is NOT reliable after rotation normalization!
        # The ROI may be wider than tall even when finger is vertical.
        # Always use horizontal filter orientation for upright hands.
        filter_orientation = "horizontal"  # Detect left/right edges for vertical finger
    elif axis_direction == "vertical":
        filter_orientation = "horizontal"
    elif axis_direction == "horizontal":
        filter_orientation = "vertical"
    else:
        raise ValueError(f"Invalid axis_direction: {axis_direction}")

    # Apply Sobel filters
    # Sobel X detects vertical edges (left/right boundaries)
    # Sobel Y detects horizontal edges (top/bottom boundaries)

    # Use cv2.Sobel for standard implementation
    grad_x = cv2.Sobel(roi_image, cv2.CV_64F, 1, 0, ksize=kernel_size)
    grad_y = cv2.Sobel(roi_image, cv2.CV_64F, 0, 1, ksize=kernel_size)

    # Directional Sobel responses along X:
    # - left_to_right: rising intensity while moving left -> right
    # - right_to_left: falling intensity while moving left -> right
    gradient_left_to_right = np.maximum(grad_x, 0.0)
    gradient_right_to_left = np.maximum(-grad_x, 0.0)

    # Spatial gating to reduce nearby non-target finger interference:
    # - left_to_right only on ROI right half
    # - right_to_left only on ROI left half
    roi_split_x = w // 2
    if filter_orientation == "horizontal":
        gradient_left_to_right[:, :roi_split_x] = 0.0
        gradient_right_to_left[:, roi_split_x:] = 0.0
        gradient_magnitude = np.sqrt(gradient_left_to_right**2 + gradient_right_to_left**2)
    else:
        # Vertical mode fallback keeps the original behavior.
        gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)

    # Calculate gradient direction (angle)
    gradient_direction = np.arctan2(grad_y, grad_x)

    # Normalize gradients to 0-255 for visualization
    grad_x_normalized = np.clip(np.abs(grad_x), 0, 255).astype(np.uint8)
    grad_y_normalized = np.clip(np.abs(grad_y), 0, 255).astype(np.uint8)
    grad_mag_normalized = np.clip(gradient_magnitude, 0, 255).astype(np.uint8)
    grad_l2r_normalized = np.clip(gradient_left_to_right, 0, 255).astype(np.uint8)
    grad_r2l_normalized = np.clip(gradient_right_to_left, 0, 255).astype(np.uint8)

    return {
        "gradient_x": grad_x,
        "gradient_y": grad_y,
        "gradient_left_to_right": gradient_left_to_right,
        "gradient_right_to_left": gradient_right_to_left,
        "gradient_magnitude": gradient_magnitude,
        "gradient_direction": gradient_direction,
        "gradient_x_normalized": grad_x_normalized,
        "gradient_y_normalized": grad_y_normalized,
        "gradient_left_to_right_normalized": grad_l2r_normalized,
        "gradient_right_to_left_normalized": grad_r2l_normalized,
        "gradient_mag_normalized": grad_mag_normalized,
        "kernel_size": kernel_size,
        "filter_orientation": filter_orientation,
        "roi_split_x": roi_split_x,
    }


def detect_edges_per_row(
    gradient_data: Dict[str, Any],
    roi_data: Dict[str, Any],
    threshold: float = DEFAULT_GRADIENT_THRESHOLD,
    expected_width_px: Optional[float] = None,
    scale_px_per_cm: Optional[float] = None,
    mask_only: bool = False,
) -> Dict[str, Any]:
    """
    Detect left and right finger edges for each row (cross-section).

    Uses mask-constrained mode when roi_mask is available:
    1. Find leftmost/rightmost mask pixels (anatomical finger boundaries)
    2. Search for gradient peaks within ±10px of mask boundaries
    3. Combines anatomical accuracy with sub-pixel gradient precision

    Falls back to axis-expansion mode when no mask:
    1. Start at finger axis (guaranteed inside finger)
    2. Expand left/right to find nearest salient edges
    3. Validate width is within realistic range

    Args:
        gradient_data: Output from apply_sobel_filters()
        roi_data: Output from extract_ring_zone_roi()
        threshold: Minimum gradient magnitude for valid edge
        expected_width_px: Expected finger width from contour (optional)
        scale_px_per_cm: Scale factor for width validation (optional)

    Returns:
        Dictionary containing:
        - left_edges: Array of left edge x-coordinates (one per row)
        - right_edges: Array of right edge x-coordinates (one per row)
        - edge_strengths_left: Gradient magnitude at left edges
        - edge_strengths_right: Gradient magnitude at right edges
        - valid_rows: Boolean mask of rows with successful detection
        - num_valid_rows: Count of successful detections
        - mode_used: "mask_constrained" or "axis_expansion"
    """
    gradient_magnitude = gradient_data["gradient_magnitude"]
    gradient_left_to_right = gradient_data.get("gradient_left_to_right")
    gradient_right_to_left = gradient_data.get("gradient_right_to_left")
    filter_orientation = gradient_data["filter_orientation"]

    h, w = gradient_magnitude.shape

    # Calculate realistic finger width range in pixels
    min_width_px = None
    max_width_px = None
    if scale_px_per_cm is not None:
        min_width_px = MIN_FINGER_WIDTH_CM * scale_px_per_cm
        max_width_px = MAX_FINGER_WIDTH_CM * scale_px_per_cm
        logger.debug(f"Width constraint: {min_width_px:.1f}-{max_width_px:.1f}px ({MIN_FINGER_WIDTH_CM}-{MAX_FINGER_WIDTH_CM}cm)")
    elif expected_width_px is not None:
        # Use expected width with tolerance
        min_width_px = expected_width_px * (1 - WIDTH_TOLERANCE_FACTOR)
        max_width_px = expected_width_px * (1 + WIDTH_TOLERANCE_FACTOR)
        logger.debug(f"Width constraint: {min_width_px:.1f}-{max_width_px:.1f}px (±{WIDTH_TOLERANCE_FACTOR*100}% of expected)")
    else:
        logger.debug("No width constraint (scale and expected width both None)")

    # Get axis information - this is our strong anchor point (INSIDE the finger)
    axis_center = roi_data.get("axis_center_in_roi")
    axis_direction = roi_data.get("axis_direction_in_roi")
    zone_start = roi_data.get("zone_start_in_roi")
    zone_end = roi_data.get("zone_end_in_roi")

    # Get finger mask for constrained edge detection (if available)
    roi_mask = roi_data.get("roi_mask")
    if mask_only and roi_mask is not None:
        mode_used = "mask_only"
    elif roi_mask is not None:
        mode_used = "mask_constrained"
    else:
        mode_used = "axis_expansion"

    if roi_mask is not None:
        logger.debug(f"Using MASK-CONSTRAINED edge detection (mask shape: {roi_mask.shape})")
    else:
        logger.debug("Using AXIS-EXPANSION edge detection (no mask available)")

    # For horizontal filter orientation (detecting left/right edges)
    # Process each row to find left and right edges
    if filter_orientation == "horizontal":
        num_rows = h
        left_edges = np.full(num_rows, -1.0, dtype=np.float32)
        right_edges = np.full(num_rows, -1.0, dtype=np.float32)
        edge_strengths_left = np.zeros(num_rows, dtype=np.float32)
        edge_strengths_right = np.zeros(num_rows, dtype=np.float32)
        valid_rows = np.zeros(num_rows, dtype=bool)

        for row in range(num_rows):
            # Get axis position (our anchor point INSIDE the finger)
            axis_x = _get_axis_x_at_row(row, axis_center, axis_direction, w)

            # Get gradient for this row
            row_gradient = gradient_magnitude[row, :]
            row_gradient_l2r = gradient_left_to_right[row, :] if gradient_left_to_right is not None else None
            row_gradient_r2l = gradient_right_to_left[row, :] if gradient_right_to_left is not None else None

            # Get mask for this row (if available)
            row_mask = roi_mask[row, :] if roi_mask is not None else None

            # Find edges using mask-constrained or axis-expansion method
            result = _find_edges_from_axis(row_gradient, row, axis_x, threshold,
                                          min_width_px, max_width_px, row_mask,
                                          row_gradient_left_to_right=row_gradient_l2r,
                                          row_gradient_right_to_left=row_gradient_r2l,
                                          mask_only=mask_only)

            if result is None:
                continue  # No valid edges found

            left_edge_x, right_edge_x, left_strength, right_strength = result

            # Mark as valid
            left_edges[row] = float(left_edge_x)
            right_edges[row] = float(right_edge_x)
            edge_strengths_left[row] = left_strength
            edge_strengths_right[row] = right_strength
            valid_rows[row] = True

    else:
        # Vertical filter orientation (detecting top/bottom edges)
        # Process each column
        num_cols = w
        left_edges = np.full(num_cols, -1.0, dtype=np.float32)
        right_edges = np.full(num_cols, -1.0, dtype=np.float32)
        edge_strengths_left = np.zeros(num_cols, dtype=np.float32)
        edge_strengths_right = np.zeros(num_cols, dtype=np.float32)
        valid_rows = np.zeros(num_cols, dtype=bool)

        roi_center_y = h / 2.0

        for col in range(num_cols):
            col_gradient = gradient_magnitude[:, col]

            strong_edges = np.where(col_gradient > threshold)[0]

            if len(strong_edges) < 2:
                continue

            top_candidates = strong_edges[strong_edges < roi_center_y]
            bottom_candidates = strong_edges[strong_edges >= roi_center_y]

            if len(top_candidates) == 0 or len(bottom_candidates) == 0:
                continue

            # Select edges closest to center (finger boundaries)
            top_edge_y = top_candidates[-1]  # Bottommost of top candidates
            bottom_edge_y = bottom_candidates[0]  # Topmost of bottom candidates

            top_strength = col_gradient[top_edge_y]
            bottom_strength = col_gradient[bottom_edge_y]

            height = bottom_edge_y - top_edge_y

            if expected_width_px is not None:
                if height < expected_width_px * 0.5 or height > expected_width_px * 1.5:
                    continue

            left_edges[col] = float(top_edge_y)
            right_edges[col] = float(bottom_edge_y)
            edge_strengths_left[col] = top_strength
            edge_strengths_right[col] = bottom_strength
            valid_rows[col] = True

    num_valid = np.sum(valid_rows)

    return {
        "left_edges": left_edges,
        "right_edges": right_edges,
        "edge_strengths_left": edge_strengths_left,
        "edge_strengths_right": edge_strengths_right,
        "valid_rows": valid_rows,
        "num_valid_rows": int(num_valid),
        "filter_orientation": filter_orientation,
        "mode_used": mode_used,  # "mask_constrained" or "axis_expansion"
    }


def refine_edge_subpixel(
    gradient_magnitude: np.ndarray,
    edge_positions: np.ndarray,
    valid_mask: np.ndarray,
    method: str = "parabola"
) -> np.ndarray:
    """
    Refine edge positions to sub-pixel precision.

    Uses parabola fitting on gradient magnitude to find peak position
    with <0.5 pixel accuracy.

    Args:
        gradient_magnitude: 2D gradient magnitude array
        edge_positions: Integer edge positions (one per row/col)
        valid_mask: Boolean mask indicating which positions are valid
        method: Refinement method ("parabola" or "gaussian")

    Returns:
        Refined edge positions (float, sub-pixel precision)
    """
    refined_positions = edge_positions.copy()

    if method == "parabola":
        # Parabola fitting: fit f(x) = ax^2 + bx + c to 3 points
        # Peak at x = -b/(2a)

        for i in range(len(edge_positions)):
            if not valid_mask[i]:
                continue

            edge_pos = int(edge_positions[i])

            # Get gradient magnitude at edge and neighbors
            # Handle edge cases (pun intended)
            if edge_pos <= 0 or edge_pos >= gradient_magnitude.shape[1] - 1:
                continue  # Can't refine at image boundaries

            # For horizontal orientation (row-wise edge detection)
            if len(gradient_magnitude.shape) == 2 and i < gradient_magnitude.shape[0]:
                # Sample gradient at x-1, x, x+1
                x_minus = edge_pos - 1
                x_center = edge_pos
                x_plus = edge_pos + 1

                g_minus = gradient_magnitude[i, x_minus]
                g_center = gradient_magnitude[i, x_center]
                g_plus = gradient_magnitude[i, x_plus]

                # Fit parabola: f(x) = ax^2 + bx + c
                # Using x = -1, 0, 1 for simplicity
                # f(-1) = a - b + c = g_minus
                # f(0) = c = g_center
                # f(1) = a + b + c = g_plus

                c = g_center
                a = (g_plus + g_minus - 2 * c) / 2.0
                b = (g_plus - g_minus) / 2.0

                # Peak at x_peak = -b/(2a)
                if abs(a) > MIN_PARABOLA_DENOMINATOR:  # Avoid division by zero
                    x_peak = -b / (2.0 * a)

                    # Constrain to reasonable range
                    if abs(x_peak) <= MAX_SUBPIXEL_OFFSET:
                        refined_positions[i] = edge_pos + x_peak

    elif method == "gaussian":
        # Gaussian fitting (more complex, not implemented yet)
        # Would fit Gaussian to 5-pixel window
        # For now, fall back to parabola
        return refine_edge_subpixel(gradient_magnitude, edge_positions, valid_mask, method="parabola")

    else:
        raise ValueError(f"Unknown refinement method: {method}")

    return refined_positions


def measure_width_from_edges(
    edge_data: Dict[str, Any],
    roi_data: Dict[str, Any],
    scale_px_per_cm: float,
    gradient_data: Optional[Dict[str, Any]] = None,
    use_subpixel: bool = True
) -> Dict[str, Any]:
    """
    Compute finger width from detected edges.

    Steps:
    1. Apply sub-pixel refinement if gradient data available
    2. Calculate width for each valid row: width_px = right_edge - left_edge
    3. Filter outliers (>3 MAD from median)
    4. Compute statistics (median, mean, std)
    5. Convert width from pixels to cm

    Args:
        edge_data: Output from detect_edges_per_row()
        roi_data: Output from extract_ring_zone_roi()
        scale_px_per_cm: Pixels per cm from card detection
        gradient_data: Optional gradient data for sub-pixel refinement
        use_subpixel: Enable sub-pixel refinement (default True)

    Returns:
        Dictionary containing:
        - widths_px: Array of width measurements (pixels)
        - median_width_px: Median width in pixels
        - median_width_cm: Median width in cm (final measurement)
        - mean_width_px: Mean width in pixels
        - std_width_px: Standard deviation of widths
        - num_samples: Number of valid width measurements
        - outliers_removed: Number of outliers filtered
        - subpixel_refinement_used: Whether sub-pixel refinement was applied
    """
    left_edges = edge_data["left_edges"].copy()
    right_edges = edge_data["right_edges"].copy()
    valid_rows = edge_data["valid_rows"]

    # Apply sub-pixel refinement if available
    subpixel_used = False
    if use_subpixel and gradient_data is not None:
        try:
            gradient_magnitude = gradient_data["gradient_magnitude"]

            # Refine left edges
            left_edges = refine_edge_subpixel(
                gradient_magnitude, left_edges, valid_rows, method="parabola"
            )

            # Refine right edges
            right_edges = refine_edge_subpixel(
                gradient_magnitude, right_edges, valid_rows, method="parabola"
            )

            subpixel_used = True
        except Exception as e:
            logger.warning(f"Sub-pixel refinement failed: {e}, using integer positions")
            # Fall back to integer positions
            left_edges = edge_data["left_edges"]
            right_edges = edge_data["right_edges"]

    # Calculate widths for valid rows
    widths_px = []
    for i in range(len(valid_rows)):
        if valid_rows[i]:
            width = right_edges[i] - left_edges[i]
            if width > 0:
                widths_px.append(width)

    if len(widths_px) == 0:
        raise ValueError("No valid width measurements found")

    widths_px = np.array(widths_px)

    # Filter outliers using median absolute deviation (MAD)
    median = np.median(widths_px)
    mad = np.median(np.abs(widths_px - median))

    # Outliers are >3 MAD from median (more robust than std dev)
    if mad > 0:
        is_outlier = np.abs(widths_px - median) > (MAD_OUTLIER_THRESHOLD * mad)
        widths_filtered = widths_px[~is_outlier]
        outliers_removed = np.sum(is_outlier)
    else:
        widths_filtered = widths_px
        outliers_removed = 0

    if len(widths_filtered) == 0:
        # All measurements were outliers, use original
        widths_filtered = widths_px
        outliers_removed = 0

    # Calculate statistics
    median_width_px = float(np.median(widths_filtered))
    mean_width_px = float(np.mean(widths_filtered))
    std_width_px = float(np.std(widths_filtered))

    # Convert to cm
    median_width_cm = median_width_px / scale_px_per_cm

    # Log measurements
    logger.debug(f"Raw median width: {median_width_px:.2f}px, scale: {scale_px_per_cm:.2f} px/cm → {median_width_cm:.4f}cm")
    logger.debug(f"Width range: {np.min(widths_filtered):.1f}-{np.max(widths_filtered):.1f}px, std: {std_width_px:.1f}px")

    return {
        "widths_px": widths_filtered.tolist(),
        "median_width_px": median_width_px,
        "median_width_cm": median_width_cm,
        "mean_width_px": mean_width_px,
        "std_width_px": std_width_px,
        "num_samples": len(widths_filtered),
        "outliers_removed": int(outliers_removed),
        "subpixel_refinement_used": subpixel_used,
    }


def compute_edge_quality_score(
    gradient_data: Dict[str, Any],
    edge_data: Dict[str, Any],
    width_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Assess quality of edge detection for confidence scoring.

    Computes 4 quality metrics:
    1. Gradient strength: Average gradient magnitude at detected edges
    2. Edge consistency: Percentage of rows with valid edge pairs
    3. Edge smoothness: Variance of edge positions along finger
    4. Bilateral symmetry: Correlation between left/right edge quality

    Args:
        gradient_data: Output from apply_sobel_filters()
        edge_data: Output from detect_edges_per_row()
        width_data: Output from measure_width_from_edges()

    Returns:
        Dictionary containing:
        - overall_score: Weighted average (0-1)
        - gradient_strength_score: Gradient strength metric (0-1)
        - consistency_score: Edge detection success rate (0-1)
        - smoothness_score: Edge position smoothness (0-1)
        - symmetry_score: Left/right balance (0-1)
        - metrics: Dict with raw metric values
    """
    gradient_magnitude = gradient_data["gradient_magnitude"]
    left_edges = edge_data["left_edges"]
    right_edges = edge_data["right_edges"]
    valid_rows = edge_data["valid_rows"]
    edge_strengths_left = edge_data["edge_strengths_left"]
    edge_strengths_right = edge_data["edge_strengths_right"]

    # Metric 1: Gradient Strength
    # Average gradient magnitude at detected edges, normalized
    valid_left_strengths = edge_strengths_left[valid_rows]
    valid_right_strengths = edge_strengths_right[valid_rows]

    if len(valid_left_strengths) > 0:
        avg_gradient_strength = (np.mean(valid_left_strengths) + np.mean(valid_right_strengths)) / 2.0
        # Normalize: typical strong edge is 20-50, weak is <10
        gradient_strength_score = min(avg_gradient_strength / GRADIENT_STRENGTH_NORMALIZER, 1.0)
    else:
        avg_gradient_strength = 0.0
        gradient_strength_score = 0.0

    # Metric 2: Edge Consistency
    # Percentage of rows with valid edge pairs
    total_rows = len(valid_rows)
    num_valid = np.sum(valid_rows)
    consistency_score = num_valid / total_rows if total_rows > 0 else 0.0

    # Metric 3: Edge Smoothness
    # Measure variance of edge positions (smoother = better)
    # Lower variance = higher score
    if num_valid > 1:
        # Calculate variance of left and right edges separately
        valid_left = left_edges[valid_rows]
        valid_right = right_edges[valid_rows]

        left_variance = np.var(valid_left)
        right_variance = np.var(valid_right)
        avg_variance = (left_variance + right_variance) / 2.0

        # Normalize: typical finger has variance <100, noisy edges >500
        smoothness_score = np.exp(-avg_variance / SMOOTHNESS_VARIANCE_NORMALIZER)
    else:
        avg_variance = 0.0
        smoothness_score = 0.0

    # Metric 4: Bilateral Symmetry
    # Correlation between left and right edge quality (strength balance)
    if len(valid_left_strengths) > 1:
        # Calculate ratio of average strengths
        avg_left = np.mean(valid_left_strengths)
        avg_right = np.mean(valid_right_strengths)

        if avg_left > 0 and avg_right > 0:
            # Symmetric ratio close to 1.0 is good
            ratio = min(avg_left, avg_right) / max(avg_left, avg_right)
            symmetry_score = ratio  # Already 0-1
        else:
            symmetry_score = 0.0
    else:
        symmetry_score = 0.0

    # Weighted overall score
    overall_score = (
        QUALITY_WEIGHT_GRADIENT * gradient_strength_score +
        QUALITY_WEIGHT_CONSISTENCY * consistency_score +
        QUALITY_WEIGHT_SMOOTHNESS * smoothness_score +
        QUALITY_WEIGHT_SYMMETRY * symmetry_score
    )

    return {
        "overall_score": float(overall_score),
        "gradient_strength_score": float(gradient_strength_score),
        "consistency_score": float(consistency_score),
        "smoothness_score": float(smoothness_score),
        "symmetry_score": float(symmetry_score),
        "metrics": {
            "avg_gradient_strength": float(avg_gradient_strength),
            "edge_consistency_pct": float(consistency_score * 100),
            "avg_variance": float(avg_variance) if num_valid > 1 else 0.0,
            "left_right_strength_ratio": float(symmetry_score),
        }
    }


def refine_edges_sobel(
    image: np.ndarray,
    axis_data: Dict[str, Any],
    zone_data: Dict[str, Any],
    scale_px_per_cm: float,
    finger_landmarks: Optional[np.ndarray] = None,
    sobel_threshold: float = DEFAULT_GRADIENT_THRESHOLD,
    kernel_size: int = DEFAULT_KERNEL_SIZE,
    rotate_align: bool = False,
    use_subpixel: bool = True,
    expected_width_px: Optional[float] = None,
    debug_dir: Optional[str] = None,
    finger_mask: Optional[np.ndarray] = None,
    mask_mode: str = "hybrid",
    finger_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main entry point for Sobel-based edge refinement.

    Replaces contour-based width measurement with gradient-based edge detection.

    Pipeline:
    1. Extract ROI around ring zone
    2. Apply bidirectional Sobel filters
    3. Detect left/right edges per row
    4. Measure width from edges
    5. Convert to cm and return measurement

    Args:
        image: Input BGR image
        axis_data: Output from estimate_finger_axis()
        zone_data: Output from localize_ring_zone()
        scale_px_per_cm: Pixels per cm from card detection
        finger_landmarks: Optional 4x2 array of finger landmarks for debug
        sobel_threshold: Minimum gradient magnitude for valid edge
        kernel_size: Sobel kernel size (3, 5, or 7)
        rotate_align: Rotate ROI for vertical finger alignment
        use_subpixel: Enable sub-pixel edge localization
        expected_width_px: Expected width for validation (optional)
        debug_dir: Directory to save debug visualizations (None to skip)

    Returns:
        Dictionary containing:
        - median_width_cm: Final measurement in cm
        - median_width_px: Measurement in pixels
        - std_width_px: Standard deviation
        - num_samples: Number of valid measurements
        - edge_detection_success_rate: % of rows with valid edges
        - roi_data: ROI extraction data
        - gradient_data: Sobel filter data
        - edge_data: Edge detection data
        - method: "sobel"
    """
    # Initialize debug observer if debug_dir provided
    if debug_dir:
        from src.debug_observer import DebugObserver, draw_landmark_axis, draw_ring_zone_roi
        from src.debug_observer import draw_roi_extraction, draw_gradient_visualization
        from src.debug_observer import draw_edge_candidates, draw_filtered_edge_candidates
        from src.debug_observer import draw_selected_edges
        from src.debug_observer import draw_width_measurements, draw_outlier_detection
        from src.debug_observer import draw_comprehensive_edge_overlay
        observer = DebugObserver(debug_dir)

    # Stage A: Axis & Zone Visualization
    if debug_dir:
        # A.1: Landmark axis
        observer.draw_and_save("01_landmark_axis", image, draw_landmark_axis, axis_data, finger_landmarks)

        # A.2: Ring zone + ROI bounds (need to extract bounds first)
        # We'll save this after ROI extraction

    # Step 1: Extract ROI. Pure-Sobel mode drops the SAM mask so the gradient
    # search expands from the finger axis without any mask anchoring; the
    # "mask_only" and legacy "hybrid" modes both pass the mask through.
    roi_finger_mask = None if mask_mode == "sobel_only" else finger_mask
    roi_data = extract_ring_zone_roi(
        image, axis_data, zone_data,
        rotate_align=rotate_align,
        finger_mask=roi_finger_mask,
        finger_name=finger_name,
    )

    logger.debug(f"ROI size: {roi_data['roi_width']}x{roi_data['roi_height']}px")
    logger.debug(f"ROI bounds: {roi_data['roi_bounds']}")

    if debug_dir:
        # A.2: Ring zone + ROI bounds
        roi_bounds = roi_data["roi_bounds"]
        observer.draw_and_save("02_ring_zone_roi", image, draw_ring_zone_roi, zone_data, roi_bounds)

        # A.3: ROI extraction
        observer.draw_and_save("03_roi_extraction", roi_data["roi_image"], draw_roi_extraction, roi_data.get("roi_mask"))

    # Step 2: Apply Sobel filters
    gradient_data = apply_sobel_filters(
        roi_data["roi_image"],
        kernel_size=kernel_size,
        axis_direction="auto"
    )

    if debug_dir:
        # Stage B: Sobel Filtering
        # B.1: Left-to-right gradient
        grad_left = draw_gradient_visualization(gradient_data["gradient_left_to_right"], cv2.COLORMAP_JET)
        observer.save_stage("04_sobel_left_to_right", grad_left)

        # B.2: Right-to-left gradient
        grad_right = draw_gradient_visualization(gradient_data["gradient_right_to_left"], cv2.COLORMAP_JET)
        observer.save_stage("05_sobel_right_to_left", grad_right)

        # B.3: Gradient magnitude
        grad_mag = draw_gradient_visualization(gradient_data["gradient_magnitude"], cv2.COLORMAP_HOT)
        observer.save_stage("06_gradient_magnitude", grad_mag)

    # Step 3: Detect edges per row. In "mask_only" mode the mask boundary is
    # used verbatim so gradient snapping is disabled.
    edge_data = detect_edges_per_row(
        gradient_data, roi_data,
        threshold=sobel_threshold,
        expected_width_px=expected_width_px,
        scale_px_per_cm=scale_px_per_cm,
        mask_only=(mask_mode == "mask_only"),
    )

    logger.debug(f"Valid rows: {edge_data['num_valid_rows']}/{len(edge_data['valid_rows'])} ({edge_data['num_valid_rows']/len(edge_data['valid_rows'])*100:.1f}%)")
    if edge_data['num_valid_rows'] > 0:
        valid_left = edge_data['left_edges'][edge_data['valid_rows']]
        valid_right = edge_data['right_edges'][edge_data['valid_rows']]
        logger.debug(f"Left edges range: {np.min(valid_left):.1f}-{np.max(valid_left):.1f}px")
        logger.debug(f"Right edges range: {np.min(valid_right):.1f}-{np.max(valid_right):.1f}px")
        widths = valid_right - valid_left
        logger.debug(f"Raw widths range: {np.min(widths):.1f}-{np.max(widths):.1f}px, median: {np.median(widths):.1f}px")

    if debug_dir:
        # B.4a: All edge candidates (raw threshold, shows noise)
        observer.draw_and_save("07a_all_candidates", roi_data["roi_image"],
                             draw_edge_candidates, gradient_data["gradient_magnitude"], sobel_threshold)

        # B.4b: Filtered edge candidates (spatially-filtered, what algorithm uses)
        observer.draw_and_save("07b_filtered_candidates", roi_data["roi_image"],
                             draw_filtered_edge_candidates,
                             gradient_data["gradient_magnitude"],
                             sobel_threshold,
                             roi_data.get("roi_mask"),
                             roi_data["axis_center_in_roi"],
                             roi_data["axis_direction_in_roi"])

        # B.5: Selected edges (final detected edges)
        observer.draw_and_save("09_selected_edges", roi_data["roi_image"], draw_selected_edges, edge_data)

    # Step 4: Measure width from edges (with sub-pixel refinement).
    # Sub-pixel refinement is gradient-based, so it is skipped in mask_only.
    effective_subpixel = use_subpixel and mask_mode != "mask_only"
    width_data = measure_width_from_edges(
        edge_data, roi_data, scale_px_per_cm,
        gradient_data=gradient_data,
        use_subpixel=effective_subpixel,
    )

    if debug_dir:
        # Stage C: Measurement
        # C.1: Sub-pixel refinement (use selected edges for now)
        observer.draw_and_save("10_subpixel_refinement", roi_data["roi_image"], draw_selected_edges, edge_data)

        # C.2: Width measurements
        observer.draw_and_save("11_width_measurements", roi_data["roi_image"],
                             draw_width_measurements, edge_data, width_data)

        # C.3: Width distribution (histogram - requires matplotlib)
        try:
            _save_width_distribution(width_data, debug_dir)
        except:
            pass  # Skip if matplotlib not available

        # C.4: Outlier detection
        observer.draw_and_save("13_outlier_detection", roi_data["roi_image"],
                             draw_outlier_detection, edge_data, width_data)

        # C.5: Comprehensive edge overlay on full image
        observer.draw_and_save("14_comprehensive_overlay", image,
                             draw_comprehensive_edge_overlay,
                             edge_data, roi_data["roi_bounds"], axis_data, zone_data,
                             width_data, scale_px_per_cm)

    # Step 5: Compute edge quality score
    edge_quality = compute_edge_quality_score(
        gradient_data, edge_data, width_data
    )

    # Calculate success rate
    total_rows = len(edge_data["valid_rows"])
    success_rate = edge_data["num_valid_rows"] / total_rows if total_rows > 0 else 0.0

    # Combine results
    return {
        "median_width_cm": width_data["median_width_cm"],
        "median_width_px": width_data["median_width_px"],
        "mean_width_px": width_data["mean_width_px"],
        "std_width_px": width_data["std_width_px"],
        "num_samples": width_data["num_samples"],
        "outliers_removed": width_data["outliers_removed"],
        "subpixel_refinement_used": width_data["subpixel_refinement_used"],
        "edge_detection_success_rate": success_rate,
        "edge_quality": edge_quality,
        "roi_data": roi_data,
        "gradient_data": gradient_data,
        "edge_data": edge_data,
        "width_data": width_data,
        "method": "sobel",
    }


def _save_width_distribution(width_data: Dict[str, Any], debug_dir: str) -> None:
    """Helper to save width distribution histogram."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import os
    except ImportError:
        return

    widths_px = width_data.get("widths_px", [])
    if len(widths_px) == 0:
        return

    median_width_px = width_data["median_width_px"]
    mean_width_px = width_data["mean_width_px"]

    # Create histogram
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(widths_px, bins=30, color='skyblue', edgecolor='black', alpha=0.7)
    ax.axvline(median_width_px, color='red', linestyle='--', linewidth=2, label=f'Median: {median_width_px:.1f} px')
    ax.axvline(mean_width_px, color='orange', linestyle='--', linewidth=2, label=f'Mean: {mean_width_px:.1f} px')

    ax.set_xlabel('Width (pixels)', fontsize=12)
    ax.set_ylabel('Frequency', fontsize=12)
    ax.set_title('Distribution of Cross-Section Widths', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    # Save
    output_path = os.path.join(debug_dir, "12_width_distribution.png")
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()


