"""Ask Claude about the slate, the simulations, and baseball.

A chat endpoint is easy; a chat endpoint worth having is the part that takes
work. A model answering from training data alone would talk confidently about a
2024 roster and know nothing about the simulation it is supposedly explaining —
worse than no feature, because it sounds authoritative while being wrong.

So the model gets tools instead of a paragraph of pasted context. It can pull
the slate, run a matchup through the same cached Monte Carlo the cards use,
read the trend forecasts, and check how the model has actually been scoring.
Every number it quotes comes from the same place the page gets its numbers, and
when it has nothing to go on it can say so rather than inventing.

Two deliberate limits. The tools are read-only — nothing here can write to the
record, re-issue a forecast, or change a projection, so a conversation can be
wrong but cannot do damage. And the whole feature is gated on an API key being
present: without one the endpoint reports itself unavailable and the panel
never renders, rather than erroring at the user.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterator, Optional

# Haiku by default, and the reason is cost rather than taste.
#
# The first version ran Opus 5, which thinks by default — and thinking bills at
# the *output* rate. One question came to $0.32, of which roughly $0.30 was
# ~12,000 thinking tokens. The tool payloads, which is what I originally sized,
# were never the problem.
#
# Haiku 4.5 is a fifth the price on both sides and does no thinking unless it
# is explicitly asked for, which removes that entire line item. It suits the
# job: the analysis already happened in the simulator, and the model is reading
# results and writing a sentence about them.
MODEL = os.environ.get("THEBEAST_CHAT_MODEL", "claude-haiku-4-5").strip() \
    or "claude-haiku-4-5"
EFFORT = os.environ.get("THEBEAST_CHAT_EFFORT", "low").strip() or "low"

# `output_config.effort` is rejected by models that predate it — sending it to
# Haiku 4.5 is a 400, not a no-op — so it only goes out to models that take it.
_EFFORT_MODELS = (
    "claude-fable-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
    "claude-opus-4-6", "claude-sonnet-5", "claude-sonnet-4-6",
)


def _request_extras() -> dict:
    """Per-model request fields, so swapping the model cannot 400.

    Thinking is left alone deliberately. On Haiku it is off unless asked for,
    which is what makes this cheap; on an Opus-tier override it stays on, and
    the operator has chosen to pay for it.
    """
    if MODEL.startswith(_EFFORT_MODELS):
        return {"output_config": {"effort": EFFORT}}
    return {}


# Short answers need a low ceiling as well as a prompt that asks for one.
MAX_TOKENS = 1024

# Every turn of history is resent on every question, so a long conversation is
# a bill that grows quietly. Eight turns is plenty for "and what about the
# other game?" and stops the tail wagging the cost.
MAX_TURNS = 8
MAX_CHARS = 6000

# Each round resends the whole context including every tool result so far, so
# rounds compound rather than add. Three is enough to look something up, look
# up a second thing, and answer.
MAX_TOOL_ROUNDS = 3

# What to tell someone whose key was refused. The 401 body says "invalid
# x-api-key" and nothing about what to do next; these are the things that
# actually cause it, in the order they actually happen.
# Creating a key costs nothing; calling the API does. An account that has never
# been funded gets this far — valid key, no balance — and deserves to be told
# that rather than shown a 400.
NO_CREDIT = (
    "The API key works, but the Anthropic account behind it has no credit. "
    "Add a payment method or buy credits at console.anthropic.com → Plans & "
    "Billing, then ask again. Nothing is charged until a question is asked, "
    "and questions here run around 2-3 cents each."
)

KEY_REJECTED = (
    "Anthropic rejected the API key. The value is set on the Space but is not "
    "one Anthropic recognises — usually a partial paste, a key that was later "
    "revoked, or a value copied from somewhere other than the API keys page. "
    "Create a fresh key at console.anthropic.com → API keys and replace the "
    "ANTHROPIC_API_KEY secret with the whole thing."
)


# Anthropic keys all carry this prefix. Checking it catches the common paste
# accidents — half a key, a key name instead of its value, a token from some
# other service — before they cost a round trip and a confusing 401.
_KEY_PREFIX = "sk-ant-"


def api_key() -> Optional[str]:
    """The configured key, whitespace stripped.

    Stripping is not cosmetic. A secrets form on a phone will happily carry a
    trailing newline or a leading space into the stored value, and the API
    rejects the resulting header as an invalid key — which reads as "my key is
    wrong" when the key is fine and only its packaging is not.
    """
    raw = os.environ.get("ANTHROPIC_API_KEY") or ""
    return raw.strip() or None


def available() -> bool:
    """Whether a key is configured at all."""
    return api_key() is not None


def key_looks_wrong() -> bool:
    """True when a key is present but is not shaped like an Anthropic key.

    Deliberately a shape check, not a validity check: confirming a key really
    works means spending a live API call, and doing that on every page load
    would bill the owner for the privilege of rendering a panel.
    """
    key = api_key()
    return key is not None and not key.startswith(_KEY_PREFIX)


# ── the tools ───────────────────────────────────────────────────────────────
#
# Descriptions say *when* to call, not just what the tool does. The model reaches
# for tools conservatively, and a description that only names the return value
# tends to get skipped in favour of an answer from memory — which for a live
# slate is exactly the wrong trade.

TOOLS: list[dict] = [
    {
        "name": "get_slate",
        "description": (
            "Tonight's whole slate with the model's projection already attached "
            "to every game: matchup, start time, status, win probability and "
            "projected total, read from the simulations the app ran when it "
            "started. One call, no game ids to look up, and the same numbers "
            "the matchup cards are showing. Call it first for anything about "
            "tonight — which games, which look close, where the model leans."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Slate date as YYYY-MM-DD. Omit for today.",
                },
            },
        },
    },
    {
        "name": "get_best_bets",
        "description": (
            "The ranked plays for a slate — the same ones in the Best bets "
            "panel, built by pricing the configured props feed against "
            "this app's simulations and keeping where they disagree. The reply "
            "names that feed in `source`, and carries a `pricing_caveat` when "
            "the feed posts no odds of its own — repeat it rather than "
            "presenting the price as one the user can go and take. Each play "
            "carries the model's probability, the book's implied probability, "
            "the edge between them, and whether it clears the bar. Call it for "
            "any question about what to bet, parlays, props, edges or value — "
            "never assemble a recommendation by running games yourself, and "
            "never invent a price or a line."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Slate date as YYYY-MM-DD. Omit for today.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many plays to return, best edge first. Default 12.",
                },
                "with_edge_only": {
                    "type": "boolean",
                    "description": (
                        "Only plays that clear the minimum edge. Default true — "
                        "the rest are listed for context, not as recommendations."
                    ),
                },
            },
        },
    },
    {
        "name": "get_projections",
        "description": (
            "One projected stat, ranked across every player on the slate — "
            "'which pitcher strikes out the most tonight', 'who is most likely "
            "to homer', 'who gets the most hits'. Read straight from the "
            "simulations already run, sorted here, so the answer is ordered "
            "correctly and nothing is re-simulated. Call it for any question "
            "comparing players across games; simulating each game to compare "
            "them by hand is slow and gets the order wrong."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["pitchers", "batters"],
                    "description": "Which side of the ball. Required.",
                },
                "stat": {
                    "type": "string",
                    "description": (
                        "Pitchers: k, ip, hits_allowed, runs_allowed, "
                        "bb_allowed, pitches. Batters: hits, home_runs, rbi, "
                        "k, bb, pa."
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "Slate date as YYYY-MM-DD. Omit for today.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many to return, highest first. Default 8.",
                },
                "include_bullpen": {
                    "type": "boolean",
                    "description": (
                        "Include each team's combined bullpen line. Off by "
                        "default — it is an aggregate, not a person, and would "
                        "be a wrong answer to 'which pitcher'."
                    ),
                },
            },
            "required": ["kind", "stat"],
        },
    },
    {
        "name": "simulate_what_if",
        "description": (
            "Re-run one game with a player's rates changed, and get back both "
            "the normal projection and the altered one. This is the only tool "
            "that runs a new simulation, and the only reason to: the user has "
            "asked a question the stored runs cannot answer — 'what if Judge "
            "were healthy', 'what if their ace went 20% better on strikeouts'. "
            "Multipliers are relative to the player's real rates, so 1.2 is "
            "20% more and 0.8 is 20% fewer. Call it only for an explicit "
            "what-if; every ordinary question is answered from the tools above."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "game_id": {"type": "string",
                            "description": "Game id from get_slate."},
                "batter_changes": {
                    "type": "object",
                    "description": (
                        "{player_id: {hits|home_runs|bb|k: multiplier}}. Get "
                        "ids from find_player or simulate_game with detail."
                    ),
                },
                "pitcher_changes": {
                    "type": "object",
                    "description": (
                        "{pitcher_id: {hits_allowed|hr_allowed|bb_allowed|k: "
                        "multiplier}}."
                    ),
                },
            },
            "required": ["game_id"],
        },
    },
    {
        "name": "list_games",
        "description": (
            "The MLB slate for a date: matchups, start times, status, and the "
            "score for anything live or final. Call this whenever the question "
            "touches which games are on, who is playing, or what has happened "
            "today — never answer those from memory, the schedule changes daily."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Slate date as YYYY-MM-DD. Omit for today.",
                },
            },
        },
    },
    {
        "name": "simulate_game",
        "description": (
            "The model's projection for one matchup: win probability, "
            "projected score, total, and optionally the per-player lines. "
            "Reads what has already been computed — the graded record for a "
            "game that has finished, otherwise the run behind that game's "
            "card — and only simulates when neither exists. The numbers "
            "therefore agree with what the user is looking at. Call it for "
            "any question about a specific game, player, or pitcher. Get the "
            "game_id from list_games first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "game_id": {
                    "type": "string",
                    "description": "Game id from list_games, e.g. 2026-08-02-NYY-BOS.",
                },
                "detail": {
                    "type": "boolean",
                    "description": (
                        "Include every batter and pitcher line. Leave this off "
                        "unless the question is about specific players — the "
                        "summary already carries the win probability, score, "
                        "and total, which is what most questions need."
                    ),
                },
            },
            "required": ["game_id"],
        },
    },
    {
        "name": "get_trends",
        "description": (
            "What the league has been doing over the last week measured against "
            "the season, plus the forecasts for the coming week and how earlier "
            "forecasts scored. Call this for questions about league trends — "
            "scoring, home runs, bullpen usage, home-field — or about what the "
            "app expects next week."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_accuracy",
        "description": (
            "How the simulations have actually scored against finished games: "
            "winner accuracy, error on totals and spreads, and per-position "
            "player accuracy. Call this for any question about whether the model "
            "is any good, where it is wrong, or how a projection should be "
            "trusted. Answer honestly from what this returns — do not soften it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Window length in days, 1-60. Defaults to 7.",
                },
            },
        },
    },
    {
        "name": "get_league_history",
        "description": (
            "League-wide levels from several seasons of real games — runs, home "
            "runs, strikeouts, walks, hits per game, home win rate, one-run and "
            "blowout rates. Use it for historical context, season-over-season "
            "comparisons, or to check whether something is actually unusual."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "season": {
                    "type": "integer",
                    "description": "A single season. Omit for every season on file.",
                },
            },
        },
    },
    {
        "name": "find_player",
        "description": (
            "Look up a player by name and return their rate statline — the "
            "season form the simulation is built from. Call this when the "
            "question is about a specific hitter or pitcher and no particular "
            "game is in play."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Full or partial player name.",
                },
            },
            "required": ["name"],
        },
    },
]


def _parse_date(raw: Optional[str]) -> date:
    if not raw:
        return date.today()
    return datetime.strptime(raw, "%Y-%m-%d").date()


def _slate_games(repo, d: date) -> list:
    """The stored schedule for a date, fetching it first if we have nothing.

    Reading storage alone was how the assistant ended up telling someone the
    game ids didn't exist: nothing had fetched tonight's schedule into this
    container yet, `list_games` came back empty, and the model filled the gap
    by inventing ids. The page routes all fetch before they read; this has to
    as well.
    """
    games = repo.get_schedule(d)
    if games:
        return games
    try:
        from .data.sources.schedules import MLBScheduleSource
        MLBScheduleSource(repo).fetch_schedule(d)
    except Exception:
        return []
    return repo.get_schedule(d)


def _tool_list_games(repo, season: int, args: dict) -> dict:
    d = _parse_date(args.get("date"))
    games = _slate_games(repo, d)
    rows = []
    for g in games:
        row = {"game_id": g.game_id, "away": g.away_team_id, "home": g.home_team_id,
               "first_pitch": g.first_pitch, "status": getattr(g, "status", None)}
        hs, as_ = getattr(g, "home_score", None), getattr(g, "away_score", None)
        if hs is not None and as_ is not None:
            row["score"] = f"{g.away_team_id} {as_} @ {g.home_team_id} {hs}"
        rows.append(row)
    return {"date": d.isoformat(), "games": rows,
            "note": "No games listed means none are stored for that date."}


def _tool_get_slate(repo, season: int, args: dict) -> dict:
    """Every game tonight with the model's projection already on it.

    The single call the assistant should be making first. It was doing the
    opposite — guessing a game id, simulating one matchup, guessing another —
    and when the guesses missed it told the user the ids didn't exist. The
    simulations are already run and sitting in the cache; this hands them over
    in one payload, so there is nothing to guess.
    """
    from .api.main import CHAT_WAIT_SECONDS, PARK_SEASON
    from .simcache import peek
    from .slate import ensure as warm_slate, wait as wait_slate

    d = _parse_date(args.get("date"))
    games = _slate_games(repo, d)
    if not games:
        return {"date": d.isoformat(), "games": [],
                "note": "No games on this date."}

    # Ask for the slate and wait for it, rather than simulating anything here.
    # The app runs these on startup; this is a reader.
    try:
        warm_slate(repo, d, season=season, park_season=PARK_SEASON)
        wait_slate(d, timeout=CHAT_WAIT_SECONDS)
    except Exception:
        pass

    rows, missing = [], 0
    for g in games:
        row = {"game_id": g.game_id, "away": g.away_team_id,
               "home": g.home_team_id, "first_pitch": g.first_pitch,
               "status": getattr(g, "status", None)}
        hs, as_ = getattr(g, "home_score", None), getattr(g, "away_score", None)
        if hs is not None and as_ is not None:
            row["score"] = f"{g.away_team_id} {as_} @ {g.home_team_id} {hs}"
        try:
            hit = peek(g.game_id, repo, home_team=g.home_team_id,
                       away_team=g.away_team_id)
        except Exception:
            hit = None
        if hit is None:
            missing += 1
        else:
            result, _raw = hit
            row["home_win_probability"] = round(result.home_win_probability, 4)
            row["projected_total"] = round(result.total_mean, 2)
            row["projected_score"] = (f"{g.away_team_id} "
                                      f"{round(result.away_run_mean, 1)} - "
                                      f"{round(result.home_run_mean, 1)} "
                                      f"{g.home_team_id}")
        rows.append(row)

    out = {"date": d.isoformat(), "games": rows,
           "source": "the simulations this app ran for tonight's slate"}
    if missing:
        # Say it rather than let a game with no projection read as a game the
        # model has no opinion about.
        out["note"] = (f"{missing} of {len(rows)} game(s) not simulated yet — "
                       "ask again shortly for those.")
    return out


_PROJECTION_STATS = {
    "pitchers": ("k", "ip", "hits_allowed", "runs_allowed", "bb_allowed", "pitches"),
    "batters": ("hits", "home_runs", "rbi", "k", "bb", "pa"),
}


def _tool_get_projections(repo, season: int, args: dict) -> dict:
    """One stat, ranked across the whole slate, from runs already in hand.

    Asked which pitcher would strike out the most, the assistant had no way to
    compare players across games — so it pulled fifteen full box scores, one
    simulate call at a time, and then ranked them in its head. It got the order
    wrong doing it: it named a pitcher at 6.3 as the leader and listed one at
    6.31 behind him.

    Both problems are the same problem. Sorting is not a thing to do in prose,
    and the numbers were already sitting in the cache.
    """
    from .api.main import CHAT_WAIT_SECONDS, PARK_SEASON
    from .data.names import player_names
    from .simcache import peek
    from .slate import ensure as warm_slate, wait as wait_slate

    kind = str(args.get("kind") or "batters").lower()
    if kind not in _PROJECTION_STATS:
        return {"error": f"kind must be one of {sorted(_PROJECTION_STATS)}"}
    stat = str(args.get("stat") or "").lower()
    if stat not in _PROJECTION_STATS[kind]:
        return {"error": f"stat for {kind} must be one of "
                         f"{list(_PROJECTION_STATS[kind])}"}
    limit = max(1, min(int(args.get("limit") or 8), 25))
    include_bullpen = bool(args.get("include_bullpen"))

    d = _parse_date(args.get("date"))
    games = _slate_games(repo, d)
    if not games:
        return {"date": d.isoformat(), "leaders": [],
                "note": "No games on this date."}
    try:
        warm_slate(repo, d, season=season, park_season=PARK_SEASON)
        wait_slate(d, timeout=CHAT_WAIT_SECONDS)
    except Exception:
        pass

    rows, missing = [], 0
    for g in games:
        try:
            hit = peek(g.game_id, repo, home_team=g.home_team_id,
                       away_team=g.away_team_id)
        except Exception:
            hit = None
        if hit is None:
            missing += 1
            continue
        result, _raw = hit
        lines = (result.pitcher_lines if kind == "pitchers"
                 else result.player_lines)
        for line in lines:
            pid = int(line.get("player_id", 0))
            if pid <= 0 and not include_bullpen:
                # A negative id is the combined bullpen and 0 is a starter who
                # hasn't been named. Neither is a person, and offering one as
                # the answer to "which pitcher" would be wrong twice over.
                continue
            value = line.get(stat)
            if value is None:
                continue
            rows.append({"player_id": pid, "team": line.get("team"),
                         "value": float(value),
                         "game": f"{g.away_team_id} @ {g.home_team_id}"})

    rows.sort(key=lambda r: -r["value"])
    top = rows[:limit]
    names = player_names(repo, [r["player_id"] for r in top if r["player_id"] > 0],
                         season)

    def label(row: dict) -> str:
        pid = row["player_id"]
        if pid < 0:
            return f"{row['team']} bullpen (all relievers combined)"
        if pid == 0:
            return f"{row['team']} starter (not yet announced)"
        return names.get(pid) or f"unidentified player {pid}"

    leaders = [{"rank": i + 1, "name": label(r), "team": r["team"],
                "game": r["game"], stat: round(r["value"], 2)}
               for i, r in enumerate(top)]
    out = {"date": d.isoformat(), "kind": kind, "stat": stat,
           "leaders": leaders,
           "source": ("the simulations already run for this slate, sorted "
                      "here — this order is correct as given")}
    if missing:
        out["note"] = (f"{missing} of {len(games)} game(s) not simulated yet, "
                       "so their players are not in this ranking.")
    return out


def _tool_simulate_what_if(repo, season: int, args: dict) -> dict:
    """Run one game again with a player's rates changed, against the baseline.

    The single exception to everything else here. Ordinary questions are
    answered from simulations already run, because re-running them is slow and
    produces numbers that disagree with the cards. A what-if has no stored
    answer by definition — nobody simulated a healthy Judge — so this one runs
    fresh, and returns the baseline alongside it so the difference is the answer
    rather than a number floating on its own.

    Deliberately not cached: an override is one person's private question and
    would poison the shared run everything else reads.
    """
    from .api.main import PARK_SEASON, _ensure_lineups, _teams_from_game_id
    from .pipeline import simulate_matchup
    from .simcache import SLATE_N, SLATE_SEED, peek

    game_id = _resolve_game_id(repo, args.get("game_id", ""))
    if game_id is None:
        return {"error": f"no game matching {args.get('game_id')!r}",
                "hint": "call get_slate for tonight's games and their ids"}
    home, away = _teams_from_game_id(game_id)
    if not home or not away:
        return {"error": f"could not read teams from game_id {game_id!r}"}

    def as_overrides(raw) -> dict:
        out: dict[int, dict[str, float]] = {}
        for pid, mults in (raw or {}).items():
            try:
                out[int(pid)] = {str(k): float(v) for k, v in mults.items()}
            except (TypeError, ValueError):
                continue
        return out

    batters = as_overrides(args.get("batter_changes"))
    pitchers = as_overrides(args.get("pitcher_changes"))
    if not batters and not pitchers:
        return {"error": "nothing to change — give batter_changes or "
                         "pitcher_changes as {player_id: {stat: multiplier}}"}

    _ensure_lineups(repo, game_id, home, away, season)
    try:
        altered, _raw = simulate_matchup(
            game_id, repo, home_team=home, away_team=away,
            n=SLATE_N, seed=SLATE_SEED, season=season, park_season=PARK_SEASON,
            rate_overrides=batters or None, pitcher_overrides=pitchers or None,
        )
    except Exception as exc:
        return {"error": f"what-if run failed: {type(exc).__name__}: {exc}"}

    out = {
        "game_id": game_id, "home": altered.home, "away": altered.away,
        "source": "a fresh run with your changes applied — not the stored one",
        "with_changes": {
            "home_win_probability": round(altered.home_win_probability, 4),
            "projected_total": round(altered.total_mean, 2),
            "projected_score": {"home": round(altered.home_run_mean, 2),
                                "away": round(altered.away_run_mean, 2)},
        },
    }
    base = peek(game_id, repo, home_team=home, away_team=away)
    if base is not None:
        result, _ = base
        out["baseline"] = {
            "home_win_probability": round(result.home_win_probability, 4),
            "projected_total": round(result.total_mean, 2),
            "projected_score": {"home": round(result.home_run_mean, 2),
                                "away": round(result.away_run_mean, 2)},
        }
        out["shift"] = {
            "home_win_probability": round(
                altered.home_win_probability - result.home_win_probability, 4),
            "projected_total": round(altered.total_mean - result.total_mean, 2),
        }
    return out


def _tool_get_best_bets(repo, season: int, args: dict) -> dict:
    """The ranked plays, from the same simulations and the same posted prices.

    A parlay question used to make the assistant run games itself and assemble
    something out of raw projections, which is both a second opinion nobody
    asked for and how it ended up quoting prices that never existed. The panel
    already does this properly — simulate, price against the configured feed,
    rank by edge — so the assistant reads that instead of re-deriving it.

    Which feed that is travels back in `source`, along with the pricing caveat.
    PrizePicks posts no odds — the payout is on the slip — so the `price` on
    every play is a break-even we derived rather than a number anyone quoted,
    and an assistant that read it as a quote would send someone looking for a
    line that does not exist.
    """
    from .api.main import BEST_BETS_WAIT_SECONDS, CURRENT_SEASON, PARK_SEASON
    from .betting.best_bets import build_best_bets
    from .slate import ensure as warm_slate, wait as wait_slate

    d = _parse_date(args.get("date"))
    limit = max(1, min(int(args.get("limit") or 12), 25))
    edge_only = args.get("with_edge_only", True)

    _slate_games(repo, d)
    try:
        warm_slate(repo, d, season=CURRENT_SEASON, park_season=PARK_SEASON)
        wait_slate(d, timeout=BEST_BETS_WAIT_SECONDS)
    except Exception:
        pass

    report = build_best_bets(repo, d, season=CURRENT_SEASON,
                             park_season=PARK_SEASON)
    bets = report.bets or []
    if edge_only:
        with_edge = [b for b in bets if b.get("has_edge")]
        bets = with_edge or bets[:limit]
    rows = []
    for b in bets[:limit]:
        # Trimmed hard: every field here is resent on every later round, and a
        # recommendation only needs what it is, the price, and why.
        rows.append({
            "game": f"{b.get('away')} @ {b.get('home')}",
            "selection": b.get("selection"),
            "player": b.get("player"),
            "market": b.get("market"),
            "line": b.get("line"),
            "price": b.get("price"),
            "book": b.get("book"),
            "model_probability": round(float(b.get("model_probability") or 0), 4),
            "implied_probability": round(float(b.get("implied_probability") or 0), 4),
            "edge": round(float(b.get("edge") or 0), 4),
            "category": b.get("category"),
            "clears_the_bar": bool(b.get("has_edge")),
            "live": bool(b.get("is_live")),
        })
    from .data.sources.prizepicks import BOOK

    book = getattr(report, "book", "") or BOOK
    caveat = getattr(report, "pricing_note", "")
    return {
        "date": report.date,
        "games_priced": report.games_priced,
        "props_available": report.props_available,
        "plays": rows,
        "source": (f"{book}'s posted prices against this app's simulations; "
                   f"edge is model probability minus the book's implied"),
        # Only present when the feed posts no odds. Sent to the assistant
        # verbatim so it repeats the caveat rather than reporting a derived
        # break-even as a price the user could go and take.
        "pricing_caveat": caveat or None,
        "note": ("Nothing cleared the minimum edge — these are the closest, "
                 "not recommendations.") if rows and not any(
                     r["clears_the_bar"] for r in rows) else None,
    }


def _graded_summary(record: dict, detail: bool) -> dict:
    """What the model needs about a game that has already been played.

    A finished game was scored when it finished; the projection and the result
    are both on disk. Re-simulating it would burn a slate's worth of compute to
    re-derive a number we wrote down days ago — and worse, a fresh run would
    disagree slightly with the graded record the accuracy page is built from,
    so the assistant and the scorecard would quote different projections for
    the same game.
    """
    out = record.get("outcome") or {}
    actual = record.get("actual") or {}
    summary = {
        "game_id": record.get("game_id"), "home": record.get("home"),
        "away": record.get("away"), "status": "final",
        "source": "graded record — this game is over, nothing was simulated",
        "final_score": (f"{record.get('away')} {actual.get('away_runs')} @ "
                        f"{record.get('home')} {actual.get('home_runs')}"),
        "projected_score": {"home": (out.get("home_runs") or {}).get("mean"),
                            "away": (out.get("away_runs") or {}).get("mean")},
        "home_win_probability": out.get("home_win_probability"),
        "picked_winner": out.get("picked_winner"),
        "total": {"projected": (out.get("total") or {}).get("mean"),
                  "actual": (out.get("total") or {}).get("actual"),
                  "inside_p10_p90": (out.get("total") or {}).get("covered")},
    }
    if not detail:
        summary["note"] = ("Per-player projected-vs-actual lines omitted. Ask "
                           "again with detail=true if the question needs them.")
        return summary
    summary["batters"] = [
        {"team": b.get("team"), "name": b.get("name"), "slot": b.get("lineup_slot"),
         **{k: {"projected": v.get("projected"), "actual": v.get("actual")}
            for k, v in (b.get("stats") or {}).items()
            if k in ("hits", "home_runs", "rbi", "k", "bb")}}
        for b in record.get("batters", []) if b.get("played")
    ]
    summary["pitchers"] = [
        {"team": p.get("team"), "name": p.get("name"),
         **{k: {"projected": v.get("projected"), "actual": v.get("actual")}
            for k, v in (p.get("stats") or {}).items()
            if k in ("ip", "k", "hits_allowed", "runs_allowed")}}
        for p in record.get("pitchers", []) if p.get("played")
    ]
    return summary


# Lenient on purpose: this is what lets "2026-08-03 STL at NYY" resolve rather
# than being refused for not being a well-formed id.
from .gameid import date_of as _game_date  # noqa: E402


def _unavailable(repo, teams: list, season: int) -> dict:
    """{team: [{name, reason}]} for regulars the roster says can't play.

    Only players who would otherwise have been in the projected lineup — not
    the whole 40-man injured list, which runs to a dozen names a team and is
    mostly people nobody was going to ask about. Those are the ones a reader
    would notice missing, and the ones a recommendation could wrongly be built
    on.
    """
    from .data.ingest import ROSTER_GAME_ID
    from .data.names import player_names
    from .data.sources.availability import MLBAvailabilitySource

    out: dict = {}
    source = MLBAvailabilitySource()
    for team in teams:
        if not team:
            continue
        # Never fatal. This is a note attached to a projection, and losing the
        # projection because a roster lookup failed would be a poor trade.
        try:
            card = repo.get_lineup(f"{ROSTER_GAME_ID}-{season}", team)
            regulars = list(card.batting_order) if card else []
            if not regulars:
                continue
            roster = source.roster(team)
            if not roster.usable:
                continue
            missing = [pid for pid in regulars if not roster.can_play(pid)]
            if not missing:
                continue
            names = player_names(repo, missing, season)
            reasons = source.label_absences(team, missing)
            out[team] = [{"name": names.get(pid) or f"player {pid}",
                          "reason": reasons.get(pid, "not on the active roster")}
                         for pid in missing]
        except Exception:
            continue
    return out


def _resolve_game_id(repo, raw: str) -> Optional[str]:
    """The real game id behind whatever the model typed, or None.

    It writes "STL-NYY", or "2026-08-03-NYY-STL" with the teams the wrong way
    round, and the old code answered "could not read teams from game_id" — which
    the model relayed to the user as *the games don't exist*. They did. Matching
    against the actual slate turns a formatting slip into the right game.
    """
    from .api.main import _teams_from_game_id

    if not raw:
        return None
    text = str(raw).strip()
    upper = text.upper()
    codes = {c for c in re.split(r"[^A-Z0-9]+", upper) if c and not c.isdigit()}

    # The slate is the arbiter, not the string's shape. `_teams_from_game_id`
    # will happily read teams out of "2026-06-30-XXX-YYY", so trusting a
    # well-formed *looking* id was how a nonexistent game got through to the
    # simulator and came back as an error the model relayed as "no such game".
    days = [d for d in (_game_date(upper), date.today()) if d is not None]
    checked_against_a_slate = False
    for day in dict.fromkeys(days):
        try:
            games = _slate_games(repo, day)
        except Exception:
            continue
        if not games:
            continue
        checked_against_a_slate = True
        for g in games:
            if g.game_id.upper() == upper:
                return g.game_id
        for g in games:
            if {g.home_team_id.upper(), g.away_team_id.upper()} <= codes:
                return g.game_id

    if checked_against_a_slate:
        # We had the slate and this isn't on it. Saying so beats passing an
        # invented id down to the simulator and letting its failure surface as
        # "the games don't exist".
        return None
    # No slate to check against — an unfetchable date, or a schedule we can't
    # reach. Fall back to the old behaviour rather than refusing outright: a
    # well-formed id was accepted before this existed and still should be.
    home, away = _teams_from_game_id(text)
    return text if home and away else None


def _tool_simulate_game(repo, season: int, args: dict) -> dict:
    from .api.main import (CHAT_WAIT_SECONDS, PARK_SEASON, _ensure_lineups,
                           _teams_from_game_id)
    from .data.names import player_names
    from .simcache import SLATE_N, SLATE_SEED, peek, simulate_cached
    from .slate import wait_for_game as warm_game

    game_id = _resolve_game_id(repo, args["game_id"])
    if game_id is None:
        return {"error": f"no game matching {args['game_id']!r}",
                "hint": "call get_slate for tonight's games and their ids"}
    detail = bool(args.get("detail"))

    # Cheapest answer first: a game that has already been played was graded
    # when it finished, so the projection and the result are both on disk.
    stored = repo.get_accuracy_game(game_id)
    if stored and (stored.get("actual") or {}).get("status") == "Final":
        return _graded_summary(stored, detail)

    home, away = _teams_from_game_id(game_id)
    if not home or not away:
        return {"error": f"could not read teams from game_id {game_id!r}"}

    # Next cheapest: the run the site already did for this matchup. The cards
    # and the best-bets panel simulate the slate as the page loads, so by the
    # time anyone is asking about a game the work is usually done. Reusing it
    # is not only faster — it's what makes the answer agree with the card the
    # question was asked about.
    hit = peek(game_id, repo, home_team=home, away_team=away)
    if hit is None:
        # Not warm yet — but the server is very likely working on it right now,
        # because opening the slate starts it. Waiting for that run beats
        # starting a second one: it's faster than a fresh simulation once the
        # queue reaches this game, and it yields the numbers the card will
        # show rather than numbers a percentage point off them.
        game_day = _game_date(game_id)
        if game_day is not None:
            warm_game(game_day, game_id, CHAT_WAIT_SECONDS)
            hit = peek(game_id, repo, home_team=home, away_team=away)

    if hit is not None:
        result, _raw = hit
        source = "the run already behind this game's card — not re-simulated"
    else:
        # Nothing warm and nothing warming it: a date nobody has opened, or a
        # slate that gave up on this game. Run it at the slate's own parameters
        # so it lands in the entry the cards read rather than beside it.
        _ensure_lineups(repo, game_id, home, away, season)
        result, _raw = simulate_cached(
            game_id, repo, home_team=home, away_team=away,
            n=SLATE_N, seed=SLATE_SEED, season=season, park_season=PARK_SEASON,
        )
        source = "simulated now; the cards will reuse this run"

    # `simulate_cached` returns raw lines keyed by player id — the API routes
    # attach names on the way out and this one has to as well. Without it the
    # model receives bare numbers and starts describing people by batting slot,
    # which reads as though the simulation itself were slot-based. It is not:
    # every line is one real player simulated from their own rates.
    names = player_names(
        repo,
        [int(p["player_id"]) for p in result.player_lines]
        + [int(p["player_id"]) for p in result.pitcher_lines],
        season,
    )

    def named(line: dict) -> str:
        """A label the model can use in a sentence.

        Two of these are not people and must not be presented as though a
        lookup failed. A negative id is the team's aggregate bullpen — one
        statline standing in for every reliever, which is how the late innings
        are simulated. Zero means the probable starter has not been announced
        yet, so the sim is using a generic starter profile.
        """
        pid = int(line["player_id"])
        if pid < 0:
            return f"{line['team']} bullpen (all relievers combined)"
        if pid == 0:
            return f"{line['team']} starter (not yet announced)"
        # A name can still be missing if the MLB people lookup is unreachable.
        # Say so rather than handing over a bare number the model might read as
        # an identifier worth repeating.
        return names.get(pid) or f"unidentified player {pid}"
    summary = {
        "game_id": game_id, "home": result.home, "away": result.away,
        "source": source, "simulations": result.n,
        # Who isn't playing, so a recommendation can't be built on someone on
        # the IL. This tool was quoting Aaron Judge a home-run probability
        # while he was on the injured list, because the projected lineup is
        # season usage and knew nothing about availability.
        "unavailable": _unavailable(repo, [home, away], season),
        "home_win_probability": round(result.home_win_probability, 4),
        "projected_score": {
            "home": round(result.home_run_mean, 2),
            "away": round(result.away_run_mean, 2),
        },
        "total": {"mean": round(result.total_mean, 2),
                  "p10": result.total_p10, "p90": result.total_p90},
        "extra_inning_pct": round(result.extra_inning_pct, 4),
    }
    # The box score is the expensive half — roughly four times the summary, and
    # every tool result is resent on every subsequent round, so a question that
    # sweeps the slate pays for it once per game per round. Most questions only
    # ever needed the win probability and the total, so it is now opt-in.
    if not detail:
        summary["note"] = ("Per-player lines omitted. Ask again with "
                           "detail=true if the question needs them.")
        return summary

    summary.update({
        # Trimmed to the fields a conversation actually uses: the full line
        # carries a dozen more per player and would crowd the context for no
        # gain the reader would notice.
        "batters": [
            {"team": p["team"], "name": named(p), "slot": p.get("lineup_slot"),
             "pa": round(p["pa"], 2), "hits": round(p["hits"], 2),
             "home_runs": round(p["home_runs"], 2), "rbi": round(p["rbi"], 2),
             "k": round(p["k"], 2), "bb": round(p["bb"], 2)}
            for p in result.player_lines
        ],
        "pitchers": [
            {"team": p["team"], "name": named(p), "ip": round(p["ip"], 2),
             "k": round(p["k"], 2), "bb_allowed": round(p["bb_allowed"], 2),
             "hits_allowed": round(p["hits_allowed"], 2),
             "runs_allowed": round(p["runs_allowed"], 2),
             "pitches": round(p["pitches"], 1)}
            for p in result.pitcher_lines
        ],
    })
    return summary


def _tool_get_trends(repo, season: int, args: dict) -> dict:
    from .trends import report

    end = date.today()
    games = repo.get_accuracy_games(end - timedelta(days=60), end)
    rep = report(games, asof=end, season=season)
    return {
        "history": rep["history"],
        "this_week": [{"headline": t["headline"], "detail": t["detail"],
                       "moving": t["moving"]} for t in rep["this_week"]],
        "week_ahead": [{"headline": t["headline"], "detail": t["detail"],
                        "range": t.get("range_display"),
                        "confidence": t["confidence"],
                        "window": f"{t['window_start']}..{t['window_end']}"}
                       for t in rep["next_week"]],
        "forecast_scorecard": rep["scorecard"],
    }


def _tool_get_accuracy(repo, season: int, args: dict) -> dict:
    from .accuracy import load_report

    days = max(1, min(60, int(args.get("days") or 7)))
    rep = load_report(repo, end=date.today() - timedelta(days=1), days=days)
    o = rep["outcomes"]
    return {
        "window": rep["window"],
        "outcomes": {k: o[k] for k in o if not isinstance(o[k], (list, dict))},
        # Positions rather than every player: the per-player table runs to
        # hundreds of rows and the useful answer is almost always positional.
        "by_position": rep.get("by_position"),
        "players_graded": len(rep.get("players") or []),
    }


def _tool_get_league_history(repo, season: int, args: dict) -> dict:
    from .baseball import _METRICS
    from .league_history import load

    hist = load()
    if not hist:
        return {"available": False,
                "note": "No league history on file yet; it is fetched by the "
                        "scheduled job."}
    seasons = ([int(args["season"])] if args.get("season") else hist.seasons)
    out = {}
    for s in seasons:
        levels = {}
        for metric in _METRICS:
            lvl = hist.level(metric, season=s)
            if lvl is not None:
                levels[metric] = round(lvl, 4)
        if levels:
            out[str(s)] = levels
    return {"available": True, "games_on_file": hist.game_count,
            "seasons": hist.seasons, "levels_per_game": out}


def _tool_find_player(repo, season: int, args: dict) -> dict:
    from .api.main import CURRENT_SEASON

    needle = (args.get("name") or "").strip().lower()
    if not needle:
        return {"error": "name is required"}
    hits: list[dict] = []
    # Newest season first, and stop at the first that matches: a callup may only
    # have last year on file, and last year's real line beats no answer.
    for yr in (season, CURRENT_SEASON, CURRENT_SEASON - 1):
        for kind, fetch in (("batter", repo.get_batters_for_season),
                            ("pitcher", repo.get_pitchers_for_season)):
            try:
                rows = fetch(yr)
            except Exception:
                continue
            for r in rows:
                name = getattr(r, "name", "") or ""
                if needle in name.lower():
                    hits.append({
                        "kind": kind, "season": yr, "name": name,
                        "player_id": getattr(r, "player_id", None),
                        "team": getattr(r, "team_id", None),
                        "stats": {k: round(v, 4) for k, v in vars(r).items()
                                  if isinstance(v, (int, float))
                                  and k not in ("player_id", "season")},
                    })
        if hits:
            break
    if not hits:
        return {"found": False, "note": f"No player matching {args['name']!r}."}
    return {"found": True, "matches": hits[:5]}


_DISPATCH: dict[str, Callable[[Any, int, dict], dict]] = {
    "get_slate": _tool_get_slate,
    "get_best_bets": _tool_get_best_bets,
    "get_projections": _tool_get_projections,
    "simulate_what_if": _tool_simulate_what_if,
    "list_games": _tool_list_games,
    "simulate_game": _tool_simulate_game,
    "get_trends": _tool_get_trends,
    "get_accuracy": _tool_get_accuracy,
    "get_league_history": _tool_get_league_history,
    "find_player": _tool_find_player,
}


def run_tool(name: str, args: dict, repo, season: int) -> tuple[str, bool]:
    """Execute one tool. Returns `(payload, is_error)`.

    A failing tool comes back as a readable error rather than an exception, so
    the model can try a different route or tell the user plainly — a traceback
    that kills the stream helps nobody.
    """
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"No such tool: {name}", True
    try:
        return json.dumps(fn(repo, season, args or {}), default=str), False
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}", True


# ── the conversation ────────────────────────────────────────────────────────

SYSTEM = """You are the assistant inside The Beast, an MLB Monte Carlo \
simulation app, talking to its owner about tonight's slate and about baseball.

