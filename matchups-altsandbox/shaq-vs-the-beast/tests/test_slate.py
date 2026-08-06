"""The server-side slate warm-up: one simulation everything else waits for.

What's worth pinning here is not that it simulates — that's `simcache`'s job —
but that it is the only thing that does, that readers block on it instead of
starting their own runs, and that a game which can't be simulated releases its
waiters instead of stranding them.
"""
from __future__ import annotations

import threading
import time
from datetime import date

import pytest

from thebeast import slate


class FakeGame:
    def __init__(self, game_id, home="BAL", away="CWS", status="Scheduled"):
        self.game_id = game_id
        self.home_team_id = home
        self.away_team_id = away
        self.status = status


class FakeRepo:
    def __init__(self, games):
        self._games = games

    def get_schedule(self, day):
        return self._games


DAY = date(2026, 6, 30)


def _settle(timeout=20.0):
    """Cancel every warm-up and wait for its thread to notice.

    A test that starts a warm-up and doesn't wait for it leaks that thread into
    the next test, where it calls whatever `simulate_cached` is patched to *now*
    and writes into that test's records — which made
    `test_finished_games_are_warmed_too` fail about one run in three.

    `reset` first, then join: cancelling is what makes the join quick. Joining
    an uncancelled slate means sitting through the rest of its games, and with
    a global CPU lock that queue is every other suite's warm-ups too.
    """
    slate.reset()
    deadline = time.time() + timeout
    for t in threading.enumerate():
        if t.name.startswith("slate-warm-"):
            t.join(max(0.0, deadline - time.time()))


@pytest.fixture(autouse=True)
def _clean():
    _settle()
    yield
    _settle()


def _patch_sim(monkeypatch, runs, delay=0.0, fail=()):
    def fake(game_id, repo, **kwargs):
        time.sleep(delay)
        if game_id in fail:
            raise RuntimeError("no lineup")
        runs.append(game_id)
        return ("result", "raw")

    monkeypatch.setattr(slate, "simulate_cached", fake)
    monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)


class TestWarming:
    def test_it_simulates_every_game_once(self, monkeypatch):
        runs: list[str] = []
        _patch_sim(monkeypatch, runs)
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(4)])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=10)

        assert sorted(runs) == ["g0", "g1", "g2", "g3"]
        assert slate.status(DAY).state == "ready"
        assert slate.status(DAY).done == 4

    def test_a_second_caller_does_not_start_a_second_warm_up(self, monkeypatch):
        """The whole point. `/api/games`, the ranked plays and the assistant all
        call `ensure`; if each started a run the slate would be simulated three
        times over, which is the bug this module exists to close."""
        runs: list[str] = []
        _patch_sim(monkeypatch, runs, delay=0.02)
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(5)])

        for _ in range(3):
            slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=10)

        assert runs == ["g0", "g1", "g2", "g3", "g4"], "each game exactly once"

    def test_ensure_returns_immediately(self, monkeypatch):
        """It is called from `/api/games`, which renders the page. A warm-up
        that blocked there would trade one problem for a worse one."""
        _patch_sim(monkeypatch, [], delay=0.3)
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(6)])

        start = time.time()
        progress = slate.ensure(repo, DAY, season=2026, park_season=2023)
        assert time.time() - start < 0.1
        assert progress.state == "running"

    def test_finished_games_are_warmed_too(self, monkeypatch):
        """Tempting to skip them, and wrong. A card shows a projection for a
        game that's over — comparing it to the result is the point of the
        accuracy view — so skipping them wouldn't save the work, it would push
        it onto whoever asked first, one blocking run at a time."""
        runs: list[str] = []
        _patch_sim(monkeypatch, runs)
        repo = FakeRepo([FakeGame("done", status="Final"), FakeGame("todo")])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=10)

        assert sorted(runs) == ["done", "todo"]
        assert slate.status(DAY).total == 2


