#!/usr/bin/env python3
"""
research/db_backtest.py — NSE Strategy Backtest using cached OHLCV data.

Follows the 6-step workflow: Idea → Rules → Code → Variations → Backtest → Filter → Report

Data source: ohlcv_cache.db → ohlcv_cache table (same schema as data_sources.py).
Supports fetching all NSE universe stocks and caching them on first run.

Usage:
    python research/db_backtest.py              # backtest cached stocks
    python research/db_backtest.py --fetch      # fetch full NSE universe first, then backtest
    python research/db_backtest.py --fetch-only # only fetch/refresh data, no backtest
"""

import os, sys, pickle, sqlite3, warnings, argparse
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Tuple, Optional

warnings.filterwarnings("ignore")

# Add project root to path so we can import data_sources + universe
_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
FEES_PCT = 0.10      # per-side brokerage + STT (%)
SLIPPAGE_PCT = 0.05  # per-side market impact (%)
ROUND_TRIP_COST = (FEES_PCT + SLIPPAGE_PCT) * 2 / 100  # total cost as decimal

# ohlcv_cache.db lives in the project root (same logic as data_sources._ohlcv_data_dir)
_HF_DATA = "/data"
_OHLCV_DB = os.path.join(
    _HF_DATA if (os.path.isdir(_HF_DATA) and os.access(_HF_DATA, os.W_OK)) else _PROJ_ROOT,
    "ohlcv_cache.db",
)
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

FETCH_PERIOD = "2y"    # period for data fetch and backtest
FETCH_WORKERS = 6      # parallel fetch threads (keep low to avoid rate limits)

# ---------------------------------------------------------------------------
# STEP 1 — RULES
# ---------------------------------------------------------------------------
STRATEGIES = {
    # ── Baseline (keep for comparison) ──────────────────────────────────────
    "V1_RSI14_EMA200_3D": {
        "desc": "RSI(14)<30 + Close>EMA200 → hold 3 days or RSI>60",
        "rsi_period": 14, "rsi_entry": 30, "rsi_exit": 60,
        "ema_trend": 200, "max_hold": 3,
    },
    "V3_RSI2_EMA200_3D": {
        "desc": "RSI(2)<5 + Close>EMA200 → hold 3 days (mirrors S4V2 signal)",
        "rsi_period": 2, "rsi_entry": 5, "rsi_exit": 70,
        "ema_trend": 200, "max_hold": 3,
    },
    "V4_RSI14_DEEP_5D": {
        "desc": "RSI(14)<25 (deeply oversold, no trend filter) → hold 5 days",
        "rsi_period": 14, "rsi_entry": 25, "rsi_exit": 55,
        "ema_trend": None, "max_hold": 5,
    },
    # ── Improved strategies — higher accuracy ───────────────────────────────
    "V5_RSI14_ADX_5D": {
        "desc": "RSI(14)<25 + ADX>20 → hold 5 days (V4 + trending market filter)",
        "rsi_period": 14, "rsi_entry": 25, "rsi_exit": 55,
        "ema_trend": None, "adx_min": 20, "max_hold": 5,
    },
    "V6_RSI14_BB_5D": {
        "desc": "RSI(14)<30 + BB_pos<25% + EMA200 → 5D hold or +3% profit target",
        "rsi_period": 14, "rsi_entry": 30, "rsi_exit": 60,
        "ema_trend": 200, "bb_max": 25.0, "max_hold": 5, "profit_target_pct": 3.0,
    },
    "V7_RSI2_ADX_3D": {
        "desc": "RSI(2)<5 + EMA200 + ADX>15 → 3D hold or +4% profit target (S4V2 + ADX)",
        "rsi_period": 2, "rsi_entry": 5, "rsi_exit": 70,
        "ema_trend": 200, "adx_min": 15, "max_hold": 3, "profit_target_pct": 4.0,
    },
    "V8_TRIPLE_RSI_5D": {
        "desc": "RSI(14)<35 + RSI(2)<5 + EMA200 + ADX>20 → 5D hold or +5% (S_CTRIO-inspired)",
        "rsi_period": 14, "rsi_entry": 35, "rsi_exit": 60,
        "rsi2_entry": 5, "ema_trend": 200, "adx_min": 20, "max_hold": 5,
        "profit_target_pct": 5.0,
    },
}

