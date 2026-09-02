"""Player props from Sleeper's public API.

Sleeper runs a higher/lower player-props product and serves its lines from
`/lines/available`. The endpoint is public and needs no key, but it is not a
documented, versioned API — the field names below are the ones its client uses
and every access is defensive, so a rename degrades to "no props" rather than an
exception.

Two calls are involved:

  GET /lines/available?sport=mlb&include_props=true&dynamic=true
      the lines themselves, each keyed to a Sleeper `subject_id`

  GET /v1/players/mlb
      the player directory, used to turn those ids into names we can match
      against our own projections. It is large, so it is fetched once and held
      for the life of the process.

Because the shape is unofficial, `probe()` returns what the endpoint actually
sent — reachability, count, and the keys observed — so the parser can be
corrected against reality instead of guesswork.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests

from ..names import normalize_name

_LINES_URL = "https://api.sleeper.app/lines/available"
_PLAYERS_URL = "https://api.sleeper.app/v1/players/mlb"

# Sleeper's `wager_type` vocabulary, mapped onto the stat our simulator keeps a
# per-game distribution for. `side` says whether the subject is hitting or
# pitching, which decides which distribution to read. Sleeper prefixes the
# batter's version of an ambiguous market ("bat_walks") and leaves the
# pitcher's unprefixed ("walks").
#
# Deliberately absent, so they're dropped rather than mispriced:
#   runs, hits_runs_rbis — runs *scored* are credited to the runner, and the
#     simulator's bases are an occupancy bitmap with no runner identity, so
#     there is no per-batter runs distribution to price against.
#   stolen_bases, first_inning_runs — not simulated at all.
_STAT_MAP: dict[str, tuple[str, str]] = {
    # batting
    "hits": ("batter", "hits"),
    "singles": ("batter", "singles"),
    "doubles": ("batter", "doubles"),
    "triples": ("batter", "triples"),
    "home_runs": ("batter", "home_runs"),
    "total_bases": ("batter", "total_bases"),
    "rbis": ("batter", "rbi"),
    "bat_walks": ("batter", "bb"),
    "bat_strike_outs": ("batter", "k"),
    # pitching
    "strike_outs": ("pitcher", "k"),
    "outs": ("pitcher", "outs"),
    "hits_allowed": ("pitcher", "hits_allowed"),
    "walks": ("pitcher", "bb_allowed"),
    # We simulate runs allowed, not earned runs; unearned runs are rare enough
    # that the difference is far inside this market's vig.
    "earned_runs": ("pitcher", "runs_allowed"),
}


@dataclass
class TeamLine:
    """One team market — moneyline, spread or total — from the Picks API.

    Field names come from Sleeper's GraphQL `Line` type, read off its own
    introspection, so this mirrors the server's vocabulary rather than a
    guess at it.
    """
    market: str                # "moneyline" | "spread" | "total"
    team: Optional[str]
    line: Optional[float] = None
    price: Optional[int] = None
    over_price: Optional[int] = None
    under_price: Optional[int] = None
    game_id: Optional[str] = None
    game_status: str = "pre_game"
    is_live: bool = False
    raw_type: Optional[str] = None


def _collect_lines(node: Any, out: list, depth: int = 0) -> None:
    """Gather every Line-shaped object anywhere in a payload.

    `my_picks_init` returns an opaque JSON scalar, so where the lines sit
    inside it is not described by the schema. What *is* described is what a
    Line looks like — so rather than assume a container key, this recognises
    Lines by their own fields wherever they are nested.
    """
    if depth > 8:
        return
    if isinstance(node, dict):
        if "wager_type" in node and "subject_type" in node:
            out.append(node)
        for v in node.values():
            _collect_lines(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _collect_lines(v, out, depth + 1)


@dataclass
class PlayerProp:
    """One over/under prop, normalized onto our stat vocabulary."""
    player_name: str
    player_key: str            # normalized name, for matching
    side: str                  # "batter" | "pitcher"
    stat: str                  # our stat id (hits, home_runs, k, ...)
    line: float
    over_price: Optional[int]  # American odds
    under_price: Optional[int]
    team: Optional[str] = None
    raw_stat: Optional[str] = None
    # Sleeper's own label for the game's state ("pre_game", "in_game", ...).
    game_status: str = "pre_game"
    # True once the game is under way, which decides whether this has to be
    # priced against the rest of the game rather than against all nine innings.
    is_live: bool = False


def _as_american(v: Any) -> Optional[int]:
    """American odds from whatever the feed carries.

    Sleeper quotes some markets as a payout multiplier (decimal-style) rather
    than American odds, so both are accepted and multipliers are converted.
    """
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if abs(f) >= 100:          # already American
            return int(round(f))
        if f > 1.0:                # decimal payout multiplier
            b = f - 1.0
            return int(round(b * 100)) if b >= 1.0 else int(round(-100.0 / b))
        return None
    if isinstance(v, str):
        try:
            return _as_american(float(v.replace("+", "")))
        except ValueError:
            return None
    return None


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


class SleeperPropsSource:
    """Fetches Sleeper's public player-prop lines. Best-effort throughout."""

    _players_cache: Optional[dict[str, dict]] = None

    def _get(self, url: str, params: Optional[dict] = None, timeout=(4, 12)) -> Any:
        resp = requests.get(url, params=params, timeout=timeout,
                            headers={"accept": "application/json"})
        resp.raise_for_status()
        return resp.json()

    def _players(self) -> dict[str, dict]:
        """Sleeper's MLB player directory, id → record. Fetched once."""
        if SleeperPropsSource._players_cache is None:
            try:
                data = self._get(_PLAYERS_URL, timeout=(4, 25))
                SleeperPropsSource._players_cache = data if isinstance(data, dict) else {}
            except Exception:
                SleeperPropsSource._players_cache = {}
        return SleeperPropsSource._players_cache

    def _name_for(self, subject_id: Any) -> tuple[Optional[str], Optional[str]]:
        rec = self._players().get(str(subject_id))
        if not isinstance(rec, dict):
            return None, None
        name = _first(rec, "full_name", "fullName") or " ".join(
            x for x in (rec.get("first_name"), rec.get("last_name")) if x
        )
        return (name or None), rec.get("team")

    def probe(self, sport: str = "mlb") -> dict:
        """What the endpoint actually returned — for confirming the shape live.

        The parser below is written against an undocumented response, so this
        reports reachability, how many lines came back, and the keys present on
        a sample, without asserting anything about them.
        """
        out: dict[str, Any] = {"reachable": False, "count": 0}
        try:
            data = self._get(_LINES_URL, params={
                "sport": sport, "include_props": "true", "dynamic": "true"})
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"[:200]
            return out
        out["reachable"] = True
        items = data if isinstance(data, list) else (
            data.get("lines") if isinstance(data, dict) else None) or []
        out["count"] = len(items)
        out["top_level_type"] = type(data).__name__
        if items and isinstance(items[0], dict):
            out["sample_keys"] = sorted(items[0].keys())
            # `recent_performance` is a long per-game array that says nothing
            # about the shape, so it's dropped from the sample.
            out["sample"] = {k: v for k, v in items[0].items()
                             if k != "recent_performance"}
            opts = items[0].get("options")
            if isinstance(opts, list) and opts and isinstance(opts[0], dict):
                out["option_keys"] = sorted(opts[0].keys())
            # The market vocabulary is the thing most likely to be wrong: our
            # stat map has to key off whatever strings actually appear here.
            counts: dict[str, int] = {}
            for it in items:
                if isinstance(it, dict):
                    for f in ("wager_type", "market_type", "line_type",
                              "subject_type", "outcome_type"):
                        v = it.get(f)
                        if isinstance(v, str):
                            counts[f"{f}={v}"] = counts.get(f"{f}={v}", 0) + 1
            out["vocabulary"] = dict(sorted(counts.items(),
                                            key=lambda kv: -kv[1])[:40])

            # Team markets — moneyline, spread, total — come off the same
            # endpoint as the player props but under a different subject type,
            # and the parser drops them today. Report them separately so the
            # team parser can be written against the real shape rather than
            # guessed at: which wager types exist for a non-player subject,
            # and one whole example with its options.
            team_items = [it for it in items
                          if isinstance(it, dict)
                          and str(it.get("sport") or "").lower() == sport.lower()
                          and str(it.get("subject_type") or "").lower() not in
                          ("player", "")]
            out["team_count"] = len(team_items)
            tcounts: dict[str, int] = {}
            for it in team_items:
                st = str(it.get("subject_type") or "?")
                wt = str(it.get("wager_type") or it.get("market") or "?")
                tcounts[f"{st}/{wt}"] = tcounts.get(f"{st}/{wt}", 0) + 1
            out["team_vocabulary"] = dict(sorted(tcounts.items(),
                                                 key=lambda kv: -kv[1])[:40])
            if team_items:
                out["team_sample_keys"] = sorted(team_items[0].keys())
                # A few whole examples, one per wager type, so every team
                # market's option shape is visible in a single probe.
                seen: set[str] = set()
                samples = []
                for it in team_items:
                    wt = str(it.get("wager_type") or "?")
                    if wt in seen:
                        continue
                    seen.add(wt)
                    samples.append({k: v for k, v in it.items()
                                    if k != "recent_performance"})
                    if len(samples) >= 4:
                        break
                out["team_samples"] = samples
        # What each filter threw away, and how many props actually survive.
        # Added because "why is this player missing" was only answerable by
        # reading the parser — every drop looks identical from the board.
        drops: dict[str, int] = {}
        parsed = self.fetch_props(sport, drops)
        out["parsed"] = len(parsed)
        out["dropped"] = dict(sorted(drops.items(), key=lambda kv: -kv[1])[:30])
        # Per stat, so a market coming through thin against the app's own board
        # is visible as a number rather than as a hunch.
        per_stat: dict[str, int] = {}
        for pr in parsed:
            k = f"{pr.side}/{pr.stat}"
            per_stat[k] = per_stat.get(k, 0) + 1
        out["parsed_by_stat"] = dict(sorted(per_stat.items()))
        # One-sided markets, which is the shape the outcome_type gate used to
        # remove wholesale.
        out["one_sided"] = sum(
            1 for pr in parsed if (pr.over_price is None) != (pr.under_price is None))
        out["players_loaded"] = len(self._players())
        return out

    _GRAPHQL_URL = "https://api.sleeper.app/graphql"

    def _graphql(self, query: str, variables: Optional[dict] = None,
                 timeout=(4, 15)) -> dict:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = requests.post(
            self._GRAPHQL_URL, json=payload, timeout=timeout,
            headers={"accept": "application/json",
                     "content-type": "application/json"})
        resp.raise_for_status()
        return resp.json()

    def discover_picks_api(self, sport: str = "mlb") -> dict:
        """Read the Picks schema off the server, then run the query it names.

        Introspection is enabled — the endpoint answered a malformed query by
        naming the correct field (`query_type`, not `queryType`), which is how
        the snake_case above was arrived at rather than guessed.

        Three things get reported, each a fact the server supplied:

        * every `RootQueryType` field with its arguments and return type, so
          the entry point for the Picks tab is named rather than assumed;
        * the whole `Line` type, which is what a market is made of;
        * the result of actually running `my_picks_init` — the no-argument
          query the picks screen would call — asked only for its type name, so
          it either returns a shape to drill into or an error that says what
          it wants (an argument, or a session).
        """
        out: dict[str, Any] = {"sport": sport}

        def run(label: str, query: str, variables=None):
            try:
                body = self._graphql(query, variables)
            except Exception as e:
                out[label] = {"error": f"{type(e).__name__}: {e}"[:200]}
                return None
            row: dict[str, Any] = {}
            if body.get("errors"):
                row["errors"] = str(body["errors"])[:600]
            row["data"] = body.get("data")
            out[label] = row
            return body.get("data")

        # 1. Every root query, with arguments and return type.
        data = run("root_queries", """
            query R { __type(name: "RootQueryType") {
                fields {
                  name
                  args { name type { name kind of_type { name } } }
                  type { name kind of_type { name kind of_type { name } } }
                }
            } }""")
        if data:
            fields = ((data.get("__type") or {}).get("fields") or [])
            out["root_query_list"] = sorted(
                f"{f['name']}({', '.join(a['name'] for a in (f.get('args') or []))})"
                for f in fields if isinstance(f, dict))

        # 2. What a Line is made of.
        run("line_type", """
            query L { __type(name: "Line") {
                fields { name type { name kind of_type { name kind } } }
            } }""")

        # 3. The picks entry point, run for real. It returns `Map` — an
        # opaque JSON scalar — so it takes no selection set; the server
        # said as much ("must not have a selection since type Map has no
        # subfields"), which is how this is written rather than guessed.
        run("my_picks_init", "query P { my_picks_init }")
        return out

    # Every field below is the schema's, read off Sleeper's own GraphQL
    # introspection — not inferred from a response and not guessed.
    _TEAM_MARKET: dict[str, str] = {
        "moneyline": "moneyline", "money_line": "moneyline",
        "to_win": "moneyline", "winner": "moneyline", "win": "moneyline",
        "spread": "spread", "point_spread": "spread", "run_line": "spread",
        "handicap": "spread",
        "total": "total", "game_total": "total", "total_runs": "total",
        "over_under": "total",
    }

    def fetch_team_lines(self, sport: str = "mlb") -> list["TeamLine"]:
        """Team markets from the Picks API. Empty without a session token.

        Established by asking Sleeper's GraphQL schema to describe itself:

        * `/lines/available` (REST, anonymous) serves `subject_type=player`
          and nothing else — 2230 of 2230 items on a full slate.
        * The GraphQL schema has a `Line` type carrying `subject_type`,
          `subject`, `wager_type`, `outcome_type`, `outcome_value`,
          `payout_multiplier`, `market_type`, `game_id` and `game_status`.
          Team markets are Lines; they are simply not served anonymously.
        * Every root query that returns markets is user-scoped —
          `my_picks_init`, `my_parlays`, `league_parlays`, `parlay` — and
          `my_picks_init` answers an anonymous call with
          `{"code": "unauthorized", "message": "Unauthorized"}`.

        So this needs a session. Set `SLEEPER_AUTH_TOKEN` and it sends it as
        the `authorization` header; without one it returns nothing rather than
        pretending.

        `my_picks_init` returns `Map` — an opaque JSON scalar — so the shape of
        the container is not in the schema. Rather than assume where the lines
        sit inside it, the payload is walked for objects that *are* Lines: the
        field names are schema-confirmed, so a Line is recognisable wherever it
        is nested.
        """
        import os

        token = os.environ.get("SLEEPER_AUTH_TOKEN")
        if not token:
            return []
        try:
            body = self._graphql_authed("query P { my_picks_init }", token)
        except Exception:
            return []
        blob = (body.get("data") or {}).get("my_picks_init")
        if blob is None:
            return []

        found: list[dict] = []
        _collect_lines(blob, found)

        out: list[TeamLine] = []
        for it in found:
            if str(it.get("sport") or sport).lower() != sport.lower():
                continue
            if str(it.get("subject_type") or "player").lower() == "player":
                continue          # player props are the REST feed's job
            if str(it.get("status") or "active").lower() != "active":
                continue
            market = self._TEAM_MARKET.get(
                str(it.get("wager_type") or "").strip().lower())
            if market is None:
                continue
            subject = it.get("subject")
            team = None
            if isinstance(subject, dict):
                team = subject.get("team") or subject.get("abbreviation")
            team = team or it.get("subject_id")
            price = _as_american(it.get("payout_multiplier"))
            line = it.get("outcome_value")
            try:
                line = float(line) if line is not None else None
            except (TypeError, ValueError):
                line = None
            gs = str(it.get("game_status") or "pre_game").lower()
            outcome = str(it.get("outcome") or "").lower()
            out.append(TeamLine(
                market=market,
                team=str(team) if team else None,
                line=line,
                price=price,
                over_price=price if outcome.startswith("over") else None,
                under_price=price if outcome.startswith("under") else None,
                game_id=str(it.get("game_id") or "") or None,
                game_status=gs,
                is_live=gs not in ("pre_game", ""),
                raw_type=it.get("wager_type"),
            ))
        return out

    def _graphql_authed(self, query: str, token: str) -> dict:
        resp = requests.post(
            self._GRAPHQL_URL, json={"query": query}, timeout=(4, 15),
            headers={"accept": "application/json",
                     "content-type": "application/json",
                     "authorization": token})
        resp.raise_for_status()
        return resp.json()

    def fetch_props(self, sport: str = "mlb",
                    drops: Optional[dict] = None) -> list[PlayerProp]:
        """Normalized props; empty list if unreachable, unparseable, or absent.

        The feed answers with every sport it runs regardless of the `sport`
        parameter — an MLB request comes back carrying esports markets too — so
        each line is filtered on its own `sport` field rather than trusted.

        `drops` counts what each filter threw away. Every `continue` below ends
        as a prop that isn't on the board, and from outside they all look the
        same — a player Sleeper plainly offers who simply isn't there.
        """
        def lost(stage: str) -> None:
            if drops is not None:
                drops[stage] = drops.get(stage, 0) + 1

        try:
            data = self._get(_LINES_URL, params={
                "sport": sport, "include_props": "true", "dynamic": "true"})
        except Exception:
            return []
        items = data if isinstance(data, list) else (
            data.get("lines") if isinstance(data, dict) else None) or []

        props: list[PlayerProp] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            if str(it.get("sport") or "").lower() != sport.lower():
                continue
            if str(it.get("subject_type") or "player").lower() != "player":
                lost("not_a_player_subject")
                continue
            if str(it.get("status") or "active").lower() != "active":
                lost(f"status={it.get('status')}")
                continue
            # `outcome_type` is deliberately *not* filtered on. It used to be
            # gated to "over_under", which quietly removed every one-sided
            # market — Sleeper posts plenty of picks with only a MORE side, and
            # home runs are mostly those, so the HR board came through nearly
            # empty while hits and total bases were full.
            #
            # Nothing is lost by dropping the gate, because the real check is
            # below and always was: an option has to be labelled over/high or
            # under/low, carry a usable price, and have a numeric line. A market
            # that can't be read as an over/under still fails that, and one that
            # can is priceable whatever the feed calls it.
            # Both pregame and in-progress lines are kept; the caller decides
            # which it can price. A live one must be matched against a
            # simulation of the *remaining* innings, so it is tagged rather
            # than dropped — dropping it here is why live props never appeared.
            gs = str(it.get("game_status") or "pre_game").lower()

            raw_stat = _first(it, "wager_type", "stat", "market", "type")
            if not isinstance(raw_stat, str):
                continue
            mapped = _STAT_MAP.get(raw_stat.strip().lower())
            if mapped is None:
                lost(f"unmapped_market={raw_stat.strip().lower()}")
                continue
            side, stat = mapped

            # The line and both prices live on the options, not the parent.
            line = _first(it, "outcome_value", "line", "value")
            over = under = team = None
            for o in it.get("options") or []:
                if not isinstance(o, dict):
                    continue
                if str(o.get("status") or "active").lower() != "active":
                    continue
                if line is None:
                    line = _first(o, "outcome_value", "line", "value")
                team = team or o.get("subject_team")
                price = _as_american(
                    _first(o, "payout_multiplier", "odds", "american_odds"))
                if price is None:
                    continue
                label = str(_first(o, "outcome", "side", "name") or "").lower()
                if label.startswith("over") or label.startswith("high"):
                    over = price
                elif label.startswith("under") or label.startswith("low"):
                    under = price
            if over is None and under is None:
                lost("no_price_either_side")
                continue
            try:
                line = float(line)
            except (TypeError, ValueError):
                lost("no_usable_line_value")
                continue

            subject = _first(it, "subject_id", "player_id", "subject")
            name, directory_team = self._name_for(subject)
            if not name:
                name = _first(it, "player_name", "subject_name")
            if not name:
                lost("no_name_resolved")
                continue

            props.append(PlayerProp(
                player_name=name, player_key=normalize_name(name), side=side,
                stat=stat, line=line, over_price=over, under_price=under,
                team=team or directory_team, raw_stat=raw_stat,
                game_status=gs, is_live=gs not in ("pre_game", ""),
            ))
        return props