Answer the question that was asked. Nothing else.

Length: one or two sentences for a simple question. A short paragraph for a \
real analytical one. Only go longer if asked to.

Do not:
- restate the question before answering it
- explain what you are about to do, or narrate which tool you used
- add background, caveats, or context nobody asked for
- offer follow-ups, suggestions, or "would you like me to..."
- use headers or bullets unless comparing several things at once
- end with a summary of what you just said

If the answer is a number, lead with the number. If it is a name, lead with \
the name.

Use your tools rather than memory for anything about the current slate, a \
specific projection, league trends, or the model's accuracy — your training \
data does not know tonight's lineups. Answer general baseball questions \
directly; there is nothing to look up.

Everything here comes from one place: the simulations this app ran for \
tonight's slate. `get_slate` hands you all of them at once and is where to \
start for anything about tonight. `get_best_bets` prices those same \
simulations against the posted lines and ranks the disagreements — use \
it for every question about bets, parlays, props, edges or value. It names \
the book it used; never name a different one, and never quote a price it \
didn't give you.

To compare players across games — most strikeouts, most likely to homer, most \
hits — use `get_projections`. It reads the same simulations and sorts them for \
you. `simulate_game` with detail is for one game you have already been asked \
about, never for building a comparison a game at a time.

Never rank things yourself when a tool returns them ranked, and never round \
before comparing: 6.31 is more than 6.3.

