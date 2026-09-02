"""
Constants for geometric computation module.

This module contains thresholds and parameters used in finger axis
estimation and ring zone localization.
"""

# =============================================================================
# Landmark Quality Validation Constants
# =============================================================================

# Minimum distance between consecutive landmarks (pixels)
# Less than this suggests collapsed/invalid landmarks
MIN_LANDMARK_SPACING_PX = 5.0

# Minimum total finger length from MCP to TIP (pixels)
# Entire finger less than this suggests invalid detection
MIN_FINGER_LENGTH_PX = 20.0


# =============================================================================
# Ring Zone Localization Constants
# =============================================================================

# Default ring zone position as percentage of finger length from palm
DEFAULT_ZONE_START_PCT = 0.15  # 15% from palm end
DEFAULT_ZONE_END_PCT = 0.25    # 25% from palm end

# Anatomical zone width factor (for anatomical localization mode)
# Zone width = MCP-PIP distance * this factor
ANATOMICAL_ZONE_WIDTH_FACTOR = 0.5  # 50% of MCP-PIP segment (25% each side)
