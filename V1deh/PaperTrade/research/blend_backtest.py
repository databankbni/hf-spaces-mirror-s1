#!/usr/bin/env python3
"""
research/blend_backtest.py — Does the LLM's OWN (tighter) range hit as well as the ATR band,
especially when the LLM is HIGH-confidence? Tests the user's "blend: use AI when confident,
else ATR band" idea with real LLM calls.

For each (ticker, date, tf) it runs the production fast-mode forecast and compares, against the
realized forward move:
  ATR band   — fc.target_price_lo/hi (what production shows)
  AI raw     — the LLM's own range (fc.raw_llm_return_lo/hi, before the ATR clamp)
Grades target_hit (favorable move reached the range) + graded_hit (range touched), split by
confidence (HIGH vs MEDIUM/LOW) so we can see if an AI-when-HIGH blend keeps the hit rate.

Run:  python research/blend_backtest.py
"""
from __future__ import annotations
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

from backtest import (fetch_data, _compute_indicators, _fwd_intraday_moves, _fwd_returns,
                      _vix_nifty_series, _simple_ml_prob)
from ai_forecast import get_ai_forecast
from experiment_features import ExperimentContextBuilder, ExperimentalConfig

_exp = ExperimentContextBuilder(ExperimentalConfig(enable_alt_sentiment=False, enable_fundamentals=False))

# Big array so we sweep many regimes/volatilities; env-overridable.
TICKERS = (os.getenv("BLEND_TICKERS") or
    "RELIANCE.NS,SBIN.NS,TATASTEEL.NS,DLF.NS,HINDALCO.NS,BEL.NS,AXISBANK.NS,MARUTI.NS,"
    "VEDL.NS,INFY.NS,TCS.NS,ICICIBANK.NS,ADANIENT.NS,JSWSTEEL.NS,SUNPHARMA.NS,LT.NS,"
    "ONGC.NS,COALINDIA.NS,PNB.NS,ASHOKLEY.NS,BANKBARODA.NS,TATAPOWER.NS,IRFC.NS,NMDC.NS"
).split(",")
DATA_START, DATA_END = "2024-06-01", "2026-07-17"
TEST_START = os.getenv("BLEND_TEST_START", "2026-01-01")
STEP = int(os.getenv("BLEND_STEP", "8"))
TFS = ["INTRADAY", "1D"]
PACE = float(os.getenv("BLEND_PACE_SECS", "1"))
MAX_FORECASTS = int(os.getenv("BLEND_MAX", "400"))
RESULTS_CSV = os.path.join(os.path.dirname(__file__), "blend_backtest_results.csv")


def _hit(direction, price, lo, hi, max_up, min_down, tf, ret_tf):
    """Return (midpoint_hit, range_entered) — did the favorable move reach the range midpoint /
    near bound. Same grading applied to both the ATR band and the AI raw range for a fair compare."""
    if not lo or not hi or price <= 0:
        return 0, 0
    lo_pct = (min(lo, hi) / price - 1) * 100
    hi_pct = (max(lo, hi) / price - 1) * 100
    mid_pct = ((lo + hi) / 2 / price - 1) * 100
    if direction == "BULLISH":
        near = lo_pct  # conservative (low) target for a long
        return int(max_up >= mid_pct), int(max_up >= near)
    else:  # BEARISH — favorable move is downward (min_down, negative)
        near = hi_pct  # shallow (high) target for a short
        return int(min_down <= mid_pct), int(min_down <= near)


