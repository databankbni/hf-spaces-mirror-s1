"""Which seasons the app reads, in one place.

These were defined twice — once in `api.main` and once in `live.py`, both
spelled 2026, with a comment in the second saying it "mirrors the API's current
season". Mirrors held by hand come apart: at the rollover one gets edited and
the other doesn't, and the failure is silent. A live game would quietly look up
pitcher statlines for the wrong year and fall back to league average, which
reads as a modelling result rather than a stale constant.

`api.main` imports `live`, so neither could own it. This module imports nothing
from the package, which is what lets both take it from here.
"""
from __future__ import annotations

# Statlines used for upcoming-game predictions.
CURRENT_SEASON = 2026

# Park factors are stable year to year, so this deliberately lags: it points at
# the most recent season with a full set of measured factors rather than at the
# one in progress.
PARK_SEASON = 2023
