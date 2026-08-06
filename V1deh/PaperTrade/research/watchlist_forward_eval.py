#!/usr/bin/env python3
"""research/watchlist_forward_eval.py — PER-STOCK forward check on the watchlist.

For a single SELECTED DATE, this reconstructs the model's point-in-time prediction for every
watchlist ticker (no lookahead — features/strategies use only bars on/before that date), then
walks FORWARD over the real bars that followed and reports, PER STOCK, PER TIMEFRAME:

  • the prediction made that day (direction, confidence, range, expected/median target)
  • which STRATEGY signals (S1..S20, S_CTRIO, …) fired that day
  • each future date and the HIGH the stock actually printed that day
  • the single HIGHEST price the stock reached over the horizon (and the low)
  • FULL-RANGE hit  — did price reach the far (optimistic) bound of the range?
  • MEDIAN hit      — did price touch the expected/median target?
  • ENTERED-RANGE   — did price reach the near bound (enter the band at all)?
  • DIRECTION hit   — did it move the predicted way?

Nothing is aggregated into a single blended accuracy — every stock is printed on its own.
A short, clearly-separated STRATEGY-LIFT diagnostic at the end answers the second question
("which strategies can be added to raise confidence and price-hit") by comparing, over a
lookback window, the median-hit rate of ML-alone vs ML when a strategy also fired.

Usage:
    python research/watchlist_forward_eval.py                       # auto-picks a date 6 trading days back
    python research/watchlist_forward_eval.py --date 2026-07-15
    python research/watchlist_forward_eval.py --tickers TATASTEEL.NS,HINDZINC.NS --date 2026-07-15
    python research/watchlist_forward_eval.py --date 2026-07-15 --tfs 1D,3D
    python research/watchlist_forward_eval.py --date 2026-07-15 --lift-days 40   # widen strategy-lift sample
    python research/watchlist_forward_eval.py --no-lift                          # skip the strategy diagnostic
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import FEATURE_COLUMNS, TIMEFRAMES, compute_features  # noqa: E402
from ml_predictor.infer import MLPredictor  # noqa: E402
from predictor_core import run_strategy_signals  # noqa: E402

# horizon in forward trading days per TF (0 == same-day intraday proxy: entry day's own H/L)
_HORIZON = {"INTRADAY": 0, "1D": 1, "3D": 3}
_NEUTRAL_CAP = {"INTRADAY": 0.90, "1D": 1.0, "3D": 1.0}  # |close move| under which NEUTRAL "holds"


# ── data helpers ──────────────────────────────────────────────────────────────
def _watchlist() -> list[str]:
    db = os.path.join(_PROJ_ROOT, "paper_trading.db")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
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


def _resolve_idx(index: pd.DatetimeIndex, sel: pd.Timestamp) -> int | None:
    """Position of the last trading bar on/before `sel`."""
    pos = index.searchsorted(sel, side="right") - 1
    return int(pos) if pos >= 0 else None


def _forward(c, h, l, idx: int, horizon: int):
    """Return (dates, highs, lows, p0) for the forward window, or None if not enough bars.
    horizon 0 → the entry day's own bar (INTRADAY same-day proxy)."""
    p0 = float(c.iloc[idx])
    if p0 <= 0:
        return None
    if horizon == 0:
        return [c.index[idx]], [float(h.iloc[idx])], [float(l.iloc[idx])], p0
    if idx + horizon >= len(c):
        return None
    js = range(idx + 1, idx + horizon + 1)
    return ([c.index[j] for j in js], [float(h.iloc[j]) for j in js], [float(l.iloc[j]) for j in js], p0)


def _hits(pred: dict, tf: str, p0: float, highs, lows, close_ret_pct: float) -> dict:
    """Compute entered-range / median / full-range / direction hits from actual forward H/L."""
    d = (pred.get("direction") or "NEUTRAL").upper()
    hi = max(highs)
    lo = min(lows)
    tp_lo = pred["target_price_lo"]      # BULLISH: near ; BEARISH: deep(far)
    tp_hi = pred["target_price_hi"]      # BULLISH: far  ; BEARISH: shallow(near)
    exp = pred.get("expected_target_price")
    if d == "BULLISH":
        entered = hi >= tp_lo
        full = hi >= tp_hi
        median = (exp is not None) and (hi >= exp)
        direction = hi > p0
    elif d == "BEARISH":
        entered = lo <= tp_hi
        full = lo <= tp_lo
        median = (exp is not None) and (lo <= exp)
        direction = lo < p0
    else:  # NEUTRAL / range-bound — "hit" == it actually stayed in the band
        cap = _NEUTRAL_CAP.get(tf, 1.0)
        held = abs(close_ret_pct) <= cap
        entered = held
        full = held
        median = held
        direction = held
    return {"entered": bool(entered), "median": bool(median), "full": bool(full),
            "direction": bool(direction), "high": hi, "low": lo}


