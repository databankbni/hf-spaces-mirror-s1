"""
Geometric computation utilities.

This module handles:
- Finger axis estimation from MediaPipe landmarks
- Ring-wearing zone localization
- Coordinate transformations (precise rotation to canonical frame)
"""

import logging
import cv2
import numpy as np
from typing import Tuple, Optional, Dict, Any

from .geometry_constants import (
    MIN_LANDMARK_SPACING_PX,
    MIN_FINGER_LENGTH_PX,
    DEFAULT_ZONE_START_PCT,
    DEFAULT_ZONE_END_PCT,
    ANATOMICAL_ZONE_WIDTH_FACTOR,
)

logger = logging.getLogger(__name__)


def _validate_landmark_quality(landmarks: np.ndarray) -> Tuple[bool, str]:
    """
    Validate quality of finger landmarks for axis estimation.

    Args:
        landmarks: 4x2 array of finger landmarks [MCP, PIP, DIP, TIP]

    Returns:
        Tuple of (is_valid, reason)
    """
    if landmarks is None or len(landmarks) != 4:
        return False, "landmarks_missing_or_incomplete"

    # Check for NaN or infinite values
    if not np.all(np.isfinite(landmarks)):
        return False, "landmarks_contain_invalid_values"

    # Check reasonable spacing (landmarks not collapsed)
    # Calculate distances between consecutive landmarks
    distances = []
    for i in range(len(landmarks) - 1):
        dist = np.linalg.norm(landmarks[i + 1] - landmarks[i])
        distances.append(dist)

    # Check if any distance is too small (collapsed landmarks)
    min_distance = min(distances)
    if min_distance < MIN_LANDMARK_SPACING_PX:
        return False, "landmarks_too_close"

    # Check for monotonically increasing progression (no crossovers)
    # Calculate overall direction from MCP to TIP
    overall_direction = landmarks[3] - landmarks[0]
    overall_length = np.linalg.norm(overall_direction)

    if overall_length < MIN_FINGER_LENGTH_PX:
        return False, "finger_too_short"

    overall_direction = overall_direction / overall_length

    # Project each landmark onto overall direction
    # They should be monotonically increasing from MCP to TIP
    projections = []
    for i in range(len(landmarks)):
        proj = np.dot(landmarks[i] - landmarks[0], overall_direction)
        projections.append(proj)

    # Check monotonic increase
    for i in range(len(projections) - 1):
        if projections[i + 1] <= projections[i]:
            return False, "landmarks_not_monotonic"

    return True, "valid"


