"""Real per-player box score from the MLB Stats API.

GET /api/v1/game/{gamePk}/boxscore returns full batting/pitching lines for
every player who appeared, keyed by an opaque "IDxxxxx" player id per team.
Used for the matchup detail page's real (not simulated) game leaders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests

_MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


@dataclass
class BatterBoxLine:
    name: str
    player_id: Optional[int] = None
    position: Optional[str] = None
    # Real batting-order slot (1-9), from MLB's own `battingOrder` field — the
    # authoritative order, unlike at-bats which only correlates with it.
    lineup_slot: Optional[int] = None
    # Total trips to the plate. Summed over a team this gives the exact number
    # of batters who have hit, so (sum % 9) is the slot due up next — correct
    # even after pinch-hitters, unlike anything derived from at-bats alone.
    plate_appearances: Optional[int] = None
    at_bats: Optional[int] = None
    hits: Optional[int] = None
    home_runs: Optional[int] = None
    rbi: Optional[int] = None
    walks: Optional[int] = None
    strikeouts: Optional[int] = None


@dataclass
class PitcherBoxLine:
    name: str
    player_id: Optional[int] = None
    innings_pitched: Optional[str] = None
    # Real pitch count. Seeds the live sim so a starter already at 80
    # pitches is hooked on schedule rather than treated as fresh.
    pitches: Optional[int] = None
    hits_allowed: Optional[int] = None
    earned_runs: Optional[int] = None
    walks_allowed: Optional[int] = None
    strikeouts: Optional[int] = None


@dataclass
class TeamBoxscore:
    batters: list[BatterBoxLine]
    pitchers: list[PitcherBoxLine]


@dataclass
class GameBoxscore:
    game_id: str
    away: TeamBoxscore
    home: TeamBoxscore


def _ip_outs(ip: Any) -> Optional[int]:
    """Innings-pitched string to outs; "6.2" is six innings and two outs."""
    if ip is None:
        return None
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole or 0) * 3 + int(frac or 0)
    except (TypeError, ValueError):
        return None


def _batting_order_slot(raw: Any) -> Optional[int]:
    """MLB encodes lineup slot as a string like "100"/"200".../"900" (1st-9th),
    with in-game substitutions incrementing the last two digits (e.g. "101" =
    1st slot, first substitute) — dividing by 100 recovers the slot number
    regardless of substitution count.
    """
    try:
        return int(raw) // 100
    except (TypeError, ValueError):
        return None


class MLBBoxscoreSource:
    """Fetches the full per-player box score for one game."""

    def _fetch_json(self, url: str) -> Any:
        # Tight timeout: fires on every live-game page view/poll, so a
        # slow/unreachable host must fail fast, not hang the page.
        resp = requests.get(url, timeout=(3, 5))
        resp.raise_for_status()
        return resp.json()

    def fetch_boxscore(self, game_pk: int, game_id: str) -> Optional[GameBoxscore]:
        """Best-effort box score for one game; None if unreachable/malformed."""
        try:
            data = self._fetch_json(f"{_MLB_API_BASE}/game/{game_pk}/boxscore")
        except Exception:
            return None
        try:
            return self._parse(data, game_id)
        except (AttributeError, TypeError):
            return None

    def _parse_team(self, team_data: dict[str, Any]) -> TeamBoxscore:
        batters: list[BatterBoxLine] = []
        pitchers: list[PitcherBoxLine] = []
        players = team_data.get("players", {}) or {}
        for p in players.values():
            person = p.get("person", {}) or {}
            name = person.get("fullName")
            if not name:
                continue
            position = (p.get("position", {}) or {}).get("abbreviation")
            stats = p.get("stats", {}) or {}
            batting = stats.get("batting", {}) or {}
            pitching = stats.get("pitching", {}) or {}

            player_id = person.get("id")
            lineup_slot = _batting_order_slot(p.get("battingOrder"))

            if batting.get("atBats") is not None:
                batters.append(BatterBoxLine(
                    name=name, player_id=player_id, position=position,
                    lineup_slot=lineup_slot,
                    plate_appearances=batting.get("plateAppearances"),
                    at_bats=batting.get("atBats"), hits=batting.get("hits"),
                    home_runs=batting.get("homeRuns"), rbi=batting.get("rbi"),
                    walks=batting.get("baseOnBalls"), strikeouts=batting.get("strikeOuts"),
                ))
            if pitching.get("inningsPitched") is not None:
                pitchers.append(PitcherBoxLine(
                    name=name, player_id=player_id, innings_pitched=pitching.get("inningsPitched"),
                    pitches=pitching.get("numberOfPitches") or pitching.get("pitchesThrown"),
                    hits_allowed=pitching.get("hits"), earned_runs=pitching.get("earnedRuns"),
                    walks_allowed=pitching.get("baseOnBalls"), strikeouts=pitching.get("strikeOuts"),
                ))
        # `players` is a dict keyed by "IDnnnnnn", so iterating it yields no
        # meaningful order — but the side's `pitchers` array lists ids in the
        # order they appeared, which is the only place the starter is
        # identifiable. Anything the array doesn't mention keeps its position at
        # the end rather than being dropped.
        order = [i for i in (team_data.get("pitchers") or []) if i is not None]
        if order:
            rank = {int(pid): i for i, pid in enumerate(order)}
            pitchers.sort(key=lambda p: rank.get(
                int(p.player_id) if p.player_id is not None else -1, len(rank)))
        elif pitchers:
            # No order array — fall back to workload, since the starter is
            # almost always the one who pitched the most. It is an
            # approximation, but leaving dict order alone silently hands the
            # "starter" label to whichever reliever happened to sort first.
            pitchers.sort(key=lambda p: -(_ip_outs(p.innings_pitched) or 0))
        return TeamBoxscore(batters=batters, pitchers=pitchers)

    def _parse(self, data: dict[str, Any], game_id: str) -> GameBoxscore:
        teams = data.get("teams", {}) or {}
        return GameBoxscore(
            game_id=game_id,
            away=self._parse_team(teams.get("away", {}) or {}),
            home=self._parse_team(teams.get("home", {}) or {}),
        )
