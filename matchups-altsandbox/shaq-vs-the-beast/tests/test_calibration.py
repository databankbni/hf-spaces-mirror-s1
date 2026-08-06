"""Tests for thebeast.matchup.calibration — isotonic calibration + reliability.

Test-first (Constitution Article III). Synthetic probability/outcome pairs only.
"""
from __future__ import annotations

import numpy as np
import pytest

from thebeast.matchup.calibration import (
    CalibrationReport,
    IsotonicCalibrator,
    PlattCalibrator,
    TotalsCalibrator,
    reliability_curve,
)


def _well_calibrated(n: int = 4000, seed: int = 0) -> tuple[list[float], list[int]]:
    """Probabilities that already match outcome frequencies."""
    rng = np.random.default_rng(seed)
    probs = rng.uniform(0.05, 0.95, size=n)
    outcomes = (rng.uniform(size=n) < probs).astype(int)
    return probs.tolist(), outcomes.tolist()


def _miscalibrated(n: int = 4000, seed: int = 1) -> tuple[list[float], list[int]]:
    """Overconfident probabilities: reported p but true rate is sqrt(p)."""
    rng = np.random.default_rng(seed)
    probs = rng.uniform(0.05, 0.95, size=n)
    true_p = np.sqrt(probs)
    outcomes = (rng.uniform(size=n) < true_p).astype(int)
    return probs.tolist(), outcomes.tolist()


class TestReliabilityCurve:
    def test_decile_count(self) -> None:
        probs, outcomes = _well_calibrated()
        report = reliability_curve(probs, outcomes, n_bins=10)
        assert isinstance(report, CalibrationReport)
        assert len(report.bin_predicted) == len(report.bin_actual)
        assert report.n_bins <= 10

    def test_well_calibrated_within_tolerance(self) -> None:
        probs, outcomes = _well_calibrated()
        report = reliability_curve(probs, outcomes, n_bins=10)
        # Each populated bin's actual rate should track its predicted mean.
        assert report.max_deviation < 0.05

    def test_miscalibrated_flagged(self) -> None:
        probs, outcomes = _miscalibrated()
        report = reliability_curve(probs, outcomes, n_bins=10)
        assert report.max_deviation > 0.05


class TestIsotonicCalibrator:
    def test_fit_improves_calibration(self) -> None:
        probs, outcomes = _miscalibrated()
        cal = IsotonicCalibrator().fit(probs, outcomes)
        adjusted = cal.transform(probs)
        before = reliability_curve(probs, outcomes).max_deviation
        after = reliability_curve(adjusted, outcomes).max_deviation
        assert after < before

    def test_transform_monotonic(self) -> None:
        probs, outcomes = _miscalibrated()
        cal = IsotonicCalibrator().fit(probs, outcomes)
        xs = [0.1, 0.3, 0.5, 0.7, 0.9]
        ys = cal.transform(xs)
        assert all(ys[i] <= ys[i + 1] + 1e-9 for i in range(len(ys) - 1))

    def test_transform_in_unit_interval(self) -> None:
        probs, outcomes = _miscalibrated()
        cal = IsotonicCalibrator().fit(probs, outcomes)
        ys = cal.transform([0.0, 0.25, 0.5, 0.75, 1.0])
        assert all(0.0 <= y <= 1.0 for y in ys)

    def test_transform_before_fit_raises(self) -> None:
        with pytest.raises(RuntimeError):
            IsotonicCalibrator().transform([0.5])


class TestPlattCalibrator:
    def test_corrects_overconfidence(self) -> None:
        # Overconfident probs: reported spans 0.05..0.95 but truth hugs the mean.
        rng = np.random.default_rng(2)
        n = 4000
        true_p = rng.uniform(0.4, 0.6, size=n)
        # Inflate spread around 0.5 to simulate overconfidence.
        reported = np.clip(0.5 + (true_p - 0.5) * 4.0, 0.02, 0.98)
        outcomes = (rng.uniform(size=n) < true_p).astype(int)
        cal = PlattCalibrator().fit(reported.tolist(), outcomes.tolist())
        adjusted = cal.transform(reported.tolist())
        before = reliability_curve(reported.tolist(), outcomes.tolist()).max_deviation
        after = reliability_curve(adjusted, outcomes.tolist()).max_deviation
        assert after < before

    def test_rank_preserving(self) -> None:
        rng = np.random.default_rng(3)
        probs = rng.uniform(0.05, 0.95, size=500)
        outcomes = (rng.uniform(size=500) < probs).astype(int)
        cal = PlattCalibrator().fit(probs.tolist(), outcomes.tolist())
        adj = np.array(cal.transform(probs.tolist()))
        order_in = np.argsort(probs)
        order_out = np.argsort(adj)
        assert np.array_equal(order_in, order_out)  # monotone → ranks preserved

    def test_transform_before_fit_raises(self) -> None:
        with pytest.raises(RuntimeError):
            PlattCalibrator().transform([0.5])

    def test_serialization_round_trip(self, tmp_path) -> None:
        probs, outcomes = _miscalibrated()
        cal = PlattCalibrator().fit(probs, outcomes)
        path = tmp_path / "cal.json"
        cal.save(path)
        loaded = PlattCalibrator.load(path)
        # Loaded calibrator reproduces transforms exactly (analytic 2-param form).
        xs = [0.1, 0.3, 0.5, 0.7, 0.9]
        assert cal.transform(xs) == loaded.transform(xs)

    def test_loaded_from_dict_no_sklearn_needed(self) -> None:
        cal = PlattCalibrator.from_dict({"coef": 0.32, "intercept": 0.13})
        assert cal.fitted
        # Overconfident 0.95 should pull toward the mean.
        assert cal.transform_one(0.95) < 0.95
        assert cal.transform_one(0.05) > 0.05

    def test_compresses_overconfident_extremes(self) -> None:
        cal = PlattCalibrator.from_dict({"coef": 0.32, "intercept": 0.13})
        assert cal.transform_one(0.5) == pytest.approx(0.532, abs=0.01)


