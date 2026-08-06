"""
Ensemble inference engine for the hosted dashboard.
Same logic as ../engine.py but with flat imports (Space repo is self-contained).
"""
import json
import time
from pathlib import Path

import numpy as np

from model import Kronos, KronosTokenizer, KronosPredictor
from predict_us import fetch_ohlcv, future_timestamps, report_metrics

_COLS = ["open", "high", "low", "close", "volume"]
_PROFILE_DIR = Path(__file__).resolve().parent / "out" / "profiles"


def load_profile(ticker: str, interval: str = "1d"):
    """Return the cached trust profile for a ticker (from autoconfig.py), or None."""
    p = _PROFILE_DIR / f"{ticker.upper()}_{interval}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

# When the lookback window's max/min close exceeds this, Kronos' per-window
# normalisation gets skewed by the trend and forecasts can collapse. Warn above it.
_RANGE_THRESH = 2.0
_MIN_LOOKBACK = 40

_PREDICTOR = None
_PREDICTOR_KEY = None


def get_predictor(device: str = "cpu", max_context: int = 512,
                  model_id: str = "NeoQuasar/Kronos-small",
                  tokenizer_id: str = "NeoQuasar/Kronos-Tokenizer-base"):
    global _PREDICTOR, _PREDICTOR_KEY
    key = (device, max_context, model_id, tokenizer_id)
    if _PREDICTOR is None or _PREDICTOR_KEY != key:
        tokenizer = KronosTokenizer.from_pretrained(tokenizer_id)
        model = Kronos.from_pretrained(model_id)
        tokenizer.eval()
        model.eval()
        _PREDICTOR = KronosPredictor(model, tokenizer, device=device, max_context=max_context)
        _PREDICTOR_KEY = key
    return _PREDICTOR


def is_loaded() -> bool:
    return _PREDICTOR is not None


def run_ensemble(ticker: str = "AAPL", interval: str = "1d", period: str = "3y",
                 lookback: int = 120, pred_len: int = 20, mode: str = "backtest",
                 n_paths: int = 20, T: float = 0.7, top_p: float = 0.9, top_k: int = 0,
                 seed: int = 123, device: str = "cpu", ctx_tail: int = 120,
                 band_scale: float = 1.0) -> dict:
    import random
    import torch

    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)

    df = fetch_ohlcv(ticker, interval, period)
    need = lookback + (pred_len if mode == "backtest" else 0)
    if len(df) < need:
        raise ValueError(
            f"Not enough bars for {ticker}: have {len(df)}, need {need}. "
            f"Lower lookback/pred_len or raise period."
        )

    if mode == "backtest":
        hist = df.iloc[-(lookback + pred_len):-pred_len]
        fut = df.iloc[-pred_len:]
        y_ts = fut["timestamps"].reset_index(drop=True)
    else:
        hist = df.iloc[-lookback:]
        fut = None
        y_ts = future_timestamps(hist["timestamps"].iloc[-1], interval, pred_len)

    x_df = hist[_COLS].reset_index(drop=True)
    x_ts = hist["timestamps"].reset_index(drop=True)

    predictor = get_predictor(device=device)

    t0 = time.time()
    paths = []
    for i in range(n_paths):
        torch.manual_seed(seed + i); np.random.seed(seed + i)
        pred_df = predictor.predict(
            df=x_df, x_timestamp=x_ts, y_timestamp=y_ts, pred_len=pred_len,
            T=T, top_k=top_k, top_p=top_p, sample_count=1, verbose=False,
        )
        paths.append(pred_df["close"].values.astype(float))
    paths = np.stack(paths, axis=0)
    elapsed = time.time() - t0

    median = np.median(paths, axis=0)
    lo = np.quantile(paths, 0.1, axis=0)
    hi = np.quantile(paths, 0.9, axis=0)
    if band_scale and band_scale != 1.0:
        lo = median - band_scale * (median - lo)
        hi = median + band_scale * (hi - median)

    def _iso(ts_series):
        return [pd_ts.isoformat() for pd_ts in ts_series]

    # Kronos normalises by the lookback window's mean/std; if that window spans a huge
    # price range (a strong trend), the latest price is an extreme outlier and forecasts
    # collapse toward the window mean. Flag it and suggest a shorter, tighter window.
    win = hist["close"].values.astype(float)
    range_ratio = float(win.max() / win.min()) if win.min() > 0 else float("inf")
    warning = None
    if range_ratio >= _RANGE_THRESH:
        suggest = None
        for L in range(len(win), _MIN_LOOKBACK, -1):
            w = win[-L:]
            if w.min() > 0 and w.max() / w.min() < _RANGE_THRESH:
                suggest = L  # monotonic: first hit scanning down = largest safe window
                break
        warning = {"type": "wide_range", "range_ratio": round(range_ratio, 2),
                   "suggest_lookback": suggest}

    ctx = hist.iloc[-ctx_tail:]
    out = {
        "meta": {
            "ticker": ticker, "interval": interval, "period": period, "mode": mode,
            "lookback": lookback, "pred_len": pred_len, "n_paths": n_paths,
            "T": T, "top_p": top_p, "top_k": top_k, "elapsed": round(elapsed, 1),
            "range_ratio": round(range_ratio, 2), "band_scale": round(band_scale, 3),
        },
        "warning": warning,
        "history": {
            "t": _iso(ctx["timestamps"]),
            "close": [float(v) for v in ctx["close"].values],
        },
        "forecast": {
            "t": _iso(y_ts),
            "median": [float(v) for v in median],
            "lo": [float(v) for v in lo],
            "hi": [float(v) for v in hi],
            "paths": [[float(v) for v in p] for p in paths],
        },
        "truth": None,
        "metrics": None,
    }

    if mode == "backtest":
        truth = fut["close"].values.astype(float)
        out["truth"] = {"t": _iso(fut["timestamps"]), "close": [float(v) for v in truth]}
        m = report_metrics(truth, median)
        cover = float(np.mean((truth >= lo) & (truth <= hi)) * 100)
        m["coverage%"] = cover
        out["metrics"] = {k: round(v, 3) for k, v in m.items()}

    return out
