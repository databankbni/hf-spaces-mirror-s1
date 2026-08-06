#!/usr/bin/env python3
"""
stock_ranker.py — Find the best Indian stocks to buy for a given date range.

Usage:
  python3 stock_ranker.py --start 2026-06-15 --end 2026-06-30
  python3 stock_ranker.py --start 2026-06-15 --end 2026-06-30 --capital 500000
  python3 stock_ranker.py --start 2026-06-15 --end 2026-06-30 --capital 500000 --stocks RELIANCE.NS TCS.NS INFY.NS
  python3 stock_ranker.py --start 2026-06-15 --end 2026-07-15 --capital 1500000 --top 5

Arguments:
  --start    YYYY-MM-DD  Prediction start date (required)
  --end      YYYY-MM-DD  Prediction end date   (required)
  --capital  INR amount  Optional capital to invest (e.g. 500000 for ₹5L)
  --stocks   TICKER...   Optional custom stock list (default: 34-stock universe)
  --top      N           Show top N picks in detail (default: 8)
  --json                 Output raw JSON instead of formatted report

Output:
  Ranked list of best stocks with expected % return, confidence level,
  news sentiment, and capital allocation (if --capital provided).
"""

import argparse
import json
import sys
from datetime import datetime

import warnings
warnings.filterwarnings("ignore")

# ── Ensure predictor_core is importable from the same dir ────────────────────
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from predictor_core import rank_stocks_v2 as rank_stocks, predict_stock_v2 as predict_stock, DEFAULT_UNIVERSE

SEP  = "=" * 72
SEP2 = "─" * 72


