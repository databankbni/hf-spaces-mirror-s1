#!/usr/bin/env python3
"""ml_predictor/dataset.py — build the ML training CSV from cached OHLCV.

Reads the local SQLite OHLCV cache (ohlcv_cache.db → ohlcv_cache table, the same
store data_sources.py uses), computes the point-in-time feature vector
(ml_predictor.features.compute_features) and the forward-excursion labels
(_fwd_intraday_moves / _fwd_returns, mirroring research/backtest.py) for every
sampled (ticker, date), and writes one row per (ticker, date) to
ml_predictor/training_data.csv.

Labels per row (all % moves vs the entry close):
  up_INTRADAY / dn_INTRADAY  — entry day's own daily High/Low vs close (same-session proxy)
  up_1D / dn_1D              — best-up / worst-down over the next 1 bar
  up_3D / dn_3D              — best-up / worst-down over the next 3 bars
  ret_1D / ret_3D            — close-to-close returns (for the direction label)
  dir_INTRADAY / dir_1D / dir_3D — 3-class direction label (BULLISH/BEARISH/NEUTRAL)

News sentiment is NOT a feature (live-only, cannot be backfilled — see features.py).

Usage (from project root):
    python ml_predictor/dataset.py                 # build from cache (offline)
    python ml_predictor/dataset.py --step 1        # every trading day (max rows)
    python ml_predictor/dataset.py --fetch         # warm missing tickers first
    python ml_predictor/dataset.py --limit 50      # first 50 tickers (quick test)
"""
from __future__ import annotations

import argparse
import os
import pickle
import sqlite3
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from ml_predictor.features import compute_features, FEATURE_COLUMNS, TIMEFRAMES  # noqa: E402
from ml_predictor.features import STRATEGY_FEATURE_COLS, _USE_STRATEGY_FEATS  # noqa: E402

# ── Paths (mirror data_sources._ohlcv_data_dir HF-Spaces logic) ───────────────
_HF_DATA = "/data"
_OHLCV_DB = os.path.join(
    _HF_DATA if (os.path.isdir(_HF_DATA) and os.access(_HF_DATA, os.W_OK)) else _PROJ_ROOT,
    "ohlcv_cache.db",
)
OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "training_data.csv")

FETCH_PERIOD = "2y"
WARMUP_BARS = 200        # skip first N bars so EMA200 / 52W features are warmed up
DEFAULT_STEP = 1         # sample every Nth trading day per ticker

# NEUTRAL direction-label bands (half-width %, per TF) — outside the band is directional.
_DIR_BAND = {"INTRADAY": 0.5, "1D": 1.0, "3D": 1.5}

LABEL_COLUMNS = [
    "up_INTRADAY", "dn_INTRADAY", "up_1D", "dn_1D", "up_3D", "dn_3D",
    "ret_1D", "ret_3D",
    "dir_INTRADAY", "dir_1D", "dir_3D",
]


# Excess-return direction labels are now PRODUCTION DEFAULT (validated to ~10× the 1D and 2×
# the 3D per-trade expectancy under target-exit trading). The 1D/3D DIRECTION label is the
# stock's return MINUS the Nifty return over the same window — so BULLISH means "expected to
# OUTPERFORM the market" (alpha), not merely "go up" (beta). Excursion quantiles stay absolute
# (they drive price targets); INTRADAY stays absolute. Set ML_EXCESS_LABELS=0 to revert to raw.
_EXCESS = os.environ.get("ML_EXCESS_LABELS", "1") != "0"


