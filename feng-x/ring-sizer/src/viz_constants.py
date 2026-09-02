"""
Shared visualization constants for debug output across all algorithms.

This module provides centralized configuration for fonts, colors, sizes, and
layout used in debug visualizations throughout the Ring Sizer system.

Used by:
- card_detection.py - Multi-strategy card detection debug output
- finger_segmentation.py - Hand/finger detection debug output
- geometry.py - Axis, zone, measurement debug output
- visualization.py - Final composite debug overlay
- confidence.py - Confidence visualization

Example usage:
    from viz_constants import Color, FontScale, FontThickness, FONT_FACE

    cv2.putText(img, "Title", (20, 100), FONT_FACE,
                FontScale.TITLE, Color.WHITE,
                FontThickness.TITLE_OUTLINE, cv2.LINE_AA)
"""

import cv2
from typing import Tuple

# ============================================================================
# FONT SETTINGS
# ============================================================================

# Font face used across all visualizations
FONT_FACE = cv2.FONT_HERSHEY_SIMPLEX


class FontScale:
    """
    Font scale constants for text hierarchy levels.

    Larger values = bigger text. These are base scales that may be
    adjusted based on image size in some visualizations.
    """
    TITLE = 3.5          # Main titles (e.g., "Card Detection", "Final Result")
    SUBTITLE = 2.5       # Section headers (e.g., "Score: 0.85")
    LABEL = 1.8          # Inline labels (e.g., "#1 Score:0.83")
    BODY = 1.5           # Body text (normal annotations)
    SMALL = 1.0          # Small text (fine details)


class FontThickness:
    """
    Font thickness (stroke width) for text rendering.

    Larger values = thicker/bolder text.
    Use OUTLINE variants for background layer to create outlined text effect.
    """
    # Main text thickness
    TITLE = 7
    SUBTITLE = 5
    LABEL = 4
    BODY = 2

    # Outline/shadow thickness (draw first for outline effect)
    TITLE_OUTLINE = 10
    SUBTITLE_OUTLINE = 8
    LABEL_OUTLINE = 6
    BODY_OUTLINE = 4


# ============================================================================
# COLORS (BGR format for OpenCV)
# ============================================================================

class Color:
    """
    Standard colors used across all visualizations.

    All colors in BGR format (Blue, Green, Red) as required by OpenCV.
    Example: (255, 255, 255) = White in BGR

    Usage:
        cv2.circle(img, center, radius, Color.GREEN, -1)
    """
    # ========================================================================
    # Basic Colors
    # ========================================================================
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    RED = (0, 0, 255)      # BGR: (0, 0, 255)
    GREEN = (0, 255, 0)     # BGR: (0, 255, 0)
    BLUE = (255, 0, 0)      # BGR: (255, 0, 0)

    # ========================================================================
    # Extended Palette
    # ========================================================================
    CYAN = (255, 255, 0)    # BGR: (255, 255, 0)
    YELLOW = (0, 255, 255)   # BGR: (0, 255, 255)
    MAGENTA = (255, 0, 255)  # BGR: (255, 0, 255)
    ORANGE = (0, 128, 255)   # BGR: (0, 128, 255)
    PINK = (128, 128, 255)   # BGR: (128, 128, 255)

    # ========================================================================
    # Semantic Colors (what they represent in the system)
    # ========================================================================

    # Object colors. CONTOUR is the shared default for tracing detected
    # objects (card, hand silhouette, finger contour). Kept distinct from the
    # per-finger ring-zone band colors (cyan/green/magenta) so the structural
    # outlines don't compete with the measurement bands.
    CONTOUR = GREEN         # Default object contour
    CARD = CONTOUR          # Credit card outline
    FINGER = CONTOUR        # Finger contour

    # Axis/geometry colors
    AXIS_PALM = CYAN        # Palm-side axis endpoint
    AXIS_TIP = ORANGE       # Fingertip axis endpoint
    AXIS_LINE = YELLOW      # Finger principal axis line

    # Measurement colors
    RING_ZONE = CYAN        # Ring-wearing zone overlay
    CROSS_SECTION = ORANGE  # Cross-section lines
    POINT = BLUE            # Intersection/measurement points

    # Text colors
    TEXT_PRIMARY = WHITE    # Primary text (titles, main info)
    TEXT_SUCCESS = GREEN    # Success messages
    TEXT_ERROR = RED        # Error messages
    TEXT_WARNING = YELLOW   # Warning messages


class StrategyColor:
    """
    Colors for different card detection strategies.

    Used to visually distinguish candidates from different detection methods
    in debug visualizations.
    """
    CANNY = Color.CYAN           # Canny edge detection (cyan)
    ADAPTIVE = Color.ORANGE      # Adaptive thresholding (orange)
    OTSU = Color.MAGENTA         # Otsu's thresholding (magenta)
    COLOR_BASED = Color.GREEN    # Color-based detection (green)
    ALL_CANDIDATES = Color.PINK  # Combined candidates (pink/purple)