# ---------------------------------------------------------------------------
# STEP 2 — UNIVERSE FETCH + OHLCV CACHING
# ---------------------------------------------------------------------------

def fetch_and_cache_universe(universe_size: int = 500, period: str = FETCH_PERIOD) -> List[str]:
    """
    Fetch the top-N NSE stocks by market cap, download OHLCV for any not
    already cached, and save them to ohlcv_cache.db via data_sources.fetch_ohlcv.
    Returns the list of all tickers available after the fetch.
    """
    from universe import get_universe
    from data_sources import fetch_ohlcv

    print(f"[fetch] Loading NSE universe (top {universe_size} by market cap) ...")
    universe = get_universe()
    tickers = list(universe.keys())[:universe_size]
    print(f"[fetch] {len(tickers)} tickers in universe")

    # Find which tickers already have fresh cached data
    cached = _get_cached_tickers(period)
    to_fetch = [t for t in tickers if t not in cached]
    print(f"[fetch] {len(cached)} already cached, {len(to_fetch)} need fetching")

    if not to_fetch:
        print("[fetch] All tickers already cached.")
        return tickers

    ok = 0
    fail = 0

    def _fetch_one(ticker):
        try:
            fetch_ohlcv(ticker, period=period)  # auto-saves to ohlcv_cache.db
            return ticker, True
        except Exception as e:
            return ticker, False

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futs = {ex.submit(_fetch_one, t): t for t in to_fetch}
        for i, fut in enumerate(as_completed(futs), 1):
            ticker, success = fut.result()
            if success:
                ok += 1
            else:
                fail += 1
            if i % 20 == 0 or i == len(to_fetch):
                print(f"[fetch] {i}/{len(to_fetch)} done — {ok} ok, {fail} failed")

    print(f"[fetch] Complete: {ok} fetched, {fail} failed")
    return tickers


def _get_cached_tickers(period: str = FETCH_PERIOD) -> set:
    """Return set of tickers that have data in ohlcv_cache.db for the given period."""
    try:
        conn = sqlite3.connect(f"file:{_OHLCV_DB}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM ohlcv_cache WHERE period=?", (period,)
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# STEP 3 — DATA LOADING
# ---------------------------------------------------------------------------

def load_all_ohlcv(period: str = FETCH_PERIOD) -> Dict[str, pd.DataFrame]:
    """Load all tickers from ohlcv_cache.db into {ticker: DataFrame}."""
    if not os.path.exists(_OHLCV_DB):
        print(f"[data] ohlcv_cache.db not found at {_OHLCV_DB}")
        print("[data] Run with --fetch to download NSE data first.")
        return {}

    conn = sqlite3.connect(f"file:{_OHLCV_DB}?immutable=1", uri=True)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ticker, data FROM ohlcv_cache WHERE period=? ORDER BY ticker",
        (period,),
    )
    rows = cursor.fetchall()
    conn.close()

    data = {}
    for ticker, blob in rows:
        try:
            sc, sh, sl, sv = pickle.loads(blob)
            col = sc.columns[0]
            df = pd.DataFrame({
                "Close":  sc[col],
                "High":   sh[col],
                "Low":    sl[col],
                "Volume": sv[col],
            })
            df.index = pd.to_datetime(df.index)
            df = df.sort_index().dropna(subset=["Close"])
            if len(df) >= 60:
                data[ticker] = df
        except Exception:
            pass

    print(f"[data] Loaded {len(data)} tickers (period={period})")
    return data


# ---------------------------------------------------------------------------
# STEP 4 — INDICATORS
# ---------------------------------------------------------------------------

