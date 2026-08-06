"""
Cross-stock parameter study — find the lookback/T range that generalises.

Instead of tuning per ticker in isolation, this runs the walk-forward validation across a
whole basket and aggregates: which lookback consistently gives the lowest MAPE while still
beating a random walk and staying in-distribution? The answer becomes the *global default*
for tickers that don't have their own profile yet.

Because the per-(ticker, config) walk-forward runs ARE the profile evidence, this also
writes each ticker's trust profile in the same pass — one expensive sweep, two outputs:
  * us/out/study.csv                 (every ticker x config row, for analysis)
  * us/out/profiles/<TICKER>_1d.json (per-ticker recommended config + trust card)

Example
-------
  python us/study.py --pred_len 20 --n_windows 5 --n_paths 10 --lookbacks 60,120,180,240
"""
import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from predict_us import fetch_ohlcv
from engine import get_predictor, _RANGE_THRESH
from autoconfig import run_ticker, profile_path

# Diverse basket: mega-cap tech, ETFs, high-vol names, and non-tech sectors.
DEFAULT_BASKET = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD",
                  "SPY", "QQQ", "JPM", "XOM", "WMT", "KO"]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=",".join(DEFAULT_BASKET))
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--pred_len", type=int, default=20)
    ap.add_argument("--n_windows", type=int, default=8)
    ap.add_argument("--n_outer", type=int, default=3)
    ap.add_argument("--n_paths", type=int, default=10)
    ap.add_argument("--lookbacks", default="60,120,180,240")
    ap.add_argument("--temps", default="0.7")
    ap.add_argument("--top_p", type=float, default=0.9)
    ap.add_argument("--target_coverage", type=float, default=0.8)
    ap.add_argument("--objective", default="blend")
    ap.add_argument("--seed", type=int, default=123)
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    lookbacks = [int(x) for x in args.lookbacks.split(",") if x.strip()]
    temps = [float(x) for x in args.temps.split(",") if x.strip()]

    predictor = get_predictor()
    outdir = Path(__file__).resolve().parent / "out"
    prof_dir = outdir / "profiles"; prof_dir.mkdir(parents=True, exist_ok=True)

    n_cfg = len(lookbacks) * len(temps)
    n_pred = len(tickers) * n_cfg * args.n_windows * args.n_paths
    print(f"[study] {len(tickers)} tickers x {n_cfg} configs x {args.n_windows} win "
          f"x {args.n_paths} paths ≈ {n_pred} predicts (nested {args.n_windows-args.n_outer}/{args.n_outer})\n")

    rows = []
    best_lb, best_T, grades = [], [], []
    t0 = time.time()

    for tk in tickers:
        try:
            df = fetch_ohlcv(tk, args.interval, args.period)
            prof = run_ticker(predictor, df, tk, args.interval, args.period, args.pred_len,
                              lookbacks, temps, args.top_p, args.n_paths, args.n_windows,
                              args.n_outer, args.target_coverage, args.objective, args.seed)
        except Exception as e:
            print(f"[skip] {tk}: {e}")
            continue

        profile_path(prof_dir, tk, args.interval).write_text(
            __import__("json").dumps(prof, indent=2, ensure_ascii=False), encoding="utf-8")
        rec = prof["recommended"]; tr = prof["track_record"]; v = prof["verdict"]
        best_lb.append(rec["lookback"]); best_T.append(rec["T"]); grades.append(v["grade"])
        for c in prof["all_configs"]:   # inner (selection) metrics per config, for the range study
            rows.append({"ticker": tk, **c})

        print(f"[{tk:5}] best lb={rec['lookback']:>3} T={rec['T']} grade {v['grade']}  | "
              f"HONEST(outer): MAPE={tr['MAPE%']}% skill={tr['skill_vs_rw']} "
              f"IC={tr['IC']} Dir={tr['DirAcc%']}%")

    # ---- write raw table ----
    df_rows = pd.DataFrame(rows)
    csv = outdir / "study.csv"
    df_rows.to_csv(csv, index=False)

    # ---- aggregate: which lookback generalises? ----
    print("\n" + "=" * 64)
    print("CROSS-STOCK SUMMARY")
    print("=" * 64)
    if not df_rows.empty:
        ind = df_rows[df_rows["in_distribution"]]
        print("\nMean MAPE by lookback (in-distribution only):")
        by_lb = ind.groupby("lookback").agg(
            MAPE_mean=("MAPE%", "mean"), MAPE_median=("MAPE%", "median"),
            skill_mean=("skill_vs_rw", "mean"), n=("MAPE%", "size")).round(3)
        print(by_lb.to_string())

        # per-ticker best lookback by MAPE (in-dist)
        print("\nPer-ticker best lookback (min MAPE, in-distribution):")
        picks = (ind.sort_values("MAPE%").groupby("ticker").first()
                 .reset_index()[["ticker", "lookback", "T", "MAPE%", "skill_vs_rw"]])
        print(picks.to_string(index=False))

        lb_counts = Counter(picks["lookback"].tolist())
        print("\nBest-lookback distribution:", dict(sorted(lb_counts.items())))
        winners = ind.groupby("lookback")["MAPE%"].mean().sort_values()
        print(f"Lowest mean-MAPE lookback: {int(winners.index[0])} "
              f"(MAPE {winners.iloc[0]:.2f}%)")
    print(f"\ngrades: {dict(Counter(grades))}")
    print(f"[done] {time.time()-t0:.0f}s  table -> {csv}  profiles -> {prof_dir}")


if __name__ == "__main__":
    main()
