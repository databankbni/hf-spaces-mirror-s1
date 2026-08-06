"""What has actually been happening on the field, and what should happen next.

This is deliberately *not* the drift monitor. Drift asks "where is the model
wrong"; this asks "what is baseball doing" — scoring, home runs, how long
starters are lasting, whether home teams are holding serve. Every number here
comes out of a real box score. The simulation only ever supplies a reference
point, and where it does the wording says so.

Two halves, and they are different kinds of claim:

**What we have been seeing** is description: the last seven days through today,
against the season so far. Nothing to grade — it either happened or it didn't.

**The week ahead** is a forecast, covering the seven days starting tomorrow.
The two windows are deliberately adjacent, because the persistence slope is
fitted on consecutive weeks and so answers exactly one question: given the week
just played, where does the next one land. Forecasting further out with that
same slope would be using a one-step relationship for a multi-step problem.

The interesting part of the forecast is that the honest answer is usually "less
than you think". A week of baseball is a small sample, so most of a swing is
noise and washes out, and how much survives is measured rather than assumed.

Forecasts are written down with their window and graded on the games that fall
inside it, same rule as everything else here.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Optional

# How each tracked quantity reads in a sentence. `digits` is display precision,
# `share` marks the ones that are percentages rather than counts, and `noun`
# finishes the phrase "9.42 ___".
_METRICS: dict[str, dict[str, Any]] = {
    "runs_per_game": {
        "label": "Scoring", "noun": "runs a game", "digits": 2,
        "up": "up", "down": "down"},
    "home_runs_per_game": {
        "label": "Home runs", "noun": "a game", "digits": 2,
        "up": "up", "down": "down"},
    "strikeouts_per_game": {
        "label": "Strikeouts", "noun": "a game", "digits": 1,
        "up": "up", "down": "down"},
    "walks_per_game": {
        "label": "Walks", "noun": "a game", "digits": 2,
        "up": "up", "down": "down"},
    "hits_per_game": {
        "label": "Hits", "noun": "a game", "digits": 1,
        "up": "up", "down": "down"},
    "starter_innings": {
        "label": "Starting pitchers", "noun": "innings a start", "digits": 2,
        "up": "lasting longer", "down": "getting pulled earlier"},
    "starter_pitches": {
        "label": "Starter pitch counts", "noun": "pitches a start", "digits": 1,
        "up": "up", "down": "down"},
    "bullpen_innings": {
        "label": "Bullpens", "noun": "innings a game", "digits": 2,
        "up": "working more", "down": "working less"},
    "home_win_rate": {
        "label": "Home teams", "noun": "of games", "digits": 0, "share": True,
        "up": "holding serve", "down": "struggling"},
    "one_run_rate": {
        "label": "One-run games", "noun": "of the slate", "digits": 0,
        "share": True, "up": "up", "down": "down"},
    "blowout_rate": {
        "label": "Blowouts", "noun": "of the slate", "digits": 0,
        "share": True, "up": "up", "down": "down"},
}

# Order matters: the homepage shows the top few, and scoring is the thing a
# reader cares about first.
_ORDER = list(_METRICS)

GAMES_PER_DAY = 15

# Bumped whenever the forecasting rule changes in a way that would produce a
# different number from the same data. It rides in the forecast id, so a change
# issues a fresh claim instead of colliding with the old one and being silently
# dropped — which would otherwise force a hand-edit of the record, and a record
# that can be hand-edited is not a record. The superseded forecast stays open,
# gets graded on its own window, and the scorecard can say which rule was
# better.
#
#   1  first league forecasts: shrinkage from a variance decomposition
#   2  lag-1 persistence, seasons of league history, calendar effect charged
#      its own standard error rather than passed through a significance gate
METHOD = 2


# ── pulling league quantities out of the graded record ──────────────────────

def _stat(row: dict, name: str, field: str) -> Optional[float]:
    s = (row.get("stats") or {}).get(name) or {}
    v = s.get(field)
    return None if v is None else float(v)


def _sum(rows: list[dict], name: str, field: str) -> float:
    return sum(v for r in rows if (v := _stat(r, name, field)) is not None)


def _game_row(game: dict) -> dict[str, tuple[float, Optional[float]]]:
    """One game's league quantities as (actual, expected) pairs.

    `expected` is what the simulation projected for that same game, which is
    season form filtered through the matchup. It is a reference point, not a
    claim — where a card uses it, it says so.
    """
    actual = game.get("actual") or {}
    outcome = game.get("outcome") or {}
    batters = game.get("batters") or []
    # Every player who appeared is in the record, projected or not, so summing
    # actuals gives the real league totals rather than the lineup-card ones.
    pitchers = game.get("pitchers") or []
    starters = [p for p in pitchers if p.get("role") == "SP"]
    relievers = [p for p in pitchers if p.get("role") == "RP"]

    total = actual.get("total")
    spread = actual.get("spread")
    proj_total = None
    hr_mean = ((outcome.get("home_runs") or {}).get("mean"))
    ar_mean = ((outcome.get("away_runs") or {}).get("mean"))
    if hr_mean is not None and ar_mean is not None:
        proj_total = float(hr_mean) + float(ar_mean)

    out: dict[str, tuple[float, Optional[float]]] = {}

    if total is not None:
        out["runs_per_game"] = (float(total), proj_total)
    for key, stat in (("home_runs_per_game", "home_runs"),
                      ("strikeouts_per_game", "k"),
                      ("walks_per_game", "bb"),
                      ("hits_per_game", "hits")):
        if batters:
            out[key] = (_sum(batters, stat, "actual"),
                        _sum(batters, stat, "projected") or None)
    if starters:
        # Per start, not per game: a doubleheader half and a normal night both
        # ask the same question of a starting pitcher.
        n = len(starters)
        outs = _sum(starters, "outs", "actual") / n
        proj_outs = _sum(starters, "outs", "projected") / n
        out["starter_innings"] = (outs / 3.0, (proj_outs / 3.0) or None)
        pitches = _sum(starters, "pitches", "actual") / n
        proj_p = _sum(starters, "pitches", "projected") / n
        out["starter_pitches"] = (pitches, proj_p or None)
    if relievers:
        # The record carries one aggregate reliever row per side, so this is
        # bullpen innings per side, doubled to read as a whole game.
        n = max(len(relievers), 1)
        outs = _sum(relievers, "outs", "actual") / n
        proj_outs = _sum(relievers, "outs", "projected") / n
        out["bullpen_innings"] = (2 * outs / 3.0, (2 * proj_outs / 3.0) or None)

    winner = actual.get("winner")
    if winner in ("home", "away"):
        p = outcome.get("home_win_probability")
        out["home_win_rate"] = (1.0 if winner == "home" else 0.0,
                                None if p is None else float(p))
    if spread is not None:
        out["one_run_rate"] = (1.0 if abs(float(spread)) == 1 else 0.0, None)
        out["blowout_rate"] = (1.0 if abs(float(spread)) >= 5 else 0.0, None)
    return out


def league_series(games: list[dict]) -> dict[str, list[dict]]:
    """Per-metric, per-game observations sorted by date."""
    out: dict[str, list[dict]] = {k: [] for k in _METRICS}
    for g in games:
        d = g.get("date") or ""
        for key, (act, exp) in _game_row(g).items():
            out.setdefault(key, []).append(
                {"date": d, "actual": act, "expected": exp})
    for rows in out.values():
        rows.sort(key=lambda r: r["date"])
    return {k: v for k, v in out.items() if v}


# ── small statistics ────────────────────────────────────────────────────────

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _var(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def _p_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def _chance_phrase(p: float) -> str:
    """A p-value as something a reader can picture.

    Kept to one short sentence on purpose: these sit under every card, and a
    paragraph repeated eleven times is read as decoration and stops carrying
    the caveat it exists to carry.
    """
    if p >= 0.5:
        return "Well inside normal week-to-week wobble."
    odds = max(2, int(round(1.0 / max(p, 1e-6))))
    if odds >= 1000:
        return "Far beyond normal week-to-week wobble."
    return f"Chance alone would do this about 1 week in {odds}."


def _fmt(spec: dict, value: float) -> str:
    if spec.get("share"):
        return f"{100 * value:.{spec['digits']}f}%"
    return f"{value:.{spec['digits']}f}"


def _day_means(rows: list[dict]) -> list[tuple[str, list[float]]]:
    by_day: dict[str, list[float]] = {}
    for r in rows:
        by_day.setdefault(r["date"], []).append(r["actual"])
    return sorted(by_day.items())


def _persistence(values: list[float]) -> Optional[dict]:
    """How much of one week shows up in the next, from the weeks themselves.

    This is a lag-1 regression on the observed weekly series, and the slope is
    exactly the question the forecast asks: given this week came in at y, where
    does next week land? It is a better instrument than decomposing variance
    into signal and noise, because a level can wobble genuinely and still not
    persist — a hot week caused by a soft schedule reverts as soon as the
    schedule turns over, and the slope sees that while a variance ratio does
    not.

    The slope is charged its own standard error before being returned, for the
    same reason as everywhere else here: an estimate from a dozen weeks is a
    rough estimate, and on a short record the costly mistake is believing a
    swing will hold when it won't.
    """
    n = len(values) - 1
    if n < 4:
        return None
    x, y = values[:-1], values[1:]
    mx, my = _mean(x), _mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx <= 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    syy = sum((b - my) ** 2 for b in y)
    beta = sxy / sxx
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
    resid_var = max(0.0, (syy - beta * sxy) / max(1, n - 2))
    se_beta = math.sqrt(resid_var / sxx) if sxx > 0 else 0.0
    # Shrink toward "none of it carries", by one standard error.
    shrunk = 0.0 if abs(beta) <= se_beta else beta - math.copysign(se_beta, beta)
    return {
        "beta": max(0.0, min(1.0, shrunk)),
        "raw_beta": beta, "se": se_beta, "r2": r2,
        "resid_sd": math.sqrt(resid_var), "n": n,
        "total_sd": math.sqrt(syy / n) if n else 0.0,
    }


def _signal_variance(rows: list[dict]) -> float:
    """How much a day's level really moves, once sampling noise is removed.

    Daily means bounce around for two reasons: the league genuinely plays
    differently some nights, and fifteen games is a small sample. Subtracting
    the second leaves the first. Negative means every wobble seen is explained
    by sample size alone, which is the honest answer often enough to keep.

    The estimate is then charged its own standard error before being used. A
    variance measured from a week of days is barely measured at all, and left
    raw it reads noise as signal and promises a swing will hold when it won't —
    on a short record that is the failure mode, not under-reacting. The penalty
    fades as days accumulate, so the forecast earns its confidence rather than
    assuming it.
    """
    days = _day_means(rows)
    usable = [(d, v) for d, v in days if len(v) >= 3]
    if len(usable) < 3:
        return 0.0
    means = [_mean(v) for _, v in usable]
    between = _var(means)
    within = _mean([_var(v) / len(v) for _, v in usable])
    se = between * math.sqrt(2.0 / (len(usable) - 1))
    return max(0.0, between - within - se)


# ── this week: what has been happening ──────────────────────────────────────

def _window(rows: list[dict], start: date, end: date) -> list[dict]:
    a, b = start.isoformat(), end.isoformat()
    return [r for r in rows if a <= r["date"] <= b]


def _from_history(key: str, history, asof: date, days: int,
                  season: int) -> Optional[dict]:
    """Measure a metric against the season, using every game the league played.

    Preferred over our own graded record wherever the history covers the metric,
    for two reasons. It sees the whole slate rather than the games we happened
    to grade, and it compares against a season baseline built from thousands of
    games instead of the same few weeks the recent window came out of — a
    baseline that moves with the thing it is measuring hides the trend it is
    supposed to reveal.
    """
    if history is None or not history.covers(key):
        return None
    recent_start = asof - timedelta(days=days - 1)
    weeks = history.weekly(key, season=season, through=asof)
    if len(weeks) < 3:
        return None

    recent = [w for w in weeks if w["end"] >= recent_start.isoformat()]
    prior = [w for w in weeks if w["end"] < recent_start.isoformat()]
    if not recent or len(prior) < 2:
        return None

    r_games = sum(w["games"] for w in recent)
    level = sum(w["value"] * w["games"] for w in recent) / r_games
    p_games = sum(w["games"] for w in prior)
    base = sum(w["value"] * w["games"] for w in prior) / p_games

    # A week's spread against the spread of the season's other weeks. The
    # baseline rests on far more games than the window, so its own error is
    # small next to the window's and is not worth pretending to model.
    sd = math.sqrt(_var([w["value"] for w in prior]))
    z = (level - base) / sd if sd > 0 else 0.0
    return {"level": level, "base": base, "z": z, "games": int(round(r_games)),
            "base_games": int(round(p_games)), "weeks": len(prior)}


def recent_trends(games: list[dict], *, asof: Optional[date] = None,
                  days: int = 7, min_games: int = 15, history=None,
                  season: Optional[int] = None) -> list[dict]:
    """Plain description of the last `days` of finished baseball.

    Three ways of measuring, in descending order of what they can support:
    against the season so far using every league game, against the earlier
    games in our own record, and — weakest, and labelled as such on the card —
    against what season form projected.
    """
    asof = asof or date.today()
    season = season or asof.year
    ser = league_series(games)
    recent_start = asof - timedelta(days=days - 1)

    out: list[dict] = []
    for key in _ORDER:
        spec = _METRICS[key]
        hist = _from_history(key, history, asof, days, season)
        if hist is not None:
            out.append(_describe(key, spec, hist["level"], hist["base"],
                                 hist["level"] - hist["base"], hist["z"],
                                 hist["games"], days, "season_to_date",
                                 base_games=hist["base_games"]))
            continue

        rows = ser.get(key) or []
        if not rows:
            continue
        recent = _window(rows, recent_start, asof)
        if len(recent) < min_games:
            continue
        prior = [r for r in rows if r["date"] < recent_start.isoformat()]
        r_vals = [r["actual"] for r in recent]
        r_mean = _mean(r_vals)

        basis = comparison = None
        change = z = None
        if len(prior) >= min_games:
            p_vals = [r["actual"] for r in prior]
            p_mean = _mean(p_vals)
            se = math.sqrt(_var(r_vals) / len(r_vals) + _var(p_vals) / len(p_vals))
            z = (r_mean - p_mean) / se if se > 0 else 0.0
            comparison, change = p_mean, r_mean - p_mean
            basis = "prior_games"
        else:
            paired = [(r["actual"], r["expected"]) for r in recent
                      if r["expected"] is not None]
            if len(paired) >= min_games:
                diffs = [a - e for a, e in paired]
                se = math.sqrt(_var(diffs) / len(diffs))
                z = _mean(diffs) / se if se > 0 else 0.0
                comparison = _mean([e for _, e in paired])
                change = _mean(diffs)
                basis = "season_form"
        if basis is None:
            # Nothing to compare against yet — still worth stating the level.
            out.append(_describe(key, spec, r_mean, None, None, None,
                                 len(recent), days, "level_only"))
            continue
        out.append(_describe(key, spec, r_mean, comparison, change, z,
                             len(recent), days, basis))

    # Loudest first, but a metric with no comparison sinks to the bottom.
    out.sort(key=lambda t: -abs(t.get("z") or 0))
    return out


def _describe(key: str, spec: dict, level: float, comparison: Optional[float],
              change: Optional[float], z: Optional[float], n: int, days: int,
              basis: str, base_games: Optional[int] = None) -> dict:
    label, noun = spec["label"], spec["noun"]
    lvl = _fmt(spec, level)

    if basis == "level_only" or change is None or z is None:
        headline = f"{label}: {lvl} {noun}"
        detail = (f"Across {n} games in the last {days} days. Not enough "
                  f"earlier games in the record yet to say which way it is "
                  f"moving.")
        direction, moving, firm = "flat", False, False
    else:
        p = _p_two_sided(z)
        # Three tiers, because two would force a 13% move to be called either
        # a trend or nothing. The middle one is the honest home for most of a
        # week's worth of games.
        firm, moving = p < 0.10, p < 0.35
        rising = change > 0
        direction = "up" if rising else "down"
        word = spec["up"] if rising else spec["down"]
        if not moving:
            headline = f"{label} steady at {lvl} {noun}"
        elif firm:
            headline = f"{label} {word} — {lvl} {noun}"
        else:
            headline = f"{label} maybe {word} — {lvl} {noun}"
        if basis == "season_to_date":
            detail = (f"{n} games league-wide, against {_fmt(spec, comparison)} "
                      f"across the season's first {base_games:,} "
                      f"games. {_chance_phrase(p)}")
        elif basis == "prior_games":
            detail = (f"{n} games, {'up' if rising else 'down'} from "
                      f"{_fmt(spec, comparison)} before. {_chance_phrase(p)}")
        else:
            detail = (f"{n} games, against {_fmt(spec, comparison)} implied by "
                      f"season form. {_chance_phrase(p)} Weaker reading than "
                      f"comparing with earlier games.")

    return {
        "metric": key, "label": label, "level": round(level, 4),
        "display": _fmt(spec, level),
        "comparison": None if comparison is None else round(comparison, 4),
        "comparison_display": (None if comparison is None
                               else _fmt(spec, comparison)),
        "change": None if change is None else round(change, 4),
        "change_display": (None if change is None
                           else ("+" if change > 0 else "") + _fmt(spec, change)),
        "change_pct": (None if not comparison or change is None
                       else round(100 * change / abs(comparison), 1)),
        "z": None if z is None else round(z, 2),
        "moving": moving, "firm": firm, "direction": direction,
        "games": n, "days": days, "basis": basis,
        "headline": headline, "detail": detail,
    }


# ── next week: what should happen ───────────────────────────────────────────

def _history_outlook(key: str, spec: dict, history, asof: date, days: int,
                     season: int, conf: float) -> Optional[dict]:
    """Next week from seasons of league data rather than from our own record.

    Three inputs, and only the first two exist in the short-record version:

    Where the season sits, from every game played. Where the calendar says the
    week ahead usually sits relative to that — August air carries, September
    bullpens are deeper, and prior seasons already know it. And how much of the
    current week's departure from all that historically survives into the next
    one, which is a lag-1 slope fitted on real weeks, not an assumption.
    """
    if history is None or not history.covers(key):
        return None
    weeks = history.weekly(key, through=asof)
    if len(weeks) < 8:
        return None
    this_season = [w for w in weeks if w["season"] == season]
    if len(this_season) < 3:
        return None

    values = [w["value"] for w in weeks]
    persist = _persistence(values)
    if persist is None:
        return None

    recent_start = asof - timedelta(days=days - 1)
    recent = [w for w in this_season if w["end"] >= recent_start.isoformat()]
    if not recent:
        return None
    r_games = sum(w["games"] for w in recent)
    now = sum(w["value"] * w["games"] for w in recent) / r_games

    base = history.season_to_date(key, season, asof)
    if not base:
        return None

    # The week that starts tomorrow, not the one after it. The persistence
    # slope is fitted on consecutive weeks, so it answers "given this week,
    # where does the next one land" — applying it two weeks out was using a
    # one-step relationship for a two-step question, and the extra step was
    # never paid for.
    start = asof + timedelta(days=1)
    end = asof + timedelta(days=7)
    cal_next = history.calendar_factor(key, start, end, exclude_season=season)
    cal_now = history.calendar_factor(key, recent_start, asof,
                                      exclude_season=season)

    # `applied` is the effect after it has been charged its own standard
    # error, which lands on exactly 1.0 for anything that cannot pay. Direction
    # agreement alone would be a one-in-four coin flip across three seasons,
    # and with eleven metrics on the page that manufactures two or three
    # effects a week.
    f_next = (cal_next or {}).get("applied", 1.0)
    f_now = (cal_now or {}).get("applied", 1.0)

    expected_next = base * f_next
    expected_now = base * f_now
    beta = persist["beta"]
    predicted = expected_next + beta * (now - expected_now)

    # The band is the spread the lag-1 fit actually leaves behind, which is the
    # right width by construction: it is how wrong this same rule was on every
    # previous week of the record.
    se_pred = persist["resid_sd"] or persist["total_sd"]
    if cal_next and cal_next["applies"]:
        se_pred = math.sqrt(se_pred ** 2 + (base * cal_next["se"]) ** 2)
    lo, hi = predicted - conf * se_pred, predicted + conf * se_pred

    games = sum(int(w["games"]) for w in weeks)
    confidence = ("high" if persist["n"] >= 40 and games >= 3000
                  else "medium" if persist["n"] >= 15 or games >= 1500
                  else "low")
    return {
        # The source is part of the identity. When a metric graduates from our
        # own record to seasons of league data, that is a different claim made
        # by a different method, not a restatement of the old one — so both are
        # issued, both get graded, and the scorecard can say which was better.
        "id": (f"{asof.isoformat()}:lg{METHOD}:league_history:week_ahead:"
               f"{key}"),
        "method": METHOD,
        "kind": "league", "source": "league_history",
        "metric": key, "label": spec["label"],
        "horizon": "week_ahead",
        "issued": asof.isoformat(),
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "predicted": round(predicted, 4), "lo": round(lo, 4), "hi": round(hi, 4),
        "null": round(expected_next, 4), "now": round(now, 4),
        "season_base": round(base, 4),
        "predicted_display": _fmt(spec, predicted),
        "range_display": f"{_fmt(spec, lo)} – {_fmt(spec, hi)}",
        "now_display": _fmt(spec, now), "baseline_display": _fmt(spec, base),
        "carry_pct": round(100 * beta),
        "calendar_pct": round(100 * (f_next - 1), 1),
        "calendar_seasons": (cal_next or {}).get("seasons") or [],
        "calendar_games": (cal_next or {}).get("games") or 0,
        "confidence": confidence,
        "n_basis": games, "n_weeks": len(weeks),
        "headline": _outlook_headline(spec, now, predicted, expected_next),
        "detail": _history_detail(spec, now, predicted, base, beta, f_next,
                                  cal_next, len(weeks), games),
        "graded": False,
    }


def _history_detail(spec: dict, now: float, pred: float, base: float,
                    beta: float, f_next: float, cal: Optional[dict],
                    n_weeks: int, games: int) -> str:
    bits = [f"Season sits at {_fmt(spec, base)} across {games:,} games."]
    if cal and cal["applies"] and abs(f_next - 1) >= 0.01:
        way = "above" if f_next > 1 else "below"
        yrs = len(cal["seasons"])
        bits.append(f"This stretch of the calendar has run "
                    f"{abs(f_next - 1) * 100:.0f}% {way} the season average in "
                    f"all {yrs} prior years, across "
                    f"{cal['games']:,} games.")
    carry = round(100 * beta)
    if carry <= 10:
        bits.append(f"Week-to-week, almost none of a swing carries "
                    f"(measured over {n_weeks} weeks).")
    else:
        bits.append(f"About {carry}% of a week's swing typically carries into "
                    f"the next.")
    return " ".join(bits)


def outlook(games: list[dict], *, asof: Optional[date] = None,
            days: int = 7, min_games: int = 25, conf: float = 1.28,
            history=None, season: Optional[int] = None) -> list[dict]:
    """Forecast next week's league level for each quantity, with a band.

    Uses seasons of real league data wherever they cover the metric. Where they
    do not — starter and bullpen workload, which no league-wide endpoint splits
    by role — it falls back to our own graded record and a variance-components
    shrinkage, which is weaker but is the honest ceiling on what that record can
    support.
    """
    asof = asof or date.today()
    season = season or asof.year
    ser = league_series(games)
    start = asof + timedelta(days=1)
    end = asof + timedelta(days=7)
    k = GAMES_PER_DAY * 7
    recent_start = asof - timedelta(days=days - 1)

    out: list[dict] = []
    for key in _ORDER:
        spec = _METRICS[key]
        deep = _history_outlook(key, spec, history, asof, days, season, conf)
        if deep is not None:
            out.append(deep)
            continue

        rows = ser.get(key) or []
        if len(rows) < min_games:
            continue
        recent = _window(rows, recent_start, asof) or rows
        if len(recent) < 10:
            continue
        all_vals = [r["actual"] for r in rows]
        r_vals = [r["actual"] for r in recent]
        base = _mean(all_vals)
        r_mean = _mean(r_vals)
        gap = r_mean - base

        var_all = _var(all_vals)
        if var_all <= 0:
            continue
        se2 = var_all / len(r_vals)                     # noise in this week
        tau2 = _signal_variance(rows)                   # real day-to-day move
        w = tau2 / (tau2 + se2) if (tau2 + se2) > 0 else 0.0
        predicted = base + w * gap
        # Posterior spread on the true level, plus next week's own sampling
        # error. Both are needed: knowing the level exactly would still leave
        # a week of baseball to be played.
        se_pred = math.sqrt(tau2 * (1 - w) + var_all / k)
        lo, hi = predicted - conf * se_pred, predicted + conf * se_pred

        out.append({
            "id": (f"{asof.isoformat()}:lg{METHOD}:graded_record:week_ahead:"
                   f"{key}"),
            "method": METHOD,
            "kind": "league", "source": "graded_record",
            "metric": key, "label": spec["label"],
            "horizon": "week_ahead",
            "issued": asof.isoformat(),
            "window_start": start.isoformat(), "window_end": end.isoformat(),
            "predicted": round(predicted, 4), "lo": round(lo, 4),
            "hi": round(hi, 4), "null": round(base, 4),
            "now": round(r_mean, 4),
            "predicted_display": _fmt(spec, predicted),
            "range_display": f"{_fmt(spec, lo)} – {_fmt(spec, hi)}",
            "now_display": _fmt(spec, r_mean),
            "baseline_display": _fmt(spec, base),
            "carry_pct": round(100 * w),
            # Our record is thin by comparison, and a card built on it should
            # not sit alongside one built on three seasons wearing the same
            # confidence.
            "confidence": "low",
            "n_basis": len(rows),
            "headline": _outlook_headline(spec, r_mean, predicted, base),
            "detail": _outlook_detail(spec, r_mean, predicted, base, w,
                                      len(recent), len(rows)),
            "graded": False,
        })
    out.sort(key=_outlook_order)
    return out


def _outlook_order(t: dict) -> tuple:
    """Biggest expected move first, as a share of the level.

    Ordering on distance from the season norm would put everything in a flat
    heap on a week when the shrinkage is strong — which is exactly the week
    when "this is about to come back down" is the thing worth reading first.
    """
    scale = abs(t["null"]) or 1.0
    move = abs(t["predicted"] - t.get("now", t["null"])) / scale
    return ({"high": 0, "medium": 1, "low": 2}.get(t["confidence"], 3), -move)


def _outlook_headline(spec: dict, now: float, pred: float,
                      base: float) -> str:
    """Lead with the change a reader would notice.

    The useful claim is almost always "this is about to move" — that scoring
    cools off, that bullpens get a break. Distance from the season norm is the
    fallback for when nothing is expected to move, because "roughly normal" is
    a real answer but a dull headline.
    """
    label, noun = spec["label"], spec["noun"]
    p, n = _fmt(spec, pred), _fmt(spec, now)
    scale = abs(base) or 1.0
    from_now = (pred - now) / scale
    from_base = (pred - base) / scale

    if abs(from_now) >= 0.03:
        # Shrinkage only ever pulls toward the norm, so the move is always a
        # retreat from where the week has been sitting.
        way = "ease back to" if from_now < 0 else "recover to"
        return f"{label} should {way} about {p} {noun}, from {n} lately"
    if abs(from_base) >= 0.02:
        state = "stay above normal" if from_base > 0 else "stay below normal"
        return f"{label} should {state}, around {p} {noun}"
    return f"{label} should hold near normal, about {p} {noun}"


def _outlook_detail(spec: dict, now: float, pred: float, base: float,
                    w: float, n_recent: int, n_all: int) -> str:
    now_s, base_s = _fmt(spec, now), _fmt(spec, base)
    if abs(now - base) < 1e-9:
        return (f"Level with its {n_all}-game norm of {base_s}, so there is "
                f"nothing to give back.")
    way = "above" if now > base else "below"
    carry = round(100 * w)
    if carry <= 10:
        why = "A swing this size is almost all sample noise."
    elif carry <= 40:
        why = f"About {carry}% of a swing this size holds; the rest washes out."
    else:
        why = f"This one really does move, so about {carry}% should hold."
    return (f"{n_recent} games at {now_s}, {way} the {n_all}-game norm of "
            f"{base_s}. {why}")


# ── grading ─────────────────────────────────────────────────────────────────

def grade_league(trend: dict, games: list[dict], *,
                 history=None) -> Optional[dict]:
    """Score one league forecast on the games inside its own window.

    Graded against the league where the history covers the metric, because the
    forecast was about the league — marking a claim about all of baseball on
    the subset of games we happened to grade would let sampling decide the
    result. Falls back to our record for the workload metrics the history
    cannot reach.

    Returns None when the window has not been played out far enough to judge,
    which leaves the forecast open rather than quietly scoring it as a miss.
    """
    metric = trend["metric"]
    a, b = trend["window_start"], trend["window_end"]
    spec = _METRICS.get(metric, {"digits": 2})
    actual = n = source = None

    if history is not None and history.covers(metric):
        weeks = [w for w in history.weekly(metric)
                 if w["start"] >= a and w["end"] <= b]
        played = sum(w["games"] for w in weeks)
        if played >= 60:
            actual = sum(w["value"] * w["games"] for w in weeks) / played
            n, source = int(round(played)), "league_history"

    if actual is None:
        rows = (league_series(games).get(metric) or [])
        vals = [r["actual"] for r in rows if a <= r["date"] <= b]
        if len(vals) < 25:
            return None
        actual, n, source = _mean(vals), len(vals), "graded_record"

    return {
        "actual": round(actual, 4),
        "actual_display": _fmt(spec, actual),
        "n_window": n,
        "graded_against": source,
        "hit": bool(trend["lo"] <= actual <= trend["hi"]),
        "direction_right": bool(
            (trend["predicted"] - trend["null"]) * (actual - trend["null"]) > 0
            or abs(trend["predicted"] - trend["null"]) < 1e-9),
    }
