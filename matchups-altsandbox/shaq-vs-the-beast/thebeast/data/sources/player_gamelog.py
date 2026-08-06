"""Per-game season log for one player from the MLB Stats API.

GET /api/v1/people/{personId}/stats?stats=gameLog&group=hitting|pitching&season=&sportId=1
returns one split per game the player has appeared in (chronological). Each
split carries that game's stat line, the opponent, and the gamePk.

Live tracking: today's in-progress game already shows up in the log with its
accumulating line; we cross-reference today's schedule once to flag which
entries are still live (and with what inning) so the player page can mark and
poll them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from typing import Any, Optional

import requests

_MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# MLB Stats API team id → the abbreviation the rest of this app uses.
_TEAM_ID_TO_ABBR: dict[int, str] = {
    108: "LAA", 109: "AZ", 110: "BAL", 111: "BOS", 112: "CHC", 113: "CIN",
    114: "CLE", 115: "COL", 116: "DET", 117: "HOU", 118: "KC", 119: "LAD",
    120: "WSH", 121: "NYM", 133: "ATH", 134: "PIT", 135: "SD", 136: "SEA",
    137: "SF", 138: "STL", 139: "TB", 140: "TEX", 141: "TOR", 142: "MIN",
    143: "PHI", 144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}


@dataclass
class GameLogEntry:
    date: str
    opponent: str
    is_home: bool
    game_pk: Optional[int]
    status: str = "Final"          # "Final" | "Live" | "Preview"
    inning: Optional[int] = None
    inning_half: Optional[str] = None
    stats: dict[str, Any] = field(default_factory=dict)


class MLBGameLogSource:
    """Fetches a player's per-game season log (hitting or pitching)."""

    def _fetch_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = requests.get(url, params=params, timeout=(3, 6))
        resp.raise_for_status()
        return resp.json()

    def _live_games(self) -> dict[int, dict[str, Any]]:
        """gamePk → {status, inning, inning_half} for today's non-final games."""
        today = _date.today().strftime("%Y-%m-%d")
        try:
            data = self._fetch_json(f"{_MLB_API_BASE}/schedule", params={
                "sportId": 1, "date": today, "hydrate": "linescore",
            })
        except Exception:
            return {}
        out: dict[int, dict[str, Any]] = {}
        for d in data.get("dates", []):
            for g in d.get("games", []):
                state = (g.get("status", {}) or {}).get("abstractGameState")
                if state not in ("Live", "Preview"):
                    continue
                ls = g.get("linescore", {}) or {}
                out[g.get("gamePk")] = {
                    "status": state,
                    "inning": ls.get("currentInning"),
                    "inning_half": ls.get("inningHalf"),
                }
        return out

    def fetch_game_log(self, player_id: int, season: int,
                       group: str = "hitting") -> list[GameLogEntry]:
        """Most-recent-first game log; empty list if unavailable/malformed."""
        try:
            data = self._fetch_json(
                f"{_MLB_API_BASE}/people/{player_id}/stats",
                params={"stats": "gameLog", "group": group,
                        "season": season, "sportId": 1},
            )
        except Exception:
            return []
        try:
            return self._parse(data, group)
        except (AttributeError, TypeError, KeyError):
            return []

    def _parse(self, data: dict[str, Any], group: str) -> list[GameLogEntry]:
        stat_blocks = data.get("stats", []) or []
        if not stat_blocks:
            return []
        splits = stat_blocks[0].get("splits", []) or []
        live = self._live_games() if splits else {}

        entries: list[GameLogEntry] = []
        for sp in splits:
            game_pk = (sp.get("game", {}) or {}).get("gamePk")
            opp = sp.get("opponent", {}) or {}
            opp_abbr = _TEAM_ID_TO_ABBR.get(opp.get("id"), opp.get("abbreviation") or "")
            st = sp.get("stat", {}) or {}
            entry = GameLogEntry(
                date=sp.get("date", ""),
                opponent=opp_abbr,
                is_home=bool(sp.get("isHome", False)),
                game_pk=game_pk,
                stats=_hitting_line(st) if group == "hitting" else _pitching_line(st),
            )
            live_info = live.get(game_pk)
            if live_info is not None:
                entry.status = live_info["status"]
                entry.inning = live_info.get("inning")
                entry.inning_half = live_info.get("inning_half")
            entries.append(entry)

        entries.reverse()  # most recent first
        return entries


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _hitting_line(st: dict[str, Any]) -> dict[str, Any]:
    return {
        "ab": _int(st.get("atBats")), "r": _int(st.get("runs")),
        "h": _int(st.get("hits")), "2b": _int(st.get("doubles")),
        "3b": _int(st.get("triples")), "hr": _int(st.get("homeRuns")),
        "rbi": _int(st.get("rbi")), "bb": _int(st.get("baseOnBalls")),
        "k": _int(st.get("strikeOuts")), "sb": _int(st.get("stolenBases")),
    }


def _pitching_line(st: dict[str, Any]) -> dict[str, Any]:
    return {
        "ip": st.get("inningsPitched"), "h": _int(st.get("hits")),
        "r": _int(st.get("runs")), "er": _int(st.get("earnedRuns")),
        "bb": _int(st.get("baseOnBalls")), "k": _int(st.get("strikeOuts")),
        "hr": _int(st.get("homeRuns")),
    }
