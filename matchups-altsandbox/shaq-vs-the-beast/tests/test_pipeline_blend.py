"""Tests for multi-season blend helpers in the pipeline.

The blend is opt-in; default behaviour (single season) must be preserved.
"""
from __future__ import annotations

import pytest

from thebeast.pipeline import _blend_rates, _season_weights


class TestSeasonWeights:
    def test_single_season_default(self) -> None:
        assert _season_weights(2024, None, 0.6) == [(2024, 1.0)]

    def test_empty_train_seasons_is_single(self) -> None:
        assert _season_weights(2024, [], 0.6) == [(2024, 1.0)]

    def test_decay_most_recent_first(self) -> None:
        sw = _season_weights(2024, [2021, 2022, 2023], 0.5)
        assert sw[0] == (2023, 1.0)
        assert sw[1] == (2022, 0.5)
        assert sw[2] == (2021, 0.25)


class TestBlendRates:
    def test_single_entry_passthrough(self) -> None:
        rates = (0.15, 0.05, 0.005, 0.04, 0.08, 0.01, 0.22, 0.445)
        blended, eff = _blend_rates([(rates, 500, 1.0)])
        assert eff == 500
        assert abs(blended["single"] - 0.15) < 1e-9
        assert abs(sum(blended.values()) - 1.0) < 1e-9

    def test_sample_weighting(self) -> None:
        # Two seasons: a high-PA league-ish line and a low-PA extreme line.
        big = (0.15, 0.05, 0.005, 0.04, 0.08, 0.01, 0.22, 0.445)
        small = (0.05, 0.02, 0.001, 0.30, 0.05, 0.01, 0.30, 0.269)
        blended, eff = _blend_rates([(big, 600, 1.0), (small, 60, 1.0)])
        # 600 PA dominates 60 PA → blended HR near the big line, far from 0.30.
        assert blended["hr"] < 0.08
        assert eff == 660
        assert abs(sum(blended.values()) - 1.0) < 1e-9

    def test_decay_weight_reduces_contribution(self) -> None:
        recent = (0.15, 0.05, 0.005, 0.04, 0.08, 0.01, 0.22, 0.445)
        old = (0.05, 0.02, 0.001, 0.30, 0.05, 0.01, 0.30, 0.269)
        # Equal samples, but the old extreme line is decayed to 0.1.
        blended, _ = _blend_rates([(recent, 500, 1.0), (old, 500, 0.1)])
        assert blended["hr"] < 0.08  # recent dominates despite equal PA
