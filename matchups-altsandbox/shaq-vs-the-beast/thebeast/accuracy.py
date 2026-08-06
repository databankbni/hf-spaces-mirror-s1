"""Scoring the simulation against what actually happened.

Every finished game can be graded: the model projected a score, a win
probability and a full box score, and reality then supplied all three. This
module turns that comparison into numbers — per player, per position, per
stat, per game — and rolls them up over a date window.

Three things are worth knowing about how it works:

**The unconditioned projection is what gets graded.** There is a second,
conditioned simulation in the API that keeps only the runs which ended at the
real final score; that one answers "given it got the score right, how right
was the box score", which is a diagnostic, not a forecast. Grading a forecast
means grading what it said beforehand, so only the base run is used here.

**A game is scored once and stored.** Scoring means re-simulating and fetching
a box score, which is far too slow for a page load. `score_and_store` writes
one row per game and the report is an aggregation over those rows.

**Relief is graded in aggregate, not per arm.** The simulator's bullpen is
usually a single synthetic pitcher standing in for the whole pen, so matching
it against individual real relievers would be scoring it for a claim it never
made. Starters are graded individually; everything behind them is compared as
one line against the sum of what the real bullpen did.

A caveat that belongs in the report rather than buried here: a game re-scored
today is simulated from season statlines that already contain that game. The
contribution of one game to a season line is small, but it is not zero and it
flatters the model. `pregame` is true only for rows scored from a projection
captured before first pitch.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Optional

# Batter stats the real box score carries, mapped onto our projected line's
# field names. Doubles/triples/total bases are deliberately absent: MLB's
# boxscore payload doesn't break them out, so there is nothing to grade against.
BATTER_STATS: tuple[str, ...] = ("pa", "ab", "hits", "home_runs", "rbi", "bb", "k")
_BOX_BATTER: dict[str, str] = {
    "pa": "plate_appearances", "ab": "at_bats", "hits": "hits",
    "home_runs": "home_runs", "rbi": "rbi", "bb": "walks", "k": "strikeouts",
}

# Pitcher stats, same idea. `runs_allowed` is graded against earned runs: the
# simulator has no fielding errors, so every run it charges is earned.
PITCHER_STATS: tuple[str, ...] = (
    "outs", "hits_allowed", "runs_allowed", "bb_allowed", "k", "pitches")
_BOX_PITCHER: dict[str, str] = {
    "hits_allowed": "hits_allowed", "runs_allowed": "earned_runs",
    "bb_allowed": "walks_allowed", "k": "strikeouts", "pitches": "pitches",
}

# Fielding positions, in the order a box score lists them, so the report reads
# like a lineup card rather than an alphabetical jumble.
POSITION_ORDER: tuple[str, ...] = (
    "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "PH", "PR", "SP", "RP")


def ip_to_outs(ip: Any) -> Optional[int]:
    """MLB's innings-pitched string to outs. "6.2" is six innings and 2 outs."""
    if ip is None:
        return None
    try:
        whole, _, frac = str(ip).partition(".")
        return int(whole or 0) * 3 + int(frac or 0)
    except (ValueError, TypeError):
        return None


def _norm_position(raw: Any) -> Optional[str]:
    if not raw:
        return None
    p = str(raw).strip().upper()
    return p if p in POSITION_ORDER else (p or None)


# ── Per-player comparison ────────────────────────────────────────────────────

def _stat_row(proj: Optional[dict], actual: Optional[dict],
              stats: tuple[str, ...], box_map: dict[str, str],
              outs_from_ip: bool = False) -> dict:
    """{stat: {projected, actual, error}} for one player.

    `error` is actual - projected, so a positive number means the model was
    low. Kept signed because the direction is the interesting part: a model
    that misses by one hit in both directions is unbiased, and one that is
    always short by half a hit is not.
    """
    out: dict[str, dict] = {}
    for stat in stats:
        p = None if proj is None else proj.get(stat)
        a = None
        if actual is not None:
            if outs_from_ip and stat == "outs":
                a = ip_to_outs(actual.get("innings_pitched"))
            else:
                key = box_map.get(stat)
                a = actual.get(key) if key else None
        if p is None and a is None:
            continue
        row: dict[str, Any] = {
            "projected": round(float(p), 3) if p is not None else None,
            "actual": int(a) if a is not None else None,
        }
        if p is not None and a is not None:
            row["error"] = round(float(a) - float(p), 3)
        out[stat] = row
    return out


