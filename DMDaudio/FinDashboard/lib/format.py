from collections.abc import Iterable

import pandas as pd
import streamlit as st

# Visual marker prepended to a company label when its latest filed year lags the
# dataset's max year — signals "this company's most recent numbers are stale".
STALE_MARKER = "⚠"  # ⚠


def _as_int_year(value) -> int | None:
    """Coerce a possibly-None / NaN / str year to int, or None if not parseable."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_stale(latest_year, dataset_max_year) -> bool:
    """True when a company's latest filed year is older than the dataset max year.

    A company is "stale" if its most recent filing predates the newest year
    present anywhere in the dataset — i.e. it stopped reporting before the
    frontier. Unknown / unparseable latest years are treated as NOT stale
    (we don't flag what we can't measure).
    """
    ly = _as_int_year(latest_year)
    my = _as_int_year(dataset_max_year)
    if ly is None or my is None:
        return False
    return ly < my


def stale_count(latest_years: Iterable, dataset_max_year) -> tuple[int, int]:
    """Return ``(n_stale, n_total)`` over an iterable of latest-filed years.

    ``n_total`` counts only companies with a parseable latest year; companies
    whose latest year is unknown are excluded from BOTH numerator and
    denominator so the caption reads honestly.
    """
    my = _as_int_year(dataset_max_year)
    n_total = 0
    n_stale = 0
    for ly in latest_years:
        ly_i = _as_int_year(ly)
        if ly_i is None or my is None:
            continue
        n_total += 1
        if ly_i < my:
            n_stale += 1
    return n_stale, n_total


def stale_caption(latest_years: Iterable, dataset_max_year) -> str | None:
    """Build a caption like '12 of 50 companies last filed before FY2024'.

    Returns ``None`` when nothing is stale (or the dataset max year is unknown),
    so callers can omit the caption entirely in the clean case.
    """
    my = _as_int_year(dataset_max_year)
    if my is None:
        return None
    n_stale, n_total = stale_count(latest_years, dataset_max_year)
    if n_stale <= 0 or n_total <= 0:
        return None
    return (
        f"{STALE_MARKER} {n_stale} of {n_total} companies last filed before "
        f"FY{my} (marked {STALE_MARKER})."
    )


def display_decimals() -> int:
    """Read the user-chosen decimal precision (0/1/2) from session state."""
    return int(st.session_state.get("display_decimals", 0))


def fmt_k_gel(v) -> str:
    """Format a raw GEL value as thousands. Blank for 0/None/NaN; parens for negatives.

    Decimal count is read from session state (the sidebar "Decimal precision"
    selector) so the user can flip 0/1/2 globally without re-rendering wiring.
    """
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    try:
        f = float(v) / 1000.0
    except (TypeError, ValueError):
        return str(v)
    d = display_decimals()
    if d == 0 and abs(f) < 0.5:
        # Avoid rendering tiny values that round to zero at 0-decimal precision
        # as the bare string "0" — keep them blank like true zeros for clarity.
        return ""
    if f == 0:
        return ""
    if f < 0:
        return f"({abs(f):,.{d}f})"
    return f"{f:,.{d}f}"


def fmt_pct(v) -> str:
    """Format a decimal proportion (0.123) as a percentage (12.3% at 1 decimal).

    Decimal count follows the same session-state setting as `_fmt`.
    """
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    if v == 0:
        return ""
    d = display_decimals()
    return f"{v * 100:,.{d}f}%"


def fmt_pct_signed(v, min_decimals: int = 1) -> str:
    """Margin-style percent: parenthesized negatives, blank for 0/None/NaN.

    THE shared formatter for statement margin rows / common-size cells / CAGR
    percents — previously four near-identical private copies had drifted
    (2026-07-02 review). Decimals = max(global "Decimal precision" setting,
    ``min_decimals``): the user setting can RAISE precision, but statement
    tables never drop below 1 decimal (0-decimal margins are unreadable).
    """
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    if v == 0:
        return ""
    d = max(display_decimals(), min_decimals)
    if v < 0:
        return f"({abs(v) * 100:,.{d}f}%)"
    return f"{v * 100:,.{d}f}%"


def fmt_money_compact(v) -> str:
    """Compact ₾ for KPI tiles: ``₾1.2bn`` / ``₾45.1m`` / ``₾6,200k``.

    Returns an em-dash for None/NaN (KPI tiles need a visible placeholder,
    unlike table cells which blank). Decimals follow the global "Decimal
    precision" setting, floored at 1 for bn/m so the compact form never
    collapses to a bare ``₾1bn``.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    d = display_decimals()
    a = abs(f)
    if a >= 1e9:
        return f"₾{f / 1e9:,.{max(d, 1)}f}bn"
    if a >= 1e6:
        return f"₾{f / 1e6:,.{max(d, 1)}f}m"
    if a >= 1e3:
        return f"₾{f / 1e3:,.{d}f}k"
    return f"₾{f:,.{d}f}"
