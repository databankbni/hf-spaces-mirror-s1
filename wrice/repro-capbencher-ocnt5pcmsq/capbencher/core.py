"""Core mathematical functions for CapBencher reproduction."""

from typing import Union
import math
try:
    from scipy.stats import binomtest
except ImportError:
    binomtest = None


def estimate_bayes_accuracy(num_choices: int) -> float:
    """Calculate the Bayes accuracy ceiling for a benchmark with K choices."""
    if num_choices < 1:
        raise ValueError("num_choices must be at least 1")
    return 1.0 / float(num_choices)


def affine_capped_score(orig_score: float, num_choices: int) -> float:
    """Map original benchmark score to capped score via Theorem 1 affine transformation."""
    if not (0.0 <= orig_score <= 1.0):
        raise ValueError("orig_score must be between 0.0 and 1.0")
    bayes_acc = estimate_bayes_accuracy(num_choices)
    return bayes_acc + (1.0 - bayes_acc) * orig_score


def exact_binomial_pvalue(k: int, n: int, alpha: float) -> float:
    """Calculate exact one-sided binomial test p-value for contamination detection."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not (0 <= k <= n):
        raise ValueError("k must be between 0 and n")
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be between 0 and 1")

    if binomtest is not None:
        result = binomtest(k, n, alpha, alternative="greater")
        return float(result.pvalue)

    # Fallback to exact sum formula: P(X >= k) under Binom(n, alpha)
    p_val = 0.0
    for i in range(k, n + 1):
        prob = math.comb(n, i) * (alpha ** i) * ((1.0 - alpha) ** (n - i))
        p_val += prob
    return p_val


def is_contaminated(k: int, n: int, alpha: float, significance: float = 0.05) -> bool:
    """Determine whether model performance is flagged as contaminated at given significance level."""
    p_val = exact_binomial_pvalue(k, n, alpha)
    return p_val <= significance
