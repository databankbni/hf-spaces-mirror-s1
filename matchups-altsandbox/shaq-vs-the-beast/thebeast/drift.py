"""Watching the model drift, early enough to do something about it.

The accuracy report says how the model did. This says where it is *going*, and
which of the numbers in that report are worth acting on at all.

Three questions, because they are genuinely different:

**Is this real?** The first two graded windows had winner accuracy of 40.5%
then 53.5%, and a totals bias that flipped sign. Neither was a model change;
both were a fortnight of baseball. A bias is only worth chasing when it clears
sampling error *and* points the same way in both halves of the record — a
metric that flips sign has told you nothing except its own variance.

**Is it moving?** A bias that is small but growing matters more than a larger
one that is flat, because the flat one is already priced into what you know
and the growing one is not. Each metric is regressed on time, so a drift shows
up while it is still small.

**When will we know?** For anything not yet significant, the honest answer is
a sample size rather than a verdict — how many more games until the current
effect, if real, would clear the bar. That turns "not significant" from a dead
end into a date.

Alongside that, the leading indicators: the rates fed *into* the simulation
compared with the rates actually being played. Those diverge before any
projection error appears in a graded report, which is the only part of this
that genuinely predicts rather than detects.
"""
from __future__ import annotations

import math
from typing import Any, Optional

# Metrics worth tracking, with the value that means "no error" and a
# tolerance below which a difference is not worth anyone's attention even if
# the sample says it is real.
_NULL = 0.0

