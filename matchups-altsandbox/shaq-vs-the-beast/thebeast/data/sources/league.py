"""League-wide history from the MLB Stats API — seasons, not weeks.

Everything else in this app is per-player or per-game. This one deliberately
zooms all the way out: how much the whole league scored on a given day, going
back several seasons. That is what a trend needs to be measured against. A week
compared with the week before it is two small samples arguing; a week compared
with three seasons of the same calendar window is a claim worth printing.

Two endpoints, chosen for how much they return per call, because the alternative
is a boxscore fetch per game and roughly 2,400 games a season:

`/schedule` over a date range gives every final score at once, which is enough
for runs, winners and margins — the metrics with the deepest history.

`/teams/stats?stats=byDateRange` gives league counting stats for a window in one
call, summed across the thirty teams. Weekly buckets keep that to about 27 calls
a season while still being fine-grained enough to see a calendar effect.

Starter and bullpen workload are not here on purpose: no league-wide endpoint
splits innings by role, and inferring it would mean the per-game boxscore fetch
this module exists to avoid. Those metrics stay on our own graded record, and
the page says so rather than implying they have the same history behind them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

import requests

_MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# The regular season, near enough. Spring training and the postseason are
# different sports for these purposes — different rosters, different usage —
# and mixing them in would move the baselines for no good reason.
SEASON_START = (3, 20)
SEASON_END = (10, 5)


@dataclass
class LeagueDay:
    """One day of finished baseball, league-wide."""
    date: str
    games: int = 0
    runs: int = 0                  # both teams, summed over every game
    home_wins: int = 0
    one_run: int = 0
    blowouts: int = 0              # decided by five or more

    def merge(self, other: "LeagueDay") -> "LeagueDay":
        return LeagueDay(
            date=self.date, games=self.games + other.games,
            runs=self.runs + other.runs, home_wins=self.home_wins + other.home_wins,
            one_run=self.one_run + other.one_run,
            blowouts=self.blowouts + other.blowouts)


@dataclass
class LeagueWindow:
    """League counting stats over a date range, summed across all teams."""
    season: int
    start: str
    end: str
    games: int = 0                 # team-games; two per contest
    home_runs: int = 0
    strikeouts: int = 0
    walks: int = 0
    hits: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def _season_bounds(season: int) -> tuple[date, date]:
    return (date(season, *SEASON_START), date(season, *SEASON_END))


class MLBLeagueSource:
    """Fetches league-wide history. HTTP is isolated for test patching."""

    def _fetch_json(self, url: str, params: Optional[dict[str, Any]] = None) -> Any:
        # Generous timeouts: this runs in the scheduled job, never on a page
        # load, and a season of schedule is a big response.
        resp = requests.get(url, params=params, timeout=(5, 60))
        resp.raise_for_status()
        return resp.json()

    # ── daily results ───────────────────────────────────────────────────────

    def fetch_days(self, start: date, end: date) -> list[LeagueDay]:
        """Every final score between `start` and `end`, bucketed by date.

        The Stats API caps a schedule query at one season, so callers spanning a
        year boundary should split; `fetch_season_days` does that for you.
        """
        data = self._fetch_json(f"{_MLB_API_BASE}/schedule", params={
            "sportId": 1,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "gameType": "R",
        })
        out: dict[str, LeagueDay] = {}
        for entry in data.get("dates", []) or []:
            for game in entry.get("games", []) or []:
                parsed = self._parse_game(game, entry.get("date") or "")
                if parsed is None:
                    continue
                day, rec = parsed
                out[day] = out[day].merge(rec) if day in out else rec
        return [out[k] for k in sorted(out)]

    def _parse_game(self, game: dict[str, Any],
                    fallback_date: str) -> Optional[tuple[str, LeagueDay]]:
        if (game.get("status", {}) or {}).get("abstractGameState") != "Final":
            return None
        teams = game.get("teams") or {}
        home, away = teams.get("home") or {}, teams.get("away") or {}
        hs, as_ = home.get("score"), away.get("score")
        if hs is None or as_ is None:
            return None
        hs, as_ = int(hs), int(as_)
        # `officialDate` is the day the game counts for, which is not the
        # calendar day a game finishing after midnight ended on.
        day = game.get("officialDate") or fallback_date
        if not day:
            return None
        margin = abs(hs - as_)
        return day, LeagueDay(
            date=day, games=1, runs=hs + as_,
            home_wins=1 if hs > as_ else 0,
            one_run=1 if margin == 1 else 0,
            blowouts=1 if margin >= 5 else 0)

    def fetch_season_days(self, season: int,
                          through: Optional[date] = None) -> list[LeagueDay]:
        """A whole season of daily results, stopping at `through` if given."""
        start, end = _season_bounds(season)
        if through is not None and through < end:
            end = through
        if end < start:
            return []
        return self.fetch_days(start, end)

    # ── counting stats by window ────────────────────────────────────────────

    def fetch_window(self, season: int, start: date, end: date,
                     group: str = "hitting") -> LeagueWindow:
        """League totals for one date range, summed over the thirty teams."""
        data = self._fetch_json(f"{_MLB_API_BASE}/teams/stats", params={
            "sportId": 1, "season": season, "group": group,
            "stats": "byDateRange",
            "startDate": start.isoformat(), "endDate": end.isoformat(),
        })
        win = LeagueWindow(season=season, start=start.isoformat(),
                           end=end.isoformat())
        blocks = data.get("stats") or []
        splits = (blocks[0].get("splits") or []) if blocks else []
        for sp in splits:
            st = sp.get("stat") or {}
            win.games += _int(st.get("gamesPlayed"))
            win.home_runs += _int(st.get("homeRuns"))
            win.strikeouts += _int(st.get("strikeOuts"))
            win.walks += _int(st.get("baseOnBalls"))
            win.hits += _int(st.get("hits"))
        return win

    def fetch_season_windows(self, season: int, *, days: int = 7,
                             through: Optional[date] = None,
                             group: str = "hitting") -> list[LeagueWindow]:
        """The season in `days`-long buckets, skipping any that came back empty.

        Weekly is a compromise: fine enough that a calendar effect is visible,
        coarse enough that a season is under thirty calls.
        """
        start, end = _season_bounds(season)
        if through is not None and through < end:
            end = through
        out: list[LeagueWindow] = []
        cursor = start
        while cursor <= end:
            stop = min(cursor + timedelta(days=days - 1), end)
            win = self.fetch_window(season, cursor, stop, group=group)
            if win.games:
                out.append(win)
            cursor = stop + timedelta(days=1)
        return out


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
