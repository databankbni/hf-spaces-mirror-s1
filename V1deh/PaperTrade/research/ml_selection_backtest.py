#!/usr/bin/env python3
"""research/ml_selection_backtest.py — "give it one day, can it pick winners?" backtest.

Answers the practical question: on a given day, if the ML model RANKS the universe and we
buy its top-N BULLISH picks, does the basket make money over the next 1 / 3 / 5 days —
net of costs, and does it beat just buying the whole market that day?

This is a stock-SELECTION / portfolio test (distinct from research/ml_backtest.py, which
measures per-prediction accuracy). It uses the trained 3D model to rank, then measures the
picks' REALIZED forward close-to-close returns straight from the OHLCV cache — including the
5-day horizon the model isn't trained on, so we can honestly see the 5-day outcome.

For each out-of-sample date:
  1. Predict every ticker with a row that day (batch), keep BULLISH picks.
  2. Rank by expected up-move (up_q50), tie-break by confidence; take top-N.
  3. Realized fwd return at 1/3/5 trading days for each pick, minus 0.30% round-trip cost.
  4. Basket return = equal-weight mean; baseline = equal-weight ALL stocks that day (market).

Usage:
    python research/ml_selection_backtest.py                 # top-10, all holdout dates
    python research/ml_selection_backtest.py --top 5 --step 2
    python research/ml_selection_backtest.py --date 2026-03-15   # inspect one day's picks
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

from ml_predictor.features import FEATURE_COLUMNS  # noqa: E402
from ml_predictor.infer import MLPredictor  # noqa: E402
from ml_predictor.dataset import _cached_tickers, _load_ticker, DEFAULT_STEP  # noqa: E402
from research.strategy_validation_funnel import _sharpe, _max_drawdown  # noqa: E402

DEFAULT_CSV = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data.csv")
OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_selection_results.csv")

ROUND_TRIP_COST_PCT = 0.30
HORIZONS = [1, 3, 5]
_CONF_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_SELECTOR_TF = "3D"   # use the longest-horizon model to rank for a multi-day hold


def _passes_filters(r, filters: set) -> bool:
    """Strategy/quality gates (the docs' 'Filter' stage) applied to a BULLISH candidate.
    Each is an AND gate computed from the features already in the row."""
    def g(k, d=float("nan")):
        v = r.get(k, d)
        return float(v) if v is not None else d
    if "trend" in filters:      # confirmed uptrend: above EMA50 AND EMA200
        if not (g("price_vs_ema50") > 0 and g("price_vs_ema200") > 0):
            return False
    if "momentum" in filters:   # positive momentum: MACD>0 AND 10-day return>0
        if not (g("macd_hist") > 0 and g("return_10d") > 0):
            return False
    if "adx" in filters:        # trending market only
        if not (g("adx14") > 20):
            return False
    if "trigger" in filters:    # ≥1 bullish strategy trigger fired (S-signal confirmation)
        if sum(g(f"trigger_T{n}", 0) for n in range(1, 8)) < 1:
            return False
    if "lowvol" in filters:     # avoid extreme-volatility small-caps (noise)
        v = g("atr_pct")
        if not (v == v and v <= 4.0):
            return False
    if "notob" in filters:      # not overbought
        if not (g("rsi14") < 70):
            return False
    return True


def _load_close_series() -> dict:
    """Preload every cached ticker's close Series (for realized forward returns)."""
    out = {}
    for tk in _cached_tickers():
        loaded = _load_ticker(tk)
        if loaded is not None:
            out[tk] = loaded[0].dropna()  # close series
    return out


def _fwd_ret(close: pd.Series, date: pd.Timestamp, h: int) -> float:
    """Close-to-close % return h trading days after `date` (NaN if not enough future bars)."""
    try:
        idx = close.index.searchsorted(pd.Timestamp(date))
        if idx >= len(close):
            return float("nan")
        p0 = float(close.iloc[idx])
        j = idx + h
        if j >= len(close) or p0 <= 0:
            return float("nan")
        return (float(close.iloc[j]) / p0 - 1.0) * 100.0
    except Exception:
        return float("nan")


def run(csv_path: str = DEFAULT_CSV, top_n: int = 10, step: int = 1,
        one_date: str | None = None, rank_mode: str = "expmove",
        min_conf: str = "LOW", filters: set | None = None,
        six_filter: bool = False) -> pd.DataFrame:
    filters = filters or set()
    predictor = MLPredictor()
    if not predictor.available:
        raise SystemExit("ml_predictor model not loaded — run `python ml_predictor/train.py` first.")

    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"])
    holdout_start = predictor.manifest.get("holdout_start")
    # --six-filter validates the ML SELECTOR itself through the doc's funnel, which needs an
    # in-sample (IS) leg too — so evaluate the FULL date range and split at holdout_start.
    if six_filter:
        oos = df.copy()
    else:
        oos = df[df["date"] >= pd.to_datetime(holdout_start)].copy() if holdout_start else df
    print(f"  Model: rank by {_SELECTOR_TF} BULLISH · mode={rank_mode} · min_conf={min_conf} · "
          f"filters={sorted(filters) or 'none'} · top-{top_n} picks/day · cost {ROUND_TRIP_COST_PCT}% round-trip")
    print(f"  Out-of-sample rows: {len(oos):,} · loading close series for realized fwd returns…")
    closes = _load_close_series()

    dates = sorted(oos["date"].unique())
    if one_date:
        dates = [pd.Timestamp(one_date)]
    else:
        dates = dates[::step]

    pick_rows = []          # per-pick detail
    day_rows = []           # per-day basket vs market
    for d in dates:
        day = oos[oos["date"] == d]
        if len(day) < top_n:
            continue
        X = day[FEATURE_COLUMNS].to_numpy(dtype=float)
        q, proba_m, classes = predictor._raw_predict(_SELECTOR_TF, X)
        median_w = float(predictor.manifest.get("tf", {}).get(_SELECTOR_TF, {}).get("median_train_width", 1.5)) or 1.5
        cand = []
        for i, (_, r) in enumerate(day.iterrows()):
            row_q = {k: float(v[i]) for k, v in q.items()}
            pred = predictor._derive(row_q, proba_m[i], classes, _SELECTOR_TF, price=100.0,
                                     atr14=float(r["atr_pct"]) if np.isfinite(r["atr_pct"]) else None,
                                     median_w=median_w, live_price=None, today_high=None,
                                     news_score=0, anchor_close=100.0)
            if pred["direction"] != "BULLISH":
                continue
            crank = _CONF_RANK.get(pred["confidence"], 3)
            if crank > _CONF_RANK.get(min_conf, 2):     # confidence filter
                continue
            if filters and not _passes_filters(r, filters):   # strategy/quality gates
                continue
            atrp = float(r["atr_pct"]) if np.isfinite(r["atr_pct"]) else 2.0
            up50 = row_q["up50"]
            proba = proba_m[i]
            bull_p = float(proba[list(classes).index("BULLISH")]) if "BULLISH" in classes else 0.0
            cand.append({"ticker": r["ticker"], "up50": up50, "crank": crank, "conf": pred["confidence"],
                         "atr_pct": max(atrp, 0.1), "bull_p": bull_p})
        if not cand:
            day_rows.append({"date": d.strftime("%Y-%m-%d"), "n_picks": 0})
            continue
        # Ranking strategy (higher score = picked first):
        if rank_mode == "riskadj":       # expected move per unit volatility (Sharpe-like)
            keyfn = lambda c: (-(c["up50"] / c["atr_pct"]), c["crank"])
        elif rank_mode == "conf":        # confidence first (bull prob), then expected move
            keyfn = lambda c: (c["crank"], -c["bull_p"], -c["up50"])
        else:                            # "expmove" (default): raw expected up-move
            keyfn = lambda c: (-c["up50"], c["crank"])
        cand.sort(key=keyfn)
        picks = [(c["ticker"], c["up50"], c["crank"], c["conf"]) for c in cand[:top_n]]

        # Realized forward returns (net of cost) for picks and for the whole market that day.
        basket = {h: [] for h in HORIZONS}
        for tk, up50, _, conf in picks:
            cs = closes.get(tk)
            rets = {h: (_fwd_ret(cs, d, h) - ROUND_TRIP_COST_PCT) if cs is not None else float("nan")
                    for h in HORIZONS}
            for h in HORIZONS:
                if not np.isnan(rets[h]):
                    basket[h].append(rets[h])
            pick_rows.append({"date": d.strftime("%Y-%m-%d"), "ticker": tk, "exp_up_q50": round(up50, 2),
                              "confidence": conf, **{f"ret_{h}d_net": round(rets[h], 3) for h in HORIZONS}})
        market = {h: [] for h in HORIZONS}
        for tk in day["ticker"]:
            cs = closes.get(tk)
            for h in HORIZONS:
                v = _fwd_ret(cs, d, h) - ROUND_TRIP_COST_PCT if cs is not None else float("nan")
                if not np.isnan(v):
                    market[h].append(v)

        row = {"date": d.strftime("%Y-%m-%d"), "n_picks": len(picks)}
        for h in HORIZONS:
            row[f"basket_{h}d"] = float(np.mean(basket[h])) if basket[h] else float("nan")
            row[f"market_{h}d"] = float(np.mean(market[h])) if market[h] else float("nan")
        day_rows.append(row)

    picks_df = pd.DataFrame(pick_rows)
    days_df = pd.DataFrame(day_rows)
    picks_df.to_csv(OUT_CSV, index=False)

    if one_date:
        _one_day_report(one_date, picks_df, days_df)
    else:
        _summary(days_df, picks_df, top_n)
    if six_filter and not one_date:
        _six_filter_verdict(days_df, pd.to_datetime(holdout_start) if holdout_start else None)
    print(f"\n  ✓ Wrote per-pick detail → {OUT_CSV}")
    return days_df


def _six_filter_verdict(days_df: pd.DataFrame, split):
    """Run the '9,120-backtest' doc's 6-filter funnel on the ML SELECTION basket itself.
    Treats each decision day's top-N basket 3-day return as one trade; splits IS/OOS at the
    model's holdout_start. NOTE: the OOS leg is only as long as the manifest holdout window —
    if that is a handful of days the verdict is directional, not conclusive."""
    HOLD = 3
    d = days_df.copy()
    d = d[d["n_picks"] > 0]
    d["_dt"] = pd.to_datetime(d["date"])
    col = "basket_3d"
    if split is None:
        is_r = []
        oos_r = list(d[col].dropna())
    else:
        is_r = list(d[d["_dt"] < split][col].dropna())
        oos_r = list(d[d["_dt"] >= split][col].dropna())
    is_s, oos_s = _sharpe(is_r, HOLD), _sharpe(oos_r, HOLD)
    mdd = _max_drawdown(oos_r)
    n_oos = len(oos_r)
    checks = [
        ("[01] OOS Sharpe > 0.5", oos_s > 0.5, f"{oos_s:+.2f}"),
        ("[02] Max DD better than -35%", mdd > -35.0, f"{mdd:.1f}%"),
        ("[03] OOS Sharpe < 2.5 (not absurd)", oos_s < 2.5, f"{oos_s:+.2f}"),
        ("[04] OOS <= IS*1.3 + 0.5 (not overfit)", oos_s <= is_s * 1.3 + 0.5, f"OOS {oos_s:+.2f} / IS {is_s:+.2f}"),
        ("[05] At least 30 OOS trades", n_oos >= 30, f"{n_oos}"),
        ("[06] IS Sharpe > 0", is_s > 0, f"{is_s:+.2f}"),
    ]
    print("\n" + "=" * 78)
    print("  6-FILTER VALIDATION — is the ML top-N SELECTION strategy a real OOS edge?")
    print(f"  IS trades={len(is_r)}  OOS trades={n_oos}  (3-day basket return per decision day)")
    print("=" * 78)
    for label, ok, val in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<42} {val}")
    verdict = "SURVIVES all 6 filters" if all(c[1] for c in checks) else "does NOT survive"
    print(f"\n  → The ML selection strategy {verdict}.")
    if n_oos < 30:
        print("  ⚠ OOS window is short (manifest holdout is small) — treat as directional only.")