The slate is simulated before you are asked anything, so every ordinary \
question is a lookup. `simulate_what_if` is the one exception and the only \
tool that runs a new simulation — use it when the user asks something the \
stored runs cannot answer, like a player being healthy or a pitcher being \
sharper than his rates. Give the change against the baseline, not on its own.

Never build a recommendation by simulating games one at a time and comparing \
them yourself; that is a second opinion nobody asked for and it will not match \
what the user is looking at. Never state a price, a line or a game id you did \
not get from a tool. If a game id doesn't resolve, call `get_slate` and use \
the ids it returns — do not tell the user the games don't exist.

Every batter and pitcher in a simulation is an individual, simulated from \
their own season rates. Refer to players by name.

A `source` field says where a number came from. It is provenance, not part of \
the answer — mention it only if asked where a figure came from. A game marked \
`status: final` has been played: give the result, and treat the projection as \
something to compare against it rather than as a forecast.

Never recommend or project a player listed under `unavailable`; he is not \
playing. If someone asks about him, say he is out and why. When a team's \
regular is missing, that is worth one clause — a lineup without its best \
hitter is a different lineup.

Be straight about uncertainty in one clause, not a paragraph. A win \
probability near .500 is a coin flip; a projection is the middle of a wide \
distribution. If a tool returns nothing, say the data is not there rather \
than inventing a number."""


def _trim(messages: list[dict]) -> list[dict]:
    """Keep the tail of the conversation, starting on a user turn.

    The API requires the first message to be a user turn, and a naive slice can
    cut into the middle of a tool exchange — an assistant `tool_use` whose
    matching `tool_result` got dropped is a 400, not a degraded answer.
    """
    out = messages[-MAX_TURNS:]
    while out and out[0].get("role") != "user":
        out = out[1:]
    return out


def stream_reply(messages: list[dict], repo, season: int) -> Iterator[dict]:
    """Answer the conversation, yielding events as they happen.

    Events are `{"type": ...}` dicts the endpoint forwards to the browser:
    `text` for a chunk of the answer, `tool` when a lookup starts, `done` at
    the end, `error` if something broke. Streaming is what makes tool use
    tolerable to sit through — the user sees "checking the slate" rather than
    a spinner that lasts as long as a simulation.
    """
    import anthropic

    # Pass the key explicitly rather than letting the SDK read the environment,
    # so the stripped value is the one that actually gets used.
    client = anthropic.Anthropic(api_key=api_key())
    convo = _trim([dict(m) for m in messages])

    for _round in range(MAX_TOOL_ROUNDS):
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM,
                tools=TOOLS,
                messages=convo,
                **_request_extras(),
            ) as stream:
                for text in stream.text_stream:
                    yield {"type": "text", "text": text}
                final = stream.get_final_message()
        except anthropic.AuthenticationError:
            # The key reached Anthropic and was refused. Almost always a paste
            # accident rather than a broken account, so say what to check
            # instead of surfacing a raw 401 the reader has to decode.
            yield {"type": "error", "message": KEY_REJECTED}
            return
        except anthropic.RateLimitError:
            yield {"type": "error",
                   "message": "Anthropic is rate-limiting this key right now. "
                              "Wait a moment and ask again."}
            return
        except anthropic.BadRequestError as exc:
            # An unfunded account fails here, not at the key check: the key is
            # valid, it just has no balance behind it. Left raw it is a wall of
            # exception text; named, it is a two-minute fix.
            if "credit balance" in str(exc).lower():
                yield {"type": "error", "message": NO_CREDIT}
                return
            raise

        if final.stop_reason != "tool_use":
            yield {"type": "done"}
            return

        calls = [b for b in final.content if b.type == "tool_use"]
        convo.append({"role": "assistant", "content": final.content})
        results = []
        for call in calls:
            yield {"type": "tool", "name": call.name}
            payload, is_error = run_tool(call.name, call.input, repo, season)
            results.append({"type": "tool_result", "tool_use_id": call.id,
                            "content": payload, "is_error": is_error})
        # Every result goes back in one user message — splitting them across
        # messages teaches the model to stop calling tools in parallel.
        convo.append({"role": "user", "content": results})

    yield {"type": "error",
           "message": "Gave up after too many lookups without an answer."}


# ── rate limiting ───────────────────────────────────────────────────────────

_HITS: dict[str, list[float]] = {}
RATE_LIMIT = 20          # messages
RATE_WINDOW = 300.0      # seconds


def rate_limited(who: str, *, now: Optional[float] = None) -> bool:
    """Crude per-caller throttle.

    In-process and therefore reset by every deploy, which is the right shape
    for the threat: this is a spend guard on a key the owner is paying for, not
    a security control. Anything stronger belongs in front of the app.
    """
    now = now if now is not None else time.monotonic()
    hits = [t for t in _HITS.get(who, []) if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        _HITS[who] = hits
        return True
    hits.append(now)
    _HITS[who] = hits
    return False
