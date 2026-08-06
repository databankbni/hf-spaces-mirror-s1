"""
Data + metric helpers for the hosted dashboard (trimmed, no matplotlib/CLI).
Mirrors the functions of the same name in ../predict_us.py.
"""
import numpy as np
import pandas as pd


def _clamp_intraday_period(interval: str, period: str) -> str:
    """yfinance only serves intraday history for a limited window: minute bars ~60d
    (1m/2m ~7d), hourly ~730d. Clamp long periods for intraday so it still returns data."""
    iv = interval.lower()
    if iv.endswith("m") and not iv.endswith("mo"):
        return "7d" if iv in ("1m", "2m") else "60d"
    if iv.endswith("h"):
        return "730d"
    return period


def fetch_ohlcv(ticker: str, interval: str, period: str) -> pd.DataFrame:
    """Download OHLCV via yfinance and normalise to Kronos' expected schema."""
    import yfinance as yf

    period = _clamp_intraday_period(interval, period)
    raw = yf.download(ticker, interval=interval, period=period,
                      auto_adjust=True, progress=False)
    if raw is None or raw.empty:
        raise RuntimeError(
            f"No data returned for {ticker} ({interval}, {period}). "
            f"Intraday history is limited (5m≈60d, 1h≈730d)."
        )

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw.rename(columns=str.lower)
    df = raw[["open", "high", "low", "close", "volume"]].copy()
    df = df.dropna().reset_index()
    ts_col = "Date" if "Date" in df.columns else "Datetime"
    df = df.rename(columns={ts_col: "timestamps"})
    df["timestamps"] = pd.to_datetime(df["timestamps"]).dt.tz_localize(None)
    return df


def future_timestamps(last_ts: pd.Timestamp, interval: str, n: int) -> pd.Series:
    """Generate n future timestamps after last_ts, respecting the bar interval."""
    if interval.endswith("d"):
        idx = pd.bdate_range(start=last_ts, periods=n + 1, freq="C")[1:]
    elif interval.endswith("h"):
        idx = pd.date_range(start=last_ts, periods=n + 1, freq="h")[1:]
    else:
        step = int("".join(c for c in interval if c.isdigit()) or "1")
        idx = pd.date_range(start=last_ts, periods=n + 1, freq=f"{step}min")[1:]
    return pd.Series(idx)


def report_metrics(truth: np.ndarray, pred: np.ndarray) -> dict:
    """Accuracy metrics on the close price."""
    mae = float(np.mean(np.abs(pred - truth)))
    rmse = float(np.sqrt(np.mean((pred - truth) ** 2)))
    mape = float(np.mean(np.abs((pred - truth) / truth)) * 100)
    dir_truth = np.sign(np.diff(truth))
    dir_pred = np.sign(np.diff(pred))
    da = float(np.mean(dir_truth == dir_pred) * 100) if len(dir_truth) else float("nan")
    return {"MAE": mae, "RMSE": rmse, "MAPE%": mape, "DirAcc%": da}


def baseline_skill(hist_close: np.ndarray, truth: np.ndarray, pred: np.ndarray) -> dict:
    """MASE (vs in-sample one-step naive) + skill-vs-random-walk (vs flat persistence).
    <1 means the forecast beats doing nothing; the core trust yardstick."""
    hist_close = np.asarray(hist_close, float)
    truth = np.asarray(truth, float)
    pred = np.asarray(pred, float)
    mae = float(np.mean(np.abs(pred - truth)))
    scale = float(np.mean(np.abs(np.diff(hist_close)))) if len(hist_close) > 1 else float("nan")
    mase = mae / scale if scale and scale > 1e-9 else float("nan")
    last = hist_close[-1]
    mae_rw = float(np.mean(np.abs(last - truth)))
    skill = mae / mae_rw if mae_rw > 1e-9 else float("nan")
    return {"MASE": mase, "skill_vs_rw": skill, "MAE_rw": mae_rw}
