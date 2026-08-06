"""Tests for bulk Statcast → statline ingestion (no network).

Builds statlines for all players from a single season-wide DataFrame, the
efficient path for backtest/calibration ingestion.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from thebeast.data.ingest import (
    build_batter_statlines,
    build_pitcher_statlines,
    build_team_bullpens,
    ingest_dataframe,
    team_bullpen_pid,
)
from thebeast.data.repository import SQLiteRepository


def _synthetic_statcast(n_per_batter: int = 200, seed: int = 0) -> pd.DataFrame:
    """Two batters vs two pitchers with realistic event distribution."""
    rng = np.random.default_rng(seed)
    events_pool = (["single"] * 15 + ["double"] * 5 + ["home_run"] * 4
                   + ["walk"] * 9 + ["strikeout"] * 22 + ["field_out"] * 45)
    rows = []
    for batter in (101, 102):
        for _ in range(n_per_batter):
            pitcher = int(rng.choice([201, 202]))
            rows.append({
                "batter": batter,
                "pitcher": pitcher,
                "events": rng.choice(events_pool),
                "stand": "L" if batter == 101 else "R",
                "p_throws": "R" if pitcher == 201 else "L",
                "woba_value": float(rng.uniform(0, 2)),
                "estimated_woba_using_speedangle": float(rng.uniform(0, 2)),
            })
    return pd.DataFrame(rows)


@pytest.fixture
def df() -> pd.DataFrame:
    return _synthetic_statcast()


class TestBuildBatterStatlines:
    def test_one_per_batter(self, df: pd.DataFrame) -> None:
        lines = build_batter_statlines(df, season=2024, min_pa=10)
        assert {b.player_id for b in lines} == {101, 102}

    def test_rates_sum_to_one(self, df: pd.DataFrame) -> None:
        for b in build_batter_statlines(df, season=2024, min_pa=10):
            total = (b.single_rate + b.double_rate + b.triple_rate + b.hr_rate
                     + b.bb_rate + b.hbp_rate + b.k_rate + b.ipo_rate)
            assert abs(total - 1.0) < 1e-9

    def test_min_pa_filters(self, df: pd.DataFrame) -> None:
        # threshold above any single player's PA count → nobody qualifies
        assert build_batter_statlines(df, season=2024, min_pa=10_000) == []

    def test_hand_inferred(self, df: pd.DataFrame) -> None:
        lines = {b.player_id: b for b in build_batter_statlines(df, season=2024, min_pa=10)}
        assert lines[101].hand == "L"
        assert lines[102].hand == "R"


class TestBuildPitcherStatlines:
    def test_one_per_pitcher(self, df: pd.DataFrame) -> None:
        lines = build_pitcher_statlines(df, season=2024, min_bf=10)
        assert {p.player_id for p in lines} == {201, 202}

    def test_allowed_rates_sum_to_one(self, df: pd.DataFrame) -> None:
        for p in build_pitcher_statlines(df, season=2024, min_bf=10):
            total = (p.single_allowed + p.double_allowed + p.triple_allowed
                     + p.hr_allowed + p.bb_allowed + p.hbp_allowed
                     + p.k_rate + p.ipo_rate)
            assert abs(total - 1.0) < 1e-9


class TestIngestDataframe:
    def test_persists_to_repo(self, df: pd.DataFrame, tmp_path) -> None:
        repo = SQLiteRepository(str(tmp_path / "ingest.db"))
        n_b, n_p = ingest_dataframe(df, season=2024, repo=repo, min_pa=10, min_bf=10)
        assert n_b == 2 and n_p == 2
        assert repo.get_batter(101, 2024) is not None
        assert repo.get_pitcher(201, 2024) is not None


def _bullpen_statcast(seed: int = 0) -> pd.DataFrame:
    """Relievers (low BF) for two teams, plus a starter who should be excluded."""
    rng = np.random.default_rng(seed)
    events_pool = ["single"] * 14 + ["home_run"] * 4 + ["walk"] * 8 + \
                  ["strikeout"] * 24 + ["field_out"] * 50
    rows = []
    # Two relievers per team, ~120 PA each (below the 400 starter threshold).
    for team, opp, pid in [("NYY", "BOS", 9001), ("NYY", "BOS", 9002),
                           ("BOS", "NYY", 9101), ("BOS", "NYY", 9102)]:
        for _ in range(120):
            rows.append({
                "pitcher": pid, "events": rng.choice(events_pool),
                "inning_topbot": "Top" if team == "NYY" else "Bot",
                "home_team": "NYY", "away_team": "BOS", "stand": "R",
                "woba_value": float(rng.uniform(0, 2)),
            })
    # A workhorse starter (>400 BF) — must be excluded from the bullpen.
    for _ in range(500):
        rows.append({
            "pitcher": 7000, "events": "strikeout", "inning_topbot": "Top",
            "home_team": "NYY", "away_team": "BOS", "stand": "R", "woba_value": 0.1,
        })
    return pd.DataFrame(rows)


class TestTeamBullpens:
    def test_one_per_team(self) -> None:
        pens = build_team_bullpens(_bullpen_statcast(), season=2023, min_bf=50)
        assert {p.team_id for p in pens} == {"NYY", "BOS"}

    def test_allowed_rates_sum_to_one(self) -> None:
        for p in build_team_bullpens(_bullpen_statcast(), season=2023, min_bf=50):
            total = (p.single_allowed + p.double_allowed + p.triple_allowed
                     + p.hr_allowed + p.bb_allowed + p.hbp_allowed
                     + p.k_rate + p.ipo_rate)
            assert abs(total - 1.0) < 1e-9

    def test_excludes_starter(self) -> None:
        # The starter (pid 7000, all strikeouts) would spike K% if included.
        pens = {p.team_id: p for p in build_team_bullpens(_bullpen_statcast(), 2023, min_bf=50)}
        assert pens["NYY"].k_rate < 0.40  # reliever-only mix, not the 100%-K starter

    def test_pid_stable_and_negative(self) -> None:
        assert team_bullpen_pid("NYY") == team_bullpen_pid("NYY")
        assert team_bullpen_pid("NYY") != team_bullpen_pid("BOS")
        assert team_bullpen_pid("NYY") < 0


class TestTeamRosters:
    def test_top_batters_per_team(self) -> None:
        import pandas as pd
        from thebeast.data.ingest import ROSTER_GAME_ID, build_team_rosters
        rows = []
        # NYY (home) batters in bottom innings, BOS (away) in top. 10 batters each
        # so the top-9 cut is exercised; usage decreasing by id.
        for team_is_home, ids in [(True, range(100, 110)), (False, range(200, 210))]:
            for k, bid in enumerate(ids):
                for _ in range(20 - k):  # earlier ids get more PAs
                    rows.append({
                        "batter": bid, "events": "single",
                        "inning_topbot": "Bot" if team_is_home else "Top",
                        "home_team": "NYY", "away_team": "BOS", "stand": "R",
                    })
        rosters = {lc.team_id: lc for lc in build_team_rosters(pd.DataFrame(rows), 2026)}
        assert set(rosters) == {"NYY", "BOS"}
        assert len(rosters["NYY"].batting_order) == 9
        assert rosters["NYY"].game_id == f"{ROSTER_GAME_ID}-2026"
        assert 100 in rosters["NYY"].batting_order  # most-used batter included
        assert 109 not in rosters["NYY"].batting_order  # least-used dropped
