"""
Walk-forward validation engine — the trust backbone.

For a fixed config, roll the *same* ensemble forecast the dashboard makes across many
recent origins, hold out the truth each time, and measure how good (and how honest) the
forecast actually is on THIS ticker:

  * accuracy      : MAPE / MAE / DirAcc of the ensemble median
  * skill         : MASE and skill-vs-random-walk (does it beat "tomorrow = today"?)
  * calibration   : the 10-90% band's real coverage, and a multiplicative band-scale that
                    corrects it to a target coverage (split-conformal, CQR-style)
  * validity      : mean range_ratio of the fed windows (Kronos normalisation sanity)

Everything downstream (autoconfig, the trust card) is computed from this one pass so a
config is judged by evidence, not by guesswork.
"""
import time

import numpy as np

# predict_us lives one level up when imported as `us.validation`, or flat in the Space.
try:
    from us.predict_us import fetch_ohlcv, report_metrics, baseline_skill  # type: ignore
except Exception:  # flat context (Space) or run from inside us/
    from predict_us import fetch_ohlcv, report_metrics, baseline_skill  # type: ignore

_COLS = ["open", "high", "low", "close", "volume"]


def make_windows(n_bars: int, lookback: int, pred_len: int, n_windows: int) -> list:
    """End-indices (exclusive) for rolling origins, spread across the recent slice."""
    span = lookback + pred_len
    first = span + pred_len          # leave room for one extra step back
    last = n_bars
    if first >= last:
        first = span
    return [int(x) for x in np.linspace(first, last, n_windows, dtype=int)]


def _draw_paths(predictor, hist, fut_ts, pred_len, T, top_p, top_k, n_paths, seed):
    import torch
    paths = []
    x_df = hist[_COLS].reset_index(drop=True)
    x_ts = hist["timestamps"].reset_index(drop=True)
    for i in range(n_paths):
        torch.manual_seed(seed + i); np.random.seed(seed + i)
        pred_df = predictor.predict(
            df=x_df, x_timestamp=x_ts, y_timestamp=fut_ts, pred_len=pred_len,
            T=T, top_k=top_k, top_p=top_p, sample_count=1, verbose=False,
        )
        paths.append(pred_df["close"].values.astype(float))
    return np.stack(paths, axis=0)  # (n_paths, pred_len)


def _best_band_scale(median, lo, hi, truth, target, grid=None):
    """Multiplicative scale s so [median±s·halfwidth] hits `target` coverage (CQR-style)."""
    if grid is None:
        grid = np.round(np.arange(0.3, 6.001, 0.05), 3)
    best_s, best_cov, best_gap = 1.0, float("nan"), 1e9
    for s in grid:
        lo_s = median - s * (median - lo)
        hi_s = median + s * (hi - median)
        cov = float(np.mean((truth >= lo_s) & (truth <= hi_s)))
        gap = abs(cov - target)
        # prefer the tightest band whose coverage is closest to target
        if gap < best_gap - 1e-9 or (abs(gap - best_gap) <= 1e-9 and s < best_s):
            best_s, best_cov, best_gap = float(s), cov, gap
    return best_s, best_cov


def _pearson(a, b):
    a = np.asarray(a, float); b = np.asarray(b, float)
    if len(a) < 3 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def compute_ic(records):
    """Information Coefficient: correlation of predicted vs realised step-returns, pooled
    across windows. This is how the Kronos paper judges skill (direction/ranking is what a
    generative price model can actually capture; absolute price level is near-random).
    Returns (IC=Pearson, RankIC=Spearman)."""
    pr, tr = [], []
    for w in records:
        if len(w["median"]) > 1:
            pr.append(np.diff(w["median"])); tr.append(np.diff(w["truth"]))
    if not pr:
        return float("nan"), float("nan")
    pr = np.concatenate(pr); tr = np.concatenate(tr)
    ic = _pearson(pr, tr)
    rank = lambda x: np.argsort(np.argsort(x)).astype(float)
    ric = _pearson(rank(pr), rank(tr))
    return ic, ric