def _summary(days_df: pd.DataFrame, picks_df: pd.DataFrame, top_n: int):
    active = days_df[days_df["n_picks"] > 0]
    print("\n" + "=" * 78)
    print(f"  STOCK-SELECTION BACKTEST — top-{top_n} BULLISH picks, equal-weight, held N days")
    print(f"  {len(active)} decision days · {len(picks_df):,} total picks · net of {ROUND_TRIP_COST_PCT}% cost")
    print("=" * 78)
    print(f"  {'Hold':<7}{'BasketAvg':>11}{'MarketAvg':>11}{'Edge':>9}{'PickWin%':>10}{'DaysBeatMkt':>13}{'BookRet':>9}")
    print("  " + "-" * 70)
    for h in HORIZONS:
        b = active[f"basket_{h}d"].dropna()
        m = active[f"market_{h}d"].dropna()
        pick_win = float((picks_df[f"ret_{h}d_net"] > 0).mean()) if len(picks_df) else float("nan")
        beat = float((active[f"basket_{h}d"] > active[f"market_{h}d"]).mean())
        # Equal-weight daily-rebalanced book return: compound each day's basket mean across days.
        book = 1.0
        for v in active[f"basket_{h}d"].dropna():
            book *= (1 + v / 100.0)
        book_ret = (book - 1) * 100.0
        print(f"  {str(h)+'d':<7}{b.mean():>+11.2f}{m.mean():>+11.2f}{(b.mean()-m.mean()):>+9.2f}"
              f"{pick_win:>10.0%}{beat:>13.0%}{book_ret:>+9.1f}")
    print("\n  BasketAvg/MarketAvg = mean per-pick vs per-stock net return over the hold.")
    print("  Edge = how much the picks beat buying the whole market. PickWin% = picks that closed green.")
    print("  DaysBeatMkt = fraction of decision days the basket beat the market.")
    print(f"  BookRet compounds each day's top-{top_n} basket across all decision days (rebalanced).")
    # Direct answer to the 5-day question
    b5 = active["basket_5d"].dropna()
    m5 = active["market_5d"].dropna()
    win5 = float((picks_df["ret_5d_net"] > 0).mean()) if len(picks_df) else float("nan")
    verdict = "YES" if (b5.mean() > 0 and b5.mean() > m5.mean()) else ("MARGINAL" if b5.mean() > 0 else "NO")
    print("\n  ── 5-DAY VERDICT ──")
    print(f"  Avg pick makes {b5.mean():+.2f}% over 5 days (net) vs market {m5.mean():+.2f}% · "
          f"{win5:.0%} of picks close green · edge {b5.mean()-m5.mean():+.2f}%  →  profitable? {verdict}")