def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, min_periods=period).mean()


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder smoothing). Returns ADX series."""
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    plus_dm  = (high - prev_high).clip(lower=0).where(
        (high - prev_high) > (prev_low - low), 0
    )
    minus_dm = (prev_low - low).clip(lower=0).where(
        (prev_low - low) > (high - prev_high), 0
    )

    atr       = tr.ewm(com=period - 1, min_periods=period).mean()
    plus_di   = 100 * plus_dm.ewm(com=period - 1, min_periods=period).mean() / atr
    minus_di  = 100 * minus_dm.ewm(com=period - 1, min_periods=period).mean() / atr
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(com=period - 1, min_periods=period).mean()
    return adx


def compute_bb_position(close: pd.Series, period: int = 20) -> pd.Series:
    """
    Bollinger Band position: 0% = at lower band, 100% = at upper band.
    Values below 25% = oversold relative to recent range.
    """
    mid = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    lower = mid - 2 * std
    upper = mid + 2 * std
    band_width = (upper - lower).replace(0, np.nan)
    return ((close - lower) / band_width * 100).clip(0, 100)


def generate_signals(df: pd.DataFrame, params: dict) -> pd.Series:
    """Return True on bars where entry conditions are met."""
    close = df["Close"]
    rsi   = compute_rsi(close, params["rsi_period"])
    sig   = rsi < params["rsi_entry"]

    if params.get("ema_trend") is not None:
        ema = compute_ema(close, params["ema_trend"])
        sig = sig & (close > ema)

    if params.get("adx_min") is not None:
        adx = compute_adx(df)
        sig = sig & (adx > params["adx_min"])

    if params.get("bb_max") is not None:
        bb = compute_bb_position(close)
        sig = sig & (bb < params["bb_max"])

    if params.get("rsi2_entry") is not None:
        rsi2 = compute_rsi(close, 2)
        sig = sig & (rsi2 < params["rsi2_entry"])

    return sig


# ---------------------------------------------------------------------------
# STEP 5 — BACKTEST ENGINE
# ---------------------------------------------------------------------------

def backtest_single(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Event-driven backtest.
    Entry: next bar's close after signal fires.
    Exit: RSI > rsi_exit OR profit_target hit OR max_hold bars.
    """
    close  = df["Close"].values
    dates  = df.index
    n      = len(df)

    close_s = df["Close"]
    rsi     = compute_rsi(close_s, params["rsi_period"]).values
    max_hold = params["max_hold"]
    rsi_exit_th = params["rsi_exit"]
    profit_target = params.get("profit_target_pct")

    # Precompute optional EMA / ADX / BB / RSI2 arrays for exit checks
    ema_arr  = None
    adx_arr  = None
    bb_arr   = None
    rsi2_arr = None

    if params.get("ema_trend") is not None:
        ema_arr = compute_ema(close_s, params["ema_trend"]).values
    if params.get("adx_min") is not None:
        adx_arr = compute_adx(df).values
    if params.get("bb_max") is not None:
        bb_arr = compute_bb_position(close_s).values
    if params.get("rsi2_entry") is not None:
        rsi2_arr = compute_rsi(close_s, 2).values

    trades    = []
    in_trade  = False
    entry_idx = None
    entry_price = None

    for i in range(1, n):
        if in_trade:
            hold_bars = i - entry_idx
            rsi_exit  = rsi[i] > rsi_exit_th
            max_exit  = hold_bars >= max_hold
            profit_exit = (
                profit_target is not None
                and (close[i] - entry_price) / entry_price * 100 >= profit_target
            )

            if rsi_exit or max_exit or profit_exit:
                exit_price = close[i]
                gross_ret  = (exit_price - entry_price) / entry_price
                net_ret    = gross_ret - ROUND_TRIP_COST
                reason = "rsi" if rsi_exit else ("profit" if profit_exit else "maxhold")
                trades.append({
                    "entry_date":   dates[entry_idx],
                    "exit_date":    dates[i],
                    "entry_price":  entry_price,
                    "exit_price":   exit_price,
                    "hold_bars":    hold_bars,
                    "gross_pct":    gross_ret * 100,
                    "net_pct":      net_ret * 100,
                    "win":          net_ret > 0,
                    "exit_reason":  reason,
                })
                in_trade = False
        else:
            # Check entry conditions on bar i-1
            prev_rsi_ok = rsi[i - 1] < params["rsi_entry"]
            prev_ema_ok = (
                params.get("ema_trend") is None
                or (ema_arr is not None and not np.isnan(ema_arr[i - 1])
                    and close[i - 1] > ema_arr[i - 1])
            )
            prev_adx_ok = (
                params.get("adx_min") is None
                or (adx_arr is not None and not np.isnan(adx_arr[i - 1])
                    and adx_arr[i - 1] > params["adx_min"])
            )
            prev_bb_ok = (
                params.get("bb_max") is None
                or (bb_arr is not None and not np.isnan(bb_arr[i - 1])
                    and bb_arr[i - 1] < params["bb_max"])
            )
            prev_rsi2_ok = (
                params.get("rsi2_entry") is None
                or (rsi2_arr is not None and not np.isnan(rsi2_arr[i - 1])
                    and rsi2_arr[i - 1] < params["rsi2_entry"])
            )

            if prev_rsi_ok and prev_ema_ok and prev_adx_ok and prev_bb_ok and prev_rsi2_ok:
                entry_price = close[i]
                entry_idx   = i
                in_trade    = True

    return pd.DataFrame(trades)


