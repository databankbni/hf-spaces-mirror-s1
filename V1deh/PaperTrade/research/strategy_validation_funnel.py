#!/usr/bin/env python3
"""research/strategy_validation_funnel.py — apply the "9,120-backtest" doc's 6-filter
validation funnel to THIS project's strategy signals, and answer the doc's headline claim:
is MEAN REVERSION really the only category that survives out-of-sample?

For each strategy signal (S1..S20, S_CTRIO, MFS, NIRA, PED, …) this builds a simple
long-on-signal trade series from the cached OHLCV (enter at signal close, exit `--hold`
trading days later, minus round-trip cost), splits it chronologically into in-sample (IS)
and out-of-sample (OOS), then runs the doc's six filters:

  [01] OOS Sharpe > 0.5
  [02] max drawdown better than -35%
  [03] OOS Sharpe < 2.5           (not absurd / likely a bug)
  [04] OOS Sharpe <= IS*1.3 + 0.5 (anti-overfit)
  [05] >= --min-trades OOS trades
  [06] IS Sharpe > 0

Then it aggregates SURVIVAL RATE and MEAN OOS SHARPE **by category** and prints it next to
the doc's own funnel so you can compare directly.

Offline only (cached tickers); never imported by the production prediction path.

Usage:
    python research/strategy_validation_funnel.py                      # 300 tickers, 3-day hold
    python research/strategy_validation_funnel.py --tickers 500 --hold 5 --min-trades 30
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from data_sources import cached_tickers, fetch_ohlcv  # noqa: E402
from research.strategy_combo_swing import _gen_map, _indices  # noqa: E402

ROUND_TRIP_COST_PCT = 0.30
TRADING_DAYS = 252

# ── Category map (mirrors the doc's taxonomy) — classified from each signal's logic ──
CATEGORY = {
    # Mean reversion: oversold / dip / RSI-recovery / capitulation
    "S1": "MeanRev", "S4": "MeanRev", "S4V2": "MeanRev", "S5": "MeanRev", "S5V2": "MeanRev",
    "S6": "MeanRev", "S6V2": "MeanRev", "S7": "MeanRev", "S8": "MeanRev", "S10": "MeanRev",
    "S11": "MeanRev", "S16": "MeanRev", "S18": "MeanRev", "S_CAPFLOW": "MeanRev", "S_CTRIO": "MeanRev",
    # Trend / momentum: EMA-MACD-ADX, supertrend, breakout, gap-drift
    "S2": "Trend", "S3": "Trend", "NIRA": "Trend", "SUPER": "Trend", "S9": "Trend",
    "S14": "Trend", "S19": "Trend", "S20": "Trend", "PED": "Trend",
    # Composite multi-factor
    "MFS": "Composite",
    # Volatility compression (squeeze / NR7)
    "S15": "Volatility", "S17": "Volatility",
    # Seasonal (no doc equivalent — reported separately)
    "S_SEASONAL": "Seasonal", "S12": "Seasonal", "S13": "Seasonal",
}

# Doc's own funnel (for side-by-side comparison)
_DOC = {
    "MeanRev":    {"tested": 4080, "survived": 344, "rate": 8.4, "best": "Ultimate Osc 1.59"},
    "Trend":      {"tested": 3450, "survived": 108, "rate": 3.1, "best": "Turtle 1.18"},
    "Volume":     {"tested": 690,  "survived": 42,  "rate": 6.1, "best": "Money Flow Idx 1.02"},
    "Composite":  {"tested": 270,  "survived": 11,  "rate": 4.1, "best": "Triple Screen 0.97"},
    "Volatility": {"tested": 360,  "survived": 14,  "rate": 3.9, "best": "Squeeze Break 0.81"},
    "Pattern":    {"tested": 240,  "survived": 5,   "rate": 2.1, "best": "Three Bar Rev 0.75"},
}


def _sharpe(rets: list[float], hold: int) -> float:
    """Annualised Sharpe of a per-trade return series (each trade ≈ one `hold`-day sample)."""
    a = np.asarray(rets, dtype=float)
    if a.size < 2:
        return 0.0
    sd = a.std(ddof=1)
    if sd <= 1e-9:
        return 0.0
    return float(a.mean() / sd * np.sqrt(TRADING_DAYS / max(hold, 1)))


def _max_drawdown(rets_in_order: list[float]) -> float:
    """Max drawdown (%) of the equity curve from compounding trades in date order."""
    if not rets_in_order:
        return 0.0
    eq = np.cumprod([1 + r / 100.0 for r in rets_in_order])
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    return float(dd.min() * 100.0)


def run(n_tickers: int, hold: int, oos_frac: float, min_trades: int, seed: int):
    gens = _gen_map()
    nifty_c, vix_c = _indices()
    pool = sorted(cached_tickers("2y"))
    if not pool:
        raise SystemExit("no cached tickers — warm the OHLCV cache first.")
    import random
    random.Random(seed).shuffle(pool)
    pool = sorted(pool[:n_tickers])

    trades = defaultdict(list)   # strategy -> list[(date, ret_pct_net)]
    all_dates = []
    print(f"  Building long-on-signal trades — {len(pool)} tickers · {hold}-day hold · "
          f"cost {ROUND_TRIP_COST_PCT}% · {len(gens)} strategies")
    for ti, tk in enumerate(pool, 1):
        if ti % 50 == 0 or ti == len(pool):
            print(f"    … {ti}/{len(pool)} tickers")
        try:
            sc, sh, sl, sv = fetch_ohlcv(tk, "2y")
            c = sc[tk].dropna()
        except Exception:
            continue
        if len(c) < 260:
            continue
        pos = {d: i for i, d in enumerate(c.index)}
        cvals = c.values
        for name, fn in gens.items():
            try:
                sigs = fn(sc, sh, sl, sv, nifty_c, vix_c)
            except Exception:
                continue
            for d, t in sigs:
                i = pos.get(d)
                if i is None or i + hold >= len(cvals) or cvals[i] <= 0:
                    continue
                ret = (cvals[i + hold] / cvals[i] - 1.0) * 100.0 - ROUND_TRIP_COST_PCT
                trades[name].append((d, ret))
                all_dates.append(d)
    if not all_dates:
        raise SystemExit("no trades generated.")

    dmin, dmax = min(all_dates), max(all_dates)
    split = dmin + (dmax - dmin) * (1 - oos_frac)
    print(f"\n  Date span {pd.Timestamp(dmin).date()} → {pd.Timestamp(dmax).date()} · "
          f"IS < {pd.Timestamp(split).date()} ≤ OOS   (OOS = last {oos_frac:.0%})")

    rows = []
    cat_oos = defaultdict(list)   # category -> pooled OOS trade returns (trade-weighted)
    for name in gens:
        tl = sorted(trades.get(name, []), key=lambda x: x[0])
        is_r = [r for d, r in tl if d < split]
        oos_r = [r for d, r in tl if d >= split]
        cat_oos[CATEGORY.get(name, "Other")].extend(oos_r)
        is_s, oos_s = _sharpe(is_r, hold), _sharpe(oos_r, hold)
        mdd = _max_drawdown([r for d, r in tl if d >= split])
        n_oos = len(oos_r)
        f = {
            "01 OOS>0.5":  oos_s > 0.5,
            "02 DD>-35":   mdd > -35.0,
            "03 OOS<2.5":  oos_s < 2.5,
            "04 !overfit": oos_s <= is_s * 1.3 + 0.5,
            "05 N>=min":   n_oos >= min_trades,
            "06 IS>0":     is_s > 0,
        }
        survived = all(f.values())
        failed = [k for k, ok in f.items() if not ok]
        rows.append({
            "strategy": name, "category": CATEGORY.get(name, "Other"),
            "n_is": len(is_r), "n_oos": n_oos,
            "is_sharpe": round(is_s, 2), "oos_sharpe": round(oos_s, 2),
            "oos_winrate": round(100 * np.mean([r > 0 for r in oos_r]), 0) if oos_r else 0.0,
            "oos_mean_ret": round(float(np.mean(oos_r)), 2) if oos_r else 0.0,
            "max_dd": round(mdd, 1), "survived": survived,
            "first_fail": failed[0] if failed else "",
        })
    df = pd.DataFrame(rows).sort_values(["category", "oos_sharpe"], ascending=[True, False])
    _report(df, min_trades, cat_oos, hold)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy_validation_funnel.csv")
    df.to_csv(out, index=False)
    print(f"\n  ✓ per-strategy detail → {out}")
    return df


def _pooled(cat_oos: dict, hold: int):
    """Trade-weighted per-category stats: pool ALL OOS trades in a category into one series."""
    out = {}
    for cat, rets in cat_oos.items():
        if not rets:
            continue
        out[cat] = {"n": len(rets), "sharpe": _sharpe(rets, hold),
                    "win": 100 * np.mean([r > 0 for r in rets]),
                    "mean": float(np.mean(rets))}
    return out


def _report(df: pd.DataFrame, min_trades: int, cat_oos: dict, hold: int):
    print("\n" + "═" * 92)
    print("  STRATEGY VALIDATION FUNNEL — doc's 6 filters applied to THIS project's signals")
    print("═" * 92)
    print(f"  {'Strategy':<12}{'Category':<12}{'N_oos':>6}{'IS_Shp':>8}{'OOS_Shp':>9}"
          f"{'Win%':>6}{'MeanRet':>9}{'MaxDD':>8}  Verdict")
    print("  " + "-" * 88)
    for _, r in df.iterrows():
        verdict = "✓ SURVIVES" if r["survived"] else f"✗ {r['first_fail']}"
        print(f"  {r['strategy']:<12}{r['category']:<12}{int(r['n_oos']):>6}{r['is_sharpe']:>8.2f}"
              f"{r['oos_sharpe']:>9.2f}{r['oos_winrate']:>5.0f}%{r['oos_mean_ret']:>+9.2f}"
              f"{r['max_dd']:>7.1f}%  {verdict}")

    print("\n" + "═" * 92)
    print(f"  SURVIVAL BY CATEGORY  (our result  vs  the doc's 9,120-backtest funnel)")
    print("═" * 92)
    print(f"  {'Category':<12}{'Tested':>7}{'Surv':>6}{'Rate':>7}{'MeanOOS_Shp':>13}{'BestSurvivor':>22}"
          f"   | {'DocRate':>8}{'DocBest':>20}")
    print("  " + "-" * 108)
    order = ["MeanRev", "Trend", "Composite", "Volatility", "Seasonal", "Other"]
    cats = [c for c in order if c in set(df["category"])]
    for cat in cats:
        g = df[df["category"] == cat]
        tested = len(g)
        surv = int(g["survived"].sum())
        rate = 100 * surv / tested if tested else 0
        mean_oos = g["oos_sharpe"].mean()
        best = g.sort_values("oos_sharpe", ascending=False).iloc[0]
        best_lbl = f"{best['strategy']} {best['oos_sharpe']:.2f}"
        doc = _DOC.get(cat, {})
        doc_rate = f"{doc.get('rate', float('nan')):.1f}%" if doc else "—"
        doc_best = doc.get("best", "—")
        print(f"  {cat:<12}{tested:>7}{surv:>6}{rate:>6.0f}%{mean_oos:>13.2f}{best_lbl:>22}"
              f"   | {doc_rate:>8}{doc_best:>20}")

    # Headline comparison to the doc's claim (TRADE-WEIGHTED, robust to tiny-N strategies)
    pooled = _pooled(cat_oos, hold)
    print("\n  ── TRADE-WEIGHTED category OOS (pool every trade in the category into one series) ──")
    print(f"  {'Category':<12}{'N_trades':>9}{'OOS_Sharpe':>12}{'Win%':>7}{'MeanRet%':>10}")
    print("  " + "-" * 50)
    ranked = sorted(pooled.items(), key=lambda kv: kv[1]["sharpe"], reverse=True)
    for cat, s in ranked:
        print(f"  {cat:<12}{s['n']:>9,}{s['sharpe']:>+12.2f}{s['win']:>6.0f}%{s['mean']:>+10.2f}")

    top_cat = ranked[0][0] if ranked else ""
    mr = pooled.get("MeanRev", {}).get("sharpe", float("nan"))
    tr = pooled.get("Trend", {}).get("sharpe", float("nan"))
    print("\n  ── VERDICT vs the doc's claim (\"mean reversion is the only category that works OOS\") ──")
    if top_cat == "MeanRev":
        print(f"  → CONFIRMS the doc: MeanRev leads trade-weighted OOS Sharpe ({mr:+.2f} vs Trend {tr:+.2f}).")
    else:
        print(f"  → DIFFERS from the doc: '{top_cat}' leads here; MeanRev {mr:+.2f} vs Trend {tr:+.2f}.")
    print("  Doc tested US/crypto-style assets 2010-2025; this is NSE single-stock signals traded RAW")
    print("  (enter@signal, exit after hold, no stop/target/ML/AI gating). Not the deployed system.")
    print("  NOTE: point-in-time signals (no lookahead); calendar split. Low-N categories = low-confidence.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=int, default=300, help="cached tickers to sample")
    ap.add_argument("--hold", type=int, default=3, help="holding period in trading days")
    ap.add_argument("--oos-frac", type=float, default=0.30, help="fraction of the date span held out OOS")
    ap.add_argument("--min-trades", type=int, default=30, help="doc filter [05]: min OOS trades to survive")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    run(args.tickers, args.hold, args.oos_frac, args.min_trades, args.seed)


if __name__ == "__main__":
    main()
