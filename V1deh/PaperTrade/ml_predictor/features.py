"""ml_predictor/features.py — shared point-in-time feature builder.

ONE source of truth for the ML model's feature vector, used identically by:
  • dataset.py  (training-CSV construction over historical dates)
  • infer.py    (live inference on the latest bar)
so training features exactly equal production features (no train/serve skew).

Every feature is computed point-in-time from data up to and including `date`
(no lookahead), mirroring research/backtest.py::_compute_indicators and the
11-weight ML sub-feature math in predictor_core.get_ml_feature_score (L667-753).

News sentiment is deliberately EXCLUDED — it is live-only and cannot be
backfilled to historical dates (see CLAUDE.md). It is applied as a live
inference-time confidence adjustment inside infer.py, not as a trained feature.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

# Lightweight indicator primitives (no heavy imports).
from trial_run import rsi, atr, obv, adx_s, macd_h
from ml_combiner import bollinger_position, ema_stack_score, shadow_flag

TIMEFRAMES = ["INTRADAY", "1D", "3D"]

# Experiment flag: when ML_STRATEGY_FEATURES=1, the best NSE-backtested S-signals are
# appended as binary features (computed in dataset.py per ticker). Off by default.
STRATEGY_FEATURE_COLS = ["sig_s8", "sig_ctrio", "sig_s4v2", "sig_s6", "sig_s16", "sig_s1"]
_USE_STRATEGY_FEATS = os.environ.get("ML_STRATEGY_FEATURES") == "1"

# Extra indicator + Monte-Carlo features. PRODUCTION DEFAULT (validated on the 5-month OOS
# holdout, research/ml_backtest.py): vs the 37-feature baseline they lift INTRADAY direction
# 71%→82% and price-target hit 64%→84%, cut the estimated-high MAE 1.54→1.07, and raise 1D/3D
# per-trade P&L (+0.86→+1.02, +1.29→+1.51, PF 1.74→1.93 / 1.79→1.96) with NO regression. The
# channel positions, extra oscillators, realized vol, and MC hit-probability/excursion estimates
# are computed identically in compute_features (live) and research/augment_features.py (training
# CSV) via the shared _extra_feature_series / _mc_features helpers → no train/serve skew.
# Set ML_EXTRA_FEATURES=0 to revert to the 37-feature model (must retrain to match).
EXTRA_FEATURE_COLS = [
    "bb_bandwidth", "bb_squeeze",           # Bollinger volatility regime / squeeze
    "keltner_pct", "donchian_pct",          # channel positions
    "stoch_k", "cci20", "mfi14", "williams_r",  # extra oscillators
    "hist_vol_20",                          # realized volatility
    "mc_up_prob_3d", "mc_exp_maxup_3d", "mc_exp_maxdn_3d",  # Monte-Carlo path features
]
_USE_EXTRA_FEATS = os.environ.get("ML_EXTRA_FEATURES", "1") != "0"

# Ordered feature list — the manifest stores this so infer.py builds columns in
# the exact order the models were trained on. Keep additions APPEND-ONLY.
FEATURE_COLUMNS: list[str] = [
    # Momentum / oscillators
    "rsi14", "rsi5", "rsi2", "macd_hist", "adx14",
    # Trend / EMA
    "price_vs_ema20", "price_vs_ema50", "price_vs_ema200", "ema_stack", "supertrend",
    # Bollinger
    "bb_pct", "bb_lower_dist", "bb_upper_dist",
    # Relative strength vs Nifty
    "rs_3m",
    # Volume
    "vol_ratio", "obv_z", "vol_trend_5d",
    # Volatility / range
    "atr_pct", "shadow",
    # Returns / streak
    "return_10d", "return_20d", "return_90d", "dist_52w_high", "consec_days",
    # Domain trigger flags
    "trigger_T1", "trigger_T2", "trigger_T3", "trigger_T4", "trigger_T5",
    "trigger_T6", "trigger_T7", "trigger_B1", "trigger_B2", "trigger_B3",
    # Macro regime
    "vix_level", "nifty_ok", "vix_decl",
]

if _USE_STRATEGY_FEATS:
    FEATURE_COLUMNS = FEATURE_COLUMNS + STRATEGY_FEATURE_COLS

if _USE_EXTRA_FEATS:
    FEATURE_COLUMNS = FEATURE_COLUMNS + EXTRA_FEATURE_COLS

_NAN = float("nan")


def _supertrend_dir(c: pd.Series, h: pd.Series, l: pd.Series, period: int = 10, mult: float = 3.0) -> int:
    """Supertrend(10,3) final direction: +1 bullish, -1 bearish. Mirrors
    predictor_core._st_dir_last / backtest._compute_indicators supertrend block."""
    try:
        if len(c) < period + 1:
            return 0
        tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        _atr = tr.rolling(period).mean()
        hl2 = (h + l) / 2
        up_raw = (hl2 + mult * _atr).values
        dn_raw = (hl2 - mult * _atr).values
        cv = c.values
        n = len(cv)
        upper, lower = up_raw.copy(), dn_raw.copy()
        dirn = 1
        for i in range(1, n):
            if not (pd.isna(up_raw[i]) or pd.isna(dn_raw[i])):
                upper[i] = min(up_raw[i], upper[i - 1]) if cv[i - 1] <= upper[i - 1] else up_raw[i]
                lower[i] = max(dn_raw[i], lower[i - 1]) if cv[i - 1] >= lower[i - 1] else dn_raw[i]
                if cv[i] > upper[i - 1]:
                    dirn = 1
                elif cv[i] < lower[i - 1]:
                    dirn = -1
        return dirn
    except Exception:
        return 0


def _consec_days(c: pd.Series) -> float:
    """Signed consecutive-day streak: +n up, -n down, 0 otherwise."""
    try:
        if len(c) < 6:
            return 0.0
        diffs = c.iloc[-6:].diff().dropna()
        up = dn = 0
        for d in reversed(diffs.values):
            if d > 0 and dn == 0:
                up += 1
            elif d < 0 and up == 0:
                dn += 1
            else:
                break
        if up >= 1:
            return float(up)
        if dn >= 1:
            return float(-dn)
        return 0.0
    except Exception:
        return 0.0


def _trigger_flags(rsi14, bb_pct, r10, r20, macd, above_ema50, above_ema200, consec) -> dict:
    """Replicates research/backtest.py::_compute_trigger_flags (1D canonical triggers)."""
    consec_up = int(consec) if consec and consec > 0 else 0
    crash_exhausted = bool(r10 < -6.0 or r20 < -8.0)
    overbought_extreme = bool(rsi14 > 70)

    T1 = bool(above_ema50 and macd > 0 and not overbought_extreme)
    T2 = bool(above_ema50 and r10 > 3.0 and bb_pct < 85.0)
    T3 = bool(above_ema50 and consec_up >= 3 and r20 > 0.0)
    T4 = bool(rsi14 < 50 and bb_pct < 45.0 and r10 > -2.0 and not crash_exhausted)
    T5 = bool(r10 > 7.0 and bb_pct < 80.0)
    T6 = bool(rsi14 < 44 and bb_pct < 35.0 and not crash_exhausted)
    T7 = bool(above_ema50 and 1.0 <= r20 <= 5.0 and rsi14 < 62.0)
    B1 = False  # removed from production; kept for schema stability
    B2 = bool((not above_ema50) and macd < 0 and r10 < -4.0 and rsi14 > 42 and bb_pct > 40.0)
    B3 = bool(crash_exhausted and macd < 0)
    return {
        "trigger_T1": int(T1), "trigger_T2": int(T2), "trigger_T3": int(T3),
        "trigger_T4": int(T4), "trigger_T5": int(T5), "trigger_T6": int(T6),
        "trigger_T7": int(T7), "trigger_B1": int(B1), "trigger_B2": int(B2),
        "trigger_B3": int(B3),
    }


def _last(series: pd.Series, default=_NAN) -> float:
    try:
        v = float(series.iloc[-1])
        return v if np.isfinite(v) else default
    except Exception:
        return default


# ── Extra indicator features (ML_EXTRA_FEATURES=1) — vectorized, point-in-time ──
# These return full backward-looking Series so the SAME math serves both live inference
# (compute_features → last value at `date`) and the training-CSV augmenter
# (research/augment_features.py → value indexed at each sampled date). All windows are
# trailing (rolling/ewm), so the last value of the full series == the value at that date
# with no lookahead. Keep in ONE place to avoid train/serve skew.
def _extra_feature_series(c: pd.Series, h: pd.Series, l: pd.Series, v: pd.Series) -> dict:
    out: dict[str, pd.Series] = {}
    tp = (h + l + c) / 3.0  # typical price

    # Bollinger bandwidth + squeeze regime.
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    bb_up = sma20 + 2 * std20
    bb_lo = sma20 - 2 * std20
    bandwidth = (bb_up - bb_lo) / sma20.replace(0, np.nan) * 100.0
    out["bb_bandwidth"] = bandwidth
    # squeeze = bandwidth in the bottom 20% of its trailing 126-bar range (breakout setup).
    bw_q20 = bandwidth.rolling(126, min_periods=30).quantile(0.20)
    out["bb_squeeze"] = (bandwidth <= bw_q20).astype(float)

    # Keltner channel position (EMA20 ± 2·ATR20).
    _atr20 = atr(h, l, c, 20)
    ema20 = c.ewm(span=20).mean()
    kc_up = ema20 + 2 * _atr20
    kc_lo = ema20 - 2 * _atr20
    out["keltner_pct"] = (c - kc_lo) / (kc_up - kc_lo).replace(0, np.nan) * 100.0

    # Donchian channel position (20).
    dc_hi = h.rolling(20).max()
    dc_lo = l.rolling(20).min()
    out["donchian_pct"] = (c - dc_lo) / (dc_hi - dc_lo).replace(0, np.nan) * 100.0

    # Stochastic %K (14).
    ll14 = l.rolling(14).min()
    hh14 = h.rolling(14).max()
    out["stoch_k"] = (c - ll14) / (hh14 - ll14).replace(0, np.nan) * 100.0

    # CCI (20).
    tp_sma = tp.rolling(20).mean()
    tp_mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    out["cci20"] = (tp - tp_sma) / (0.015 * tp_mad.replace(0, np.nan))

    # Money Flow Index (14).
    rmf = tp * v
    pos_mf = rmf.where(tp.diff() > 0, 0.0).rolling(14).sum()
    neg_mf = rmf.where(tp.diff() < 0, 0.0).rolling(14).sum()
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    out["mfi14"] = 100.0 - 100.0 / (1.0 + mfr)

    # Williams %R (14) → mapped to 0..100 (0 = at 14-bar low, 100 = at 14-bar high).
    out["williams_r"] = (c - ll14) / (hh14 - ll14).replace(0, np.nan) * 100.0

    # Realized (historical) volatility, 20-bar, annualized %.
    rets = c.pct_change()
    out["hist_vol_20"] = rets.rolling(20).std() * np.sqrt(252) * 100.0
    return out


def _mc_features(rets: np.ndarray, horizon: int = 3, n_sims: int = 400) -> tuple:
    """Monte-Carlo bootstrap of forward price paths from the trailing daily returns.

    Draws `n_sims` paths of length `horizon` by sampling WITH replacement from the recent
    return distribution (non-parametric, captures fat tails / skew unlike a Gaussian), then
    measures the forward-excursion distribution the way the labels do:
      • mc_up_prob   = P(best up-excursion over the path > 0)   → chance the up-target is reachable
      • mc_exp_maxup = mean best up-excursion (%)               → expected reachable high
      • mc_exp_maxdn = mean worst down-excursion (%)            → expected drawdown
    Deterministic (fixed seed) so live inference and the training augmenter agree exactly.
    """
    rets = rets[np.isfinite(rets)]
    if rets.size < 10:
        return (_NAN, _NAN, _NAN)
    rng = np.random.default_rng(12345)
    draws = rng.choice(rets, size=(n_sims, horizon), replace=True)
    paths = np.cumprod(1.0 + draws, axis=1)          # cumulative price factor along each path
    max_up = (paths.max(axis=1) - 1.0) * 100.0       # best up-excursion per path (%)
    min_dn = (paths.min(axis=1) - 1.0) * 100.0       # worst down-excursion per path (%)
    return (float(np.mean(max_up > 0.0)) * 100.0, float(np.mean(max_up)), float(np.mean(min_dn)))


def compute_extra_features(c: pd.Series, h: pd.Series, l: pd.Series, v: pd.Series) -> dict:
    """Point-in-time extra-feature dict for the LAST bar of the given series (live path)."""
    ser = _extra_feature_series(c, h, l, v)
    feat = {k: _last(s, _NAN) for k, s in ser.items()}
    rets = c.pct_change().to_numpy()[-63:]
    up_prob, exp_up, exp_dn = _mc_features(rets)
    feat["mc_up_prob_3d"] = up_prob
    feat["mc_exp_maxup_3d"] = exp_up
    feat["mc_exp_maxdn_3d"] = exp_dn
    return {k: float(feat.get(k, _NAN)) for k in EXTRA_FEATURE_COLS}


def compute_features(
    c: pd.Series, h: pd.Series, l: pd.Series, v: pd.Series,
    nifty_c: pd.Series | None = None, vix_c: pd.Series | None = None,
    date=None,
) -> dict | None:
    """Return the ordered numeric feature dict for one (ticker, date).

    c/h/l/v are full daily Close/High/Low/Volume Series (DatetimeIndex).
    nifty_c/vix_c are ^NSEI / ^INDIAVIX Close Series (for RS + macro features).
    If `date` is given, all series are sliced to `.loc[:date]` (point-in-time).
    Returns None if there is too little history (< 26 bars) to compute indicators.
    """
    if date is not None:
        c = c.loc[:date]
        h = h.loc[:date]
        l = l.loc[:date]
        v = v.loc[:date]
    c = c.dropna(); h = h.dropna(); l = l.dropna(); v = v.dropna()
    if len(c) < 26:
        return None
    price = float(c.iloc[-1])
    f: dict[str, float] = {}

    # ── Momentum / oscillators ──────────────────────────────────────────────
    f["rsi14"] = _last(rsi(c, 14), 50.0)
    f["rsi5"]  = _last(rsi(c, 5), 50.0)
    f["rsi2"]  = _last(rsi(c, 2), 50.0)
    f["macd_hist"] = _last(macd_h(c), 0.0) if len(c) >= 27 else 0.0
    f["adx14"] = _last(adx_s(h, l, c), 20.0) if (len(h) >= 15 and len(l) >= 15) else 20.0

    # ── Trend / EMA (distance in %) ─────────────────────────────────────────
    e20  = float(c.ewm(span=20).mean().iloc[-1])
    e50  = float(c.ewm(span=50).mean().iloc[-1]) if len(c) >= 50 else _NAN
    e200 = float(c.ewm(span=200).mean().iloc[-1]) if len(c) >= 200 else _NAN
    f["price_vs_ema20"]  = (price / e20 - 1.0) * 100.0
    f["price_vs_ema50"]  = (price / e50 - 1.0) * 100.0 if np.isfinite(e50) else _NAN
    f["price_vs_ema200"] = (price / e200 - 1.0) * 100.0 if np.isfinite(e200) else _NAN
    f["ema_stack"] = _last(ema_stack_score(c), 0.5) if len(c) >= 20 else 0.5
    f["supertrend"] = float(1 if _supertrend_dir(c, h, l) > 0 else 0)

    # ── Bollinger position + explicit band-distance (room to band, %) ───────
    bb_pct = 50.0
    bb_lower_dist = _NAN
    bb_upper_dist = _NAN
    if len(c) >= 20:
        sma20 = float(c.rolling(20).mean().iloc[-1])
        std20 = float(c.rolling(20).std().iloc[-1])
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        if bb_upper > bb_lower:
            bb_pct = (price - bb_lower) / (bb_upper - bb_lower) * 100.0
            bb_lower_dist = (price - bb_lower) / price * 100.0
            bb_upper_dist = (bb_upper - price) / price * 100.0
    f["bb_pct"] = bb_pct
    f["bb_lower_dist"] = bb_lower_dist
    f["bb_upper_dist"] = bb_upper_dist

    # ── Relative strength vs Nifty (3M = 63 bars) ───────────────────────────
    rs_3m = 0.0
    if nifty_c is not None and len(nifty_c) > 0 and len(c) >= 63:
        ni = nifty_c
        if date is not None:
            ni = ni.loc[:date]
        ni = ni.reindex(c.index).ffill()
        try:
            rs_3m = float((c.iloc[-1] / c.iloc[-63] - 1) - (ni.iloc[-1] / ni.iloc[-63] - 1)) * 100.0
        except Exception:
            rs_3m = 0.0
    f["rs_3m"] = rs_3m

    # ── Volume ──────────────────────────────────────────────────────────────
    vol_ratio = 1.0
    if len(v) >= 20:
        v20 = float(v.rolling(20).mean().iloc[-1])
        vol_ratio = float(v.iloc[-1]) / v20 if v20 > 0 else 1.0
    f["vol_ratio"] = vol_ratio
    obv_z = 0.0
    if len(c) >= 20:
        ob = obv(c, v)
        ob_mu = ob.rolling(20).mean().iloc[-1]
        ob_std = ob.rolling(20).std().iloc[-1]
        obv_z = float((ob.iloc[-1] - ob_mu) / ob_std) if ob_std and ob_std > 0 else 0.0
    f["obv_z"] = float(np.clip(obv_z, -5, 5))
    vt = 1.0
    if len(v) >= 25:
        v20s = v / (v.rolling(20).mean() + 1e-9)
        vt = float(v20s.rolling(5).mean().iloc[-1])
    f["vol_trend_5d"] = float(np.clip(vt, 0, 5))

    # ── Volatility / range ────────────────────────────────────────────────
    atr14 = _last(atr(h, l, c, 14), _NAN) if (len(h) >= 15 and len(l) >= 15) else _NAN
    f["atr_pct"] = (atr14 / price * 100.0) if (np.isfinite(atr14) and price > 0) else _NAN
    f["shadow"] = _last(shadow_flag(c, l), 0.0) if len(c) >= 20 else 0.0

    # ── Returns / streak ────────────────────────────────────────────────────
    f["return_10d"] = (price / float(c.iloc[-10]) - 1) * 100.0 if len(c) >= 10 else _NAN
    f["return_20d"] = (price / float(c.iloc[-20]) - 1) * 100.0 if len(c) >= 20 else _NAN
    f["return_90d"] = (price / float(c.iloc[-63]) - 1) * 100.0 if len(c) >= 63 else _NAN
    f["dist_52w_high"] = (price / float(c.iloc[-252:].max()) - 1) * 100.0 if len(c) >= 252 else _NAN
    consec = _consec_days(c)
    f["consec_days"] = consec

    # ── Domain trigger flags ──────────────────────────────────────────────
    above_ema50 = np.isfinite(e50) and price > e50
    above_ema200 = np.isfinite(e200) and price > e200
    r10 = f["return_10d"] if np.isfinite(f["return_10d"]) else 0.0
    r20 = f["return_20d"] if np.isfinite(f["return_20d"]) else 0.0
    f.update(_trigger_flags(f["rsi14"], bb_pct, r10, r20, f["macd_hist"],
                            above_ema50, above_ema200, consec))

    # ── Macro regime ──────────────────────────────────────────────────────
    vix_level = _NAN
    vix_decl = 0.0
    if vix_c is not None and len(vix_c) > 0:
        vc = vix_c
        if date is not None:
            vc = vc.loc[:date]
        vc = vc.dropna()
        if len(vc) > 0:
            vix_level = float(vc.iloc[-1])
            if len(vc) >= 10:
                vix_ema5 = vc.ewm(span=5).mean()
                vix_decl = float(1 if vix_ema5.iloc[-1] < vix_ema5.iloc[-2] else 0)
    f["vix_level"] = vix_level
    f["vix_decl"] = vix_decl
    nifty_ok = 0.0
    if nifty_c is not None and len(nifty_c) > 0:
        ni = nifty_c
        if date is not None:
            ni = ni.loc[:date]
        ni = ni.dropna()
        if len(ni) >= 3:
            nema = ni.ewm(span=200).mean().iloc[-1]
            nifty_ok = float(1 if float(ni.iloc[-1]) > float(nema) else 0)
    f["nifty_ok"] = nifty_ok

    # ── Extra indicator + Monte-Carlo features (ML_EXTRA_FEATURES=1) ──────────
    if _USE_EXTRA_FEATS:
        try:
            f.update(compute_extra_features(c, h, l, v))
        except Exception:
            f.update({k: _NAN for k in EXTRA_FEATURE_COLS})

    # Return in canonical order (any missing key → NaN, tolerated by HistGBM).
    return {k: float(f.get(k, _NAN)) for k in FEATURE_COLUMNS}


def features_to_row(feat: dict) -> list[float]:
    """Feature dict → ordered list matching FEATURE_COLUMNS (for model input)."""
    return [feat.get(k, _NAN) for k in FEATURE_COLUMNS]