class TestWaiting:
    def test_a_reader_waits_for_the_game_it_asked_about(self, monkeypatch):
        runs: list[str] = []
        _patch_sim(monkeypatch, runs, delay=0.05)
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(5)])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        assert slate.wait_for_game(DAY, "g4", timeout=10) is True
        assert "g4" in runs

    def test_waiting_on_one_game_does_not_wait_for_the_slate(self, monkeypatch):
        """A question about the first game shouldn't sit through the other
        fourteen."""
        _patch_sim(monkeypatch, [], delay=0.15)
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(10)])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        start = time.time()
        assert slate.wait_for_game(DAY, "g0", timeout=10) is True
        early = time.time() - start
        slate.wait(DAY, timeout=10)
        assert early < 1.0, "released as soon as its own game landed"

    def test_a_game_that_cannot_be_simulated_still_releases_its_waiters(
        self, monkeypatch
    ):
        """Otherwise one missing lineup hangs every reader for the full timeout
        — and the assistant would look broken rather than merely uninformed."""
        runs: list[str] = []
        _patch_sim(monkeypatch, runs, fail={"g1"})
        repo = FakeRepo([FakeGame("g0"), FakeGame("g1"), FakeGame("g2")])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        assert slate.wait_for_game(DAY, "g1", timeout=10) is True
        slate.wait(DAY, timeout=10)
        assert slate.status(DAY).failed == ["g1"]
        assert runs == ["g0", "g2"], "the rest of the slate still ran"

    def test_asking_about_a_game_not_on_the_slate_is_released_at_the_end(
        self, monkeypatch
    ):
        """A postponed game, or a typo'd id. It must not hold a request open
        for the whole timeout."""
        _patch_sim(monkeypatch, [], delay=0.02)
        repo = FakeRepo([FakeGame("g0"), FakeGame("g1")])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        assert slate.wait_for_game(DAY, "not-on-this-slate", timeout=10) is True

    def test_asking_about_an_unknown_game_after_the_slate_is_done_returns_at_once(
        self, monkeypatch
    ):
        """The finished slate has nothing left to wait for. Minting a fresh
        event for a game nobody is going to simulate would block the caller for
        the full timeout — 90 seconds, in the assistant's case, for a question
        it could have answered immediately."""
        _patch_sim(monkeypatch, [])
        repo = FakeRepo([FakeGame("g0")])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=10)

        start = time.time()
        assert slate.wait_for_game(DAY, "never-heard-of-it", timeout=30) is True
        assert time.time() - start < 0.1

    def test_waiting_on_a_slate_nobody_opened_returns_false_at_once(self):
        """No warm-up to wait for — the caller should simulate it itself rather
        than block."""
        start = time.time()
        assert slate.wait_for_game(DAY, "g0", timeout=10) is False
        assert time.time() - start < 0.1


class TestReset:
    def test_reset_lets_the_slate_run_again(self, monkeypatch):
        """The re-run button drops the cached runs; without this the slate
        stays marked ready and nothing refills it."""
        runs: list[str] = []
        _patch_sim(monkeypatch, runs)
        repo = FakeRepo([FakeGame("g0")])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=10)
        slate.ensure(repo, DAY, season=2026, park_season=2023)  # no-op
        assert runs == ["g0"]

        slate.reset(DAY)
        slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=10)
        assert runs == ["g0", "g0"]

    def test_status_is_none_before_anyone_opens_the_slate(self):
        assert slate.status(date(2026, 1, 1)) is None

    def test_reset_stops_the_run_rather_than_just_forgetting_it(self, monkeypatch):
        """A dropped warm-up that kept going would hold the CPU lock against the
        run that replaced it, so a re-run would finish slower than the original
        did."""
        runs: list[str] = []
        _patch_sim(monkeypatch, runs, delay=0.05)
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(40)])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        time.sleep(0.12)
        slate.reset(DAY)
        settled = len(runs)
        time.sleep(0.4)

        assert len(runs) <= settled + 1, "it stopped instead of finishing 40 games"

    def test_reset_releases_anyone_waiting_on_the_dropped_run(self, monkeypatch):
        """Otherwise a re-run leaves the previous readers hanging for their full
        timeout on a slate that is never going to finish."""
        _patch_sim(monkeypatch, [], delay=0.05)
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(40)])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        released = threading.Event()

        def reader():
            slate.wait_for_game(DAY, "g39", timeout=30)
            released.set()

        threading.Thread(target=reader, daemon=True).start()
        time.sleep(0.1)
        slate.reset(DAY)
        assert released.wait(2.0), "reset must let the waiters go"