# ── Forward labels (mirror research/backtest.py _fwd_intraday_moves/_fwd_returns) ──
def _fwd_labels(c: pd.Series, h: pd.Series, l: pd.Series, idx: int,
                ni: pd.Series | None = None) -> dict | None:
    """Excursion + close-return labels for the bar at position `idx`.
    `ni` = Nifty close aligned to c.index (only used for excess-return direction labels)."""
    p0 = float(c.iloc[idx])
    if not np.isfinite(p0) or p0 <= 0:
        return None

    def _moves(n):
        fut = c.index[idx + 1: idx + n + 1]
        if len(fut) < n:
            return np.nan, np.nan
        hw = h.reindex(fut).dropna()
        lw = l.reindex(fut).dropna()
        if hw.empty or lw.empty:
            return np.nan, np.nan
        return (float(hw.max()) / p0 - 1) * 100.0, (float(lw.min()) / p0 - 1) * 100.0

    def _ret(n):
        i = idx + n
        return (float(c.iloc[i]) / p0 - 1) * 100.0 if i < len(c) else np.nan

    # INTRADAY: entry day's own High/Low vs its close (daily-OHLC same-session proxy).
    entry_day = c.index[idx]
    try:
        up0 = (float(h.reindex([entry_day]).iloc[0]) / p0 - 1) * 100.0
        dn0 = (float(l.reindex([entry_day]).iloc[0]) / p0 - 1) * 100.0
    except Exception:
        up0, dn0 = np.nan, np.nan

    up1, dn1 = _moves(1)
    up3, dn3 = _moves(3)
    r1, r3 = _ret(1), _ret(3)

    # Require the longest-horizon label to exist so the row is fully labeled.
    if any(pd.isna(x) for x in (up0, dn0, up1, dn1, up3, dn3, r1, r3)):
        return None

    def _nret(n):
        if ni is None:
            return 0.0
        try:
            n0 = float(ni.iloc[idx]); nn = float(ni.iloc[idx + n])
            return (nn / n0 - 1) * 100.0 if (n0 > 0 and idx + n < len(ni)) else 0.0
        except Exception:
            return 0.0

    def _dir(tf, ret_val, up_val, dn_val):
        band = _DIR_BAND[tf]
        if tf == "INTRADAY":
            metric = up_val + dn_val               # net intraday excursion (always absolute)
        else:
            metric = ret_val - (_nret(1 if tf == "1D" else 3) if _EXCESS else 0.0)
        if metric > band:
            return "BULLISH"
        if metric < -band:
            return "BEARISH"
        return "NEUTRAL"

    return {
        "up_INTRADAY": up0, "dn_INTRADAY": dn0,
        "up_1D": up1, "dn_1D": dn1,
        "up_3D": up3, "dn_3D": dn3,
        "ret_1D": r1, "ret_3D": r3,
        "dir_INTRADAY": _dir("INTRADAY", 0.0, up0, dn0),
        "dir_1D": _dir("1D", r1, up1, dn1),
        "dir_3D": _dir("3D", r3, up3, dn3),
    }


# ── Cache access ──────────────────────────────────────────────────────────────
def _cached_tickers() -> list[str]:
    con = sqlite3.connect(_OHLCV_DB)
    try:
        rows = con.execute("SELECT DISTINCT ticker FROM ohlcv_cache").fetchall()
    finally:
        con.close()
    return sorted(r[0] for r in rows)


def _load_ticker(ticker: str) -> tuple | None:
    """Return (close, high, low, volume) Series for `ticker` from the cache."""
    con = sqlite3.connect(_OHLCV_DB)
    try:
        row = con.execute(
            "SELECT data FROM ohlcv_cache WHERE ticker=? ORDER BY period DESC LIMIT 1", (ticker,)
        ).fetchone()
    finally:
        con.close()
    if not row:
        return None
    try:
        sc, sh, sl, sv = pickle.loads(row[0])
        return sc[ticker], sh[ticker], sl[ticker], sv[ticker]
    except Exception:
        return None


def _fetch_indices() -> tuple[pd.Series | None, pd.Series | None]:
    """Full ^NSEI / ^INDIAVIX Close history via yfinance (full history, unlike the
    spot-first fetch_market_data)."""
    try:
        import yfinance as yf
        raw = yf.download(["^NSEI", "^INDIAVIX"], period=FETCH_PERIOD, auto_adjust=True, progress=False)
        nifty = raw["Close"]["^NSEI"].dropna()
        vix = raw["Close"]["^INDIAVIX"].dropna()
        return nifty, vix
    except Exception as e:
        print(f"  ! Could not fetch indices ({e}); RS/macro features will be NaN")
        return None, None


def _strategy_signal_sets(ticker, c, h, l, v, nifty_c, vix_c) -> dict:
    """Compute the best NSE-backtested S-signals for one ticker → {sig_col: set(dates)}.
    Each gen_* returns (date, ticker) events; we keep the firing dates per signal."""
    import trial_run as T
    sc = pd.DataFrame({ticker: c}); sh = pd.DataFrame({ticker: h})
    sl = pd.DataFrame({ticker: l}); sv = pd.DataFrame({ticker: v})
    gens = {
        "sig_s8":    lambda: T.gen_s8(sc, sh, sl, sv, nifty_c, vix_c),
        "sig_ctrio": lambda: T.gen_s_confluence_trio(sc, sh, sl, sv, nifty_c, vix_c),
        "sig_s4v2":  lambda: T.gen_s4v2(sc, sh, sl, sv, nifty_c, vix_c),
        "sig_s6":    lambda: T.gen_s6(sc, sh, sl, sv, nifty_c, vix_c),
        "sig_s16":   lambda: T.gen_s16(sc, sh, sl, sv, nifty_c, vix_c),
        "sig_s1":    lambda: T.gen_s1(sc, sh, sl, sv, nifty_c),
    }
    out = {}
    for col, fn in gens.items():
        try:
            out[col] = {pd.Timestamp(d) for d, _tk in fn()}
        except Exception:
            out[col] = set()
    return out


