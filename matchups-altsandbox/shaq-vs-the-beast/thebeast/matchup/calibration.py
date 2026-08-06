"""Probability calibration — isotonic regression + reliability curve (F-003).

Calibration is the secondary accuracy gate (SPEC.md): on the 2024 holdout, each
decile's actual win rate must fall within ±2% of its predicted probability.

`reliability_curve` measures calibration; `IsotonicCalibrator` corrects it with
a monotone fit (sklearn IsotonicRegression) that can be serialized into the
Repository and reapplied to live model probabilities at inference time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


@dataclass
class CalibrationReport:
    """Reliability-curve summary across probability bins."""
    n_bins: int
    bin_predicted: list[float] = field(default_factory=list)
    bin_actual: list[float] = field(default_factory=list)
    bin_count: list[int] = field(default_factory=list)
    max_deviation: float = 0.0

    def within_tolerance(self, tol: float = 0.02) -> bool:
        """True when every populated bin is within `tol` of perfect calibration."""
        return self.max_deviation <= tol

    def format(self) -> str:
        rows = [
            f"  [{p:.2f}] actual={a:.3f} n={c}"
            for p, a, c in zip(self.bin_predicted, self.bin_actual, self.bin_count)
        ]
        return ("Reliability curve:\n" + "\n".join(rows)
                + f"\n  max deviation: {self.max_deviation:.4f}")


def reliability_curve(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    n_bins: int = 10,
) -> CalibrationReport:
    """Bin predictions and compare each bin's mean prediction to its hit rate."""
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must be the same length")
    if not probabilities:
        raise ValueError("cannot build a reliability curve from empty input")

    probs = np.asarray(probabilities, dtype=float)
    actual = np.asarray(outcomes, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    # Bin index for each prob; clip the right edge into the last bin.
    idx = np.clip(np.digitize(probs, edges[1:-1]), 0, n_bins - 1)

    predicted: list[float] = []
    observed: list[float] = []
    counts: list[int] = []
    max_dev = 0.0
    for b in range(n_bins):
        mask = idx == b
        c = int(mask.sum())
        if c == 0:
            continue
        p_mean = float(probs[mask].mean())
        a_mean = float(actual[mask].mean())
        predicted.append(p_mean)
        observed.append(a_mean)
        counts.append(c)
        max_dev = max(max_dev, abs(p_mean - a_mean))

    return CalibrationReport(
        n_bins=len(counts),
        bin_predicted=predicted,
        bin_actual=observed,
        bin_count=counts,
        max_deviation=max_dev,
    )


class IsotonicCalibrator:
    """Monotone (isotonic) probability calibrator wrapping sklearn."""

    def __init__(self) -> None:
        self._model: Optional[IsotonicRegression] = None

    def fit(self, probabilities: Sequence[float], outcomes: Sequence[int]) -> "IsotonicCalibrator":
        model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        model.fit(np.asarray(probabilities, dtype=float),
                  np.asarray(outcomes, dtype=float))
        self._model = model
        return self

    def transform(self, probabilities: Sequence[float]) -> list[float]:
        if self._model is None:
            raise RuntimeError("calibrator must be fit before transform")
        return [float(v) for v in self._model.predict(np.asarray(probabilities, dtype=float))]

    def fit_transform(self, probabilities: Sequence[float], outcomes: Sequence[int]) -> list[float]:
        return self.fit(probabilities, outcomes).transform(probabilities)


class PlattCalibrator:
    """Logistic (Platt) recalibration: a logistic fit on the predicted logit.

    Empirically the right calibrator for the simulator's overconfident win
    probabilities (2023→2024 holdout): rank-preserving, only two parameters, so
    it generalizes where IsotonicRegression overfits sparse high-confidence bins.
    Held out it beat the home-field base-rate log-loss; isotonic did not.

    The fit reduces to two numbers (a slope and intercept on the logit), so a
    fitted calibrator serializes to a tiny JSON and is reapplied at inference
    analytically (no sklearn model or pickle needed at serve time).
    """

    _EPS = 1e-6

    def __init__(self, coef: Optional[float] = None, intercept: Optional[float] = None) -> None:
        self._coef = coef
        self._intercept = intercept

    @property
    def fitted(self) -> bool:
        return self._coef is not None and self._intercept is not None

    @staticmethod
    def _logit(p: np.ndarray, eps: float) -> np.ndarray:
        p = np.clip(p, eps, 1.0 - eps)
        return np.log(p / (1.0 - p))

    def fit(self, probabilities: Sequence[float], outcomes: Sequence[int],
            *, allow_intercept: bool = False) -> "PlattCalibrator":
        """Fit the recalibration. Slope-only unless an intercept is asked for.

        The intercept is off by default because the simulator already models
        home field — it plays the home half-innings last and gives the home
        team the last at-bat — so a constant added on top of its logit is that
        advantage counted twice. Graded games bear this out: the raw model's
        mean home probability is .520 against MLB's long-run .525, so its
        baseline is already right, while the intercept previously carried
        (+0.127) moved the decision boundary to a raw .403 — the model had to
        call the home team worse than a 40% shot before the shipped number
        would pick against it, and 27 of 80 picks were flipped, every one of
        them away to home.

        Shrinking an overconfident model is what this is for; shifting its
        level is not.
        """
        x = self._logit(np.asarray(probabilities, dtype=float), self._EPS).reshape(-1, 1)
        model = LogisticRegression(C=1e6, fit_intercept=allow_intercept)
        model.fit(x, np.asarray(outcomes, dtype=int))
        self._coef = float(model.coef_[0][0])
        self._intercept = float(model.intercept_[0]) if allow_intercept else 0.0
        return self

    def transform(self, probabilities: Sequence[float]) -> list[float]:
        if not self.fitted:
            raise RuntimeError("calibrator must be fit (or loaded) before transform")
        z = self._coef * self._logit(np.asarray(probabilities, dtype=float), self._EPS) + self._intercept
        return [float(v) for v in 1.0 / (1.0 + np.exp(-z))]

    def transform_one(self, probability: float) -> float:
        return self.transform([probability])[0]

    def fit_transform(self, probabilities: Sequence[float], outcomes: Sequence[int]) -> list[float]:
        return self.fit(probabilities, outcomes).transform(probabilities)

    # ── Serialization (2 params → tiny JSON) ──────────────────────────────────

    def to_dict(self) -> dict:
        if not self.fitted:
            raise RuntimeError("cannot serialize an unfitted calibrator")
        return {"kind": "platt", "coef": self._coef, "intercept": self._intercept}

    @classmethod
    def from_dict(cls, d: dict) -> "PlattCalibrator":
        return cls(coef=float(d["coef"]), intercept=float(d["intercept"]))

    def save(self, path) -> None:
        import json
        from pathlib import Path
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path) -> "PlattCalibrator":
        import json
        from pathlib import Path
        return cls.from_dict(json.loads(Path(path).read_text()))