def _strategies_on(ticker, sc, sh, sl, sv, nifty_c, vix_c, idx: int) -> list[str]:
    """Strategy signals that fired within the last 5 bars ending at `idx` (point-in-time)."""
    end = idx + 1
    try:
        res = run_strategy_signals(ticker, sc.iloc[:end], sh.iloc[:end], sl.iloc[:end],
                                   sv.iloc[:end], nifty_c, vix_c=vix_c)
        return res.get("active", [])
    except Exception:
        return []


# ── core ──────────────────────────────────────────────────────────────────────
def run(tickers, sel_date: pd.Timestamp, tfs, lift_days: int, do_lift: bool, lift_only: bool = False):
    predictor = MLPredictor()
    if not predictor.available:
        raise SystemExit("ml_predictor model not loaded — run `python ml_predictor/train.py` first.")
    from data_sources import fetch_ohlcv
    nifty_c, vix_c = _indices()
    cutoff = predictor.manifest.get("train_cutoff")

    rows = []            # CSV rows (detail at the selected date)
    lift_rows = []       # (tf, strat_fired_set, ml_dir, ml_conf, median_hit) over the lookback window

    print("\n" + "═" * 96)
    mode = "STRATEGY-LIFT ONLY" if lift_only else "per-stock detail + lift"
    print(f"  WATCHLIST FORWARD CHECK — prediction date {sel_date.date()}  ·  "
          f"{len(tickers)} tickers  ·  model cutoff {cutoff}  ·  {mode}")
    if not lift_only:
        print("  (every stock shown individually — no blended accuracy number)")
    print("═" * 96)

    done_n = 0
    for tk in tickers:
        done_n += 1
        if lift_only and (done_n % 10 == 0 or done_n == len(tickers)):
            print(f"    … sampled {done_n}/{len(tickers)} tickers")
        try:
            sc, sh, sl, sv = fetch_ohlcv(tk, "2y")
            c, h, l, v = sc[tk].dropna(), sh[tk].dropna(), sl[tk].dropna(), sv[tk].dropna()
        except Exception as e:
            print(f"\n  {tk:<14} ! OHLCV unavailable ({e})")
            continue
        if len(c) < 210:
            print(f"\n  {tk:<14} ! too little history ({len(c)} bars)")
            continue

        idx = _resolve_idx(c.index, sel_date)
        if idx is None:
            print(f"\n  {tk:<14} ! selected date precedes available history")
            continue

        eff_date = c.index[idx]
        price = float(c.iloc[idx])
        feat = compute_features(c, h, l, v, nifty_c, vix_c, date=eff_date)
        if feat is None:
            print(f"\n  {tk:<14} ! features unavailable at {eff_date.date()}")
            continue
        feat_row = [feat.get(k, float("nan")) for k in FEATURE_COLUMNS]
        atr14 = (feat["atr_pct"] / 100 * price) if np.isfinite(feat.get("atr_pct", np.nan)) else None
        active = _strategies_on(tk, sc, sh, sl, sv, nifty_c, vix_c, idx)

        # ── header per stock (skipped in lift-only mode) ──
        if not lift_only:
            note = "" if eff_date.normalize() == sel_date.normalize() else \
                f"  (nearest trading day ≤ {sel_date.date()})"
            print("\n" + "─" * 96)
            print(f"  {tk:<14} @ {eff_date.date()}{note}   entry ₹{price:,.2f}")
            print(f"     strategies firing: {', '.join(active) if active else '(none)'}"
                  f"   [{len(active)} active]")

        for tf in ([] if lift_only else tfs):
            hz = _HORIZON[tf]
            pred = predictor._predict_tf(feat_row, tf, price, atr14, None, None, 0, anchor_close=price)
            d = pred["direction"]
            conf = pred["confidence"]
            p = pred.get("confidence_prob")
            basis = pred.get("dir_basis", "absolute")
            band = f"₹{pred['target_price_lo']:,.2f} … ₹{pred['target_price_hi']:,.2f}  " \
                   f"({pred['predicted_return_lo']:+.2f}% … {pred['predicted_return_hi']:+.2f}%)"
            exp = pred.get("expected_target_price")
            exp_s = f"₹{exp:,.2f}" if exp is not None else "— (range-bound)"
            basis_tag = " vs Nifty" if basis == "vs_nifty" else ""

            print(f"     ── {tf} ──  ML {d}{basis_tag}  ·  conf {conf}"
                  f"{f' (p={p:.2f})' if p is not None else ''}")
            print(f"         range   {band}")
            print(f"         expected/median target  {exp_s}")

            fwd = _forward(c, h, l, idx, hz)
            if fwd is None:
                print("         forward: PENDING — not enough bars after the selected date yet")
                rows.append({"ticker": tk, "date": str(eff_date.date()), "tf": tf, "direction": d,
                             "confidence": conf, "conf_prob": p, "dir_basis": basis,
                             "ret_lo": pred["predicted_return_lo"], "ret_hi": pred["predicted_return_hi"],
                             "target_lo": pred["target_price_lo"], "target_hi": pred["target_price_hi"],
                             "expected_target": exp, "strategies": "|".join(active),
                             "status": "PENDING"})
                continue

            dates, highs, lows, p0 = fwd
            close_ret = (float(c.iloc[idx + hz]) / p0 - 1) * 100 if hz > 0 else 0.0
            hit = _hits(pred, tf, p0, highs, lows, close_ret)
            hi_px, hi_i = max(zip(highs, range(len(highs))))
            hi_date = dates[hi_i]

            # per future day
            print("         forward days (actual):")
            for dt, hh, ll in zip(dates, highs, lows):
                mv = (hh / p0 - 1) * 100
                print(f"            {pd.Timestamp(dt).date()}   high ₹{hh:,.2f} ({mv:+.2f}%)   "
                      f"low ₹{ll:,.2f} ({(ll / p0 - 1) * 100:+.2f}%)")
            print(f"         highest reached  ₹{hit['high']:,.2f} ({(hit['high'] / p0 - 1) * 100:+.2f}%) "
                  f"on {pd.Timestamp(hi_date).date()}   ·   lowest ₹{hit['low']:,.2f} "
                  f"({(hit['low'] / p0 - 1) * 100:+.2f}%)")
            mk = lambda b: "✓" if b else "✗"
            print(f"         → entered-range {mk(hit['entered'])}   median-hit {mk(hit['median'])}   "
                  f"full-range {mk(hit['full'])}   direction {mk(hit['direction'])}")

            rows.append({"ticker": tk, "date": str(eff_date.date()), "tf": tf, "direction": d,
                         "confidence": conf, "conf_prob": p, "dir_basis": basis,
                         "ret_lo": pred["predicted_return_lo"], "ret_hi": pred["predicted_return_hi"],
                         "target_lo": pred["target_price_lo"], "target_hi": pred["target_price_hi"],
                         "expected_target": exp, "strategies": "|".join(active),
                         "highest_price": round(hit["high"], 2), "highest_date": str(pd.Timestamp(hi_date).date()),
                         "lowest_price": round(hit["low"], 2),
                         "entered_range": int(hit["entered"]), "median_hit": int(hit["median"]),
                         "full_range_hit": int(hit["full"]), "direction_hit": int(hit["direction"]),
                         "status": "DONE"})

        # ── strategy-lift sampling over a lookback window (per this stock) ──
        if do_lift:
            start = max(210, idx - lift_days + 1)
            for j in range(start, idx + 1):
                dj = c.index[j]
                fj = compute_features(c, h, l, v, nifty_c, vix_c, date=dj)
                if fj is None:
                    continue
                frow = [fj.get(k, float("nan")) for k in FEATURE_COLUMNS]
                pj = float(c.iloc[j])
                aj = (fj["atr_pct"] / 100 * pj) if np.isfinite(fj.get("atr_pct", np.nan)) else None
                act_j = set(_strategies_on(tk, sc, sh, sl, sv, nifty_c, vix_c, j))
                for tf in tfs:
                    hz = _HORIZON[tf]
                    fwd = _forward(c, h, l, j, hz)
                    if fwd is None:
                        continue
                    pr = predictor._predict_tf(frow, tf, pj, aj, None, None, 0, anchor_close=pj)
                    _, hh, ll, p0 = fwd
                    cret = (float(c.iloc[j + hz]) / p0 - 1) * 100 if hz > 0 else 0.0
                    hit = _hits(pr, tf, p0, hh, ll, cret)
                    lift_rows.append({"tf": tf, "strats": act_j, "ml_dir": pr["direction"],
                                      "ml_conf": pr["confidence"], "median": int(hit["median"]),
                                      "entered": int(hit["entered"])})

    if not lift_only:
        _write_csv(rows)
    if do_lift and lift_rows:
        _strategy_lift(pd.DataFrame(lift_rows), tfs)
    return rows