# ── Row builder ─────────────────────────────────────────────────────────────
def _rows_for_ticker(ticker: str, nifty_c, vix_c, step: int) -> list[dict]:
    loaded = _load_ticker(ticker)
    if loaded is None:
        return []
    c, h, l, v = (s.dropna() for s in loaded)
    if len(c) < WARMUP_BARS + 5:
        return []
    # Nifty aligned to this ticker's dates (for excess-return direction labels).
    ni = nifty_c.reindex(c.index).ffill() if (_EXCESS and nifty_c is not None) else None
    # Strategy-signal firing dates (only when the experiment flag is on).
    sig_sets = _strategy_signal_sets(ticker, c, h, l, v, nifty_c, vix_c) if _USE_STRATEGY_FEATS else None
    rows = []
    # Sample positions from WARMUP_BARS to len-4 (need 3 forward bars for the 3D label).
    positions = range(WARMUP_BARS, len(c) - 3, step)
    for idx in positions:
        date = c.index[idx]
        labels = _fwd_labels(c, h, l, idx, ni=ni)
        if labels is None:
            continue
        feat = compute_features(c, h, l, v, nifty_c, vix_c, date=date)
        if feat is None:
            continue
        row = {"date": pd.Timestamp(date).strftime("%Y-%m-%d"), "ticker": ticker}
        row.update(feat)
        if sig_sets is not None:
            ts = pd.Timestamp(date)
            for col in STRATEGY_FEATURE_COLS:
                row[col] = 1.0 if ts in sig_sets.get(col, ()) else 0.0
        row.update(labels)
        rows.append(row)
    return rows


def build_training_frame(step: int = DEFAULT_STEP, limit: int | None = None,
                         workers: int = 6) -> pd.DataFrame:
    tickers = _cached_tickers()
    if limit:
        tickers = tickers[:limit]
    print(f"  Building features for {len(tickers)} tickers (step={step}) from {_OHLCV_DB}")
    print("  Fetching ^NSEI / ^INDIAVIX history…")
    nifty_c, vix_c = _fetch_indices()

    all_rows: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_rows_for_ticker, tk, nifty_c, vix_c, step): tk for tk in tickers}
        for fut in as_completed(futs):
            tk = futs[fut]
            try:
                rows = fut.result()
            except Exception as e:
                print(f"    ! {tk}: {e}")
                rows = []
            all_rows.extend(rows)
            done += 1
            if done % 50 == 0 or done == len(tickers):
                print(f"    {done}/{len(tickers)} tickers · {len(all_rows)} rows")

    df = pd.DataFrame(all_rows)
    if not df.empty:
        cols = ["date", "ticker"] + FEATURE_COLUMNS + LABEL_COLUMNS
        df = df[[c for c in cols if c in df.columns]]
        df = df.sort_values(["date", "ticker"]).reset_index(drop=True)
    return df


def _fetch_missing(limit: int | None):
    """Warm the OHLCV cache for universe tickers not yet present."""
    from universe import get_universe
    from data_sources import warm_ohlcv_cache
    have = set(_cached_tickers())
    want = list(get_universe().keys())
    if limit:
        want = want[:limit]
    missing = [t for t in want if t not in have]
    print(f"  Warming {len(missing)} missing tickers…")
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda t: warm_ohlcv_cache(t, FETCH_PERIOD), missing))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=DEFAULT_STEP, help="sample every Nth trading day")
    ap.add_argument("--limit", type=int, default=None, help="first N tickers only (quick test)")
    ap.add_argument("--fetch", action="store_true", help="warm missing universe tickers first")
    ap.add_argument("--out", default=OUT_CSV)
    args = ap.parse_args()

    if args.fetch:
        _fetch_missing(args.limit)

    df = build_training_frame(step=args.step, limit=args.limit)
    if df.empty:
        print("  ! No rows produced — is ohlcv_cache.db populated?")
        return
    df.to_csv(args.out, index=False)
    print(f"\n  ✓ Wrote {len(df):,} rows × {df.shape[1]} cols → {args.out}")
    print(f"  Date range: {df['date'].min()} → {df['date'].max()} · {df['ticker'].nunique()} tickers")
    for tf in TIMEFRAMES:
        vc = df[f"dir_{tf}"].value_counts(normalize=True)
        print(f"  dir_{tf}: " + " ".join(f"{k}={v:.0%}" for k, v in vc.items()))


if __name__ == "__main__":
    main()
