"""
Hand and finger segmentation utilities.

This module handles:
- Hand detection using MediaPipe
- Hand mask generation
- Individual finger isolation
- Mask cleanup and validation
"""

import logging

import cv2
import numpy as np
from typing import Optional, Dict, Any, Literal, List, Tuple
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import urllib.request
import os
from pathlib import Path

# Import debug observer and drawing functions
from src.debug_observer import (
    DebugObserver,
    draw_landmarks_overlay,
    draw_hand_skeleton,
    draw_detection_info,
)

logger = logging.getLogger(__name__)

FingerIndex = Literal["auto", "index", "middle", "ring", "pinky"]

# MediaPipe hand landmark indices for each finger
# Each finger has 4 landmarks: MCP (knuckle), PIP, DIP, TIP
FINGER_LANDMARKS = {
    "index": [5, 6, 7, 8],
    "middle": [9, 10, 11, 12],
    "ring": [13, 14, 15, 16],
    "pinky": [17, 18, 19, 20],
}

# Thumb landmarks (special case - not typically used for ring measurement)
THUMB_LANDMARKS = [1, 2, 3, 4]

# Wrist landmark
WRIST_LANDMARK = 0

# Palm landmarks (for creating hand mask)
PALM_LANDMARKS = [0, 1, 5, 9, 13, 17]

# Model path
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", ".model", "hand_landmarker.task")
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

# Initialize MediaPipe Hands (lazy loading)
_hands_detector = None


def _download_model():
    """Download the hand landmarker model if not present."""
    if not os.path.exists(MODEL_PATH):
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        logger.info("downloading MediaPipe hand landmarker model...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        logger.info("MediaPipe model downloaded to %s", MODEL_PATH)


def _get_hands_detector(force_new: bool = False):
    """Get or initialize the MediaPipe Hands detector."""
    global _hands_detector
    if _hands_detector is None or force_new:
        _download_model()
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            min_hand_detection_confidence=0.3,  # Lower threshold for better detection
            min_tracking_confidence=0.3,
        )
        _hands_detector = vision.HandLandmarker.create_from_options(options)
    return _hands_detector