# ============================================================================
# DRAWING SIZES
# ============================================================================

class Size:
    """
    Size constants for drawing geometric elements (circles, lines, etc.).

    All sizes in pixels.
    """
    # Circle radii
    CORNER_RADIUS = 8           # Card corners, small points
    ENDPOINT_RADIUS = 15        # Axis endpoints (palm/tip)
    INTERSECTION_RADIUS = 8     # Cross-section intersection points
    POINT_RADIUS = 5            # Generic points

    # Line thicknesses
    CONTOUR_THICK = 5           # Thick contours (finger, card)
    CONTOUR_NORMAL = 3          # Normal contours (candidates)
    LINE_THICK = 4              # Thick lines (axis)
    LINE_NORMAL = 2             # Normal lines (cross-sections)
    LINE_THIN = 1               # Thin lines (grid, reference)


# ============================================================================
# LAYOUT CONSTANTS
# ============================================================================

class Layout:
    """
    Layout positioning constants for text and elements.

    All positions in pixels from top-left corner.
    """
    # Title positioning (top-left text block)
    TITLE_Y = 100               # Y position for main title
    SUBTITLE_Y = 200            # Y position for subtitle/secondary text
    LINE_SPACING = 100          # Vertical spacing between text lines

    # Text offsets
    TEXT_OFFSET_X = 20          # Horizontal margin from left edge
    TEXT_OFFSET_Y = 25          # Vertical offset for inline text
    LABEL_OFFSET = 20           # Offset for labels near objects

    # Result text area (final visualization)
    RESULT_TEXT_Y_START = 60           # Starting Y for result text block
    RESULT_TEXT_LINE_HEIGHT = 55       # Height between result text lines
    RESULT_TEXT_X_OFFSET = 40          # X offset for result text


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_scaled_font_size(base_scale: float, image_height: int,
                         reference_height: int = 1200,
                         min_scale: float = 1.5) -> float:
    """
    Scale font size based on image dimensions for consistent appearance.

    Args:
        base_scale: Base font scale (e.g., FontScale.TITLE)
        image_height: Height of the image in pixels
        reference_height: Reference height for scaling (default: 1200px)
        min_scale: Minimum scale to prevent text from being too small

    Returns:
        Scaled font size adjusted for image dimensions

    Example:
        # For a 2400px tall image, double the font size
        scale = get_scaled_font_size(FontScale.TITLE, 2400)
        # scale = 3.5 * 2 = 7.0
    """
    scale_factor = image_height / reference_height
    scaled = base_scale * scale_factor
    return max(scaled, min_scale)


def create_outlined_text(image, text, position, font_scale,
                        color, outline_color=None,
                        thickness=None, outline_thickness=None):
    """
    Draw text with outline for better visibility.

    Args:
        image: Image to draw on
        text: Text string to draw
        position: (x, y) position tuple
        font_scale: Font scale (from FontScale)
        color: Main text color (from Color)
        outline_color: Outline color (default: Color.WHITE)
        thickness: Main text thickness (auto-selected if None)
        outline_thickness: Outline thickness (auto-selected if None)

    Example:
        create_outlined_text(img, "Title", (20, 100),
                           FontScale.TITLE, Color.GREEN)
    """
    if outline_color is None:
        outline_color = Color.WHITE

    # Auto-select thickness based on font scale
    if thickness is None:
        if font_scale >= FontScale.TITLE:
            thickness = FontThickness.TITLE
        elif font_scale >= FontScale.SUBTITLE:
            thickness = FontThickness.SUBTITLE
        elif font_scale >= FontScale.LABEL:
            thickness = FontThickness.LABEL
        else:
            thickness = FontThickness.BODY

    if outline_thickness is None:
        outline_thickness = thickness + 3

    # Draw outline first (background layer)
    cv2.putText(image, text, position, FONT_FACE,
                font_scale, outline_color, outline_thickness, cv2.LINE_AA)

    # Draw main text on top
    cv2.putText(image, text, position, FONT_FACE,
                font_scale, color, thickness, cv2.LINE_AA)


# ============================================================================
# VALIDATION (Optional: for type checking and debugging)
# ============================================================================

def validate_color(color: Tuple[int, int, int]) -> bool:
    """
    Validate that a color tuple is in correct BGR format.

    Args:
        color: Tuple of (B, G, R) values

    Returns:
        True if valid, False otherwise
    """
    if not isinstance(color, tuple) or len(color) != 3:
        return False
    return all(0 <= val <= 255 for val in color)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Font settings
    'FONT_FACE',
    'FontScale',
    'FontThickness',

    # Colors
    'Color',
    'StrategyColor',

    # Sizes
    'Size',

    # Layout
    'Layout',

    # Helper functions
    'get_scaled_font_size',
    'create_outlined_text',
    'validate_color',
]
