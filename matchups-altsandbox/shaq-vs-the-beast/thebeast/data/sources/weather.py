"""Per-game weather from the MLB Stats API (schedule weather hydrate).

The schedule endpoint hydrates weather in one call per date:
``{'condition': 'Sunny', 'temp': '69', 'wind': '8 mph, Out To CF'}``. We parse
temperature and the wind (mph + direction) into WeatherConditions, keyed by the
same ``{date}-{away}-{home}`` game_id the schedule source uses.

HTTP is isolated in ``_fetch_json`` for test patching.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import requests

from ..models import WeatherConditions
from ..park_factors import wind_description_to_deg

_MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


def _parse_wind(wind: str) -> tuple[Optional[float], Optional[float]]:
    """'8 mph, Out To CF' → (8.0, 0.0 deg). Returns (mph, dir_deg)."""
    if not wind:
        return None, None
    parts = wind.split(",", 1)
    mph: Optional[float] = None
    try:
        mph = float(parts[0].strip().split()[0])
    except (ValueError, IndexError):
        mph = None
    desc = parts[1].strip() if len(parts) > 1 else None
    deg = wind_description_to_deg(desc) if desc else None
    return mph, deg


class MLBWeatherSource:
    """Fetches game weather and writes WeatherConditions to the repository."""

    def __init__(self, repo) -> None:
        self._repo = repo

    def _fetch_json(self, url: str, params: Optional[dict[str, Any]] = None) -> Any:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def fetch_weather(self, game_date: date) -> list[WeatherConditions]:
        data = self._fetch_json(f"{_MLB_API_BASE}/schedule", params={
            "sportId": 1,
            "date": game_date.strftime("%Y-%m-%d"),
            "hydrate": "team,weather",
        })
        out: list[WeatherConditions] = []
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                wc = self._parse(game)
                if wc is not None:
                    self._repo.save_weather(wc)
                    out.append(wc)
        return out

    def _parse(self, game: dict[str, Any]) -> Optional[WeatherConditions]:
        weather = game.get("weather") or {}
        if not weather:
            return None
        teams = game["teams"]
        home_abbr = teams["home"]["team"]["abbreviation"]
        away_abbr = teams["away"]["team"]["abbreviation"]
        date_str = game.get("gameDate", "")
        try:
            gdate = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            gdate = date.today()
        game_id = f"{gdate.isoformat()}-{away_abbr}-{home_abbr}"

        try:
            temp_f = float(weather["temp"]) if weather.get("temp") else None
        except (ValueError, TypeError):
            temp_f = None
        mph, deg = _parse_wind(weather.get("wind", ""))

        return WeatherConditions(
            game_id=game_id,
            temperature_f=temp_f if temp_f is not None else 70.0,
            wind_mph=mph if mph is not None else 0.0,
            wind_direction_deg=deg if deg is not None else 90.0,
            humidity_pct=50.0,
        )
