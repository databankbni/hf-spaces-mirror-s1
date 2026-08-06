"""Live linescore + box score detail from the MLB Stats API.

GET /api/v1/game/{gamePk}/linescore returns per-inning runs/hits/errors for
both teams, team totals, and — only while the game is actually in progress —
the live situation (balls/strikes/outs, runners on base, current batter and
pitcher). Once a game is Final, the situational fields are simply absent;
callers should treat an all-None GameSituation as "nothing to show."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import requests

_MLB_API_BASE = "https://statsapi.mlb.com/api/v1"


@dataclass
class InningLine:
    num: int
    away_runs: Optional[int] = None
    home_runs: Optional[int] = None


@dataclass
class TeamTotals:
    runs: Optional[int] = None
    hits: Optional[int] = None
    errors: Optional[int] = None
    left_on_base: Optional[int] = None


@dataclass
class GameSituation:
    """Balls/strikes/outs and baserunners — meaningful only while live."""
    balls: Optional[int] = None
    strikes: Optional[int] = None
    outs: Optional[int] = None
    on_first: bool = False
    on_second: bool = False
    on_third: bool = False
    batter: Optional[str] = None
    pitcher: Optional[str] = None


@dataclass
class GameLinescore:
    game_id: str
    innings: list[InningLine] = field(default_factory=list)
    away_totals: TeamTotals = field(default_factory=TeamTotals)
    home_totals: TeamTotals = field(default_factory=TeamTotals)
    situation: GameSituation = field(default_factory=GameSituation)
    # Where the game currently stands. `inning_state` is MLB's own label:
    # "Top"/"Bottom" while a half is being played, "Middle" between the top and
    # bottom of an inning, and "End" once the bottom is over — the resume-point
    # logic needs that distinction, since Middle/End mean the next half starts
    # clean (no outs, empty bases) rather than continuing the current one.
    current_inning: Optional[int] = None
    is_top_inning: Optional[bool] = None
    inning_state: Optional[str] = None


class MLBLinescoreSource:
    """Fetches the per-game linescore (box score + live situation)."""

    def _fetch_json(self, url: str) -> Any:
        # Tight timeout: fires on every live-game page view/poll, so a
        # slow/unreachable host must fail fast, not hang the page.
        resp = requests.get(url, timeout=(3, 5))
        resp.raise_for_status()
        return resp.json()

    def fetch_linescore(self, game_pk: int, game_id: str) -> Optional[GameLinescore]:
        """Best-effort linescore for one game; None if unreachable/malformed."""
        try:
            data = self._fetch_json(f"{_MLB_API_BASE}/game/{game_pk}/linescore")
        except Exception:
            return None
        try:
            return self._parse(data, game_id)
        except (AttributeError, TypeError):
            return None

    def _parse(self, data: dict[str, Any], game_id: str) -> GameLinescore:
        innings: list[InningLine] = []
        for inn in data.get("innings", []) or []:
            innings.append(InningLine(
                num=inn.get("num", 0),
                away_runs=(inn.get("away") or {}).get("runs"),
                home_runs=(inn.get("home") or {}).get("runs"),
            ))

        teams = data.get("teams", {}) or {}
        away_t = teams.get("away", {}) or {}
        home_t = teams.get("home", {}) or {}

        offense = data.get("offense", {}) or {}
        defense = data.get("defense", {}) or {}
        situation = GameSituation(
            balls=data.get("balls"),
            strikes=data.get("strikes"),
            outs=data.get("outs"),
            on_first="first" in offense,
            on_second="second" in offense,
            on_third="third" in offense,
            batter=(offense.get("batter") or {}).get("fullName"),
            pitcher=(defense.get("pitcher") or {}).get("fullName"),
        )

        return GameLinescore(
            game_id=game_id,
            innings=innings,
            current_inning=data.get("currentInning"),
            is_top_inning=data.get("isTopInning"),
            inning_state=data.get("inningState"),
            away_totals=TeamTotals(
                runs=away_t.get("runs"), hits=away_t.get("hits"),
                errors=away_t.get("errors"), left_on_base=away_t.get("leftOnBase"),
            ),
            home_totals=TeamTotals(
                runs=home_t.get("runs"), hits=home_t.get("hits"),
                errors=home_t.get("errors"), left_on_base=home_t.get("leftOnBase"),
            ),
            situation=situation,
        )
