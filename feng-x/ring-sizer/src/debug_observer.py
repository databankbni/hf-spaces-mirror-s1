"""
Debug visualization observer for the ring measurement pipeline.

This module provides a non-intrusive way to capture and visualize intermediate
processing stages without polluting core algorithm implementations.

It also contains all drawing utility functions used for debug visualizations.
"""

import cv2
import numpy as np
from typing import Optional, Dict, Any, Callable, List, Tuple
from pathlib import Path

# Import visualization constants
from src.viz_constants import (
    FONT_FACE, FontScale, FontThickness, Color, Size, Layout
)


class DebugObserver:
    """
    Observer for capturing and saving intermediate processing stages.
    
    This class provides methods to save images and visualizations during
    algorithm execution without requiring core functions to handle I/O directly.
    """
    
    def __init__(self, debug_dir: str):
        """
        Initialize debug observer.
        
        Args:
            debug_dir: Directory where debug images will be saved
        """
        self.debug_dir = Path(debug_dir)
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self._stage_counter = {}
    
    def save_stage(self, name: str, image: np.ndarray) -> None:
        """
        Save an intermediate processing stage image.
        
        Args:
            name: Stage name (used as filename prefix)
            image: Image to save
        """
        if image is None or image.size == 0:
            return
        
        # Add counter for stages with multiple saves
        if name in self._stage_counter:
            self._stage_counter[name] += 1
            filename = f"{name}_{self._stage_counter[name]}.png"
        else:
            self._stage_counter[name] = 0
            filename = f"{name}.png"
        
        self._save_with_compression(image, filename)
    
    def draw_and_save(self, name: str, image: np.ndarray,
                      draw_func: Callable, *args, **kwargs) -> None:
        """
        Apply a drawing function to an image and save the result.
        
        Args:
            name: Stage name for the output file
            image: Base image to draw on
            draw_func: Function that takes (image, *args, **kwargs) and returns annotated image
            *args, **kwargs: Arguments to pass to draw_func
        """
        if image is None or image.size == 0:
            return
        
        annotated = draw_func(image, *args, **kwargs)
        self.save_stage(name, annotated)
    
    def _save_with_compression(self, image: np.ndarray, filename: str) -> None:
        """
        Save image with compression and optional downsampling.
        
        Args:
            image: Image to save
            filename: Output filename
        """
        output_path = self.debug_dir / filename
        
        # Downsample if too large (max 1920px dimension)
        h, w = image.shape[:2]
        max_dim = 1920
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        
        # PNG compression
        cv2.imwrite(str(output_path), image, [cv2.IMWRITE_PNG_COMPRESSION, 6])


# =============================================================================
# Drawing Functions for Debug Visualization
# =============================================================================

# Hand landmark and finger constants (from finger_segmentation.py)
FINGER_LANDMARKS = {
    "index": [5, 6, 7, 8],
    "middle": [9, 10, 11, 12],
    "ring": [13, 14, 15, 16],
    "pinky": [17, 18, 19, 20],
}

THUMB_LANDMARKS = [1, 2, 3, 4]

HAND_CONNECTIONS = [
    # Palm
    (0, 1), (0, 5), (0, 17), (5, 9), (9, 13), (13, 17),
    # Thumb
    (1, 2), (2, 3), (3, 4),
    # Index
    (5, 6), (6, 7), (7, 8),
    # Middle
    (9, 10), (10, 11), (11, 12),
    # Ring
    (13, 14), (14, 15), (15, 16),
    # Pinky
    (17, 18), (18, 19), (19, 20),
]

FINGER_COLORS = {
    "thumb": Color.RED,
    "index": Color.CYAN,
    "middle": Color.YELLOW,
    "ring": Color.MAGENTA,
    "pinky": Color.ORANGE,
}


# --- Finger Segmentation Drawing Functions ---

def draw_landmarks_overlay(image: np.ndarray, landmarks: np.ndarray, label: bool = True) -> np.ndarray:
    """
    Draw hand landmarks as numbered circles.

    Args:
        image: Input image
        landmarks: 21x2 array of landmark positions
        label: Whether to draw landmark numbers

    Returns:
        Image with landmarks drawn
    """
    overlay = image.copy()

    for i, (x, y) in enumerate(landmarks):
        # Draw circle
        cv2.circle(overlay, (int(x), int(y)), Size.ENDPOINT_RADIUS, Color.GREEN, -1)
        cv2.circle(overlay, (int(x), int(y)), Size.ENDPOINT_RADIUS, Color.BLACK, 2)

        # Draw number
        if label:
            text = str(i)
            text_size = cv2.getTextSize(text, FONT_FACE, FontScale.SMALL, FontThickness.BODY)[0]
            text_x = int(x - text_size[0] / 2)
            text_y = int(y + text_size[1] / 2)

            # Black outline
            cv2.putText(overlay, text, (text_x, text_y), FONT_FACE, FontScale.SMALL,
                       Color.BLACK, FontThickness.BODY + 2, cv2.LINE_AA)
            # White text
            cv2.putText(overlay, text, (text_x, text_y), FONT_FACE, FontScale.SMALL,
                       Color.WHITE, FontThickness.BODY, cv2.LINE_AA)

    return overlay


