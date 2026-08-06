"""Chunk -> recording probability aggregation."""

import numpy as np

_EPS = 1e-12


def aggregate_chunks(chunk_probs: np.ndarray, method: str = "mean") -> np.ndarray:
    """Aggregate (n_chunks, C) chunk probabilities into one (C,) distribution."""
    p = np.asarray(chunk_probs, dtype=np.float64)
    if p.ndim == 1:
        p = p[None, :]
    if method == "mean":
        agg = p.mean(axis=0)
    elif method == "median":
        agg = np.median(p, axis=0)
    elif method == "logmean":
        agg = np.exp(np.log(np.clip(p, _EPS, None)).mean(axis=0))
    else:
        raise ValueError(f"unknown aggregation method: {method}")
    return agg / agg.sum()
