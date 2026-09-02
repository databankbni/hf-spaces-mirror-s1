"""What the record says about the week coming — and when it says nothing.

This is the one part of the app that points forwards, which makes it the one
part most able to invent things. So it is built the other way round from a
tipster: it starts from measured error in the simulator's own past output,
keeps only what survives two tests, and says plainly when nothing does.

**The two tests.** A finding has to be *persistent* — visible over the whole
record, not just the last few nights — and *significant* — bigger than what a
sample that size produces by chance. One without the other is a story. A bias
that shows up only in the last five days is five days of noise; a bias inside
the standard error is not a bias at all. Both are checked, both are reported,
and a signal failing either is kept in the output as a failed signal rather
than quietly dropped, because "we looked and it wasn't there" is information.

**What it is allowed to say.** Only things that follow from the simulator's own
demonstrated error. "Our ranges run narrow, so results land outside them more
often than they should" is a statement about this model, measurable and
checkable. "The Yankees are due" is not, and nothing here can produce it —
there is no path in this module from a team name to a recommendation.

**What it is not.** Not a tip sheet and not a claim about what books will
price. It says where *our* numbers have been unreliable, which is where a
disagreement with a book is most likely to be our fault rather than an edge.
That is the useful direction: knowing where you're wrong beats guessing where
someone else is.
"""
from __future__ import annotations

import statistics as _stats
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Optional

# The middle 80% of a simulated distribution should contain the real result
# 80% of the time. Anything else is a statement about the model's spread rather
# than about baseball.
TARGET_COVERAGE_PCT = 80.0

# A model that rates most games between these is barely differentiating them.
# Worth measuring, because it decides whether a disagreement with a price is
# worth anything.
FLAT_LOW, FLAT_HIGH = 0.45, 0.55

# Below this a window is an anecdote. Fifteen games is one night, and one night
# moves ten points on a rate by itself.
MIN_FOR_SIGNAL = 30
MIN_FOR_WINDOW = 5

# How many standard errors a difference has to clear before it's reported as
# real. Two is the conventional bar and about right for a record this size.
SIGMA = 2.0

RECENT_DAYS = 5


def _se_rate(pct: Optional[float], n: int, fallback: float = 50.0) -> Optional[float]:
    """Standard error of a percentage, in points.

    A window where every game agreed gives p=0 or p=1, and the textbook error
    there is zero — which would make a perfect five games infinitely
    convincing. The wider record's rate sizes those instead.
    """
    if not n or pct is None:
        return None
    p = (fallback if pct <= 0 or pct >= 100 else pct) / 100.0
    return 100.0 * (max(p * (1.0 - p), 0.0) / n) ** 0.5


def _se_mean(values: list, n: int) -> Optional[float]:
    if not values or n < 2:
        return None
    try:
        return _stats.stdev(values) / (n ** 0.5)
    except _stats.StatisticsError:
        return None


def _outcome(game: dict) -> dict:
    return (game or {}).get("outcome") or {}


def measure(games: list) -> dict:
    """Everything one window of graded games has to say about itself."""
    total_err: list = []
    spread_err: list = []
    covered: list = []
    picked: list = []
    probs: list = []
    hits: list = []

    for g in games:
        o = _outcome(g)
        t = o.get("total") or {}
        if t.get("error") is not None:
            total_err.append(float(t["error"]))
        if t.get("covered") is not None:
            covered.append(1.0 if t["covered"] else 0.0)
        s = o.get("spread") or {}
        if s.get("error") is not None:
            spread_err.append(float(s["error"]))
        if o.get("picked_winner") is not None:
            picked.append(1.0 if o["picked_winner"] else 0.0)
        p = o.get("home_win_probability")
        if p is not None:
            probs.append(float(p))
            hits.append(1.0 if (g.get("actual") or {}).get("winner") == "home" else 0.0)

    def mean(v):
        return round(_stats.fmean(v), 3) if v else None

    def pct(v):
        return round(100.0 * _stats.fmean(v), 1) if v else None

    flat = ([1.0 if FLAT_LOW <= p < FLAT_HIGH else 0.0 for p in probs]
            if probs else [])
    return {
        "games": len(games),
        "winner_pct": pct(picked),
        "winner_n": len(picked),
        # Signed, not absolute. The average *miss* says how noisy we are; the
        # average *direction* of the miss is the only one that points at a bet.
        "total_bias": mean(total_err),
        "total_bias_se": (round(_se_mean(total_err, len(total_err)), 3)
                          if _se_mean(total_err, len(total_err)) else None),
        "total_mae": (round(_stats.fmean([abs(e) for e in total_err]), 3)
                      if total_err else None),
        "total_n": len(total_err),
        "spread_bias": mean(spread_err),
        "spread_n": len(spread_err),
        "coverage_pct": pct(covered),
        "coverage_n": len(covered),
        # How often the model has an opinion worth calling an opinion.
        "flat_pct": pct(flat),
        "flat_n": len(flat),
        "calibration_gap": (round(100.0 * (_stats.fmean(probs) - _stats.fmean(hits)), 1)
                            if probs else None),
    }


