"""
risk_engine.py — Portfolio risk metrics for the paper trading platform.

Reads closed trades from database.py and computes:
  - Sharpe ratio          (annualized, 6.5% India risk-free rate)
  - Max drawdown %        (on equity curve built from closed trades)
  - Beta vs Nifty50       (regression of per-trade returns vs Nifty over same period)
  - Portfolio volatility  (annualized std dev of per-trade returns)
  - Profit factor         (gross profit / gross loss)
  - Kelly fraction        (optimal position sizing)
  - Suggested position %  (half-Kelly, capped at 10%)

Usage:
    from risk_engine import get_portfolio_risk
    metrics = get_portfolio_risk()
    # metrics["sharpe_ratio"]          → float
    # metrics["suggested_position_size_pct"] → float (% of capital per trade)

Run standalone to test:
    python risk_engine.py
"""

from __future__ import annotations
import logging
import math
from datetime import datetime
from typing import Optional


_INDIA_RISK_FREE_RATE = 6.5 / 100  # 6.5% annualized (RBI repo rate proxy)
_MIN_TRADES = 5                     # minimum closed trades for meaningful metrics


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _safe(v, default=0.0):
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _annualized_return(mean_return_per_trade: float, avg_holding_days: float) -> float:
    """Approximate annualized return from per-trade mean and average holding period."""
    if avg_holding_days <= 0:
        return 0.0
    trades_per_year = 252 / avg_holding_days
    return mean_return_per_trade * trades_per_year / 100  # convert % to decimal


def _annualized_vol(std_per_trade: float, avg_holding_days: float) -> float:
    if avg_holding_days <= 0 or std_per_trade <= 0:
        return 0.0
    trades_per_year = 252 / avg_holding_days
    return (std_per_trade / 100) * math.sqrt(trades_per_year)


# ── EQUITY CURVE & DRAWDOWN ───────────────────────────────────────────────────

def _build_equity_series(sorted_trades: list[dict]) -> list[dict]:
    """Build equity curve as [{date, equity, trade_id}] starting at 100."""
    series = []
    equity = 100.0
    for t in sorted_trades:
        pnl = _safe(t.get("pnl_pct"), 0.0)
        equity *= (1 + pnl / 100)
        series.append({
            "date":     (t.get("closed_at") or "")[:10],
            "equity":   round(equity, 4),
            "trade_id": t.get("id"),
            "ticker":   t.get("ticker"),
            "pnl_pct":  round(pnl, 3),
        })
    return series


def _max_drawdown(pnl_pct_list: list[float]) -> float:
    """Max drawdown % from an ordered series of per-trade P&L %."""
    if not pnl_pct_list:
        return 0.0

    equity = 100.0  # start at 100
    peak = 100.0
    max_dd = 0.0

    for r in pnl_pct_list:
        equity *= (1 + r / 100)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return round(max_dd, 2)


# ── BETA CALCULATION ──────────────────────────────────────────────────────────

def _compute_beta(trades: list[dict]) -> Optional[float]:
    """
    Estimate beta vs Nifty50 by matching each trade's return to the Nifty's return
    over the same open→close window.  Requires at least 10 closed trades.
    """
    if len(trades) < 10:
        return None

    try:
        import yfinance as yf
        import pandas as pd
        nifty = yf.download("^NSEI", period="2y", progress=False, auto_adjust=True)["Close"].dropna()
    except Exception as e:
        logging.debug("risk_engine: beta Nifty download failed: %s", e)
        return None

    trade_ret = []
    nifty_ret = []

    for t in trades:
        if not t.get("opened_at") or not t.get("closed_at") or t.get("pnl_pct") is None:
            continue
        try:
            open_dt  = pd.Timestamp(t["opened_at"]).normalize()
            close_dt = pd.Timestamp(t["closed_at"]).normalize()

            nifty_at_open  = nifty.asof(open_dt)
            nifty_at_close = nifty.asof(close_dt)

            if nifty_at_open > 0 and nifty_at_close > 0:
                nr = (nifty_at_close / nifty_at_open - 1) * 100
                tr = _safe(t["pnl_pct"])
                if direction := t.get("direction"):
                    if direction == "SHORT":
                        tr = -tr  # short profits when market falls
                trade_ret.append(tr)
                nifty_ret.append(nr)
        except Exception:
            continue

    if len(trade_ret) < 5:
        return None

    try:
        import numpy as np
        x = np.array(nifty_ret)
        y = np.array(trade_ret)
        cov = np.cov(x, y)[0, 1]
        var = np.var(x)
        if var <= 0:
            return None
        return round(float(cov / var), 3)
    except Exception:
        return None