def compute_metrics(trades: pd.DataFrame, total_bars: int) -> dict:
    if len(trades) == 0:
        return {
            "n_trades": 0, "win_rate": 0.0, "avg_net_pct": 0.0,
            "total_return_pct": 0.0, "max_drawdown_pct": 0.0,
            "profit_factor": 0.0, "trades_per_year": 0.0,
        }

    wins   = trades[trades["win"]]
    losses = trades[~trades["win"]]

    n_trades = len(trades)
    win_rate = len(wins) / n_trades * 100
    avg_net  = trades["net_pct"].mean()

    compound = (1 + trades["net_pct"] / 100).prod() - 1
    equity   = (1 + trades["net_pct"] / 100).cumprod()
    roll_max = equity.cummax()
    max_dd   = ((equity - roll_max) / roll_max).min() * 100

    gross_wins   = wins["net_pct"].sum()   if len(wins)   else 0
    gross_losses = abs(losses["net_pct"].sum()) if len(losses) else 0
    pf = min(gross_wins / gross_losses, 99.0) if gross_losses > 0 else 99.0

    years = total_bars / 252
    tpy   = n_trades / years if years > 0 else 0

    return {
        "n_trades":         n_trades,
        "win_rate":         round(win_rate, 1),
        "avg_net_pct":      round(avg_net,   3),
        "total_return_pct": round(compound * 100, 2),
        "max_drawdown_pct": round(max_dd,    2),
        "profit_factor":    round(pf,        2),
        "trades_per_year":  round(tpy,       1),
    }


# ---------------------------------------------------------------------------
# STEP 6 — FILTER
# ---------------------------------------------------------------------------
MIN_TOTAL_TRADES     = 50
MIN_PROFIT_FACTOR    = 1.10
MIN_WIN_RATE         = 50.0   # raised from 45% — target real edge
MIN_OOS_TRADES       = 10
MIN_OOS_PROFIT_FACTOR = 1.0


def passes_is_filter(m: dict) -> bool:
    return (
        m["n_trades"]      >= MIN_TOTAL_TRADES
        and m["profit_factor"] >= MIN_PROFIT_FACTOR
        and m["win_rate"]      >= MIN_WIN_RATE
    )


def passes_oos_filter(m: dict) -> bool:
    return (
        m["n_trades"]      >= MIN_OOS_TRADES
        and m["profit_factor"] >= MIN_OOS_PROFIT_FACTOR
    )


# ---------------------------------------------------------------------------
# MAIN BACKTEST RUNNER
# ---------------------------------------------------------------------------
IS_END  = "2025-07-17"
OOS_START = "2025-07-18"


