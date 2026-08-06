"""Real sportsbook odds from ESPN's public (undocumented) scoreboard API.

No API key required, but the schema is unofficial and can drift — every
field access below is defensive (missing/None → the caller gets a partial
or empty MarketLines rather than an exception).

Endpoint: GET .../scoreboard?dates=YYYYMMDD returns one `event` per game for
that date; each event's `competitions[0].odds[0]` (when present — odds are
posted a few days out and pulled once a game starts) holds, per a real
captured response (verified against ESPN's live DraftKings feed):

    {
      "provider": {"name": "DraftKings"},
      "overUnder": 10.0,
      "moneyline": {
        "home": {"close": {"odds": "+135"}},
        "away": {"close": {"odds": "-163"}}
      },
      "pointSpread": {
        "home": {"close": {"line": "+1.5"}},
        "away": {"close": {"line": "-1.5"}}
      }
    }

Moneyline and spread values are strings with an explicit sign (e.g. "+135",
"-1.5") under `.close`, not the `homeTeamOdds.moneyLine` shape an earlier
version of this module assumed and which doesn't actually exist on the real
payload — `homeTeamOdds`/`awayTeamOdds` only carry favorite/underdog flags
and team identity, not the odds values themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import requests

_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
# ESPN drops the scoreboard `odds` node at first pitch, but the game-summary
# `pickcenter` keeps live-updating lines (and opening values) through the game.
_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary"
# ESPN's core API. The summary endpoint's `pickcenter` carries the *pregame*
# market — its flat `overUnder`/`moneyLine` stay on the closing number all game,
# which is how a team leading by two in the 7th was still being shown at -136
# instead of the -700 ESPN's own live odds tab was quoting. The live market
# lives here instead, under each provider's `current` node.
# Slate enrichment runs per live game against a shared budget, so its calls use
# a tighter timeout than the single-game path — and the budget has to be able
# to afford *both* of them for at least one game. Sizing the reservation off
# the default (3, 5) timeout instead made the fallback unreachable: 8s could
# never fit in a 6s budget, so whenever the live feed came back unusable the
# pickcenter fallback was skipped and live games showed no odds at all.
_ENRICH_TIMEOUT = (1.5, 2.5)
_ENRICH_WORST_CASE = 4.0
# Two enrichment calls (live feed, then fallback) plus headroom, well inside
# the 12s at which the matchups list abandons the request.
_ENRICH_BUDGET = 9.0
_CORE_ODDS_URL = (
    "https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb"
    "/events/{event_id}/competitions/{event_id}/odds"
)

# ESPN abbreviates Arizona differently than the MLB Stats API (which the
# rest of this app follows: WSH, CWS, KC, SD, SF, TB match on both sides
# and need no translation — verified against real ingested game_ids).
_ESPN_TO_INTERNAL_ABBR: dict[str, str] = {
    "ARI": "AZ",
}


def _normalize_abbr(abbr: str) -> str:
    abbr = abbr.upper()
    return _ESPN_TO_INTERNAL_ABBR.get(abbr, abbr)


@dataclass
class MarketLines:
    """Real moneyline/spread/total for one game, from whichever book ESPN surfaces first.

    The base fields are the *current* line (the live number during a game, the
    pregame line before it starts). When `is_live` is true the `*_open` fields
    carry the opening line so the UI can show both, live most prominent.
    """
    game_id: str
    provider: Optional[str] = None
    home_ml: Optional[int] = None
    away_ml: Optional[int] = None
    home_spread: Optional[float] = None  # favorite's line is negative
    away_spread: Optional[float] = None
    home_spread_odds: Optional[int] = None  # American price laid to take that run line
    away_spread_odds: Optional[int] = None
    total: Optional[float] = None
    is_live: bool = False
    # Opening line (populated from pickcenter, mainly for live games).
    home_ml_open: Optional[int] = None
    away_ml_open: Optional[int] = None
    home_spread_open: Optional[float] = None
    away_spread_open: Optional[float] = None
    total_open: Optional[float] = None
    # When this line was pulled from the source (UTC, ISO). Every response is
    # fetched live — nothing here is cached — so this doubles as proof of that
    # rather than a claim the UI has to take on trust.
    fetched_at: Optional[str] = None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ESPNOddsSource:
    """Fetches real pre-game betting lines for one MLB game from ESPN."""

    # game_id -> ESPN event id, process-wide. A live game's odds are refreshed
    # every ~20s from the page; without this, each refresh would re-run the
    # whole scoreboard probe (up to 3 requests) just to re-derive an id that
    # doesn't change for the life of the game, roughly doubling the latency
    # (and failure surface) of every poll for no reason. Small and unbounded,
    # like any other request-scoped/process-lifetime cache — a season's worth
    # of game_ids is a few thousand short strings.
    _event_id_cache: dict[str, Any] = {}
    # game_id -> (state, recorded_at). The warm path has to know whether a game
    # is under way: a live one should be upgraded to its in-game market, a
    # pregame one must not pay for a request that can only fail. The timestamp
    # expires the answer so a game that starts is noticed rather than served a
    # pregame line for the rest of the night.
    _event_state_cache: dict[str, tuple[str, float]] = {}
    _STATE_TTL_SECONDS = 90.0

    # The core odds API is an *enrichment*: it upgrades a pregame line to a
    # live one. It must never be able to cost us the baseline. When it fails —
    # blocked, 404 for a game with no live market, or just slow — that answer
    # is remembered for a cooldown, so a slate with five live games pays the
    # timeout once instead of five times. Without this the extra calls pushed
    # /api/odds-slate past the client's 12s abort and *every* game lost its
    # odds, including the pregame ones that were never in question.
    _core_unavailable_until: float = 0.0
    _CORE_COOLDOWN_SECONDS = 120.0

    def _fetch_json(self, url: str, params: dict[str, Any] | None = None,
                    timeout: tuple[float, float] = (3, 5)) -> Any:
        # Tight timeout: this fires on every matchup page load, so an
        # unreachable/slow host must fail fast rather than hang the page.
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def fetch_odds(self, game_date: date, home_abbr: str, away_abbr: str,
                   game_id: str) -> Optional[MarketLines]:
        """Best-effort real odds for one game; None if ESPN has nothing for it.

        Late-night starts mean a game's local date can land on a different
        UTC calendar day than the one ESPN buckets it under — try the exact
        date first, then the neighboring days, before giving up. Bounded by
        a wall-clock budget (not just each request's own timeout) so a slow
        host can't make three attempts add up to an unreasonable wait.
        """
        # Warm path: we already know this game's ESPN event id from an earlier
        # call — go straight to the summary feed. Falls through to the full
        # probe below if that comes back empty (game ended, id stale).
        #
        # Note this deliberately does *not* try the live-odds API. Nothing here
        # knows yet whether the game has started, and speculatively asking for
        # an in-game market on all of them added a doomed request per game. The
        # scoreboard pass below is what establishes liveness, and it upgrades
        # from there.
        import time
        from datetime import timedelta

        cached_id = self._event_id_cache.get(game_id)
        cached_state = self._event_state_cache.get(game_id)
        if cached_id is not None and cached_state is not None and (
                time.monotonic() - cached_state[1] < self._STATE_TTL_SECONDS):
            if cached_state[0] == "in":
                live = self._live_or_pregame(cached_id, game_id, None)
                if live is not None:
                    return live
            else:
                warm = self.fetch_pickcenter(cached_id, game_id, is_live=False)
                if warm is not None and warm.home_ml is not None:
                    return warm
        deadline = time.monotonic() + 9.0
        for offset in (0, -1, 1):
            if time.monotonic() >= deadline:
                break
            probe_date = game_date + timedelta(days=offset)
            try:
                data = self._fetch_json(_SCOREBOARD_URL, params={"dates": probe_date.strftime("%Y%m%d")})
            except Exception:
                continue
            ev = self._find_event(data, home_abbr, away_abbr)
            if ev is None:
                continue
            comp, state, event_id = ev
            if event_id is not None:
                self._event_id_cache[game_id] = event_id
                self._event_state_cache[game_id] = (state or "", time.monotonic())
            # Live game: the scoreboard odds are gone — use the summary's
            # pickcenter, which keeps updating (and carries the opening line).
            if state == "in" and event_id is not None:
                return self._live_or_pregame(event_id, game_id, comp)
            return self._parse_competition(comp, game_id)
        return None

    def fetch_pickcenter(self, event_id: Any, game_id: str,
                         is_live: bool = True,
                         timeout: Optional[tuple] = None) -> Optional[MarketLines]:
        """Live/opening lines for one game from the summary endpoint's pickcenter.

        Best-effort: None if unreachable or nothing posted. This is the source
        that keeps working once a game starts, unlike the scoreboard odds node.
        """
        try:
            summ = self._fetch_json(_SUMMARY_URL, params={"event": event_id},
                                    **({"timeout": timeout} if timeout else {}))
        except Exception:
            return None
        try:
            return self._parse_pickcenter(summ.get("pickcenter"), game_id, is_live)
        except (AttributeError, TypeError, KeyError):
            return None

    def _live_or_pregame(self, event_id: Any, game_id: str,
                         comp: Optional[dict],
                         deadline: Optional[float] = None) -> Optional[MarketLines]:
        """The in-game line for a game under way, or the pregame line marked as
        what it is.

        Order matters. The core odds API is the only one of the three that
        actually moves during a game; the summary endpoint's pickcenter and the
        scoreboard node both keep serving the closing number. Falling back to
        those is fine — a stale-but-labelled pregame price is honest — but
        passing one off as live is not, which is why `is_live` is only ever set
        by the source that genuinely had a live number.
        """
        import time as _time

        def affordable() -> bool:
            """Only start a call we can afford to see through.

            Checking the clock *between games* isn't enough — one game with two
            hanging requests overran the whole budget before the next check
            happened. The reservation must also be satisfiable: sized against a
            timeout longer than the budget itself, it silently forbade the
            fallback entirely.
            """
            if deadline is None:
                return True
            return _time.monotonic() + _ENRICH_WORST_CASE <= deadline

        timeout = _ENRICH_TIMEOUT if deadline is not None else None
        if event_id is not None:
            if affordable():
                live = self.fetch_live_odds(event_id, game_id, timeout=timeout)
                if live is not None:
                    return live
            if affordable():
                pre = self.fetch_pickcenter(event_id, game_id, is_live=False,
                                            timeout=timeout)
                if pre is not None:
                    return pre
        if comp is not None:
            return self._parse_competition(comp, game_id)
        return None

    def fetch_live_odds(self, event_id: Any, game_id: str,
                        timeout: Optional[tuple] = None) -> Optional[MarketLines]:
        """The in-game market for one game, from ESPN's core odds API.

        Returns None when there is no genuinely live number to report — the
        caller then falls back to the pregame line and, crucially, does *not*
        label it live. Reporting a pregame price as an in-game one is worse
        than reporting no in-game price, because it looks actionable.

        Every read is defensive: this is an undocumented payload, and
        `/api/odds-probe` exists to confirm its shape against production.
        """
        import time as _time
        if _time.monotonic() < ESPNOddsSource._core_unavailable_until:
            return None  # known-bad right now; don't pay the timeout again
        try:
            # Shorter than the baseline calls: this is the optional half, and
            # it is followed by a fallback that still has to fit in the budget.
            data = self._fetch_json(_CORE_ODDS_URL.format(event_id=event_id),
                                    timeout=timeout or (2, 3))
        except Exception:
            ESPNOddsSource._core_unavailable_until = (
                _time.monotonic() + ESPNOddsSource._CORE_COOLDOWN_SECONDS)
            return None
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            return None

        for item in items:
            if not isinstance(item, dict):
                continue
            lines = self._parse_core_odds(item, game_id)
            if lines is not None:
                return lines
        return None

    @staticmethod
    def _parse_core_odds(item: dict, game_id: str) -> Optional[MarketLines]:
        """One provider's entry from the core odds payload → MarketLines.

        Only the `current` node is trusted. `open` and `close` are the pregame
        market and are exactly what was being mistaken for a live line.
        """
        current = item.get("current")
        if not isinstance(current, dict):
            return None

        def _leaf(node: Any, *fields: str) -> Any:
            """Pull a value that may be flat or wrapped in {value|american|...}."""
            if isinstance(node, (int, float, str)):
                return node
            if not isinstance(node, dict):
                return None
            for f in fields:
                if node.get(f) is not None:
                    return node[f]
            return None

        ml = current.get("moneyLine") if isinstance(current.get("moneyLine"), dict) else {}
        ps = current.get("pointSpread") if isinstance(current.get("pointSpread"), dict) else {}

        home_ml = _as_int(_leaf(ml.get("home"), "american", "odds", "value", "alternateDisplayValue"))
        away_ml = _as_int(_leaf(ml.get("away"), "american", "odds", "value", "alternateDisplayValue"))
        # Some shapes put the moneyline on the team-odds nodes instead.
        if home_ml is None:
            home_ml = _as_int(_leaf((item.get("homeTeamOdds") or {}).get("current"),
                                    "moneyLine", "american", "value"))
        if away_ml is None:
            away_ml = _as_int(_leaf((item.get("awayTeamOdds") or {}).get("current"),
                                    "moneyLine", "american", "value"))

        home_spread = _as_float(_leaf(ps.get("home"), "line", "value", "handicap"))
        away_spread = _as_float(_leaf(ps.get("away"), "line", "value", "handicap"))
        if home_spread is None:
            home_spread = _as_float(_leaf(current.get("spread"), "value", "line"))
        if away_spread is None and home_spread is not None:
            away_spread = -home_spread
        home_spread_odds = _as_int(_leaf(ps.get("home"), "american", "odds"))
        away_spread_odds = _as_int(_leaf(ps.get("away"), "american", "odds"))

        total = _as_float(_leaf(current.get("total"), "value", "line", "alternateDisplayValue"))
        if total is None:
            total = _as_float(_leaf(current.get("over"), "value", "line"))

        # Nothing usable means no live market — say so rather than inventing one.
        if home_ml is None and away_ml is None and total is None:
            return None

        return MarketLines(
            fetched_at=_now_iso(),
            game_id=game_id,
            provider=(item.get("provider") or {}).get("name"),
            is_live=True,
            home_ml=home_ml, away_ml=away_ml,
            home_spread=home_spread, away_spread=away_spread,
            home_spread_odds=home_spread_odds, away_spread_odds=away_spread_odds,
            total=total,
        )

    def probe_odds(self, event_id: Any) -> dict:
        """What ESPN actually returns for a game, from both odds payloads.

        The parsers above are written against undocumented shapes and cannot be
        checked from a dev sandbox, which is how a pregame line ended up being
        served as a live one. This reports the real structure so the fix is made
        against reality rather than guessed at twice.
        """
        out: dict[str, Any] = {"event_id": event_id}

        try:
            core = self._fetch_json(_CORE_ODDS_URL.format(event_id=event_id))
            items = core.get("items") if isinstance(core, dict) else None
            out["core"] = {
                "reachable": True,
                "count": len(items) if isinstance(items, list) else 0,
                "sample": items[0] if isinstance(items, list) and items else None,
            }
        except Exception as e:
            out["core"] = {"reachable": False, "error": f"{type(e).__name__}: {e}"[:200]}

        try:
            summ = self._fetch_json(_SUMMARY_URL, params={"event": event_id})
            pc = summ.get("pickcenter") if isinstance(summ, dict) else None
            out["pickcenter"] = {
                "reachable": True,
                "count": len(pc) if isinstance(pc, list) else 0,
                "sample": pc[0] if isinstance(pc, list) and pc else None,
            }
        except Exception as e:
            out["pickcenter"] = {"reachable": False,
                                 "error": f"{type(e).__name__}: {e}"[:200]}
        return out

    def fetch_slate(self, game_date: date) -> dict[str, "MarketLines"]:
        """Every game's lines for one date in a single ESPN call, keyed by game_id.

        Far cheaper than one fetch_odds per game for the matchups list (one HTTP
        request for the whole slate instead of up to three per game). Keys are
        built from the requested date and each event's teams
        (YYYY-MM-DD-AWAY-HOME), matching this app's game_id convention. Empty
        dict if unreachable/malformed. Unlike fetch_odds it does not probe the
        neighboring calendar days — that would risk colliding same-series games
        (the same matchup on back-to-back days) onto one key; the detail page
        still does the robust per-game probe when a card is opened.
        """
        try:
            data = self._fetch_json(_SCOREBOARD_URL, params={"dates": game_date.strftime("%Y%m%d")})
        except Exception:
            return {}
        try:
            events = data.get("events", [])
        except AttributeError:
            return {}

        iso = game_date.strftime("%Y-%m-%d")
        out: dict[str, MarketLines] = {}
        # Upgrading live games to their in-game line costs extra requests per
        # game. The caller aborts the whole slate at 12s, so that work is
        # bounded well inside it: past the deadline the remaining live games
        # fall back to the pregame line instead of taking the response down
        # with them.
        import time as _time
        enrich_deadline = _time.monotonic() + _ENRICH_BUDGET
        for event in events:
            try:
                comp = event["competitions"][0]
                sides = {
                    c["homeAway"]: _normalize_abbr(c["team"]["abbreviation"])
                    for c in comp["competitors"]
                }
            except (KeyError, IndexError, TypeError):
                continue
            home, away = sides.get("home"), sides.get("away")
            if not home or not away:
                continue
            game_id = f"{iso}-{away}-{home}"
            state = ((comp.get("status") or {}).get("type") or {}).get("state")
            event_id = event.get("id")
            if event_id is not None:
                self._event_id_cache[game_id] = event_id
                self._event_state_cache[game_id] = (state or "", _time.monotonic())
            # In-progress games have no scoreboard odds anymore — pull the live
            # (and opening) line from pickcenter instead. Only live games pay
            # this extra call, so a typical slate stays a single request.
            if state == "in":
                out[game_id] = self._live_or_pregame(
                    event_id, game_id, comp, deadline=enrich_deadline)
            else:
                # Either not live, or the enrichment budget is spent. Either
                # way the scoreboard's own line is returned rather than
                # nothing — a labelled pregame price beats an empty card.
                out[game_id] = self._parse_competition(comp, game_id)
        return out

    def _find_event(self, data: Any, home_abbr: str,
                    away_abbr: str) -> Optional[tuple[dict, Optional[str], Any]]:
        """(competition, game state, event_id) for the event matching these teams."""
        try:
            events = data.get("events", [])
        except AttributeError:
            return None
        home_abbr, away_abbr = home_abbr.upper(), away_abbr.upper()
        for event in events:
            try:
                comp = event["competitions"][0]
                team_abbrs = {
                    _normalize_abbr(c["team"]["abbreviation"]): c["homeAway"]
                    for c in comp["competitors"]
                }
            except (KeyError, IndexError, TypeError):
                continue
            if team_abbrs.get(home_abbr) == "home" and team_abbrs.get(away_abbr) == "away":
                state = ((comp.get("status") or {}).get("type") or {}).get("state")
                return comp, state, event.get("id")
        return None

    def _parse_competition(self, comp: dict, game_id: str) -> MarketLines:
        """Pull the first posted book's lines off one competition node."""
        odds_list = comp.get("odds") or []
        if not odds_list:
            # Matched the game, no line posted yet.
            return MarketLines(game_id=game_id, fetched_at=_now_iso())

        odds = odds_list[0]
        provider = (odds.get("provider") or {}).get("name")
        total = odds.get("overUnder")
        moneyline = odds.get("moneyline") or {}
        point_spread = odds.get("pointSpread") or {}

        def _closing_value(section: dict, side: str, field: str) -> Any:
            return ((section.get(side) or {}).get("close") or {}).get(field)

        return MarketLines(
            fetched_at=_now_iso(),
            game_id=game_id,
            provider=provider,
            home_ml=_as_int(_closing_value(moneyline, "home", "odds")),
            away_ml=_as_int(_closing_value(moneyline, "away", "odds")),
            home_spread=_as_float(_closing_value(point_spread, "home", "line")),
            away_spread=_as_float(_closing_value(point_spread, "away", "line")),
            home_spread_odds=_as_int(_closing_value(point_spread, "home", "odds")),
            away_spread_odds=_as_int(_closing_value(point_spread, "away", "odds")),
            total=total if isinstance(total, (int, float)) else None,
        )

    def _parse_pickcenter(self, pc_list: Any, game_id: str,
                          is_live: bool) -> Optional[MarketLines]:
        """Parse the summary endpoint's `pickcenter` (live + opening lines).

        The current line comes from the flat top-level fields (the reliable,
        long-standing pickcenter shape: `overUnder`, `spread`,
        `homeTeamOdds.moneyLine`, `spreadOdds`); the opening line comes from the
        nested `open` block, best-effort. `spread` is the home team's handicap,
        so the away line is its negation.
        """
        if not pc_list:
            return None
        pc = pc_list[0]  # first book (ESPN orders by provider priority)
        provider = (pc.get("provider") or {}).get("name")
        home_odds = pc.get("homeTeamOdds") or {}
        away_odds = pc.get("awayTeamOdds") or {}
        # Nested moneyline/pointSpread objects (same shape as the scoreboard),
        # whose per-side nodes can carry open/close/current sub-values.
        moneyline = pc.get("moneyline") or {}
        point_spread = pc.get("pointSpread") or {}

        def _sub(section: dict, side: str, sub: str, field: str) -> Any:
            return (((section.get(side) or {}).get(sub) or {}) or {}).get(field)

        # Moneyline: prefer a live "current" nested value; fall back to the flat
        # field (which the real payload confirms is populated). Only upgrade to
        # the nested value when it exists, so this never regresses.
        home_ml = _as_int(_sub(moneyline, "home", "current", "odds"))
        if home_ml is None:
            home_ml = _as_int(home_odds.get("moneyLine"))
        away_ml = _as_int(_sub(moneyline, "away", "current", "odds"))
        if away_ml is None:
            away_ml = _as_int(away_odds.get("moneyLine"))

        # Run line: prefer the nested current line/price, else the flat fields.
        home_spread = _as_float(_sub(point_spread, "home", "current", "line"))
        if home_spread is None:
            home_spread = _as_float(pc.get("spread"))
        away_spread = _as_float(_sub(point_spread, "away", "current", "line"))
        if away_spread is None:
            away_spread = -home_spread if home_spread is not None else None
        home_spread_odds = _as_int(_sub(point_spread, "home", "current", "odds"))
        if home_spread_odds is None:
            home_spread_odds = _as_int(home_odds.get("spreadOdds"))
        away_spread_odds = _as_int(_sub(point_spread, "away", "current", "odds"))
        if away_spread_odds is None:
            away_spread_odds = _as_int(away_odds.get("spreadOdds"))

        lines = MarketLines(
            fetched_at=_now_iso(),
            game_id=game_id, provider=provider, is_live=is_live,
            home_ml=home_ml, away_ml=away_ml,
            home_spread=home_spread, away_spread=away_spread,
            home_spread_odds=home_spread_odds, away_spread_odds=away_spread_odds,
            total=_as_float(pc.get("overUnder")),
        )

        # Opening line — from the nested per-side "open" nodes if present, else
        # the top-level "open" block (structure varies; extract defensively).
        lines.home_ml_open = _as_int(_sub(moneyline, "home", "open", "odds"))
        lines.away_ml_open = _as_int(_sub(moneyline, "away", "open", "odds"))
        lines.home_spread_open = _as_float(_sub(point_spread, "home", "open", "line"))
        lines.away_spread_open = _as_float(_sub(point_spread, "away", "open", "line"))
        op = pc.get("open") or {}
        if isinstance(op, dict) and op:
            op_home = op.get("homeTeamOdds") or {}
            op_away = op.get("awayTeamOdds") or {}
            if lines.home_ml_open is None:
                lines.home_ml_open = _leaf_int(op_home.get("moneyLine"))
            if lines.away_ml_open is None:
                lines.away_ml_open = _leaf_int(op_away.get("moneyLine"))
            if lines.home_spread_open is None:
                lines.home_spread_open = _leaf_spread(op_home.get("pointSpread"))
            if lines.away_spread_open is None:
                lines.away_spread_open = _leaf_spread(op_away.get("pointSpread"))
            lines.total_open = _leaf_float(op.get("total")) or _leaf_float(op.get("over"))
        return lines


def _as_int(v: Any) -> Optional[int]:
    # Moneyline arrives as a signed string ("+135", "-163"); int() handles
    # the explicit "+" natively.
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return None
    return None


def _as_float(v: Any) -> Optional[float]:
    # Spread lines arrive as a signed string ("+1.5", "-1.5") with the
    # correct side already baked in — no favorite-flag math needed.
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _leaf_num(node: Any) -> Optional[float]:
    """A number out of an ESPN odds leaf: a scalar, or {value/american/...} node."""
    if isinstance(node, (int, float)):
        return float(node)
    if isinstance(node, str):
        return _as_float(node)
    if isinstance(node, dict):
        if isinstance(node.get("value"), (int, float)):
            return float(node["value"])
        for k in ("american", "displayValue", "alternateDisplayValue"):
            r = _as_float(node.get(k))
            if r is not None:
                return r
    return None


def _leaf_int(node: Any) -> Optional[int]:
    v = _leaf_num(node)
    return int(round(v)) if v is not None else None


def _leaf_float(node: Any) -> Optional[float]:
    return _leaf_num(node)


def _leaf_spread(node: Any) -> Optional[float]:
    """Signed spread line; prefer the signed string forms over an unsigned value."""
    if isinstance(node, dict):
        for k in ("displayValue", "american", "alternateDisplayValue"):
            r = _as_float(node.get(k))
            if r is not None:
                return r
    return _leaf_num(node)
