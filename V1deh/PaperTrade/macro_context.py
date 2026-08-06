"""
macro_context.py — Cross-asset macro environment for Mode C filtering.

Downloads S&P 500, USD/INR, and crude oil daily data via yfinance.
Builds boolean features lagged T-1 to prevent lookahead.
Composite gate: global_risk_on = sp500_trend AND usdinr_stable AND NOT crude_spike
"""

import yfinance as yf
import pandas as pd


class MacroContext:
    TICKERS = {
        "^GSPC":    "sp500",
        "USDINR=X": "usdinr",
        "CL=F":     "crude",
    }

    def __init__(self):
        self._features: pd.DataFrame | None = None

    def load(self, start: str, end: str) -> "MacroContext":
        frames = {}
        for ytk, name in self.TICKERS.items():
            try:
                raw = yf.download(ytk, start=start, end=end,
                                  auto_adjust=True, progress=False)
                if raw.empty:
                    raise ValueError(f"No data for {ytk}")
                close = raw["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                frames[name] = close.rename(name)
            except Exception as e:
                import logging as _log
                _log.getLogger(__name__).warning("macro_context: could not download %s: %s", ytk, e)
                frames[name] = None

        available = {k: v for k, v in frames.items() if v is not None}
        if not available:
            raise RuntimeError("No macro data could be downloaded. Check internet connection.")

        self._raw = pd.DataFrame(available).sort_index()
        self._build_features()
        return self

    def _build_features(self):
        df = self._raw.copy()

        feat = pd.DataFrame(index=df.index)

        # S&P 500: 5-day momentum positive AND price above 20-day MA
        if "sp500" in df.columns:
            sp = df["sp500"]
            feat["sp500_5d_ret"]   = sp.pct_change(5)
            feat["sp500_above_ma"] = sp > sp.rolling(20).mean()
            feat["sp500_trend"]    = (feat["sp500_5d_ret"] > 0) & feat["sp500_above_ma"]
        else:
            feat["sp500_trend"] = True  # assume benign if unavailable

        # USD/INR: stable if 5-day change within ±1% (rupee not spiking)
        if "usdinr" in df.columns:
            fx = df["usdinr"]
            feat["usdinr_5d_chg"] = fx.pct_change(5) * 100
            feat["usdinr_stable"] = feat["usdinr_5d_chg"].abs() <= 1.0
        else:
            feat["usdinr_stable"] = True

        # Crude oil: no spike if 5-day change within ±5%
        if "crude" in df.columns:
            cr = df["crude"]
            feat["crude_5d_chg"]  = cr.pct_change(5) * 100
            feat["crude_spike"]   = feat["crude_5d_chg"].abs() > 5.0
        else:
            feat["crude_spike"] = False

        # Composite gate (all conditions must hold)
        feat["global_risk_on"] = (
            feat["sp500_trend"] &
            feat["usdinr_stable"] &
            ~feat["crude_spike"]
        )

        # Drop warmup rows where indicators are NaN (rolling/pct_change warmup period).
        # bool(NaN) == True in Python, so keeping these rows would cause the gate to
        # silently pass as Risk-ON during the first ~20 bars of data.
        feat = feat.dropna(subset=["sp500_trend", "usdinr_stable", "crude_spike"])

        # Lag all features by 1 trading day (use T-1 data to predict T direction)
        self._features = feat.shift(1)

    def get(self, date: pd.Timestamp) -> dict:
        if self._features is None:
            return {}
        try:
            row = self._features.loc[date]
            return {
                "sp500_trend":    bool(row.get("sp500_trend", True)),
                "usdinr_stable":  bool(row.get("usdinr_stable", True)),
                "crude_spike":    bool(row.get("crude_spike", False)),
                "global_risk_on": bool(row.get("global_risk_on", False)),
            }
        except KeyError:
            return {}

    def build_mask(self, index: pd.DatetimeIndex) -> pd.Series:
        """Return boolean Series aligned to `index` — True where global_risk_on."""
        if self._features is None:
            return pd.Series(False, index=index)
        risk_on = self._features["global_risk_on"].reindex(index, method="ffill").fillna(False)
        return risk_on.astype(bool)

    def summary(self) -> str:
        if self._features is None:
            return "MacroContext: not loaded"
        n = len(self._features)
        pct = self._features["global_risk_on"].sum() / n * 100
        return (
            f"MacroContext loaded: {n} days | "
            f"global_risk_on: {pct:.1f}% of days | "
            f"sp500_trend: {self._features['sp500_trend'].mean()*100:.1f}% | "
            f"usdinr_stable: {self._features['usdinr_stable'].mean()*100:.1f}% | "
            f"crude_spike: {self._features['crude_spike'].mean()*100:.1f}%"
        )


def load_macro(start: str = "2019-01-01", end: str = "2024-01-01") -> MacroContext:
    mc = MacroContext()
    mc.load(start, end)
    return mc


_GIFT_CACHE: dict = {"data": None, "ts": 0}
_GIFT_TTL = 900  # 15-minute cache


def get_gift_nifty_pulse() -> dict:
    """
    Fetch GIFT Nifty (^NSGIFTNIFTY) pre-market change %.

    GIFT Nifty trades in GIFT City when NSE is closed — it's the overnight
    futures proxy for where Nifty opens next session. Strong signal for
    INTRADAY and 1D predictions. Cached 15 minutes.

    Returns dict with keys: price, prev_close, change_pct, direction, source.
    direction is BULLISH (>+0.2%), BEARISH (<-0.2%), or NEUTRAL.
    """
    import time
    global _GIFT_CACHE
    now = time.time()
    if _GIFT_CACHE["data"] and (now - _GIFT_CACHE["ts"]) < _GIFT_TTL:
        return _GIFT_CACHE["data"]

    try:
        ticker = yf.Ticker("^NSGIFTNIFTY")
        fi = ticker.fast_info
        price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
        prev_close = getattr(fi, "previous_close", None) or getattr(fi, "regular_market_previous_close", None)
        if price and prev_close and float(prev_close) > 0:
            change_pct = (float(price) / float(prev_close) - 1) * 100
        else:
            df = yf.download("^NSGIFTNIFTY", period="2d", progress=False, auto_adjust=True)
            if len(df) >= 2:
                closes = df["Close"].squeeze()
                price = float(closes.iloc[-1])
                prev_close = float(closes.iloc[-2])
                change_pct = (price / prev_close - 1) * 100
            else:
                change_pct = 0.0
                price = prev_close = None

        direction = "BULLISH" if change_pct > 0.2 else ("BEARISH" if change_pct < -0.2 else "NEUTRAL")
        result = {
            "price": round(float(price), 2) if price else None,
            "prev_close": round(float(prev_close), 2) if prev_close else None,
            "change_pct": round(change_pct, 2),
            "direction": direction,
            "source": "yfinance",
        }
        _GIFT_CACHE = {"data": result, "ts": now}
        return result
    except Exception as exc:
        result = {
            "price": None, "prev_close": None, "change_pct": 0.0,
            "direction": "NEUTRAL", "source": "error", "error": str(exc),
        }
        _GIFT_CACHE = {"data": result, "ts": now - _GIFT_TTL + 60}
        return result


if __name__ == "__main__":
    print("Testing MacroContext download...")
    ctx = load_macro()
    print(ctx.summary())
    # Spot-check one date
    test_date = pd.Timestamp("2022-03-10")
    print(f"Sample date {test_date.date()}: {ctx.get(test_date)}")