def _try_detect_hand(detector, image: np.ndarray) -> Optional[Tuple[Any, int]]:
    """
    Try to detect hand in image, returns (results, rotation_code) or None.
    rotation_code: 0=none, 1=90cw, 2=180, 3=90ccw
    """
    # Try different rotations to handle various image orientations
    rotations = [
        (image, 0),
        (cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE), 1),
        (cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE), 3),
        (cv2.rotate(image, cv2.ROTATE_180), 2),
    ]

    best_result = None
    best_confidence = 0
    best_rotation = 0

    for rotated, rot_code in rotations:
        # Convert to RGB and ensure contiguous memory layout
        rgb = cv2.cvtColor(rotated, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        results = detector.detect(mp_image)

        if results.hand_landmarks:
            # Get best confidence among detected hands
            for i, handedness in enumerate(results.handedness):
                conf = handedness[0].score
                if conf > best_confidence:
                    best_confidence = conf
                    best_result = results
                    best_rotation = rot_code

    if best_result is None:
        return None

    return best_result, best_rotation


def _transform_landmarks_for_rotation(
    landmarks: np.ndarray,
    rotation_code: int,
    original_h: int,
    original_w: int,
) -> np.ndarray:
    """
    Transform landmarks from rotated coordinates back to original image coordinates.
    """
    if rotation_code == 0:
        # No rotation
        return landmarks
    elif rotation_code == 1:
        # Was rotated 90 CW, so transform back (90 CCW)
        # In rotated: (x, y) with size (h, w) -> original: (y, w-1-x) with size (w, h)
        new_landmarks = np.zeros_like(landmarks)
        new_landmarks[:, 0] = landmarks[:, 1] * original_w  # y -> x
        new_landmarks[:, 1] = (1 - landmarks[:, 0]) * original_h  # (1-x) -> y
        return new_landmarks
    elif rotation_code == 2:
        # Was rotated 180
        new_landmarks = np.zeros_like(landmarks)
        new_landmarks[:, 0] = (1 - landmarks[:, 0]) * original_w
        new_landmarks[:, 1] = (1 - landmarks[:, 1]) * original_h
        return new_landmarks
    elif rotation_code == 3:
        # Was rotated 90 CCW, so transform back (90 CW)
        new_landmarks = np.zeros_like(landmarks)
        new_landmarks[:, 0] = (1 - landmarks[:, 1]) * original_w
        new_landmarks[:, 1] = landmarks[:, 0] * original_h
        return new_landmarks

    return landmarks


def detect_hand_orientation(
    landmarks_normalized: np.ndarray,
    finger: FingerIndex = "index"
) -> float:
    """
    Detect hand orientation angle from vertical (canonical orientation).
    
    Canonical orientation: wrist at bottom, fingers pointing upward.
    
    Uses the centroid of index, middle, and ring fingertips for robust
    orientation detection, regardless of which finger is being measured.
    Individual fingers (especially index/pinky) can lean away from the
    hand's central axis, causing borderline rotation errors.
    
    Args:
        landmarks_normalized: MediaPipe hand landmarks (21x2) in normalized [0-1] coordinates
        finger: Which finger is being measured (kept for API compat, not used for orientation)
    
    Returns:
        Angle in degrees to rotate image clockwise to achieve canonical orientation.
        Returns one of: 0, 90, 180, 270
    """
    wrist = landmarks_normalized[WRIST_LANDMARK]
    
    # Use centroid of index, middle, ring fingertips for robust orientation
    fingertip_indices = [
        FINGER_LANDMARKS["index"][3],   # 8
        FINGER_LANDMARKS["middle"][3],  # 12
        FINGER_LANDMARKS["ring"][3],    # 16
    ]
    fingertip_center = np.mean(landmarks_normalized[fingertip_indices], axis=0)
    
    # Compute vector from wrist to fingertip centroid
    direction = fingertip_center - wrist
    
    # Compute angle from vertical upward direction
    # In image coordinates: y increases downward, x increases rightward
    # Vertical upward = (0, -1) in (x, y)
    # angle = atan2(cross, dot) where cross = dx*(-1) - dy*0, dot = dx*0 + dy*(-1)
    angle_rad = np.arctan2(direction[0], -direction[1])
    angle_deg = angle_rad * 180.0 / np.pi
    
    # angle_deg is now in range [-180, 180]:
    # 0° = fingers pointing up (canonical)
    # 90° = fingers pointing right
    # 180° = fingers pointing down
    # -90° = fingers pointing left
    
    # Convert to [0, 360] range
    if angle_deg < 0:
        angle_deg += 360
    
    # Snap to nearest 90° increment
    # We want to return how much to rotate CW to get to canonical (0°)
    rotation_needed = _snap_to_orthogonal(angle_deg)
    
    return rotation_needed


def _snap_to_orthogonal(angle_deg: float) -> int:
    """
    Snap angle to nearest orthogonal rotation (0, 90, 180, 270).
    
    Args:
        angle_deg: Angle in degrees [0, 360]
    
    Returns:
        Rotation needed in degrees (0, 90, 180, 270) to rotate CW to canonical orientation
    """
    # If angle is 0±45°, no rotation needed
    # If angle is 90±45°, need to rotate 270° CW (or 90° CCW) to get to 0°
    # If angle is 180±45°, need to rotate 180°
    # If angle is 270±45°, need to rotate 90° CW
    
    # Determine which quadrant (with 45° tolerance)
    if angle_deg < 45 or angle_deg >= 315:
        return 0  # Already upright
    elif 45 <= angle_deg < 135:
        return 270  # Pointing right, rotate 270° CW (= 90° CCW)
    elif 135 <= angle_deg < 225:
        return 180  # Upside down, rotate 180°
    else:  # 225 <= angle_deg < 315
        return 90   # Pointing left, rotate 90° CW


def normalize_hand_orientation(
    image: np.ndarray,
    landmarks_normalized: np.ndarray,
    finger: FingerIndex = "index",
) -> Tuple[np.ndarray, int]:
    """
    Rotate image to canonical hand orientation (wrist at bottom, fingers up).
    
    Args:
        image: Input BGR image
        landmarks_normalized: MediaPipe landmarks in normalized [0-1] coordinates
        finger: Which finger to use for orientation detection (default: "index")
    
    Returns:
        Tuple of (rotated_image, rotation_angle_degrees)
        rotation_angle_degrees is one of: 0, 90, 180, 270
    """
    # Detect hand orientation based on specified finger
    rotation_needed = detect_hand_orientation(landmarks_normalized, finger)

    # Rotate image if needed
    if rotation_needed == 0:
        return image, 0
    elif rotation_needed == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE), 90
    elif rotation_needed == 180:
        return cv2.rotate(image, cv2.ROTATE_180), 180
    elif rotation_needed == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE), 270
    else:
        # Shouldn't happen, but return original as fallback
        logger.warning("unexpected rotation angle %s, skipping rotation", rotation_needed)
        return image, 0


