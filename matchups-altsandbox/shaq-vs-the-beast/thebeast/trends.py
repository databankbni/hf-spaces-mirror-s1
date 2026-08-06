"""The forecast record: what was claimed, when, and whether it came true.

Two kinds of forecast share this file because they share the thing that makes
either of them worth anything — a written record with a window on it.

`kind: "league"` forecasts come from `baseball.py` and are about the sport:
where scoring, home runs or starter workload should land next week. They are
what the homepage shows.

`kind: "model"` forecasts are the ones below, about the simulation's own
errors, built from the drift monitor. They are the engineering view and stay
off the front page, but they are graded on the same terms.

The recording is the part that makes it honest. A forecast that is not written
down before the fact can always be remembered as having been right, so each one
is committed with its window and its interval, and graded later against the
games that actually fell in that window — hit or miss, no re-interpretation.

The model forecasts below use two horizons:

**This week** is persistence. A bias that is established — clear of sampling
error and pointing the same way in both halves of the record — is expected to
still be there in seven days. These are the confident ones, and if they are
wrong the model has changed underneath us.

**Next week** is emergence. Either a bias that is drifting and projected to
become material, or one the record cannot yet settle but will have the games
to settle by then, or a divergence between the rates fed into the simulation
and the rates being played — that last one moves before any graded error does,
so it is the only genuinely forward-looking input rather than an extrapolation.

Intervals are prediction intervals, not confidence intervals: the spread of a
*future* sample of k games around the current estimate, which is wider than the
error on the estimate itself and is the thing a forecast should be graded on.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .drift import _mean, _sd, build_drift_report, leading_indicators, series

# One line per issued forecast, committed like the graded record and for the
# same reason: the container this runs in is rebuilt from its image on every
# deploy, so anything written at runtime is gone by the next push.
TRENDS_PATH = "data/accuracy/trends.jsonl"

# Roughly a full MLB slate a day. Used to size prediction intervals and to
# judge whether an under-powered metric will have the games to settle itself.
GAMES_PER_DAY = 15

# How each metric reads in a sentence, and which direction is which. `unit`
# says whether the effect is naturally a ratio or an absolute amount.
_LABELS: dict[str, dict[str, str]] = {
    "bat_pa":               {"what": "plate appearances", "unit": "ratio"},
    "bat_bb_rate":          {"what": "batter walks", "unit": "ratio"},
    "bat_k_rate":           {"what": "batter strikeouts", "unit": "ratio"},
    "bat_hits_rate":        {"what": "batter hits", "unit": "ratio"},
    "bat_home_runs_rate":   {"what": "home runs", "unit": "ratio"},
    "bat_rbi_rate":         {"what": "RBI", "unit": "ratio"},
    "pit_outs":             {"what": "outs recorded", "unit": "ratio"},
    "pit_pitches_rate":     {"what": "pitch counts", "unit": "ratio"},
    "pit_bb_allowed_rate":  {"what": "walks allowed", "unit": "ratio"},
    "pit_k_rate":           {"what": "pitcher strikeouts", "unit": "ratio"},
    "pit_hits_allowed_rate": {"what": "hits allowed", "unit": "ratio"},
    "pit_runs_allowed_rate": {"what": "earned runs", "unit": "ratio"},
    "total_runs":           {"what": "game totals", "unit": "runs"},
    "margin":               {"what": "the margin", "unit": "runs"},
    "total_coverage":       {"what": "totals inside the projected range",
                             "unit": "share"},
    "home_win_prob":        {"what": "home win probability", "unit": "share"},
}


def _headline(metric: str, mean: float, ratio: Optional[float],
              null: float) -> str:
    lab = _LABELS.get(metric, {"what": metric, "unit": "ratio"})
    what, unit = lab["what"], lab["unit"]
    if unit == "ratio" and ratio is not None:
        pct = abs(ratio - 1) * 100
        way = "over" if ratio > 1 else "under"
        return f"{what.capitalize()} {way}-projected by about {pct:.0f}%"
    if unit == "runs":
        way = "under" if mean > 0 else "over"
        return (f"{what.capitalize()} {way}-projected by about "
                f"{abs(mean):.2f} runs a game")
    if metric == "total_coverage":
        return (f"Only about {100 * mean:.0f}% of totals will land inside the "
                f"projected range, against a {100 * null:.0f}% target")
    if metric == "home_win_prob":
        way = "less" if mean < 0 else "more"
        return (f"Home teams will win about {abs(mean) * 100:.0f} points "
                f"{way} often than the model calls")
    return f"{what.capitalize()} off by about {abs(mean):.3f}"


def _prediction_interval(values: list[float], k: int,
                         conf: float = 1.28) -> tuple[float, float, float]:
    """Where the mean of the next `k` games should land.

    Wider than the interval on the current estimate: a future sample carries
    its own sampling error as well as the uncertainty in what it is sampling
    around. Default is 80% (z = 1.28), which is a band worth grading — a 95%
    band is so wide almost nothing would ever miss it, and a forecast that
    cannot be wrong is not a forecast.
    """
    n = len(values)
    m, sd = _mean(values), _sd(values)
    if n < 2 or sd <= 0 or k < 1:
        return m, m, m
    se = sd * math.sqrt(1.0 / k + 1.0 / n)
    return m, m - conf * se, m + conf * se


def _confidence(verdict: str, z: float, n: int) -> str:
    if verdict == "act" and abs(z) >= 3 and n >= 60:
        return "high"
    if verdict in ("act", "drifting"):
        return "medium"
    return "low"


def forecast(games: list[dict], repo=None, *, season: int = 2026,
             asof: Optional[date] = None) -> list[dict]:
    """Statements about the week ahead and the week after, from the record."""
    asof = asof or date.today()
    drift = build_drift_report(games)
    ser, _scale = series(games)
    by_metric = {m["metric"]: m for m in drift["metrics"]}

    this_start, this_end = asof, asof + timedelta(days=6)
    next_start, next_end = asof + timedelta(days=7), asof + timedelta(days=13)
    k_week = GAMES_PER_DAY * 7

    # Keyed by id, because more than one route can reach the same claim — a
    # metric can be both unsettled in the record and diverging in the rates
    # feeding it. That is one forecast with two reasons, not two forecasts, and
    # the better-founded reason is the one worth stating.
    issued: dict[str, dict] = {}
    _rank = {"high": 0, "medium": 1, "low": 2}

    def issue(m: dict, horizon: str, start: date, end: date,
              basis: str, confidence: str) -> None:
        vals = ser.get(m["metric"]) or []
        if len(vals) < 10:
            return
        key = f"{asof.isoformat()}:{m['metric']}:{horizon}"
        prior = issued.get(key)
        if prior is not None and _rank[prior["confidence"]] <= _rank[confidence]:
            return
        centre, lo, hi = _prediction_interval(vals, k_week)
        issued[key] = {
            "id": key,
            "kind": "model",
            "issued": asof.isoformat(),
            "horizon": horizon,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "metric": m["metric"],
            "headline": _headline(m["metric"], m["mean"], m.get("ratio"),
                                  m.get("null", 0.0)),
            "predicted": round(centre, 4),
            "lo": round(lo, 4), "hi": round(hi, 4),
            "null": m.get("null", 0.0),
            "ratio": m.get("ratio"),
            "z": m["z"], "n_basis": m["n"],
            "confidence": confidence,
            "basis": basis,
            "graded": False,
        }

    # ── this week: what is already established should still be there ──
    for m in drift["metrics"]:
        if m["verdict"] not in ("act", "drifting"):
            continue
        issue(m, "this_week", this_start, this_end,
              basis=(f"established over {m['n']} games "
                     f"(z {m['z']:+.1f}, same direction in both halves)"),
              confidence=_confidence(m["verdict"], m.get("z", 0), m["n"]))

    # ── next week: what is emerging ──
    for m in drift["metrics"]:
        metric = m["metric"]
        if m["verdict"] == "drifting" and m.get("projected_in_100_games") is not None:
            issue(m, "next_week", next_start, next_end,
                  basis=(f"drifting {m['trend_per_100']:+.3f} per 100 games "
                         f"(trend z {m['trend_z']:+.1f})"),
                  confidence="medium")
        elif m["verdict"] == "watch" and m.get("more_games_needed") is not None:
            # Only worth promising if the games to settle it will exist.
            if m["more_games_needed"] <= k_week * 2:
                issue(m, "next_week", next_start, next_end,
                      basis=(f"unsettled at {m['n']} games; about "
                             f"{m['more_games_needed']} more would decide it, "
                             f"which the next two weeks supply"),
                      confidence="low")

    # ── next week: the rates going in, which move before the errors do ──
    if repo is not None:
        li = leading_indicators(repo, games, season)
        for row in li.get("rates", []) if li.get("available") else []:
            if abs(row["ratio"] - 1) < 0.05 or abs(row["z"]) < 2:
                continue
            metric = {"bb": "bat_bb_rate", "home_runs": "bat_home_runs_rate",
                      "k": "bat_k_rate"}.get(row["stat"])
            if metric is None:
                continue
            m = by_metric.get(metric)
            if m is None:
                continue
            # Skip if this week already carries the same claim.
            if any(t["metric"] == metric and t["horizon"] == "this_week"
                   for t in issued.values()):
                continue
            issue(m, "next_week", next_start, next_end,
                  basis=(f"the statlines feeding the simulation put this at "
                         f"{row['statline_rate']:.4f} per PA against "
                         f"{row['realised_rate']:.4f} actually being played "
                         f"(z {row['z']:+.1f}), so the gap reaches the "
                         f"projections before it reaches a graded report"),
                  confidence="medium")

    out = sorted(issued.values(),
                 key=lambda t: (t["horizon"] != "this_week",
                                _rank.get(t["confidence"], 3),
                                -abs(t.get("z") or 0)))
    return out


# ── grading the forecasts ───────────────────────────────────────────────────

def grade(trends: list[dict], games: list[dict], *,
          history=None) -> list[dict]:
    """Score every forecast whose window has games in it.

    A forecast is graded on the games that fell inside its own window, never
    on the record that produced it — otherwise it would be marking its own
    homework.
    """
    from .baseball import grade_league

    graded = []
    for t in trends:
        if t.get("graded"):
            graded.append(t)
            continue
        # League forecasts are about what baseball does; model forecasts are
        # about where the simulation is wrong. Same record, same window rule,
        # different quantity to measure.
        if t.get("kind") == "league":
            scored = grade_league(t, games, history=history)
            if scored is None:
                graded.append(t)
                continue
            row = dict(t)
            row.update(scored)
            row["graded"] = True
            row["graded_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds")
            graded.append(row)
            continue
        window = [g for g in games
                  if t["window_start"] <= g.get("date", "") <= t["window_end"]]
        ser, _ = series(window)
        vals = ser.get(t["metric"]) or []
        if len(vals) < 10:
            graded.append(t)          # not enough played yet; leave it open
            continue
        actual = _mean(vals)
        row = dict(t)
        row.update({
            "graded": True,
            "actual": round(actual, 4),
            "n_window": len(vals),
            "hit": bool(t["lo"] <= actual <= t["hi"]),
            # Did it at least call the direction? A forecast can miss the
            # interval and still have been useful about which way to lean.
            "direction_right": bool(
                (t["predicted"] - t.get("null", 0.0)) *
                (actual - t.get("null", 0.0)) > 0),
            "graded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        graded.append(row)
    return graded


def scorecard(trends: list[dict]) -> dict:
    """How good the forecasts have been, split by horizon and confidence."""
    done = [t for t in trends if t.get("graded")]
    def block(rows):
        if not rows:
            return {"n": 0}
        return {
            "n": len(rows),
            "hit_rate": round(sum(1 for r in rows if r["hit"]) / len(rows), 3),
            "direction_rate": round(
                sum(1 for r in rows if r.get("direction_right")) / len(rows), 3),
        }
    return {
        "issued": len(trends),
        "graded": len(done),
        "open": len(trends) - len(done),
        "overall": block(done),
        # Horizons come from the record rather than a fixed list, so a change
        # of horizon shows up as a new row instead of silently vanishing from
        # the scorecard along with everything ever claimed under it.
        "by_horizon": {h: block([t for t in done if t.get("horizon") == h])
                       for h in sorted({t.get("horizon") for t in trends
                                        if t.get("horizon")})},
        "by_confidence": {c: block([t for t in done if t["confidence"] == c])
                          for c in ("high", "medium", "low")},
        # Forecasts about baseball and forecasts about the model are different
        # skills, and one being good is no excuse for the other.
        "by_kind": {k: block([t for t in done
                              if (t.get("kind") or "model") == k])
                    for k in ("league", "model")},
        # Which forecasting rule produced each graded call, so a change to the
        # method can be judged rather than assumed to be an improvement.
        "by_method": {str(m): block([t for t in done
                                     if t.get("method", 1) == m])
                      for m in sorted({t.get("method", 1) for t in done})},
        # The interval is an 80% band, so a hit rate near .80 means the
        # forecasts are as uncertain as they claim. Well above means they are
        # too timid; well below means overconfident.
        "target_hit_rate": 0.80,
    }


# ── the durable record ──────────────────────────────────────────────────────

def _path(root: Optional[str] = None) -> Path:
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    return base / TRENDS_PATH


def load(path=None, *, root: Optional[str] = None) -> list[dict]:
    p = Path(path) if path else _path(root)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue          # a broken line costs one forecast, not the file
    return out


def save(trends: list[dict], path=None, *, root: Optional[str] = None) -> int:
    p = Path(path) if path else _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(trends, key=lambda t: (t.get("issued", ""), t.get("id", "")))
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
    return len(rows)


# How often a fresh set of forecasts is issued, regardless of how often the
# job runs. Grading moved to nightly, and issuing on the same cadence would
# have been a quiet change to what the scorecard means: every forecast covers
# the following seven days, so daily issues overlap six days out of seven. A
# hundred near-identical calls would read as a hundred independent ones, and
# "right 82% of 200 graded" would claim a sample five times the size of the one
# actually behind it.
ISSUE_EVERY_DAYS = 5


def _last_issued(rows: list[dict]) -> Optional[date]:
    stamps = []
    for r in rows:
        try:
            stamps.append(date.fromisoformat(r["issued"]))
        except (KeyError, TypeError, ValueError):
            continue
    return max(stamps) if stamps else None


def refresh(games: list[dict], repo=None, *, season: int = 2026,
            asof: Optional[date] = None, path=None, history=None) -> dict:
    """Grade what is due, issue what is new, and keep the record.

    Grading happens every run — a window that has played out should be marked
    the moment it has. Issuing is rationed to `ISSUE_EVERY_DAYS`, so the record
    stays a log of distinct claims rather than the same call restated nightly.
    """
    from .baseball import outlook
    from .league_history import load as load_history

    asof = asof or date.today()
    history = history if history is not None else load_history()
    existing = load(path)
    existing = grade(existing, games, history=history)

    last = _last_issued(existing)
    due = last is None or (asof - last).days >= ISSUE_EVERY_DAYS
    if due:
        have = {t["id"] for t in existing}
        proposed = (outlook(games, asof=asof, history=history, season=season)
                    + forecast(games, repo, season=season, asof=asof))
        fresh = [t for t in proposed if t["id"] not in have]
    else:
        fresh = []

    combined = existing + fresh
    save(combined, path)
    return {"issued_now": len(fresh), "total": len(combined),
            "next_issue_due": None if last is None else
            (last + timedelta(days=ISSUE_EVERY_DAYS)).isoformat(),
            "league_issued": sum(1 for t in fresh if t.get("kind") == "league"),
            "scorecard": scorecard(combined)}


def report(games: list[dict], *, asof: Optional[date] = None,
           path=None, history=None, season: Optional[int] = None) -> dict:
    """What the homepage shows: recent baseball, next week, and the record.

    This week is computed live because it is description — the games have been
    played and there is nothing to be honest about beyond reading them
    correctly. Next week comes out of the committed record instead, so the page
    shows the forecast as it was issued rather than one quietly recomputed to
    look better.
    """
    from .baseball import _outlook_order, outlook, recent_trends
    from .league_history import load as load_history

    asof = asof or date.today()
    season = season or asof.year
    history = history if history is not None else load_history()
    issued = load(path)
    league = [t for t in issued if t.get("kind") == "league"]
    # Only the week-ahead horizon reaches the page. Forecasts made under an
    # older, further-out horizon stay in the record and still get graded — they
    # were real claims — they just are not what this column is now answering.
    open_next = [t for t in league
                 if not t.get("graded")
                 and t.get("horizon") == "week_ahead"
                 and t["window_end"] >= asof.isoformat()]
    if not open_next:
        # An empty record should not leave the page blank; label it so the
        # difference between "issued" and "computed just now" stays visible.
        open_next = [dict(t, provisional=True)
                     for t in outlook(games, asof=asof, history=history,
                                      season=season)]
    # One card per metric. Seasons of league data beat our own graded games
    # whatever the dates say, and a later issue beats an earlier one — but the
    # forecast that loses this contest still stays in the record and still gets
    # graded, so preferring the deeper one here can never quietly bury a claim.
    _depth = {"league_history": 1, "graded_record": 0}
    latest: dict[str, dict] = {}
    for t in sorted(open_next, key=lambda t: (t.get("method", 1),
                                              _depth.get(t.get("source"), 0),
                                              t.get("issued", ""))):
        latest[t["metric"]] = t

    return {
        "this_week": recent_trends(games, asof=asof, history=history,
                                   season=season),
        "history": {
            "seasons": history.seasons if history else [],
            "games": history.game_count if history else 0,
        },
        "next_week": sorted(latest.values(), key=_outlook_order),
        "recent_graded": sorted(
            [t for t in league if t.get("graded")],
            key=lambda t: t.get("window_end", ""), reverse=True)[:12],
        "scorecard": scorecard(issued),
        "model_watch": [t for t in issued
                        if (t.get("kind") or "model") == "model"
                        and not t.get("graded")],
    }
