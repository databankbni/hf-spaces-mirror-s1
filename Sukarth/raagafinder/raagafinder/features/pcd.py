"""Pitch-class distribution: fine-grained, circularly smoothed, normalized."""

import numpy as np
from scipy.ndimage import gaussian_filter1d

from raagafinder.config import CENTS_PER_OCTAVE, PCD_BINS, PCD_SMOOTH_SIGMA_BINS


def compute_pcd(
    folded_cents: np.ndarray,
    n_bins: int = PCD_BINS,
    sigma_bins: float = PCD_SMOOTH_SIGMA_BINS,
) -> np.ndarray:
    """PCD from octave-folded voiced cents in [0, 1200). NaNs are ignored.

    Returns float64 array of length n_bins summing to 1.
    """
    x = np.asarray(folded_cents, dtype=np.float64)
    x = x[~np.isnan(x)]
    if x.size == 0:
        raise ValueError("compute_pcd: no voiced frames")
    bin_width = CENTS_PER_OCTAVE / n_bins
    idx = np.floor(x / bin_width).astype(np.int64) % n_bins
    hist = np.bincount(idx, minlength=n_bins).astype(np.float64)
    if sigma_bins > 0:
        hist = gaussian_filter1d(hist, sigma=sigma_bins, mode="wrap")
    total = hist.sum()
    return hist / total