# Per-PA rate ratios (projected / actual). 1.0 is perfect; a 3% miss on a
# counting stat is inside what lineup and usage noise can explain.
_RATE_TOLERANCE = 0.03


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _sd(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _slope(xs: list[float]) -> tuple[float, float]:
    """Least-squares slope of `xs` against its index, and the slope's SE.

    Reported per 100 games so the number is readable: a totals bias drifting
    "+0.4 runs per 100 games" is immediately interpretable in a way that a
    per-game slope of 0.004 is not.
    """
    n = len(xs)
    if n < 8:
        return 0.0, 0.0
    mx = (n - 1) / 2
    my = _mean(xs)
    sxx = sum((i - mx) ** 2 for i in range(n))
    if sxx <= 0:
        return 0.0, 0.0
    b = sum((i - mx) * (y - my) for i, y in enumerate(xs)) / sxx
    resid = [y - (my + b * (i - mx)) for i, y in enumerate(xs)]
    s2 = sum(r * r for r in resid) / (n - 2)
    se = math.sqrt(s2 / sxx) if s2 > 0 else 0.0
    return b * 100, se * 100


def assess(values: list[float], *, null: float = _NULL,
           tolerance: float = 0.0, label: str = "",
           scale: Optional[float] = None) -> dict:
    """Turn a per-game series into a verdict, a trend, and a sample size.

    `values` are one observation per game, already expressed as an error
    (actual minus projected, or a ratio minus one) so that `null` is the
    no-error value.
    """
    n = len(values)
    if n < 3:
        return {"metric": label, "n": n, "verdict": "no data"}

    mean = _mean(values)
    sd = _sd(values)
    se = sd / math.sqrt(n) if sd > 0 else 0.0
    if se > 0:
        z = (mean - null) / se
    else:
        # No variance at all. Every game missed by the same amount, which is
        # the strongest evidence a bias can have, not the weakest — so this
        # must not fall through to z = 0 and read as noise.
        z = 0.0 if mean == null else math.copysign(float("inf"), mean - null)

    # Split-half agreement. This is the check that separated the calibrator's
    # real defect from the totals bias that merely looked like one.
    half = n // 2
    first, second = _mean(values[:half]), _mean(values[half:])
    consistent = (first - null) * (second - null) > 0

    slope, slope_se = _slope(values)
    slope_z = slope / slope_se if slope_se > 0 else 0.0

    effect = abs(mean - null)
    material = effect > tolerance
    # Games needed for an effect this size to clear |z| = 2, if it is real.
    needed = None
    if sd > 0 and effect > 0:
        needed = int(math.ceil((2 * sd / effect) ** 2))

    if not material:
        verdict = "immaterial"
    elif abs(z) >= 2 and consistent:
        verdict = "act"
    elif abs(z) >= 2:
        verdict = "unstable"          # significant but flips between halves
    elif abs(slope_z) >= 2:
        verdict = "drifting"
    elif abs(z) >= 1:
        verdict = "watch"
    else:
        verdict = "noise"

    out: dict[str, Any] = {
        "metric": label, "n": n,
        "mean": round(mean, 4), "null": null,
        "se": round(se, 4),
        "z": (round(z, 2) if math.isfinite(z) else z),
        "first_half": round(first, 4), "second_half": round(second, 4),
        "consistent": consistent,
        "trend_per_100": round(slope, 4), "trend_z": round(slope_z, 2),
        "verdict": verdict,
    }
    if scale:
        # Mean difference over mean actual — the ratio of means, which is the
        # correct aggregate. Averaging per-game ratios instead would let the
        # lowest-count games dominate.
        out["ratio"] = round(1.0 + mean / scale, 3)
        out["actual_per_game"] = round(scale, 3)
    if needed is not None and abs(z) < 2:
        out["games_for_significance"] = needed
        out["more_games_needed"] = max(0, needed - n)
    if abs(slope_z) >= 1.5 and n >= 20:
        # Where it lands in another 100 games if the drift holds. Explicitly a
        # projection, not a prediction — it assumes the trend continues.
        out["projected_in_100_games"] = round(mean + slope, 4)
    return out


# ── building the series off the graded record ───────────────────────────────

def _per_game_error(game: dict, side: str, stat: str) -> Optional[tuple[float, float]]:
    """(projected minus actual, actual) for one stat over a whole game.

    Deliberately a difference, not a per-game ratio. A game where one walk was
    projected and none happened has a ratio of infinity, and one with two
    against one has a ratio of 2.0 — averaging those makes a low-count stat
    look catastrophically over-projected because the games with the smallest
    denominators shout loudest. The first draft of this did exactly that and
    reported walks 62% high against the 13% they actually are.

    The difference is the paired quantity a test wants anyway, and dividing
    the mean difference by the mean actual afterwards recovers the ratio
    correctly.
    """
    proj = act = 0.0
    seen = False
    for row in game.get(side, []):
        v = (row.get("stats") or {}).get(stat) or {}
        if v.get("projected") is None or v.get("actual") is None:
            continue
        proj += float(v["projected"])
        act += float(v["actual"])
        seen = True
    return (proj - act, act) if seen else None


def series(games: list[dict]) -> tuple[dict[str, list[float]], dict[str, float]]:
    """Per-game observations for everything tracked, oldest first.

    Returns the series plus, for the counting stats, the mean actual per game
    — the denominator that turns a mean difference back into a readable ratio.
    """
    games = sorted(games, key=lambda g: (g.get("date", ""), g.get("game_id", "")))
    out: dict[str, list[float]] = {}
    scale_sums: dict[str, list[float]] = {}

    def add(key: str, v: Optional[float]) -> None:
        if v is not None:
            out.setdefault(key, []).append(float(v))

    for g in games:
        o = g.get("outcome") or {}
        t, s = o.get("total") or {}, o.get("spread") or {}
        # Sign convention for the outcome metrics: actual minus projected, so
        # positive means the model came in low.
        add("total_runs", t.get("error"))
        add("margin", s.get("error"))
        if t.get("covered") is not None:
            # Coverage is scored against its own target, not against zero.
            add("total_coverage", 1.0 if t["covered"] else 0.0)
        p = o.get("home_win_probability")
        if p is not None and (g.get("actual") or {}).get("winner") in ("home", "away"):
            won = 1.0 if g["actual"]["winner"] == "home" else 0.0
            add("home_win_prob", won - p)     # >0 means home won more than called

        # Counting stats: projected minus actual, so a positive mean means the
        # model produced too many.
        #
        # Volume and rate are tracked separately, because they have different
        # causes and only one of them is usually the real fault. Hits and
        # strikeouts both came in "too high" purely because too many plate
        # appearances were projected; per PA they were fine. Reporting the raw
        # counts alone raises seven alarms for two problems and buries which
        # two. So each stat is also rescaled to the plate appearances that
        # actually happened, which removes the volume error and leaves the
        # rate error on its own.
        for side, prefix, volume, stats in (
            ("batters", "bat", "pa", ("hits", "bb", "k", "home_runs", "rbi")),
            ("pitchers", "pit", "outs", ("pitches", "bb_allowed", "k",
                                         "hits_allowed", "runs_allowed")),
        ):
            vol = _per_game_error(g, side, volume)
            if vol is None:
                continue
            vol_diff, vol_act = vol
            add(f"{prefix}_{volume}", vol_diff)
            scale_sums.setdefault(f"{prefix}_{volume}", []).append(vol_act)

            vol_proj = vol_act + vol_diff
            for stat in stats:
                got = _per_game_error(g, side, stat)
                if got is None:
                    continue
                diff, act = got
                proj = act + diff
                if vol_proj <= 0 or vol_act <= 0:
                    continue
                # What the projection would have been at the real volume.
                add(f"{prefix}_{stat}_rate", proj * (vol_act / vol_proj) - act)
                scale_sums.setdefault(f"{prefix}_{stat}_rate", []).append(act)

    scale = {k: _mean(v) for k, v in scale_sums.items() if _mean(v) > 0}
    return out, scale


_TOLERANCE = {
    "total_runs": 0.25,       # a quarter-run on a ~4-run SD is not actionable
    "margin": 0.25,
    "home_win_prob": 0.03,
    "total_coverage": 0.05,
}


def build_drift_report(games: list[dict]) -> dict:
    """Assess every tracked metric and rank what is worth acting on."""
    ser, scale = series(games)
    rows = []
    for key, vals in sorted(ser.items()):
        null = 0.80 if key == "total_coverage" else _NULL
        sc = scale.get(key)
        # A counting stat's tolerance is a share of how often it happens: 3%
        # of the walks in a game, not an absolute 0.03 walks.
        tol = _TOLERANCE.get(key, _RATE_TOLERANCE * sc if sc else _RATE_TOLERANCE)
        rows.append(assess(vals, null=null, tolerance=tol, label=key, scale=sc))

    order = {"act": 0, "drifting": 1, "unstable": 2, "watch": 3,
             "noise": 4, "immaterial": 5, "no data": 6}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), -abs(r.get("z", 0))))
    return {
        "games": len(games),
        "metrics": rows,
        "actionable": [r["metric"] for r in rows
                       if r["verdict"] in ("act", "drifting")],
    }


