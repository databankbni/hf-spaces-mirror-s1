#!/usr/bin/env python3
"""research/augment_features.py — add the ML_EXTRA_FEATURES columns to an existing
training CSV WITHOUT re-running the slow per-date compute_features.

The base CSV (ml_predictor/training_data.csv) already carries the 37 production features
+ forward labels for every sampled (ticker, date). This script reloads each ticker's OHLCV
from the same SQLite cache dataset.py uses, computes ONLY the extra indicator columns
(vectorized, full series) + the per-date Monte-Carlo path features via the SHARED helpers in
ml_predictor.features (so live inference and training stay identical), and merges them onto
the base rows by (ticker, date). Writes an augmented CSV.

Usage:
    python research/augment_features.py \
        --in ml_predictor/training_data.csv \
        --out ml_predictor/training_data_extra.csv
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import EXTRA_FEATURE_COLS, _extra_feature_series, _mc_features  # noqa: E402
from ml_predictor.dataset import _load_ticker  # noqa: E402

DEFAULT_IN = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data.csv")
DEFAULT_OUT = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data_extra.csv")

_INDICATOR_COLS = [c for c in EXTRA_FEATURE_COLS if not c.startswith("mc_")]
_MC_COLS = [c for c in EXTRA_FEATURE_COLS if c.startswith("mc_")]


def _rows_for_ticker(ticker: str, want_dates: set) -> list[dict]:
    loaded = _load_ticker(ticker)
    if loaded is None:
        return []
    c, h, l, v = (s.dropna() for s in loaded)
    if len(c) < 30:
        return []
    ser = _extra_feature_series(c, h, l, v)          # vectorized indicator Series
    rets_full = c.pct_change().to_numpy()
    idx_by_ts = {pd.Timestamp(d).strftime("%Y-%m-%d"): i for i, d in enumerate(c.index)}
    rows = []
    for dstr in want_dates:
        i = idx_by_ts.get(dstr)
        if i is None:
            continue
        row = {"date": dstr, "ticker": ticker}
        for col, s in ser.items():
            try:
                val = float(s.iloc[i])
            except Exception:
                val = np.nan
            row[col] = val if np.isfinite(val) else np.nan
        # Monte-Carlo on the trailing 63 returns up to (and including) this bar.
        up_prob, exp_up, exp_dn = _mc_features(rets_full[max(0, i - 62): i + 1])
        row["mc_up_prob_3d"] = up_prob
        row["mc_exp_maxup_3d"] = exp_up
        row["mc_exp_maxdn_3d"] = exp_dn
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=DEFAULT_IN)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    base = pd.read_csv(args.inp)
    base["date"] = base["date"].astype(str)
    print(f"  Base CSV: {len(base):,} rows · {base['ticker'].nunique()} tickers")

    want = {tk: set(g["date"]) for tk, g in base.groupby("ticker")}
    tickers = list(want.keys())

    all_rows: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_rows_for_ticker, tk, want[tk]): tk for tk in tickers}
        for fut in as_completed(futs):
            try:
                all_rows.extend(fut.result())
            except Exception as e:
                print(f"    ! {futs[fut]}: {e}")
            done += 1
            if done % 100 == 0 or done == len(tickers):
                print(f"    {done}/{len(tickers)} tickers · {len(all_rows):,} extra rows")

    extra = pd.DataFrame(all_rows)
    if extra.empty:
        raise SystemExit("No extra rows produced — is ohlcv_cache.db populated?")
    merged = base.merge(extra, on=["date", "ticker"], how="left")

    # Reorder so extra columns sit before the label columns (labels stay last).
    label_cols = [c for c in merged.columns if c in (
        "up_INTRADAY", "dn_INTRADAY", "up_1D", "dn_1D", "up_3D", "dn_3D",
        "ret_1D", "ret_3D", "dir_INTRADAY", "dir_1D", "dir_3D")]
    front = [c for c in merged.columns if c not in label_cols and c not in EXTRA_FEATURE_COLS]
    merged = merged[front + EXTRA_FEATURE_COLS + label_cols]

    n_missing = merged[EXTRA_FEATURE_COLS].isna().any(axis=1).sum()
    merged.to_csv(args.out, index=False)
    print(f"\n  ✓ Wrote {len(merged):,} rows × {merged.shape[1]} cols → {args.out}")
    print(f"  Extra cols: {EXTRA_FEATURE_COLS}")
    print(f"  Rows with any missing extra feature: {n_missing:,} ({n_missing / len(merged):.1%})")
    for col in EXTRA_FEATURE_COLS:
        s = merged[col].dropna()
        if len(s):
            print(f"    {col:<18} mean={s.mean():>8.3f}  p50={s.median():>8.3f}  "
                  f"p10={s.quantile(.1):>8.3f}  p90={s.quantile(.9):>8.3f}")


if __name__ == "__main__":
    main()