def estimate_finger_axis_from_landmarks(
    landmarks: np.ndarray,
    method: str = "linear_fit"
) -> Dict[str, Any]:
    """
    Calculate finger axis directly from anatomical landmarks.

    OPTIMIZED: Focuses on the PIP-MCP segment (proximal phalanx, where the
    ring actually sits) for better accuracy. For straight fingers (index,
    middle) this agrees with the DIP-PIP direction to within ~1°, but ring
    and pinky often hold a visible PIP-joint curl, so the proximal phalanx
    is at a different angle from the middle phalanx. Rotating by the
    proximal-phalanx direction makes the ring zone exactly vertical and
    cross-sections perpendicular to the bone we measure.

    Args:
        landmarks: 4x2 array of finger landmarks [MCP, PIP, DIP, TIP]
        method: Calculation method
            - "endpoints": MCP to TIP vector (legacy, less accurate)
            - "linear_fit": MCP to PIP vector (DEFAULT, proximal phalanx)
            - "median_direction": Median of 3 segment directions (robust to outliers)

    Returns:
        Dictionary containing:
        - center: Axis center point at midpoint of MCP-PIP (x, y)
        - direction: Unit direction vector (dx, dy) pointing palm→tip
        - length: Full finger length in pixels (TIP to MCP, for reference)
        - palm_end: Visualization endpoint (extended from MCP toward palm)
        - tip_end: Visualization endpoint (extended from PIP toward tip)
        - method: Method used ("landmarks")
    """
    # Validate landmarks
    is_valid, reason = _validate_landmark_quality(landmarks)
    if not is_valid:
        raise ValueError(f"Invalid landmarks for axis estimation: {reason}")

    # Extract landmark positions
    mcp = landmarks[0]  # Metacarpophalangeal joint (knuckle, palm-side)
    pip = landmarks[1]  # Proximal interphalangeal joint
    dip = landmarks[2]  # Distal interphalangeal joint
    tip = landmarks[3]  # Fingertip

    # Calculate direction based on method
    # OPTIMIZED: Focus on the PIP-MCP segment (proximal phalanx = ring zone)
    if method == "endpoints":
        # Simple: vector from MCP to TIP (legacy, less accurate for ring zone)
        direction = tip - mcp
        direction_length = np.linalg.norm(direction)
        direction = direction / direction_length

    elif method == "linear_fit":
        # OPTIMIZED: Use MCP→PIP, the proximal phalanx bone that a ring
        # actually rests on. For ring and pinky this differs from the old
        # DIP-PIP direction by the PIP-joint curl angle, which was
        # silently tilting the measurement frame.
        direction = pip - mcp  # Vector from MCP to PIP (palm→tip)
        direction_length = np.linalg.norm(direction)
        direction = direction / direction_length

        # Sanity check: direction should point palm→tip. (MCP→PIP already
        # does, but verify in case landmarks are swapped.)
        if np.dot(direction, tip - mcp) < 0:
            direction = -direction

    elif method == "median_direction":
        # Robust to outliers: median of segment directions
        # Calculate direction vectors for each segment
        seg1_dir = (pip - mcp) / np.linalg.norm(pip - mcp)
        seg2_dir = (dip - pip) / np.linalg.norm(dip - pip)
        seg3_dir = (tip - dip) / np.linalg.norm(tip - dip)

        # Take median of each component
        directions = np.array([seg1_dir, seg2_dir, seg3_dir])
        median_dir = np.median(directions, axis=0)
        direction = median_dir / np.linalg.norm(median_dir)

    else:
        raise ValueError(f"Unknown method: {method}. Use 'endpoints', 'linear_fit', or 'median_direction'")

    # OPTIMIZED: Center on the proximal phalanx midpoint (the ring zone).
    center = (mcp + pip) / 2.0

    # Calculate finger length (still use full finger for reference)
    length = np.linalg.norm(tip - mcp)

    # OPTIMIZED: Visual endpoints span the proximal phalanx (MCP→PIP)
    # extended slightly for visualization clarity.
    segment_length = np.linalg.norm(pip - mcp)
    extension_factor = 0.5  # Extend 50% beyond each endpoint for visualization
    palm_end = mcp - direction * (segment_length * extension_factor)
    tip_end = pip + direction * (segment_length * extension_factor)

    return {
        "center": center.astype(np.float32),
        "direction": direction.astype(np.float32),
        "length": float(length),
        "palm_end": palm_end.astype(np.float32),
        "tip_end": tip_end.astype(np.float32),
        "method": "landmarks",
    }


def estimate_finger_axis(
    landmarks: np.ndarray,
    landmark_method: str = "linear_fit",
) -> Dict[str, Any]:
    """Estimate the finger axis from MediaPipe finger landmarks.

    Raises ``ValueError`` via :func:`_validate_landmark_quality` when the
    landmarks are missing, non-finite, too close together, too short, or
    non-monotonic — callers should treat that as a measurement failure with
    ``fail_reason="axis_estimation_failed"``.
    """
    return estimate_finger_axis_from_landmarks(landmarks, method=landmark_method)


