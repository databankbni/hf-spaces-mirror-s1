"""
Constants for confidence scoring module.

This module contains thresholds and weights used in confidence calculation
for card detection, finger detection, and measurement stability.
"""

# =============================================================================
# Card Confidence Constants
# =============================================================================

# Ideal credit card aspect ratio (ISO/IEC 7810 ID-1)
CARD_IDEAL_ASPECT_RATIO = 85.60 / 53.98  # ≈ 1.586

# Maximum acceptable aspect ratio deviation (fraction)
CARD_MAX_ASPECT_DEVIATION = 0.15  # 15%

# Card confidence component weights
CARD_WEIGHT_DETECTION = 0.5    # Detection quality: 50%
CARD_WEIGHT_ASPECT = 0.25      # Aspect ratio: 25%
CARD_WEIGHT_SCALE = 0.25       # Scale calibration: 25%


# =============================================================================
# Finger Confidence Constants
# =============================================================================

# Ideal mask area fraction of total image area
FINGER_IDEAL_MIN_AREA_FRACTION = 0.005  # 0.5% of image
FINGER_IDEAL_MAX_AREA_FRACTION = 0.05   # 5% of image

# Finger confidence component weights
FINGER_WEIGHT_HAND_DETECTION = 0.7  # Hand detection: 70%
FINGER_WEIGHT_MASK_VALIDITY = 0.3   # Mask validity: 30%


# =============================================================================
# Measurement Confidence Constants
# =============================================================================

# Coefficient of variation thresholds
# CV = std_dev / mean
MEASUREMENT_CV_EXCELLENT = 0.05  # CV < 0.05 is excellent
MEASUREMENT_CV_POOR = 0.15       # CV < 0.15 is acceptable

# Median-mean consistency threshold (fractional difference)
MEASUREMENT_CONSISTENCY_THRESHOLD = 0.1  # 10% difference acceptable

# Outlier detection threshold (multiples of std dev)
MEASUREMENT_OUTLIER_STD_MULTIPLIER = 2.0

# Realistic finger width range (cm)
MEASUREMENT_WIDTH_TYPICAL_MIN = 1.4  # Typical minimum
MEASUREMENT_WIDTH_TYPICAL_MAX = 2.4  # Typical maximum
MEASUREMENT_WIDTH_ABSOLUTE_MIN = 1.0  # Absolute minimum (borderline)
MEASUREMENT_WIDTH_ABSOLUTE_MAX = 3.0  # Absolute maximum (borderline)

# Measurement confidence component weights
MEASUREMENT_WEIGHT_VARIANCE = 0.4      # Variance: 40%
MEASUREMENT_WEIGHT_CONSISTENCY = 0.2   # Consistency: 20%
MEASUREMENT_WEIGHT_OUTLIERS = 0.2      # Outliers: 20%
MEASUREMENT_WEIGHT_RANGE = 0.2         # Range: 20%

# Range score values
MEASUREMENT_RANGE_SCORE_IDEAL = 1.0        # Within typical range
MEASUREMENT_RANGE_SCORE_BORDERLINE = 0.7   # Within absolute range
MEASUREMENT_RANGE_SCORE_OUTSIDE = 0.3      # Outside realistic range


# =============================================================================
# Overall Confidence Constants
# =============================================================================

# Overall confidence component weights (4-component model)
WEIGHT_CARD = 0.25          # Card: 25%
WEIGHT_FINGER = 0.25        # Finger: 25%
WEIGHT_EDGE_QUALITY = 0.20  # Edge quality: 20%
WEIGHT_MEASUREMENT = 0.30   # Measurement: 30%

# Confidence level thresholds
CONFIDENCE_LEVEL_HIGH_THRESHOLD = 0.85   # > 0.85 = high
CONFIDENCE_LEVEL_MEDIUM_THRESHOLD = 0.6  # >= 0.6 = medium, < 0.6 = low