def _brier(p: float, hit: bool) -> float:
    return (p - (1.0 if hit else 0.0)) ** 2


def _log_loss(p: float, hit: bool) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -(math.log(p) if hit else math.log(1 - p))


def _dist_metrics(actual: float, arr) -> dict:
    """Where reality landed inside the simulated distribution.

    `centrality_pct` is 100 when the actual sat on the model's median and 0 at
    either tail — a readable "did the forecast centre on what happened".
    `covered` is whether it fell inside the middle 80%, which is the honest
    test of an interval rather than of a point estimate.
    """
    import numpy as np

    arr = np.asarray(arr)
    if arr.size == 0:
        return {}
    below = float(np.mean(arr < actual))
    equal = float(np.mean(arr == actual))
    pct = (below + equal / 2) * 100
    p10, p90 = float(np.percentile(arr, 10)), float(np.percentile(arr, 90))
    return {
        "actual": float(actual),
        "mean": round(float(arr.mean()), 3),
        "percentile": round(pct, 1),
        "centrality_pct": round(100 * (1 - 2 * abs(pct / 100 - 0.5)), 1),
        "exact_pct": round(equal * 100, 2),
        "p10": p10, "p90": p90,
        "covered": bool(p10 <= actual <= p90),
        "error": round(float(actual) - float(arr.mean()), 3),
    }