class TestConcurrency:
    def test_many_readers_arriving_at_once_produce_one_warm_up(self, monkeypatch):
        runs: list[str] = []
        _patch_sim(monkeypatch, runs, delay=0.01)
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(4)])

        barrier = threading.Barrier(8)

        def reader():
            barrier.wait()
            slate.ensure(repo, DAY, season=2026, park_season=2023)

        threads = [threading.Thread(target=reader) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        slate.wait(DAY, timeout=10)

        assert len(runs) == 4, "one run per game, not one per reader"


class TestResourceLimits:
    def test_two_slates_do_not_simulate_at_the_same_time(self, monkeypatch):
        """The simulator is GIL-bound and the container has two shared cores, so
        overlapping slates make every run slower and starve the request handlers
        that keep the page responsive."""
        concurrent = []
        live = 0
        guard = threading.Lock()

        def fake(game_id, repo, **kwargs):
            nonlocal live
            with guard:
                live += 1
                concurrent.append(live)
            time.sleep(0.05)
            with guard:
                live -= 1
            return ("result", "raw")

        monkeypatch.setattr(slate, "simulate_cached", fake)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(4)])

        other = date(2026, 7, 1)
        slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.ensure(repo, other, season=2026, park_season=2023)
        slate.wait(DAY, timeout=20)
        slate.wait(other, timeout=20)

        assert max(concurrent) == 1, "one simulation at a time across all slates"

    def test_finished_slates_are_evicted_but_running_ones_are_not(self, monkeypatch):
        """Browsing a fortnight of dates shouldn't grow the record without
        limit — but evicting a slate mid-run would orphan its waiters."""
        _patch_sim(monkeypatch, [])
        repo = FakeRepo([FakeGame("g0")])

        for i in range(1, slate._MAX_SLATES + 6):
            day = date(2026, 6, 1) + __import__("datetime").timedelta(days=i)
            slate.ensure(repo, day, season=2026, park_season=2023)
            slate.wait(day, timeout=10)

        assert len(slate._SLATES) <= slate._MAX_SLATES


class TestRetries:
    """A game that fails once has usually failed on a lineup or schedule fetch
    that hadn't landed, not because it can't be simulated. Writing it off after
    one go is what left slates finishing with games missing."""

    def test_a_transient_failure_is_retried_and_recovered(self, monkeypatch):
        monkeypatch.setattr(slate, "RETRY_PAUSE_SECONDS", 0.0)
        seen: dict[str, int] = {}

        def flaky(game_id, repo, **kwargs):
            seen[game_id] = seen.get(game_id, 0) + 1
            if game_id == "g1" and seen[game_id] == 1:
                raise RuntimeError("lineup not in yet")
            return ("result", "raw")

        monkeypatch.setattr(slate, "simulate_cached", flaky)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)
        repo = FakeRepo([FakeGame("g0"), FakeGame("g1"), FakeGame("g2")])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=20)

        p = slate.status(DAY)
        assert p.failed == [], "the retry recovered it"
        assert p.state == "ready" and p.complete is True
        assert seen["g1"] == 2

    def test_a_game_that_never_works_stops_after_the_cap(self, monkeypatch):
        """A postponement with no lineup all night must not hold the slate — and
        everything downstream — open forever."""
        monkeypatch.setattr(slate, "RETRY_PAUSE_SECONDS", 0.0)
        tries = {"n": 0}

        def always_fails(game_id, repo, **kwargs):
            if game_id == "g1":
                tries["n"] += 1
                raise RuntimeError("postponed")
            return ("result", "raw")

        monkeypatch.setattr(slate, "simulate_cached", always_fails)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)
        repo = FakeRepo([FakeGame("g0"), FakeGame("g1")])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=20)

        p = slate.status(DAY)
        assert tries["n"] == slate.MAX_ATTEMPTS
        assert p.failed == ["g1"]
        assert p.state == "partial", "finished, but not complete"
        assert p.complete is False
        assert p.running is False, "downstream must not wait forever"

    def test_a_complete_slate_reports_itself_complete(self, monkeypatch):
        _patch_sim(monkeypatch, [])
        repo = FakeRepo([FakeGame(f"g{i}") for i in range(3)])
        slate.ensure(repo, DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=10)
        p = slate.status(DAY)
        assert p.complete is True and p.running is False and p.attempts == 1

    def test_waiters_are_released_on_the_first_pass_not_after_retries(
        self, monkeypatch
    ):
        """A reader blocked on one game shouldn't sit through two more rounds of
        somebody else's retries."""
        monkeypatch.setattr(slate, "RETRY_PAUSE_SECONDS", 5.0)

        def one_bad(game_id, repo, **kwargs):
            if game_id == "g0":
                raise RuntimeError("nope")
            return ("result", "raw")

        monkeypatch.setattr(slate, "simulate_cached", one_bad)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)
        repo = FakeRepo([FakeGame("g0"), FakeGame("g1")])

        slate.ensure(repo, DAY, season=2026, park_season=2023)
        start = time.time()
        assert slate.wait_for_game(DAY, "g1", timeout=10) is True
        assert time.time() - start < 3.0