def _window(repo, start: date_type, end: date_type) -> dict:
    games = repo.get_accuracy_games(start, end)
    out = measure(games)
    out["start"], out["end"] = start.isoformat(), end.isoformat()
    out["days"] = len({g.get("date") for g in games if g.get("date")})
    return out


def _signal(key: str, headline: str, detail: str, *, lifetime, recent,
            expected: float, n: int, se: Optional[float],
            direction: str) -> dict:
    """One measured finding, with both tests applied and both reported."""
    gap = None if lifetime is None else lifetime - expected
    significant = bool(
        gap is not None and se and n >= MIN_FOR_SIGNAL and abs(gap) > SIGMA * se)
    # Persistent means the recent window leans the same way, not that it
    # matches. Demanding agreement to the decimal would reject everything.
    persistent = bool(
        gap is not None and recent is not None
        and (recent - expected) * gap > 0)
    return {
        "key": key, "headline": headline, "detail": detail,
        "lifetime": lifetime, "recent": recent, "expected": expected,
        "gap": None if gap is None else round(gap, 3),
        "n": n, "direction": direction,
        "significant": significant, "persistent": persistent,
        "usable": significant and persistent,
    }


def _signals(life: dict, recent: dict) -> list:
    out = []

    out.append(_signal(
        "coverage",
        "Our ranges run narrow" if (life["coverage_pct"] or 0) < TARGET_COVERAGE_PCT
        else "Our ranges run wide",
        "The p10–p90 band should contain the real total 80% of the time. "
        "Where it doesn't, the simulator is surer of itself than its record "
        "justifies, and any bet priced off the middle of that band inherits "
        "the error.",
        lifetime=life["coverage_pct"], recent=recent["coverage_pct"],
        expected=TARGET_COVERAGE_PCT, n=life["coverage_n"],
        se=_se_rate(life["coverage_pct"], life["coverage_n"],
                    fallback=TARGET_COVERAGE_PCT),
        direction="low" if (life["coverage_pct"] or 0) < TARGET_COVERAGE_PCT else "high",
    ))

    bias = life["total_bias"]
    out.append(_signal(
        "total_bias",
        "We project too few runs" if (bias or 0) > 0 else "We project too many runs",
        "The average signed miss on the game total. Positive means real games "
        "outscored the projection, which is the direction that points at overs; "
        "negative points the other way.",
        lifetime=bias, recent=recent["total_bias"], expected=0.0,
        n=life["total_n"], se=life["total_bias_se"],
        direction="over" if (bias or 0) > 0 else "under",
    ))

    out.append(_signal(
        "winners",
        "We beat the coin flip" if (life["winner_pct"] or 0) > 50
        else "We don't beat the coin flip",
        "Share of games whose winner we called. Against a 50% baseline, "
        "because picking the winner of a baseball game is close to that by "
        "nature — and a model at 50% has no moneyline opinion worth backing.",
        lifetime=life["winner_pct"], recent=recent["winner_pct"], expected=50.0,
        n=life["winner_n"], se=_se_rate(life["winner_pct"], life["winner_n"]),
        direction="up" if (life["winner_pct"] or 0) > 50 else "down",
    ))

    out.append(_signal(
        "flatness",
        "We rarely have a strong opinion",
        "Share of games the model prices between 45% and 55% — a near coin "
        "flip. A model that says the same thing about most of the slate can't "
        "be the reason to take one side of it.",
        lifetime=life["flat_pct"], recent=recent["flat_pct"], expected=50.0,
        n=life["flat_n"], se=_se_rate(life["flat_pct"], life["flat_n"]),
        direction="flat",
    ))
    return out