def score_game(
    *,
    game_id: str,
    game_date: date,
    home: str,
    away: str,
    result,
    raw,
    home_lineup,
    away_lineup,
    actual: dict,
    names: Optional[dict[int, str]] = None,
    pregame: bool = False,
) -> dict:
    """Grade one finished game. Pure — every input is already fetched.

    `actual` is {home_runs, away_runs, status, boxscore}; the box score may be
    None, in which case the run and winner comparisons still work and the
    player section is simply empty.
    """
    import numpy as np

    names = names or {}
    a_home, a_away = int(actual["home_runs"]), int(actual["away_runs"])
    a_total, a_spread = a_home + a_away, a_home - a_away
    actual_winner = ("home" if a_home > a_away else
                     "away" if a_away > a_home else "tie")
    p_home = float(result.home_win_probability)
    predicted_winner = "home" if p_home >= 0.5 else "away"
    winner_prob = p_home if actual_winner == "home" else 1.0 - p_home

    spread_arr = raw.home_runs.astype(np.int64) - raw.away_runs.astype(np.int64)
    outcome = {
        "home_win_probability": round(p_home, 4),
        "predicted_winner": predicted_winner,
        "actual_winner": actual_winner,
        # A tie is not a miss and not a hit — it is excluded from the rate.
        "picked_winner": (None if actual_winner == "tie"
                          else predicted_winner == actual_winner),
        "winner_prob": round(winner_prob, 4),
        "brier": round(_brier(p_home, actual_winner == "home"), 4),
        "log_loss": round(_log_loss(p_home, actual_winner == "home"), 4),
        "home_runs": _dist_metrics(a_home, raw.home_runs),
        "away_runs": _dist_metrics(a_away, raw.away_runs),
        "total": _dist_metrics(a_total, raw.totals),
        "spread": _dist_metrics(a_spread, spread_arr),
        "exact_score_pct": round(100 * float(np.mean(
            (raw.home_runs == a_home) & (raw.away_runs == a_away))), 2),
    }

    box = actual.get("boxscore")
    batters = _score_batters(result, box, home, away, home_lineup, away_lineup, names)
    pitchers = _score_pitchers(result, box, home, away, home_lineup, away_lineup, names)

    return {
        "game_id": game_id,
        "date": game_date.isoformat(),
        "home": home, "away": away,
        "n": int(getattr(result, "n", 0) or 0),
        "pregame": bool(pregame),
        "actual": {"home_runs": a_home, "away_runs": a_away,
                   "total": a_total, "spread": a_spread,
                   "winner": actual_winner, "status": actual.get("status")},
        "outcome": outcome,
        "batters": batters,
        "pitchers": pitchers,
        "has_boxscore": box is not None,
        "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _slot_map(home_lineup, away_lineup) -> dict[int, int]:
    return {pid: i + 1
            for lu in (home_lineup, away_lineup)
            for i, pid in enumerate(lu.batting_order)}


def _score_batters(result, box, home: str, away: str,
                   home_lineup, away_lineup, names) -> list[dict]:
    """One row per hitter, whether the model projected him, reality used him,
    or both.

    Players on only one side of that are the interesting failures — a projected
    starter who was scratched, or a pinch-hitter the model never saw — so they
    are kept and flagged rather than dropped, which would quietly grade the
    model only on the players it happened to get right.
    """
    import dataclasses

    slots = _slot_map(home_lineup, away_lineup)
    proj_by = {(pl["team"], int(pl["player_id"])): pl
               for pl in getattr(result, "player_lines", [])}
    act_by: dict[tuple[str, int], dict] = {}
    positions: dict[tuple[str, int], Optional[str]] = {}
    real_names: dict[tuple[str, int], str] = {}
    if box is not None:
        for side, team in (("home", home), ("away", away)):
            for b in getattr(box, side).batters:
                if b.player_id is None:
                    continue
                key = (team, int(b.player_id))
                act_by[key] = dataclasses.asdict(b)
                positions[key] = _norm_position(b.position)
                if b.name:
                    real_names[key] = b.name

    rows = []
    for key in sorted(set(proj_by) | set(act_by), key=lambda k: (k[0], k[1])):
        team, pid = key
        proj, act = proj_by.get(key), act_by.get(key)
        stats = _stat_row(proj, act, BATTER_STATS, _BOX_BATTER)
        if not stats:
            continue
        rows.append({
            "player_id": pid,
            "name": real_names.get(key) or names.get(pid) or str(pid),
            "team": team,
            "side": "batter",
            "position": positions.get(key),
            "lineup_slot": slots.get(pid),
            "projected": proj is not None,
            "played": act is not None,
            "stats": stats,
        })
    rows.sort(key=lambda r: (r["team"], r["lineup_slot"] is None,
                             r["lineup_slot"] or 99, r["name"]))
    return rows


def _score_pitchers(result, box, home: str, away: str,
                    home_lineup, away_lineup, names) -> list[dict]:
    """Starters individually; everything behind them as one aggregate line.

    The simulator usually represents a bullpen as a single synthetic pitcher
    with a negative id. Grading that against named relievers would be scoring
    a claim the model never made, so the pen is summed on both sides and
    compared as one row per team.
    """
    import dataclasses

    starters = {home: home_lineup.starter_id, away: away_lineup.starter_id}
    proj_by = {(pl["team"], int(pl["player_id"])): pl
               for pl in getattr(result, "pitcher_lines", [])}

    act_by: dict[tuple[str, int], dict] = {}
    act_starter: dict[str, Optional[int]] = {home: None, away: None}
    real_names: dict[tuple[str, int], str] = {}
    if box is not None:
        for side, team in (("home", home), ("away", away)):
            pitchers = getattr(box, side).pitchers
            for i, p in enumerate(pitchers):
                if p.player_id is None:
                    continue
                key = (team, int(p.player_id))
                act_by[key] = dataclasses.asdict(p)
                if i == 0:                     # MLB lists pitchers in order used
                    act_starter[team] = int(p.player_id)
                if p.name:
                    real_names[key] = p.name

    rows: list[dict] = []
    for team in (away, home):
        # ── the start ──
        proj_sid = starters.get(team)
        act_sid = act_starter.get(team)
        proj = proj_by.get((team, proj_sid))
        act = act_by.get((team, act_sid)) if act_sid is not None else None
        # Only grade the start as one player's when both sides agree who it
        # was; a late change makes the projection a forecast of a different
        # pitcher and comparing them would be meaningless.
        same = proj_sid is not None and act_sid is not None and proj_sid == act_sid
        stats = _stat_row(proj, act if same else None, PITCHER_STATS,
                          _BOX_PITCHER, outs_from_ip=True)
        if stats:
            pid = proj_sid if proj_sid is not None else act_sid
            rows.append({
                "player_id": int(pid) if pid is not None else 0,
                "name": (real_names.get((team, act_sid)) if act_sid else None)
                        or names.get(proj_sid) or str(proj_sid),
                "team": team, "side": "pitcher", "position": "SP",
                "role": "SP", "lineup_slot": None,
                "projected": proj is not None,
                "played": act is not None,
                "starter_changed": bool(
                    proj_sid and act_sid and proj_sid != act_sid),
                "stats": stats,
            })

        # ── the pen, summed on both sides ──
        pen_proj = [pl for (t, pid), pl in proj_by.items()
                    if t == team and pid != proj_sid]
        pen_act = [a for (t, pid), a in act_by.items()
                   if t == team and pid != act_sid]
        if not pen_proj and not pen_act:
            continue
        summed_proj = {s: sum(float(pl.get(s, 0) or 0) for pl in pen_proj)
                       for s in PITCHER_STATS} if pen_proj else None
        summed_act = None
        if pen_act:
            summed_act = {k: sum(int(a.get(k) or 0) for a in pen_act)
                          for k in ("hits_allowed", "earned_runs",
                                    "walks_allowed", "strikeouts", "pitches")}
            summed_act["innings_pitched"] = None
            outs = sum(ip_to_outs(a.get("innings_pitched")) or 0 for a in pen_act)
            summed_act["_outs"] = outs
        stats = _stat_row(summed_proj, summed_act, PITCHER_STATS, _BOX_PITCHER)
        if summed_act is not None and "outs" in (summed_proj or {}):
            stats.setdefault("outs", {})
            stats["outs"]["actual"] = summed_act["_outs"]
            if summed_proj is not None:
                stats["outs"]["projected"] = round(summed_proj["outs"], 3)
                stats["outs"]["error"] = round(
                    summed_act["_outs"] - summed_proj["outs"], 3)
        if stats:
            rows.append({
                "player_id": 0, "name": "Bullpen", "team": team,
                "side": "pitcher", "position": "RP", "role": "RP",
                "lineup_slot": None, "aggregate": True,
                "arms_used": len(pen_act),
                "projected": summed_proj is not None,
                "played": summed_act is not None,
                "stats": stats,
            })
    return rows


# ── Rolling report ──────────────────────────────────────────────────────────

def _agg_init() -> dict:
    return {"n": 0, "abs_err": 0.0, "sq_err": 0.0, "signed_err": 0.0,
            "proj_total": 0.0, "actual_total": 0.0, "exact": 0}


def _agg_add(a: dict, proj: float, act: float) -> None:
    e = act - proj
    a["n"] += 1
    a["abs_err"] += abs(e)
    a["sq_err"] += e * e
    a["signed_err"] += e
    a["proj_total"] += proj
    a["actual_total"] += act
    if round(proj) == act:
        a["exact"] += 1


def _agg_done(a: dict) -> Optional[dict]:
    n = a["n"]
    if not n:
        return None
    mae = a["abs_err"] / n
    # Scale the average miss against the average real value, so a stat that
    # happens twice a game and one that happens twice a month are readable on
    # the same axis. Guarded at 1 so a near-zero denominator (home runs) can't
    # turn a small miss into a huge percentage.
    denom = max(a["actual_total"] / n, 1.0)
    return {
        "n": n,
        "mae": round(mae, 3),
        "rmse": round(math.sqrt(a["sq_err"] / n), 3),
        "bias": round(a["signed_err"] / n, 3),
        "proj_per_game": round(a["proj_total"] / n, 3),
        "actual_per_game": round(a["actual_total"] / n, 3),
        "exact_pct": round(100 * a["exact"] / n, 1),
        "accuracy_pct": round(max(0.0, 100 * (1 - mae / denom)), 1),
    }


def _roll(bucket: dict, stats: dict) -> None:
    for stat, v in stats.items():
        p, a = v.get("projected"), v.get("actual")
        if p is None or a is None:
            continue
        _agg_add(bucket.setdefault(stat, _agg_init()), float(p), float(a))


def _finish(bucket: dict) -> dict:
    return {k: d for k, d in ((s, _agg_done(v)) for s, v in bucket.items())
            if d is not None}


def build_report(games: list[dict], *, start: str, end: str) -> dict:
    """Aggregate scored games into the report the UI renders.

    Everything is grouped more than once — by stat, by position, by player —
    because the useful question is rarely "how accurate is the model" but
    "where is it wrong". A model that is excellent on hits and badly biased on
    strikeouts averages out to unremarkable, and the average is the one number
    that hides it.
    """
    import numpy as np

    overall_bat: dict = {}
    overall_pit: dict = {}
    by_position: dict[str, dict] = {}
    by_player: dict[tuple, dict] = {}
    by_slot: dict[int, dict] = {}

    winners, ties, briers, losses, win_probs, win_hits = 0, 0, [], [], [], []
    picked = 0
    run_err, total_err, spread_err = [], [], []
    covered_total, covered_home, covered_away = [], [], []
    centr_total, centr_spread = [], []
    exact_scores = []
    unprojected, unplayed = 0, 0
    pregame_games = 0

    for g in games:
        o = g.get("outcome") or {}
        if o.get("picked_winner") is not None:
            winners += 1
            picked += 1 if o["picked_winner"] else 0
        else:
            ties += 1
        if "brier" in o:
            briers.append(o["brier"])
            losses.append(o["log_loss"])
            win_probs.append(o["home_win_probability"])
            win_hits.append(1 if g["actual"]["winner"] == "home" else 0)
        for key, errs, cov in (("home_runs", run_err, covered_home),
                               ("away_runs", run_err, covered_away)):
            d = o.get(key) or {}
            if "error" in d:
                errs.append(abs(d["error"]))
                cov.append(1 if d.get("covered") else 0)
        for key, errs, cov, cen in (("total", total_err, covered_total, centr_total),
                                    ("spread", spread_err, None, centr_spread)):
            d = o.get(key) or {}
            if "error" in d:
                errs.append(abs(d["error"]))
                if cov is not None:
                    cov.append(1 if d.get("covered") else 0)
                if cen is not None and d.get("centrality_pct") is not None:
                    cen.append(d["centrality_pct"])
        if o.get("exact_score_pct") is not None:
            exact_scores.append(o["exact_score_pct"])
        if g.get("pregame"):
            pregame_games += 1

        for row in list(g.get("batters", [])) + list(g.get("pitchers", [])):
            if not row.get("projected"):
                unprojected += 1
            if not row.get("played"):
                unplayed += 1
            stats = row.get("stats") or {}
            target = overall_bat if row["side"] == "batter" else overall_pit
            _roll(target, stats)
            pos = row.get("position") or ("SP" if row.get("role") == "SP" else None)
            if pos:
                _roll(by_position.setdefault(pos, {}), stats)
            pkey = (row["player_id"], row["name"], row["team"], row["side"],
                    row.get("position"))
            entry = by_player.setdefault(pkey, {"games": 0, "buckets": {}})
            entry["games"] += 1
            _roll(entry["buckets"], stats)
            if row["side"] == "batter" and row.get("lineup_slot"):
                _roll(by_slot.setdefault(int(row["lineup_slot"]), {}), stats)

    def _mean(v):
        return round(float(np.mean(v)), 4) if v else None

    # Calibration: does a 60% call actually win 60% of the time? Ten buckets is
    # too many for a handful of games, so five is the default granularity.
    cal_buckets = []
    if win_probs:
        edges = [0.0, 0.35, 0.45, 0.55, 0.65, 1.01]
        for lo, hi in zip(edges, edges[1:]):
            idx = [i for i, p in enumerate(win_probs) if lo <= p < hi]
            if idx:
                cal_buckets.append({
                    "range": f"{int(lo*100)}-{int(min(hi,1.0)*100)}%",
                    "n": len(idx),
                    "predicted": round(float(np.mean([win_probs[i] for i in idx])), 4),
                    "actual": round(float(np.mean([win_hits[i] for i in idx])), 4),
                })

    players = []
    for (pid, name, team, side, pos), entry in by_player.items():
        stats = _finish(entry["buckets"])
        if not stats:
            continue
        players.append({
            "player_id": pid, "name": name, "team": team, "side": side,
            "position": pos, "games": entry["games"], "stats": stats,
        })
    players.sort(key=lambda p: (-p["games"], p["name"]))

    positions = []
    for pos, bucket in by_position.items():
        stats = _finish(bucket)
        if stats:
            positions.append({"position": pos, "stats": stats,
                              "players": sum(1 for p in players
                                             if p["position"] == pos)})
    positions.sort(key=lambda d: (POSITION_ORDER.index(d["position"])
                                  if d["position"] in POSITION_ORDER else 99))

    games_out = [{
        "game_id": g["game_id"], "date": g["date"],
        "home": g["home"], "away": g["away"],
        "actual": g["actual"],
        "home_win_probability": (g.get("outcome") or {}).get("home_win_probability"),
        "picked_winner": (g.get("outcome") or {}).get("picked_winner"),
        "predicted_total": ((g.get("outcome") or {}).get("total") or {}).get("mean"),
        "total_error": ((g.get("outcome") or {}).get("total") or {}).get("error"),
        "total_covered": ((g.get("outcome") or {}).get("total") or {}).get("covered"),
        "exact_score_pct": (g.get("outcome") or {}).get("exact_score_pct"),
        "pregame": g.get("pregame", False),
    } for g in games]
    games_out.sort(key=lambda g: (g["date"], g["game_id"]))

    return {
        "window": {"start": start, "end": end, "games": len(games),
                   "pregame_games": pregame_games,
                   "resimulated_games": len(games) - pregame_games},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "outcomes": {
            "games_scored": winners,
            "ties": ties,
            "winner_accuracy_pct": (round(100 * picked / winners, 1)
                                    if winners else None),
            "winners_correct": picked,
            "brier": _mean(briers),
            "log_loss": _mean(losses),
            "run_mae": _mean(run_err),
            "total_mae": _mean(total_err),
            "spread_mae": _mean(spread_err),
            "total_coverage_pct": (round(100 * float(np.mean(covered_total)), 1)
                                   if covered_total else None),
            "team_runs_coverage_pct": (
                round(100 * float(np.mean(covered_home + covered_away)), 1)
                if (covered_home or covered_away) else None),
            "total_centrality_pct": _mean(centr_total),
            "spread_centrality_pct": _mean(centr_spread),
            "mean_exact_score_pct": _mean(exact_scores),
            "calibration": cal_buckets,
        },
        "batting": _finish(overall_bat),
        "pitching": _finish(overall_pit),
        "by_position": positions,
        "by_lineup_slot": [{"slot": s, "stats": _finish(b)}
                           for s, b in sorted(by_slot.items())],
        "players": players,
        "games": games_out,
        "coverage": {"unprojected_appearances": unprojected,
                     "projected_but_absent": unplayed},
    }


# ── Fetching, scoring and storing ───────────────────────────────────────────

def _base_game_id(game_id: str) -> str:
    import re
    return re.sub(r"-g\d+$", "", game_id)


def parse_game_id(game_id: str) -> tuple[Optional[date], Optional[str], Optional[str]]:
    """'<date>-<away>-<home>[-g{N}]' → (date, home, away)."""
    parts = _base_game_id(game_id).rsplit("-", 2)
    if len(parts) != 3:
        return None, None, None
    try:
        d = datetime.strptime(parts[0], "%Y-%m-%d").date()
    except ValueError:
        return None, None, None
    return d, parts[2], parts[1]


def fetch_actual(repo, game_id: str) -> Optional[dict]:
    """Real final line plus box score for a finished game, or None.

    Refreshes the schedule first so a game that has just ended reads as Final
    rather than as whatever was stored this morning.
    """
    game_date, _, _ = parse_game_id(game_id)
    if game_date is None:
        return None
    try:
        from .data.sources.schedules import MLBScheduleSource
        MLBScheduleSource(repo).fetch_schedule(game_date)
    except Exception:
        pass  # whatever is stored is better than nothing
    row = next((g for g in repo.get_schedule(game_date)
                if g.game_id == game_id), None)
    if row is None or row.game_pk is None:
        return None
    if "final" not in (row.status or "").lower():
        return None
    if row.home_score is None or row.away_score is None:
        return None
    box = None
    try:
        from .data.sources.boxscore import MLBBoxscoreSource
        box = MLBBoxscoreSource().fetch_boxscore(row.game_pk, game_id)
    except Exception:
        box = None
    return {"home_runs": int(row.home_score), "away_runs": int(row.away_score),
            "status": row.status, "boxscore": box}


def score_and_store(repo, game_id: str, *, season: int, park_season: int,
                    n: int = 1500, force: bool = False,
                    name_lookup=None) -> Optional[dict]:
    """Score one finished game and persist it. Returns None if not scoreable.

    Already-scored games are returned from storage unless `force`, which is
    what keeps a rolling rebuild cheap: only genuinely new finals are
    simulated.
    """
    if not force:
        cached = repo.get_accuracy_game(game_id)
        if cached is not None:
            return cached

    game_date, home, away = parse_game_id(game_id)
    if game_date is None or home is None:
        return None
    actual = fetch_actual(repo, game_id)
    if actual is None:
        return None

    from .pipeline import ensure_lineups, resolve_lineups, simulate_matchup

    ensure_lineups(repo, game_id, home, away, season)
    result, raw = simulate_matchup(
        game_id, repo, home_team=home, away_team=away, n=n,
        season=season, park_season=park_season)
    home_lineup, away_lineup = resolve_lineups(game_id, repo, home, away)

    names: dict[int, str] = {}
    if name_lookup is not None:
        ids = [int(pl["player_id"]) for pl in getattr(result, "player_lines", [])]
        ids += [int(pl["player_id"]) for pl in getattr(result, "pitcher_lines", [])]
        try:
            names = name_lookup([i for i in ids if i > 0]) or {}
        except Exception:
            names = {}

    scored = score_game(
        game_id=game_id, game_date=game_date, home=home, away=away,
        result=result, raw=raw, home_lineup=home_lineup,
        away_lineup=away_lineup, actual=actual, names=names, pregame=False)
    repo.save_accuracy_game(game_id, game_date, scored["scored_at"], scored)
    return scored


def refresh_window(repo, *, end: date, days: int, season: int, park_season: int,
                   n: int = 1500, limit: Optional[int] = None,
                   force: bool = False, name_lookup=None) -> dict:
    """Score every finished game in the window that isn't scored yet.

    `limit` caps how many games are simulated in one call, so a scheduled run
    can't hang indefinitely on a backlog; the next run picks up the rest.
    """
    from datetime import timedelta

    start = end - timedelta(days=days - 1)
    already = set() if force else repo.accuracy_game_ids(start, end)

    # Fetch the window's schedule before reading it. The bundled database is a
    # snapshot taken whenever it was last committed, so in CI it reliably stops
    # weeks short of the window being graded — and an unfetched window has no
    # games to iterate, which looks exactly like "nothing to grade" rather than
    # like missing data. Best-effort: an unreachable API leaves whatever is
    # stored, which is the right degradation.
    fetched = 0
    try:
        from .data.sources.schedules import MLBScheduleSource
        source = MLBScheduleSource(repo)
        for i in range((end - start).days + 1):
            try:
                fetched += len(source.fetch_schedule(start + timedelta(days=i)) or [])
            except Exception:
                continue
    except Exception:
        pass

    scheduled = repo.get_schedule_range(start, end)

    scored, skipped, failed = 0, 0, 0
    for g in scheduled:
        if g.game_id in already:
            skipped += 1
            continue
        if limit is not None and scored >= limit:
            break
        try:
            out = score_and_store(repo, g.game_id, season=season,
                                  park_season=park_season, n=n, force=force,
                                  name_lookup=name_lookup)
        except Exception:
            out = None
        if out is None:
            failed += 1
        else:
            scored += 1
    return {"start": start.isoformat(), "end": end.isoformat(),
            "schedule_rows_fetched": fetched,
            "scheduled": len(scheduled), "newly_scored": scored,
            "already_scored": skipped, "not_scoreable": failed}


def load_report(repo, *, end: date, days: int) -> dict:
    """The rolling report over a window, built from stored scored games."""
    from datetime import timedelta

    start = end - timedelta(days=days - 1)
    games = repo.get_accuracy_games(start, end)
    return build_report(games, start=start.isoformat(), end=end.isoformat())


# ── The durable record ──────────────────────────────────────────────────────
#
# The app runs in a container whose filesystem is rebuilt from the image on
# every deploy, and the deploy copies `data/` in wholesale. Anything the
# running app writes to the database is therefore erased by the next push —
# which makes the database a cache, not a record.
#
# So the record lives in the repository as a JSONL file, one scored game per
# line, written by the scheduled job and committed. The container loads it on
# startup. That also means scoring happens in CI rather than in the Space: the
# runner has the statline database, network access to MLB, and somewhere to
# put the answer that survives.

SCORED_PATH = "data/accuracy/scored.jsonl"


def _scored_file(root: Optional[str] = None):
    from pathlib import Path
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    return base / SCORED_PATH


def export_scored(repo, path=None, *, root: Optional[str] = None) -> int:
    """Write every stored scorecard to the JSONL record. Returns the count.

    Sorted by date then game id so the file has a stable order and a rerun
    that changes nothing produces no diff.
    """
    import json
    from pathlib import Path

    target = Path(path) if path else _scored_file(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with repo._connect() as conn:
        rows = conn.execute(
            "SELECT data FROM accuracy_games ORDER BY date, game_id").fetchall()
    with open(target, "w", encoding="utf-8") as fh:
        for (blob,) in rows:
            fh.write(json.dumps(json.loads(blob), sort_keys=True,
                                separators=(",", ":")) + "\n")
    return len(rows)


def import_scored(repo, path=None, *, root: Optional[str] = None) -> int:
    """Load the JSONL record into the database. Returns how many were added.

    Idempotent and non-destructive: a game already in the database is left
    alone, so a container that has scored something itself does not lose it,
    and a missing or malformed line is skipped rather than fatal — a broken
    record should degrade the report, not stop the app from booting.
    """
    import json
    from pathlib import Path

    target = Path(path) if path else _scored_file(root)
    if not target.exists():
        return 0
    existing: set[str] = set()
    with repo._connect() as conn:
        existing = {r[0] for r in conn.execute("SELECT game_id FROM accuracy_games")}
    added = 0
    with open(target, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                gid = rec["game_id"]
                if gid in existing:
                    continue
                d = datetime.strptime(rec["date"], "%Y-%m-%d").date()
            except Exception:
                continue
            repo.save_accuracy_game(gid, d, rec.get("scored_at", ""), rec)
            existing.add(gid)
            added += 1
    return added
