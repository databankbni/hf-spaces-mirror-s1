"""One simulation of a slate, run by the server, that everything else waits for.

Three things wanted the same fifteen Monte Carlo runs, and each started its own:
the matchup cards (fifteen calls driven from the browser), the best-bets ranker
(the whole slate, server-side) and the assistant (whatever game was asked
about). `simcache` stops two callers duplicating a game they ask for at the
same instant, but it can't help with the two ways they actually collided:

**They arrived at different moments.** The ranker builds while the cards are
still working through the slate, so it reaches a game before the card gets
there and runs it itself. Whoever is second gets a cache hit; whoever is third
usually isn't, because by then the assistant is asking too.

**The browser skipped the server.** The cards keep their results in
sessionStorage and don't re-request a game they already have. So on a revisit —
or after a container restart, which empties the server's cache but not the
browser's — the page looks fully simulated while the server holds nothing at
all. The assistant then had no choice but to run the game itself, which is
exactly the "why is it simulating again?" the user was seeing.

The fix is to stop letting the readers drive. The server simulates the slate
once, in the background, and the cards, the ranker and the assistant all read
that. None of them run anything of their own; the slowest thing any of them
does now is wait, which is the trade the owner asked for explicitly.

Results land in `simcache`, so this module holds progress and nothing else. It
is the scheduler; that is still the store.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date as date_type
from typing import Optional

from .simcache import SLATE_N, SLATE_SEED, simulate_cached


@dataclass
class SlateProgress:
    """What the warm-up has managed so far. Safe to read from any thread."""

    date: str
    total: int = 0
    done: int = 0
    # idle | running | ready | partial | cancelled. `partial` is finished-with-
    # gaps, and it is a separate state from `ready` on purpose: everything
    # downstream is supposed to wait for the simulations, and "finished" meaning
    # two different things is how a reader ends up building on half a slate
    # without knowing it.
    state: str = "idle"
    failed: list[str] = field(default_factory=list)
    # {game_id: last error}. A failure list with no reasons on it told nobody
    # anything — not the page, and not me: a game stopped simulating and the
    # only way to find out why was to reproduce it by hand.
    reasons: dict = field(default_factory=dict)
    attempts: int = 0
    # How many sides have a lineup MLB has actually posted, out of two per
    # game. Worth surfacing: a projection and a confirmed card are different
    # claims, and a reader should be able to tell which they're looking at.
    confirmed: int = 0
    lineup_slots: int = 0
    # True while the background watcher is still checking for posted lineups.
    watching: bool = False
    resimulated: int = 0
    started_at: float = 0.0
    finished_at: Optional[float] = None

    @property
    def running(self) -> bool:
        return self.state in ("idle", "running")

    @property
    def complete(self) -> bool:
        """Every game on the slate has a simulation behind it."""
        return self.state == "ready" and not self.failed

    def as_dict(self) -> dict:
        elapsed = (self.finished_at or time.time()) - self.started_at
        return {
            "date": self.date, "total": self.total, "done": self.done,
            "state": self.state, "failed": self.failed,
            "reasons": self.reasons, "attempts": self.attempts,
            "confirmed": self.confirmed, "lineup_slots": self.lineup_slots,
            "watching": self.watching, "resimulated": self.resimulated,
            "complete": self.complete, "running": self.running,
            "elapsed_seconds": round(elapsed, 1) if self.started_at else 0.0,
        }


class _Slate:
    def __init__(self, day: str) -> None:
        self.progress = SlateProgress(date=day)
        # One event for the whole slate, and one per game. A reader waiting on
        # a single matchup shouldn't have to sit through the other fourteen.
        self.finished = threading.Event()
        self.games: dict[str, threading.Event] = {}
        self.lock = threading.Lock()
        # Set when this warm-up has been superseded — by a re-run, usually.
        # Without it the old thread keeps grinding through a slate nobody is
        # waiting on, holding the CPU lock against the run that replaced it.
        self.cancelled = threading.Event()

    def event_for(self, game_id: str) -> threading.Event:
        with self.lock:
            ev = self.games.get(game_id)
            if ev is None:
                ev = self.games[game_id] = threading.Event()
            return ev


_SLATES: dict[str, _Slate] = {}
_GUARD = threading.Lock()

# Browsing back through a week opens a warm-up per date. The simulator is
# GIL-bound, so letting several run at once makes all of them slower and starves
# the request handlers besides — the container has two shared cores. This is
# held for one game at a time rather than one slate, so a date opened just now
# starts making visible progress instead of sitting behind a full slate.
_CPU = threading.Lock()

# Warm-up records are small, but a long session browsing dates shouldn't grow
# them without limit. The simulations themselves are bounded by `simcache`.
_MAX_SLATES = 24

# A game that fails the first pass has usually failed on a lineup or schedule
# fetch that hadn't landed yet, not because it can't be simulated — so it gets
# tried again rather than written off, which is what left slates finishing with
# games missing. Bounded, because a genuinely unsimulatable game (postponed, no
# lineup posted all night) must not hold the slate open forever.
MAX_ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 5.0

# Lineups are posted a few hours before first pitch, so the interesting window
# is entirely *before* anything is live. Nothing was watching it: the page
# polled only while a game was in progress, and the server simulated the slate
# once and never looked again — so a card posted at four o'clock reached the app
# whenever somebody happened to reload.
WATCH_INTERVAL_SECONDS = 300.0

# Watching stops when every game is over. These are MLB's terminal states.
_FINAL_STATES = {"final", "game over", "completed early"}


def _run(slate: _Slate, repo, day: date_type, season: int, park_season: int) -> None:
    """Simulate the slate, one game at a time, marking each as it lands."""
    from .api.main import _ensure_lineups

    try:
        games = repo.get_schedule(day)
    except Exception:
        games = []

    # Every game on the slate, finished ones included. A card still shows a
    # projection for a game that's over — that's the whole point of the accuracy
    # view — so skipping them here wouldn't save the work, it would just push it
    # back onto whoever asked first, one blocking run at a time. Which is the
    # behaviour this module exists to remove.
    slate.progress.total = len(games)
    slate.progress.state = "running"

    def attempt(g) -> bool:
        try:
            with _CPU:
                _ensure_lineups(repo, g.game_id, g.home_team_id,
                                g.away_team_id, season)
                simulate_cached(
                    g.game_id, repo, home_team=g.home_team_id,
                    away_team=g.away_team_id, n=SLATE_N, seed=SLATE_SEED,
                    season=season, park_season=park_season,
                )
            slate.progress.reasons.pop(g.game_id, None)
            return True
        except Exception as exc:
            slate.progress.reasons[g.game_id] = f"{type(exc).__name__}: {exc}"[:200]
            return False

    # Sequential on purpose. The simulator is pure-Python and GIL-bound, so
    # running two at once is measurably slower than running them in turn — and
    # it would starve the request handlers that make the page respond at all.
    pending = list(games)
    for round_number in range(1, MAX_ATTEMPTS + 1):
        if slate.cancelled.is_set():
            break
        slate.progress.attempts = round_number
        still_failing = []
        for g in pending:
            if slate.cancelled.is_set():
                break
            if attempt(g):
                if round_number == 1:
                    slate.progress.done += 1
                else:
                    # A retry that lands is a game recovered, not a new one.
                    slate.progress.failed = [f for f in slate.progress.failed
                                             if f != g.game_id]
            else:
                still_failing.append(g)
                if round_number == 1:
                    slate.progress.done += 1
                    slate.progress.failed.append(g.game_id)
            # Release waiters on the first pass only; a reader blocked on this
            # game shouldn't sit through the retries as well.
            if round_number == 1:
                slate.event_for(g.game_id).set()
        pending = still_failing
        if not pending:
            break
        # Most first-pass failures are a lineup or schedule fetch that hadn't
        # landed yet rather than a game that can't be simulated at all, so a
        # short pause before trying again recovers most of them.
        if round_number < MAX_ATTEMPTS:
            time.sleep(RETRY_PAUSE_SECONDS)

    # Anything that survived every attempt gets its waiters released now.
    for g in pending:
        slate.event_for(g.game_id).set()

    if slate.cancelled.is_set():
        slate.progress.state = "cancelled"
    else:
        slate.progress.state = "partial" if slate.progress.failed else "ready"
    slate.progress.finished_at = time.time()
    _count_confirmed(slate, repo, day)
    # Release anyone waiting on a game that isn't on this slate at all, rather
    # than leaving them to time out.
    with slate.lock:
        stragglers = list(slate.games.values())
    for ev in stragglers:
        ev.set()
    slate.finished.set()

    # Everything downstream is unblocked now; the thread stays alive to watch
    # for lineups being posted.
    _watch(slate, repo, day, season, park_season)


def _count_confirmed(slate: _Slate, repo, day: date_type) -> None:
    """How many sides have a card MLB has actually posted."""
    try:
        games = repo.get_schedule(day)
    except Exception:
        return
    confirmed = slots = 0
    for g in games:
        for team in (g.home_team_id, g.away_team_id):
            slots += 1
            try:
                lc = repo.get_lineup(g.game_id, team)
            except Exception:
                continue
            if lc is not None and lc.confirmed:
                confirmed += 1
    slate.progress.confirmed = confirmed
    slate.progress.lineup_slots = slots


def _all_final(repo, day: date_type) -> bool:
    try:
        games = repo.get_schedule(day)
    except Exception:
        return False
    if not games:
        return False
    return all(str(getattr(g, "status", "") or "").lower() in _FINAL_STATES
               for g in games)


def _watch(slate: _Slate, repo, day: date_type, season: int,
           park_season: int) -> None:
    """Keep re-checking for posted lineups, and re-simulate when one lands.

    MLB posts a card a few hours before first pitch. Nothing was looking for it:
    the page polled only while a game was already in progress — which is after
    the window that matters — and the server simulated the slate once on open
    and never again. So a lineup posted at four o'clock reached the app whenever
    somebody next happened to reload, which for the Washington game meant not at
    all.

    Re-running `simulate_cached` is how the check is made as well as the fix:
    its key carries a fingerprint of both batting orders, so an unchanged game
    is a cache hit costing nothing and a newly posted card misses and
    re-simulates by itself. A pass over a quiet slate is fifteen lookups.
    """
    if day != date_type.today():
        return  # past and future dates don't get lineups posted at them
    from .api.main import _ensure_lineups

    slate.progress.watching = True
    try:
        while not slate.cancelled.wait(WATCH_INTERVAL_SECONDS):
            if _all_final(repo, day):
                return
            # Snapshot *before* fetching. Taking it afterwards compares the new
            # lineups against themselves, so a posted card looked like no change
            # at all and nothing was ever counted as re-simulated.
            try:
                before = {g.game_id: _fingerprint(repo, g)
                          for g in repo.get_schedule(day)}
            except Exception:
                before = {}
            try:
                from .data.sources.schedules import MLBScheduleSource
                MLBScheduleSource(repo).fetch_schedule(day)
            except Exception:
                continue  # unreachable source: try again next time round

            try:
                games = repo.get_schedule(day)
            except Exception:
                continue
            for g in games:
                if slate.cancelled.is_set():
                    return
                try:
                    with _CPU:
                        _ensure_lineups(repo, g.game_id, g.home_team_id,
                                        g.away_team_id, season)
                        simulate_cached(
                            g.game_id, repo, home_team=g.home_team_id,
                            away_team=g.away_team_id, n=SLATE_N,
                            seed=SLATE_SEED, season=season,
                            park_season=park_season,
                        )
                except Exception as exc:
                    slate.progress.reasons[g.game_id] = \
                        f"{type(exc).__name__}: {exc}"[:200]
                    continue
                if _fingerprint(repo, g) != before.get(g.game_id):
                    slate.progress.resimulated += 1
                    # A game that failed the opening pass often succeeds once
                    # its lineup is posted, so this is its way back in.
                    slate.progress.failed = [f for f in slate.progress.failed
                                             if f != g.game_id]
                    slate.progress.reasons.pop(g.game_id, None)
            if not slate.progress.failed and slate.progress.state == "partial":
                slate.progress.state = "ready"
            _count_confirmed(slate, repo, day)
    finally:
        slate.progress.watching = False


def _fingerprint(repo, g) -> tuple:
    """What the stored lineups look like right now, for change detection."""
    out = []
    for team in (g.home_team_id, g.away_team_id):
        try:
            lc = repo.get_lineup(g.game_id, team)
        except Exception:
            lc = None
        out.append(None if lc is None
                   else (tuple(lc.batting_order), lc.starter_id, lc.confirmed))
    return tuple(out)


def ensure(repo, day: date_type, *, season: int, park_season: int) -> SlateProgress:
    """Start warming this slate if nobody has. Returns immediately either way."""
    key = day.isoformat()
    with _GUARD:
        slate = _SLATES.get(key)
        if slate is not None:
            return slate.progress
        if len(_SLATES) >= _MAX_SLATES:
            # Oldest first, and only ones that have finished — evicting a slate
            # mid-run would orphan everyone waiting on it.
            for old, rec in list(_SLATES.items()):
                if len(_SLATES) < _MAX_SLATES:
                    break
                if rec.progress.state == "ready":
                    _SLATES.pop(old, None)
        slate = _SLATES[key] = _Slate(key)
        slate.progress.started_at = time.time()
        slate.progress.state = "running"
    threading.Thread(
        target=_run, args=(slate, repo, day, season, park_season),
        name=f"slate-warm-{key}", daemon=True,
    ).start()
    return slate.progress


def status(day: date_type) -> Optional[SlateProgress]:
    with _GUARD:
        slate = _SLATES.get(day.isoformat())
    return None if slate is None else slate.progress


def wait(day: date_type, timeout: float) -> Optional[SlateProgress]:
    """Block until the whole slate is warm, or the timeout runs out."""
    with _GUARD:
        slate = _SLATES.get(day.isoformat())
    if slate is None:
        return None
    slate.finished.wait(timeout)
    return slate.progress


def wait_for_game(day: date_type, game_id: str, timeout: float) -> bool:
    """Block until this one game is warm. False if it isn't being warmed.

    What the assistant calls before deciding to simulate anything: if the slate
    is already working on the game, waiting for it is strictly better than
    starting a second run of it — faster, and it yields the same numbers the
    card will show rather than numbers a percentage point off.
    """
    with _GUARD:
        slate = _SLATES.get(day.isoformat())
    if slate is None:
        return False
    # A slate that has already finished has nothing left to wait for. Without
    # this, asking about a game that wasn't on it — a postponement, a mistyped
    # id — would mint a fresh event nobody will ever set and block on it for the
    # full timeout.
    if slate.finished.is_set():
        return True
    return slate.event_for(game_id).wait(timeout)


def reset(day: Optional[date_type] = None) -> None:
    """Forget warm-up state so the next `ensure` starts over.

    Paired with `simcache.clear` by the re-run button: dropping the cached runs
    without dropping the "already warmed" flag would leave a slate marked ready
    with nothing behind it.
    """
    with _GUARD:
        if day is None:
            dropped = list(_SLATES.values())
            _SLATES.clear()
        else:
            gone = _SLATES.pop(day.isoformat(), None)
            dropped = [gone] if gone is not None else []
    # Tell the threads to stop, and release anyone still waiting on them. A
    # dropped warm-up that kept running would hold the CPU lock against the
    # run that replaced it, so the re-run would be slower than the original.
    for slate in dropped:
        slate.cancelled.set()
        slate.finished.set()
        with slate.lock:
            for ev in slate.games.values():
                ev.set()