def run_windows(predictor, df, lookback, pred_len, T=0.7, top_p=0.9, top_k=0,
                n_paths=10, windows=None, n_windows=6, seed=123):
    """Draw the ensemble at each rolling origin; return a per-window record list (raw
    arrays + point metrics). Explicit `windows` lets callers share identical origins
    across configs (needed for a fair nested inner/outer split)."""
    if windows is None:
        windows = make_windows(len(df), lookback, pred_len, n_windows)
    records = []
    for end in windows:
        hist = df.iloc[end - lookback - pred_len:end - pred_len]
        fut = df.iloc[end - pred_len:end]
        if len(hist) < lookback or len(fut) < pred_len:
            continue
        fut_ts = fut["timestamps"].reset_index(drop=True)
        paths = _draw_paths(predictor, hist, fut_ts, pred_len, T, top_p, top_k, n_paths, seed)
        median = np.median(paths, axis=0)
        lo = np.quantile(paths, 0.1, axis=0)
        hi = np.quantile(paths, 0.9, axis=0)
        truth = fut["close"].values.astype(float)
        hist_close = hist["close"].values.astype(float)
        wmin, wmax = float(hist_close.min()), float(hist_close.max())
        rec = {"median": median, "lo": lo, "hi": hi, "truth": truth,
               "range_ratio": wmax / wmin if wmin > 0 else float("inf")}
        rec.update(report_metrics(truth, median))
        rec.update(baseline_skill(hist_close, truth, median))
        records.append(rec)
    return records


def aggregate(records, target_coverage=0.8, band_scale=None) -> dict:
    """Summarise a set of window records. If band_scale is None, FIT the conformal scale
    to hit target coverage on these records (calibration set). If a band_scale is given,
    APPLY it and just measure the resulting coverage (test set) — this is how the nested
    outer set reports coverage using a scale fitted only on the inner set."""
    if not records:
        raise ValueError("No valid windows — not enough history for this lookback/pred_len.")
    keys = ["MAE", "RMSE", "MAPE%", "DirAcc%", "MASE", "skill_vs_rw"]
    agg = {k: float(np.nanmean([w[k] for w in records])) for k in keys}
    ic, ric = compute_ic(records)
    agg["IC"] = ic; agg["RankIC"] = ric

    med = np.concatenate([w["median"] for w in records])
    lo = np.concatenate([w["lo"] for w in records])
    hi = np.concatenate([w["hi"] for w in records])
    tr = np.concatenate([w["truth"] for w in records])
    cov_raw = float(np.mean((tr >= lo) & (tr <= hi)))
    if band_scale is None:
        bs, cov_cal = _best_band_scale(med, lo, hi, tr, target_coverage)
    else:
        bs = float(band_scale)
        lo_s = med - bs * (med - lo); hi_s = med + bs * (hi - med)
        cov_cal = float(np.mean((tr >= lo_s) & (tr <= hi_s)))
    rr = [w["range_ratio"] for w in records]
    return {
        "n_windows": len(records),
        "metrics": {k: (round(v, 4) if v == v else None) for k, v in agg.items()},
        "calibration": {"target_coverage": target_coverage,
                        "coverage_raw": round(cov_raw, 4),
                        "band_scale": round(float(bs), 3),
                        "coverage_calibrated": round(cov_cal, 4)},
        "validity": {"range_ratio_mean": round(float(np.mean(rr)), 3),
                     "range_ratio_max": round(float(np.max(rr)), 3)},
    }


def evaluate(predictor, df, lookback, pred_len, T=0.7, top_p=0.9, top_k=0,
             n_paths=10, n_windows=6, seed=123, target_coverage=0.8) -> dict:
    """Single-pass walk-forward for one config (non-nested; used for quick checks)."""
    t0 = time.time()
    records = run_windows(predictor, df, lookback, pred_len, T=T, top_p=top_p, top_k=top_k,
                          n_paths=n_paths, n_windows=n_windows, seed=seed)
    out = aggregate(records, target_coverage)
    out["config"] = {"lookback": lookback, "pred_len": pred_len, "T": T, "top_p": top_p,
                     "top_k": top_k, "n_paths": n_paths}
    out["secs"] = round(time.time() - t0, 1)
    return out