def segment_hand(
    image: np.ndarray,
    finger: FingerIndex = "index",
    max_dimension: int = 1280,
    debug_dir: Optional[str] = None,
    use_sam_mask: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Detect and segment hand from image using MediaPipe.

    Args:
        image: Input BGR image
        finger: Which finger to use for orientation detection (default: "index")
        max_dimension: Maximum dimension for processing (large images are resized)
        debug_dir: Optional directory to save debug images

    Returns:
        Dictionary containing:
        - landmarks: 21x2 array of landmark positions (pixel coordinates)
        - landmarks_normalized: 21x2 array of normalized coordinates [0-1]
        - mask: Binary hand mask (pixel-accurate SAM 2.1 mask if use_sam_mask=True,
          else synthetic convex-hull fallback from landmarks)
        - mask_synthetic: Synthetic fallback mask (always populated for debug)
        - confidence: Detection confidence
        - handedness: "Left" or "Right"
        Or None if no hand detected

    Args:
        use_sam_mask: If True (default), call SAM 2.1 seeded by the palm-center
            landmark to produce a pixel-accurate hand mask. If False, use the
            legacy synthetic convex-hull mask built from landmarks only.
    """
    # Create debug observer if debug mode enabled
    observer = DebugObserver(debug_dir) if debug_dir else None
    
    h, w = image.shape[:2]

    # Debug: Save original image
    if observer:
        observer.save_stage("01_original", image)

    # Resize if image is too large (MediaPipe works better with smaller images)
    scale = 1.0
    if max(h, w) > max_dimension:
        scale = max_dimension / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        resized = image
        new_h, new_w = h, w

    # Debug: Save resized image (if resized)
    if scale != 1.0 and observer:
        observer.save_stage("02_resized_for_detection", resized)

    # Process with MediaPipe (try multiple rotations)
    detector = _get_hands_detector()
    detection_result = _try_detect_hand(detector, resized)

    if detection_result is None:
        return None

    results, rotation_code = detection_result

    # Select the best hand (highest confidence)
    best_hand_idx = 0
    best_conf = 0
    for i, handedness in enumerate(results.handedness):
        if handedness[0].score > best_conf:
            best_conf = handedness[0].score
            best_hand_idx = i

    hand_landmarks = results.hand_landmarks[best_hand_idx]
    handedness = results.handedness[best_hand_idx]

    # Extract landmark coordinates (normalized 0-1 in rotated image)
    landmarks_normalized_rotated = np.array([
        [lm.x, lm.y] for lm in hand_landmarks
    ])

    # NEW: Normalize hand orientation to canonical (wrist at bottom, fingers up)
    # This is done in the detected-rotation space first
    if rotation_code == 1:
        # Was rotated 90 CW
        rotated_image = cv2.rotate(resized, cv2.ROTATE_90_CLOCKWISE)
    elif rotation_code == 2:
        # Was rotated 180
        rotated_image = cv2.rotate(resized, cv2.ROTATE_180)
    elif rotation_code == 3:
        # Was rotated 90 CCW
        rotated_image = cv2.rotate(resized, cv2.ROTATE_90_COUNTERCLOCKWISE)
    else:
        rotated_image = resized
    
    # Now normalize orientation based on hand direction
    canonical_image, orientation_rotation = normalize_hand_orientation(
        rotated_image, landmarks_normalized_rotated, finger
    )
    
    # Update landmarks for orientation normalization
    if orientation_rotation != 0:
        rot_h, rot_w = rotated_image.shape[:2]
        landmarks_px_rotated = landmarks_normalized_rotated.copy()
        landmarks_px_rotated[:, 0] *= rot_w
        landmarks_px_rotated[:, 1] *= rot_h
        
        # Apply rotation transform to landmarks
        if orientation_rotation == 90:
            # Rotate 90 CW: (x, y) -> (h-1-y, x)
            new_landmarks = np.zeros_like(landmarks_px_rotated)
            new_landmarks[:, 0] = rot_h - 1 - landmarks_px_rotated[:, 1]
            new_landmarks[:, 1] = landmarks_px_rotated[:, 0]
            landmarks_px_canonical = new_landmarks
        elif orientation_rotation == 180:
            # Rotate 180: (x, y) -> (w-1-x, h-1-y)
            new_landmarks = np.zeros_like(landmarks_px_rotated)
            new_landmarks[:, 0] = rot_w - 1 - landmarks_px_rotated[:, 0]
            new_landmarks[:, 1] = rot_h - 1 - landmarks_px_rotated[:, 1]
            landmarks_px_canonical = new_landmarks
        elif orientation_rotation == 270:
            # Rotate 90 CCW: (x, y) -> (y, w-1-x)
            new_landmarks = np.zeros_like(landmarks_px_rotated)
            new_landmarks[:, 0] = landmarks_px_rotated[:, 1]
            new_landmarks[:, 1] = rot_w - 1 - landmarks_px_rotated[:, 0]
            landmarks_px_canonical = new_landmarks
        else:
            landmarks_px_canonical = landmarks_px_rotated
        
        # Update normalized landmarks for canonical image
        can_h, can_w = canonical_image.shape[:2]
        landmarks_normalized_canonical = landmarks_px_canonical.copy()
        landmarks_normalized_canonical[:, 0] /= can_w
        landmarks_normalized_canonical[:, 1] /= can_h
    else:
        landmarks_normalized_canonical = landmarks_normalized_rotated
    
    # Scale landmarks back to original resolution if needed
    if scale != 1.0:
        canonical_full = cv2.resize(canonical_image, (int(canonical_image.shape[1] / scale), 
                                                      int(canonical_image.shape[0] / scale)),
                                   interpolation=cv2.INTER_CUBIC)
    else:
        canonical_full = canonical_image
    
    # Final landmarks in canonical full resolution
    can_full_h, can_full_w = canonical_full.shape[:2]
    landmarks_canonical = landmarks_normalized_canonical.copy()
    landmarks_canonical[:, 0] *= can_full_w
    landmarks_canonical[:, 1] *= can_full_h

    # Debug: Draw landmarks overlay in canonical orientation
    if observer:
        observer.draw_and_save("03_landmarks_overlay_canonical", canonical_full,
                             draw_landmarks_overlay, landmarks_canonical, label=True)
        observer.draw_and_save("04_hand_skeleton_canonical", canonical_full,
                             draw_hand_skeleton, landmarks_canonical)
        observer.draw_and_save("05_detection_info_canonical", canonical_full,
                             draw_detection_info, handedness[0].score,
                             handedness[0].category_name, 
                             f"det={rotation_code}, orient={orientation_rotation}")

    # Legacy synthetic mask (convex hull of landmarks) — kept for fallback and debug
    synthetic_mask = _create_hand_mask(landmarks_canonical, (can_full_h, can_full_w))

    # SAM 2.1 pixel-accurate hand mask (default), seeded by palm center landmark
    mask = synthetic_mask
    mask_source = "synthetic"
    if use_sam_mask:
        try:
            from .sam_hand_segmentation import segment_hand_sam, palm_center_from_landmarks
            palm_xy = palm_center_from_landmarks(landmarks_canonical)
            sam_debug_dir = str(Path(debug_dir) / "sam_hand") if debug_dir else None
            sam_mask_bool = segment_hand_sam(
                canonical_full, palm_xy, debug_dir=sam_debug_dir
            )
            if sam_mask_bool is not None:
                mask = (sam_mask_bool.astype(np.uint8) * 255)
                mask_source = "sam"
            else:
                logger.warning("SAM hand mask returned None, falling back to synthetic")
        except Exception as e:
            logger.warning("SAM hand mask failed (%r), falling back to synthetic", e)

    return {
        "landmarks": landmarks_canonical,
        "landmarks_normalized": landmarks_normalized_canonical,
        "mask": mask,
        "mask_synthetic": synthetic_mask,
        "mask_source": mask_source,
        "confidence": handedness[0].score,
        "handedness": handedness[0].category_name,
        "rotation_applied": rotation_code,
        "orientation_rotation": orientation_rotation,
        "canonical_image": canonical_full,  # Return the canonical image for downstream processing
    }


def _create_hand_mask(landmarks: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    """
    Create a binary mask of the hand region from landmarks.

    Args:
        landmarks: 21x2 array of landmark pixel coordinates
        shape: (height, width) of output mask

    Returns:
        Binary mask (uint8, 0 or 255)
    """
    h, w = shape
    mask = np.zeros((h, w), dtype=np.uint8)

    # Create convex hull of all landmarks
    hull_points = cv2.convexHull(landmarks.astype(np.int32))
    cv2.fillConvexPoly(mask, hull_points, 255)

    # Also fill individual finger regions for better coverage
    for finger_name, indices in FINGER_LANDMARKS.items():
        finger_pts = landmarks[indices].astype(np.int32)
        cv2.fillConvexPoly(mask, finger_pts, 255)

    # Fill thumb
    thumb_pts = landmarks[THUMB_LANDMARKS].astype(np.int32)
    cv2.fillConvexPoly(mask, thumb_pts, 255)

    # Apply morphological operations to smooth the mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    return mask


def _calculate_finger_extension(landmarks: np.ndarray, finger_indices: List[int]) -> float:
    """
    Calculate how extended a finger is based on landmark positions.

    Returns a score where higher = more extended.
    """
    if len(finger_indices) < 4:
        return 0.0

    # Get finger landmarks
    mcp = landmarks[finger_indices[0]]  # Knuckle
    pip = landmarks[finger_indices[1]]  # First joint
    dip = landmarks[finger_indices[2]]  # Second joint
    tip = landmarks[finger_indices[3]]  # Fingertip

    # Calculate vectors
    mcp_to_tip = tip - mcp
    mcp_to_pip = pip - mcp

    # Extension score based on:
    # 1. Distance from knuckle to tip (longer = more extended)
    finger_length = np.linalg.norm(mcp_to_tip)

    # 2. Straightness (how aligned are the joints)
    pip_to_dip = dip - pip
    dip_to_tip = tip - dip

    # Dot products to check alignment (1 = straight, -1 = bent back)
    if np.linalg.norm(mcp_to_pip) > 0 and np.linalg.norm(pip_to_dip) > 0:
        align1 = np.dot(mcp_to_pip, pip_to_dip) / (np.linalg.norm(mcp_to_pip) * np.linalg.norm(pip_to_dip))
    else:
        align1 = 0

    if np.linalg.norm(pip_to_dip) > 0 and np.linalg.norm(dip_to_tip) > 0:
        align2 = np.dot(pip_to_dip, dip_to_tip) / (np.linalg.norm(pip_to_dip) * np.linalg.norm(dip_to_tip))
    else:
        align2 = 0

    straightness = (align1 + align2) / 2

    # Combined score
    return finger_length * (0.5 + 0.5 * max(0, straightness))


def _create_finger_roi_mask(
    finger_landmarks: np.ndarray,
    all_landmarks: np.ndarray,
    shape: Tuple[int, int],
    expansion_factor: float = 1.8,
) -> np.ndarray:
    """
    Create a Region of Interest (ROI) mask around finger landmarks.

    This creates a generous bounding region that should contain the entire finger
    without cutting off edges, but excludes other fingers.

    Args:
        finger_landmarks: 4x2 array of finger landmark positions (MCP, PIP, DIP, TIP)
        all_landmarks: 21x2 array of all hand landmarks
        shape: (height, width) of output mask
        expansion_factor: How much to expand perpendicular to finger axis

    Returns:
        Binary ROI mask
    """
    h, w = shape
    roi_mask = np.zeros((h, w), dtype=np.uint8)

    # Calculate finger axis direction
    mcp = finger_landmarks[0]
    tip = finger_landmarks[3]
    finger_axis = tip - mcp
    finger_length = np.linalg.norm(finger_axis)

    if finger_length < 1:
        return roi_mask

    finger_direction = finger_axis / finger_length

    # Perpendicular direction
    perp = np.array([-finger_direction[1], finger_direction[0]])

    # Estimate finger width from landmark spacing
    # Use median distance between consecutive landmarks as width proxy
    segment_lengths = []
    for i in range(len(finger_landmarks) - 1):
        seg_len = np.linalg.norm(finger_landmarks[i + 1] - finger_landmarks[i])
        segment_lengths.append(seg_len)
    avg_segment = np.median(segment_lengths) if segment_lengths else finger_length / 3

    # Finger width is roughly 1/3 to 1/2 of segment length
    base_width = avg_segment * 0.6 * expansion_factor

    # Extend ROI slightly beyond landmarks (towards palm and beyond tip)
    wrist = all_landmarks[WRIST_LANDMARK]
    palm_direction = mcp - wrist
    palm_direction = palm_direction / (np.linalg.norm(palm_direction) + 1e-8)

    # Extend 20% beyond MCP toward palm
    extended_base = mcp - palm_direction * finger_length * 0.2
    # Extend 10% beyond tip
    extended_tip = tip + finger_direction * finger_length * 0.1

    # Create polygon along finger with wider margins
    polygon_points = []
    num_samples = 8  # More points for smoother ROI

    for i in range(num_samples):
        t = i / (num_samples - 1)
        # Interpolate from extended base to extended tip
        pt = extended_base + (extended_tip - extended_base) * t

        # Width varies: wider at base, narrower at tip
        width_scale = 1.0 - 0.2 * t
        half_width = base_width * width_scale / 2

        # Add left and right points
        left = pt + perp * half_width
        right = pt - perp * half_width
        polygon_points.append((left, right))

    # Build polygon
    polygon = []
    for left, right in polygon_points:
        polygon.append(left)
    for left, right in reversed(polygon_points):
        polygon.append(right)

    polygon = np.array(polygon, dtype=np.int32)
    cv2.fillPoly(roi_mask, [polygon], 255)

    return roi_mask


def _isolate_finger_from_hand_mask(
    hand_mask: np.ndarray,
    finger_landmarks: np.ndarray,
    all_landmarks: np.ndarray,
    min_area: int = 500,
) -> Optional[np.ndarray]:
    """
    Isolate finger using pixel-level intersection of hand mask with finger ROI.

    This is the preferred method as it preserves actual finger edges from MediaPipe
    rather than creating a synthetic polygon.

    Args:
        hand_mask: Full hand mask from MediaPipe (pixel-accurate)
        finger_landmarks: 4x2 array of finger landmarks
        all_landmarks: 21x2 array of all hand landmarks
        min_area: Minimum valid finger area

    Returns:
        Binary finger mask, or None if isolation fails
    """
    h, w = hand_mask.shape

    # Create ROI mask around finger
    roi_mask = _create_finger_roi_mask(finger_landmarks, all_landmarks, (h, w))

    # Intersect hand mask with finger ROI
    # This preserves real pixel-level edges from MediaPipe
    finger_mask = cv2.bitwise_and(hand_mask, roi_mask)

    # Find connected components to remove fragments from other fingers
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        finger_mask, connectivity=8
    )

    if num_labels <= 1:
        return None

    # Select component closest to finger landmarks centroid
    landmarks_centroid = np.mean(finger_landmarks, axis=0)

    best_component = None
    best_distance = float('inf')

    for i in range(1, num_labels):  # Skip background (0)
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area:
            continue

        component_centroid = centroids[i]
        dist = np.linalg.norm(component_centroid - landmarks_centroid)

        if dist < best_distance:
            best_distance = dist
            best_component = i

    if best_component is None:
        return None

    # Create final mask with only the selected component
    final_mask = np.zeros_like(finger_mask)
    final_mask[labels == best_component] = 255

    return final_mask


def isolate_finger(
    hand_data: Dict[str, Any],
    finger: FingerIndex = "auto",
    image_shape: Optional[Tuple[int, int]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Isolate a specific finger from hand segmentation data.

    Args:
        hand_data: Output from segment_hand()
        finger: Which finger to isolate, or "auto" to select most extended
        image_shape: (height, width) for mask generation

    Returns:
        Dictionary containing:
        - mask: Binary finger mask
        - landmarks: Finger landmark positions (4x2 array)
        - base_point: Palm-side base of finger (MCP joint)
        - tip_point: Fingertip position
        - finger_name: Name of the isolated finger
        Or None if finger cannot be isolated
    """
    landmarks = hand_data["landmarks"]

    if image_shape is None:
        if "mask" in hand_data:
            image_shape = hand_data["mask"].shape[:2]
        else:
            return None

    # Determine which finger to use
    if finger == "auto":
        best_finger = None
        best_score = -1

        for finger_name, indices in FINGER_LANDMARKS.items():
            score = _calculate_finger_extension(landmarks, indices)
            if score > best_score:
                best_score = score
                best_finger = finger_name

        if best_finger is None:
            return None
        finger = best_finger

    if finger not in FINGER_LANDMARKS:
        return None

    indices = FINGER_LANDMARKS[finger]
    finger_landmarks = landmarks[indices]

    # Create finger mask using pixel-level approach (preferred)
    mask = None
    method_used = "unknown"

    if "mask" in hand_data and hand_data["mask"] is not None:
        mask = _isolate_finger_from_hand_mask(
            hand_data["mask"],
            finger_landmarks,
            landmarks,
            min_area=500,
        )
        if mask is not None:
            method_used = "pixel-level"
            logger.debug("finger isolated via pixel-level segmentation")
        else:
            logger.debug("pixel-level segmentation failed, falling back to polygon")

    # Fallback to polygon-based approach
    if mask is None:
        mask = _create_finger_mask(landmarks, indices, image_shape)
        if mask is not None:
            method_used = "polygon"
            logger.debug("finger isolated via polygon segmentation (fallback)")
        else:
            logger.warning("both finger segmentation methods failed")
            return None

    return {
        "mask": mask,
        "landmarks": finger_landmarks,
        "base_point": finger_landmarks[0],  # MCP joint
        "tip_point": finger_landmarks[3],   # Fingertip
        "finger_name": finger,
        "method": method_used,
    }


def _create_finger_mask(
    all_landmarks: np.ndarray,
    finger_indices: List[int],
    shape: Tuple[int, int],
    width_factor: float = 2.5,
) -> Optional[np.ndarray]:
    """
    Create a binary mask for a single finger using polygon approximation.

    This is the fallback method when pixel-level segmentation fails.

    Args:
        all_landmarks: All 21 hand landmarks
        finger_indices: Indices of the 4 finger landmarks
        shape: (height, width) of output mask
        width_factor: Multiplier for estimated finger width

    Returns:
        Binary mask of finger region
    """
    h, w = shape
    mask = np.zeros((h, w), dtype=np.uint8)

    finger_landmarks = all_landmarks[finger_indices]

    # Estimate finger width based on joint spacing
    mcp_idx = finger_indices[0]

    adjacent_distances = []
    for other_finger, other_indices in FINGER_LANDMARKS.items():
        other_mcp = other_indices[0]
        if other_mcp != mcp_idx:
            dist = np.linalg.norm(all_landmarks[mcp_idx] - all_landmarks[other_mcp])
            adjacent_distances.append(dist)

    if adjacent_distances:
        estimated_width = min(adjacent_distances) * 0.4 * width_factor
    else:
        finger_length = np.linalg.norm(finger_landmarks[3] - finger_landmarks[0])
        estimated_width = finger_length / 6 * width_factor

    # Create polygon along finger with estimated width
    polygon_points = []

    for i in range(len(finger_landmarks)):
        pt = finger_landmarks[i]

        if i < len(finger_landmarks) - 1:
            direction = finger_landmarks[i + 1] - pt
        else:
            direction = pt - finger_landmarks[i - 1]

        perp = np.array([-direction[1], direction[0]])
        perp_norm = np.linalg.norm(perp)
        if perp_norm > 0:
            perp = perp / perp_norm

        width_scale = 1.0 - 0.3 * (i / (len(finger_landmarks) - 1))
        half_width = estimated_width * width_scale / 2

        left = pt + perp * half_width
        right = pt - perp * half_width
        polygon_points.append((left, right))

    # Build polygon: go up left side, then down right side
    polygon = []
    for left, right in polygon_points:
        polygon.append(left)
    for left, right in reversed(polygon_points):
        polygon.append(right)

    polygon = np.array(polygon, dtype=np.int32)
    cv2.fillPoly(mask, [polygon], 255)

    # Extend mask slightly towards palm
    mcp = finger_landmarks[0]
    wrist = all_landmarks[WRIST_LANDMARK]
    palm_direction = mcp - wrist
    palm_direction = palm_direction / (np.linalg.norm(palm_direction) + 1e-8)

    finger_length = np.linalg.norm(finger_landmarks[3] - finger_landmarks[0])
    extension = palm_direction * finger_length * 0.15
    extended_base = mcp - extension

    perp = np.array([-palm_direction[1], palm_direction[0]])
    half_width = estimated_width / 2
    ext_polygon = np.array([
        mcp + perp * half_width,
        mcp - perp * half_width,
        extended_base - perp * half_width * 0.8,
        extended_base + perp * half_width * 0.8,
    ], dtype=np.int32)

    cv2.fillPoly(mask, [ext_polygon], 255)

    return mask


def clean_mask(
    mask: np.ndarray,
    min_area: int = 1000,
) -> Optional[np.ndarray]:
    """
    Clean a binary mask by extracting largest component and applying morphology.

    Args:
        mask: Input binary mask
        min_area: Minimum valid area in pixels

    Returns:
        Cleaned binary mask, or None if no valid component found
    """
    if mask is None or mask.size == 0:
        return None

    # Find connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    if num_labels <= 1:
        return None

    # Find largest component (excluding background at index 0)
    largest_idx = 1
    largest_area = 0

    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area > largest_area:
            largest_area = area
            largest_idx = i

    if largest_area < min_area:
        return None

    # Create mask with only the largest component
    cleaned = np.zeros_like(mask)
    cleaned[labels == largest_idx] = 255

    # Apply morphological smoothing
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)

    # Smooth edges with Gaussian blur and re-threshold
    cleaned = cv2.GaussianBlur(cleaned, (5, 5), 0)
    _, cleaned = cv2.threshold(cleaned, 127, 255, cv2.THRESH_BINARY)

    return cleaned


def get_finger_contour(
    mask: np.ndarray,
    smooth: bool = True,
) -> Optional[np.ndarray]:
    """
    Extract outer contour from finger mask.

    Args:
        mask: Binary finger mask
        smooth: Whether to apply contour smoothing

    Returns:
        Contour points as Nx2 array, or None if no contour found
    """
    if mask is None:
        return None

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    # Get the largest contour
    largest_contour = max(contours, key=cv2.contourArea)

    # Reshape to Nx2
    contour = largest_contour.reshape(-1, 2)

    if smooth and len(contour) > 10:
        # Apply contour smoothing using approximation
        epsilon = 0.005 * cv2.arcLength(largest_contour, True)
        smoothed = cv2.approxPolyDP(largest_contour, epsilon, True)
        contour = smoothed.reshape(-1, 2)

    return contour.astype(np.float32)