def _one_day_report(date: str, picks_df: pd.DataFrame, days_df: pd.DataFrame):
    print("\n" + "=" * 78)
    print(f"  SINGLE-DAY PICKS — {date}")
    print("=" * 78)
    if picks_df.empty:
        print("  No BULLISH picks that day.")
        return
    cols = ["ticker", "confidence", "exp_up_q50", "ret_1d_net", "ret_3d_net", "ret_5d_net"]
    print(picks_df[cols].to_string(index=False))
    if not days_df.empty and days_df.iloc[0].get("n_picks", 0) > 0:
        r = days_df.iloc[0]
        print(f"\n  Basket avg — 1d {r['basket_1d']:+.2f}%  3d {r['basket_3d']:+.2f}%  5d {r['basket_5d']:+.2f}%  "
              f"(net) vs market 5d {r['market_5d']:+.2f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--step", type=int, default=1, help="sample every Nth decision day")
    ap.add_argument("--date", default=None, help="inspect a single date (YYYY-MM-DD)")
    ap.add_argument("--rank", default="expmove", choices=["expmove", "riskadj", "conf"],
                    help="ranking strategy for picks")
    ap.add_argument("--min-conf", default="LOW", choices=["LOW", "MEDIUM", "HIGH"],
                    help="only pick stocks at/above this confidence")
    ap.add_argument("--filters", default="", help="comma-separated quality gates: "
                    "trend,momentum,adx,trigger,lowvol,notob")
    ap.add_argument("--six-filter", action="store_true",
                    help="validate the ML selection basket through the doc's 6-filter funnel (IS vs OOS)")
    args = ap.parse_args()
    filters = {f.strip() for f in args.filters.split(",") if f.strip()}
    run(args.csv, top_n=args.top, step=args.step, one_date=args.date,
        rank_mode=args.rank, min_conf=args.min_conf, filters=filters,
        six_filter=args.six_filter)


if __name__ == "__main__":
    main()
