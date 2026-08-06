#!/usr/bin/env python3
"""research/dip_order_probe.py — PROTOTYPE: can the model learn "dip-before-high"?

Dip-entry (limit buy at the modeled pullback) only makes money if the intraday LOW
occurs BEFORE the HIGH — price dips first, then rallies. The production quantile model
predicts only MAGNITUDES (max up / max down excursion), never their ORDER, so dip-entry
today rests on an ordering the model cannot forecast.

This probe tests whether that ordering is *learnable*:
  1. From the cached 15-minute bars (the ONLY source of true intraday sequence, ~60 days),
     build a label   low_before_high = (time of session Low) < (time of session High)
     for each (ticker, day, prediction-time T), using bars in [T, 15:00 IST].
  2. Train a classifier on the SAME production features (as-of previous daily close) → the
     probability the dip precedes the high. Report out-of-time AUC vs the base rate.
  3. Back-test dip-entry three ways on the held-out dates and compare win-rate + expectancy:
       (a) MARKET entry, (b) UNCONDITIONAL dip entry, (c) dip entry ONLY when the model
       says P(dip-first) is high. If (c) > (b) > (a), the ordering head adds real value.

This is research only — NOT wired into production. It is inherently limited by the ~60-day
15-min history (small sample; a real feature would need a longer intraday archive).

Usage:
    python research/dip_order_probe.py --n-universe 40
    python research/dip_order_probe.py --tickers SBIN.NS,TATASTEEL.NS --prob-threshold 0.6
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import compute_features, FEATURE_COLUMNS  # noqa: E402
from ml_predictor.infer import MLPredictor, intraday_session_scale  # noqa: E402
from research.ml_intraday_backtest import (  # noqa: E402
    _fetch_15m, _watchlist, _sample_universe, _dip_path_pnl,
    PRED_TIMES, CLOSE_TIME, ROUND_TRIP_COST_PCT,
)

OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dip_order_probe.csv")


def _collect(tickers: list[str], nifty_c, vix_c) -> pd.DataFrame:
    """Walk cached 15-min bars → per (ticker, day, T): features, ordering label, trade outcomes."""
    from data_sources import fetch_ohlcv
    predictor = MLPredictor()
    if not predictor.available:
        raise SystemExit("ml_predictor model not loaded — run ml_predictor/train.py first.")
    rows = []
    for tk in tickers:
        intr = _fetch_15m(tk)
        if intr is None or intr.empty:
            continue
        try:
            sc, sh, sl, sv = fetch_ohlcv(tk, "2y")
            c, h, l, v = sc[tk].dropna(), sh[tk].dropna(), sl[tk].dropna(), sv[tk].dropna()
        except Exception:
            continue
        if len(c) < 210:
            continue
        intr["t"] = intr.index.strftime("%H:%M")
        intr["d"] = intr.index.date
        for day, g in intr.groupby("d"):
            day_ts = pd.Timestamp(day)
            prior = c.index[c.index < day_ts]
            if len(prior) < 210:
                continue
            feat = compute_features(c, h, l, v, nifty_c, vix_c, date=prior[-1])
            if feat is None:
                continue
            feat_row = [feat.get(k, float("nan")) for k in predictor.feature_columns]
            atrp = feat.get("atr_pct")
            for T in PRED_TIMES:
                bar_T = g[g["t"] == T]
                if bar_T.empty:
                    continue
                entry = float(bar_T["Open"].iloc[0])
                if entry <= 0:
                    continue
                win = g[(g["t"] >= T) & (g["t"] <= CLOSE_TIME)]
                if len(win) < 2:
                    continue
                # ── True ordering label: did the LOW precede the HIGH? ──
                low_time = win["Low"].idxmin()
                high_time = win["High"].idxmax()
                low_before_high = int(low_time < high_time)

                atr14 = (atrp / 100 * entry) if (atrp and np.isfinite(atrp)) else None
                hh, mm = int(T[:2]), int(T[3:])
                scale = intraday_session_scale(hh * 60 + mm)
                pred = predictor._predict_tf(feat_row, "INTRADAY", entry, atr14,
                                             live_price=entry, today_high=None, news_score=0,
                                             anchor_close=entry, intraday_scale=scale)
                exp_ret = (pred["expected_target_price"] / entry - 1) * 100.0
                dip_pct = float(pred.get("quantiles", {}).get("down_q50", 0.0))
                stop_pct = pred["stop_loss_pct"]

                # Market-entry outcome (win if target touched before stop, bar-walk).
                mkt_pnl, _ = _dip_path_pnl(win, entry, 0.0, exp_ret, stop_pct)  # dip=0 → fills at open
                dip_pnl, dip_filled = _dip_path_pnl(win, entry, dip_pct, exp_ret, stop_pct)

                row = {k: feat.get(k, float("nan")) for k in FEATURE_COLUMNS}
                row.update({
                    "ticker": tk, "date": str(day), "pred_time": T,
                    "direction": pred["direction"], "should_buy": int(pred["should_buy"]),
                    "low_before_high": low_before_high,
                    "mkt_pnl": mkt_pnl, "dip_pnl": dip_pnl, "dip_filled": int(dip_filled),
                })
                rows.append(row)
    return pd.DataFrame(rows)


def _win(x):
    x = x[~pd.isna(x)]
    return float((x > 0).mean()) if len(x) else float("nan")


def run(tickers: list[str], nifty_c, vix_c, prob_threshold: float = 0.55):
    df = _collect(tickers, nifty_c, vix_c)
    if df.empty:
        raise SystemExit("No rows produced (need cached 15-min bars — run ml_intraday_backtest first).")
    df.to_csv(OUT_CSV, index=False)
    dates = sorted(df["date"].unique())
    if len(dates) < 6:
        raise SystemExit(f"Only {len(dates)} distinct dates — too few for a time split.")
    cut = dates[int(len(dates) * 0.7)]
    train, test = df[df["date"] < cut], df[df["date"] >= cut]

    print("\n" + "=" * 82)
    print("  DIP-BEFORE-HIGH ORDERING PROBE — can the model learn intraday sequence?")
    print(f"  {df['ticker'].nunique()} tickers · {len(dates)} days · {len(df):,} rows "
          f"(train<{cut}: {len(train):,}, test≥{cut}: {len(test):,})")
    print("=" * 82)
    base_rate = df["low_before_high"].mean()
    print(f"  Base rate  P(low precedes high) = {base_rate:.0%}  (a coin-flip baseline)")

    # ── Train the ordering classifier on production features ──
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    Xtr = train[FEATURE_COLUMNS].to_numpy(float)
    ytr = train["low_before_high"].to_numpy(int)
    Xte = test[FEATURE_COLUMNS].to_numpy(float)
    yte = test["low_before_high"].to_numpy(int)
    auc = float("nan")
    p_te = np.full(len(test), base_rate)
    if len(np.unique(ytr)) == 2:
        clf = HistGradientBoostingClassifier(max_iter=300, max_leaf_nodes=31,
                                             learning_rate=0.06, l2_regularization=1.0,
                                             random_state=0)
        clf.fit(Xtr, ytr)
        p_te = clf.predict_proba(Xte)[:, 1]
        if len(np.unique(yte)) == 2:
            auc = roc_auc_score(yte, p_te)
    print(f"  Classifier out-of-time AUC = {auc:.3f}  "
          f"(0.50 = no skill, >0.55 = weak signal, >0.60 = usable)")

    # ── Compare entry strategies on the TEST slice (BULLISH long signals only) ──
    test = test.copy()
    test["p_dip_first"] = p_te
    buys = test[test["should_buy"] == 1]
    print(f"\n  ENTRY-STRATEGY COMPARISON on test BULLISH signals (n={len(buys)}):")
    print(f"    {'strategy':<34}{'#trades':>8}{'win%':>7}{'exp/sig%':>10}")
    print("    " + "-" * 59)
    # (a) market
    mk = buys["mkt_pnl"]
    print(f"    {'MARKET entry':<34}{mk.notna().sum():>8}{_win(mk):>7.0%}{mk.fillna(0).mean():>+10.2f}")
    # (b) unconditional dip
    dp = buys[buys["dip_filled"] == 1]["dip_pnl"]
    exp_sig_dip = buys["dip_pnl"].where(buys["dip_filled"] == 1).fillna(0).mean()
    print(f"    {'DIP entry (unconditional)':<34}{len(dp):>8}{_win(dp):>7.0%}{exp_sig_dip:>+10.2f}")
    # (c) conditional dip — only where model predicts dip-first
    cond = buys[(buys["dip_filled"] == 1) & (buys["p_dip_first"] >= prob_threshold)]["dip_pnl"]
    exp_sig_cond = buys["dip_pnl"].where(
        (buys["dip_filled"] == 1) & (buys["p_dip_first"] >= prob_threshold)).fillna(0).mean()
    print(f"    {f'DIP entry (P≥{prob_threshold:.2f} dip-first)':<34}{len(cond):>8}{_win(cond):>7.0%}{exp_sig_cond:>+10.2f}")
    print("\n  win% = of trades taken, how many profited. exp/sig = avg P&L per SIGNAL")
    print("  (unfilled/skipped = 0, so it reflects deploying capital across every signal).")
    print(f"\n  ✓ Wrote per-row probe data → {OUT_CSV}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=None, help="comma-separated (default = watchlist + sample)")
    ap.add_argument("--n-universe", type=int, default=40, help="add N liquid universe names")
    ap.add_argument("--prob-threshold", type=float, default=0.55,
                    help="min P(dip-first) to take a conditional dip trade")
    args = ap.parse_args()
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",")]
    else:
        tickers = sorted(set(_watchlist()) | set(_sample_universe(args.n_universe)))
    try:
        import yfinance as yf
        raw = yf.download(["^NSEI", "^INDIAVIX"], period="1y", auto_adjust=True, progress=False)
        nifty_c, vix_c = raw["Close"]["^NSEI"].dropna(), raw["Close"]["^INDIAVIX"].dropna()
    except Exception:
        nifty_c = vix_c = None
    run(tickers, nifty_c, vix_c, prob_threshold=args.prob_threshold)


if __name__ == "__main__":
    main()
