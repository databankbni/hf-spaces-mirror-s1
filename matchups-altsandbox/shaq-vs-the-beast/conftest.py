"""Make `thebeast` importable from tests without requiring `pip install -e .`."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cross_test_at_bat_caching():
    """Stop one test's live forecast leaking into the next.

    The at-bat endpoint caches its payload per game for a couple of seconds so
    that polling it every few seconds doesn't mean calling MLB every few
    seconds. That is right in a server and wrong in a suite, where two tests
    hitting the same game id run well inside the window and the second would
    silently receive the first's answer.
    """
    from thebeast.api import main

    main._at_bat_cache.clear()
    yield
    main._at_bat_cache.clear()


@pytest.fixture(autouse=True)
def _no_cross_test_prop_caching():
    """Stop one test's prop board leaking into the next.

    The PrizePicks source caches its board for a minute and its league lookup
    for an hour, both on class attributes shared by every instance. That's right
    in a server and wrong in a suite: a test that patched the feed would hand
    its canned slate to whichever test ran next.
    """
    from thebeast.data.sources.prizepicks import PrizePicksSource

    PrizePicksSource.clear()
    yield
    PrizePicksSource.clear()


@pytest.fixture(autouse=True)
def _no_stray_slate_warm_ups():
    """Don't let a test's background slate simulation outlive it.

    Hitting `/api/games` starts the server simulating that date — the whole
    point of the feature, and a real fifteen-game Monte Carlo when a test does
    it. Those threads share one CPU lock, so left running they queue up behind
    each other and every later test waits on a slate it never asked for. The
    suite went from 80 seconds to not finishing.
    """
    yield
    from thebeast import slate

    slate.reset()
