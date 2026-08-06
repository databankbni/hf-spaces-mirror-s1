#!/usr/bin/env python3
"""research/ml_watchlist_eval.py — how did the ML model do on YOUR watchlist last week?

For each watchlist ticker and each of the last N trading days, it reconstructs the model's
point-in-time prediction (as if run that day, no lookahead), then grades it against the
REALIZED INTRADAY/1D/3D outcome and simulates the under-3-day trade P&L (net of cost).

Data comes straight from the OHLCV cache/fetch (covers watchlist names not in the training
universe). Horizons with insufficient forward bars (this-week's latest days) show as PENDING.

Usage:
    python research/ml_watchlist_eval.py                 # last 5 trading days
    python research/ml_watchlist_eval.py --days 7
    python research/ml_watchlist_eval.py --tickers TATASTEEL.NS,HINDZINC.NS
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import compute_features, FEATURE_COLUMNS, TIMEFRAMES  # noqa: E402
from ml_predictor.infer import MLPredictor  # noqa: E402
from research.ml_backtest import _graded_hit, _evaluate_intraday_hit, _simulate_trade, ROUND_TRIP_COST_PCT  # noqa: E402

_UP = {"INTRADAY": 0, "1D": 1, "3D": 3}


def _watchlist() -> list[str]:
    con = sqlite3.connect("file:%s?mode=ro" % os.path.join(_PROJ_ROOT, "paper_trading.db"), uri=True)
    try:
        return [r[0] for r in con.execute("SELECT ticker FROM watchlist ORDER BY ticker").fetchall()]
    finally:
        con.close()


def _indices():
    try:
        import yfinance as yf
        raw = yf.download(["^NSEI", "^INDIAVIX"], period="2y", auto_adjust=True, progress=False)
        return raw["Close"]["^NSEI"].dropna(), raw["Close"]["^INDIAVIX"].dropna()
    except Exception:
        return None, None


def _realized(c, h, l, idx: int, horizon: int):
    """(max_up%, min_down%, close_ret%) over `horizon` trading days after position idx.
    horizon 0 = entry day's own High/Low vs close (INTRADAY proxy). None if not enough bars."""
    p0 = float(c.iloc[idx])
    if p0 <= 0:
        return None
    if horizon == 0:
        return (float(h.iloc[idx]) / p0 - 1) * 100, (float(l.iloc[idx]) / p0 - 1) * 100, 0.0
    if idx + horizon >= len(c):
        return None
    hw = h.iloc[idx + 1: idx + horizon + 1]
    lw = l.iloc[idx + 1: idx + horizon + 1]
    ret = (float(c.iloc[idx + horizon]) / p0 - 1) * 100
    return (float(hw.max()) / p0 - 1) * 100, (float(lw.min()) / p0 - 1) * 100, ret


def run(tickers: list[str], days: int = 5):
    predictor = MLPredictor()
    if not predictor.available:
        raise SystemExit("ml_predictor model not loaded — run `python ml_predictor/train.py`.")
    from data_sources import fetch_ohlcv
    nifty_c, vix_c = _indices()

    rows = []
    print(f"  Evaluating {len(tickers)} watchlist tickers over the last {days} trading days "
          f"(model cutoff {predictor.manifest.get('train_cutoff')})…")
    for tk in tickers:
        try:
            sc, sh, sl, sv = fetch_ohlcv(tk, "2y")
            c, h, l, v = sc[tk].dropna(), sh[tk].dropna(), sl[tk].dropna(), sv[tk].dropna()
        except Exception as e:
            print(f"    ! {tk}: OHLCV unavailable ({e})")
            continue
        if len(c) < 210:
            print(f"    ! {tk}: too little history ({len(c)} bars)")
            continue
        for idx in range(len(c) - days, len(c)):
            date = c.index[idx]
            feat = compute_features(c, h, l, v, nifty_c, vix_c, date=date)
            if feat is None:
                continue
            feat_row = [feat.get(k, float("nan")) for k in FEATURE_COLUMNS]
            price = float(c.iloc[idx])
            atr14 = (feat["atr_pct"] / 100 * price) if np.isfinite(feat.get("atr_pct", np.nan)) else None
            for tf in TIMEFRAMES:
                pred = predictor._predict_tf(feat_row, tf, price, atr14, None, None, 0, anchor_close=price)
                real = _realized(c, h, l, idx, _UP[tf])
                rec = {"ticker": tk, "date": pd.Timestamp(date).strftime("%Y-%m-%d"), "tf": tf,
                       "direction": pred["direction"], "confidence": pred["confidence"],
                       "ret_lo": pred["predicted_return_lo"], "ret_hi": pred["predicted_return_hi"],
                       "buy": pred["buy_price_suggestion"], "stop_pct": pred["stop_loss_pct"],
                       "exp_ret": round(pred["expected_target_price"] - price, 2) if False else
                                  round((pred["expected_target_price"] / price - 1) * 100, 2)}
                if real is None:
                    rec.update({"status": "PENDING", "max_up": None, "min_dn": None, "ret": None,
                                "dir_hit": None, "graded": None, "pnl": None})
                else:
                    mu, md, rt = real
                    tlo = price * (1 + pred["predicted_return_lo"] / 100)
                    thi = price * (1 + pred["predicted_return_hi"] / 100)
                    dh, _ = _evaluate_intraday_hit(pred["direction"], price, tlo, thi, mu, md, tf, rt)
                    grade = _graded_hit(pred["direction"], price, tlo, thi, mu, md)
                    pnl = None
                    if pred["should_buy"]:
                        pnl = _simulate_trade(rec["exp_ret"], pred["stop_loss_pct"], mu, md, rt)
                    rec.update({"status": "DONE", "max_up": round(mu, 2), "min_dn": round(md, 2),
                                "ret": round(rt, 2), "dir_hit": int(bool(dh)),
                                "graded": int(grade in ("MIDPOINT_HIT", "RANGE_HIT")),
                                "pnl": round(pnl, 3) if pnl is not None else None})
                rows.append(rec)
    df = pd.DataFrame(rows)
    _report(df)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_watchlist_eval.csv")
    df.to_csv(out, index=False)
    print(f"\n  ✓ Wrote detail → {out}")
    return df


