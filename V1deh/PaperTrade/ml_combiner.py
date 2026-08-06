"""
ml_combiner.py — ML signal filter for NSE equity strategies.

15-feature logistic regression trained walk-forward (13 folds).
Threshold 0.60 for signal upgrade → Mode D in trial_run.py.
Upgrade to RandomForest only if LR achieves OOS accuracy > 58% with t > 1.5.

Features (T-1 lagged, no lookahead):
  Technical (10): RSI, BB position, volume ratio, shadow recovery flag,
                  OBV z-score, 52W proximity, RS vs Nifty 3M,
                  EMA stack score, MACD sign, ADX normalized
  Macro (5): VIX level, VIX slope, S&P500 5D ret, USD/INR 5D chg, crude 5D chg
"""

from __future__ import annotations
import sys
import os
import warnings
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score
try:
    from xgboost import XGBClassifier
    _HAS_XGB = True
except ImportError:
    _HAS_XGB = False

sys.path.insert(0, os.path.dirname(__file__))
from trial_run import (
    load_data, vix_mask_series, rsi, obv, macd_h, adx_s,
    H_LABELS, HORIZONS, UNIVERSE,
)

try:
    from macro_context import MacroContext
    _HAS_MACRO = True
except ImportError:
    _HAS_MACRO = False

warnings.filterwarnings("ignore")

START = "2019-01-01"
END   = "2024-01-01"
PROB_THRESHOLD = 0.60
MIN_TRAIN_ROWS = 500
OOS_UPGRADE_THRESHOLD = 0.58
OOS_T_THRESHOLD = 1.5