def main():
    print(f"Fetching {len(TICKERS)} tickers …")
    sc, sh, sl, sv, nc, vc = fetch_data(TICKERS, DATA_START, DATA_END)
    nifty_ema200, vix_slope = _vix_nifty_series(nc, vc)
    ts = pd.Timestamp(TEST_START)

    rows = []
    n = 0
    for t in TICKERS:
        if t not in sc.columns:
            continue
        c = sc[t].dropna()
        for date in c.index[c.index >= ts][::STEP]:
            try:
                price = float(c.loc[:date].iloc[-1])
                inds = _compute_indicators(sc[t], sh[t], sl[t], sv[t], date)
                if not price or not inds.get("atr14"):
                    continue
                vix = float(vc.loc[:date].dropna().iloc[-1]); nif = float(nc.loc[:date].dropna().iloc[-1])
                nema = float(nifty_ema200.loc[:date].dropna().iloc[-1]); nok = nif > nema
                vdec = float(vix_slope.loc[:date].dropna().iloc[-1]) < 0
                r1, r3, r5 = _fwd_returns(sc, date, t)
                up0, dn0, up1, dn1, *_ = _fwd_intraday_moves(sc, sh, sl, date, t)
                mlp = _simple_ml_prob(sc[t], sv[t], date)
                i2 = c.index.searchsorted(date, side="right")
                ohlcv = pd.DataFrame({"High": sh[t].iloc[max(0,i2-20):i2].values,
                                      "Low": sl[t].iloc[max(0,i2-20):i2].values,
                                      "Close": sc[t].iloc[max(0,i2-20):i2].values,
                                      "Volume": sv[t].iloc[max(0,i2-20):i2].values}).dropna()
            except Exception:
                continue
            for tf in TFS:
                time.sleep(PACE)
                try:
                    fc = get_ai_forecast(
                        ticker=t, company=t.replace(".NS",""), tf_label=tf,
                        ml={"probability": mlp, "upgraded": mlp>0.62, "score": int(mlp*100), "features": {}},
                        nifty_ok=nok, macro_ok=(nok and vix<20), vix_level=vix,
                        news=_exp.build_news_bundle(t, t.replace(".NS","")),
                        current_price=price, indicators=inds, ohlcv_df=ohlcv, vix_declining=vdec,
                        _fast_mode=True, _tight_test_ranges=False,
                        _forecast_date=str(date.date()), _fast_fail_on_rate_limit=True,
                        _enable_backtest_openrouter=True,
                    )
                except Exception:
                    continue
                d = fc.get("direction", "NEUTRAL")
                if d not in ("BULLISH", "BEARISH"):
                    continue
                ret_tf = 0.0 if tf == "INTRADAY" else r1
                mx = up0 if tf == "INTRADAY" else up1
                mn = dn0 if tf == "INTRADAY" else dn1
                # ATR band (production)
                a_lo, a_hi = fc.get("target_price_lo",0.0), fc.get("target_price_hi",0.0)
                at_th, at_gr = _hit(d, price, a_lo, a_hi, mx, mn, tf, ret_tf)
                # AI raw range
                rlo, rhi = fc.get("raw_llm_return_lo"), fc.get("raw_llm_return_hi")
                if rlo is None or rhi is None:
                    continue
                ai_lo = round(price*(1+rlo/100),2); ai_hi = round(price*(1+rhi/100),2)
                ai_th, ai_gr = _hit(d, price, ai_lo, ai_hi, mx, mn, tf, ret_tf)
                rows.append(dict(date=str(date.date()), ticker=t, tf=tf, conf=fc.get("confidence","LOW"), dirn=d,
                                 src=fc.get("source",""),
                                 atr_w=round(abs(fc.get("predicted_return_hi",0)-fc.get("predicted_return_lo",0)),3),
                                 ai_w=round(abs(rhi-rlo),3),
                                 atr_th=at_th, atr_gr=at_gr, ai_th=ai_th, ai_gr=ai_gr))
                n += 1
                # Incremental CSV so a long/rate-limited run keeps whatever it captured.
                pd.DataFrame(rows).to_csv(RESULTS_CSV, index=False)
                if n % 10 == 0:
                    _c = pd.DataFrame(rows).conf.value_counts().to_dict()
                    print(f"  … {n} forecasts (conf {_c})", flush=True)
                if n >= MAX_FORECASTS:
                    print(f"  reached MAX_FORECASTS={MAX_FORECASTS}", flush=True)
                    break
            else:
                continue
            break
        else:
            continue
        break

    df = pd.DataFrame(rows)
    if df.empty:
        print("No directional forecasts captured (LLM unavailable?).")
        return
    print(f"\nDirectional forecasts: {len(df)}  |  confidence mix: {df.conf.value_counts().to_dict()}\n")

    def block(sub, label):
        if len(sub) < 3:
            print(f"{label:<26} n={len(sub):3d}  (too few)"); return
        print(f"{label:<26} n={len(sub):3d}  "
              f"ATR band: target_hit={sub.atr_th.mean()*100:3.0f}% graded={sub.atr_gr.mean()*100:3.0f}% w={sub.atr_w.mean():.2f}%  ||  "
              f"AI raw: target_hit={sub.ai_th.mean()*100:3.0f}% graded={sub.ai_gr.mean()*100:3.0f}% w={sub.ai_w.mean():.2f}%")

    print("=" * 110)
    block(df, "ALL")
    for tf in TFS:
        block(df[df.tf==tf], f"  {tf}")
    print("-" * 110)
    block(df[df.conf=="HIGH"], "HIGH confidence only")
    block(df[df.conf!="HIGH"], "MEDIUM/LOW confidence")
    print("=" * 110)
    print("\nBlend simulation (AI raw when HIGH-conf, ATR band otherwise):")
    blend_th = np.where(df.conf=="HIGH", df.ai_th, df.atr_th).mean()*100
    blend_gr = np.where(df.conf=="HIGH", df.ai_gr, df.atr_gr).mean()*100
    blend_w  = np.where(df.conf=="HIGH", df.ai_w,  df.atr_w ).mean()
    print(f"  BLEND       target_hit={blend_th:.0f}%  graded={blend_gr:.0f}%  avg width={blend_w:.2f}%")
    print(f"  ALL-ATR     target_hit={df.atr_th.mean()*100:.0f}%  graded={df.atr_gr.mean()*100:.0f}%  avg width={df.atr_w.mean():.2f}%")
    print(f"  ALL-AI-raw  target_hit={df.ai_th.mean()*100:.0f}%  graded={df.ai_gr.mean()*100:.0f}%  avg width={df.ai_w.mean():.2f}%")


if __name__ == "__main__":
    main()