class TestFailuresSayWhy:
    """A failure list with no reasons told nobody anything — not the page, and
    not me. A game stopped simulating and the only way to find out why was to
    reproduce it by hand."""

    def test_the_error_is_recorded_against_the_game(self, monkeypatch):
        monkeypatch.setattr(slate, "RETRY_PAUSE_SECONDS", 0.0)

        def boom(game_id, repo, **kwargs):
            if game_id == "g1":
                raise IndexError("list index out of range")
            return ("result", "raw")

        monkeypatch.setattr(slate, "simulate_cached", boom)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)
        slate.ensure(FakeRepo([FakeGame("g0"), FakeGame("g1")]), DAY,
                     season=2026, park_season=2023)
        slate.wait(DAY, timeout=20)

        p = slate.status(DAY)
        assert p.failed == ["g1"]
        assert "IndexError" in p.reasons["g1"]
        assert "reasons" in p.as_dict()

    def test_a_recovered_game_drops_its_reason(self, monkeypatch):
        monkeypatch.setattr(slate, "RETRY_PAUSE_SECONDS", 0.0)
        seen = {"n": 0}

        def flaky(game_id, repo, **kwargs):
            if game_id == "g0":
                seen["n"] += 1
                if seen["n"] == 1:
                    raise RuntimeError("not yet")
            return ("result", "raw")

        monkeypatch.setattr(slate, "simulate_cached", flaky)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)
        slate.ensure(FakeRepo([FakeGame("g0")]), DAY, season=2026, park_season=2023)
        slate.wait(DAY, timeout=20)

        p = slate.status(DAY)
        assert p.reasons == {} and p.failed == [] and p.complete is True