def _write_csv(rows):
    if not rows:
        return
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist_forward_eval.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print("\n" + "─" * 96)
    print(f"  ✓ Per-stock detail written → {out}")


def _strategy_lift(df: pd.DataFrame, tfs):
    """Which strategies raise the MEDIAN-hit rate when they co-fire with the ML call?

    For each TF this compares ML-alone median-hit vs ML+strategy median-hit over the sampled
    lookback window. A positive 'lift' means: on the days that strategy fired, the model's
    median target was reached MORE often than its own baseline — i.e. adding that strategy as a
    confirmation gate would raise both the confidence you can place in the call and the hit rate.
    """
    print("\n" + "═" * 96)
    print("  STRATEGY-LIFT DIAGNOSTIC — which signals, added as a confirm gate, raise the median-hit rate")
    print("  (sampled point-in-time over the lookback window; lift = strat-day hit% − ML-baseline hit%)")
    print("═" * 96)
    # collect the strategy universe seen
    all_strats = sorted({s for row in df["strats"] for s in row})
    for tf in tfs:
        t = df[df["tf"] == tf]
        if t.empty:
            continue
        base = t["median"].mean()
        base_ent = t["entered"].mean()
        print(f"\n  ── {tf} ──   ML-baseline: median-hit {base:.0%}  ·  entered-range {base_ent:.0%}  "
              f"(N={len(t)})")
        print(f"     {'strategy':<12}{'#days':>7}{'median-hit':>13}{'lift':>9}{'entered':>10}")
        scored = []
        for s in all_strats:
            m = t[t["strats"].apply(lambda st: s in st)]
            if len(m) < 3:  # too few to be meaningful
                continue
            mh = m["median"].mean()
            scored.append((s, len(m), mh, mh - base, m["entered"].mean()))
        # sort by lift desc
        scored.sort(key=lambda r: r[3], reverse=True)
        if not scored:
            print("     (no strategy fired often enough over this window to measure)")
            continue
        for s, n, mh, lift, ent in scored:
            flag = "  ⟵ helps" if lift > 0.05 and n >= 4 else ""
            print(f"     {s:<12}{n:>7}{mh:>12.0%}{lift:>+9.0%}{ent:>10.0%}{flag}")
    print("\n  Read: a strategy with a clearly positive 'lift' and enough '#days' is a candidate to")
    print("  gate/upgrade the ML call on (raises confidence + price-hit). Zero/negative lift = the")
    print("  model already prices that signal in, so adding it changes nothing.")


