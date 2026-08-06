"""Seasons of league baseball, and what they say about the week ahead.

Comparing this week with last week is two small samples arguing. This module
supplies the two things that make a trend statement worth printing:

**A real baseline.** Season-to-date league level from thousands of games, so
"above normal" means above the league's actual normal rather than above our own
eighty-game record — which is a baseline that moves whenever the thing being
measured moves, and therefore hides exactly the trend it is meant to reveal.

**A calendar effect.** Baseball is not stationary across a season. Home runs
carry in August air, bullpens are deeper in September, cold April nights
suppress scoring. Prior seasons already contain that shape, so the week ahead
can be anticipated rather than merely extrapolated: take how the same calendar
window behaved relative to its own season in each previous year, and that is a
forward-looking input that owes nothing to the current week's noise.

The record is a committed JSONL for the same reason the graded games are — the
container is rebuilt from its image on deploy, so a runtime fetch would be gone
by the next push. The scheduled job refreshes it; the app only reads it.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

HISTORY_PATH = "data/accuracy/league_history.jsonl"

# Weeks are counted from here in every season, so bucket 12 covers the same
# stretch of June whichever year it is. Kept in step with the fetcher's
# `SEASON_START`, but defined locally so reading the record never imports the
# module that talks to the network.
WEEK_ANCHOR = (3, 20)

# A full modern season is about 2,430 games. Anything well short of that is a
# partial fetch rather than a season, and should be picked up again.
MIN_SEASON_GAMES = 2000

# Which league metrics have deep history behind them, and how to get each from
# a day or window record. Everything else stays on our own graded record.
_DAILY_METRICS = {
    "runs_per_game":  lambda d: (d["runs"], d["games"]),
    "home_win_rate":  lambda d: (d["home_wins"], d["games"]),
    "one_run_rate":   lambda d: (d["one_run"], d["games"]),
    "blowout_rate":   lambda d: (d["blowouts"], d["games"]),
}

# Window records count team-games (two per contest), so a per-game rate needs
# the pair put back together.
_WINDOW_METRICS = {
    "home_runs_per_game":  "home_runs",
    "strikeouts_per_game": "strikeouts",
    "walks_per_game":      "walks",
    "hits_per_game":       "hits",
}


def _path(path=None, *, root: Optional[str] = None) -> Path:
    if path:
        return Path(path)
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    return base / HISTORY_PATH


class LeagueHistory:
    """Loaded history, with the questions the trend pages actually ask."""

    def __init__(self, days: list[dict], windows: list[dict]) -> None:
        self.days = sorted(days, key=lambda d: d["date"])
        self.windows = sorted(windows, key=lambda w: (w["season"], w["start"]))

    # ── construction ────────────────────────────────────────────────────────

    def __bool__(self) -> bool:
        return bool(self.days or self.windows)

    @property
    def seasons(self) -> list[int]:
        out = {int(d["date"][:4]) for d in self.days}
        out |= {int(w["season"]) for w in self.windows}
        return sorted(out)

    @property
    def game_count(self) -> int:
        return sum(int(d.get("games", 0)) for d in self.days)

    def covers(self, metric: str) -> bool:
        if metric in _DAILY_METRICS:
            return bool(self.days)
        return metric in _WINDOW_METRICS and bool(self.windows)

    # ── levels ──────────────────────────────────────────────────────────────

    def _daily_rate(self, metric: str, rows: Iterable[dict]) -> Optional[float]:
        get = _DAILY_METRICS[metric]
        num = den = 0.0
        for r in rows:
            n, g = get(r)
            num += n
            den += g
        return None if den <= 0 else num / den

    def _window_rate(self, metric: str, rows: Iterable[dict]) -> Optional[float]:
        key = _WINDOW_METRICS[metric]
        num = den = 0.0
        for r in rows:
            num += float(r.get(key, 0))
            den += float(r.get("games", 0))
        # `games` is team-games; two of them make one contest.
        return None if den <= 0 else num / (den / 2.0)

    def level(self, metric: str, *, season: Optional[int] = None,
              start: Optional[date] = None,
              end: Optional[date] = None) -> Optional[float]:
        """League level for a metric, optionally restricted to a season or a
        date range. A ratio of sums, never an average of per-day averages —
        the second silently weights a three-game Monday like a fifteen-game
        Saturday."""
        a = start.isoformat() if start else None
        b = end.isoformat() if end else None

        if metric in _DAILY_METRICS:
            rows = [d for d in self.days
                    if (season is None or int(d["date"][:4]) == season)
                    and (a is None or d["date"] >= a)
                    and (b is None or d["date"] <= b)]
            return self._daily_rate(metric, rows)
        if metric in _WINDOW_METRICS:
            rows = [w for w in self.windows
                    if (season is None or int(w["season"]) == season)
                    and (a is None or w["end"] >= a)
                    and (b is None or w["start"] <= b)]
            return self._window_rate(metric, rows)
        return None

    def season_to_date(self, metric: str, season: int,
                       asof: date) -> Optional[float]:
        return self.level(metric, season=season, end=asof)

    def games_behind(self, metric: str, season: int,
                     asof: date) -> int:
        """How many games the season-to-date baseline rests on."""
        a = asof.isoformat()
        if metric in _DAILY_METRICS:
            return sum(int(d["games"]) for d in self.days
                       if int(d["date"][:4]) == season and d["date"] <= a)
        if metric in _WINDOW_METRICS:
            return int(sum(float(w.get("games", 0)) / 2.0 for w in self.windows
                           if int(w["season"]) == season and w["start"] <= a))
        return 0

    # ── weekly series ───────────────────────────────────────────────────────

    def weekly(self, metric: str, *, season: Optional[int] = None,
               through: Optional[date] = None) -> list[dict]:
        """The metric as a series of weeks: `{season, start, end, value, games}`.

        A week is the natural unit here. It is what the page forecasts, it is
        long enough that a single rained-out Tuesday does not dominate, and it
        makes the persistence question — how much of this week shows up in the
        next one — a straight lag-1 regression on evenly spaced points.

        Weeks are anchored to each season's own start so the same bucket falls
        on the same part of the calendar year to year.
        """
        b = through.isoformat() if through else None
        if metric in _WINDOW_METRICS:
            key = _WINDOW_METRICS[metric]
            out = []
            for w in self.windows:
                if season is not None and int(w["season"]) != season:
                    continue
                if b is not None and w["start"] > b:
                    continue
                games = float(w.get("games", 0)) / 2.0
                if games <= 0:
                    continue
                out.append({"season": int(w["season"]), "start": w["start"],
                            "end": w["end"], "games": games,
                            "value": float(w.get(key, 0)) / games})
            return out
        if metric not in _DAILY_METRICS:
            return []

        get = _DAILY_METRICS[metric]
        buckets: dict[tuple[int, str], dict] = {}
        for d in self.days:
            yr = int(d["date"][:4])
            if season is not None and yr != season:
                continue
            if b is not None and d["date"] > b:
                continue
            day = date.fromisoformat(d["date"])
            anchor = date(yr, *WEEK_ANCHOR)
            if day < anchor:
                continue
            idx = (day - anchor).days // 7
            start = anchor + timedelta(days=idx * 7)
            key = (yr, start.isoformat())
            n, g = get(d)
            rec = buckets.setdefault(key, {
                "season": yr, "start": start.isoformat(),
                "end": (start + timedelta(days=6)).isoformat(),
                "_num": 0.0, "games": 0.0})
            rec["_num"] += n
            rec["games"] += g
        out = []
        for rec in sorted(buckets.values(), key=lambda r: (r["season"], r["start"])):
            if rec["games"] <= 0:
                continue
            rec["value"] = rec.pop("_num") / rec["games"]
            out.append(rec)
        return out

    # ── the calendar ────────────────────────────────────────────────────────

    def _weekly_ratios(self, metric: str,
                       exclude_season: Optional[int]) -> list[dict]:
        """Every prior week as a fraction of its own season's level.

        Dividing by the season removes year-to-year level shifts — 2023 scored
        more than 2024 — so what is left is purely where in the calendar a week
        sat. This is also the reference distribution: how far a *typical* week
        strays from its season is the only honest yardstick for deciding
        whether a particular stretch of the calendar strays further.
        """
        out = []
        for w in self.weekly(metric):
            if exclude_season is not None and w["season"] == exclude_season:
                continue
            level = self.level(metric, season=w["season"])
            if not level:
                continue
            out.append({**w, "ratio": w["value"] / level})
        return out

    def calendar_factor(self, metric: str, start: date, end: date, *,
                        exclude_season: Optional[int] = None,
                        min_seasons: int = 2, pad_days: int = 7,
                        min_z: float = 2.0) -> Optional[dict]:
        """How this stretch of the calendar usually compares with its season.

        Returned as a multiplier: 1.08 means the league typically runs 8% above
        its season average around these dates.

        Two things stop this from inventing effects. The estimate is taken over
        a window padded either side of the target, because the question is what
        mid-August does rather than what these exact seven days did — three
        seasons of one week is about 300 games, which is not enough to see an
        8% effect through the noise.

        And significance is judged against how much an ordinary week strays
        from its own season, not against the spread of the three seasonal
        ratios. The latter is a t-test with two degrees of freedom, and it will
        happily report z of 5 on three coin flips that happen to land the same
        way. That is not a hypothetical: it initially produced a 15% "calendar
        effect" on blowouts and a 20% one on one-run games — opposite tails of
        the same distribution, both supposedly rising, both pure noise.
        """
        reference = self._weekly_ratios(metric, exclude_season)
        if len(reference) < 20:
            return None
        ref_vals = [r["ratio"] for r in reference]
        ref_mean = sum(ref_vals) / len(ref_vals)
        ref_sd = math.sqrt(sum((v - ref_mean) ** 2 for v in ref_vals)
                           / (len(ref_vals) - 1))

        lo_pad = start - timedelta(days=pad_days)
        hi_pad = end + timedelta(days=pad_days)
        picked: dict[int, list[dict]] = {}
        for r in reference:
            # Match on the day of the year, so the same stretch of calendar is
            # selected whichever season a week belongs to.
            try:
                shifted = date(lo_pad.year, *_md(r["start"]))
            except ValueError:
                continue
            if lo_pad <= shifted <= hi_pad:
                picked.setdefault(r["season"], []).append(r)

        if len(picked) < min_seasons:
            return None
        weeks = [w for rows in picked.values() for w in rows]
        games = sum(w["games"] for w in weeks)
        if games <= 0:
            return None
        factor = sum(w["ratio"] * w["games"] for w in weeks) / games

        # One point per season, for the direction check only.
        per_season = {}
        for season, rows in picked.items():
            g = sum(w["games"] for w in rows)
            per_season[season] = sum(w["ratio"] * w["games"] for w in rows) / g

        se = ref_sd / math.sqrt(len(weeks)) if ref_sd > 0 else 0.0
        z = (factor - 1.0) / se if se > 0 else 0.0
        vals = list(per_season.values())
        consistent = all(v > 1 for v in vals) or all(v < 1 for v in vals)

        # What the forecast actually applies is the effect charged its own
        # standard error, not the raw one — the same treatment the persistence
        # slope gets, and for the same reason.
        #
        # A hard significance gate was the first attempt and it behaved badly
        # on real data: the August home-run lift measures 1.072, 1.075 and
        # 1.091 across three adjacent windows, all three seasons agreeing every
        # time, and a z threshold of 2 admits the last two and rejects the
        # first. The same physical effect blinking on and off between one
        # Sunday and the next is an artefact of the cutoff, not a finding.
        # Shrinking continuously keeps the ordering — noise still lands on
        # zero, because an effect smaller than its own error has nothing left
        # after the subtraction.
        effect = factor - 1.0
        if not consistent or abs(effect) <= se:
            applied = 1.0
        else:
            applied = 1.0 + effect - math.copysign(se, effect)
        return {
            "factor": factor, "applied": applied, "se": se, "z": z,
            "reference_sd": ref_sd,
            "weeks": len(weeks), "games": int(round(games)),
            "seasons": sorted(per_season),
            "per_season": {str(s): round(v, 4) for s, v in per_season.items()},
            "consistent": consistent,
            "significant": bool(consistent and abs(z) >= min_z),
            # Whether the forecast leaned on it at all.
            "applies": applied != 1.0,
        }


def _md(iso: str) -> tuple[int, int]:
    return int(iso[5:7]), int(iso[8:10])


# ── the record ──────────────────────────────────────────────────────────────

def load(path=None, *, root: Optional[str] = None) -> LeagueHistory:
    p = _path(path, root=root)
    if not p.exists():
        return LeagueHistory([], [])
    days: list[dict] = []
    windows: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue              # a broken line costs one day, not the file
        if rec.get("kind") == "day":
            days.append(rec)
        elif rec.get("kind") == "window":
            windows.append(rec)
    return LeagueHistory(days, windows)


def save(days: list[dict], windows: list[dict], path=None, *,
         root: Optional[str] = None) -> int:
    p = _path(path, root=root)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = ([dict(d, kind="day") for d in sorted(days, key=lambda d: d["date"])]
            + [dict(w, kind="window")
               for w in sorted(windows, key=lambda w: (w["season"], w["start"]))])
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
    return len(rows)


def refresh(seasons: list[int], *, asof: Optional[date] = None, path=None,
            source=None, windows: bool = True) -> dict:
    """Fetch and merge league history for `seasons`.

    Completed seasons are only fetched once — they cannot change — so a rerun
    costs one season of calls, not all of them. The current season is always
    re-fetched from scratch because its later days keep arriving.
    """
    from .data.sources.league import MLBLeagueSource

    asof = asof or date.today()
    src = source or MLBLeagueSource()
    existing = load(path)
    current = asof.year

    have_days = {d["date"] for d in existing.days}
    have_windows = {(int(w["season"]), w["start"]) for w in existing.windows}
    kept_days = [d for d in existing.days if int(d["date"][:4]) != current]
    kept_windows = [w for w in existing.windows if int(w["season"]) != current]

    new_days, new_windows = [], []
    fetched_seasons = []
    for season in sorted(set(seasons)):
        settled = season < current
        # "Already have it" has to mean a whole season, not a single day. A
        # fetch that died halfway through 2024 leaves a stub, and treating any
        # row as proof of coverage would freeze that stub in place forever —
        # the record would look complete and quietly never be.
        have = sum(int(d.get("games", 0)) for d in existing.days
                   if int(d["date"][:4]) == season)
        if settled and have >= MIN_SEASON_GAMES:
            continue                       # a finished season is finished
        fetched_seasons.append(season)
        through = asof if season == current else None
        for day in src.fetch_season_days(season, through=through):
            new_days.append(asdict(day))
        if windows:
            for win in src.fetch_season_windows(season, through=through):
                rec = asdict(win)
                rec.pop("extra", None)
                new_windows.append(rec)

    merged_days = kept_days + [d for d in new_days
                               if int(d["date"][:4]) == current
                               or d["date"] not in have_days]
    merged_windows = kept_windows + [
        w for w in new_windows
        if int(w["season"]) == current
        or (int(w["season"]), w["start"]) not in have_windows]

    # Deduplicate on the natural key, newest write winning.
    by_day = {d["date"]: d for d in merged_days}
    by_win = {(int(w["season"]), w["start"]): w for w in merged_windows}
    rows = save(list(by_day.values()), list(by_win.values()), path)

    hist = LeagueHistory(list(by_day.values()), list(by_win.values()))
    return {
        "rows": rows,
        "seasons": hist.seasons,
        "fetched": fetched_seasons,
        "days": len(by_day),
        "windows": len(by_win),
        "games": hist.game_count,
        "refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