# ── KELLY FRACTION ────────────────────────────────────────────────────────────

def _kelly(win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
    """
    Kelly criterion: fraction = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
    Uses absolute values.  Returns 0.0 if inputs are degenerate.
    """
    w = abs(avg_win_pct) / 100
    l = abs(avg_loss_pct) / 100
    if w <= 0:
        return 0.0
    p = win_rate
    q = 1 - p
    kelly = (p * w - q * l) / w
    return max(0.0, round(kelly, 4))


# ── HOLDING PERIOD ESTIMATION ─────────────────────────────────────────────────

def _avg_holding_days(trades: list[dict]) -> float:
    """Estimate average holding period in days from opened_at → closed_at."""
    durations = []
    for t in trades:
        try:
            if t.get("opened_at") and t.get("closed_at"):
                open_dt  = datetime.fromisoformat(t["opened_at"].replace("Z", "+00:00"))
                close_dt = datetime.fromisoformat(t["closed_at"].replace("Z", "+00:00"))
                days = abs((close_dt - open_dt).total_seconds()) / 86400
                if 0 < days <= 30:
                    durations.append(days)
        except Exception:
            pass
    if not durations:
        return 3.0  # default 3D holding period if no data
    avg = sum(durations) / len(durations)
    return max(1.0, avg)


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def get_portfolio_risk(include_curve: bool = False) -> dict:
    """
    Compute risk metrics from the paper trading database.

    Returns:
      sharpe_ratio                — annualized Sharpe (>1.0 = good, >2.0 = excellent)
      max_drawdown_pct            — largest peak-to-trough loss on equity curve (%)
      beta_vs_nifty               — correlation-adjusted sensitivity to Nifty moves
      portfolio_volatility_ann    — annualized volatility of per-trade returns
      profit_factor               — gross profit / gross loss (>1.5 = decent)
      kelly_fraction              — theoretical optimal position fraction
      suggested_position_size_pct — half-Kelly, capped at 10% (conservative)
      trade_count                 — number of closed trades used
      avg_holding_days            — average trade duration in days
      win_rate                    — % of trades that were profitable
      avg_win_pct                 — average winner return %
      avg_loss_pct                — average loser return %
      computed_at                 — ISO timestamp
      note                        — warning if insufficient data
    """
    try:
        from database import get_trade_history
        trades = get_trade_history()
    except Exception as e:
        return {"error": f"database read failed: {e}", "trade_count": 0}

    closed = [t for t in trades if t.get("pnl_pct") is not None]
    n = len(closed)

    if n < _MIN_TRADES:
        return {
            "sharpe_ratio": None,
            "max_drawdown_pct": None,
            "beta_vs_nifty": None,
            "portfolio_volatility_ann": None,
            "profit_factor": None,
            "kelly_fraction": None,
            "suggested_position_size_pct": 5.0,  # conservative default
            "trade_count": n,
            "avg_holding_days": None,
            "win_rate": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "computed_at": datetime.now().isoformat(),
            "note": f"Only {n} closed trade(s); need {_MIN_TRADES}+ for reliable metrics",
        }

    pnl_pcts = [_safe(t["pnl_pct"]) for t in closed]

    # Split into winners/losers
    winners = [p for p in pnl_pcts if p >= 0]
    losers  = [p for p in pnl_pcts if p < 0]

    win_rate  = len(winners) / n
    avg_win   = sum(winners) / len(winners) if winners else 0.0
    avg_loss  = abs(sum(losers) / len(losers)) if losers else 0.0

    gross_profit = sum(winners)
    gross_loss   = abs(sum(losers))
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else float("inf")

    loss_rate = 1 - win_rate
    expectancy = round(win_rate * avg_win - loss_rate * avg_loss, 3)

    # Holding period & volatility
    avg_hold = _avg_holding_days(closed)

    try:
        import numpy as np
        arr = np.array(pnl_pcts)
        mean_ret = float(np.mean(arr))
        std_ret  = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    except ImportError:
        mean_ret = sum(pnl_pcts) / n
        variance = sum((p - mean_ret) ** 2 for p in pnl_pcts) / max(1, n - 1)
        std_ret  = math.sqrt(variance)

    ann_ret = _annualized_return(mean_ret, avg_hold)
    ann_vol = _annualized_vol(std_ret, avg_hold)

    sharpe = None
    if ann_vol > 0:
        sharpe = round((ann_ret - _INDIA_RISK_FREE_RATE) / ann_vol, 3)

    # Max drawdown from ordered equity curve (sort by closed_at)
    sorted_trades = sorted(
        [t for t in closed if t.get("closed_at")],
        key=lambda t: t["closed_at"],
    )
    ordered_pnl = [_safe(t["pnl_pct"]) for t in sorted_trades]
    max_dd = _max_drawdown(ordered_pnl)

    # Equity curve (exposed when include_curve=True)
    equity_series = _build_equity_series(sorted_trades) if include_curve else None

    # Beta (best-effort; may return None)
    beta = _compute_beta(sorted_trades)

    # Kelly and position sizing
    kf = _kelly(win_rate, avg_win, avg_loss)
    half_kelly = kf * 0.5
    suggested_position = round(min(half_kelly * 100, 10.0), 1)  # cap at 10%

    return {
        "sharpe_ratio":              sharpe,
        "max_drawdown_pct":          max_dd,
        "beta_vs_nifty":             beta,
        "portfolio_volatility_ann":  round(ann_vol * 100, 2) if ann_vol else None,
        "profit_factor":             profit_factor,
        "expectancy":                expectancy,
        "kelly_fraction":            round(kf, 4),
        "suggested_position_size_pct": suggested_position,
        "trade_count":               n,
        "avg_holding_days":          round(avg_hold, 1),
        "win_rate":                  round(win_rate * 100, 1),
        "avg_win_pct":               round(avg_win, 2),
        "avg_loss_pct":              round(avg_loss, 2),
        "computed_at":               datetime.now().isoformat(),
        **({"equity_curve": equity_series} if include_curve else {}),
    }


def format_risk_summary(metrics: dict) -> str:
    """One-line risk summary for logging / UI display."""
    if metrics.get("error") or metrics.get("trade_count", 0) < _MIN_TRADES:
        return f"Risk metrics: insufficient data ({metrics.get('trade_count', 0)} trades)"

    sharpe = metrics.get("sharpe_ratio")
    dd = metrics.get("max_drawdown_pct")
    pf = metrics.get("profit_factor")
    wr = metrics.get("win_rate")
    pos = metrics.get("suggested_position_size_pct")

    return (
        f"Sharpe: {sharpe:.2f}  |  MaxDD: {dd:.1f}%  |  "
        f"Profit Factor: {pf:.2f}  |  Win: {wr:.1f}%  |  "
        f"Suggested size: {pos}% per trade"
    )


if __name__ == "__main__":
    import pprint
    print("Computing portfolio risk metrics...")
    metrics = get_portfolio_risk()
    pprint.pprint(metrics)
    print(f"\n{format_risk_summary(metrics)}")
