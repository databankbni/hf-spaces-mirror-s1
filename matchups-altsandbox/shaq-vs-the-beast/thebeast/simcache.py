"""One simulation per matchup, shared by everything that needs it.

The matchup cards and the best-bets ranker both want a Monte Carlo run for
every game on the slate. Run separately they cost twice the compute and — worse
— disagree, because two runs of a stochastic model with different sample sizes
land a percentage point or so apart. A user then sees one win probability on
the card and a slightly different one backing the bet beside it.

This module makes them the same run. `simulate_cached` is a memoized
`simulate_matchup`: the first caller pays for the simulation, everyone after
gets the identical arrays back.

Two details matter:

**Lineups invalidate it.** The key carries a fingerprint of both batting orders
and both starters, so the moment a projected lineup is replaced by a confirmed
one the key changes and the game re-simulates. That's what makes it safe to
hold a result indefinitely instead of guessing at a TTL — nothing about the
matchup can change without the key changing with it.

**Concurrent callers wait rather than duplicate.** The page fires the card sims
and the best-bets build at once, so without a per-key lock both would miss the
cache and run the same simulation twice. The simulation is pure-Python and
GIL-bound, so running two at once is measurably *slower* than running one after
the other — the second caller blocking on the first is strictly the better
outcome.

**The key is normalised.** Callers spell the same request differently — the
card names every knob, the ranker names none — so parameters left at their
default are dropped from the key rather than carried in it. Without that, two
identical requests produced two keys and two simulations, which is the failure
this module exists to prevent.

Only unmodified simulations are cached. A what-if run with per-player
overrides is one caller's private question and never enters the cache.

`peek` is the read-only door in: it returns a run already in hand for a matchup
and never starts one.
"""
from __future__ import annotations

import inspect
import threading
from typing import Optional

# What the slate is simulated with. The matchup cards, the best-bets ranker and
# the assistant all name these rather than each picking their own, because the
# sample size and seed are part of the cache key: a caller that asks for 1500
# draws cannot be handed the 2000-draw run the page already did, however much
# it would like to be.
SLATE_N = 2000
SLATE_SEED = 7

