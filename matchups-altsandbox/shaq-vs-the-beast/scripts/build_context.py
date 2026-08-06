"""Populate park factors (2023 results) and per-game weather (2024) into the DB.

  uv run python scripts/build_context.py
"""
from __future__ import annotations

import sys
import warnings
from datetime import date, timedelta

warnings.filterwarnings("ignore")

from thebeast.data.park_factors import compute_park_factors
from thebeast.data.repository import SQLiteRepository
from thebeast.data.sources.results import MLBResultsSource
from thebeast.data.sources.weather import MLBWeatherSource

DB = "local_data/thebeast.db"
PARK_SEASON = 2023
PARK_SPAN = (date(2023, 3, 30), date(2023, 10, 1))
WEATHER_SPAN = (date(2024, 3, 28), date(2024, 9, 30))


def log(m: str) -> None:
    print(m, flush=True)


def _dates(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def build_park_factors(repo: SQLiteRepository) -> None:
    if repo.get_park_factor("COL", PARK_SEASON) is not None:
        log("[park] already present — skipping")
        return
    src = MLBResultsSource()
    results = []
    for d in _dates(*PARK_SPAN):
        try:
            results.extend(src.fetch_results(d))
        except Exception as exc:
            log(f"[park] {d} failed: {exc}")
    log(f"[park] fetched {len(results)} final games")
    factors = compute_park_factors(results, PARK_SEASON)
    for pf in factors:
        repo.save_park_factor(pf)
    top = sorted(factors, key=lambda p: -p.runs_factor)
    log(f"[park] stored {len(factors)} parks; "
        f"highest {top[0].venue_id}={top[0].runs_factor}, "
        f"lowest {top[-1].venue_id}={top[-1].runs_factor}")


def build_weather(repo: SQLiteRepository) -> None:
    src = MLBWeatherSource(repo)
    total = 0
    for i, d in enumerate(_dates(*WEATHER_SPAN), 1):
        try:
            total += len(src.fetch_weather(d))
        except Exception as exc:
            log(f"[weather] {d} failed: {exc}")
        if i % 30 == 0:
            log(f"[weather] {d} … {total} games stored")
    log(f"[weather] stored {total} game weather rows")


def main() -> int:
    repo = SQLiteRepository(DB)
    build_park_factors(repo)
    build_weather(repo)
    log("[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
