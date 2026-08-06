"""
market_calendar.py — NSE trading calendar helper.

Source: NSE India official holiday circulars.
Covers 2024, 2025, 2026.  Update _NSE_HOLIDAYS each January with the
new year's list from https://www.nseindia.com/resources/exchange-communication-holidays
"""
from __future__ import annotations
from datetime import date, datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

# ── Official NSE equity-segment holidays ──────────────────────────────────────
# Format: "YYYY-MM-DD"  (dates when NSE is CLOSED for equity trading)
_NSE_HOLIDAYS: set[str] = {
    # 2024
    "2024-01-22",  # Ram Mandir Consecration (special)
    "2024-01-26",  # Republic Day
    "2024-03-08",  # Mahashivratri
    "2024-03-25",  # Holi
    "2024-03-29",  # Good Friday
    "2024-04-11",  # Id-Ul-Fitr (Ramadan Eid)
    "2024-04-14",  # Dr. Ambedkar Jayanti / Ugadi
    "2024-04-17",  # Ram Navami
    "2024-04-21",  # Mahavir Jayanti
    "2024-05-01",  # Maharashtra Day
    "2024-05-23",  # Buddha Purnima
    "2024-06-17",  # Bakri Id (Eid ul-Adha)
    "2024-07-17",  # Muharram
    "2024-08-15",  # Independence Day
    "2024-10-02",  # Gandhi Jayanti / Mahatma Gandhi Birthday
    "2024-10-12",  # Dussehra
    "2024-11-01",  # Diwali-Laxmi Puja
    "2024-11-15",  # Gurunanak Jayanti / Diwali-Balipratipada
    "2024-11-20",  # Maharashtra Assembly Election
    "2024-12-25",  # Christmas

    # 2025
    "2025-02-26",  # Mahashivratri
    "2025-03-14",  # Holi
    "2025-03-31",  # Id-Ul-Fitr (Ramadan Eid)
    "2025-04-10",  # Shri Ram Navami
    "2025-04-14",  # Dr. Ambedkar Jayanti
    "2025-04-18",  # Good Friday
    "2025-05-01",  # Maharashtra Day / Buddha Purnima
    "2025-06-07",  # Eid ul-Adha (Bakri Id) — tentative
    "2025-08-15",  # Independence Day
    "2025-08-27",  # Ganesh Chaturthi
    "2025-10-02",  # Gandhi Jayanti / Dussehra
    "2025-10-21",  # Diwali eve (Diwali-Laxmi Puja) — tentative
    "2025-10-22",  # Diwali (Laxmi Puja) — tentative
    "2025-10-23",  # Diwali (Balipratipada) — tentative
    "2025-11-05",  # Gurunanak Jayanti — tentative
    "2025-12-25",  # Christmas

    # 2026 — tentative (will be confirmed by NSE circular in Jan 2026)
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi — tentative
    "2026-03-20",  # Ugadi / Gudi Padwa — tentative
    "2026-04-03",  # Good Friday — tentative
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-10-02",  # Gandhi Jayanti
    "2026-11-14",  # Diwali (Laxmi Puja) — tentative
    "2026-12-25",  # Christmas
}

# NSE equity trading hours (IST = UTC+5:30)
_MARKET_OPEN_IST  = (9, 15)   # 09:15
_MARKET_CLOSE_IST = (15, 30)  # 15:30
_IST_OFFSET = timedelta(hours=5, minutes=30)


def is_nse_holiday(d: date) -> bool:
    """Return True if `d` is an NSE-declared holiday (not a weekend)."""
    return d.isoformat() in _NSE_HOLIDAYS


def is_trading_day(d: date | None = None) -> bool:
    """Return True if `d` (default = today IST) is an NSE equity trading day."""
    if d is None:
        d = _today_ist()
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return not is_nse_holiday(d)


def next_trading_day(d: date | None = None) -> date:
    """Return the first NSE trading day on or after `d` (today IST if None).

    On a weekday trading day returns `d` unchanged. On weekends or holidays
    advances forward until the next trading day (up to 10 days).
    """
    if d is None:
        d = _today_ist()
    probe = d
    for _ in range(10):
        if is_trading_day(probe):
            return probe
        probe += timedelta(days=1)
    return probe  # fallback — should never happen for valid calendars


def _today_ist() -> date:
    return (datetime.now(timezone.utc) + _IST_OFFSET).date()


def _now_ist() -> datetime:
    return datetime.now(timezone.utc) + _IST_OFFSET


def market_status(d: date | None = None) -> dict:
    """
    Return a dict describing the current NSE market status.

    Keys:
        is_open        bool  — True if market is currently open
        is_trading_day bool  — True if today is a trading day (regardless of time)
        status         str   — "OPEN" | "CLOSED" | "PRE_MARKET" | "POST_MARKET" | "WEEKEND" | "HOLIDAY"
        message        str   — Human-readable label
        date           str   — ISO date in IST
        next_open      str | None  — ISO date of next trading day (if today is non-trading)
    """
    now_ist = _now_ist()
    today = now_ist.date() if d is None else d
    check_time = d is None  # only check intraday status for "today" queries

    if today.weekday() >= 5:
        status = "WEEKEND"
        msg = f"Market closed — {today.strftime('%A')} (weekend)"
    elif is_nse_holiday(today):
        status = "HOLIDAY"
        msg = f"Market closed — NSE holiday on {today.strftime('%d %b %Y')}"
    elif check_time:
        h, m = now_ist.hour, now_ist.minute
        open_mins  = _MARKET_OPEN_IST[0]  * 60 + _MARKET_OPEN_IST[1]
        close_mins = _MARKET_CLOSE_IST[0] * 60 + _MARKET_CLOSE_IST[1]
        cur_mins   = h * 60 + m
        if cur_mins < open_mins:
            status = "PRE_MARKET"
            msg = f"Pre-market — NSE opens at 09:15 IST"
        elif cur_mins > close_mins:
            status = "POST_MARKET"
            msg = f"Market closed for the day — NSE closed at 15:30 IST"
        else:
            status = "OPEN"
            msg = f"Market OPEN — NSE trading until 15:30 IST"
    else:
        status = "OPEN"  # it's a trading day (no time check for historical dates)
        msg = f"Trading day — {today.strftime('%d %b %Y')}"

    # Compute next trading day when closed
    next_open: str | None = None
    if status in ("WEEKEND", "HOLIDAY", "POST_MARKET"):
        probe = today + timedelta(days=1)
        for _ in range(10):
            if is_trading_day(probe):
                next_open = probe.isoformat()
                break
            probe += timedelta(days=1)

    return {
        "is_open":        status == "OPEN",
        "is_trading_day": is_trading_day(today),
        "status":         status,
        "message":        msg,
        "date":           today.isoformat(),
        "next_open":      next_open,
    }
