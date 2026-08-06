"""MLB Stats API schedule and lineup source.

External HTTP calls are isolated in `_fetch_json` for test patching.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import requests

from ..models import GameSchedule, LineupCard
from ..repository import SQLiteRepository

_MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

_VENUE_SLUGS: dict[int, str] = {
    3:    "fenway",
    1:    "yankee-stadium",
    2:    "camden-yards",
    4:    "tropicana",
    5:    "progressive",
    31:   "globe-life",
    680:  "dodger-stadium",
    2392: "oracle-park",
}


class MLBScheduleSource:
    """Fetches game schedules and lineup cards from the MLB Stats API."""

    def __init__(self, repo: SQLiteRepository) -> None:
        self._repo = repo

    def _fetch_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        # (connect, read) timeouts kept tight — this fires on every page load of
        # the live slate, so a slow/unreachable host must fail fast, not hang.
        resp = requests.get(url, params=params, timeout=(3, 5))
        resp.raise_for_status()
        return resp.json()

    def fetch_schedule(self, game_date: date) -> list[GameSchedule]:
        """Fetch all games for `game_date` and write to repository."""
        url = f"{_MLB_API_BASE}/schedule"
        data = self._fetch_json(url, params={
            "sportId": 1,
            "date": game_date.strftime("%Y-%m-%d"),
            "hydrate": "team,venue,probablePitcher,lineups,linescore",
        })
        schedules: list[GameSchedule] = []
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                schedule = self._parse_schedule(game, game_date)
                self._repo.save_schedule(schedule)
                schedules.append(schedule)
                self._maybe_save_lineups(game, game_date)
        return schedules

    def _game_id(self, game: dict[str, Any], game_date: date) -> str:
        """Unique id per game. Doubleheaders repeat date/teams, so games after
        the first get a "-g{N}" suffix (game 1 keeps the plain id, so single
        games and existing ids are unchanged). MLB's `gameNumber` is 1 or 2."""
        teams = game["teams"]
        away = teams["away"]["team"]["abbreviation"]
        home = teams["home"]["team"]["abbreviation"]
        base = f"{game_date.isoformat()}-{away}-{home}"
        try:
            num = int(game.get("gameNumber", 1) or 1)
        except (TypeError, ValueError):
            num = 1
        return f"{base}-g{num}" if num > 1 else base

    def _parse_schedule(self, game: dict[str, Any], game_date: date) -> GameSchedule:
        game_pk = game["gamePk"]
        teams = game["teams"]
        home = teams["home"]["team"]
        away = teams["away"]["team"]
        venue_id = _VENUE_SLUGS.get(game.get("venue", {}).get("id", 0),
                                     str(game.get("venue", {}).get("id", "unknown")))
        date_str = game.get("gameDate", "")
        try:
            first_pitch = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            first_pitch = None

        # `game_date` is the schedule day MLB itself filed this game under
        # (the date we queried for) — not derived from first_pitch, which is
        # a UTC timestamp that can roll onto the next calendar day for
        # evening games and would otherwise mis-bucket the game by a day.
        game_id = self._game_id(game, game_date)

        status = game.get("status", {}) or {}
        linescore = game.get("linescore", {}) or {}

        return GameSchedule(
            game_id=game_id,
            date=game_date,
            home_team_id=home["abbreviation"],
            away_team_id=away["abbreviation"],
            venue_id=venue_id,
            first_pitch=first_pitch,
            game_pk=game_pk,
            status=status.get("abstractGameState"),
            detailed_state=status.get("detailedState"),
            home_score=teams["home"].get("score"),
            away_score=teams["away"].get("score"),
            inning=linescore.get("currentInning"),
            inning_half=linescore.get("inningHalf"),
        )

    def _maybe_save_lineups(self, game: dict[str, Any], game_date: date) -> None:
        teams = game["teams"]
        home_abbr = teams["home"]["team"]["abbreviation"]
        away_abbr = teams["away"]["team"]["abbreviation"]
        game_id = self._game_id(game, game_date)
        lineups = game.get("lineups", {}) or {}

        for side, abbr, key in [("homePlayers", home_abbr, "home"),
                                ("awayPlayers", away_abbr, "away")]:
            players = lineups.get(side, [])
            prob = teams[key].get("probablePitcher") or {}
            starter_id = prob.get("id")
            if players:
                player_ids = [p["id"] for p in players][:9]
                confirmed = True
            elif starter_id is not None:
                # Pre-lineup upcoming game: keep the real probable starter; use
                # placeholder batters (→ league-average offense in the sim).
                base = 9_000_000 + (100 if key == "home" else 200)
                player_ids = list(range(base, base + 9))
                confirmed = False
            else:
                continue  # nothing useful to store yet
            if starter_id is None:
                # A posted batting order with no probable pitcher named yet.
                # This used to discard the whole card, which threw away the one
                # thing that is actually confirmed — the nine hitters — because
                # the pitcher hadn't been announced. Zero is the sentinel the
                # rest of the app already reads as "starter not yet announced".
                if not confirmed:
                    continue
                starter_id = 0
            existing = self._repo.get_lineup(game_id, abbr)
            if (existing is not None and existing.confirmed and not confirmed):
                # Never let a later poll downgrade a posted lineup back to
                # placeholders — MLB drops `lineups` from the payload once a
                # game goes final, and overwriting would lose the real card.
                continue
            self._repo.save_lineup(LineupCard(
                game_id=game_id, team_id=abbr, batting_order=player_ids,
                starter_id=starter_id, bullpen_ids=[], confirmed=confirmed,
                confirmed_at=datetime.now(timezone.utc) if confirmed else None,
            ))