def leading_indicators(repo, games: list[dict], season: int) -> dict:
    """Rates going *into* the simulation against rates actually being played.

    This is the part that predicts rather than detects. The simulator's PA
    outcome distributions are built from stored statlines, so if the league is
    walking less than those statlines say, every future projection is already
    wrong by that margin — visible before a single new game is graded.

    Reported as a ratio: statline rate over realised rate. 1.10 means the
    simulation will over-produce that outcome by about 10% until the statlines
    catch up.
    """
    try:
        batters = repo.get_batters_for_season(season)
    except Exception:
        return {"available": False, "reason": "no statlines"}
    pa_total = sum(b.pa for b in batters)
    if not pa_total:
        return {"available": False, "reason": "no plate appearances on file"}

    def league(attr: str) -> float:
        return sum(getattr(b, attr) * b.pa for b in batters) / pa_total

    # Realised rates across the graded games, from the actual box scores.
    tot: dict[str, float] = {}
    pa_seen = 0.0
    for g in games:
        for row in g.get("batters", []):
            st = row.get("stats") or {}
            pa = (st.get("pa") or {}).get("actual")
            if pa is None:
                continue
            pa_seen += pa
            for stat in ("hits", "bb", "k", "home_runs"):
                v = (st.get(stat) or {}).get("actual")
                if v is not None:
                    tot[stat] = tot.get(stat, 0.0) + v
    if pa_seen < 500:
        return {"available": False, "reason": f"only {int(pa_seen)} graded PA"}

    pairs = (("bb", "bb_rate"), ("home_runs", "hr_rate"), ("k", "k_rate"))
    rows = []
    for stat, attr in pairs:
        realised = tot.get(stat, 0.0) / pa_seen
        fed = league(attr)
        if realised <= 0:
            continue
        events = tot.get(stat, 0.0)
        se = math.sqrt(events) / pa_seen if events > 0 else 0.0
        rows.append({
            "stat": stat,
            "statline_rate": round(fed, 5),
            "realised_rate": round(realised, 5),
            "ratio": round(fed / realised, 3),
            "z": round((fed - realised) / se, 2) if se > 0 else 0.0,
            "graded_pa": int(pa_seen),
        })
    rows.sort(key=lambda r: -abs(r["ratio"] - 1))
    return {"available": True, "season": season, "rates": rows,
            "note": ("ratio > 1 means the simulation will keep over-producing "
                     "that outcome until the statlines catch up to the league")}
