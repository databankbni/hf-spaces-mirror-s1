"""Pitch-track utilities: Hz -> cents, octave folding, voicing, chunk sampling.

Pure numpy. This module (with pcd/tdms/rotations) defines the feature space
shared verbatim between training and the deployed Space.
"""

import numpy as np

from raagafinder.config import CENTS_PER_OCTAVE

# Anything at or below this f0 is treated as unvoiced regardless of the
# dataset's exact unvoiced convention (0.0 or negative).
MIN_VALID_F0_HZ = 10.0


def voiced_mask(f0_hz: np.ndarray) -> np.ndarray:
    """Boolean mask of voiced frames."""
    return np.asarray(f0_hz) > MIN_VALID_F0_HZ


def hz_to_cents(f0_hz: np.ndarray, tonic_hz: float) -> np.ndarray:
    """Unfolded cents relative to tonic. Unvoiced frames become NaN."""
    f0 = np.asarray(f0_hz, dtype=np.float64)
    out = np.full(f0.shape, np.nan)
    mask = voiced_mask(f0)
    out[mask] = CENTS_PER_OCTAVE * np.log2(f0[mask] / tonic_hz)
    return out


def fold_octave(cents: np.ndarray) -> np.ndarray:
    """Fold cents into [0, 1200). NaNs pass through."""
    return np.mod(cents, CENTS_PER_OCTAVE)


def sample_voiced_windows(
    mask: np.ndarray,
    hop_s: float,
    target_voiced_s: float,
    n_windows: int,
    rng: np.random.Generator,
) -> list[tuple[int, int]]:
    """Sample contiguous frame windows each containing >= target voiced time.

    Returns a list of (start, end) frame index pairs (end exclusive). A window
    starts at a voiced frame and extends to the minimal end index reaching the
    voiced-frame target. Windows may overlap. Returns fewer than n_windows if
    the recording is too short.
    """
    mask = np.asarray(mask, dtype=bool)
    target_frames = int(round(target_voiced_s / hop_s))
    csum = np.concatenate([[0], np.cumsum(mask)])  # csum[i] = voiced in [0, i)
    total_voiced = csum[-1]
    if total_voiced < target_frames:
        return []

    # Latest usable start: window starting here can still reach the target.
    # Find minimal end for each candidate start via searchsorted on csum.
    voiced_starts = np.flatnonzero(mask)
    # csum[end] - csum[start] >= target_frames  =>  csum[end] >= csum[start] + target
    max_csum_start = total_voiced - target_frames
    usable = voiced_starts[csum[voiced_starts] <= max_csum_start]
    if len(usable) == 0:
        return []

    starts = rng.choice(usable, size=min(n_windows, len(usable)), replace=len(usable) < n_windows)
    windows = []
    for s in np.atleast_1d(starts):
        end = int(np.searchsorted(csum, csum[s] + target_frames, side="left"))
        windows.append((int(s), end))
    return windows
