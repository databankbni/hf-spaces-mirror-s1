"""Full-season out-of-sample calibration run (thebeast-8u0).

Trains on 2023 statlines, predicts every 2024 game out-of-sample, and calibrates
the model's home-win probabilities against actual 2024 results.

Resumable:
  * statline ingestion is skipped when the repo already holds the season
  * per-game predictions are appended to predictions.jsonl and reloaded on restart

Run:  uv run python scripts/calibration_run.py
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

from thebeast.data.ingest import fetch_statcast_range, ingest_dataframe
from thebeast.data.repository import SQLiteRepository
from thebeast.data.sources.results import MLBResultsSource
from thebeast.data.sources.schedules import MLBScheduleSource
from thebeast.matchup.calibration import IsotonicCalibrator, reliability_curve
from thebeast.betting.edge import log_loss
from thebeast.pipeline import simulate_matchup

LOCAL = Path(__file__).resolve().parent.parent / "local_data"
LOCAL.mkdir(exist_ok=True)
DB_PATH = str(LOCAL / "thebeast.db")
PRED_PATH = LOCAL / "predictions.jsonl"
REPORT_PATH = LOCAL / "calibration_report.json"

TRAIN_SEASON = 2023
HOLDOUT_SEASON = 2024
N_SIMS = 150
MIN_PA = 100
MIN_BF = 100

# Regular-season date spans (approximate; covers all games).
TRAIN_SPAN = (date(2023, 3, 30), date(2023, 10, 1))
HOLDOUT_SPAN = (date(2024, 3, 28), date(2024, 9, 30))


def log(msg: str) -> None:
    print(msg, flush=True)


def _month_ranges(start: date, end: date):
    cur = start
    while cur <= end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        span_end = min(nxt - timedelta(days=1), end)
        yield cur, span_end
        cur = nxt


def ingest_season(repo: SQLiteRepository, season: int, span) -> None:
    existing = repo.get_batters_for_season(season)
    if len(existing) > 200:
        log(f"[ingest] {season}: already have {len(existing)} batters — skipping")
        return
    start, end = span
    import pandas as pd
    frames = []
    for m_start, m_end in _month_ranges(start, end):
        log(f"[ingest] {season}: fetching {m_start}..{m_end}")
        frames.append(fetch_statcast_range(m_start.isoformat(), m_end.isoformat()))
    # Concatenate all months so each statline reflects the full season, then
    # build once. Per-month fetching bounds each network call's size.
    df = pd.concat(frames, ignore_index=True)
    log(f"[ingest] {season}: building statlines from {len(df)} rows")
    n_b, n_p = ingest_dataframe(df, season, repo, min_pa=MIN_PA, min_bf=MIN_BF)
    log(f"[ingest] {season}: DONE — {n_b} batters, {n_p} pitchers (>= {MIN_PA} PA / {MIN_BF} BF)")


def collect_games(repo: SQLiteRepository, span) -> list[dict]:
    """Fetch schedules+lineups+results for the holdout span; return game dicts."""
    sched = MLBScheduleSource(repo)
    results_src = MLBResultsSource()
    start, end = span
    games: list[dict] = []
    cur = start
    n_days = (end - start).days + 1
    day_i = 0
    while cur <= end:
        day_i += 1
        try:
            day_games = sched.fetch_schedule(cur)
            results = {r.game_id: r for r in results_src.fetch_results(cur)}
        except Exception as exc:
            log(f"[collect] {cur}: fetch failed ({exc}); skipping")
            cur += timedelta(days=1)
            continue
        kept = 0
        for g in day_games:
            res = results.get(g.game_id)
            if res is None:
                continue
            home_lc = repo.get_lineup(g.game_id, g.home_team_id)
            away_lc = repo.get_lineup(g.game_id, g.away_team_id)
            if home_lc is None or away_lc is None:
                continue
            games.append({
                "game_id": g.game_id,
                "home_team": g.home_team_id,
                "away_team": g.away_team_id,
                "home_won": res.home_won,
            })
            kept += 1
        if day_i % 10 == 0 or kept:
            log(f"[collect] {cur} ({day_i}/{n_days}): +{kept} games (total {len(games)})")
        cur += timedelta(days=1)
    return games


def load_done() -> dict[str, dict]:
    done: dict[str, dict] = {}
    if PRED_PATH.exists():
        for line in PRED_PATH.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["game_id"]] = rec
    return done


def predict_games(repo: SQLiteRepository, games: list[dict]) -> list[dict]:
    done = load_done()
    log(f"[predict] {len(done)} already done; {len(games)} total games")
    with PRED_PATH.open("a") as fh:
        for i, g in enumerate(games, 1):
            if g["game_id"] in done:
                continue
            try:
                result, _ = simulate_matchup(
                    g["game_id"], repo,
                    home_team=g["home_team"], away_team=g["away_team"],
                    n=N_SIMS, seed=7, season=TRAIN_SEASON,
                    calibrate=False, calibrate_totals=False,  # fit on raw model output
                )
            except Exception as exc:
                log(f"[predict] {g['game_id']} failed: {exc}")
                continue
            rec = {
                "game_id": g["game_id"],
                "model_home_win_prob": result.home_win_probability,
                "home_won": g["home_won"],
            }
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            done[g["game_id"]] = rec
            if i % 100 == 0:
                log(f"[predict] {i}/{len(games)} simulated")
    return list(done.values())


def calibrate(records: list[dict]) -> None:
    probs = [r["model_home_win_prob"] for r in records]
    actuals = [1 if r["home_won"] else 0 for r in records]
    n = len(records)
    log(f"\n=== CALIBRATION (out-of-sample: 2023 model → 2024 results, n={n}) ===")

    base_rate = sum(actuals) / n
    log(f"actual home-win base rate : {base_rate:.3f}")
    model_ll = log_loss(probs, actuals)
    baseline_ll = log_loss([base_rate] * n, actuals)
    log(f"model    log-loss          : {model_ll:.5f}")
    log(f"baseline log-loss (always base rate) : {baseline_ll:.5f}")
    log(f"model beats naive baseline : {model_ll < baseline_ll}")

    pre = reliability_curve(probs, actuals, n_bins=10)
    log("\nPre-calibration reliability:")
    log(pre.format())

    cal = IsotonicCalibrator().fit(probs, actuals)
    adjusted = cal.transform(probs)
    post = reliability_curve(adjusted, actuals, n_bins=10)
    log("\nPost-isotonic-calibration reliability:")
    log(post.format())
    log(f"\nmax deviation: pre={pre.max_deviation:.4f} → post={post.max_deviation:.4f}")
    log(f"post within ±2% per decile: {post.within_tolerance(0.02)}")

    REPORT_PATH.write_text(json.dumps({
        "n_games": n,
        "train_season": TRAIN_SEASON,
        "holdout_season": HOLDOUT_SEASON,
        "actual_home_win_rate": base_rate,
        "model_log_loss": model_ll,
        "baseline_log_loss": baseline_ll,
        "pre_max_deviation": pre.max_deviation,
        "post_max_deviation": post.max_deviation,
        "pre_curve": {"predicted": pre.bin_predicted, "actual": pre.bin_actual, "count": pre.bin_count},
        "post_curve": {"predicted": post.bin_predicted, "actual": post.bin_actual, "count": post.bin_count},
    }, indent=2))
    log(f"\n[done] report → {REPORT_PATH}")


def main() -> int:
    log(f"[start] db={DB_PATH}")
    repo = SQLiteRepository(DB_PATH)
    ingest_season(repo, TRAIN_SEASON, TRAIN_SPAN)
    games = collect_games(repo, HOLDOUT_SPAN)
    log(f"[collect] DONE — {len(games)} games with lineups + results")
    records = predict_games(repo, games)
    if not records:
        log("[error] no predictions produced")
        return 1
    calibrate(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
