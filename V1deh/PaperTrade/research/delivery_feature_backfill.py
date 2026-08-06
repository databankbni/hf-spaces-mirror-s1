#!/usr/bin/env python3
"""research/delivery_feature_backfill.py — does per-stock DELIVERY % lift the model?

Delivery % (DELIV_PER in NSE's sec_bhavdata_full bhavcopy) = fraction of traded volume that
actually changed hands as delivery vs intraday churn. High delivery = conviction/accumulation,
low = speculative. Unlike VIX / Nifty / sector (market-wide, already in the model), this is a
genuine PER-STOCK, per-day signal — the kind that could actually add edge.

This backfills delivery % from the NSE archive (cached locally), builds per-stock features
(raw level, 20-day z-score, 5-day change), merges them into training_data_extra.csv over an
N-month window, and A/B-tests dir_3D accuracy + the top-5 selection edge WITH vs WITHOUT them.

Research only; never touches the production model. Cache: research/cache/deliv/.

Usage:
    python research/delivery_feature_backfill.py                    # last 8 months, 6-mo train/2-mo OOS
    python research/delivery_feature_backfill.py --months 8 --holdout-months 2
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import FEATURE_COLUMNS  # noqa: E402

_CSV = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data_extra.csv")
_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "deliv")
os.makedirs(_CACHE, exist_ok=True)
COST = 0.30
TRADING_DAYS = 252
HOLD = 3
_DELIV_FEATS = ["deliv_per", "deliv_z20", "deliv_chg5"]

_H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36", "Accept": "text/csv,*/*",
      "Accept-Language": "en-US,en"}


def _fetch_bhav(session, dt: pd.Timestamp) -> pd.DataFrame | None:
    d = dt.strftime("%d%m%Y")
    cache = os.path.join(_CACHE, f"sec_{d}.csv")
    if os.path.exists(cache):
        try:
            df = pd.read_csv(cache)
        except Exception:
            df = None
        if df is not None and len(df):
            return df
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
    try:
        r = session.get(url, timeout=25)
        if r.status_code != 200 or len(r.content) < 1000:
            return None
        df = pd.read_csv(io.BytesIO(r.content))
        df.columns = [c.strip() for c in df.columns]
        df.to_csv(cache, index=False)
        return df
    except Exception:
        return None


def _build_delivery(dates) -> pd.DataFrame:
    import requests
    s = requests.Session(); s.headers.update(_H)
    try:
        s.get("https://www.nseindia.com", timeout=10)
    except Exception:
        pass
    recs = []
    hit = 0
    for i, dt in enumerate(dates, 1):
        df = _fetch_bhav(s, dt)
        if i % 25 == 0 or i == len(dates):
            print(f"    delivery fetch {i}/{len(dates)} · {hit} days with data", file=sys.stderr)
        if df is None or "DELIV_PER" not in df.columns:
            continue
        hit += 1
        d = df.copy()
        d["SERIES"] = d["SERIES"].astype(str).str.strip()
        d = d[d["SERIES"] == "EQ"]
        d["SYMBOL"] = d["SYMBOL"].astype(str).str.strip()
        d["deliv_per"] = pd.to_numeric(d["DELIV_PER"], errors="coerce")
        d = d.dropna(subset=["deliv_per"])
        for sym, dp in zip(d["SYMBOL"], d["deliv_per"]):
            recs.append((dt, sym + ".NS", float(dp)))
        if not os.path.exists(os.path.join(_CACHE, f"sec_{dt.strftime('%d%m%Y')}.csv")):
            time.sleep(0.35)  # polite pacing only on live fetch
    out = pd.DataFrame(recs, columns=["date", "ticker", "deliv_per"])
    if out.empty:
        return out
    # Per-stock rolling features (needs chronological order per ticker)
    out = out.sort_values(["ticker", "date"])
    g = out.groupby("ticker")["deliv_per"]
    mean20 = g.transform(lambda x: x.rolling(20, min_periods=5).mean())
    std20 = g.transform(lambda x: x.rolling(20, min_periods=5).std())
    out["deliv_z20"] = ((out["deliv_per"] - mean20) / std20.replace(0, np.nan)).fillna(0.0)
    out["deliv_chg5"] = g.transform(lambda x: x - x.shift(5)).fillna(0.0)
    return out


def _sharpe(rets):
    a = np.asarray([x for x in rets if not np.isnan(x)], dtype=float)
    if a.size < 2 or a.std(ddof=1) <= 1e-9:
        return 0.0
    return float(a.mean() / a.std(ddof=1) * np.sqrt(TRADING_DAYS / HOLD))


def _selection_edge(bd, u5, feats, te, top_n=5):
    Xte = te[feats].to_numpy(float)
    te = te.assign(_dir=bd.predict(Xte), _up50=u5.predict(Xte),
                   _net=te["ret_3D"].to_numpy(float) - COST)
    basket, market = [], []
    for _, day in te.groupby("date"):
        market.append(float(day["_net"].mean()))
        bull = day[day["_dir"] == "BULLISH"]
        if len(bull) < top_n:
            basket.append(np.nan); continue
        basket.append(float(bull.sort_values("_up50", ascending=False).head(top_n)["_net"].mean()))
    edge = np.array([b - m for b, m in zip(basket, market) if not np.isnan(b)])
    return (edge.mean() if len(edge) else float("nan")), _sharpe(basket)


def run(months: int, holdout_months: int):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.metrics import accuracy_score

    df = pd.read_csv(_CSV)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    base_feats = [c for c in FEATURE_COLUMNS if c in df.columns]
    df = df.dropna(subset=base_feats + ["ret_3D", "up_3D", "dir_3D", "date", "ticker"]).reset_index(drop=True)
    win_start = df["date"].max() - pd.DateOffset(months=months)
    win = df[df["date"] >= win_start].copy()
    dates = sorted(win["date"].unique())
    print(f"  Window {pd.Timestamp(dates[0]).date()} → {pd.Timestamp(dates[-1]).date()} · "
          f"{len(dates)} trading days · {len(win):,} rows · fetching delivery %…")
    deliv = _build_delivery([pd.Timestamp(d) for d in dates])
    if deliv.empty:
        raise SystemExit("no delivery data fetched — NSE archive unreachable.")
    win = win.merge(deliv, on=["date", "ticker"], how="left")
    cov = win["deliv_per"].notna().mean()
    win = win.dropna(subset=_DELIV_FEATS).reset_index(drop=True)
    print(f"  Delivery merged · coverage {cov:.0%} of window rows · {len(win):,} rows with delivery features")

    cutoff = win["date"].max() - pd.DateOffset(months=holdout_months)
    tr, te = win[win["date"] <= cutoff], win[win["date"] > cutoff].copy()
    print(f"  Train ≤ {cutoff.date()}: {len(tr):,} · OOS: {len(te):,}\n")
    if len(te) < 200:
        raise SystemExit("OOS too small — increase --months.")

    def fit_eval(feats, label):
        bd = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06,
                                            class_weight="balanced", random_state=0)
        bd.fit(tr[feats].to_numpy(float), tr["dir_3D"].to_numpy())
        u5 = HistGradientBoostingRegressor(loss="quantile", quantile=0.5, max_iter=250,
                                           learning_rate=0.06, random_state=0)
        u5.fit(tr[feats].to_numpy(float), tr["up_3D"].to_numpy(float))
        acc = accuracy_score(te["dir_3D"].to_numpy(), bd.predict(te[feats].to_numpy(float)))
        edge, shp = _selection_edge(bd, u5, feats, te)
        return {"label": label, "acc": acc, "edge": edge, "sharpe": shp}

    base = fit_eval(base_feats, "BASE (current features)")
    withd = fit_eval(base_feats + _DELIV_FEATS, "BASE + delivery %")

    print("=" * 78)
    print("  DELIVERY-% A/B — out-of-sample (dir_3D + top-5 selection edge)")
    print("=" * 78)
    print(f"  {'Model':<28}{'DirAcc':>8}{'SelEdge%':>10}{'SelSharpe':>11}")
    print("  " + "-" * 58)
    for r in (base, withd):
        print(f"  {r['label']:<28}{r['acc']:>7.1%}{r['edge']:>+10.2f}{r['sharpe']:>11.2f}")
    d_acc = (withd["acc"] - base["acc"]) * 100
    d_edge = withd["edge"] - base["edge"]
    d_shp = withd["sharpe"] - base["sharpe"]
    print("  " + "-" * 58)
    print(f"  {'Δ (delivery − base)':<28}{d_acc:>+6.1f}pp{d_edge:>+10.2f}{d_shp:>+11.2f}")
    verdict = ("HELPS" if (d_edge > 0.05 and d_shp > 0.1) else
               "NEUTRAL/NOISE" if (abs(d_edge) <= 0.10 and abs(d_shp) <= 0.15) else
               "MIXED" if d_edge > -0.05 else "HURTS")
    print(f"\n  → Delivery %: {verdict}. Per-stock conviction signal (not market-wide) — the most")
    print("  promising new feature. NOTE: window is short (yfinance-free NSE backfill); if it helps")
    print("  here, backfill the FULL history and re-test before considering production.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=8, help="months of history to backfill+test")
    ap.add_argument("--holdout-months", type=int, default=2)
    args = ap.parse_args()
    run(args.months, args.holdout_months)


if __name__ == "__main__":
    main()
