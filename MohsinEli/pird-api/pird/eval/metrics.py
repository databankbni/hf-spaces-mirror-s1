"""
Evaluation metrics for AI-text detection (pure NumPy, no sklearn dependency).

Convention everywhere:
    label 1 = AI-generated (positive class), label 0 = human.
    score   = detector's P(AI) or any monotonic AI-ness score; HIGHER = more likely AI.

The deployment-relevant metric for this project is TPR@low-FPR (you must not falsely accuse humans),
plus ECE for the calibrated 0-100% confidence claim.
"""
from __future__ import annotations
import numpy as np


def _rankdata(a: np.ndarray) -> np.ndarray:
    """Average ranks (ties shared), equivalent to scipy.stats.rankdata(method='average')."""
    a = np.asarray(a, dtype=float)
    sorter = np.argsort(a, kind="mergesort")
    inv = np.empty(len(a), dtype=int)
    inv[sorter] = np.arange(len(a))
    a_sorted = a[sorter]
    obs = np.r_[True, a_sorted[1:] != a_sorted[:-1]]
    dense = obs.cumsum()[inv]
    counts = np.r_[np.nonzero(obs)[0], len(a)]
    return 0.5 * (counts[dense] + counts[dense - 1] + 1)


def auroc(labels, scores) -> float:
    """Area under the ROC curve via the Mann-Whitney U statistic (tie-aware)."""
    labels = np.asarray(labels).astype(int)
    scores = np.asarray(scores, dtype=float)
    n1 = int((labels == 1).sum())
    n0 = int((labels == 0).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = _rankdata(scores)
    return float((r[labels == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def tpr_at_fpr(labels, scores, fpr_target: float = 0.01) -> float:
    """True-positive rate (AI caught) at a fixed false-positive rate (humans wrongly flagged)."""
    labels = np.asarray(labels).astype(int)
    scores = np.asarray(scores, dtype=float)
    pos = scores[labels == 1]
    neg = scores[labels == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    thr = np.quantile(neg, 1.0 - fpr_target)  # flag if score >= thr
    return float(np.mean(pos >= thr))


def fpr_at_threshold(labels, scores, thr: float) -> float:
    labels = np.asarray(labels).astype(int)
    scores = np.asarray(scores, dtype=float)
    neg = scores[labels == 0]
    return float(np.mean(neg >= thr)) if len(neg) else float("nan")


def accuracy(labels, scores, thr: float = 0.5) -> float:
    labels = np.asarray(labels).astype(int)
    preds = (np.asarray(scores, dtype=float) >= thr).astype(int)
    return float(np.mean(preds == labels))


def f1(labels, scores, thr: float = 0.5) -> float:
    labels = np.asarray(labels).astype(int)
    preds = (np.asarray(scores, dtype=float) >= thr).astype(int)
    tp = int(((preds == 1) & (labels == 1)).sum())
    fp = int(((preds == 1) & (labels == 0)).sum())
    fn = int(((preds == 0) & (labels == 1)).sum())
    if tp == 0:
        return 0.0
    prec = tp / (tp + fp)
    rec = tp / (tp + fn)
    return float(2 * prec * rec / (prec + rec))


def best_accuracy(labels, scores) -> float:
    """Accuracy at the score threshold that maximizes it (predict AI if score >= thr).
    Meaningful for raw, uncalibrated scores where a fixed 0.5 cutoff is arbitrary."""
    labels = np.asarray(labels).astype(int)
    scores = np.asarray(scores, dtype=float)
    if len(scores) == 0:
        return float("nan")
    thrs = np.r_[np.unique(scores), np.inf]
    best = max(float((labels == 1).mean()), float((labels == 0).mean()))  # trivial baselines
    for thr in thrs:
        best = max(best, float(((scores >= thr).astype(int) == labels).mean()))
    return best


def ece(labels, probs, n_bins: int = 15) -> float:
    """Expected Calibration Error (equal-width bins) for the P(AI) estimate. Needs probs in [0,1]."""
    labels = np.asarray(labels).astype(int)
    probs = np.asarray(probs, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    n = len(probs)
    err = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (probs > lo) & (probs <= hi) if i > 0 else (probs >= lo) & (probs <= hi)
        if not m.any():
            continue
        conf = probs[m].mean()
        acc = labels[m].mean()
        err += abs(acc - conf) * m.sum() / n
    return float(err)


def summary(labels, scores, probs=None) -> dict:
    """Headline metrics dict. Pass `probs` (calibrated P(AI) in [0,1]) to include ECE."""
    sc = np.asarray(scores, dtype=float)
    out = {
        "auroc": auroc(labels, scores),
        "tpr@fpr=1%": tpr_at_fpr(labels, scores, 0.01),
        "tpr@fpr=5%": tpr_at_fpr(labels, scores, 0.05),
        "acc_best": best_accuracy(labels, scores),
        "nan": int((~np.isfinite(sc)).sum()),   # >0 means the detector is broken (don't trust auroc)
        "n_ai": int((np.asarray(labels) == 1).sum()),
        "n_human": int((np.asarray(labels) == 0).sum()),
    }
    if probs is not None:
        out["ece"] = ece(labels, probs)
    return out


def format_summary(s: dict) -> str:
    order = ["auroc", "tpr@fpr=1%", "tpr@fpr=5%", "acc_best", "ece", "nan", "n_ai", "n_human"]
    parts = [f"{k}={s[k]:.4f}" if isinstance(s.get(k), float) else f"{k}={s.get(k)}"
             for k in order if k in s]
    return "  ".join(parts)


if __name__ == "__main__":  # self-test
    rng = np.random.default_rng(0)
    ai = rng.normal(0.8, 0.1, 500).clip(0, 1)      # AI scores high
    hu = rng.normal(0.2, 0.1, 500).clip(0, 1)      # humans low
    labels = np.r_[np.ones(500), np.zeros(500)]
    scores = np.r_[ai, hu]
    s = summary(labels, scores, probs=scores)
    print(format_summary(s))
    assert 0.95 < s["auroc"] <= 1.0, s["auroc"]
    assert s["tpr@fpr=1%"] > 0.8
    print("metrics self-test passed")
