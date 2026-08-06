"""
costs.py — Realistic NSE equity transaction-cost model.

Motivation (see research doc "Stock-Prediction-Models: Key Takeaways"):
price prediction ≠ profitable trading. A backtest that ignores fees, and a
predictor that only says "tomorrow ≈ today" (a tiny ±0.07% band that always
"hits"), both LOOK great and make no money. Costs are the reality check: a move
that doesn't clear the round-trip cost is not a tradeable edge.

Round-trip = buy + sell. Components for NSE cash-market equity:
  - Brokerage      : discount-broker model — ₹0 delivery, min(0.03%, ₹20)/leg intraday
  - STT            : delivery 0.10% buy + 0.10% sell; intraday 0.025% sell-only
  - Exchange txn   : ~0.00297% per leg (NSE)
  - SEBI charges   : 0.0001% per leg
  - Stamp duty     : delivery 0.015% buy-only; intraday 0.003% buy-only
  - GST            : 18% on (brokerage + exchange txn + SEBI)

Everything is expressed as a **percent of trade value** so it composes with the
percentage returns used throughout the predictor.
"""
from __future__ import annotations

# Per-leg / round-trip rates as fractions of trade value (not %).
_STT_DELIVERY_PER_SIDE = 0.0010      # 0.10% buy AND sell
_STT_INTRADAY_SELL     = 0.00025     # 0.025% sell-only
_EXCH_TXN_PER_SIDE     = 0.0000297   # NSE ~0.00297%
_SEBI_PER_SIDE         = 0.000001    # 0.0001%
_STAMP_DELIVERY_BUY    = 0.00015     # 0.015% buy-only
_STAMP_INTRADAY_BUY    = 0.00003     # 0.003% buy-only
_GST                   = 0.18        # on brokerage + exch txn + SEBI
_BROKERAGE_INTRADAY    = 0.0003      # 0.03% per leg (discount broker)
_BROKERAGE_INTRADAY_CAP = 20.0       # ₹20 per leg cap
_BROKERAGE_DELIVERY    = 0.0         # ₹0 delivery (discount broker)


def round_trip_cost_pct(intraday: bool = False,
                        price: float | None = None,
                        qty: int | None = None) -> float:
    """Return the total round-trip cost as a PERCENT of trade value.

    If price and qty are given, brokerage caps (₹20/leg intraday) are applied
    exactly; otherwise brokerage uses the uncapped percentage (conservative for
    small tickets, slightly high for large ones — fine as a threshold).
    """
    if intraday:
        stt = _STT_INTRADAY_SELL
        stamp = _STAMP_INTRADAY_BUY
        brok_rate = _BROKERAGE_INTRADAY
        brok_cap = _BROKERAGE_INTRADAY_CAP
    else:
        stt = _STT_DELIVERY_PER_SIDE * 2  # both legs
        stamp = _STAMP_DELIVERY_BUY
        brok_rate = _BROKERAGE_DELIVERY
        brok_cap = None

    exch = _EXCH_TXN_PER_SIDE * 2
    sebi = _SEBI_PER_SIDE * 2

    # Brokerage as a fraction of value (both legs), honoring the per-leg cap.
    if brok_rate <= 0:
        brok_frac = 0.0
    elif price and qty and price * qty > 0:
        value = price * qty
        per_leg = min(brok_rate * value, brok_cap) if brok_cap else brok_rate * value
        brok_frac = (per_leg * 2) / value
    else:
        brok_frac = brok_rate * 2  # uncapped %

    gst = _GST * (brok_frac + exch + sebi)
    total = stt + exch + sebi + stamp + brok_frac + gst
    return round(total * 100, 4)  # as percent


# Convenience defaults so callers don't need a ticket size:
#   delivery (1D/3D swing) ≈ 0.27%, intraday ≈ 0.10%
ROUND_TRIP_DELIVERY_PCT = round_trip_cost_pct(intraday=False)
ROUND_TRIP_INTRADAY_PCT = round_trip_cost_pct(intraday=True)


def cost_pct_for_timeframe(tf_label: str) -> float:
    """Round-trip cost % for a timeframe. INTRADAY uses the intraday rate;
    1D/3D/5D are held overnight → delivery (CNC) rates."""
    return ROUND_TRIP_INTRADAY_PCT if (tf_label or "").upper() == "INTRADAY" else ROUND_TRIP_DELIVERY_PCT


def net_return_pct(gross_return_pct: float, tf_label: str = "1D") -> float:
    """Gross % return minus round-trip cost for the timeframe."""
    return round(gross_return_pct - cost_pct_for_timeframe(tf_label), 3)


def clears_costs(expected_move_pct: float, tf_label: str = "1D", margin: float = 1.0) -> bool:
    """True if |expected move %| exceeds round-trip cost × margin — i.e. the
    predicted edge survives fees. margin>1 demands a profit cushion beyond breakeven."""
    return abs(expected_move_pct) >= cost_pct_for_timeframe(tf_label) * margin


if __name__ == "__main__":
    print(f"NSE round-trip cost — delivery: {ROUND_TRIP_DELIVERY_PCT}%  intraday: {ROUND_TRIP_INTRADAY_PCT}%")
    for tf, mv in [("1D", 0.07), ("1D", 0.86), ("INTRADAY", 0.5), ("3D", 2.0)]:
        print(f"  {tf} move {mv:+.2f}% -> net {net_return_pct(mv, tf):+.3f}%  clears={clears_costs(mv, tf)}")
