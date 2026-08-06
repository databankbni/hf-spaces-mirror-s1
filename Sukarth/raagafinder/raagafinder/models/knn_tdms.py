"""Distance-based kNN over TDMS surfaces (pure numpy; used in the Space).

Distances operate on flattened, L1-normalized surfaces. Bhattacharyya is the
primary metric per the ISMIR 2016 recipe; symmetric KL as secondary.
"""

import numpy as np

_EPS = 1e-12


def bhattacharyya(query: np.ndarray, refs: np.ndarray) -> np.ndarray:
    """-ln sum(sqrt(p*q)); query (D,), refs (N, D) -> (N,)."""
    bc = np.sqrt(np.clip(query[None, :], 0, None) * np.clip(refs, 0, None)).sum(axis=1)
    return -np.log(np.clip(bc, _EPS, None))


def symmetric_kl(query: np.ndarray, refs: np.ndarray) -> np.ndarray:
    p = np.clip(query[None, :], _EPS, None)
    q = np.clip(refs, _EPS, None)
    return ((p - q) * (np.log(p) - np.log(q))).sum(axis=1)


def euclidean(query: np.ndarray, refs: np.ndarray) -> np.ndarray:
    d = refs - query[None, :]
    return np.sqrt((d * d).sum(axis=1))


DISTANCES = {
    "bhattacharyya": bhattacharyya,
    "symmetric_kl": symmetric_kl,
    "euclidean": euclidean,
}


def knn_probs(
    query: np.ndarray,
    refs: np.ndarray,
    ref_labels: np.ndarray,
    n_classes: int,
    k: int = 1,
    distance: str = "bhattacharyya",
    temperature: float = 1.0,
) -> np.ndarray:
    """Soft class probabilities from distance-weighted kNN.

    Uses softmax(-d/T) over the k nearest references, accumulated per class.
    """
    d = DISTANCES[distance](query.astype(np.float64), refs.astype(np.float64))
    nn = np.argpartition(d, min(k, len(d) - 1))[:k]
    w = np.exp(-(d[nn] - d[nn].min()) / max(temperature, _EPS))
    probs = np.zeros(n_classes)
    np.add.at(probs, ref_labels[nn], w)
    return probs / probs.sum()
