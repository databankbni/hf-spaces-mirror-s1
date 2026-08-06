#!/usr/bin/env python3
"""research/strategy_combo_swing.py — does STRATEGY CONFLUENCE (2-3 signals firing
together) improve SWING-trade (1D / 3D) hit rate?

For a broad sample of already-cached NSE tickers this walks each trading day in a lookback
window (point-in-time, no lookahead), records:
  • which strategy signals (S1..S20, S_CTRIO, MFS, …) were active that day (5-bar window,
    exactly like predictor_core.run_strategy_signals)
  • the ML model's 1D/3D call + its median target
  • whether the median target was actually hit over the forward window

then answers three swing-trading questions:
  1. Does median-hit RISE with the NUMBER of strategies co-firing (0 / 1 / 2 / 3+)?
  2. Which specific 2-strategy PAIRS give the best median-hit?
  3. Which specific 3-strategy TRIPLES give the best median-hit?
Reported for ALL calls and for ML-BULLISH-only calls (the actual swing-long entries).

No network: uses the OHLCV cache (fetch_ohlcv hits the SQLite cache for warmed tickers).

Usage:
    python research/strategy_combo_swing.py                       # 200 cached tickers, 90-day window
    python research/strategy_combo_swing.py --tickers 350 --days 120
    python research/strategy_combo_swing.py --tfs 3D --min-n 40 --bullish-only
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import FEATURE_COLUMNS, compute_features  # noqa: E402
from ml_predictor.infer import MLPredictor  # noqa: E402
from research.ml_backtest import _graded_hit  # noqa: E402
from data_sources import cached_tickers, fetch_ohlcv  # noqa: E402
import trial_run as T  # noqa: E402

_HORIZON = {"1D": 1, "3D": 3}
_LOOKBACK = 5  # a signal is "active" for 5 bars, matching run_strategy_signals
_DIRC = {"1D": "dir_1D", "3D": "dir_3D"}  # realized excess-of-Nifty direction label


# gen(name → callable(sc,sh,sl,sv,nifty,vix)) mirroring predictor_core.run_strategy_signals
def _gen_map():
    n = lambda f: (lambda sc, sh, sl, sv, ni, vx: f(sc, sh, sl, sv, ni))
    b = lambda f: (lambda sc, sh, sl, sv, ni, vx: f(sc, sh, sl, sv))
    v = lambda f: (lambda sc, sh, sl, sv, ni, vx: f(sc, sh, sl, sv, vx))
    nv = lambda f: (lambda sc, sh, sl, sv, ni, vx: f(sc, sh, sl, sv, ni, vx))
    return {
        "S1": n(T.gen_s1), "S2": n(T.gen_s2), "S3": b(T.gen_s3), "MFS": n(T.gen_mfs),
        "NIRA": n(T.gen_nira), "PED": b(T.gen_ped),
        "SUPER": (lambda sc, sh, sl, sv, ni, vx: T.gen_supertrend(sc, sh, sl)),
        "S4": v(T.gen_s4), "S5": v(T.gen_s5), "S6": nv(T.gen_s6),
        "S4V2": nv(T.gen_s4v2), "S5V2": nv(T.gen_s5v2), "S6V2": nv(T.gen_s6v2),
        "S7": nv(T.gen_s7), "S8": nv(T.gen_s8), "S9": nv(T.gen_s9), "S10": nv(T.gen_s10),
        "S11": nv(T.gen_s11), "S_CAPFLOW": nv(T.gen_s_capflow),
        "S_CTRIO": nv(T.gen_s_confluence_trio), "S_SEASONAL": nv(T.gen_s_seasonal),
        "S12": nv(T.gen_s12), "S13": nv(T.gen_s13), "S14": nv(T.gen_s14), "S15": nv(T.gen_s15),
        "S16": nv(T.gen_s16), "S17": nv(T.gen_s17), "S18": nv(T.gen_s18), "S19": nv(T.gen_s19),
        "S20": nv(T.gen_s20),
    }


def _active_by_pos(tk, sc, sh, sl, sv, nifty_c, vix_c, n_bars: int, gens) -> list[set]:
    """active_by_pos[p] = set of strategies active at bar position p (fired within last 5 bars)."""
    active = [set() for _ in range(n_bars)]
    pos_of = {d: i for i, d in enumerate(sc.index)}
    for name, fn in gens.items():
        try:
            sigs = fn(sc, sh, sl, sv, nifty_c, vix_c)
        except Exception:
            continue
        for d, t in sigs:
            p = pos_of.get(d)
            if p is None:
                continue
            for q in range(p, min(p + _LOOKBACK, n_bars)):
                active[q].add(name)
    return active


def _indices():
    try:
        import yfinance as yf
        raw = yf.download(["^NSEI", "^INDIAVIX"], period="2y", auto_adjust=True, progress=False)
        return raw["Close"]["^NSEI"].dropna(), raw["Close"]["^INDIAVIX"].dropna()
    except Exception:
        return None, None


_CSV = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data_extra.csv")
_UP = {"1D": "up_1D", "3D": "up_3D"}
_DN = {"1D": "dn_1D", "3D": "dn_3D"}


def run(n_tickers: int, days: int, tfs, min_n: int, bullish_only: bool, seed: int):
    predictor = MLPredictor()
    if not predictor.available:
        raise SystemExit("ml_predictor model not loaded — run `python ml_predictor/train.py` first.")
    # FAST PATH: features + realized excursions come precomputed from training_data_extra.csv
    # (no per-day recompute, no forward fetch); only the strategy active-sets need OHLCV frames.
    print(f"  Loading precomputed features {_CSV} …")
    data = pd.read_csv(_CSV)
    data["date"] = pd.to_datetime(data["date"])
    csv_tickers = set(data["ticker"].unique())
    cached = cached_tickers("2y")
    pool = sorted(csv_tickers & cached)   # need OHLCV (strategy signals) AND feature rows
    if not pool:
        raise SystemExit("no overlap between cached OHLCV and feature CSV.")
    import random
    random.Random(seed).shuffle(pool)
    pool = sorted(pool[:n_tickers])
    data = data[data["ticker"].isin(pool)].copy()
    nifty_c, vix_c = _indices()
    gens = _gen_map()

    # ── Pass 1: collect every sample's feature row + metadata (strategy set, realized excursions).
    # Model inference is BATCHED afterwards (one _raw_predict call per TF over the whole matrix)
    # instead of one 7-estimator call per row — the row-by-row path is ~1000× slower.
    print(f"\n  Confluence swing study — {len(pool)} tickers · last {days} rows/ticker · "
          f"TFs {','.join(tfs)} · model cutoff {predictor.manifest.get('train_cutoff')}")
    feat_rows = []                      # list[np.ndarray]  (one per sample)
    meta = []                           # list[dict]  strats + realized up/dn per tf
    for ti, tk in enumerate(pool, 1):
        if ti % 25 == 0 or ti == len(pool):
            print(f"    … {ti}/{len(pool)} tickers  ({len(feat_rows)} rows collected)")
        sub = data[data["ticker"] == tk].sort_values("date")
        if days and days > 0:
            sub = sub.tail(days)
        if sub.empty:
            continue
        try:
            sc, sh, sl, sv = fetch_ohlcv(tk, "2y")
        except Exception:
            continue
        active = _active_by_pos(tk, sc, sh, sl, sv, nifty_c, vix_c, len(sc), gens)
        pos_of = {d: i for i, d in enumerate(sc.index)}
        feat_mat = sub[FEATURE_COLUMNS].values
        dates = sub["date"].values
        up_vals = {tf: sub[_UP[tf]].values for tf in tfs}
        dn_vals = {tf: sub[_DN[tf]].values for tf in tfs}
        dirc_vals = {tf: sub[_DIRC[tf]].values for tf in tfs}
        for ri in range(len(sub)):
            full_p = pos_of.get(pd.Timestamp(dates[ri]))
            strat_set = active[full_p] if full_p is not None else set()
            feat_rows.append(feat_mat[ri])
            meta.append({"strats": frozenset(strat_set),
                         "up": {tf: float(up_vals[tf][ri]) for tf in tfs},
                         "dn": {tf: float(dn_vals[tf][ri]) for tf in tfs},
                         "true_dir": {tf: str(dirc_vals[tf][ri]) for tf in tfs}})
    if not feat_rows:
        raise SystemExit("no samples collected.")

    # ── Pass 2: BATCH model inference per TF, then cheap pure-Python derivation + grading.
    X = np.asarray(feat_rows, dtype=float)
    print(f"    running batched inference on {len(X):,} rows × {len(tfs)} TFs …")
    rows = []  # {tf, strats:frozenset, dir, median}
    for tf in tfs:
        median_w = float(predictor.manifest.get("tf", {}).get(tf, {}).get("median_train_width", 1.5)) or 1.5
        q, proba_m, classes = predictor._raw_predict(tf, X)   # ONE batch call per TF
        for i, mrow in enumerate(meta):
            row_q = {k: float(v[i]) for k, v in q.items()}
            pr = predictor._derive(row_q, proba_m[i], classes, tf, 100.0, 1.5,
                                   median_w, None, None, 0, 100.0)
            if bullish_only and pr["direction"] != "BULLISH":
                continue
            g = _graded_hit(pr["direction"], 100.0, pr["target_price_lo"],
                            pr["target_price_hi"], mrow["up"][tf], mrow["dn"][tf])
            rows.append({"tf": tf, "strats": mrow["strats"],
                         "dir": pr["direction"],
                         "dir_correct": 1 if pr["direction"] == mrow["true_dir"][tf] else 0,
                         "median": 1 if g == "MIDPOINT_HIT" else 0})
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no samples collected.")
    _report(df, tfs, min_n, bullish_only)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_combo_swing.csv")
    df.assign(strats=df["strats"].apply(lambda s: "|".join(sorted(s)))).to_csv(out, index=False)
    print(f"\n  ✓ samples written → {out}")
    return df


def _report(df: pd.DataFrame, tfs, min_n: int, bullish_only: bool):
    scope = "ML-BULLISH calls only" if bullish_only else "ALL ML calls"
    print("\n" + "═" * 96)
    print(f"  STRATEGY CONFLUENCE FOR SWING TRADES — does co-firing lift the swing metrics? ({scope})")
    print("  DIR-ACC = predicted direction matched the realised move (the metric that's actually ~40-50%")
    print("  and worth improving). MID-HIT = band-midpoint reached (already ~90%, little headroom).")
    print("═" * 96)

    def bucket(n):
        return "0" if n == 0 else ("1" if n == 1 else ("2" if n == 2 else "3+"))

    for tf in tfs:
        t = df[df["tf"] == tf]
        if t.empty:
            continue
        base_dir = t["dir_correct"].mean()
        base_med = t["median"].mean()
        print(f"\n  ── {tf} ──   baseline DIR-ACC {base_dir:.0%}  |  MID-HIT {base_med:.0%}   (N={len(t):,})")

        t = t.assign(k=t["strats"].apply(lambda s: bucket(len(s))))
        print("     confluence count → DIR-ACC  (MID-HIT):")
        for kb in ["0", "1", "2", "3+"]:
            g = t[t["k"] == kb]
            if len(g):
                da, mh = g["dir_correct"].mean(), g["median"].mean()
                print(f"        {kb:<3} signals   N={len(g):>6,}   DIR-ACC {da:>4.0%}"
                      f"   lift {da - base_dir:>+4.0%}     (MID-HIT {mh:>4.0%})")

        # best PAIRS / TRIPLES ranked by directional accuracy (the improvable metric)
        _combo_table(t, 2, min_n, base_dir, "PAIRS")
        _combo_table(t, 3, min_n, base_dir, "TRIPLES")

    print("\n  Read: if DIR-ACC climbs from '1 signal' → '2' → '3+', confluence sharpens the swing")
    print("  DIRECTION call (the real edge). The best PAIRS/TRIPLES with enough N are the combos to trade.")


def _combo_table(t: pd.DataFrame, k: int, min_n: int, base: float, label: str):
    counts = defaultdict(lambda: [0, 0])  # combo → [dir-correct hits, n]
    for strats, dc in zip(t["strats"], t["dir_correct"]):
        if len(strats) < k:
            continue
        for combo in itertools.combinations(sorted(strats), k):
            c = counts[combo]
            c[0] += dc
            c[1] += 1
    scored = [(combo, hn[1], hn[0] / hn[1]) for combo, hn in counts.items() if hn[1] >= min_n]
    scored.sort(key=lambda r: r[2], reverse=True)
    print(f"     best {label} by DIR-ACC (min N={min_n}):")
    if not scored:
        print(f"        (no {k}-combo reached N={min_n} in this sample — widen --tickers/--days or lower --min-n)")
        return
    for combo, n, mh in scored[:8]:
        print(f"        {'+'.join(combo):<26} N={n:>5}   DIR-ACC {mh:>4.0%}   lift {mh - base:>+4.0%}"
              f"{'  ⟵' if mh - base > 0.08 else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=int, default=200, help="how many cached tickers to sample")
    ap.add_argument("--days", type=int, default=90, help="lookback trading days per ticker")
    ap.add_argument("--tfs", default="1D,3D", help="swing timeframes (subset of 1D,3D)")
    ap.add_argument("--min-n", type=int, default=30, help="min samples for a combo to be reported")
    ap.add_argument("--bullish-only", action="store_true", help="restrict to ML-BULLISH (swing-long) calls")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    tfs = [x.strip().upper() for x in args.tfs.split(",") if x.strip().upper() in _HORIZON]
    if not tfs:
        raise SystemExit("no valid --tfs (choose from 1D,3D)")
    run(args.tickers, args.days, tfs, args.min_n, args.bullish_only, args.seed)


if __name__ == "__main__":
    main()
