"""Shared finance-ratio primitives — the single source of truth for the
return ratios (ROE, ROA, ROIC) and their guard rules.

Both the Screener / ``metrics_panel`` build path (``lib.screener`` →
``scripts.build_metrics_panel``) and the Single-Company Ratios tab
(``lib.ratios``) delegate here so the SAME labelled metric agrees everywhere.
Pure functions only — no DB, Streamlit, or pandas dependency — so it imports
cheaply from build scripts and tests.

Guard rules (mirroring the existing Net Debt / EBITDA guard in the screener,
which returns ``None`` when EBITDA <= 0):

* **ROE** is meaningful only when **equity > 0**. A negative or zero equity
  base makes the ratio sign-blind — a loss divided by negative equity yields a
  *positive* "return" (e.g. IdCode 200002120 FY2019: NetProfit -354,044 /
  equity -150,751 = +234.9%). Return ``None`` instead.
* **ROA** is meaningful only when the **asset base > 0** (assets are virtually
  always positive, but guard for symmetry and safety).
* **ROIC** uses **net-debt invested capital** (``Total Equity + Net Debt``,
  where ``Net Debt = Total Debt − Cash``) — the standard definition. Return
  ``None`` when invested capital <= 0 (a negative base makes EBIT/IC
  sign-blind the same way ROE is).
"""
from __future__ import annotations


def safe_div(num: float | None, den: float | None) -> float | None:
    """Plain guarded division: ``None`` when the denominator is falsy/zero."""
    if not den or den == 0:
        return None
    return num / den


def roe(net_profit: float | None, total_equity: float | None) -> float | None:
    """Return on Equity. ``None`` when equity <= 0 (sign-blind otherwise)."""
    if total_equity is None or total_equity <= 0:
        return None
    return safe_div(net_profit, total_equity)


def roa(net_profit: float | None, total_assets: float | None) -> float | None:
    """Return on Assets. ``None`` when the asset base <= 0."""
    if total_assets is None or total_assets <= 0:
        return None
    return safe_div(net_profit, total_assets)


def invested_capital(total_equity: float | None, net_debt: float | None) -> float:
    """Net-debt invested capital = Total Equity + Net Debt.

    ``Net Debt`` is ``Total Debt − Cash`` (can be negative for net-cash
    companies). This is the canonical ROIC denominator used across the app.
    """
    return (total_equity or 0.0) + (net_debt or 0.0)


def roic(
    ebit: float | None,
    total_equity: float | None,
    net_debt: float | None,
) -> float | None:
    """Return on Invested Capital = EBIT / (Total Equity + Net Debt).

    ``None`` when invested capital <= 0 (negative base is sign-blind).
    """
    ic = invested_capital(total_equity, net_debt)
    if ic <= 0:
        return None
    return safe_div(ebit, ic)
