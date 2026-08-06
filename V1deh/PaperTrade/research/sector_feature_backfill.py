#!/usr/bin/env python3
"""research/sector_feature_backfill.py — does adding SECTOR-REGIME features lift the model?

Priority-1 "better data" test. FII/DII/PCR can't be backfilled (NSE live-only), but the 10 NSE
sector indices HAVE full history on yfinance. This backfills market-wide sector-rotation / breadth
features per date, merges them into training_data_extra.csv, and A/B-tests whether they improve
(a) OOS 3D direction accuracy and (b) the top-N selection edge — WITHOUT touching production.

Sector features (per date, same for all stocks that day — a regime signal):
  • sec_breadth_5d      fraction of the 10 sectors with positive 5-day return
  • sec_dispersion_5d   std of the 10 sectors' 5-day returns (rotation intensity)
  • sec_growth_minus_def (IT+BANK+FINANCE) − (FMCG+PHARMA) 5-day  (risk-on vs risk-off)
  • sec_cyc_minus_def    (METAL+ENERGY+AUTO) − (FMCG+PHARMA) 5-day
  • sec_best_5d / sec_worst_5d   strongest / weakest sector 5-day momentum

Research only; never touches the production model.

Usage:
    python research/sector_feature_backfill.py                     # dir_3D, 6-month OOS
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import FEATURE_COLUMNS  # noqa: E402

_CSV = os.path.join(_PROJ_ROOT, "ml_predictor", "training_data_extra.csv")
COST = 0.30
TRADING_DAYS = 252
HOLD = 3

# 10 NSE sector indices (same set as sector_pulse.py)
_SECTORS = {
    "BANK": "^NSEBANK", "IT": "^CNXIT", "PHARMA": "^CNXPHARMA", "FMCG": "^CNXFMCG",
    "AUTO": "^CNXAUTO", "METAL": "^CNXMETAL", "REALTY": "^CNXREALTY", "ENERGY": "^CNXENERGY",
    "FINANCE": "^CNXFINANCE", "INFRA": "^CNXINFRA",
}
_SECTOR_FEATS = ["sec_breadth_5d", "sec_dispersion_5d", "sec_growth_minus_def",
                 "sec_cyc_minus_def", "sec_best_5d", "sec_worst_5d"]


def _build_sector_features(start, end) -> pd.DataFrame:
    import yfinance as yf
    tickers = list(_SECTORS.values())
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    close = raw["Close"] if "Close" in raw else raw
    # 5-day % return per sector
    r5 = close.pct_change(5) * 100.0
    r5 = r5.dropna(how="all")
    # map columns back to sector names
    name_by_tk = {v: k for k, v in _SECTORS.items()}
    r5 = r5.rename(columns=name_by_tk)
    have = [c for c in _SECTORS if c in r5.columns]
    if len(have) < 5:
        raise SystemExit(f"only {len(have)} sector indices downloaded — sector history unavailable.")
    growth = [c for c in ["IT", "BANK", "FINANCE"] if c in r5.columns]
    defen = [c for c in ["FMCG", "PHARMA"] if c in r5.columns]
    cyc = [c for c in ["METAL", "ENERGY", "AUTO"] if c in r5.columns]
    out = pd.DataFrame(index=r5.index)
    sect = r5[have]
    out["sec_breadth_5d"] = (sect > 0).mean(axis=1)
    out["sec_dispersion_5d"] = sect.std(axis=1)
    out["sec_growth_minus_def"] = r5[growth].mean(axis=1) - r5[defen].mean(axis=1)
    out["sec_cyc_minus_def"] = r5[cyc].mean(axis=1) - r5[defen].mean(axis=1)
    out["sec_best_5d"] = sect.max(axis=1)
    out["sec_worst_5d"] = sect.min(axis=1)
    out = out.reset_index().rename(columns={out.reset_index().columns[0]: "date"})
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None).dt.normalize()
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


def run(holdout_months: int):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.metrics import accuracy_score

    df = pd.read_csv(_CSV)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    base_feats = [c for c in FEATURE_COLUMNS if c in df.columns]
    df = df.dropna(subset=base_feats + ["ret_3D", "up_3D", "dir_3D", "date"]).reset_index(drop=True)

    print(f"  Downloading 10 NSE sector indices {df['date'].min().date()} → {df['date'].max().date()} …")
    sec = _build_sector_features(df["date"].min() - pd.Timedelta(days=15), df["date"].max() + pd.Timedelta(days=2))
    df = df.merge(sec, on="date", how="left")
    miss = df[_SECTOR_FEATS].isna().any(axis=1).mean()
    df = df.dropna(subset=_SECTOR_FEATS).reset_index(drop=True)
    print(f"  Merged sector features · dropped {miss:.0%} rows with no sector data · {len(df):,} rows remain")

    cutoff = df["date"].max() - pd.DateOffset(months=holdout_months)
    tr, te = df[df["date"] <= cutoff], df[df["date"] > cutoff].copy()
    print(f"  Train ≤ {cutoff.date()}: {len(tr):,} · OOS: {len(te):,}\n")

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
    withsec = fit_eval(base_feats + _SECTOR_FEATS, "BASE + sector features")

    print("=" * 78)
    print("  SECTOR-FEATURE A/B — out-of-sample (dir_3D + top-5 selection edge)")
    print("=" * 78)
    print(f"  {'Model':<28}{'DirAcc':>8}{'SelEdge%':>10}{'SelSharpe':>11}")
    print("  " + "-" * 58)
    for r in (base, withsec):
        print(f"  {r['label']:<28}{r['acc']:>7.1%}{r['edge']:>+10.2f}{r['sharpe']:>11.2f}")
    d_acc = (withsec["acc"] - base["acc"]) * 100
    d_edge = withsec["edge"] - base["edge"]
    d_shp = withsec["sharpe"] - base["sharpe"]
    print("  " + "-" * 58)
    print(f"  {'Δ (sector − base)':<28}{d_acc:>+6.1f}pp{d_edge:>+10.2f}{d_shp:>+11.2f}")
    verdict = ("HELPS" if (d_edge > 0.05 and d_shp > 0.1) else
               "NEUTRAL/NOISE" if abs(d_edge) <= 0.10 else "HURTS")
    print(f"\n  → Sector features: {verdict}. (Market-wide regime signal; the model already carries")
    print("  VIX + Nifty regime, so a large lift is unlikely. Per-stock sector needs a ticker→sector map.)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout-months", type=int, default=6)
    args = ap.parse_args()
    run(args.holdout_months)


if __name__ == "__main__":
    main()