class TestWatchingForLineups:
    """Lineups are posted a few hours before first pitch, and nothing was
    looking. The page polled only while a game was already in progress — after
    the window that matters — and the server simulated the slate once on open
    and never again. A card posted at four o'clock reached the app whenever
    somebody next happened to reload."""

    def _today_is(self, monkeypatch, day):
        monkeypatch.setattr(slate, "date_type",
                            type("D", (), {"today": staticmethod(lambda: day)}))

    def _one_pass(self, monkeypatch):
        """Let the watcher round-trip once, then report everything finished."""
        monkeypatch.setattr(slate, "WATCH_INTERVAL_SECONDS", 0.01)
        seen = {"n": 0}

        def stop_after_one(repo, day):
            seen["n"] += 1
            return seen["n"] > 1

        monkeypatch.setattr(slate, "_all_final", stop_after_one)

    def _schedule_source(self, monkeypatch, on_fetch=lambda: None):
        monkeypatch.setattr(
            "thebeast.data.sources.schedules.MLBScheduleSource",
            lambda repo: type("S", (), {
                "fetch_schedule": lambda self, d: on_fetch()})())

    def test_a_posted_lineup_is_picked_up_and_re_simulated(self, monkeypatch):
        posted = {"yet": False}
        runs: list[str] = []

        class Repo:
            def get_schedule(self, day):
                return [FakeGame("g0")]

            def get_lineup(self, game_id, team):
                class LC:
                    starter_id = 0
                lc = LC()
                lc.batting_order = [9, 9, 9] if posted["yet"] else [1, 2, 3]
                lc.confirmed = posted["yet"]
                return lc

        monkeypatch.setattr(slate, "simulate_cached",
                            lambda gid, repo, **k: runs.append(gid) or ("r", "raw"))
        monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)
        self._schedule_source(monkeypatch, lambda: posted.__setitem__("yet", True))
        self._today_is(monkeypatch, DAY)
        self._one_pass(monkeypatch)

        s = slate._Slate(DAY.isoformat())
        slate._watch(s, Repo(), DAY, 2026, 2023)

        assert runs == ["g0"], "the game was re-run after the card was posted"
        assert s.progress.resimulated == 1
        assert s.progress.watching is False

    def test_an_unchanged_slate_re_simulates_nothing(self, monkeypatch):
        """A quiet pass is cache hits: `simulate_cached` keys on the lineup
        fingerprint, so the check and the fix are the same call."""
        class Repo:
            def get_schedule(self, day):
                return [FakeGame("g0"), FakeGame("g1")]

            def get_lineup(self, game_id, team):
                class LC:
                    batting_order = [1, 2, 3]
                    starter_id = 0
                    confirmed = False
                return LC()

        monkeypatch.setattr(slate, "simulate_cached", lambda *a, **k: ("r", "raw"))
        monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)
        self._schedule_source(monkeypatch)
        self._today_is(monkeypatch, DAY)
        self._one_pass(monkeypatch)

        s = slate._Slate(DAY.isoformat())
        slate._watch(s, Repo(), DAY, 2026, 2023)
        assert s.progress.resimulated == 0

    def test_a_game_that_failed_recovers_when_its_lineup_lands(self, monkeypatch):
        """The commonest reason a game can't be simulated is that its lineup
        isn't in yet, so the watcher is also how it gets back into the slate."""
        posted = {"yet": False}

        class Repo:
            def get_schedule(self, day):
                return [FakeGame("g0")]

            def get_lineup(self, game_id, team):
                class LC:
                    starter_id = 0
                lc = LC()
                lc.batting_order = [9] if posted["yet"] else [1]
                lc.confirmed = posted["yet"]
                return lc

        monkeypatch.setattr(slate, "simulate_cached", lambda *a, **k: ("r", "raw"))
        monkeypatch.setattr("thebeast.api.main._ensure_lineups", lambda *a, **k: None)
        self._schedule_source(monkeypatch, lambda: posted.__setitem__("yet", True))
        self._today_is(monkeypatch, DAY)
        self._one_pass(monkeypatch)

        s = slate._Slate(DAY.isoformat())
        s.progress.state = "partial"
        s.progress.failed = ["g0"]
        s.progress.reasons = {"g0": "IndexError: list index out of range"}
        slate._watch(s, Repo(), DAY, 2026, 2023)

        assert s.progress.failed == [] and s.progress.reasons == {}
        assert s.progress.state == "ready"

    def test_it_does_not_watch_a_date_that_is_not_today(self, monkeypatch):
        """Yesterday's lineups are not going to change."""
        called = {"n": 0}
        monkeypatch.setattr(slate, "_all_final",
                            lambda *a: called.__setitem__("n", called["n"] + 1))
        self._today_is(monkeypatch, DAY)
        slate._watch(slate._Slate("2019-04-01"), FakeRepo([]),
                     date(2019, 4, 1), 2026, 2023)
        assert called["n"] == 0

    def test_it_stops_once_every_game_is_over(self, monkeypatch):
        monkeypatch.setattr(slate, "WATCH_INTERVAL_SECONDS", 0.01)
        self._today_is(monkeypatch, DAY)
        fetches = {"n": 0}
        self._schedule_source(monkeypatch,
                              lambda: fetches.__setitem__("n", fetches["n"] + 1))
        slate._watch(slate._Slate(DAY.isoformat()),
                     FakeRepo([FakeGame("g0", status="Final")]), DAY, 2026, 2023)
        assert fetches["n"] == 0, "nothing left to wait for"

    def test_a_reset_interrupts_the_wait(self, monkeypatch):
        monkeypatch.setattr(slate, "WATCH_INTERVAL_SECONDS", 30.0)
        self._today_is(monkeypatch, DAY)
        s = slate._Slate(DAY.isoformat())
        done = threading.Event()

        def run():
            slate._watch(s, FakeRepo([FakeGame("g0")]), DAY, 2026, 2023)
            done.set()

        threading.Thread(target=run, daemon=True).start()
        time.sleep(0.1)
        s.cancelled.set()
        assert done.wait(2.0), "cancelling wakes it rather than sleeping it out"

    def test_confirmed_lineups_are_counted(self):
        class Repo:
            def get_schedule(self, day):
                return [FakeGame("g0")]

            def get_lineup(self, game_id, team):
                class LC:
                    batting_order = [1]
                    starter_id = 0
                lc = LC()
                lc.confirmed = team == "BAL"
                return lc

        s = slate._Slate(DAY.isoformat())
        slate._count_confirmed(s, Repo(), DAY)
        assert s.progress.lineup_slots == 2 and s.progress.confirmed == 1
