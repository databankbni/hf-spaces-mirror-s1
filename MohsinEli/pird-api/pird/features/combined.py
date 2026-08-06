"""Combined Stream A (statistical) + Stream C (stylometric) features for PIRD fusion.
Produces a single (N, N_COMBINED) matrix; PIRD concatenates the standardized vector onto the
encoder embedding. Standardization stats (mean/std) are fit on training data and saved with the
checkpoint so train and inference use identical scaling."""
from __future__ import annotations
import numpy as np
from .statistical import StatisticalFeatures, N_FEATURES as _N_STAT
from .stylometric import stylometric_matrix, N_FEATURES as _N_STYLO

N_COMBINED = _N_STAT + _N_STYLO


class CombinedFeatures:
    def __init__(self, stat_model: str = "gpt2", device: str | None = None):
        self.stat = StatisticalFeatures(stat_model, device=device)

    def matrix(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, N_COMBINED), dtype=float)
        S = self.stat.matrix(texts)          # (N, 8)
        C = stylometric_matrix(texts)        # (N, 14)
        return np.concatenate([S, C], axis=1)


def standardize(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return (X - mean) / (std + 1e-6)
