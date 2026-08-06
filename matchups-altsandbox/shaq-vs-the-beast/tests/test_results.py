"""Tests for the actual-game-results source (final scores from MLB Stats API).

HTTP is isolated in `_fetch_json`; tests patch it with a synthetic payload.
"""
from __future__ import annotations

from datetime import date

import pytest

from thebeast.data.sources.results import GameResultRecord, MLBResultsSource


def _payload() -> dict:
    return {
        "dates": [
            {
                "games": [
                    {
                        "gamePk": 1,
                        "gameDate": "2024-04-01T17:10:00Z",
                        "status": {"abstractGameState": "Final"},
                        "teams": {
                            "home": {"team": {"abbreviation": "BOS"}, "score": 5},
                            "away": {"team": {"abbreviation": "NYY"}, "score": 3},
                        },
                    },
                    {
                        "gamePk": 2,
                        "gameDate": "2024-04-01T20:05:00Z",
                        "status": {"abstractGameState": "Final"},
                        "teams": {
                            "home": {"team": {"abbreviation": "LAD"}, "score": 1},
                            "away": {"team": {"abbreviation": "SFG"}, "score": 4},
                        },
                    },
                    {
                        "gamePk": 3,
                        "gameDate": "2024-04-01T23:00:00Z",
                        "status": {"abstractGameState": "Preview"},  # not final
                        "teams": {
                            "home": {"team": {"abbreviation": "CHC"}, "score": 0},
                            "away": {"team": {"abbreviation": "STL"}, "score": 0},
                        },
                    },
                ]
            }
        ]
    }


@pytest.fixture
def source(monkeypatch) -> MLBResultsSource:
    src = MLBResultsSource()
    monkeypatch.setattr(src, "_fetch_json", lambda url, params=None: _payload())
    return src


class TestFetchResults:
    def test_returns_only_final_games(self, source: MLBResultsSource) -> None:
        results = source.fetch_results(date(2024, 4, 1))
        assert len(results) == 2  # Preview game excluded

    def test_home_win_flag(self, source: MLBResultsSource) -> None:
        results = {r.game_id: r for r in source.fetch_results(date(2024, 4, 1))}
        bos = results["2024-04-01-NYY-BOS"]
        assert isinstance(bos, GameResultRecord)
        assert bos.home_won is True
        assert bos.home_score == 5 and bos.away_score == 3

    def test_away_win_flag(self, source: MLBResultsSource) -> None:
        results = {r.game_id: r for r in source.fetch_results(date(2024, 4, 1))}
        lad = results["2024-04-01-SFG-LAD"]
        assert lad.home_won is False

    def test_game_id_format(self, source: MLBResultsSource) -> None:
        ids = {r.game_id for r in source.fetch_results(date(2024, 4, 1))}
        assert "2024-04-01-NYY-BOS" in ids
