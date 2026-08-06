"""Make `thebeast` importable from tests without requiring `pip install -e .`."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


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