# {key: (result, raw)} — every entry is an unmodified simulation of one game.
_CACHE: dict[tuple, tuple] = {}
# One lock per key, so two callers wanting the same game serialize while
# callers wanting different games don't block each other. `_LOCKS_GUARD`
# protects the lock registry itself.
_LOCKS: dict[tuple, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_DEFAULTS: Optional[dict] = None

# A slate is ~15 games and a handful of dates stay interesting at once; well
# past that, the oldest entries are dropped. Each entry holds the raw arrays
# for one game, so this is bounded memory, not a leak.
_MAX_ENTRIES = 120


def _lineup_fingerprint(repo, game_id: str, home: str, away: str) -> tuple:
    """What the simulation depends on about the lineups.

    Two runs are interchangeable only if both batting orders and both starters
    match. Anything else — a confirmed card replacing a projection, a late
    scratch, a starter change — has to produce a different key.
    """
    from .pipeline import resolve_lineups

    try:
        home_lu, away_lu = resolve_lineups(game_id, repo, home, away)
    except Exception:
        # Unresolvable lineups can't be fingerprinted, so this run is not
        # shareable — a unique marker keeps it out of everyone else's way.
        return ("unresolved", object())
    return (
        tuple(home_lu.batting_order), home_lu.starter_id, home_lu.confirmed,
        tuple(away_lu.batting_order), away_lu.starter_id, away_lu.confirmed,
    )


def _defaults() -> dict:
    """`simulate_matchup`'s keyword defaults, read once from its signature."""
    global _DEFAULTS
    if _DEFAULTS is None:
        from .pipeline import simulate_matchup

        _DEFAULTS = {
            name: p.default
            for name, p in inspect.signature(simulate_matchup).parameters.items()
            if p.default is not inspect.Parameter.empty
        }
    return _DEFAULTS


def _canonical(kwargs: dict) -> tuple:
    """Only the kwargs that actually differ from a default run.

    Two callers asking for the same simulation must land on the same key even
    when one spells out the defaults and the other leaves them off. They didn't:
    the matchup card passes `shrink_pa=200` and friends explicitly, the ranker
    passes nothing at all, and a raw `sorted(kwargs.items())` made those two
    different keys for identical work. The sharing this module is named for was
    quietly not happening.
    """
    defaults = _defaults()
    return tuple(sorted(
        (k, v) for k, v in kwargs.items()
        if k not in defaults or v != defaults[k]
    ))


def _key_lock(key: tuple) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.Lock()
        return lock


def simulate_cached(
    game_id: str,
    repo,
    *,
    home_team: str,
    away_team: str,
    n: int,
    seed: Optional[int],
    season: int,
    park_season: int,
    **kwargs,
) -> tuple:
    """`simulate_matchup`, run once per (matchup, parameters, lineup).

    Returns the same `(result, raw)` tuple `simulate_matchup` does. Callers
    must treat it as read-only — it is shared, so mutating it would corrupt
    every other caller's copy.
    """
    from .pipeline import simulate_matchup

    # `representative` is settled here rather than by the caller. It adds a
    # sample game to the output and changes none of the aggregates, so a run
    # made with it satisfies a caller who didn't ask for it — but keeping it in
    # the key split the card's run from the ranker's over an extra field
    # neither of them disagreed about. One extra game out of `n` is the whole
    # cost of always having it.
    kwargs.pop("representative", None)
    key = (game_id, home_team, away_team, n, seed, season, park_season,
           _canonical(kwargs),
           _lineup_fingerprint(repo, game_id, home_team, away_team))

    hit = _CACHE.get(key)
    if hit is not None:
        return hit

    with _key_lock(key):
        # Re-check inside the lock: whoever held it may have just filled this in.
        hit = _CACHE.get(key)
        if hit is not None:
            return hit
        out = simulate_matchup(
            game_id, repo, home_team=home_team, away_team=away_team,
            n=n, seed=seed, season=season, park_season=park_season,
            representative=True, **kwargs,
        )
        if len(_CACHE) >= _MAX_ENTRIES:
            for stale in list(_CACHE)[:len(_CACHE) - _MAX_ENTRIES + 1]:
                _CACHE.pop(stale, None)
                with _LOCKS_GUARD:
                    _LOCKS.pop(stale, None)
        _CACHE[key] = out
        return out


def peek(game_id: str, repo, *, home_team: str, away_team: str) -> Optional[tuple]:
    """A run already in hand for this matchup, or None. Never simulates.

    For readers that would rather answer from what the site has already
    computed than start their own Monte Carlo — the assistant, mainly, which
    was running a fresh slate of simulations per question and reporting numbers
    a percentage point off the cards the user was looking at while asking.

    Sample size and seed are not required to match, so a run at any `n` will
    do; the lineup fingerprint is. That's the line worth holding: a bigger or
    smaller sample of the same matchup is the same answer with a different
    error bar, whereas a run from before the lineup was confirmed is an answer
    to a question nobody is asking any more.
    """
    fingerprint = _lineup_fingerprint(repo, game_id, home_team, away_team)
    best: Optional[tuple] = None
    for key, entry in _CACHE.items():
        if key[0] != game_id or key[-1] != fingerprint:
            continue
        # Widest sample wins, and the later entry wins a tie — it was run
        # against the more recent view of everything outside the fingerprint.
        if best is None or key[3] >= best[0]:
            best = (key[3], entry)
    return None if best is None else best[1]


def clear(game_ids: Optional[set] = None) -> int:
    """Drop cached runs; everything, or just the given games.

    A manual re-run has to actually re-run — otherwise the button would
    re-fetch the odds and hand back the same simulation it already had.
    """
    if game_ids is None:
        dropped = len(_CACHE)
        _CACHE.clear()
        with _LOCKS_GUARD:
            _LOCKS.clear()
        return dropped
    stale = [k for k in _CACHE if k[0] in game_ids]
    for k in stale:
        _CACHE.pop(k, None)
        with _LOCKS_GUARD:
            _LOCKS.pop(k, None)
    return len(stale)


def stats() -> dict:
    return {"entries": len(_CACHE), "max_entries": _MAX_ENTRIES}