def run_full_backtest(data: Dict[str, pd.DataFrame]):
    aggregate     = {}
    oos_aggregate = {}
    per_ticker    = {}

    for name, params in STRATEGIES.items():
        print(f"\n--- {name} ---")
        is_trades_all  = []
        oos_trades_all = []
        is_bars_total  = 0
        oos_bars_total = 0
        ticker_metrics = {}

        for ticker, df in data.items():
            df_is  = df[df.index <= IS_END]
            df_oos = df[df.index >  IS_END]

            if len(df_is) >= 30:
                t_is = backtest_single(df_is, params)
                ticker_metrics[ticker] = compute_metrics(t_is, len(df_is))
                is_trades_all.append(t_is)
                is_bars_total += len(df_is)

            if len(df_oos) >= 10:
                t_oos = backtest_single(df_oos, params)
                oos_trades_all.append(t_oos)
                oos_bars_total += len(df_oos)

        combined_is  = pd.concat(is_trades_all,  ignore_index=True) if is_trades_all  else pd.DataFrame()
        combined_oos = pd.concat(oos_trades_all, ignore_index=True) if oos_trades_all else pd.DataFrame()

        m_is  = compute_metrics(combined_is,  is_bars_total)
        m_oos = compute_metrics(combined_oos, oos_bars_total)

        print(f"  IS  → trades={m_is['n_trades']}, WR={m_is['win_rate']}%, PF={m_is['profit_factor']}, ret={m_is['total_return_pct']}%")
        print(f"  OOS → trades={m_oos['n_trades']}, WR={m_oos['win_rate']}%, PF={m_oos['profit_factor']}, ret={m_oos['total_return_pct']}%")

        aggregate[name]     = m_is
        oos_aggregate[name] = m_oos
        per_ticker[name]    = ticker_metrics

    return aggregate, oos_aggregate, per_ticker


# ---------------------------------------------------------------------------
# STEP 7 — REPORT GENERATOR
# ---------------------------------------------------------------------------

def _improvement_vs_v4(m_is: dict, m_oos: dict, v4_is: dict, v4_oos: dict) -> str:
    """Return a short delta string showing win-rate and PF change vs V4."""
    wr_delta = m_is["win_rate"] - v4_is["win_rate"]
    pf_delta = m_is["profit_factor"] - v4_is["profit_factor"]
    oos_wr_delta = m_oos["win_rate"] - v4_oos["win_rate"]
    sign = lambda x: f"+{x:.1f}" if x >= 0 else f"{x:.1f}"
    return f"IS WR {sign(wr_delta)}pp, IS PF {sign(pf_delta)}, OOS WR {sign(oos_wr_delta)}pp vs V4"


