"""Time-delayed melody surface (Gulati et al., ISMIR 2016).

2D histogram of (cents_t, cents_{t+tau}) over octave-folded tonic-normalized
pitch, Gaussian-smoothed (circularly), power-compressed, normalized.
"""

import numpy as np
from scipy.ndimage import gaussian_filter

from raagafinder.config import (
    CENTS_PER_OCTAVE,
    TDMS_ALPHA,
    TDMS_BINS,
    TDMS_SMOOTH_SIGMA_BINS,
    TDMS_TAU_S,
)


def compute_tdms(
    folded_cents: np.ndarray,
    mask: np.ndarray,
    hop_s: float,
    tau_s: float = TDMS_TAU_S,
    n_bins: int = TDMS_BINS,
    alpha: float = TDMS_ALPHA,
    sigma_bins: float = TDMS_SMOOTH_SIGMA_BINS,
) -> np.ndarray:
    """TDMS surface, shape (n_bins, n_bins), float64, sums to 1.

    Only frame pairs (t, t+delay) with both frames voiced contribute.
    """
    x = np.asarray(folded_cents, dtype=np.float64)
    m = np.asarray(mask, dtype=bool)
    delay = max(1, int(round(tau_s / hop_s)))
    if x.size <= delay:
        raise ValueError("compute_tdms: pitch track shorter than delay")

    a = x[:-delay]
    b = x[delay:]
    pair_mask = m[:-delay] & m[delay:]
    a = a[pair_mask]
    b = b[pair_mask]
    if a.size == 0:
        raise ValueError("compute_tdms: no voiced frame pairs")

    bin_width = CENTS_PER_OCTAVE / n_bins
    ia = np.floor(a / bin_width).astype(np.int64) % n_bins
    ib = np.floor(b / bin_width).astype(np.int64) % n_bins
    surface = np.bincount(ia * n_bins + ib, minlength=n_bins * n_bins).astype(np.float64)
    surface = surface.reshape(n_bins, n_bins)

    if sigma_bins > 0:
        surface = gaussian_filter(surface, sigma=sigma_bins, mode="wrap")
    if alpha != 1.0:
        surface = np.power(surface, alpha)
    total = surface.sum()
    return surface / total