def _universe_sample(n: int, seed: int = 7) -> list[str]:
    """A deterministic sample of the dynamic NSE universe (for broad strategy-lift validation)."""
    from universe import get_universe
    uni = sorted(get_universe().keys())
    if n >= len(uni):
        return uni
    import random
    random.Random(seed).shuffle(uni)
    return sorted(uni[:n])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="prediction date YYYY-MM-DD (default: ~6 trading days back)")
    ap.add_argument("--tickers", default=None, help="comma-separated override (default = DB watchlist)")
    ap.add_argument("--universe", type=int, default=0,
                    help="validate on a deterministic N-ticker sample of the NSE universe (implies --lift-only)")
    ap.add_argument("--tfs", default="INTRADAY,1D,3D", help="comma-separated subset of INTRADAY,1D,3D")
    ap.add_argument("--lift-days", type=int, default=30, help="lookback trading days for strategy-lift sampling")
    ap.add_argument("--no-lift", action="store_true", help="skip the strategy-lift diagnostic")
    ap.add_argument("--lift-only", action="store_true",
                    help="only compute the strategy-lift diagnostic (suppress per-stock detail)")
    args = ap.parse_args()

    if args.universe > 0:
        tickers = _universe_sample(args.universe)
        args.lift_only = True
    elif args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",")]
    else:
        tickers = _watchlist()
    if not tickers:
        raise SystemExit("watchlist is empty — pass --tickers or --universe N")
    tfs = [t.strip().upper() for t in args.tfs.split(",") if t.strip().upper() in TIMEFRAMES]
    if not tfs:
        raise SystemExit("no valid timeframes in --tfs")

    if args.date:
        sel = pd.Timestamp(args.date)
    else:
        # default: 6 calendar days back (≈ leaves forward bars for 3D). Resolved per-ticker to a bar.
        sel = pd.Timestamp.today().normalize() - pd.Timedelta(days=6)
        print(f"  (no --date given; using {sel.date()} so 1D/3D horizons have realized forward bars)")

    run(tickers, sel, tfs, args.lift_days, not args.no_lift, lift_only=args.lift_only)


if __name__ == "__main__":
    main()