def localize_ring_zone(
    axis_data: Dict[str, Any],
    zone_start_pct: float = DEFAULT_ZONE_START_PCT,
    zone_end_pct: float = DEFAULT_ZONE_END_PCT,
) -> Dict[str, Any]:
    """
    Localize the ring-wearing zone along the finger axis.

    Args:
        axis_data: Output from estimate_finger_axis() containing center,
                   direction, length, palm_end, tip_end
        zone_start_pct: Zone start as percentage from palm (default 15%)
        zone_end_pct: Zone end as percentage from palm (default 25%)

    Returns:
        Dictionary containing:
        - start_point: Zone start position (x, y)
        - end_point: Zone end position (x, y)
        - center_point: Zone center position (x, y)
        - length: Zone length in pixels
        - start_pct: Start percentage used
        - end_pct: End percentage used
        - localization_method: "percentage"
    """
    # Extract axis information
    palm_end = axis_data["palm_end"]
    tip_end = axis_data["tip_end"]
    direction = axis_data["direction"]
    finger_length = axis_data["length"]

    # Calculate zone positions along the axis
    # Start at zone_start_pct from palm end
    start_distance = finger_length * zone_start_pct
    start_point = palm_end + direction * start_distance

    # End at zone_end_pct from palm end
    end_distance = finger_length * zone_end_pct
    end_point = palm_end + direction * end_distance

    # Calculate zone center
    center_point = (start_point + end_point) / 2.0

    # Zone length
    zone_length = end_distance - start_distance

    return {
        "start_point": start_point.astype(np.float32),
        "end_point": end_point.astype(np.float32),
        "center_point": center_point.astype(np.float32),
        "length": float(zone_length),
        "start_pct": zone_start_pct,
        "end_pct": zone_end_pct,
        "localization_method": "percentage",
    }


def localize_ring_zone_from_landmarks(
    landmarks: np.ndarray,
    axis_data: Dict[str, Any],
    zone_type: str = "percentage",
    zone_start_pct: float = DEFAULT_ZONE_START_PCT,
    zone_end_pct: float = DEFAULT_ZONE_END_PCT,
) -> Dict[str, Any]:
    """
    Localize ring-wearing zone using anatomical landmarks.

    v1 Enhancement: Provides anatomical-based ring zone localization
    as an alternative to percentage-based approach.

    Args:
        landmarks: 4x2 array of finger landmarks [MCP, PIP, DIP, TIP]
        axis_data: Output from estimate_finger_axis() containing center,
                   direction, length, palm_end, tip_end
        zone_type: Zone localization method
            - "percentage": 15-25% from palm (v0 compatible, default)
            - "anatomical": Centered on PIP joint with proportional width
        zone_start_pct: Zone start percentage (percentage mode only)
        zone_end_pct: Zone end percentage (percentage mode only)

    Returns:
        Dictionary containing:
        - start_point: Zone start position (x, y)
        - end_point: Zone end position (x, y)
        - center_point: Zone center position (x, y)
        - length: Zone length in pixels
        - localization_method: "percentage" or "anatomical"
    """
    if zone_type == "percentage":
        # Use percentage-based method (v0 compatible)
        result = localize_ring_zone(axis_data, zone_start_pct, zone_end_pct)
        return result

    elif zone_type == "anatomical":
        # Anatomical mode: Target the proximal phalanx (ring-wearing segment)
        # Upper bound: PIP joint (toward fingertip)
        # Lower bound: PIP - (DIP - PIP) = one segment length below PIP (toward palm)
        # This spans the proximal phalanx where rings are typically worn
        pip = landmarks[1]
        dip = landmarks[2]

        # Calculate segment length (DIP to PIP distance)
        segment_vector = dip - pip  # Vector from PIP to DIP

        # Ring zone spans from PIP down toward palm by one segment length
        # end_point is toward fingertip (PIP)
        # start_point is toward palm (PIP - segment_vector = one segment below PIP)
        end_point = pip.copy()  # Upper bound at PIP
        start_point = pip - segment_vector  # Lower bound one segment below PIP

        # Calculate zone center and length
        center_point = (start_point + end_point) / 2.0
        zone_length = np.linalg.norm(end_point - start_point)

        return {
            "start_point": start_point.astype(np.float32),
            "end_point": end_point.astype(np.float32),
            "center_point": center_point.astype(np.float32),
            "length": float(zone_length),
            "localization_method": "anatomical",
        }

    else:
        raise ValueError(f"Unknown zone_type: {zone_type}. Use 'percentage' or 'anatomical'")


# ============================================================================
# Precise Image Rotation for Finger Alignment
# ============================================================================