def generate_report(aggregate: dict, oos_aggregate: dict, per_ticker: dict, data: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_stocks = len(data)

    survivors = [
        n for n in STRATEGIES
        if passes_is_filter(aggregate[n]) and passes_oos_filter(oos_aggregate[n])
    ]

    v4_is  = aggregate.get("V4_RSI14_DEEP_5D", {})
    v4_oos = oos_aggregate.get("V4_RSI14_DEEP_5D", {})

    lines = []
    lines.append("# NSE Stock Strategy Backtest Report")
    lines.append(f"\n**Generated:** {now}  ")
    lines.append(f"**Universe:** {total_stocks} NSE stocks (ohlcv_cache.db)  ")
    lines.append(f"**In-sample:** 2024-07-18 → {IS_END} | **Out-of-sample:** {OOS_START} → today  ")
    lines.append(f"**Transaction costs:** {FEES_PCT}% + {SLIPPAGE_PCT}% slippage per side = {ROUND_TRIP_COST*100:.2f}% round-trip  ")
    lines.append("**Note:** *Total Return %* = sequential compounding across all trades. Profit factor capped at 99.0 when no losing trades.  ")

    lines.append("\n---\n## Disclaimer\n")
    lines.append("> **Educational only — not financial advice.** Past backtest results do not guarantee future performance.")

    lines.append("\n---\n## Strategy Rules\n")
    for name, params in STRATEGIES.items():
        tag = "NEW" if name.startswith(("V5", "V6", "V7", "V8")) else "baseline"
        lines.append(f"### {name} `[{tag}]`")
        lines.append(f"- **Description:** {params['desc']}")
        lines.append(f"- RSI period: {params['rsi_period']} | Entry RSI < {params['rsi_entry']} | Exit RSI > {params['rsi_exit']}")
        if params.get("rsi2_entry"):
            lines.append(f"- Secondary RSI(2) confirmation: RSI2 < {params['rsi2_entry']}")
        if params.get("ema_trend"):
            lines.append(f"- Trend filter: Close > EMA({params['ema_trend']})")
        if params.get("adx_min"):
            lines.append(f"- ADX filter: ADX(14) > {params['adx_min']} (trending market only)")
        if params.get("bb_max"):
            lines.append(f"- Bollinger filter: BB_pos < {params['bb_max']}% (below lower BB zone)")
        if params.get("profit_target_pct"):
            lines.append(f"- Profit target: +{params['profit_target_pct']}% (exit early to lock in gain)")
        lines.append(f"- Max hold: {params['max_hold']} bars")
        lines.append("")

    lines.append("---\n## In-Sample Results\n")
    lines.append("| Strategy | Trades | Win Rate | Avg Net % | Total Return % | Max DD % | Profit Factor | Trades/yr |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, m in aggregate.items():
        lines.append(
            f"| {name} | {m['n_trades']} | {m['win_rate']}% | {m['avg_net_pct']}% | "
            f"{m['total_return_pct']}% | {m['max_drawdown_pct']}% | {m['profit_factor']} | {m['trades_per_year']} |"
        )

    lines.append("\n## Out-of-Sample Results (Survival Test)\n")
    lines.append("| Strategy | Trades | Win Rate | Avg Net % | Total Return % | Max DD % | Profit Factor | Survived? |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, m in oos_aggregate.items():
        survived = name in survivors
        flag = "✅ Yes" if survived else "❌ No"
        lines.append(
            f"| {name} | {m['n_trades']} | {m['win_rate']}% | {m['avg_net_pct']}% | "
            f"{m['total_return_pct']}% | {m['max_drawdown_pct']}% | {m['profit_factor']} | {flag} |"
        )

    lines.append("\n---\n## Accuracy Improvement vs V4 Baseline\n")
    if v4_is and v4_oos:
        lines.append("| Strategy | IS Win Rate | OOS Win Rate | IS Profit Factor | OOS PF | Delta vs V4 |")
        lines.append("|---|---|---|---|---|---|")
        for name in STRATEGIES:
            m_is  = aggregate[name]
            m_oos = oos_aggregate[name]
            delta = _improvement_vs_v4(m_is, m_oos, v4_is, v4_oos) if v4_is else "—"
            lines.append(
                f"| {name} | {m_is['win_rate']}% | {m_oos['win_rate']}% | "
                f"{m_is['profit_factor']} | {m_oos['profit_factor']} | {delta} |"
            )
    else:
        lines.append("_V4 baseline not available for comparison._")

    lines.append("\n---\n## Filter Criteria\n")
    lines.append(f"- Minimum total IS trades: ≥ {MIN_TOTAL_TRADES}")
    lines.append(f"- Minimum IS profit factor: ≥ {MIN_PROFIT_FACTOR}")
    lines.append(f"- Minimum IS win rate: ≥ {MIN_WIN_RATE}%")
    lines.append(f"- Minimum OOS trades: ≥ {MIN_OOS_TRADES}")
    lines.append(f"- Minimum OOS profit factor: ≥ {MIN_OOS_PROFIT_FACTOR}")

    lines.append("\n---\n## Strategy Filter Results\n")
    for name in STRATEGIES:
        m_is  = aggregate[name]
        m_oos = oos_aggregate[name]
        survived = name in survivors
        issues = []
        if m_is["n_trades"]      < MIN_TOTAL_TRADES:    issues.append(f"too few IS trades ({m_is['n_trades']})")
        if m_is["profit_factor"] < MIN_PROFIT_FACTOR:   issues.append(f"IS PF too low ({m_is['profit_factor']})")
        if m_is["win_rate"]      < MIN_WIN_RATE:        issues.append(f"IS win rate too low ({m_is['win_rate']}%)")
        if m_oos["n_trades"]     < MIN_OOS_TRADES:      issues.append(f"too few OOS trades ({m_oos['n_trades']})")
        elif m_oos["profit_factor"] < MIN_OOS_PROFIT_FACTOR:
            issues.append(f"OOS PF < 1 ({m_oos['profit_factor']})")
        if survived:
            lines.append(f"### ✅ {name} — SURVIVED")
            lines.append(f"Passed all filters. IS WR {m_is['win_rate']}% / PF {m_is['profit_factor']}, OOS PF {m_oos['profit_factor']}.")
        else:
            lines.append(f"### ❌ {name} — ELIMINATED")
            lines.append(f"Reasons: {'; '.join(issues) if issues else 'OOS degradation'}.")
        lines.append("")

    lines.append("---\n## Top 20 Stocks per Surviving Strategy\n")
    for name in survivors:
        lines.append(f"### {name}")
        ranked = sorted(
            [(t, m) for t, m in per_ticker[name].items() if m["n_trades"] >= 2],
            key=lambda x: (x[1]["profit_factor"], x[1]["win_rate"]),
            reverse=True,
        )[:20]
        if ranked:
            lines.append("| Ticker | Trades | Win Rate | Profit Factor | Total Return % |")
            lines.append("|---|---|---|---|---|")
            for t, m in ranked:
                lines.append(f"| {t} | {m['n_trades']} | {m['win_rate']}% | {m['profit_factor']} | {m['total_return_pct']}% |")
        else:
            lines.append("_No stocks met the minimum trade threshold._")
        lines.append("")

    lines.append("---\n## Known Limitations\n")
    lines.append("1. **No Open price** — entry is next bar's Close (slight look-ahead vs true next-open execution).")
    lines.append("2. **Survivorship bias** — universe is today's top-N NSE stocks by market cap; delisted stocks excluded.")
    lines.append("3. **Single position** — one trade at a time per stock; no portfolio-level correlation management.")
    lines.append("4. **Limited data** — ~500 trading days per stock means limited statistical confidence.")
    lines.append("5. **EMA200 warm-up** — strategies with EMA200 filter skip stocks with < 200 bars.")
    lines.append("6. **No gap risk** — overnight gaps from corporate events are not modelled separately.")
    lines.append("\n---\n## Next Steps\n")
    lines.append("1. Forward-test surviving strategies on paper trades via Flask watchlist UI.")
    lines.append("2. Wire V8_TRIPLE_RSI_5D into `trial_run.py` as a new confirmed S-signal.")
    lines.append("3. Extend data to 5+ years for higher statistical confidence on low-frequency strategies.")
    lines.append("4. Add VIX<18 filter (Mode B) — backtested 71% win rate when VIX below 18.")
    lines.append("\n---\n")
    lines.append("> *Educational only — not financial advice. Backtested/paper analysis only.*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NSE Strategy Backtest")
    parser.add_argument("--fetch",      action="store_true", help="Fetch full NSE universe before backtest")
    parser.add_argument("--fetch-only", action="store_true", help="Only fetch data, skip backtest")
    parser.add_argument("--universe-size", type=int, default=500, help="Number of NSE stocks to fetch (default 500)")
    args = parser.parse_args()

    print("=" * 60)
    print("NSE Backtest — 7-Step Workflow")
    print("=" * 60)

    if args.fetch or args.fetch_only:
        print(f"\n[0/4] Fetching NSE universe ({args.universe_size} stocks) ...")
        fetch_and_cache_universe(universe_size=args.universe_size)

    if args.fetch_only:
        print("\nFetch complete. Run without --fetch-only to run backtest.")
        sys.exit(0)

    print(f"\n[1/4] Loading OHLCV data from {_OHLCV_DB} ...")
    data = load_all_ohlcv(period=FETCH_PERIOD)
    if not data:
        print("No data found. Run with --fetch to download NSE data first.")
        sys.exit(1)

    print(f"\n[2/4] Running {len(STRATEGIES)} strategy variations across {len(data)} tickers ...")
    aggregate, oos_aggregate, per_ticker = run_full_backtest(data)

    print("\n[3/4] Generating report ...")
    report_md = generate_report(aggregate, oos_aggregate, per_ticker, data)

    out_path = os.path.join(OUT_DIR, "db_backtest_report.md")
    with open(out_path, "w") as f:
        f.write(report_md)
    print(f"\n[4/4] Report saved → {out_path}")

    print("\n=== Summary ===")
    for name, m in aggregate.items():
        oos = oos_aggregate[name]
        tag = "✅" if (passes_is_filter(m) and passes_oos_filter(oos)) else "❌"
        print(f"  {tag} {name}: IS WR={m['win_rate']}% PF={m['profit_factor']} | OOS WR={oos['win_rate']}% PF={oos['profit_factor']}")
