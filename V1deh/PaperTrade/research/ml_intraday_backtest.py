#!/usr/bin/env python3
"""research/ml_intraday_backtest.py — TRUE intraday backtest on 15-minute bars.

Unlike research/ml_backtest.py (daily bars, same-day proxy), this validates the INTRADAY
model the way it is actually used and the way you described:

  At each prediction time T ∈ {09:15, 12:00, 14:00 IST} on day D, predict using ONLY data
  available then — daily features through the PREVIOUS close (D-1) + the live price at T —
  then check, from the 15-minute bars, whether the predicted target was TOUCHED between T
  and 15:00 IST the same day. P&L enters at T, exits at target / stop / 15:00 close.

Data: 15-minute bars come from yfinance (interval="15m"), available ~60 days of history —
so this covers the last ~2 months only (the intrinsic limit on intraday history), but it is
a genuine FORWARD test, not the daily-OHLC proxy.

Usage:
    python research/ml_intraday_backtest.py                       # watchlist + sample universe
    python research/ml_intraday_backtest.py --tickers TATASTEEL.NS,SBIN.NS
    python research/ml_intraday_backtest.py --n-universe 40       # add N liquid names for power
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

from ml_predictor.features import compute_features, FEATURE_COLUMNS  # noqa: E402
from ml_predictor.infer import MLPredictor, intraday_session_scale  # noqa: E402
from research.ml_backtest import _graded_hit, _simulate_trade, ROUND_TRIP_COST_PCT  # noqa: E402

PRED_TIMES = ["09:15", "12:00", "14:00"]   # IST decision points
CLOSE_TIME = "15:00"                        # validate touches up to this bar (15:00 IST)
OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_intraday_results.csv")
_NEWS_CACHE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "news_asof.sqlite")
# 15-min bars come from yfinance which only serves ~60 days of rolling history, and the same
# ~60-day window is identical for the rest of the calendar day — so we cache one pickle per
# ticker per fetch-date under research/cache/intraday_15m/. Re-runs on the same day skip the
# (slow, ~2-3 min for 30 tickers) re-download entirely. Pass --refresh to force a fresh pull.
# (pickle, not parquet, so no pyarrow/fastparquet dependency is needed.)
_BAR_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "intraday_15m")


def _watchlist() -> list[str]:
    try:
        con = sqlite3.connect("file:%s?mode=ro" % os.path.join(_PROJ_ROOT, "paper_trading.db"), uri=True)
        rows = [r[0] for r in con.execute("SELECT ticker FROM watchlist").fetchall()]
        con.close()
        return rows
    except Exception:
        return []


def _sample_universe(n: int) -> list[str]:
    try:
        from universe import get_universe
        return list(get_universe().keys())[:n]
    except Exception:
        return []


def _fetch_15m(ticker: str, refresh: bool = False) -> pd.DataFrame | None:
    from datetime import date
    cache_path = os.path.join(_BAR_CACHE_DIR, f"{ticker}_{date.today().isoformat()}.pkl")
    if not refresh and os.path.exists(cache_path):
        try:
            return pd.read_pickle(cache_path)
        except Exception:
            pass  # corrupt/unreadable cache → fall through to re-download
    try:
        import yfinance as yf
        df = yf.download(ticker, period="60d", interval="15m", auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        idx = df.index
        df.index = idx.tz_convert("Asia/Kolkata") if idx.tz else idx.tz_localize("UTC").tz_convert("Asia/Kolkata")
        out = df[["Open", "High", "Low", "Close"]].dropna()
        try:
            os.makedirs(_BAR_CACHE_DIR, exist_ok=True)
            out.to_pickle(cache_path)
        except Exception:
            pass  # caching is best-effort; never fail the run over it
        return out
    except Exception:
        return None


def _dip_path_pnl(win: pd.DataFrame, entry: float, dip_pct: float, tp_pct: float,
                  stop_pct: float) -> tuple[float | None, bool]:
    """TRUE intraday dip-entry sim by walking 15-min bars in time order.

    Place a limit buy at the modeled dip (entry*(1+dip_pct/100)); it fills only if a bar's
    Low actually reaches it. After fill, the FIRST subsequent bar whose High hits the target
    (fill*(1+tp_pct/100)) is a win; whose Low hits the stop (fill*(1-stop_pct/100)) is a loss;
    otherwise exit at the 15:00 close. Returns (net_pnl_pct or None if never filled, filled).
    """
    dip_price = entry * (1 + dip_pct / 100.0)
    filled = False
    tgt = stop = fill_price = None
    for _, bar in win.iterrows():
        lo, hi = float(bar["Low"]), float(bar["High"])
        if not filled:
            if lo <= dip_price:                    # limit touched → fill at the limit price
                filled = True
                fill_price = dip_price
                tgt = fill_price * (1 + tp_pct / 100.0)
                stop = fill_price * (1 - stop_pct / 100.0)
                if lo <= stop:                     # same bar can resolve; stop-first (pessimistic)
                    return -stop_pct - ROUND_TRIP_COST_PCT, True
                if hi >= tgt:
                    return tp_pct - ROUND_TRIP_COST_PCT, True
            continue
        if lo <= stop:
            return -stop_pct - ROUND_TRIP_COST_PCT, True
        if hi >= tgt:
            return tp_pct - ROUND_TRIP_COST_PCT, True
    if filled:
        exit_ret = (float(win["Close"].iloc[-1]) / fill_price - 1) * 100.0
        return exit_ret - ROUND_TRIP_COST_PCT, True
    return None, False


def run(tickers: list[str], nifty_c, vix_c, use_scale: bool = True,
        news: bool = False, news_llm: bool = False, news_lookback: int = 7,
        names: dict | None = None, refresh: bool = False):
    predictor = MLPredictor()
    if not predictor.available:
        raise SystemExit("ml_predictor model not loaded — run ml_predictor/train.py first.")
    from data_sources import fetch_ohlcv
    names = names or {}
    if news:
        from news_sentiment import fetch_news_asof
        print(f"  News A/B ON — as-of company news, {news_lookback}d lookback, "
              f"{'LLM' if news_llm else 'keyword'} scorer, cache={_NEWS_CACHE_DB}")

    rows = []
    for tk in tickers:
        intr = _fetch_15m(tk, refresh=refresh)
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
            feat = compute_features(c, h, l, v, nifty_c, vix_c, date=prior[-1])  # features through D-1 close
            if feat is None:
                continue
            feat_row = [feat.get(k, float("nan")) for k in FEATURE_COLUMNS]
            atrp = feat.get("atr_pct")
            # As-of company news for this trading day (published strictly BEFORE `day`).
            news_score, news_label, news_n = 0, "", 0
            if news:
                try:
                    nz = fetch_news_asof(tk, names.get(tk, ""), str(day),
                                         lookback_days=news_lookback, use_llm=news_llm,
                                         cache_path=_NEWS_CACHE_DB)
                    news_score, news_label, news_n = int(nz.get("score", 0)), nz.get("label", ""), nz.get("n", 0)
                except Exception:
                    pass
            for T in PRED_TIMES:
                bar_T = g[g["t"] == T]
                if bar_T.empty:
                    continue
                entry = float(bar_T["Open"].iloc[0])       # price at time T
                if entry <= 0:
                    continue
                # forward window: bars from T (inclusive) through 15:00 IST
                win = g[(g["t"] >= T) & (g["t"] <= CLOSE_TIME)]
                if win.empty:
                    continue
                max_up = (float(win["High"].max()) / entry - 1) * 100
                min_down = (float(win["Low"].min()) / entry - 1) * 100
                close_ret = (float(win["Close"].iloc[-1]) / entry - 1) * 100
                atr14 = (atrp / 100 * entry) if (atrp and np.isfinite(atrp)) else None
                hh, mm = int(T[:2]), int(T[3:])
                scale = intraday_session_scale(hh * 60 + mm) if use_scale else 1.0
                pred = predictor._predict_tf(feat_row, "INTRADAY", entry, atr14,
                                             live_price=entry, today_high=None, news_score=0,
                                             anchor_close=entry, intraday_scale=scale)
                tlo = entry * (1 + pred["predicted_return_lo"] / 100)
                thi = entry * (1 + pred["predicted_return_hi"] / 100)
                grade = _graded_hit(pred["direction"], entry, tlo, thi, max_up, min_down)
                if pred["direction"] == "BULLISH":
                    dir_hit = max_up > 0
                elif pred["direction"] == "BEARISH":
                    dir_hit = min_down < 0
                else:
                    dir_hit = abs(close_ret) <= 0.9
                exp_ret = ((pred["expected_target_price"] or entry) / entry - 1) * 100
                # Expected-target hit = the HEADLINE estimate (median q50) actually touched.
                # This is the honest central metric — unlike the mechanical band-midpoint, whose
                # touch-rate is misleading for a right-skewed [q10,q90] interval.
                if pred["direction"] == "BULLISH":
                    exp_hit = max_up >= exp_ret
                elif pred["direction"] == "BEARISH":
                    exp_hit = min_down <= exp_ret
                else:
                    exp_hit = abs(close_ret) <= 0.9
                # Far-bound coverage = the reported ceiling is a genuine ~q90 (rarely exceeded).
                if pred["direction"] == "BULLISH":
                    far_cov = max_up <= pred["predicted_return_hi"]
                elif pred["direction"] == "BEARISH":
                    far_cov = min_down >= pred["predicted_return_lo"]
                else:
                    far_cov = True
                pnl = (_simulate_trade(exp_ret, pred["stop_loss_pct"], max_up, min_down, close_ret)
                       if pred["should_buy"] else None)
                # DIP-ENTRY: limit buy at the model's suggested dip (down_q50), true bar-walk fill.
                dip_pct = float(pred.get("quantiles", {}).get("down_q50", 0.0))
                dip_pnl, dip_filled = (
                    _dip_path_pnl(win, entry, dip_pct, exp_ret, pred["stop_loss_pct"])
                    if pred["should_buy"] else (None, False))
                row = {
                    "ticker": tk, "date": str(day), "pred_time": T,
                    "direction": pred["direction"], "confidence": pred["confidence"],
                    "entry": round(entry, 2), "ret_lo": pred["predicted_return_lo"],
                    "ret_hi": pred["predicted_return_hi"], "est_high_pct": round(exp_ret, 2),
                    "max_up": round(max_up, 2), "min_down": round(min_down, 2),
                    "close_ret": round(close_ret, 2),
                    "dir_hit": int(bool(dir_hit)),
                    "graded_hit": int(grade in ("MIDPOINT_HIT", "RANGE_HIT")),
                    "midpoint_hit": int(grade == "MIDPOINT_HIT"),
                    "exp_hit": int(bool(exp_hit)),
                    "far_cov": int(bool(far_cov)),
                    "should_buy": int(pred["should_buy"]),
                    "pnl": round(pnl, 3) if pnl is not None else None,
                    "dip_pnl": round(dip_pnl, 3) if dip_pnl is not None else None,
                    "dip_filled": int(dip_filled),
                    "dip_pct": round(dip_pct, 3),
                }
                if news:
                    # Re-derive WITH the news score → A/B the news-adjusted direction/confidence.
                    predn = predictor._predict_tf(feat_row, "INTRADAY", entry, atr14,
                                                  live_price=entry, today_high=None, news_score=news_score,
                                                  anchor_close=entry, intraday_scale=scale)
                    tlon = entry * (1 + predn["predicted_return_lo"] / 100)
                    thin = entry * (1 + predn["predicted_return_hi"] / 100)
                    graden = _graded_hit(predn["direction"], entry, tlon, thin, max_up, min_down)
                    if predn["direction"] == "BULLISH":
                        dir_hitn = max_up > 0
                    elif predn["direction"] == "BEARISH":
                        dir_hitn = min_down < 0
                    else:
                        dir_hitn = abs(close_ret) <= 0.9
                    row.update({
                        "news_score": news_score, "news_label": news_label, "news_n": news_n,
                        "direction_news": predn["direction"], "confidence_news": predn["confidence"],
                        "dir_hit_news": int(bool(dir_hitn)),
                        "graded_hit_news": int(graden in ("MIDPOINT_HIT", "RANGE_HIT")),
                    })
                rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("No intraday rows produced (15-min data unavailable?).")
    df.to_csv(OUT_CSV, index=False)
    _report(df, use_scale)
    print(f"\n  ✓ Wrote per-prediction detail → {OUT_CSV}")
    return df


def _report(df: pd.DataFrame, use_scale: bool = True):
    scale_note = "√time-scaled targets" if use_scale else "FULL-DAY targets (no scaling)"
    print("\n" + "=" * 84)
    print(f"  TRUE INTRADAY BACKTEST — 15-min bars, predict at T → touch by 15:00 IST · {scale_note}")
    print(f"  {df['ticker'].nunique()} tickers · {df['date'].nunique()} days · {len(df):,} predictions · "
          f"net {ROUND_TRIP_COST_PCT}% cost")
    print("=" * 84)
    print("  Column meaning (plain English):")
    print("    RightDir%   = we called up/down correctly")
    print("    ReachFloor% = stock reached our SAFE low target (very likely level)")
    print("    ReachMain%  = stock reached our MAIN 'best-guess' target")
    print("    UnderCeil%  = stock stayed BELOW our best-case top (rarely blown past)")
    print("    Win%        = of the buys taken, how many actually made money after fees")
    print("  " + "-" * 82)
    print(f"  {'time':<9}{'N':>6}{'RightDir%':>11}{'ReachFloor%':>13}{'ReachMain%':>12}"
          f"{'UnderCeil%':>12}{'#Buys':>7}{'BuyP&L':>9}{'Win%':>7}")
    print("  " + "-" * 82)
    for T in PRED_TIMES:
        t = df[df["pred_time"] == T]
        if t.empty:
            continue
        buys = t[t["pnl"].notna()]
        avg = buys["pnl"].mean() if len(buys) else float("nan")
        win = (buys["pnl"] > 0).mean() if len(buys) else float("nan")
        print(f"  {T:<9}{len(t):>6}{t['dir_hit'].mean():>11.0%}{t['graded_hit'].mean():>13.0%}"
              f"{t['exp_hit'].mean():>12.0%}{t['far_cov'].mean():>12.0%}{len(buys):>7}{avg:>+9.2f}{win:>7.0%}")
    allbuys = df[df["pnl"].notna()]
    print("\n  Direction mix:", dict(df["direction"].value_counts()))
    if len(allbuys):
        print(f"  Overall BUY (BULLISH) intraday trades: {len(allbuys)} · avg net P&L {allbuys['pnl'].mean():+.2f}% "
              f"· win {(allbuys['pnl'] > 0).mean():.0%}")
    # ── MARKET vs DIP entry (true 15-min bar-walk) ──────────────────────────
    if "dip_pnl" in df.columns and len(allbuys):
        dip = df[df["dip_filled"] == 1]
        n_sig = len(allbuys)
        print("\n  " + "-" * 76)
        print("  MARKET-ENTRY vs DIP-ENTRY (limit buy at model dip = down_q50; true bar-walk fill):")
        print(f"    MARKET: buys {n_sig}  win {(allbuys['pnl']>0).mean():.0%}  "
              f"avg/trade {allbuys['pnl'].mean():+.2f}%  avg/signal {allbuys['pnl'].mean():+.2f}%")
        if len(dip):
            fill_rate = len(dip) / n_sig
            exp_sig = dip["dip_pnl"].sum() / n_sig      # unfilled = 0 opportunity
            print(f"    DIP   : fills {len(dip)} ({fill_rate:.0%})  win {(dip['dip_pnl']>0).mean():.0%}  "
                  f"avg/fill {dip['dip_pnl'].mean():+.2f}%  avg/signal {exp_sig:+.2f}%")
            print("    → DIP raises win-rate on the trades it takes, but only fills a fraction;")
            print("      avg/signal is the honest deploy-all-capital number (misses count as 0).")
        else:
            print("    DIP   : never filled (model predicted no meaningful dip).")
    if "graded_hit_news" in df.columns:
        nz = df[df["news_n"] > 0]
        print("\n  " + "-" * 76)
        print(f"  NEWS A/B (rows WITH ≥1 as-of headline: {len(nz):,} of {len(df):,}):")
        print(f"    base : RightDir {df['dir_hit'].mean():.0%}  ReachFloor {df['graded_hit'].mean():.0%}")
        print(f"    +news: RightDir {df['dir_hit_news'].mean():.0%}  ReachFloor {df['graded_hit_news'].mean():.0%}  "
              f"(Δ {df['graded_hit_news'].mean()-df['graded_hit'].mean():+.1%})")
        if len(nz):
            print(f"    on news-bearing rows only — base ReachFloor {nz['graded_hit'].mean():.0%} → "
                  f"+news {nz['graded_hit_news'].mean():.0%} (Δ {nz['graded_hit_news'].mean()-nz['graded_hit'].mean():+.1%}); "
                  f"flips to NEUTRAL: {(nz['direction_news']!=nz['direction']).sum()}")
    print("  NOTE: features are as-of the PREVIOUS daily close (the current model is trained on")
    print("  same-day features, so this is a faithful *deployment* test, not a like-for-like one).")


def _name_map() -> dict:
    try:
        from universe import get_universe
        return get_universe()
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=None, help="comma-separated (default = watchlist + sample)")
    ap.add_argument("--n-universe", type=int, default=25, help="add N liquid universe names for power")
    ap.add_argument("--no-scale", action="store_true", help="disable √time target scaling (A/B baseline)")
    ap.add_argument("--news", action="store_true", help="A/B as-of company news adjustment")
    ap.add_argument("--news-llm", action="store_true", help="use the LLM news analyst (else keyword scorer)")
    ap.add_argument("--news-lookback", type=int, default=7, help="news window in days before each trading day")
    ap.add_argument("--refresh", action="store_true", help="ignore cached 15-min bars and re-download")
    args = ap.parse_args()
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",")]
    else:
        tickers = sorted(set(_watchlist()) | set(_sample_universe(args.n_universe)))
    print(f"  Intraday backtest on {len(tickers)} tickers…")
    try:
        import yfinance as yf
        raw = yf.download(["^NSEI", "^INDIAVIX"], period="1y", auto_adjust=True, progress=False)
        nifty_c, vix_c = raw["Close"]["^NSEI"].dropna(), raw["Close"]["^INDIAVIX"].dropna()
    except Exception:
        nifty_c = vix_c = None
    names = _name_map() if args.news else {}
    run(tickers, nifty_c, vix_c, use_scale=not args.no_scale,
        news=args.news, news_llm=args.news_llm, news_lookback=args.news_lookback,
        names=names, refresh=args.refresh)


if __name__ == "__main__":
    main()
