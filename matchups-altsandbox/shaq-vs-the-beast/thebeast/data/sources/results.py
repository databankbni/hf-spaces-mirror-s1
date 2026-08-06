"""Actual game results source — final scores from the MLB Stats API.

Provides the ground truth for calibration and the MVP backtest gate: who won
each holdout game. No betting odds (the Stats API does not carry them); pair
these records with a closing-line source to build full GameOutcomes.

External HTTP is isolated in `_fetch_json` for test patching.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

import requests

_MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


@dataclass
class GameResultRecord:
    """Final result for one completed game."""
    game_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    home_won: bool


class MLBResultsSource:
    """Fetches final scores from the MLB Stats API schedule endpoint."""

    def _fetch_json(self, url: str, params: Optional[dict[str, Any]] = None) -> Any:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def fetch_results(self, game_date: date) -> list[GameResultRecord]:
        """Return final results for every completed game on `game_date`."""
        data = self._fetch_json(f"{_MLB_API_BASE}/schedule", params={
            "sportId": 1,
            "date": game_date.strftime("%Y-%m-%d"),
            "hydrate": "team,linescore",
        })
        results: list[GameResultRecord] = []
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                record = self._parse_result(game)
                if record is not None:
                    results.append(record)
        return results

    def _parse_result(self, game: dict[str, Any]) -> Optional[GameResultRecord]:
        status = game.get("status", {}).get("abstractGameState")
        if status != "Final":
            return None
        teams = game["teams"]
        home = teams["home"]
        away = teams["away"]
        home_abbr = home["team"]["abbreviation"]
        away_abbr = away["team"]["abbreviation"]
        home_score = int(home.get("score", 0))
        away_score = int(away.get("score", 0))

        date_str = game.get("gameDate", "")
        try:
            game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            game_date = date.today()
        game_id = f"{game_date.isoformat()}-{away_abbr}-{home_abbr}"

        return GameResultRecord(
            game_id=game_id,
            home_team=home_abbr,
            away_team=away_abbr,
            home_score=home_score,
            away_score=away_score,
            home_won=home_score > away_score,
        )