# ── FORMATTERS ────────────────────────────────────────────────────────────────
def _bar(score: int, width: int = 20) -> str:
    filled = int(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _conf_label(c: str) -> str:
    return {"HIGH": "▶▶▶ HIGH", "MEDIUM": "▶▶  MED ", "LOW": "▶   LOW "}.get(c, "?")


def format_report(result: dict, top_n: int) -> str:
    lines = []
    ranked  = result["ranked"]
    market  = result.get("market", {})
    capital = result.get("capital")

    lines.append(f"\n{SEP}")
    lines.append("  INDIAN EQUITY RANKER — BEST STOCKS TO BUY")
    lines.append(SEP)
    lines.append(f"  Period   : {result['start_date']}  →  {result['end_date']}")
    if capital:
        lines.append(f"  Capital  : ₹{capital:,.0f}")
    lines.append(f"  Scanned  : {result['total_scanned']} stocks  |  Scored: {result['total_scored']}")
    lines.append(f"  VIX      : {market.get('vix_label', 'N/A')}")
    lines.append(f"  Nifty    : {market.get('nifty_label', 'N/A')}")
    lines.append(f"  Macro    : {market.get('macro_label', 'N/A')}")
    lines.append(SEP)

    buys  = [r for r in ranked if r["direction"] not in ("BEARISH", "SLIGHTLY BEARISH", "NO TRADE")]
    bears = [r for r in ranked if r["direction"] in ("BEARISH", "SLIGHTLY BEARISH")]

    if not buys:
        lines.append("\n  No bullish setups in current universe for this window.")
        lines.append("  The market may be in a defensive phase. Stay in cash or reduce exposure.")
    else:
        lines.append(f"\n  TOP PICKS  ({min(top_n, len(buys))} of {len(buys)} bullish stocks)\n")

        for r in buys[:top_n]:
            ml_s   = r.get("ml", {})
            news   = r.get("news", {})
            dir_s  = "UP" if "BULLISH" in r["direction"] else "--"
            earn   = r.get("earnings", {})

            lines.append(f"  {SEP2}")
            lines.append(f"  #{r['rank']:<2}  {r['ticker']:<18}  {dir_s}  {r['direction']:<20}  [{_conf_label(r['confidence'])}]")
            lines.append(f"      Company: {r.get('company', '')}")
            lines.append(f"      Price  : ₹{r['price']:>10,.2f}   |  {r['trading_days']}d window")
            lines.append(f"      Expect : {r['expected_return_range']:<22}  midpoint {r['midpoint']:+.1f}%")
            lines.append(f"      Signals: {', '.join(r['active_strategies']) or 'none active'}  ({r['signal_count']} fired)")
            lines.append(f"      ML     : [{_bar(ml_s.get('score', 50))}] {ml_s.get('score', 50)}/100  prob={ml_s.get('probability', 0.5)}")
            lines.append(f"      News   : {news.get('label', 'NEUTRAL'):<8} ({news.get('score', 0):+d})  [{news.get('source', '?')}]")

            if news.get("summary"):
                lines.append(f"               {news['summary'][:70]}")
            if news.get("headlines"):
                lines.append(f"               Latest: {news['headlines'][0][:65]}")

            if earn.get("in_blackout"):
                lines.append(f"      *** EARNINGS BLACKOUT: {earn['warning']} ***")
            elif earn.get("next_date"):
                lines.append(f"      Earnings: {earn['next_date']} ({earn['days_away']}d away)")

            if capital and r.get("suggested_allocation"):
                lines.append(f"      Alloc: ₹{r['suggested_allocation']:,.0f}  →  {r['suggested_shares']} shares  (₹{r['allocation_value']:,.0f} deployed)")

            lines.append("")

    if bears:
        lines.append(f"\n  AVOID  ({len(bears)} bearish setups)")
        lines.append(f"  {'Ticker':<18}  {'Direction':<22}  Signals  News")
        for r in bears:
            lines.append(f"  {r['ticker']:<18}  {r['direction']:<22}  {r['signal_count']:<7}  {r.get('news', {}).get('label', 'N/A')}")

    lines.append(f"\n{SEP}")
    lines.append("  SUMMARY")
    lines.append(SEP2)

    if buys:
        top   = buys[:top_n]
        avg   = round(sum(r["midpoint"] for r in top) / len(top), 1)
        highs = [r for r in top if r["confidence"] == "HIGH"]
        lines.append(f"  Avg expected return (top {len(top)}): {avg:+.1f}% over period")
        lines.append(f"  HIGH confidence picks: {len(highs)}")
        lines.append(f"  Best single pick: {top[0]['ticker']}  ->  {top[0]['expected_return_range']}")

        if capital:
            deployed = sum(r.get("allocation_value", 0) for r in top)
            leftover = capital - deployed
            lines.append(f"  Capital deployed: ₹{deployed:,.0f}  |  Cash held: ₹{leftover:,.0f}")
            if leftover < 0:
                lines.append(f"  Over-allocated by ₹{-leftover:,.0f} — reduce position sizes")

    lines.append("")
    lines.append("  RISK MANAGEMENT REMINDER:")
    lines.append("  - Risk 2-3% of capital per trade (₹{:,.0f})".format(
        round((capital or 1_500_000) * 0.025, 0)
    ))
    lines.append("  - No new trades if VIX > 25 or Nifty < EMA200")
    lines.append("  - Max 5-6 open positions simultaneously")
    lines.append("  - Set stop-loss at 1.5x ATR14 below entry")
    lines.append("")
    lines.append("  These are model-based estimates, not financial advice.")
    lines.append("  Paper trade for 20+ signals before deploying real capital.")
    lines.append(SEP)

    if result["errors"]:
        lines.append(f"\n  Data errors: {', '.join(result['errors'][:5])}")

    return "\n".join(lines)


# ── SINGLE STOCK DETAILED REPORT ──────────────────────────────────────────────
def format_single(pred: dict) -> str:
    if "error" in pred:
        return f"\n  {pred['ticker']}: {pred['error']}\n"

    lines = []
    ml    = pred.get("ml", {})
    news  = pred.get("news", {})
    earn  = pred.get("earnings", {})
    kl    = pred.get("key_levels", {})
    mkt   = pred.get("market", {})
    feat  = ml.get("features", {})

    lines.append(f"\n{SEP}")
    lines.append(f"  {pred['ticker']}  ({pred.get('company', '')})  |  {pred['start_date']} -> {pred['end_date']}")
    lines.append(SEP)
    lines.append(f"  Price     : ₹{pred['price']:,.2f}")
    lines.append(f"  Direction : {pred['direction']}")
    lines.append(f"  Confidence: {pred['confidence']}")
    lines.append(f"  Expected  : {pred['expected_return_range']}  (midpoint {pred['midpoint']:+.1f}%)")
    lines.append(f"  Period    : {pred['trading_days']} trading days")
    lines.append("")
    lines.append(f"  Active Signals: {', '.join(pred['active_strategies']) or 'None'}")
    lines.append(f"    S1 (Shadow Recovery) : {'FIRED' if pred['signals'].get('S1') else 'no'}")
    lines.append(f"    S2 (Momentum Breakout): {'FIRED' if pred['signals'].get('S2') else 'no'}")
    lines.append(f"    S3 (EMA Ribbon)      : {'FIRED' if pred['signals'].get('S3') else 'no'}")
    lines.append(f"    MFS (Multi-Factor)   : {'FIRED' if pred['signals'].get('MFS') else 'no'}")
    lines.append(f"    NIRA (Reconstitution): {'FIRED' if pred['signals'].get('NIRA') else 'no'}")
    lines.append("")
    lines.append(f"  ML Feature Score: [{_bar(ml.get('score', 50))}] {ml.get('score', 50)}/100")
    lines.append(f"    Probability  : {ml.get('probability', 0.5):.3f}  (threshold 0.60)")
    lines.append(f"    Upgraded     : {'Yes' if ml.get('upgraded') else 'No'}")
    if feat:
        lines.append(f"    RSI          : {feat.get('rsi', '?')}")
        lines.append(f"    EMA Stack    : {feat.get('ema_stack', '?'):.2f}  (1.0=fully aligned)")
        lines.append(f"    ADX          : {feat.get('adx', '?')}")
        lines.append(f"    RS (3M)      : {feat.get('rs_3m_pct', '?'):+.1f}% vs Nifty")
        lines.append(f"    Volume Ratio : {feat.get('vol_ratio', '?')}x")
        lines.append(f"    MACD Positive: {'Yes' if feat.get('macd_pos') else 'No'}")
    lines.append("")
    lines.append(f"  News  : {news.get('label', 'NEUTRAL')} (score: {news.get('score', 0):+d})  [{news.get('source', '?')}]")
    if news.get("summary"):
        lines.append(f"    Summary: {news['summary']}")
    for h in news.get("headlines", [])[:3]:
        lines.append(f"    - {h[:70]}")
    lines.append("")
    if earn.get("in_blackout"):
        lines.append(f"  *** EARNINGS BLACKOUT: {earn['warning']} ***")
    elif earn.get("next_date"):
        lines.append(f"  Earnings: {earn['next_date']} ({earn['days_away']}d away)")
    kl20  = f"₹{kl['ema20']:,.2f}"  if kl.get("ema20")  else "N/A"
    kl50  = f"₹{kl['ema50']:,.2f}"  if kl.get("ema50")  else "N/A"
    kl200 = f"₹{kl['ema200']:,.2f}" if kl.get("ema200") else "N/A"
    lines.append(f"  Key Levels: EMA20 {kl20}  |  EMA50 {kl50}  |  EMA200 {kl200}")
    lines.append(f"  VIX       : {mkt.get('vix_label', 'N/A')}")
    lines.append(f"  Nifty Gate: {mkt.get('nifty_label', 'N/A')}")
    lines.append(f"  Macro     : {mkt.get('macro_label', 'N/A')}")
    lines.append(SEP)
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Rank Indian NSE stocks by expected performance over a date range.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--start",   required=True,  help="Start date YYYY-MM-DD")
    p.add_argument("--end",     required=True,  help="End date YYYY-MM-DD")
    p.add_argument("--capital", type=float,     help="Capital in INR (e.g. 500000)")
    p.add_argument("--stocks",  nargs="*",      help="Custom stock list (NSE tickers)")
    p.add_argument("--top",     type=int, default=8, help="Show top N picks (default: 8)")
    p.add_argument("--json",    action="store_true", help="Output raw JSON")
    return p.parse_args()


def main():
    args = parse_args()

    # Validate dates
    try:
        s = datetime.strptime(args.start, "%Y-%m-%d")
        e = datetime.strptime(args.end,   "%Y-%m-%d")
        if e <= s:
            print("ERROR: end date must be after start date.", file=sys.stderr)
            sys.exit(1)
    except ValueError as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        sys.exit(1)

    # Normalize tickers
    universe = None
    if args.stocks:
        universe = [
            t.upper().strip() if "." in t else t.upper().strip() + ".NS"
            for t in args.stocks
        ]

    print(f"\n  Scanning universe for {args.start} → {args.end}...", flush=True)
    print("  Fetching price data and news (this may take 30-60 seconds)...\n", flush=True)

    result = rank_stocks(args.start, args.end, universe=universe, capital=args.capital)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_report(result, args.top))


if __name__ == "__main__":
    main()