class TestTotalsCalibrator:
    def test_fit_matches_mean(self) -> None:
        model = [9.0, 10.0, 8.0, 11.0]   # mean 9.5
        actual = [8.0, 9.0, 7.0, 10.0]   # mean 8.5
        cal = TotalsCalibrator.fit(model, actual)
        scaled = cal.transform(model)
        assert sum(scaled) == pytest.approx(sum(actual))
        assert cal.scale < 1.0  # model over-predicts → scale down

    def test_identity_when_unbiased(self) -> None:
        xs = [8.0, 9.0, 10.0]
        cal = TotalsCalibrator.fit(xs, xs)
        assert cal.scale == pytest.approx(1.0)

    def test_serialization_round_trip(self, tmp_path) -> None:
        cal = TotalsCalibrator(scale=0.93)
        path = tmp_path / "tc.json"
        cal.save(path)
        assert TotalsCalibrator.load(path).scale == pytest.approx(0.93)


class TestCalibrationDoesNotShiftTheLevel:
    """A recalibration may sharpen or soften the model's confidence. It must
    not tell it which side to favour.

    The simulator already models home field — the home team bats last, in the
    half-innings that decide walk-offs — so a constant added to its logit is
    that advantage counted a second time. The shipped calibrator carried
    +0.127, which moved the decision boundary to a raw .403: the model had to
    rate the home team below a 40% shot before the served number would pick
    against it. Across 80 graded games that flipped 27 picks, every one from
    away to home, and the raw model was right on 17 of them against the
    calibrated 10.
    """

    def test_fit_is_slope_only_by_default(self) -> None:
        import numpy as np
        from thebeast.matchup.calibration import PlattCalibrator

        rng = np.random.default_rng(0)
        # Outcomes deliberately biased toward the positive class, which is
        # exactly the situation that would tempt an intercept.
        p = rng.uniform(0.2, 0.8, 400)
        y = (rng.uniform(size=400) < np.clip(p + 0.15, 0, 1)).astype(int)
        cal = PlattCalibrator().fit(p, y)
        assert cal.to_dict()["intercept"] == 0.0
        assert cal.transform_one(0.5) == pytest.approx(0.5, abs=1e-9)

    def test_an_intercept_is_available_but_must_be_asked_for(self) -> None:
        import numpy as np
        from thebeast.matchup.calibration import PlattCalibrator

        rng = np.random.default_rng(1)
        p = rng.uniform(0.2, 0.8, 400)
        y = (rng.uniform(size=400) < np.clip(p + 0.15, 0, 1)).astype(int)
        cal = PlattCalibrator().fit(p, y, allow_intercept=True)
        assert cal.to_dict()["intercept"] != 0.0

    def test_the_shipped_calibrator_leaves_an_even_game_even(self) -> None:
        """Guards the artifact, not just the code path — a refit that
        reintroduced a level shift would ship silently otherwise."""
        from pathlib import Path

        from thebeast.matchup.calibration import PlattCalibrator

        path = Path(__file__).resolve().parents[1] / "data" / "calibrator.json"
        if not path.exists():
            pytest.skip("no calibrator shipped")
        cal = PlattCalibrator.load(path)
        assert cal.transform_one(0.5) == pytest.approx(0.5, abs=1e-6)

    def test_a_slope_only_calibrator_never_flips_a_pick(self) -> None:
        """The property that makes it safe: sharpening cannot change which
        side is favoured, only by how much."""
        from thebeast.matchup.calibration import PlattCalibrator

        for coef in (0.2, 0.5, 1.0, 2.0):
            cal = PlattCalibrator(coef=coef, intercept=0.0)
            for p in (0.05, 0.30, 0.45, 0.49, 0.51, 0.55, 0.70, 0.95):
                assert (cal.transform_one(p) >= 0.5) == (p >= 0.5)