def _report(df: pd.DataFrame):
    done = df[df["status"] == "DONE"]
    print("\n" + "=" * 92)
    print("  WATCHLIST — last-week ML predictions vs realized outcome (under-3-day focus)")
    print("=" * 92)
    # Per-row detail (compact)
    show = df.copy()
    show["band"] = show.apply(lambda r: f"{r['ret_lo']:+.1f}..{r['ret_hi']:+.1f}%", axis=1)
    for tf in TIMEFRAMES:
        t = show[show["tf"] == tf]
        if t.empty:
            continue
        print(f"\n  ── {tf} ──")
        print(f"  {'ticker':<14}{'date':<12}{'dir':<9}{'conf':<8}{'band':<16}{'realized':<24}{'hit':<6}{'P&L%':>7}")
        for _, r in t.iterrows():
            if r["status"] == "PENDING":
                realized = "PENDING (no fwd bars)"
                hit = "-"; pnl = ""
            else:
                realized = f"up{r['max_up']:+.1f} dn{r['min_dn']:+.1f} close{r['ret']:+.1f}"
                hit = "HIT" if r["graded"] else "miss"
                pnl = f"{r['pnl']:+.2f}" if r["pnl"] is not None else "—"
            print(f"  {r['ticker']:<14}{r['date']:<12}{r['direction']:<9}{r['confidence']:<8}"
                  f"{r['band']:<16}{realized:<24}{hit:<6}{pnl:>7}")

    # Aggregate
    print("\n" + "-" * 60)
    print("  SUMMARY (graded rows only)")
    print(f"  {'TF':<9}{'N':>5}{'DirHit':>9}{'Graded':>9}{'#Buys':>7}{'Buy P&L(avg)':>14}{'Buy Win%':>10}")
    for tf in TIMEFRAMES:
        t = done[done["tf"] == tf]
        if t.empty:
            continue
        buys = t[t["pnl"].notna()]
        avg_pnl = buys["pnl"].mean() if len(buys) else float("nan")
        winr = (buys["pnl"] > 0).mean() if len(buys) else float("nan")
        print(f"  {tf:<9}{len(t):>5}{t['dir_hit'].mean():>9.0%}{t['graded'].mean():>9.0%}"
              f"{len(buys):>7}{avg_pnl:>+14.2f}{winr:>10.0%}")
    allbuys = done[done["pnl"].notna()]
    if len(allbuys):
        print(f"\n  Overall under-3-day BUY trades: {len(allbuys)} · avg net P&L {allbuys['pnl'].mean():+.2f}% "
              f"· win rate {(allbuys['pnl'] > 0).mean():.0%} · cost {ROUND_TRIP_COST_PCT}%/trade applied")
    npend = (df["status"] == "PENDING").sum()
    if npend:
        print(f"  ({npend} horizon-rows still PENDING — forward bars not available yet this week)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5, help="last N trading days to evaluate")
    ap.add_argument("--tickers", default=None, help="comma-separated override (default = DB watchlist)")
    args = ap.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else _watchlist()
    run(tickers, days=args.days)


if __name__ == "__main__":
    main()
