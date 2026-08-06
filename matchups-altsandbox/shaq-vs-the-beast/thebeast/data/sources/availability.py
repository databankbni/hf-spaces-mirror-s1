"""Who can actually play tonight, from the MLB Stats API roster.

Projected batting orders are built from season usage — each team's nine
most-used hitters. That is a good guess about *who bats* and says nothing at
all about *who is available*, so a player who tore something in July stayed in
the projected lineup, kept getting a statline simulated, and kept turning up in
the ranked plays as though he were going to hit.

**The active roster is the check.** It is the complete, authoritative list of
players eligible to appear tonight; anyone on the injured list, optioned to the
minors, or traded away is simply not on it. So the test is membership, not
status-code parsing — a projected hitter who is not on his team's active roster
cannot play, whatever the reason, and whatever new status codes MLB invents.

The reason he's out is a nicer thing to *show* than to rely on, so it's fetched
separately, lazily, and only when somebody is actually missing. If that second
call fails the player still comes out of the lineup; he just comes out without a
label.

Two deliberate biases, both toward leaving lineups alone:

**A short roster is not trusted.** An active roster is 26 players. A response
that parses but yields eight of them is a broken response, not a decimated club,
and acting on it would empty every lineup on the slate. Below `MIN_ROSTER` the
answer is "don't know", which changes nothing.

**Never blocks.** Unreachable source, bad JSON, timeout — the lineup goes
through untouched, which is exactly the behaviour before this existed.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

import requests

_TEAMS_URL = "https://statsapi.mlb.com/api/v1/teams"
_ROSTER_URL = "https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"

# Rosters move daily, not hourly — an activation or an IL placement is news for
# the day. Half an hour keeps a slate's worth of simulations to one call per
# team while still picking up an afternoon move before first pitch.
TTL_SECONDS = 1800.0

# How long to leave a failing source alone. Without this, every simulation on
# the slate retries a host that is down — thirty teams, once per game — and the
# warm-up wears its connect timeout thirty times over instead of once.
RETRY_AFTER_SECONDS = 120.0

# An active roster is 26. Anything under this is a malformed answer rather than
# a real club, and must not be read as "these are the only men available".
MIN_ROSTER = 20

# Status codes worth naming when we say who's out. Only ever used for the label
# — availability itself comes from active-roster membership, so an unrecognised
# code costs a nice string, not a correct answer.
_REASONS = {
    "D7": "7-day injured list", "D10": "10-day injured list",
    "D15": "15-day injured list", "D60": "60-day injured list",
    "DL": "disabled list", "BRV": "bereavement list", "PL": "paternity leave",
    "FMD": "family medical leave", "RM": "restricted list", "SU": "suspended",
    "MIN": "in the minors", "RES": "reserve list", "DES": "designated for assignment",
}


class TeamRoster:
    """One team's active roster, plus labels for anyone notable who isn't on it."""

    def __init__(self, active: set[int], reasons: Optional[dict[int, str]] = None,
                 fetched_at: Optional[float] = None) -> None:
        self.active = active
        self.reasons = reasons or {}
        self.fetched_at = fetched_at or time.time()

    @property
    def usable(self) -> bool:
        """False when we don't actually know who's available.

        A failed fetch and a genuinely empty roster are indistinguishable
        downstream and must not be: treating a failure as "nobody can play"
        would empty every lineup on the slate.
        """
        return len(self.active) >= MIN_ROSTER

    def can_play(self, player_id: int) -> bool:
        return player_id in self.active

    def why_out(self, player_id: int) -> str:
        return self.reasons.get(player_id) or "not on the active roster"


_UNKNOWN = TeamRoster(set())


class MLBAvailabilitySource:
    """Active-roster membership by team abbreviation, cached with a TTL."""

    # Shared across instances: the ids never change, and the roster is the same
    # for every caller asking about the same team in the same half hour.
    _team_ids: dict[str, int] = {}
    _team_ids_at: float = 0.0
    _cache: dict[str, tuple[float, TeamRoster]] = {}
    _failed_at: dict[str, float] = {}
    _lock = threading.Lock()

    def _get(self, url: str, params: dict) -> Any:
        # Tight timeout: this sits in front of a simulation that a page is
        # waiting on, so a slow host has to fail fast rather than hold it up.
        resp = requests.get(url, params=params, timeout=(3, 6))
        resp.raise_for_status()
        return resp.json()

    def _recently_failed(self, key: str) -> bool:
        with self._lock:
            when = self._failed_at.get(key)
        return when is not None and time.time() - when < RETRY_AFTER_SECONDS

    def _note_failure(self, key: str) -> None:
        with self._lock:
            self._failed_at[key] = time.time()

    def team_ids(self) -> dict[str, int]:
        """{abbreviation: MLB team id}. Cached for a day."""
        with self._lock:
            if self._team_ids and time.time() - self._team_ids_at < 86_400:
                return dict(self._team_ids)
        if self._recently_failed("__teams__"):
            return {}
        try:
            data = self._get(_TEAMS_URL, {"sportId": 1})
            found = {}
            for t in data.get("teams", []) or []:
                abbr, tid = t.get("abbreviation"), t.get("id")
                if abbr and tid is not None:
                    found[str(abbr).upper()] = int(tid)
        except Exception:
            self._note_failure("__teams__")
            return {}
        if not found:
            self._note_failure("__teams__")
            return {}
        with self._lock:
            MLBAvailabilitySource._team_ids = found
            MLBAvailabilitySource._team_ids_at = time.time()
        return dict(found)

    def _ids_from(self, data: Any) -> set[int]:
        found = set()
        for entry in (data or {}).get("roster", []) or []:
            try:
                found.add(int((entry.get("person") or {}).get("id")))
            except (TypeError, ValueError):
                continue
        return found

    def roster(self, team: str) -> TeamRoster:
        """Who on `team` can play tonight.

        Returns an unusable roster — not an empty one — when the source can't be
        reached or answers implausibly, so the caller can tell "everyone is
        available" from "we don't know".
        """
        abbr = (team or "").strip().upper()
        if not abbr:
            return _UNKNOWN
        now = time.time()
        with self._lock:
            hit = self._cache.get(abbr)
            if hit is not None and now - hit[0] < TTL_SECONDS:
                return hit[1]
        if self._recently_failed(abbr):
            return _UNKNOWN

        team_id = self.team_ids().get(abbr)
        if team_id is None:
            self._note_failure(abbr)
            return _UNKNOWN
        try:
            data = self._get(_ROSTER_URL.format(team_id=team_id),
                             {"rosterType": "active"})
        except Exception:
            self._note_failure(abbr)
            return _UNKNOWN

        roster = TeamRoster(self._ids_from(data), fetched_at=now)
        if not roster.usable:
            self._note_failure(abbr)
            return _UNKNOWN
        with self._lock:
            self._cache[abbr] = (now, roster)
        return roster

    def label_absences(self, team: str, player_ids: list[int]) -> dict[int, str]:
        """Why these players aren't on the active roster. Best-effort.

        A second call, made only once somebody is actually missing — which is
        rare — so the common path stays at one request per team. A failure here
        costs a nice string and nothing else: the player is already out on
        active-roster membership alone.
        """
        wanted = set(player_ids)
        if not wanted:
            return {}
        abbr = (team or "").strip().upper()
        cached = self._cache.get(abbr)
        if cached and all(pid in cached[1].reasons for pid in wanted):
            return {pid: cached[1].reasons[pid] for pid in wanted}

        team_id = self.team_ids().get(abbr)
        if team_id is None or self._recently_failed(f"{abbr}__why"):
            return {}
        try:
            data = self._get(_ROSTER_URL.format(team_id=team_id),
                             {"rosterType": "fullRoster"})
        except Exception:
            self._note_failure(f"{abbr}__why")
            return {}

        found: dict[int, str] = {}
        for entry in (data or {}).get("roster", []) or []:
            try:
                pid = int((entry.get("person") or {}).get("id"))
            except (TypeError, ValueError):
                continue
            if pid not in wanted:
                continue
            status = entry.get("status") or {}
            code = str(status.get("code") or "").strip().upper()
            description = str(status.get("description") or "").strip()
            found[pid] = _REASONS.get(code) or description or "not on the active roster"
        if cached:
            cached[1].reasons.update(found)
        return found

    def injury_report(self, team: str) -> list[dict]:
        """Everyone on the 40-man who isn't active, with why. Best-effort.

        This is the report rather than the mechanism — availability is settled
        by active-roster membership, which already covers every list MLB keeps
        (7/10/15/60-day injured, bereavement, paternity, family medical,
        restricted, suspended, optioned) because a player on any of them is off
        the active roster by definition. This exists so that can be *seen*
        rather than trusted.
        """
        abbr = (team or "").strip().upper()
        team_id = self.team_ids().get(abbr)
        if team_id is None or self._recently_failed(f"{abbr}__why"):
            return []
        try:
            data = self._get(_ROSTER_URL.format(team_id=team_id),
                             {"rosterType": "fullRoster"})
        except Exception:
            self._note_failure(f"{abbr}__why")
            return []

        active = self.roster(abbr)
        report: list[dict] = []
        for row in (data or {}).get("roster", []) or []:
            person = row.get("person") or {}
            try:
                pid = int(person.get("id"))
            except (TypeError, ValueError):
                continue
            if active.usable and active.can_play(pid):
                continue
            status = row.get("status") or {}
            code = str(status.get("code") or "").strip().upper()
            report.append({
                "player_id": pid,
                "name": person.get("fullName") or str(pid),
                "status_code": code,
                "reason": _REASONS.get(code) or str(status.get("description")
                                                    or "not on the active roster"),
            })
        return sorted(report, key=lambda r: r["name"])

    def diagnose(self, team: str) -> dict:
        """What this source can see right now — for the availability probe.

        The filtering is invisible when it works and invisible when it doesn't,
        and this app can't reach statsapi from every environment it's developed
        in. This makes the difference inspectable from wherever it *is* running,
        rather than inferred from a lineup that looks wrong.
        """
        abbr = (team or "").strip().upper()
        out: dict = {"team": abbr}
        try:
            ids = self.team_ids()
            out["teams_endpoint"] = "ok" if ids else "unreachable"
            out["team_id"] = ids.get(abbr)
        except Exception as exc:
            out["teams_endpoint"] = f"error: {type(exc).__name__}"
            return out
        roster = self.roster(abbr)
        out["active_roster_size"] = len(roster.active)
        out["usable"] = roster.usable
        out["min_roster"] = MIN_ROSTER
        if not roster.usable:
            out["effect"] = "no filtering — lineups pass through unchanged"
        else:
            out["effect"] = "filtering active"
        return out

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._cache.clear()
            cls._failed_at.clear()
            cls._team_ids = {}
            cls._team_ids_at = 0.0