def draw_hand_skeleton(image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """
    Draw hand skeleton with connections between landmarks.

    Args:
        image: Input image
        landmarks: 21x2 array of landmark positions

    Returns:
        Image with skeleton drawn
    """
    overlay = image.copy()

    # Draw connections in the shared CONTOUR color so the skeleton matches
    # the hand silhouette and stays distinct from the per-finger band colors.
    # Thickness 2 (vs. the silhouette's 4) keeps the skeleton as a supporting
    # internal reference rather than competing with the outer contour.
    for idx1, idx2 in HAND_CONNECTIONS:
        pt1 = (int(landmarks[idx1, 0]), int(landmarks[idx1, 1]))
        pt2 = (int(landmarks[idx2, 0]), int(landmarks[idx2, 1]))
        cv2.line(overlay, pt1, pt2, Color.CONTOUR, 2, cv2.LINE_AA)

    # Draw landmarks on top
    for i, (x, y) in enumerate(landmarks):
        cv2.circle(overlay, (int(x), int(y)), Size.CORNER_RADIUS, Color.GREEN, -1)
        cv2.circle(overlay, (int(x), int(y)), Size.CORNER_RADIUS, Color.BLACK, 2)

    return overlay


def draw_detection_info(image: np.ndarray, confidence: float, handedness: str, rotation: int) -> np.ndarray:
    """
    Draw detection metadata on image.

    Args:
        image: Input image
        confidence: Detection confidence (0-1)
        handedness: "Left" or "Right"
        rotation: Rotation code (0, 1, 2, 3)

    Returns:
        Image with text overlay
    """
    overlay = image.copy()

    rotation_names = {0: "None", 1: "90° CW", 2: "180°", 3: "90° CCW"}
    rotation_name = rotation_names.get(rotation, "Unknown")

    lines = [
        f"Confidence: {confidence:.3f}",
        f"Hand: {handedness}",
        f"Rotation: {rotation_name}",
    ]

    y = Layout.TITLE_Y
    for line in lines:
        # Black outline
        cv2.putText(overlay, line, (Layout.TEXT_OFFSET_X, y), FONT_FACE, FontScale.BODY,
                   Color.BLACK, FontThickness.LABEL_OUTLINE, cv2.LINE_AA)
        # White text
        cv2.putText(overlay, line, (Layout.TEXT_OFFSET_X, y), FONT_FACE, FontScale.BODY,
                   Color.WHITE, FontThickness.LABEL, cv2.LINE_AA)
        y += Layout.LINE_SPACING

    return overlay


def draw_finger_regions(image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """
    Draw individual finger regions in different colors.

    Args:
        image: Input image
        landmarks: 21x2 array of landmark positions

    Returns:
        Image with colored finger regions
    """
    h, w = image.shape[:2]
    overlay = image.copy()
    mask_overlay = np.zeros((h, w, 3), dtype=np.uint8)

    # Draw thumb
    thumb_pts = landmarks[THUMB_LANDMARKS].astype(np.int32)
    cv2.fillConvexPoly(mask_overlay, thumb_pts, FINGER_COLORS["thumb"])

    # Draw each finger
    for finger_name, indices in FINGER_LANDMARKS.items():
        finger_pts = landmarks[indices].astype(np.int32)
        cv2.fillConvexPoly(mask_overlay, finger_pts, FINGER_COLORS[finger_name])

    # Blend with original
    overlay = cv2.addWeighted(overlay, 0.6, mask_overlay, 0.4, 0)

    return overlay


def draw_extension_scores(image: np.ndarray, scores: Dict[str, float], selected: str) -> np.ndarray:
    """
    Draw finger extension scores.

    Args:
        image: Input image
        scores: Dict mapping finger name to extension score
        selected: Name of selected finger

    Returns:
        Image with scores drawn
    """
    overlay = image.copy()

    # Sort by score
    sorted_fingers = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    y = Layout.TITLE_Y
    for finger_name, score in sorted_fingers:
        is_selected = (finger_name == selected)
        color = Color.GREEN if is_selected else Color.WHITE
        text = f"{finger_name.capitalize()}: {score:.1f}" + (" ✓" if is_selected else "")

        # Black outline
        cv2.putText(overlay, text, (Layout.TEXT_OFFSET_X, y), FONT_FACE, FontScale.BODY,
                   Color.BLACK, FontThickness.LABEL_OUTLINE, cv2.LINE_AA)
        # Colored text
        cv2.putText(overlay, text, (Layout.TEXT_OFFSET_X, y), FONT_FACE, FontScale.BODY,
                   color, FontThickness.LABEL, cv2.LINE_AA)
        y += Layout.LINE_SPACING

    return overlay


def draw_component_stats(image: np.ndarray, labels: np.ndarray, stats: np.ndarray,
                         selected_idx: int) -> np.ndarray:
    """
    Draw connected component statistics.

    Args:
        image: Input image
        labels: Connected component labels
        stats: Component statistics from cv2.connectedComponentsWithStats
        selected_idx: Index of selected component

    Returns:
        Image with colored components and stats
    """
    overlay = image.copy()

    # Create colored component visualization
    num_labels = stats.shape[0]
    colors = np.random.randint(0, 255, size=(num_labels, 3), dtype=np.uint8)
    colors[0] = [0, 0, 0]  # Background is black
    colors[selected_idx] = Color.GREEN  # Selected is green

    colored = colors[labels]
    overlay = cv2.addWeighted(overlay, 0.5, colored, 0.5, 0)

    # Draw text stats
    y = Layout.TITLE_Y
    lines = [
        f"Components: {num_labels - 1}",  # Exclude background
        f"Selected area: {stats[selected_idx, cv2.CC_STAT_AREA]} px",
    ]

    for line in lines:
        cv2.putText(overlay, line, (Layout.TEXT_OFFSET_X, y), FONT_FACE, FontScale.BODY,
                   Color.BLACK, FontThickness.LABEL_OUTLINE, cv2.LINE_AA)
        cv2.putText(overlay, line, (Layout.TEXT_OFFSET_X, y), FONT_FACE, FontScale.BODY,
                   Color.WHITE, FontThickness.LABEL, cv2.LINE_AA)
        y += Layout.LINE_SPACING

    return overlay


# --- Card Detection Drawing Functions ---

def draw_contours_overlay(
    image: np.ndarray,
    contours: List[np.ndarray],
    title: str,
    color: Optional[Tuple[int, int, int]] = None,
) -> np.ndarray:
    """
    Draw contours on an image overlay.

    Args:
        image: Original image
        contours: List of contours to draw
        title: Title for the visualization
        color: BGR color for contours (default: Color.GREEN)

    Returns:
        Annotated image
    """
    if color is None:
        color = Color.GREEN

    overlay = image.copy()

    # Draw all contours
    for contour in contours:
        if len(contour) == 4:
            # Draw quadrilateral
            pts = contour.reshape(4, 2).astype(np.int32)
            cv2.polylines(overlay, [pts], True, color, Size.CONTOUR_NORMAL)

    # Add title with outline for visibility
    cv2.putText(
        overlay, title, (Layout.TEXT_OFFSET_X, Layout.TITLE_Y),
        FONT_FACE, FontScale.TITLE, Color.WHITE,
        FontThickness.TITLE_OUTLINE, cv2.LINE_AA
    )
    cv2.putText(
        overlay, title, (Layout.TEXT_OFFSET_X, Layout.TITLE_Y),
        FONT_FACE, FontScale.TITLE, color,
        FontThickness.TITLE, cv2.LINE_AA
    )

    # Add count with outline
    count_text = f"Candidates: {len(contours)}"
    cv2.putText(
        overlay, count_text, (Layout.TEXT_OFFSET_X, Layout.SUBTITLE_Y),
        FONT_FACE, FontScale.SUBTITLE, Color.WHITE,
        FontThickness.SUBTITLE_OUTLINE, cv2.LINE_AA
    )
    cv2.putText(
        overlay, count_text, (Layout.TEXT_OFFSET_X, Layout.SUBTITLE_Y),
        FONT_FACE, FontScale.SUBTITLE, color,
        FontThickness.SUBTITLE, cv2.LINE_AA
    )

    return overlay


def draw_candidates_with_scores(
    image: np.ndarray,
    candidates: List[Tuple[np.ndarray, float, Dict[str, Any]]],
    title: str,
) -> np.ndarray:
    """
    Draw candidate contours with scores and details.

    Args:
        image: Original image
        candidates: List of (corners, score, details) tuples
        title: Title for the visualization

    Returns:
        Annotated image
    """
    overlay = image.copy()

    # Color palette for candidates (different colors for ranking)
    colors = [
        Color.GREEN,    # Green - best
        Color.YELLOW,   # Yellow
        Color.ORANGE,   # Orange
        Color.MAGENTA,  # Magenta
        Color.PINK      # Pink
    ]

    for idx, (corners, score, details) in enumerate(candidates):
        color = colors[idx % len(colors)]

        # Draw quadrilateral
        pts = corners.reshape(4, 2).astype(np.int32)
        cv2.polylines(overlay, [pts], True, color, Size.CONTOUR_NORMAL)

        # Draw corner circles
        for pt in pts:
            cv2.circle(overlay, tuple(pt), Size.CORNER_RADIUS, color, -1)

        # Prepare annotation text
        if score > 0:
            aspect_ratio = details.get("aspect_ratio", 0)
            area_ratio = details.get("area", 0) / (image.shape[0] * image.shape[1])
            text = f"#{idx+1} Score:{score:.2f} AR:{aspect_ratio:.2f} Area:{area_ratio:.2%}"
        else:
            reject_reason = details.get("reject_reason", "unknown")
            text = f"#{idx+1} REJECT: {reject_reason}"

        # Position text near first corner
        text_pos = (int(pts[0][0]) + 10, int(pts[0][1]) - 10)

        # Draw text with outline for visibility
        cv2.putText(
            overlay, text, text_pos,
            FONT_FACE, FontScale.LABEL, Color.BLACK,
            FontThickness.LABEL_OUTLINE, cv2.LINE_AA
        )
        cv2.putText(
            overlay, text, text_pos,
            FONT_FACE, FontScale.LABEL, color,
            FontThickness.LABEL, cv2.LINE_AA
        )

    # Add title with outline
    cv2.putText(
        overlay, title, (Layout.TEXT_OFFSET_X, Layout.TITLE_Y),
        FONT_FACE, FontScale.TITLE, Color.WHITE,
        FontThickness.TITLE_OUTLINE, cv2.LINE_AA
    )
    cv2.putText(
        overlay, title, (Layout.TEXT_OFFSET_X, Layout.TITLE_Y),
        FONT_FACE, FontScale.TITLE, Color.CYAN,
        FontThickness.TITLE, cv2.LINE_AA
    )

    return overlay


# --- Edge Refinement Drawing Functions (v1 Phase 5) ---

def draw_landmark_axis(
    image: np.ndarray,
    axis_data: Dict[str, Any],
    finger_landmarks: Optional[np.ndarray]
) -> np.ndarray:
    """
    Draw finger landmarks with axis overlay.
    
    Shows:
    - 4 finger landmarks (MCP, PIP, DIP, TIP)
    - Calculated finger axis
    - Axis endpoints
    - Landmark-based vs PCA method indicator
    """
    vis = image.copy()
    
    # Draw finger landmarks if available
    if finger_landmarks is not None and len(finger_landmarks) == 4:
        landmark_names = ["MCP", "PIP", "DIP", "TIP"]
        for i, (landmark, name) in enumerate(zip(finger_landmarks, landmark_names)):
            pt = tuple(landmark.astype(int))
            # Draw landmark
            cv2.circle(vis, pt, Size.ENDPOINT_RADIUS, Color.YELLOW, -1)
            cv2.circle(vis, pt, Size.ENDPOINT_RADIUS, Color.BLACK, 2)
            # Draw label
            cv2.putText(
                vis, name, (pt[0] + 20, pt[1] - 20),
                FONT_FACE, FontScale.LABEL,
                Color.BLACK, FontThickness.LABEL_OUTLINE
            )
            cv2.putText(
                vis, name, (pt[0] + 20, pt[1] - 20),
                FONT_FACE, FontScale.LABEL,
                Color.YELLOW, FontThickness.LABEL
            )
    
    # Draw axis line
    # Use actual anatomical endpoints (MCP to TIP) if available
    if "palm_end" in axis_data and "tip_end" in axis_data:
        start = axis_data["palm_end"]  # MCP (palm-side)
        end = axis_data["tip_end"]      # TIP (fingertip)
    else:
        # Fallback to geometric center method (for PCA or old data)
        center = axis_data["center"]
        direction = axis_data["direction"]
        length = axis_data["length"]
        start = center - direction * (length / 2.0)
        end = center + direction * (length / 2.0)

    # Draw axis
    cv2.line(
        vis,
        tuple(start.astype(int)),
        tuple(end.astype(int)),
        Color.CYAN, Size.LINE_THICK
    )

    # Draw endpoints
    cv2.circle(vis, tuple(start.astype(int)), Size.ENDPOINT_RADIUS, Color.CYAN, -1)
    cv2.circle(vis, tuple(end.astype(int)), Size.ENDPOINT_RADIUS, Color.MAGENTA, -1)
    
    # Add method indicator
    method = axis_data.get("method", "unknown")
    text = f"Axis Method: {method}"
    cv2.putText(
        vis, text, (50, 100),
        FONT_FACE, FontScale.TITLE,
        Color.BLACK, FontThickness.TITLE_OUTLINE
    )
    cv2.putText(
        vis, text, (50, 100),
        FONT_FACE, FontScale.TITLE,
        Color.CYAN, FontThickness.TITLE
    )
    
    return vis


def draw_ring_zone_roi(
    image: np.ndarray,
    zone_data: Dict[str, Any],
    roi_bounds: Tuple[int, int, int, int]
) -> np.ndarray:
    """
    Draw ring zone and ROI bounds.
    
    Shows:
    - Ring-wearing zone band
    - ROI bounding box
    - Zone start/end points
    """
    vis = image.copy()
    
    # Draw ring zone
    start_point = zone_data["start_point"]
    end_point = zone_data["end_point"]
    
    cv2.circle(vis, tuple(start_point.astype(int)), Size.ENDPOINT_RADIUS, Color.GREEN, -1)
    cv2.circle(vis, tuple(end_point.astype(int)), Size.ENDPOINT_RADIUS, Color.RED, -1)
    cv2.line(
        vis,
        tuple(start_point.astype(int)),
        tuple(end_point.astype(int)),
        Color.YELLOW, Size.LINE_THICK * 2
    )
    
    # Draw ROI bounding box
    x_min, y_min, x_max, y_max = roi_bounds
    cv2.rectangle(vis, (x_min, y_min), (x_max, y_max), Color.GREEN, Size.LINE_THICK)
    
    # Add labels
    text = "Ring Zone + ROI Bounds"
    cv2.putText(
        vis, text, (50, 100),
        FONT_FACE, FontScale.TITLE,
        Color.BLACK, FontThickness.TITLE_OUTLINE
    )
    cv2.putText(
        vis, text, (50, 100),
        FONT_FACE, FontScale.TITLE,
        Color.GREEN, FontThickness.TITLE
    )
    
    return vis


def draw_roi_extraction(
    roi_image: np.ndarray,
    roi_mask: Optional[np.ndarray]
) -> np.ndarray:
    """
    Draw extracted ROI with optional mask overlay.
    """
    # Convert grayscale to BGR for visualization
    if len(roi_image.shape) == 2:
        vis = cv2.cvtColor(roi_image, cv2.COLOR_GRAY2BGR)
    else:
        vis = roi_image.copy()
    
    # Overlay mask if available
    if roi_mask is not None:
        mask_colored = np.zeros_like(vis)
        mask_colored[:, :, 1] = roi_mask  # Green channel
        vis = cv2.addWeighted(vis, 0.7, mask_colored, 0.3, 0)
    
    return vis


def draw_gradient_visualization(
    gradient: np.ndarray,
    colormap: int = cv2.COLORMAP_JET
) -> np.ndarray:
    """
    Visualize gradient with color mapping.
    """
    grad_vis = np.clip(gradient, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(grad_vis, colormap)


def draw_edge_candidates(
    roi_image: np.ndarray,
    gradient_magnitude: np.ndarray,
    threshold: float
) -> np.ndarray:
    """
    Draw all pixels above gradient threshold (raw threshold, before spatial filtering).

    This shows ALL pixels where gradient > threshold, including background noise.
    Use draw_filtered_edge_candidates() to see only spatially-filtered candidates.
    """
    # Convert ROI to BGR
    if len(roi_image.shape) == 2:
        vis = cv2.cvtColor(roi_image, cv2.COLOR_GRAY2BGR)
    else:
        vis = roi_image.copy()

    # Find edge candidates
    candidates = gradient_magnitude > threshold

    # Overlay candidates in cyan
    vis[candidates] = Color.CYAN

    # Add annotation explaining this is raw threshold
    count = np.sum(candidates)
    text1 = f"All pixels > {threshold:.1f}"
    text2 = "(Before spatial filtering)"
    text3 = f"Count: {count:,}"

    cv2.putText(vis, text1, (20, 40), FONT_FACE, 1.5, Color.WHITE, 4)
    cv2.putText(vis, text1, (20, 40), FONT_FACE, 1.5, Color.BLACK, 2)

    cv2.putText(vis, text2, (20, 80), FONT_FACE, 1.2, Color.WHITE, 4)
    cv2.putText(vis, text2, (20, 80), FONT_FACE, 1.2, Color.YELLOW, 2)

    cv2.putText(vis, text3, (20, 120), FONT_FACE, 1.2, Color.WHITE, 4)
    cv2.putText(vis, text3, (20, 120), FONT_FACE, 1.2, Color.CYAN, 2)

    return vis


def draw_filtered_edge_candidates(
    roi_image: np.ndarray,
    gradient_magnitude: np.ndarray,
    threshold: float,
    roi_mask: Optional[np.ndarray],
    axis_center: np.ndarray,
    axis_direction: np.ndarray
) -> np.ndarray:
    """
    Draw only the spatially-filtered edge candidates that the algorithm actually considers.

    Shows pixels that pass BOTH gradient threshold AND spatial filtering:
    - Mask-constrained mode: Within finger mask boundaries
    - Axis-expansion mode: Along search path from axis outward

    This matches what detect_edges_per_row() actually evaluates.

    Args:
        roi_image: ROI image
        gradient_magnitude: Gradient magnitude array
        threshold: Gradient threshold
        roi_mask: Optional finger mask in ROI coordinates
        axis_center: Axis center point in ROI coordinates
        axis_direction: Axis direction vector in ROI coordinates

    Returns:
        Visualization showing only filtered candidates
    """
    # Convert ROI to BGR
    if len(roi_image.shape) == 2:
        vis = cv2.cvtColor(roi_image, cv2.COLOR_GRAY2BGR)
    else:
        vis = roi_image.copy()

    h, w = gradient_magnitude.shape

    # Helper function to get axis x-coordinate at each row
    def get_axis_x_at_row(y: int) -> int:
        """Calculate axis x-coordinate at given y using axis center and direction."""
        if abs(axis_direction[1]) < 1e-6:
            # Axis is horizontal, use center x
            return int(axis_center[0])

        # Calculate offset from axis center
        dy = y - axis_center[1]
        dx = dy * (axis_direction[0] / axis_direction[1])
        x = axis_center[0] + dx

        return int(np.clip(x, 0, w - 1))

    # MASK-CONSTRAINED MODE (if mask available)
    if roi_mask is not None:
        mode = "Mask-Constrained"
        candidate_count = 0

        for y in range(h):
            row_gradient = gradient_magnitude[y, :]
            row_mask = roi_mask[y, :]

            if not np.any(row_mask):
                continue

            # Find mask boundaries
            mask_indices = np.where(row_mask)[0]
            if len(mask_indices) < 2:
                continue

            left_mask_boundary = mask_indices[0]
            right_mask_boundary = mask_indices[-1]

            # Get axis position
            axis_x = get_axis_x_at_row(y)

            # Search LEFT from axis to left mask boundary - find STRONGEST gradient
            left_edge_x = None
            left_strength = 0
            search_start = max(left_mask_boundary, min(axis_x, w - 1))
            for x in range(search_start, left_mask_boundary - 1, -1):
                if x < 0 or x >= w:
                    continue
                if row_gradient[x] > threshold:
                    # Update if this is stronger than previous
                    if row_gradient[x] > left_strength:
                        left_edge_x = x
                        left_strength = row_gradient[x]

            # If no edge found, try relaxed threshold
            if left_edge_x is None:
                relaxed_threshold = threshold * 0.5
                for x in range(search_start, left_mask_boundary - 1, -1):
                    if x < 0 or x >= w:
                        continue
                    if row_gradient[x] > relaxed_threshold:
                        if row_gradient[x] > left_strength:
                            left_edge_x = x
                            left_strength = row_gradient[x]

            # Search RIGHT from axis to right mask boundary - find STRONGEST gradient
            right_edge_x = None
            right_strength = 0
            search_start = min(right_mask_boundary, max(axis_x, 0))
            for x in range(search_start, right_mask_boundary + 1):
                if x < 0 or x >= w:
                    continue
                if row_gradient[x] > threshold:
                    # Update if this is stronger than previous
                    if row_gradient[x] > right_strength:
                        right_edge_x = x
                        right_strength = row_gradient[x]

            # If no edge found, try relaxed threshold
            if right_edge_x is None:
                relaxed_threshold = threshold * 0.5
                for x in range(search_start, right_mask_boundary + 1):
                    if x < 0 or x >= w:
                        continue
                    if row_gradient[x] > relaxed_threshold:
                        if row_gradient[x] > right_strength:
                            right_edge_x = x
                            right_strength = row_gradient[x]

            # Draw the SELECTED edges only (not all candidates)
            if left_edge_x is not None:
                cv2.circle(vis, (left_edge_x, y), 2, Color.CYAN, -1)
                candidate_count += 1

            if right_edge_x is not None:
                cv2.circle(vis, (right_edge_x, y), 2, Color.MAGENTA, -1)
                candidate_count += 1

            # Draw axis position
            cv2.circle(vis, (axis_x, y), 1, Color.YELLOW, -1)

    # AXIS-EXPANSION MODE (no mask)
    else:
        mode = "Axis-Expansion"
        candidate_count = 0

        for y in range(h):
            row_gradient = gradient_magnitude[y, :]
            axis_x = get_axis_x_at_row(y)

            if axis_x < 0 or axis_x >= w:
                continue

            # Draw axis position
            cv2.circle(vis, (axis_x, y), 2, Color.YELLOW, -1)

            # Search LEFT from axis until first edge
            for x in range(axis_x, -1, -1):
                if row_gradient[x] > threshold:
                    cv2.circle(vis, (x, y), 2, Color.CYAN, -1)
                    candidate_count += 1
                    break  # Stop at first edge

            # Search RIGHT from axis until first edge
            for x in range(axis_x, w):
                if row_gradient[x] > threshold:
                    cv2.circle(vis, (x, y), 2, Color.MAGENTA, -1)
                    candidate_count += 1
                    break  # Stop at first edge

    # Add annotation
    text1 = f"Spatially-filtered candidates"
    text2 = f"Mode: {mode}"
    text3 = f"Count: {candidate_count:,}"

    cv2.putText(vis, text1, (20, 40), FONT_FACE, 1.5, Color.WHITE, 4)
    cv2.putText(vis, text1, (20, 40), FONT_FACE, 1.5, Color.GREEN, 2)

    cv2.putText(vis, text2, (20, 80), FONT_FACE, 1.2, Color.WHITE, 4)
    cv2.putText(vis, text2, (20, 80), FONT_FACE, 1.2, Color.YELLOW, 2)

    cv2.putText(vis, text3, (20, 120), FONT_FACE, 1.2, Color.WHITE, 4)
    cv2.putText(vis, text3, (20, 120), FONT_FACE, 1.2, Color.CYAN, 2)

    # Add legend
    legend_y = h - 80
    cv2.putText(vis, "Yellow: Axis", (20, legend_y), FONT_FACE, 1.0, Color.YELLOW, 2)
    cv2.putText(vis, "Cyan: Left edges", (20, legend_y + 30), FONT_FACE, 1.0, Color.CYAN, 2)
    cv2.putText(vis, "Magenta: Right edges", (20, legend_y + 60), FONT_FACE, 1.0, Color.MAGENTA, 2)

    return vis


def draw_selected_edges(
    roi_image: np.ndarray,
    edge_data: Dict[str, Any]
) -> np.ndarray:
    """
    Draw final selected left/right edges with enhanced visualization.
    Shows edge points, connecting lines, and statistics.
    """
    # Convert ROI to BGR
    if len(roi_image.shape) == 2:
        vis = cv2.cvtColor(roi_image, cv2.COLOR_GRAY2BGR)
    else:
        vis = roi_image.copy()
    
    h, w = vis.shape[:2]
    
    left_edges = edge_data["left_edges"]
    right_edges = edge_data["right_edges"]
    valid_rows = edge_data["valid_rows"]
    
    # Calculate statistics for valid edges
    valid_left = left_edges[valid_rows]
    valid_right = right_edges[valid_rows]
    valid_widths = valid_right - valid_left
    
    if len(valid_widths) > 0:
        median_width = np.median(valid_widths)
        
        # Draw connecting lines for every Nth row (to avoid clutter)
        line_spacing = max(1, int(len(valid_rows)) // 20)  # Show ~20 lines
        
        count = 0  # Count valid rows
        for row_idx, valid in enumerate(valid_rows):
            if not valid:
                continue
                
            left_x = int(left_edges[row_idx])
            right_x = int(right_edges[row_idx])
            width = right_x - left_x
            
            # Draw connecting line (every Nth valid row)
            if count % line_spacing == 0:
                # Color based on width deviation
                deviation = abs(width - median_width) / median_width if median_width > 0 else 0
                if deviation < 0.05:
                    line_color = Color.GREEN
                elif deviation < 0.15:
                    line_color = Color.YELLOW
                else:
                    line_color = Color.ORANGE
                
                cv2.line(vis, (left_x, row_idx), (right_x, row_idx), line_color, 1)
            
            count += 1  # Increment valid row counter
        
        # Draw edge points on top
        for row_idx, valid in enumerate(valid_rows):
            if valid:
                # Draw left edge (blue)
                left_x = int(left_edges[row_idx])
                cv2.circle(vis, (left_x, row_idx), 2, Color.CYAN, -1)
                
                # Draw right edge (magenta)
                right_x = int(right_edges[row_idx])
                cv2.circle(vis, (right_x, row_idx), 2, Color.MAGENTA, -1)
        
        # Add text annotations
        # Scale font size based on ROI height for readability
        font_scale = max(0.3, h / 600.0)  # Scale based on ROI height, min 0.3
        line_height = int(15 + h / 40.0)  # Scale line spacing too
        thickness = 1

        valid_pct = np.sum(valid_rows) / len(valid_rows) * 100
        text_lines = [
            f"Valid edges: {np.sum(valid_rows)}/{len(valid_rows)} ({valid_pct:.1f}%)",
            f"Left range: {np.min(valid_left):.1f}-{np.max(valid_left):.1f}px",
            f"Right range: {np.min(valid_right):.1f}-{np.max(valid_right):.1f}px",
            f"Width: {np.min(valid_widths):.1f}-{np.max(valid_widths):.1f}px",
            f"Median: {median_width:.1f}px"
        ]

        for i, text in enumerate(text_lines):
            y = line_height + i * line_height
            # Background for readability
            (text_w, text_h), _ = cv2.getTextSize(text, FONT_FACE, font_scale, thickness)
            cv2.rectangle(vis, (5, y - text_h - 2), (5 + text_w + 5, y + 2), (0, 0, 0), -1)
            cv2.putText(vis, text, (8, y), FONT_FACE, font_scale, Color.WHITE, thickness)
    
    return vis


def draw_width_measurements(
    roi_image: np.ndarray,
    edge_data: Dict[str, Any],
    width_data: Dict[str, Any]
) -> np.ndarray:
    """
    Draw width measurements with connecting lines.
    """
    # Convert ROI to BGR
    if len(roi_image.shape) == 2:
        vis = cv2.cvtColor(roi_image, cv2.COLOR_GRAY2BGR)
    else:
        vis = roi_image.copy()
    
    left_edges = edge_data["left_edges"]
    right_edges = edge_data["right_edges"]
    valid_rows = edge_data["valid_rows"]
    
    median_width_px = width_data["median_width_px"]
    
    # Draw width lines
    for row_idx, valid in enumerate(valid_rows):
        if valid:
            left_x = int(left_edges[row_idx])
            right_x = int(right_edges[row_idx])
            width_px = right_x - left_x
            
            # Color based on deviation from median
            deviation = abs(width_px - median_width_px) / median_width_px
            if deviation < 0.05:
                color = Color.GREEN  # Close to median
            elif deviation < 0.10:
                color = Color.YELLOW  # Moderate deviation
            else:
                color = Color.RED  # Large deviation
            
            # Draw line
            cv2.line(vis, (left_x, row_idx), (right_x, row_idx), color, 1)
    
    # Add median width annotation
    # Scale font size based on ROI height
    h = vis.shape[0]
    font_scale = max(0.4, h / 500.0)
    thickness = max(1, int(h / 150.0))

    median_cm = width_data["median_width_cm"]
    text = f"Median: {median_cm:.2f} cm ({median_width_px:.1f} px)"
    cv2.putText(
        vis, text, (10, int(h * 0.15)),
        FONT_FACE, font_scale,
        Color.BLACK, thickness + 2
    )
    cv2.putText(
        vis, text, (10, int(h * 0.15)),
        FONT_FACE, font_scale,
        Color.GREEN, thickness
    )
    
    return vis


def draw_outlier_detection(
    roi_image: np.ndarray,
    edge_data: Dict[str, Any],
    width_data: Dict[str, Any]
) -> np.ndarray:
    """
    Highlight outlier measurements.
    """
    # Convert ROI to BGR
    if len(roi_image.shape) == 2:
        vis = cv2.cvtColor(roi_image, cv2.COLOR_GRAY2BGR)
    else:
        vis = roi_image.copy()
    
    left_edges = edge_data["left_edges"]
    right_edges = edge_data["right_edges"]
    valid_rows = edge_data["valid_rows"]
    
    median_width_px = width_data["median_width_px"]
    outliers_removed = width_data.get("outliers_removed", 0)
    
    # Calculate MAD threshold
    all_widths = []
    for row_idx, valid in enumerate(valid_rows):
        if valid:
            width_px = right_edges[row_idx] - left_edges[row_idx]
            all_widths.append(width_px)
    
    if len(all_widths) > 0:
        all_widths = np.array(all_widths)
        mad = np.median(np.abs(all_widths - median_width_px))
        outlier_threshold = 3.0 * mad
        
        # Draw width lines color-coded
        for row_idx, valid in enumerate(valid_rows):
            if valid:
                left_x = int(left_edges[row_idx])
                right_x = int(right_edges[row_idx])
                width_px = right_x - left_x
                
                is_outlier = abs(width_px - median_width_px) > outlier_threshold
                color = Color.RED if is_outlier else Color.GREEN
                
                cv2.line(vis, (left_x, row_idx), (right_x, row_idx), color, 2)
    
    # Add annotation with adaptive font scaling
    h = vis.shape[0]
    font_scale = max(0.4, h / 500.0)
    thickness = max(1, int(h / 150.0))

    text = f"Outliers: {outliers_removed}"
    y_pos = int(h * 0.10)  # Position at 10% of image height

    # Get text size for background
    (text_w, text_h), baseline = cv2.getTextSize(text, FONT_FACE, font_scale, thickness)

    # Draw background for readability
    cv2.rectangle(vis, (5, y_pos - text_h - 5), (15 + text_w, y_pos + baseline),
                  (0, 0, 0), -1)

    # Draw text with outline
    cv2.putText(vis, text, (10, y_pos), FONT_FACE, font_scale,
                Color.BLACK, thickness + 2, cv2.LINE_AA)
    cv2.putText(vis, text, (10, y_pos), FONT_FACE, font_scale,
                Color.RED, thickness, cv2.LINE_AA)

    return vis


def draw_comprehensive_edge_overlay(
    full_image: np.ndarray,
    edge_data: Dict[str, Any],
    roi_bounds: Tuple[int, int, int, int],
    axis_data: Dict[str, Any],
    zone_data: Dict[str, Any],
    width_data: Dict[str, Any],
    scale_px_per_cm: float
) -> np.ndarray:
    """
    Comprehensive visualization showing detected edges overlaid on full image
    with axis, zone, and measurement annotations.
    """
    vis = full_image.copy()
    h, w = vis.shape[:2]
    
    x_min, y_min, x_max, y_max = roi_bounds
    left_edges = edge_data["left_edges"]
    right_edges = edge_data["right_edges"]
    valid_rows = edge_data["valid_rows"]
    
    # 1. Draw axis line
    # Handle both PCA (tip_point, palm_point) and landmark-based axis (center, direction)
    if "center" in axis_data:
        axis_center = axis_data["center"]
    elif "tip_point" in axis_data and "palm_point" in axis_data:
        axis_center = (axis_data["tip_point"] + axis_data["palm_point"]) / 2
    else:
        # Fallback: use midpoint of axis
        axis_center = np.array([w//2, h//2])
    
    axis_direction = axis_data["direction"]
    axis_length = axis_data["length"]
    
    axis_start = axis_center - axis_direction * (axis_length / 2)
    axis_end = axis_center + axis_direction * (axis_length / 2)
    cv2.line(vis, tuple(axis_start.astype(int)), tuple(axis_end.astype(int)), 
             Color.YELLOW, 2, cv2.LINE_AA)
    
    # 2. Draw ring zone bounds as two lines perpendicular to axis at zone start/end
    zone_start = zone_data["start_point"]
    zone_end = zone_data["end_point"]
    perp_direction = np.array([-axis_direction[1], axis_direction[0]])
    # Use ROI half-width so the zone lines span the ROI
    roi_half_width = (x_max - x_min) / 2.0

    for zone_pt in [zone_start, zone_end]:
        p1 = (zone_pt + perp_direction * roi_half_width).astype(int)
        p2 = (zone_pt - perp_direction * roi_half_width).astype(int)
        cv2.line(vis, tuple(p1), tuple(p2), Color.ORANGE, 2, cv2.LINE_AA)
    
    # 4. Draw detected edges
    line_spacing = max(1, int(np.sum(valid_rows)) // 25)  # Show ~25 lines
    count = 0
    
    for row_idx, valid in enumerate(valid_rows):
        if not valid:
            continue
        
        # Map ROI coordinates to full image
        global_y = y_min + row_idx
        left_x_global = x_min + int(left_edges[row_idx])
        right_x_global = x_min + int(right_edges[row_idx])
        
        # Draw edge points
        cv2.circle(vis, (left_x_global, global_y), 3, Color.BLUE, -1)
        cv2.circle(vis, (right_x_global, global_y), 3, Color.MAGENTA, -1)
        
        # Draw connecting lines for every Nth row
        if count % line_spacing == 0:
            cv2.line(vis, (left_x_global, global_y), (right_x_global, global_y),
                    Color.GREEN, 2, cv2.LINE_AA)
        count += 1
    
    # 5. Add text annotations in top-left corner with adaptive sizing
    median_cm = width_data["median_width_cm"]
    raw_cm = width_data.get("raw_width_cm")
    median_px = width_data["median_width_px"]
    std_px = width_data["std_width_px"]
    num_samples = width_data["num_samples"]
    valid_pct = np.sum(valid_rows) / len(valid_rows) * 100

    # Adaptive font scaling based on image height (more conservative for full-sized images)
    font_scale = max(0.3, h / 1500.0)  # Scale for full-sized images
    line_height = int(35 + h / 70.0)   # Scale line spacing (increased for better readability)
    thickness = max(1, int(h / 500.0))

    width_label = f"  Width: {median_cm:.3f} cm"
    if raw_cm is not None:
        width_label += f" (raw {raw_cm:.3f})"

    # Ring size recommendation
    ring_rec = width_data.get("ring_size_rec")
    ring_label = ""
    if ring_rec:
        ring_label = f"  Ring Size: best {ring_rec['best_match']}, try {ring_rec['range_min']}-{ring_rec['range_max']}"

    annotations = [
        f"Sobel Edge Detection Results:",
        width_label,
        ring_label,
        f"  Std Dev: {std_px:.2f} px",
        f"  Valid Edges: {np.sum(valid_rows)}/{len(valid_rows)} ({valid_pct:.1f}%)",
        f"  Measurements: {num_samples}",
        f"  Scale: {scale_px_per_cm:.2f} px/cm",
        "",
        "Legend:",
        "  Yellow line = Finger axis",
        "  Orange lines = Ring zone",
        "  Blue dots = Left edges",
        "  Magenta dots = Right edges",
        "  Green lines = Width measurements"
    ]

    # Draw text with background for readability
    y_offset = line_height
    for line in annotations:
        if line:  # Skip empty lines for background
            (text_w, text_h), baseline = cv2.getTextSize(line, FONT_FACE, font_scale, thickness)
            # Black background
            cv2.rectangle(vis, (15, y_offset - text_h - 5), (25 + text_w, y_offset + baseline),
                         (0, 0, 0), -1)
        # Draw text
        if line.startswith("  "):
            color = Color.WHITE
        elif line.endswith(":"):
            color = Color.YELLOW
        else:
            color = Color.CYAN
        cv2.putText(vis, line, (20, y_offset), FONT_FACE, font_scale,
                   color, thickness, cv2.LINE_AA)
        y_offset += line_height

    return vis


