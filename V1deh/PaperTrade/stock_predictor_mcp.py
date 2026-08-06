#!/usr/bin/env python3
"""
stock_predictor_mcp.py — MCP server for Indian equity market prediction.

Tools:
  predict_stocks(stocks, start_date, end_date)
      → Per-stock directional prediction + expected % move over date range.
        News auto-fetched from yfinance.

  rank_best_stocks(start_date, end_date, universe, capital)
      → Ranked list of best stocks for the period with optional capital allocation.

Run via Claude Code MCP: configured in ~/.claude/settings.json
"""

from mcp.server.fastmcp import FastMCP
from predictor_core import predict_stock_v2 as predict_stock, rank_stocks_v2 as rank_stocks
from typing import Optional
import logging, os, atexit

_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_server.log")
logging.basicConfig(
    filename=_LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logging.info("MCP server process starting (PID %d)", os.getpid())
atexit.register(lambda: logging.info("MCP server process exiting"))

mcp = FastMCP(
    "Stock Predictor India",
    instructions=(
        "Predicts NSE Indian equity performance over a date range using technical "
        "indicators (RSI, MACD, EMA, ADX, Bollinger Bands, OBV) and auto-fetched "
        "news sentiment. All tickers must be Yahoo Finance NSE format, e.g. 'RELIANCE.NS'."
    ),
)


# ── TOOL 1: PREDICT SPECIFIC STOCKS ──────────────────────────────────────────
@mcp.tool()
def predict_stocks(
    stocks:     list[str],
    start_date: str,
    end_date:   str,
) -> str:
    """
    Predict how each stock in `stocks` will perform between start_date and end_date.

    Args:
        stocks:     List of NSE tickers in Yahoo Finance format, e.g. ["RELIANCE.NS", "TCS.NS"].
                    Max 20 stocks.
        start_date: Prediction window start, format YYYY-MM-DD.
        end_date:   Prediction window end, format YYYY-MM-DD.

    Returns:
        Formatted report with directional prediction, expected % move, and confidence
        for each stock. News is auto-fetched — no manual input needed.
    """
    if not stocks:
        return "ERROR: Provide at least one ticker."
    if len(stocks) > 20:
        return "ERROR: Max 20 stocks per call."

    lines = []
    lines.append("=" * 70)
    lines.append(f"  STOCK PREDICTIONS  |  {start_date} → {end_date}")
    lines.append("=" * 70)

    for ticker in stocks:
        t = ticker.upper().strip()
        if not t.endswith(".NS") and "." not in t:
            t += ".NS"
        try:
            pred = predict_stock(t, start_date, end_date)
        except Exception as e:
            logging.error("predict_stock failed for %s: %s", t, e)
            lines.append(f"\n  {t}: prediction failed — {e}")
            continue

        if "error" in pred:
            lines.append(f"\n  {t}: {pred['error']}")
            continue

        conf_sym  = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}.get(pred["confidence"], "?")
        dir_arrow = "UP" if "BULLISH" in pred["direction"] else ("DOWN" if "BEARISH" in pred["direction"] else "NEUTRAL")
        ml   = pred.get("ml", {})
        news = pred.get("news", {})
        earn = pred.get("earnings", {})
        mkt  = pred.get("market", {})
        kl   = pred.get("key_levels", {})
        feat = ml.get("features", {})

        lines.append(f"\n{'─'*70}")
        lines.append(f"  {t}  ({pred.get('company', '')})  [{dir_arrow}]  [{conf_sym} CONFIDENCE]")
        lines.append(f"{'─'*70}")
        lines.append(f"  Direction      : {pred['direction']}")
        lines.append(f"  Current Price  : ₹{pred['price']:,.2f}")
        lines.append(f"  Period         : {pred['trading_days']} trading days")
        lines.append(f"  Expected Return: {pred['expected_return_range']}")
        lines.append(f"  Mid-Point Est. : {pred['midpoint']:+.1f}%")
        lines.append("")
        lines.append(f"  Active Signals: {', '.join(pred['active_strategies']) or 'None'} ({pred['signal_count']} fired)")
        lines.append(f"  ML Score      : {ml.get('score', 50)}/100  prob={ml.get('probability', 0.5):.3f}  upgraded={ml.get('upgraded', False)}")
        if feat:
            lines.append(f"    RSI: {feat.get('rsi', '?')}  EMA-Stack: {feat.get('ema_stack', '?'):.2f}  ADX: {feat.get('adx', '?')}")
            lines.append(f"    Vol: {feat.get('vol_ratio', '?')}x  RS(3M): {feat.get('rs_3m_pct', '?'):+.1f}%  MACD+: {feat.get('macd_pos', '?')}")
        lines.append("")
        lines.append(f"  News: {news.get('label', 'NEUTRAL')} (score: {news.get('score', 0):+d})  [{news.get('source', '?')}]")
        if news.get("summary"):
            lines.append(f"    {news['summary'][:75]}")
        for h in news.get("headlines", [])[:2]:
            lines.append(f"    - {h[:75]}")
        lines.append("")
        if earn.get("in_blackout"):
            lines.append(f"  *** EARNINGS BLACKOUT: {earn.get('warning', '')} ***")
        elif earn.get("next_date"):
            lines.append(f"  Earnings: {earn['next_date']} ({earn['days_away']}d away)")
        kl20  = f"₹{kl['ema20']:,.2f}"  if kl.get("ema20")  else "N/A"
        kl50  = f"₹{kl['ema50']:,.2f}"  if kl.get("ema50")  else "N/A"
        kl200 = f"₹{kl['ema200']:,.2f}" if kl.get("ema200") else "N/A"
        lines.append(f"  Key Levels: EMA20 {kl20}  |  EMA50 {kl50}  |  EMA200 {kl200}")
        lines.append(f"  VIX       : {mkt.get('vix_label', 'N/A')}")
        lines.append(f"  Nifty Gate: {mkt.get('nifty_label', 'N/A')}")

    lines.append(f"\n{'='*70}")
    lines.append("  ⚠  Predictions are model-based estimates, not financial advice.")
    lines.append("     Paper trade before deploying real capital.")
    lines.append("=" * 70)
    return "\n".join(lines)