def calculate_angle_from_vertical(direction: np.ndarray) -> float:
    """
    Calculate the rotation needed to align a direction vector to vertical (upward).

    In image coordinates, vertical upward is (0, -1) in (x, y) format.

    Args:
        direction: Unit direction vector (dx, dy) in (x, y) format

    Returns:
        Rotation angle in degrees to apply to align direction to vertical.
        Positive = need to rotate counter-clockwise (CCW) in image coordinates.
        Range: [-180, 180]
    """
    # Vertical upward in image coordinates: (0, -1)
    vertical = np.array([0.0, -1.0])

    # Calculate angle using atan2(cross_product, dot_product)
    # cross = dx * (-1) - dy * 0 = -dx
    # dot = dx * 0 + dy * (-1) = -dy
    cross = direction[0] * vertical[1] - direction[1] * vertical[0]
    dot = np.dot(direction, vertical)

    angle_rad = np.arctan2(cross, dot)
    angle_deg = np.degrees(angle_rad)

    # Negate the angle: if finger is tilted +10° CW from vertical,
    # we need to rotate -10° (CCW) to straighten it
    return -angle_deg


def rotate_image_precise(
    image: np.ndarray,
    angle_degrees: float,
    center: Optional[Tuple[float, float]] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Rotate image by a precise angle around a center point.

    Args:
        image: Input image (grayscale or BGR)
        angle_degrees: Rotation angle in degrees (positive = clockwise)
        center: Rotation center (x, y). If None, uses image center.

    Returns:
        Tuple of:
        - rotated_image: Rotated image (same size as input)
        - rotation_matrix: 2x3 affine transformation matrix
    """
    h, w = image.shape[:2]

    if center is None:
        center = (w / 2.0, h / 2.0)

    # Get rotation matrix (OpenCV uses clockwise positive)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle_degrees, scale=1.0)

    # Apply rotation
    rotated = cv2.warpAffine(
        image, rotation_matrix, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0
    )

    return rotated, rotation_matrix


def transform_points_rotation(
    points: np.ndarray,
    rotation_matrix: np.ndarray
) -> np.ndarray:
    """
    Transform points using a rotation matrix from cv2.getRotationMatrix2D.

    Args:
        points: Nx2 array of points in (x, y) format
        rotation_matrix: 2x3 affine transformation matrix from cv2.getRotationMatrix2D

    Returns:
        Nx2 array of transformed points in (x, y) format
    """
    # Add homogeneous coordinate (1) to each point: (x, y) -> (x, y, 1)
    n_points = points.shape[0]
    homogeneous = np.hstack([points, np.ones((n_points, 1))])

    # Apply transformation: [2x3] @ [3xN]^T -> [2xN]^T
    transformed = (rotation_matrix @ homogeneous.T).T

    return transformed.astype(np.float32)


def rotate_axis_data(
    axis_data: Dict[str, Any],
    rotation_matrix: np.ndarray
) -> Dict[str, Any]:
    """
    Update axis data after image rotation.

    Args:
        axis_data: Axis data dictionary with center, direction, palm_end, tip_end
        rotation_matrix: 2x3 rotation matrix

    Returns:
        Updated axis data with transformed coordinates
    """
    rotated = axis_data.copy()

    # Transform center point
    center = axis_data["center"].reshape(1, 2)
    rotated["center"] = transform_points_rotation(center, rotation_matrix)[0]

    # Transform direction vector (rotation only, no translation)
    # For direction vectors, we only apply the rotation part (2x2)
    rotation_only = rotation_matrix[:2, :2]
    direction = axis_data["direction"].reshape(2, 1)
    rotated_direction = (rotation_only @ direction).flatten()
    rotated["direction"] = rotated_direction / np.linalg.norm(rotated_direction)

    # Transform endpoints if they exist
    if "palm_end" in axis_data:
        palm_end = axis_data["palm_end"].reshape(1, 2)
        rotated["palm_end"] = transform_points_rotation(palm_end, rotation_matrix)[0]

    if "tip_end" in axis_data:
        tip_end = axis_data["tip_end"].reshape(1, 2)
        rotated["tip_end"] = transform_points_rotation(tip_end, rotation_matrix)[0]

    return rotated


def rotate_contour(
    contour: np.ndarray,
    rotation_matrix: np.ndarray
) -> np.ndarray:
    """
    Rotate a contour using rotation matrix.

    Args:
        contour: Nx2 array of contour points in (x, y) format
        rotation_matrix: 2x3 rotation matrix

    Returns:
        Rotated contour in same format
    """
    return transform_points_rotation(contour, rotation_matrix)
