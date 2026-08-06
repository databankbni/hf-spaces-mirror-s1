"""Probability calibration: single-parameter temperature scaling on log-probs.

Fit on pooled out-of-fold recording-level probabilities (hundreds of samples
-- a single scalar is the right capacity; isotonic would overfit).
"""

import numpy as np
from scipy.optimize import minimize_scalar

_EPS = 1e-12


def apply_temperature(probs: np.ndarray, temperature: float) -> np.ndarray:
    """Rescale probabilities via softmax(log(p)/T). probs: (..., C)."""
    logp = np.log(np.clip(probs, _EPS, None)) / temperature
    logp -= logp.max(axis=-1, keepdims=True)
    e = np.exp(logp)
    return e / e.sum(axis=-1, keepdims=True)


def fit_temperature(oof_probs: np.ndarray, labels: np.ndarray) -> float:
    """Minimize NLL of temperature-scaled probs. oof_probs (N, C), labels (N,)."""
    labels = np.asarray(labels)

    def nll(t: float) -> float:
        p = apply_temperature(oof_probs, t)
        return -float(np.log(np.clip(p[np.arange(len(labels)), labels], _EPS, None)).mean())

    res = minimize_scalar(nll, bounds=(0.05, 20.0), method="bounded")
    return float(res.x)