def _outlook(signals: list) -> list:
    """Forward-looking statements, each tied to a signal that earned it."""
    by_key = {s["key"]: s for s in signals}
    out: list = []

    cov = by_key.get("coverage")
    if cov and cov["usable"]:
        miss = round(100.0 - (cov["lifetime"] or 0), 1)
        if cov["direction"] == "low":
            out.append({
                "where": "Totals at the edges of our range, not the middle",
                "detail": (
                    f"Real totals land outside our p10–p90 band {miss}% of the "
                    f"time against the 20% it's built for. The distribution is "
                    f"too tight, so blowouts and pitchers' duels are both more "
                    f"likely than we're saying — and a total we call 'safe' is "
                    f"the one most likely to embarrass us."),
                "confidence": "firm",
            })
        else:
            out.append({
                "where": "Middle-of-the-range totals",
                "detail": (
                    f"Real totals stay inside our band {cov['lifetime']}% of the "
                    f"time against 80% expected — the spread is too generous, so "
                    f"our ranges are wider than the games actually are."),
                "confidence": "firm",
            })

    bias = by_key.get("total_bias")
    if bias and bias["usable"]:
        side = "overs" if bias["direction"] == "over" else "unders"
        out.append({
            "where": f"Leaning {side} where we're close to a book's number",
            "detail": (
                f"We've been out by {abs(bias['lifetime'] or 0):.2f} runs a game "
                f"in that direction across {bias['n']} games, and the last few "
                f"days lean the same way. Where our total sits near a posted "
                f"one, the miss has been landing on the {side[:-1]}."),
            "confidence": "firm",
        })

    win = by_key.get("winners")
    if win and not win["significant"]:
        out.append({
            "where": "Not the moneyline",
            "detail": (
                f"{win['lifetime']}% of winners called over {win['n']} games — "
                f"inside the noise of a coin flip. Whatever edge this app has, "
                f"the historical record doesn't show it in picking sides, and "
                f"backing one on our say-so isn't supported yet."),
            "confidence": "firm",
        })

    flat = by_key.get("flatness")
    if flat and (flat["lifetime"] or 0) > 60:
        out.append({
            "where": "The few games we actually separate",
            "detail": (
                f"We price {flat['lifetime']}% of games between 45% and 55%. "
                f"The handful outside that band are the only ones where the "
                f"model is saying something a price could disagree with — so "
                f"they're where a disagreement is worth a second look."),
            "confidence": "tentative",
        })
    return out


def _verdict(life: dict, usable: int) -> str:
    if life["games"] < MIN_FOR_SIGNAL:
        return (f"Too little history to forecast from — {life['games']} graded "
                f"games. This fills in as more of the season is scored.")
    if not usable:
        return (f"Nothing in {life['games']} graded games clears the noise, so "
                f"there's no honest read on the week ahead. That's a finding "
                f"too: the model has no demonstrated bias to exploit.")
    return (f"From {life['games']} graded games: the record points at where our "
            f"own numbers have been unreliable, which is where a disagreement "
            f"with a price is most likely ours rather than theirs.")


def _caveats(life: dict, latest: dict, today: date_type) -> list:
    out = []
    if life["games"] < 200:
        out.append(f"Built on {life['games']} graded games over {life['days']} "
                   f"days. Small, and everything here should firm up or fall "
                   f"apart as that grows.")
    if latest["games"] and latest["games"] < 5:
        out.append(f"The most recent graded day has {latest['games']} game(s) "
                   f"on it, which is too few to compare against anything — "
                   f"it's shown for completeness, not as a trend.")
    try:
        last = datetime.strptime(life["end"], "%Y-%m-%d").date()
        stale = (today - last).days
        if stale > 2:
            out.append(f"The record ends {life['end']}, {stale} days ago. "
                       f"Anything since is ungraded and not in these numbers.")
    except (ValueError, TypeError):
        pass
    out.append("This describes our own errors, not the books'. It says where "
               "to distrust our numbers — it can't tell you a price is wrong.")
    return out


def build(repo, *, end: Optional[date_type] = None,
          recent_days: int = RECENT_DAYS) -> dict:
    """The whole outlook: three windows, the signals, and what follows."""
    today = datetime.now(timezone.utc).date()
    end = end or (today - timedelta(days=1))

    life_start = repo.earliest_accuracy_date() or end
    life = _window(repo, life_start, end)

    latest_day = repo.latest_accuracy_date() or end
    latest = _window(repo, latest_day, latest_day)
    recent = _window(repo, latest_day - timedelta(days=recent_days - 1), latest_day)

    signals = _signals(life, recent) if life["games"] >= MIN_FOR_WINDOW else []
    usable = [s for s in signals if s["usable"]]
    outlook = _outlook(signals) if signals else []

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "windows": {"latest": latest, "recent": recent, "lifetime": life},
        "signals": signals,
        "outlook": outlook,
        "verdict": _verdict(life, len(usable)),
        "caveats": _caveats(life, latest, today),
        "method": ("Every line here comes from the simulator's own graded "
                   "results. A finding is only used if it holds across the "
                   "whole record *and* is larger than the noise of a sample "
                   "that size; the ones that failed are listed too, because "
                   "having looked and found nothing is worth knowing."),
    }