class TotalsCalibrator:
    """Multiplicative total-runs calibrator.

    The simulator over-predicts game totals (a ~0.5 run bias on the 2024
    holdout). A single scale `s` applied to both teams' run distributions removes
    the systematic bias while preserving win probability (both teams scale
    equally) and avoiding negative runs. Fit so the model's mean total matches
    the actual mean total.
    """

    def __init__(self, scale: float = 1.0) -> None:
        self.scale = float(scale)

    @classmethod
    def fit(cls, model_totals: Sequence[float], actual_totals: Sequence[float]) -> "TotalsCalibrator":
        m = float(np.sum(model_totals))
        a = float(np.sum(actual_totals))
        return cls(scale=(a / m) if m > 0 else 1.0)

    def transform(self, totals: Sequence[float]) -> list[float]:
        return [t * self.scale for t in totals]

    def to_dict(self) -> dict:
        return {"kind": "totals_scale", "scale": self.scale}

    @classmethod
    def from_dict(cls, d: dict) -> "TotalsCalibrator":
        return cls(scale=float(d["scale"]))

    def save(self, path) -> None:
        import json
        from pathlib import Path
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path) -> "TotalsCalibrator":
        import json
        from pathlib import Path
        return cls.from_dict(json.loads(Path(path).read_text()))