def bollinger_position(c: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.Series:
    """Normalized position within Bollinger Band: 0=lower, 0.5=mid, 1=upper."""
    mid = c.rolling(window).mean()
    std = c.rolling(window).std()
    lo  = mid - n_std * std
    hi  = mid + n_std * std
    pos = (c - lo) / (hi - lo + 1e-9)
    return pos.clip(0, 1)


def ema_stack_score(c: pd.Series) -> pd.Series:
    """0–1: fraction of the 4 EMA stack conditions satisfied."""
    e20  = c.ewm(span=20).mean()
    e50  = c.ewm(span=50).mean()
    e100 = c.ewm(span=100).mean()
    e200 = c.ewm(span=200).mean()
    score = (
        (c > e20).astype(float) +
        (e20 > e50).astype(float) +
        (e50 > e100).astype(float) +
        (e100 > e200).astype(float)
    ) / 4.0
    return score


def shadow_flag(c: pd.Series, l: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.Series:
    """1 if intraday shadow recovery (low<BB_lower AND close>BB_lower), else 0."""
    mid = c.rolling(window).mean()
    lo  = mid - n_std * c.rolling(window).std()
    flag = ((l < lo) & (c > lo)).astype(float)
    return flag


def build_feature_matrix(
    sc: pd.DataFrame,
    sh: pd.DataFrame,
    sl: pd.DataFrame,
    sv: pd.DataFrame,
    nifty_c: pd.Series,
    vix_c: pd.Series | None,
    macro_features: pd.DataFrame | None,
    horizon_days: int,
    fii_score: float = 0.0,
    signal_counts: dict | None = None,
) -> pd.DataFrame:
    """
    Build (date, ticker) feature matrix with target label.
    fii_score: −1.0 (RISK_OFF) / 0.0 (NEUTRAL) / +1.0 (FII_STRONG_BUY) — same for all tickers.
    signal_counts: optional dict {(date, ticker): n_strategies_active} for n_strats feature.
    All features are lagged T-1 (shift(1)) to prevent lookahead.
    Target: 1 if stock return over horizon_days > 0, else 0.
    """
    rows = []
    nifty_arr = nifty_c.values
    nifty_idx_map = {ts: i for i, ts in enumerate(nifty_c.index)}

    for tk in sc.columns:
        c  = sc[tk].dropna()
        h  = sh[tk].reindex(c.index).ffill()
        l  = sl[tk].reindex(c.index).ffill()
        v  = sv[tk].reindex(c.index).ffill()

        if len(c) < 300:
            continue

        ni   = nifty_c.reindex(c.index).ffill()
        v20  = v.rolling(20).mean()
        w52  = c.rolling(252).max()

        # Technical features
        rsi_s   = rsi(c, 14) / 100.0
        bb_pos  = bollinger_position(c)
        vol_r   = (v / (v20 + 1e-9)).clip(0, 5) / 5.0
        shad    = shadow_flag(c, l)
        obv_s   = obv(c, v)
        obv_z   = (obv_s - obv_s.rolling(63).mean()) / (obv_s.rolling(63).std() + 1e-9)
        prox52  = (c / (w52 + 1e-9)).clip(0, 1)
        rs3m    = (c / c.shift(63) - 1) - (ni / ni.shift(63) - 1)
        ema_sc  = ema_stack_score(c)
        mh      = macd_h(c).apply(lambda x: 1.0 if x > 0 else -1.0)
        adx_n   = (adx_s(h, l, c) / 50.0).clip(0, 1)

        # ── New v6 features: TTM Squeeze, RSI Divergence, VCP ───────────────
        sma20 = c.rolling(20).mean()
        std20 = c.rolling(20).std()
        ema20 = c.ewm(span=20, adjust=False).mean()
        tr    = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        kc_upper = ema20 + 1.5 * atr14
        kc_lower = ema20 - 1.5 * atr14
        ttm_squeeze = ((bb_upper < kc_upper) & (bb_lower > kc_lower)).astype(float)

        rsi14_full = rsi(c, 14)
        price_low10 = c.rolling(10).min()
        near_low_ml = (c <= price_low10 * 1.015).astype(float)
        rsi_was_os  = (rsi14_full.shift(3) < 40).astype(float)
        rsi_recov   = (rsi14_full > rsi14_full.shift(3)).astype(float)
        rsi_diverg  = (near_low_ml * rsi_was_os * rsi_recov).clip(0, 1)

        sma50  = c.rolling(50).mean()
        sma200 = c.rolling(200).mean()
        sma200_rising = (sma200 > sma200.shift(20)).astype(float)
        near_high52 = (c >= c.rolling(252).max() * 0.75).astype(float)
        range10 = h.rolling(10).max() - l.rolling(10).min()
        contraction = (range10 < range10.shift(10) * 0.75).astype(float)
        vol_dry = (v < 0.8 * v20).astype(float)
        vcp_flag = (sma200_rising * near_high52 * contraction.shift(1) * vol_dry.shift(1)).clip(0, 1)

        feat_df = pd.DataFrame({
            "rsi":        rsi_s,
            "bb_pos":     bb_pos,
            "vol_r":      vol_r,
            "shadow":     shad,
            "obv_z":      obv_z.clip(-3, 3) / 3.0,
            "prox52":     prox52,
            "rs3m":       rs3m.clip(-0.5, 0.5),
            "ema_sc":     ema_sc,
            "macd_s":     mh,
            "adx_n":      adx_n,
            # v6 analyst-derived features
            "ttm_squeeze": ttm_squeeze,
            "rsi_diverg":  rsi_diverg,
            "vcp_flag":    vcp_flag,
        }, index=c.index)

        # Add macro features if available
        if macro_features is not None:
            for col in ["vix_norm", "vix_slope", "sp500_5d", "usdinr_5d", "crude_5d"]:
                if col in macro_features.columns:
                    feat_df[col] = macro_features[col].reindex(c.index).ffill().fillna(0)
                else:
                    feat_df[col] = 0.0
        else:
            feat_df["vix_norm"]  = 0.0
            feat_df["vix_slope"] = 0.0
            feat_df["sp500_5d"]  = 0.0
            feat_df["usdinr_5d"] = 0.0
            feat_df["crude_5d"]  = 0.0

        # Stage 2 breadth (cross-sectional): % of sc universe in Stage 2 on each date
        _sma150 = sc.rolling(150).mean()
        _sma150_rising = _sma150 > _sma150.shift(10)
        _above_sma150 = sc > _sma150
        stage2_ts = (_above_sma150 & _sma150_rising).mean(axis=1)  # per-date breadth
        feat_df["stage2_breadth"] = stage2_ts.reindex(c.index).ffill().fillna(0.5)

        # FII score: scalar broadcast (same value for all tickers on all dates in this run)
        feat_df["fii_score"] = float(fii_score)

        # ── Momentum / signal-density features (v7) ─────────────────────────
        # Short-term return momentum (raw pct changes, clipped to ±30%)
        feat_df["ret_1d"] = c.pct_change(1).clip(-0.3, 0.3)
        feat_df["ret_3d"] = c.pct_change(3).clip(-0.3, 0.3)
        feat_df["ret_5d"] = c.pct_change(5).clip(-0.3, 0.3)
        # Volume trend: 5D rolling vs 20D avg (rising = accumulation)
        v20_ratio = v / (v.rolling(20).mean() + 1e-9)
        feat_df["vol_trend_5d"] = v20_ratio.rolling(5).mean().clip(0, 5) / 5.0
        # n_strats: if signal_counts provided, count strategies active in last 3 bars
        if signal_counts:
            _ns = pd.Series(
                {d: signal_counts.get((d, tk), 0) for d in c.index},
                dtype=float
            )
            feat_df["n_strats"] = _ns.rolling(3, min_periods=1).max().clip(0, 10) / 10.0
        else:
            feat_df["n_strats"] = 0.0

        # Lag all features by 1 day (use T-1 to predict T direction)
        feat_df = feat_df.shift(1)

        # Compute forward return label
        c_arr = c.values
        for i in range(len(c) - horizon_days):
            fwd_ret = (c_arr[i + horizon_days] / c_arr[i]) - 1
            label   = int(fwd_ret > 0)
            date    = c.index[i]

            npos = nifty_idx_map.get(date)
            if npos is None or npos + horizon_days >= len(nifty_arr):
                continue
            nifty_fwd = (nifty_arr[npos + horizon_days] / nifty_arr[npos]) - 1

            row_feat = feat_df.iloc[i]
            if row_feat.isna().any():
                continue

            row = {
                "date":      date,
                "ticker":    tk,
                "label":     label,
                "fwd_ret":   fwd_ret,
                "nifty_fwd": nifty_fwd,
            }
            row.update(row_feat.to_dict())
            rows.append(row)

    return pd.DataFrame(rows)


def _build_macro_feat(vix_c: pd.Series | None, mc_obj) -> pd.DataFrame | None:
    """
    Build raw (un-lagged) macro features.
    Caller (build_feature_matrix) will apply shift(1) for all features together.
    Uses mc_obj._raw (raw prices, not pre-shifted _features) to avoid double-lag.
    """
    frames = {}
    if vix_c is not None:
        vx = vix_c
        frames["vix_norm"]  = (vx / 20.0).clip(0, 2)
        frames["vix_slope"] = vx.ewm(span=5).mean().diff().clip(-2, 2)

    if mc_obj is not None and hasattr(mc_obj, "_raw") and mc_obj._raw is not None:
        raw = mc_obj._raw  # columns: sp500, usdinr, crude (raw prices, no shift)
        if "sp500" in raw.columns:
            frames["sp500_5d"]  = raw["sp500"].pct_change(5).clip(-0.1, 0.1)
        if "usdinr" in raw.columns:
            frames["usdinr_5d"] = (raw["usdinr"].pct_change(5) * 100).clip(-5, 5) / 5.0
        if "crude" in raw.columns:
            frames["crude_5d"]  = (raw["crude"].pct_change(5) * 100).clip(-20, 20) / 20.0

    if not frames:
        return None
    return pd.DataFrame(frames)


def walk_forward_ml(
    feat_matrix: pd.DataFrame,
    splits,
    use_rf: bool = False,
    use_xgb: bool = True,
) -> tuple[list[dict], list[float], list[float]]:
    """
    Walk-forward ML training. Returns (fold_stats, oos_probs, oos_labels).
    use_xgb=True (default): XGBoost if installed — better for non-linear feature interactions.
    use_rf: RandomForest override (legacy, lower priority than XGB).
    """
    FEAT_COLS = [c for c in feat_matrix.columns
                 if c not in ("date", "ticker", "label", "fwd_ret", "nifty_fwd")]
    fold_stats = []
    all_probs  = []
    all_labels = []

    for sp in splits:
        train_mask = (feat_matrix["date"] >= sp["train_start"]) & \
                     (feat_matrix["date"] < sp["train_end"])
        test_mask  = (feat_matrix["date"] >= sp["test_start"]) & \
                     (feat_matrix["date"] < sp["test_end"])

        tr = feat_matrix[train_mask].dropna(subset=FEAT_COLS)
        te = feat_matrix[test_mask].dropna(subset=FEAT_COLS)

        if len(tr) < MIN_TRAIN_ROWS or len(te) < 10:
            fold_stats.append({"fold": sp["fold"], "acc": np.nan, "n_signals": 0,
                               "oos_acc": np.nan, "signal_acc": np.nan})
            continue

        X_tr = tr[FEAT_COLS].values
        y_tr = tr["label"].values
        X_te = te[FEAT_COLS].values
        y_te = te["label"].values

        if use_xgb and _HAS_XGB:
            # XGBoost: best for non-linear interactions; no scaling needed
            model = Pipeline([
                ("clf", XGBClassifier(
                    n_estimators=100, max_depth=4,
                    learning_rate=0.1, subsample=0.8,
                    colsample_bytree=0.8, eval_metric="logloss",
                    use_label_encoder=False,
                    random_state=42, verbosity=0,
                )),
            ])
        elif use_rf:
            model = Pipeline([
                ("scaler", StandardScaler()),
                ("clf", RandomForestClassifier(
                    n_estimators=100, max_depth=5,
                    min_samples_leaf=50, class_weight="balanced",
                    random_state=42,
                )),
            ])
        else:
            model = Pipeline([
                ("scaler", StandardScaler()),
                ("clf", LogisticRegression(
                    C=0.1, class_weight="balanced",
                    max_iter=1000, solver="lbfgs", random_state=42,
                )),
            ])

        model.fit(X_tr, y_tr)
        probs = model.predict_proba(X_te)[:, 1]  # prob of up-day

        oos_acc    = accuracy_score(y_te, (probs >= 0.5).astype(int)) * 100
        signal_mask = probs >= PROB_THRESHOLD
        n_sigs      = signal_mask.sum()
        sig_acc     = (y_te[signal_mask] == 1).mean() * 100 if n_sigs > 0 else np.nan

        fold_stats.append({
            "fold":       sp["fold"],
            "test_start": sp["test_start"].strftime("%Y-%m"),
            "test_end":   sp["test_end"].strftime("%Y-%m"),
            "oos_acc":    round(oos_acc, 1),
            "n_signals":  int(n_sigs),
            "signal_acc": round(sig_acc, 1) if not np.isnan(sig_acc) else np.nan,
            "n_test":     len(te),
        })
        all_probs.extend(probs.tolist())
        all_labels.extend(y_te.tolist())

    return fold_stats, all_probs, all_labels


def evaluate_oos(probs: list[float], labels: list[int]) -> dict:
    if not probs:
        return {}
    p = np.array(probs)
    y = np.array(labels)

    oos_acc = (y == (p >= 0.5).astype(int)).mean() * 100
    sig_mask = p >= PROB_THRESHOLD
    n_sigs = sig_mask.sum()
    sig_rets = y[sig_mask].astype(float) * 2 - 1  # +1 / -1
    sig_acc  = (y[sig_mask] == 1).mean() * 100 if n_sigs > 0 else np.nan

    t = 0.0
    if n_sigs >= 5 and sig_rets.std() > 0:
        t, _ = scipy_stats.ttest_1samp(sig_rets, 0)

    return {
        "oos_acc":   round(oos_acc, 1),
        "n_signals": int(n_sigs),
        "sig_acc":   round(sig_acc, 1) if not np.isnan(sig_acc) else None,
        "t_stat":    round(t, 2),
        "upgrade":   (oos_acc / 100) > OOS_UPGRADE_THRESHOLD and t > OOS_T_THRESHOLD,
    }


def main():
    from datetime import datetime
    from walk_forward import generate_wf_splits

    print("=" * 74)
    print("  ML COMBINER — Walk-Forward Feature Validation")
    print(f"  Period: {START} → {END}  |  Run: {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("=" * 74)

    print("\n  Loading data...")
    sc, sh, sl, sv, nifty_c, vix_c = load_data()

    mc_obj = None
    if _HAS_MACRO:
        try:
            mc_obj = MacroContext()
            mc_obj.load(START, END)
            print(f"  Macro context: {mc_obj.summary()}")
        except Exception as e:
            print(f"  Macro context skipped: {e}")

    macro_feat = _build_macro_feat(vix_c, mc_obj)

    horizon_label = "1D"
    horizon_days  = HORIZONS[H_LABELS.index(horizon_label)]

    print(f"\n  Building feature matrix ({horizon_label} horizon)...")
    feat_matrix = build_feature_matrix(
        sc, sh, sl, sv, nifty_c, vix_c, macro_feat, horizon_days
    )
    print(f"  Rows: {len(feat_matrix):,} | Features: "
          f"{len([c for c in feat_matrix.columns if c not in ('date','ticker','label','fwd_ret','nifty_fwd')])}")
    print(f"  Up-day base rate: {feat_matrix['label'].mean()*100:.1f}%")

    splits = generate_wf_splits()
    print(f"  Walk-forward splits: {len(splits)}")

    print("\n  Training Logistic Regression (walk-forward)...")
    fold_stats, all_probs, all_labels = walk_forward_ml(feat_matrix, splits, use_rf=False)

    overall = evaluate_oos(all_probs, all_labels)

    print(f"\n{'─'*74}")
    print(f"  {'Fold':>4}  {'Period':>14}  {'OOS Acc':>8}  {'N Signals':>10}  {'Signal Acc':>11}")
    print(f"  {'─'*60}")
    for fs in fold_stats:
        oos_s = f"{fs['oos_acc']:.1f}%" if not np.isnan(fs.get('oos_acc', np.nan)) else "  N/A"
        sig_s = f"{fs['signal_acc']:.1f}%" if fs.get('signal_acc') and not np.isnan(fs['signal_acc']) else "  N/A"
        print(f"  {fs['fold']:>4}  "
              f"{fs.get('test_start','?'):>7}–{fs.get('test_end','?'):<7}  "
              f"{oos_s:>8}  {fs['n_signals']:>10}  {sig_s:>11}")

    print(f"\n{'═'*74}")
    print(f"  OVERALL OOS RESULTS (LogisticRegression, threshold={PROB_THRESHOLD})")
    print(f"{'─'*74}")
    if overall:
        print(f"  OOS accuracy (>0.5): {overall['oos_acc']}%")
        print(f"  High-confidence signals (prob>{PROB_THRESHOLD}): {overall['n_signals']}")
        print(f"  Signal accuracy: {overall['sig_acc']}%")
        print(f"  t-stat on signals: {overall['t_stat']}")
        upgrade = overall.get("upgrade", False)
        print(f"  Upgrade to RandomForest: {'YES' if upgrade else 'NO (LR criteria not met)'}")
    else:
        print("  No OOS data collected.")
        upgrade = False

    if upgrade:
        print("\n  Training RandomForest (upgrade criteria met)...")
        fold_stats_rf, probs_rf, labels_rf = walk_forward_ml(feat_matrix, splits, use_rf=True)
        overall_rf = evaluate_oos(probs_rf, labels_rf)
        print(f"  RF OOS accuracy: {overall_rf['oos_acc']}% | "
              f"Signal accuracy: {overall_rf['sig_acc']}% | "
              f"N={overall_rf['n_signals']} | t={overall_rf['t_stat']}")
        use_rf_final = (overall_rf.get("sig_acc") or 0) > (overall.get("sig_acc") or 0)
        print(f"  Use RF for Mode D: {'YES' if use_rf_final else 'NO — keep LR'}")

    # Save results
    md_lines = [
        "# ML Combiner Results",
        f"",
        f"Period: {START} → {END} | Run: {datetime.now().strftime('%d %b %Y %H:%M')}",
        f"Horizon: {horizon_label} | Model: LogisticRegression(C=0.1) | Threshold: {PROB_THRESHOLD}",
        f"",
        f"## Per-Fold Results",
        f"",
        f"| Fold | Test Period | OOS Acc | N Signals (prob>{PROB_THRESHOLD}) | Signal Acc |",
        f"|---|---|---|---|---|",
    ]
    for fs in fold_stats:
        oos_s = f"{fs['oos_acc']:.1f}%" if not np.isnan(fs.get('oos_acc', np.nan)) else "N/A"
        sig_s = f"{fs['signal_acc']:.1f}%" if fs.get('signal_acc') and not np.isnan(fs['signal_acc']) else "N/A"
        period = f"{fs.get('test_start','?')}–{fs.get('test_end','?')}"
        md_lines.append(f"| {fs['fold']} | {period} | {oos_s} | {fs['n_signals']} | {sig_s} |")

    if overall:
        md_lines += [
            f"",
            f"## Overall OOS Summary",
            f"",
            f"| Metric | Value |",
            f"|---|---|",
            f"| OOS accuracy (all predictions) | {overall['oos_acc']}% |",
            f"| High-confidence signals (prob>{PROB_THRESHOLD}) | {overall['n_signals']} |",
            f"| Signal accuracy | {overall['sig_acc']}% |",
            f"| t-stat on signals | {overall['t_stat']} |",
            f"| RF upgrade triggered | {'Yes' if overall.get('upgrade') else 'No'} |",
        ]

    outfile = "/Users/videkhanna/Documents/Projects/NYCFC/ml_combiner_results.md"
    with open(outfile, "w") as fp:
        fp.write("\n".join(md_lines))
    print(f"\n  Results saved → ml_combiner_results.md")
    print("=" * 74)


if __name__ == "__main__":
    main()