# ── TOOL 2: RANK BEST STOCKS FOR A DATE RANGE ────────────────────────────────
@mcp.tool()
def rank_best_stocks(
    start_date: str,
    end_date:   str,
    universe:   Optional[list[str]] = None,
    capital:    Optional[float]     = None,
    top_n:      int = 10,
) -> str:
    """
    Scan a stock universe and rank the best picks for the given date range.

    Args:
        start_date: Prediction window start, format YYYY-MM-DD.
        end_date:   Prediction window end, format YYYY-MM-DD.
        universe:   Optional list of NSE tickers to scan (defaults to 34-stock Nifty universe).
                    E.g. ["RELIANCE.NS", "TCS.NS", "INFY.NS"].
        capital:    Optional capital in INR. If provided, suggests allocation per stock.
                    E.g. 500000 for ₹5,00,000.
        top_n:      Number of top stocks to show in detail (default 10, max 20).

    Returns:
        Ranked report of best stocks to buy for the period, with confidence levels,
        expected returns, and optional capital allocation per stock.
        News is auto-fetched for every stock — no manual input needed.
    """
    top_n  = min(top_n, 20)
    try:
        result = rank_stocks(start_date, end_date, universe=universe, capital=capital)
    except Exception as e:
        logging.error("rank_stocks failed: %s", e)
        return f"ERROR: Ranking failed — {e}"

    ranked = result["ranked"]
    market = result.get("market", {})
    lines  = []

    lines.append("=" * 70)
    lines.append(f"  BEST STOCKS TO BUY  |  {start_date} -> {end_date}")
    if capital:
        lines.append(f"  Capital: ₹{capital:,.0f}")
    lines.append("=" * 70)
    lines.append(f"\n  VIX    : {market.get('vix_label', 'N/A')}")
    lines.append(f"  Nifty  : {market.get('nifty_label', 'N/A')}")
    lines.append(f"  Macro  : {market.get('macro_label', 'N/A')}")
    lines.append(f"  Scanned: {result['total_scanned']} stocks -> {result['total_scored']} scored\n")

    buys  = [r for r in ranked if r["direction"] not in ("BEARISH", "SLIGHTLY BEARISH", "NO TRADE")]
    avoid = [r for r in ranked if r["direction"] in ("BEARISH", "SLIGHTLY BEARISH")]

    if not buys:
        lines.append("  No bullish setups found in the current universe for this window.")
        lines.append("  Consider waiting or expanding the universe.")
    else:
        lines.append(f"  RECOMMENDED BUYS ({len(buys)} stocks)\n")
        for r in buys[:top_n]:
            ml   = r.get("ml", {})
            news = r.get("news", {})
            earn = r.get("earnings", {})
            conf = r["confidence"]

            lines.append(f"  {'─'*66}")
            lines.append(f"  #{r['rank']:<4} {r['ticker']:<18} {r['direction']}  [{conf}]")
            lines.append(f"       Company  : {r.get('company', '')}")
            lines.append(f"       Price    : ₹{r['price']:,.2f}  |  Expected: {r['expected_return_range']}")
            lines.append(f"       Signals  : {', '.join(r['active_strategies']) or 'none'} ({r['signal_count']})")
            lines.append(f"       ML       : {ml.get('score', 50)}/100  prob={ml.get('probability', 0.5):.2f}")
            lines.append(f"       News     : {news.get('label', 'N/A')} ({news.get('score', 0):+d})")
            if news.get("summary"):
                lines.append(f"                {news['summary'][:60]}")
            if earn.get("in_blackout"):
                lines.append(f"       *** EARNINGS BLACKOUT: {earn.get('warning', '')} ***")
            if capital and r.get("suggested_allocation"):
                lines.append(f"       Allocation: ₹{r['suggested_allocation']:,.0f} -> {r.get('suggested_shares', 0)} shares")
            lines.append("")

    if avoid[:5]:
        lines.append("\n  AVOID / BEARISH SETUPS")
        for r in avoid[:5]:
            lines.append(f"     {r['ticker']:<18} {r['direction']:<20} signals:{r['signal_count']}  news:{r.get('news', {}).get('label', 'N/A')}")

    lines.append(f"\n{'='*70}")
    lines.append("  PORTFOLIO SUMMARY")
    lines.append("─" * 70)
    if buys:
        avg_ret   = round(sum(r["midpoint"] for r in buys[:top_n]) / len(buys[:top_n]), 1)
        directional = [
            r for r in buys[:top_n]
            if r.get("direction") in ("BULLISH", "SLIGHTLY BULLISH", "NEUTRAL")
        ]
        high_conf = [r for r in buys[:top_n] if r["confidence"] == "HIGH"]
        lines.append(f"  Avg Expected Return (top {min(top_n, len(buys))}): {avg_ret:+.1f}%")
        lines.append(f"  Directional buy setups: {len(directional)}")
        lines.append(f"  Confidence mix (HIGH): {len(high_conf)}")
        if capital:
            deployed = sum(r.get("allocation_value", 0) for r in buys[:top_n])
            lines.append(f"  Capital deployed: ₹{deployed:,.0f}  |  Remaining: ₹{capital - deployed:,.0f}")
    lines.append("\n  Model estimates only. Paper trade first. Risk 2-3% max per trade.")
    lines.append("=" * 70)

    if result["errors"]:
        lines.append(f"\n  Errors: {', '.join(result['errors'][:5])}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
