"""Tonic-hypothesis rotations of PCD/TDMS features.

A tonic that is `offset` cents HIGHER shifts every folded cent value DOWN by
`offset`, which for a circular histogram is an exact roll — provided the
offset is an integer number of bins (config guarantees this for +-500/+-700
at 240 PCD bins / 120 TDMS bins).

Convention: rotate_*(feat, offset) returns the feature AS IF the tonic used
had been `offset` cents higher, i.e. equals compute(folded(cents - offset)).
"""

import numpy as np

from raagafinder.config import CENTS_PER_OCTAVE


def _offset_bins(offset_cents: float, n_bins: int) -> int:
    shift = offset_cents * n_bins / CENTS_PER_OCTAVE
    rounded = round(shift)
    if abs(shift - rounded) > 1e-9:
        raise ValueError(
            f"offset {offset_cents} cents is not an integer number of bins for n_bins={n_bins}"
        )
    return int(rounded)


def rotate_pcd(pcd: np.ndarray, offset_cents: float) -> np.ndarray:
    """PCD under a tonic offset_cents higher."""
    n_bins = pcd.shape[-1]
    return np.roll(pcd, -_offset_bins(offset_cents, n_bins), axis=-1)


def rotate_tdms(surface: np.ndarray, offset_cents: float) -> np.ndarray:
    """TDMS under a tonic offset_cents higher (both axes shift together)."""
    n_bins = surface.shape[-1]
    k = _offset_bins(offset_cents, n_bins)
    return np.roll(np.roll(surface, -k, axis=-2), -k, axis=-1)
