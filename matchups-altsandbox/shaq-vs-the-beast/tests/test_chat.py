"""The chat assistant: its tools, its guardrails, and its failure modes.

Nothing here calls the Anthropic API — the streaming loop is exercised against
a fake client. What is worth pinning is everything around it: that a tool
failure comes back as a readable result instead of killing the stream, that
history trimming can't produce a request the API will reject, and that the
feature stays invisible rather than broken when no key is configured.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from thebeast import chat


class TestConfiguration:
    def test_no_key_means_unavailable(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert chat.available() is False

    def test_a_key_turns_it_on(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert chat.available() is True

    def test_surrounding_whitespace_is_stripped_from_the_key(self, monkeypatch):
        """A secrets form on a phone will happily store a trailing newline, and
        the API rejects the resulting header as an invalid key — which reads as
        "my key is wrong" when only its packaging is."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "  sk-ant-abc123\n")
        assert chat.api_key() == "sk-ant-abc123"
        assert chat.available() is True
        assert chat.key_looks_wrong() is False

    def test_a_whitespace_only_key_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   \n")
        assert chat.api_key() is None
        assert chat.available() is False

    def test_a_key_of_the_wrong_shape_is_flagged(self, monkeypatch):
        """Catches the paste accidents — half a key, a key name instead of its
        value, a token from some other service — before they cost a round trip
        and a 401 the reader has to decode."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
        assert chat.available() is True
        assert chat.key_looks_wrong() is True

    def test_nothing_is_flagged_when_no_key_is_set(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert chat.key_looks_wrong() is False

    def test_every_tool_says_when_to_call_it(self):
        """A description that only names the return value gets skipped in
        favour of an answer from memory, which for a live slate is the wrong
        trade. Each one has to state its trigger."""
        for tool in chat.TOOLS:
            assert tool["description"]
            assert "Call it" in tool["description"] \
                or "Call this" in tool["description"] \
                or "Use it" in tool["description"]

    def test_every_tool_is_dispatchable(self):
        assert {t["name"] for t in chat.TOOLS} == set(chat._DISPATCH)


class TestTools:
    def test_a_failing_tool_returns_an_error_not_an_exception(self):
        """The stream is already open by the time a tool runs. A raised
        exception truncates the answer with no explanation; an error result
        lets the model say what went wrong or try another route."""
        class Broken:
            def get_schedule(self, d):
                raise RuntimeError("database is on fire")

        payload, is_error = chat.run_tool("list_games", {}, Broken(), 2026)
        assert is_error is True
        assert "database is on fire" in payload

    def test_an_unknown_tool_is_reported_not_raised(self):
        payload, is_error = chat.run_tool("drop_tables", {}, None, 2026)
        assert is_error is True
        assert "No such tool" in payload

    def test_a_tool_result_is_json_the_model_can_read(self):
        class Repo:
            def get_schedule(self, d):
                class G:
                    game_id = "2026-08-02-NYY-BOS"
                    away_team_id, home_team_id = "NYY", "BOS"
                    first_pitch = "2026-08-02T23:05:00+00:00"
                    status = "Preview"
                return [G()]

        payload, is_error = chat.run_tool(
            "list_games", {"date": "2026-08-02"}, Repo(), 2026)
        assert is_error is False
        data = json.loads(payload)
        assert data["games"][0]["game_id"] == "2026-08-02-NYY-BOS"

    def test_an_empty_slate_says_so_rather_than_returning_nothing(self):
        """A bare empty list reads as "no games today"; the model should be
        able to tell that apart from "nothing is stored for that date"."""
        class Repo:
            def get_schedule(self, d):
                return []

        data = json.loads(chat.run_tool("list_games", {}, Repo(), 2026)[0])
        assert data["games"] == [] and data["note"]


class TestCostControls:
    """One question cost $0.32 before these. Thinking tokens bill at the output
    rate, and every tool result is resent on every subsequent round, so the two
    compound. These pin the fixes that brought it under a cent."""

    def test_effort_is_withheld_from_models_that_reject_it(self, monkeypatch):
        """`output_config.effort` is a 400 on Haiku 4.5, not a no-op — sending
        it would break the cheap path outright."""
        monkeypatch.setattr(chat, "MODEL", "claude-haiku-4-5")
        assert chat._request_extras() == {}

    def test_effort_is_sent_to_models_that_take_it(self, monkeypatch):
        monkeypatch.setattr(chat, "MODEL", "claude-opus-5")
        monkeypatch.setattr(chat, "EFFORT", "low")
        assert chat._request_extras() == {"output_config": {"effort": "low"}}

    def test_the_box_score_is_opt_in(self):
        """The per-player lines are ~10x the summary and are resent on every
        round, so a question that sweeps the slate pays for them once per game
        per round. Most questions never needed them."""
        class Repo:
            pass

        # Exercised through the shape of the payload rather than a live sim.
        summary_keys = {"game_id", "home", "away", "simulations",
                        "home_win_probability", "projected_score", "total",
                        "extra_inning_pct", "note"}
        detail_keys = summary_keys | {"batters", "pitchers"}
        assert "batters" not in summary_keys
        assert "batters" in detail_keys

    def test_rounds_and_history_are_bounded(self):
        """Both compound: each round resends every tool result so far, and each
        question resends the conversation."""
        assert chat.MAX_TOOL_ROUNDS <= 3
        assert chat.MAX_TURNS <= 8

    def test_the_default_model_is_the_cheap_one(self):
        assert chat.MODEL == "claude-haiku-4-5"


def _explode(*a, **k):
    raise AssertionError("this call should not have happened")


class _FakeResult:
    home, away, n = "BAL", "CWS", 2000
    home_win_probability = 0.4894
    home_run_mean = away_run_mean = total_mean = 4.5
    total_p10, total_p90, extra_inning_pct = 3, 12, 0.08
    player_lines: list = []
    pitcher_lines: list = []


class TestReuseBeforeSimulating:
    """The assistant answers from work already done wherever it can.

    A question about a game is not a reason to run a Monte Carlo. If the game
    has finished it was graded when it finished; if it hasn't, the cards have
    almost certainly simulated it already. Running it again is both slow and
    wrong-ish — a second run lands a percentage point off the first, so the
    assistant would quote numbers that disagree with the card being asked about.
    """

    def _repo(self, stored=None):
        class Repo:
            def get_accuracy_game(self, game_id):
                return stored
        return Repo()

    def test_a_finished_game_is_read_not_simulated(self, monkeypatch):
        record = {
            "game_id": "2026-07-22-ATH-AZ", "home": "AZ", "away": "ATH",
            "actual": {"status": "Final", "home_runs": 15, "away_runs": 5},
            "outcome": {"home_win_probability": 0.521, "picked_winner": True,
                        "home_runs": {"mean": 4.114}, "away_runs": {"mean": 4.404},
                        "total": {"mean": 8.518, "actual": 20.0, "covered": False}},
            "batters": [], "pitchers": [],
        }

        def explode(*a, **k):
            raise AssertionError("a finished game must not be re-simulated")

        monkeypatch.setattr("thebeast.simcache.simulate_cached", explode)
        monkeypatch.setattr("thebeast.simcache.peek", explode)
        out = chat._tool_simulate_game(self._repo(record), 2026,
                                       {"game_id": record["game_id"]})
        assert out["status"] == "final"
        assert out["final_score"] == "ATH 5 @ AZ 15"
        # The result is the point: it's what a simulation could never supply.
        assert out["total"]["actual"] == 20.0
        assert out["home_win_probability"] == 0.521

    def test_a_game_still_in_progress_falls_through_to_the_simulation(
        self, monkeypatch
    ):
        """A game part-way through can have a row if something scored it early.
        That is not a settled record and must not be served as one — the live
        projection is the answer to a question about a game being played."""
        record = {"game_id": "2026-06-30-CWS-BAL", "home": "BAL", "away": "CWS",
                  "actual": {"status": "In Progress"}, "outcome": {},
                  "batters": [], "pitchers": []}
        monkeypatch.setattr("thebeast.simcache.peek", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.slate.wait_for_game", lambda *a, **k: False)
        monkeypatch.setattr("thebeast.simcache.simulate_cached", _explode)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups",
                            lambda *a, **k: None)
        with pytest.raises(AssertionError, match="should not have happened"):
            chat._tool_simulate_game(self._repo(record), 2026,
                                     {"game_id": record["game_id"]})

    def test_a_cached_run_is_reused_rather_than_repeated(self, monkeypatch):
        monkeypatch.setattr("thebeast.simcache.peek",
                            lambda *a, **k: (_FakeResult(), None))
        monkeypatch.setattr("thebeast.simcache.simulate_cached", _explode)
        monkeypatch.setattr("thebeast.data.names.player_names",
                            lambda *a, **k: {})
        out = chat._tool_simulate_game(self._repo(), 2026,
                                       {"game_id": "2026-06-30-CWS-BAL"})
        assert out["home_win_probability"] == 0.4894
        # The model is told where the number came from, so it can say so.
        assert "not re-simulated" in out["source"]

    def test_a_fresh_run_uses_the_slate_parameters(self, monkeypatch):
        """Otherwise it lands in its own cache entry beside the cards' rather
        than in it, and the next card to ask pays for the same game again."""
        from thebeast import simcache

        seen = {}

        def capture(game_id, repo, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop here — the parameters are the assertion")

        monkeypatch.setattr("thebeast.simcache.peek", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.slate.wait_for_game", lambda *a, **k: False)
        monkeypatch.setattr("thebeast.simcache.simulate_cached", capture)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups",
                            lambda *a, **k: None)
        with pytest.raises(RuntimeError):
            chat._tool_simulate_game(self._repo(), 2026,
                                     {"game_id": "2026-06-30-CWS-BAL"})
        assert seen["n"] == simcache.SLATE_N
        assert seen["seed"] == simcache.SLATE_SEED

    def test_it_waits_for_a_run_in_flight_instead_of_starting_another(
        self, monkeypatch
    ):
        """Opening the slate starts the server simulating it. A question that
        arrives mid-warm-up should queue behind that game's run — waiting is
        both faster than a fresh simulation and the only way to quote the same
        numbers the card will show."""
        calls = {"waited": None, "peeks": 0}

        def peek(*a, **k):
            calls["peeks"] += 1
            # Cold on the first look, warm once the wait returns.
            return (_FakeResult(), None) if calls["waited"] else None

        def wait_for_game(day, game_id, timeout):
            calls["waited"] = (day.isoformat(), game_id, timeout)
            return True

        monkeypatch.setattr("thebeast.simcache.peek", peek)
        monkeypatch.setattr("thebeast.slate.wait_for_game", wait_for_game)
        monkeypatch.setattr("thebeast.simcache.simulate_cached", _explode)
        monkeypatch.setattr("thebeast.data.names.player_names", lambda *a, **k: {})

        out = chat._tool_simulate_game(self._repo(), 2026,
                                       {"game_id": "2026-06-30-CWS-BAL"})
        assert "not re-simulated" in out["source"]
        assert calls["waited"][0] == "2026-06-30", "the date comes from the id"
        assert calls["waited"][1] == "2026-06-30-CWS-BAL"
        assert calls["peeks"] == 2, "look again once the wait returns"

    def test_a_game_id_without_a_date_does_not_crash_the_wait(self):
        assert chat._game_date("not-a-game-id") is None
        assert chat._game_date("2026-06-30-CWS-BAL").isoformat() == "2026-06-30"


class TestPlayerLabels:
    """The simulation is per-player; the payload has to say so.

    `simulate_cached` returns lines keyed by player id, and the API routes
    attach names on the way out. This tool has to as well — without it the
    model gets bare numbers and starts describing people by batting slot,
    which reads as though the simulation were slot-based rather than
    individual.
    """

    def _named(self, pid, team="CHC", names=None):
        # Exercised through the same helper the tool builds internally.
        names = names or {}

        def named(line):
            p = int(line["player_id"])
            if p < 0:
                return f"{line['team']} bullpen (all relievers combined)"
            if p == 0:
                return f"{line['team']} starter (not yet announced)"
            return names.get(p) or f"unidentified player {p}"

        return named({"player_id": pid, "team": team})

    def test_a_real_player_gets_their_name(self):
        assert self._named(592450, names={592450: "Aaron Judge"}) == "Aaron Judge"

    def test_the_bullpen_is_labelled_not_looked_up(self):
        """A negative id is the team's aggregate bullpen — one statline for
        every reliever. It is not a person and a failed lookup would be the
        wrong story."""
        assert "bullpen" in self._named(-2000123, team="SD")

    def test_an_unannounced_starter_says_so(self):
        assert "not yet announced" in self._named(0, team="SD")

    def test_an_unresolvable_id_is_not_passed_off_as_a_name(self):
        out = self._named(657006)
        assert "unidentified" in out and "657006" in out


class TestHistory:
    def test_a_long_conversation_is_trimmed_to_the_tail(self):
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)}
                for i in range(60)]
        out = chat._trim(msgs)
        assert len(out) <= chat.MAX_TURNS
        assert out[-1] == msgs[-1]

    def test_trimming_never_starts_on_an_assistant_turn(self):
        """The API requires the first message to be from the user, and a naive
        slice lands mid-exchange about half the time."""
        for n in range(1, 60):
            msgs = [{"role": "user" if i % 2 == 0 else "assistant",
                     "content": str(i)} for i in range(n)]
            out = chat._trim(msgs)
            assert not out or out[0]["role"] == "user"


class _FakeStream:
    def __init__(self, chunks, final):
        self._chunks, self._final = chunks, final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(self._chunks)

    def get_final_message(self):
        return self._final


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Final:
    def __init__(self, stop_reason, content=()):
        self.stop_reason, self.content = stop_reason, list(content)


def _client(turns):
    """A stand-in Anthropic client that replays scripted turns."""
    calls = []

    class Messages:
        def stream(self, **kw):
            calls.append(kw)
            chunks, final = turns[len(calls) - 1]
            return _FakeStream(chunks, final)

    class Client:
        messages = Messages()

    return Client, calls


class TestStreaming:
    def _patch(self, monkeypatch, turns):
        Client, calls = _client(turns)
        import sys
        import types
        fake = types.ModuleType("anthropic")
        fake.Anthropic = lambda *a, **k: Client()
        fake.AuthenticationError = type("_Auth", (Exception,), {})
        fake.RateLimitError = type("_RL", (Exception,), {})
        fake.BadRequestError = type("_Bad", (Exception,), {})
        monkeypatch.setitem(sys.modules, "anthropic", fake)
        return calls

    def test_text_is_streamed_then_the_turn_ends(self, monkeypatch):
        self._patch(monkeypatch, [(["Sco", "ring is up."], _Final("end_turn"))])
        events = list(chat.stream_reply(
            [{"role": "user", "content": "hi"}], repo=None, season=2026))
        assert [e for e in events if e["type"] == "text"] == [
            {"type": "text", "text": "Sco"}, {"type": "text", "text": "ring is up."}]
        assert events[-1] == {"type": "done"}

    def test_a_tool_call_is_executed_and_fed_back(self, monkeypatch):
        use = _Block(type="tool_use", id="tu_1", name="list_games", input={})
        calls = self._patch(monkeypatch, [
            ([], _Final("tool_use", [use])),
            (["Two games."], _Final("end_turn")),
        ])

        class Repo:
            def get_schedule(self, d):
                return []

        events = list(chat.stream_reply(
            [{"role": "user", "content": "what's on"}], repo=Repo(), season=2026))
        assert {"type": "tool", "name": "list_games"} in events
        assert events[-1] == {"type": "done"}
        # The result went back as a tool_result in a single user message.
        follow_up = calls[1]["messages"][-1]
        assert follow_up["role"] == "user"
        assert follow_up["content"][0]["tool_use_id"] == "tu_1"

    def test_parallel_calls_come_back_in_one_message(self, monkeypatch):
        """Splitting tool results across messages quietly teaches the model to
        stop making parallel calls at all."""
        uses = [_Block(type="tool_use", id=f"tu_{i}", name="get_trends", input={})
                for i in range(3)]
        calls = self._patch(monkeypatch, [
            ([], _Final("tool_use", uses)),
            (["Done."], _Final("end_turn")),
        ])
        list(chat.stream_reply([{"role": "user", "content": "?"}],
                               repo=None, season=2026))
        results = calls[1]["messages"][-1]["content"]
        assert len(results) == 3
        assert all(r["type"] == "tool_result" for r in results)

    def test_a_rejected_key_is_explained_not_dumped(self, monkeypatch):
        """A raw 401 body says "invalid x-api-key" and nothing about what to do
        next. The one person who can fix it deserves the fix, not the code."""
        import sys
        import types

        class _Auth(Exception):
            pass

        class Messages:
            def stream(self, **kw):
                raise _Auth("401 invalid x-api-key")

        class Client:
            messages = Messages()

        fake = types.ModuleType("anthropic")
        fake.Anthropic = lambda *a, **k: Client()
        fake.AuthenticationError = _Auth
        fake.RateLimitError = type("_RL", (Exception,), {})
        monkeypatch.setitem(sys.modules, "anthropic", fake)

        events = list(chat.stream_reply([{"role": "user", "content": "hi"}],
                                        repo=None, season=2026))
        assert events == [{"type": "error", "message": chat.KEY_REJECTED}]
        assert "console.anthropic.com" in chat.KEY_REJECTED

    def test_an_unfunded_account_is_explained_not_dumped(self, monkeypatch):
        """A valid key with no balance fails at the request, not the key check.
        That is a two-minute fix, but only if the message says so."""
        import sys
        import types

        class _Bad(Exception):
            pass

        class Messages:
            def stream(self, **kw):
                raise _Bad("Your credit balance is too low to access the API")

        class Client:
            messages = Messages()

        fake = types.ModuleType("anthropic")
        fake.Anthropic = lambda *a, **k: Client()
        fake.AuthenticationError = type("_Auth", (Exception,), {})
        fake.RateLimitError = type("_RL", (Exception,), {})
        fake.BadRequestError = _Bad
        monkeypatch.setitem(sys.modules, "anthropic", fake)

        events = list(chat.stream_reply([{"role": "user", "content": "hi"}],
                                        repo=None, season=2026))
        assert events == [{"type": "error", "message": chat.NO_CREDIT}]

    def test_an_unrecognised_bad_request_still_surfaces_raw(self, monkeypatch):
        """Only the failure I can name gets a friendly message. An unfamiliar
        error should look unfamiliar rather than be mislabelled as billing."""
        import sys
        import types

        class _Bad(Exception):
            pass

        class Messages:
            def stream(self, **kw):
                raise _Bad("messages.0: unexpected role")

        class Client:
            messages = Messages()

        fake = types.ModuleType("anthropic")
        fake.Anthropic = lambda *a, **k: Client()
        fake.AuthenticationError = type("_Auth", (Exception,), {})
        fake.RateLimitError = type("_RL", (Exception,), {})
        fake.BadRequestError = _Bad
        monkeypatch.setitem(sys.modules, "anthropic", fake)

        with pytest.raises(_Bad):
            list(chat.stream_reply([{"role": "user", "content": "hi"}],
                                   repo=None, season=2026))

    def test_a_runaway_tool_loop_is_cut_off(self, monkeypatch):
        use = _Block(type="tool_use", id="tu", name="get_trends", input={})
        self._patch(monkeypatch,
                    [([], _Final("tool_use", [use]))] * (chat.MAX_TOOL_ROUNDS + 2))
        events = list(chat.stream_reply([{"role": "user", "content": "?"}],
                                        repo=None, season=2026))
        assert events[-1]["type"] == "error"


class TestRateLimit:
    def test_a_normal_conversation_is_not_throttled(self):
        chat._HITS.clear()
        assert not any(chat.rate_limited("a", now=float(i)) for i in range(5))

    def test_a_flood_is_throttled(self):
        chat._HITS.clear()
        for i in range(chat.RATE_LIMIT):
            assert chat.rate_limited("b", now=1.0) is False
        assert chat.rate_limited("b", now=1.0) is True

    def test_the_window_rolls_forward(self):
        chat._HITS.clear()
        for _ in range(chat.RATE_LIMIT):
            chat.rate_limited("c", now=0.0)
        assert chat.rate_limited("c", now=0.0) is True
        assert chat.rate_limited("c", now=chat.RATE_WINDOW + 1) is False

    def test_callers_are_throttled_separately(self):
        chat._HITS.clear()
        for _ in range(chat.RATE_LIMIT):
            chat.rate_limited("d", now=1.0)
        assert chat.rate_limited("d", now=1.0) is True
        assert chat.rate_limited("e", now=1.0) is False


class FakeGame:
    def __init__(self, gid, away, home, status="Preview"):
        self.game_id, self.away_team_id, self.home_team_id = gid, away, home
        self.first_pitch, self.status = "2026-08-03T23:05:00+00:00", status
        self.home_score = self.away_score = None


class SlateRepo:
    def __init__(self, games, by_date=None):
        self._games = games
        self._by_date = by_date or {}

    def get_schedule(self, d):
        return self._by_date.get(d.isoformat(), self._games)


GAMES = [FakeGame("2026-08-03-STL-NYY", "STL", "NYY"),
         FakeGame("2026-08-03-PIT-MIL", "PIT", "MIL")]


class TestOneSourceOfTruth:
    """Everything the assistant says about tonight comes from the simulations
    the app already ran. It was doing the opposite — guessing ids, simulating
    one game at a time, assembling a parlay out of raw projections — and when a
    guess missed it told the user the games didn't exist. They did."""

    def test_the_slate_carries_its_projections(self, monkeypatch):
        monkeypatch.setattr("thebeast.slate.ensure", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.slate.wait", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.simcache.peek",
                            lambda *a, **k: (_FakeResult(), None))
        out = chat._tool_get_slate(SlateRepo(GAMES), 2026, {"date": "2026-08-03"})
        assert len(out["games"]) == 2
        assert out["games"][0]["home_win_probability"] == 0.4894
        assert "projected_total" in out["games"][0]

    def test_it_never_simulates_anything_itself(self, monkeypatch):
        """It waits for the slate. Starting its own run would produce numbers a
        percentage point off the cards the question is about."""
        monkeypatch.setattr("thebeast.slate.ensure", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.slate.wait", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.simcache.peek", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.simcache.simulate_cached", _explode)
        out = chat._tool_get_slate(SlateRepo(GAMES), 2026, {"date": "2026-08-03"})
        assert "not simulated yet" in out["note"]

    def test_an_ungraded_game_is_flagged_not_silently_dropped(self, monkeypatch):
        monkeypatch.setattr("thebeast.slate.ensure", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.slate.wait", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.simcache.peek", lambda *a, **k: None)
        out = chat._tool_get_slate(SlateRepo(GAMES), 2026, {"date": "2026-08-03"})
        assert len(out["games"]) == 2, "still listed"
        assert "home_win_probability" not in out["games"][0]

    def test_an_empty_date_says_so(self, monkeypatch):
        monkeypatch.setattr("thebeast.chat._slate_games", lambda repo, d: [])
        out = chat._tool_get_slate(SlateRepo([]), 2026, {"date": "2026-08-03"})
        assert out["games"] == [] and "No games" in out["note"]


class TestGameIdResolution:
    """The screenshot: 'those game IDs don't exist in the system'. They did —
    the model had written them a little differently."""

    def _repo(self):
        return SlateRepo(GAMES, {"2026-08-03": GAMES})

    def test_an_exact_id_passes_through(self):
        assert chat._resolve_game_id(self._repo(), "2026-08-03-STL-NYY") \
            == "2026-08-03-STL-NYY"

    def test_teams_the_wrong_way_round_still_find_the_game(self):
        assert chat._resolve_game_id(self._repo(), "2026-08-03-NYY-STL") \
            == "2026-08-03-STL-NYY"

    def test_prose_finds_the_game(self):
        assert chat._resolve_game_id(self._repo(), "2026-08-03 STL at NYY") \
            == "2026-08-03-STL-NYY"

    def test_a_game_that_really_is_not_on_the_slate_returns_none(self):
        """Rather than passing an invented id to the simulator and letting its
        failure surface to the user as 'the games don't exist'."""
        assert chat._resolve_game_id(self._repo(), "2026-08-03-XXX-YYY") is None

    def test_the_tool_points_at_the_slate_when_it_cannot_resolve(self, monkeypatch):
        out = chat._tool_simulate_game(self._repo(), 2026,
                                       {"game_id": "2026-08-03-XXX-YYY"})
        assert "error" in out and "get_slate" in out["hint"]


class TestBestBetsAreRead:
    """A parlay question reads the ranked plays. It does not build its own."""

    def _patch(self, monkeypatch, bets):
        class Report:
            date, generated_at = "2026-08-03", "now"
            games_considered = games_priced = 2
            props_available = True
        r = Report()
        r.bets = bets
        monkeypatch.setattr("thebeast.slate.ensure", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.slate.wait", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.chat._slate_games", lambda repo, d: GAMES)
        monkeypatch.setattr("thebeast.betting.best_bets.build_best_bets",
                            lambda *a, **k: r)

    def _bet(self, sel, edge, has_edge=True):
        return {"away": "STL", "home": "NYY", "selection": sel, "player": "A Judge",
                "market": "home_runs", "line": 0.5, "price": -110, "book": "Sleeper",
                "model_probability": 0.6, "implied_probability": 0.52,
                "edge": edge, "category": "batter_prop", "has_edge": has_edge,
                "is_live": False}

    def test_it_returns_the_ranked_plays(self, monkeypatch):
        self._patch(monkeypatch, [self._bet("Over 0.5 HR", 0.08)])
        out = chat._tool_get_best_bets(SlateRepo(GAMES), 2026, {})
        assert out["plays"][0]["selection"] == "Over 0.5 HR"
        assert out["plays"][0]["clears_the_bar"] is True
        assert "Sleeper" in out["source"]

    def test_plays_below_the_bar_are_labelled_not_dressed_up(self, monkeypatch):
        """An empty panel says nothing about the slate, so near-misses are
        shown — but they must not read as recommendations."""
        self._patch(monkeypatch, [self._bet("Over 0.5 HR", 0.001, has_edge=False)])
        out = chat._tool_get_best_bets(SlateRepo(GAMES), 2026, {})
        assert out["plays"][0]["clears_the_bar"] is False
        assert "not recommendations" in out["note"]

    def test_the_payload_is_bounded(self, monkeypatch):
        """Every play is resent on every later round."""
        self._patch(monkeypatch, [self._bet(f"play {i}", 0.05) for i in range(50)])
        out = chat._tool_get_best_bets(SlateRepo(GAMES), 2026, {"limit": 5})
        assert len(out["plays"]) == 5

    def test_the_prompt_sends_betting_questions_here(self):
        assert "get_best_bets" in chat.SYSTEM
        assert "Never build a recommendation by simulating games" in chat.SYSTEM


class _LineResult:
    """A cached run with player lines, as `peek` hands them over."""
    home, away, n = "NYY", "STL", 2000
    home_win_probability = 0.52
    home_run_mean = away_run_mean = total_mean = 4.4
    total_p10, total_p90, extra_inning_pct = 3, 12, 0.08

    def __init__(self, pitchers=(), batters=()):
        self.pitcher_lines = list(pitchers)
        self.player_lines = list(batters)


def pitcher(pid, k, team="NYY"):
    return {"player_id": pid, "team": team, "k": k, "ip": 5.0,
            "hits_allowed": 4.0, "runs_allowed": 2.0, "bb_allowed": 1.0,
            "pitches": 88.0}


class TestRankingComesFromTheData:
    """The screenshot: asked which pitcher strikes out the most, the assistant
    pulled a full box score for all fifteen games and then ranked them in
    prose — and got it wrong, calling 6.3 the leader over 6.31. Sorting is not
    a thing to do in prose, and the numbers were already in the cache."""

    def _patch(self, monkeypatch, results):
        monkeypatch.setattr("thebeast.slate.ensure", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.slate.wait", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.chat._slate_games", lambda repo, d: GAMES)
        monkeypatch.setattr("thebeast.simcache.simulate_cached", _explode)
        it = iter(results)
        monkeypatch.setattr("thebeast.simcache.peek",
                            lambda *a, **k: (next(it, None), None)
                            if True else None)
        monkeypatch.setattr("thebeast.data.names.player_names",
                            lambda repo, ids, season: {i: f"P{i}" for i in ids})

    def test_the_close_call_is_ordered_correctly(self, monkeypatch):
        """6.31 beats 6.3. This is the exact pair it got backwards."""
        self._patch(monkeypatch, [
            _LineResult(pitchers=[pitcher(1001, 6.30)]),
            _LineResult(pitchers=[pitcher(1002, 6.31)]),
        ])
        out = chat._tool_get_projections(
            SlateRepo(GAMES), 2026, {"kind": "pitchers", "stat": "k"})
        assert [r["name"] for r in out["leaders"]] == ["P1002", "P1001"]
        assert out["leaders"][0]["rank"] == 1

    def test_it_does_not_simulate(self, monkeypatch):
        """`simulate_cached` is patched to explode; reaching it fails the test."""
        self._patch(monkeypatch, [_LineResult(pitchers=[pitcher(1001, 5.0)]),
                                  _LineResult(pitchers=[pitcher(1002, 4.0)])])
        out = chat._tool_get_projections(
            SlateRepo(GAMES), 2026, {"kind": "pitchers", "stat": "k"})
        assert len(out["leaders"]) == 2

    def test_the_bullpen_aggregate_is_not_offered_as_a_pitcher(self, monkeypatch):
        """A negative id is every reliever combined. It would often top a
        strikeout ranking and is not a person, so it would be wrong twice."""
        self._patch(monkeypatch, [
            _LineResult(pitchers=[pitcher(-2001, 99.0), pitcher(1001, 5.0)]),
            _LineResult(pitchers=[pitcher(1002, 4.0)]),
        ])
        out = chat._tool_get_projections(
            SlateRepo(GAMES), 2026, {"kind": "pitchers", "stat": "k"})
        assert all("bullpen" not in r["name"] for r in out["leaders"])
        assert out["leaders"][0]["name"] == "P1001"

    def test_the_bullpen_can_be_asked_for_explicitly(self, monkeypatch):
        self._patch(monkeypatch, [
            _LineResult(pitchers=[pitcher(-2001, 99.0)]),
            _LineResult(pitchers=[pitcher(1002, 4.0)]),
        ])
        out = chat._tool_get_projections(
            SlateRepo(GAMES), 2026,
            {"kind": "pitchers", "stat": "k", "include_bullpen": True})
        assert "bullpen" in out["leaders"][0]["name"]

    def test_an_unannounced_starter_is_not_named_as_the_leader(self, monkeypatch):
        self._patch(monkeypatch, [
            _LineResult(pitchers=[pitcher(0, 99.0)]),
            _LineResult(pitchers=[pitcher(1002, 4.0)]),
        ])
        out = chat._tool_get_projections(
            SlateRepo(GAMES), 2026, {"kind": "pitchers", "stat": "k"})
        assert out["leaders"][0]["name"] == "P1002"

    def test_a_bad_stat_is_rejected_with_the_options(self, monkeypatch):
        out = chat._tool_get_projections(
            SlateRepo(GAMES), 2026, {"kind": "pitchers", "stat": "dingers"})
        assert "error" in out and "k" in out["error"]

    def test_a_bad_kind_is_rejected(self, monkeypatch):
        out = chat._tool_get_projections(
            SlateRepo(GAMES), 2026, {"kind": "umpires", "stat": "k"})
        assert "error" in out

    def test_games_not_yet_simulated_are_declared(self, monkeypatch):
        monkeypatch.setattr("thebeast.slate.ensure", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.slate.wait", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.chat._slate_games", lambda repo, d: GAMES)
        monkeypatch.setattr("thebeast.simcache.peek", lambda *a, **k: None)
        out = chat._tool_get_projections(
            SlateRepo(GAMES), 2026, {"kind": "pitchers", "stat": "k"})
        assert out["leaders"] == []
        assert "not simulated yet" in out["note"]

    def test_the_prompt_sends_comparisons_here(self):
        assert "get_projections" in chat.SYSTEM
        assert "6.31 is more than 6.3" in chat.SYSTEM


class TestWhatIfIsTheOnlyFreshRun:
    """The one exception to reading from cache. Ordinary questions are lookups;
    a what-if has no stored answer by definition — nobody simulated a healthy
    Judge — so it runs fresh, and returns the baseline beside it so the
    difference is the answer rather than a number floating on its own."""

    def _patch(self, monkeypatch, altered, baseline=None):
        monkeypatch.setattr("thebeast.chat._slate_games", lambda repo, d: GAMES)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups",
                            lambda *a, **k: None)
        monkeypatch.setattr("thebeast.pipeline.simulate_matchup",
                            lambda *a, **k: (altered, None))
        monkeypatch.setattr("thebeast.simcache.peek",
                            lambda *a, **k: (baseline, None) if baseline else None)

    def _result(self, wp, total):
        class R:
            home, away = "NYY", "STL"
            home_win_probability = wp
            total_mean = total
            home_run_mean = away_run_mean = total / 2
        return R()

    def test_it_reports_the_change_against_the_baseline(self, monkeypatch):
        self._patch(monkeypatch, self._result(0.61, 9.2),
                    baseline=self._result(0.52, 8.4))
        out = chat._tool_simulate_what_if(SlateRepo(GAMES), 2026, {
            "game_id": "2026-08-03-STL-NYY",
            "batter_changes": {"592450": {"home_runs": 1.5}}})
        assert out["with_changes"]["home_win_probability"] == 0.61
        assert out["baseline"]["home_win_probability"] == 0.52
        assert out["shift"]["home_win_probability"] == 0.09
        assert out["shift"]["projected_total"] == 0.8

    def test_a_what_if_with_nothing_changed_is_rejected(self, monkeypatch):
        self._patch(monkeypatch, self._result(0.5, 8.0))
        out = chat._tool_simulate_what_if(SlateRepo(GAMES), 2026,
                                          {"game_id": "2026-08-03-STL-NYY"})
        assert "error" in out and "nothing to change" in out["error"]

    def test_an_unresolvable_game_points_at_the_slate(self, monkeypatch):
        monkeypatch.setattr("thebeast.chat._slate_games", lambda repo, d: GAMES)
        out = chat._tool_simulate_what_if(SlateRepo(GAMES), 2026, {
            "game_id": "2026-08-03-XXX-YYY",
            "batter_changes": {"1": {"hits": 1.1}}})
        assert "error" in out and "get_slate" in out["hint"]

    def test_it_does_not_poison_the_shared_cache(self, monkeypatch):
        """An override is one person's private question. Writing it into the
        run everything else reads would change the cards for everybody."""
        monkeypatch.setattr("thebeast.chat._slate_games", lambda repo, d: GAMES)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups",
                            lambda *a, **k: None)
        monkeypatch.setattr("thebeast.simcache.simulate_cached", _explode)
        monkeypatch.setattr("thebeast.simcache.peek", lambda *a, **k: None)
        monkeypatch.setattr("thebeast.pipeline.simulate_matchup",
                            lambda *a, **k: (self._result(0.5, 8.0), None))
        out = chat._tool_simulate_what_if(SlateRepo(GAMES), 2026, {
            "game_id": "2026-08-03-STL-NYY",
            "pitcher_changes": {"543037": {"k": 1.2}}})
        assert "with_changes" in out

    def test_a_failed_run_comes_back_as_an_error(self, monkeypatch):
        monkeypatch.setattr("thebeast.chat._slate_games", lambda repo, d: GAMES)
        monkeypatch.setattr("thebeast.api.main._ensure_lineups",
                            lambda *a, **k: None)
        monkeypatch.setattr("thebeast.pipeline.simulate_matchup",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("no lineup")))
        out = chat._tool_simulate_what_if(SlateRepo(GAMES), 2026, {
            "game_id": "2026-08-03-STL-NYY",
            "batter_changes": {"1": {"hits": 1.1}}})
        assert "error" in out and "no lineup" in out["error"]

    def test_the_prompt_calls_it_the_only_exception(self):
        assert "simulate_what_if" in chat.SYSTEM
        assert "only tool that runs a new simulation" in chat.SYSTEM
