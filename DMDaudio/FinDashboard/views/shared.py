"""Shared state + cross-mode helpers for the view modules (Sprint 4.5).

``ViewContext`` bundles the per-request globals (DB path + company/label maps)
that ``app.py`` builds once and passes to each view's ``render(ctx)``. The
helper functions are the cross-mode pieces that previously lived at module
scope in app.py; they take ``db_path`` explicitly rather than reading a global,
matching the Sprint 4.3/4.4 dependency-injection convention.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from lib.cache import companies as cached_companies
from lib.cache import implied_costs, is_sections, metrics_table
from lib.cache import years as cached_years
from lib.ifrs16 import adjust_is_sections


@dataclass(frozen=True)
class ViewContext:
    """Per-render globals shared across all modes.

    Built once in app.py after the DB path and company list resolve, then
    passed to the active view's ``render(ctx)``.
    """
    db_path: str
    companies: list[tuple[str, str]]          # (IdCode, Name) pairs
    options: list[str]                        # "{IdCode} — {Name}" labels
    labels_to_idcode: dict[str, str]
    idcode_to_label: dict[str, str]


def company_short_name(companies: list[tuple[str, str]], idcode: str, maxlen: int = 24) -> str:
    """Return a short label for table columns — first part of the company name."""
    for idc, name in companies:
        if idc == idcode:
            short = name.strip()
            if len(short) > maxlen:
                short = short[: maxlen - 1] + "…"
            return short
    return idcode


def section_total_at(sections: list[dict], label_prefix: str, year: int) -> float:
    """Return the section total at a given year, or 0 if not present."""
    for s in sections:
        if s["label"].startswith(label_prefix):
            return s["total"].get(year, 0) or 0
    return 0


def adjusted_is_sections_for(
    db_path: str,
    idcode: str,
    years: list[int],
    ifrs_on: bool,
    assumed_term: float,
    interest_rate: float,
    table: str = "financial_data",
) -> list[dict]:
    """Wrapper that returns IS sections, applying the IFRS 16 reversal if requested."""
    sections = is_sections(db_path, idcode, tuple(years), table=table)
    if ifrs_on:
        ic = implied_costs(db_path, idcode, tuple(years), assumed_term, interest_rate,
                           table=table)
        return adjust_is_sections(sections, ic)
    return sections


# Column order of the metrics frame returned by sector_metrics_panel — shared
# by both the fast path and the recompute path so consumers see one shape.
_SECTOR_METRICS_COLUMNS = [
    "IdCode", "Company", "FVYear", "Revenue", "EBITDA", "NetProfit", "TotalAssets",
]

# Sprint 3 GATE — FLIPPED ON (Sprint 5, 2026-06-12). The EBITDA/NetProfit
# single source of truth landed: both `lib.income_statement.build_is_sections`
# and `lib.screener.build_metrics_table` now delegate every profitability
# subtotal to `lib.profitability.compute_profitability`, and `metrics_panel`
# was rebuilt with the canonical (IS-view) values. The panel therefore matches
# what the recompute loop has always displayed (locked by
# tests/test_ebitda_ssot_parity.py + the rewritten
# tests/test_sector_metrics_fast_path.py::test_fast_path_enabled_and_aligned).
# NOTE: flipping this back off only changes performance, not numbers — the
# recompute path produces the same canonical values now.
PANEL_FAST_PATH_ENABLED = True


@st.cache_data(show_spinner=False, ttl=3600)
def _sector_metrics_panel_cached(
    db_version: str,
    db_path: str,
    idcodes_tuple: tuple[str, ...],
    ifrs_on: bool,
    assumed_term: float,
    interest_rate: float,
) -> tuple[pd.DataFrame, list[int]]:
    """Cached per-company per-year metrics for Sector View / Compare aggregate.

    Sprint 3 dispatcher. Once ``PANEL_FAST_PATH_ENABLED`` is flipped (post
    Sprint 5), non-IFRS calls read the four metrics straight from the
    precomputed ``metrics_panel`` table — no per-company section builds.
    IFRS-on calls always use the per-company recompute (the panel is
    non-IFRS-adjusted, so it cannot serve that path).

    Cache key includes the picked idcodes tuple + IFRS settings, so adding a
    company is an INCREMENTAL cache miss (each individual company's IS/BS
    sections are still cached at the lib level).

    Returns (metrics_df, sorted_years).
    """
    if not ifrs_on and PANEL_FAST_PATH_ENABLED:
        return _sector_metrics_from_panel(db_path, idcodes_tuple)
    return _sector_metrics_recompute(
        db_path, idcodes_tuple, ifrs_on, assumed_term, interest_rate
    )


def sector_metrics_panel(
    db_path: str,
    idcodes_tuple: tuple[str, ...],
    ifrs_on: bool,
    assumed_term: float,
    interest_rate: float,
) -> tuple[pd.DataFrame, list[int]]:
    """Public entry — keys the cache on the DB file version (mtime), so a DB
    refresh invalidates immediately instead of waiting out the TTL."""
    from lib.cache import _db_version

    return _sector_metrics_panel_cached(
        _db_version(db_path), db_path, idcodes_tuple, ifrs_on, assumed_term, interest_rate
    )


def _sector_metrics_from_panel(
    db_path: str,
    idcodes_tuple: tuple[str, ...],
) -> tuple[pd.DataFrame, list[int]]:
    """Fast path: slice Revenue/EBITDA/NetProfit/TotalAssets from metrics_panel.

    Year-set parity is the crux: ``metrics_panel`` contains stub years (e.g.
    Tegeta 202177205 has a Revenue=0 FY2016 row) that ``get_years_available``
    filters out (it requires >=5 non-zero IS rows AND >=5 non-zero BS rows).
    The recompute path derives its years from ``get_years_available``, so this
    path intersects the panel's years with the same (cached) call per company —
    stub years can never leak into the aggregates.

    Plain function on purpose: ``metrics_table`` and the dispatcher are both
    cached already; decorating this too would just double-cache the result.
    """
    mt = metrics_table(db_path)
    comps = cached_companies(db_path)
    present = set(mt.index.get_level_values("IdCode")) if not mt.empty else set()
    rows: list[dict] = []
    all_years: set[int] = set()
    for idc in idcodes_tuple:
        if idc not in present:
            continue  # no financials in the panel — recompute appends nothing either
        yrs = cached_years(db_path, idc)  # same get_years_available the recompute uses
        if not yrs:
            continue
        sub = mt.xs(idc, level="IdCode")
        short = company_short_name(comps, idc)
        for y in yrs:
            if y not in sub.index:
                continue  # defensive: stale panel can't add or invent a year
            rec = sub.loc[y]
            y = int(y)
            all_years.add(y)
            rows.append({
                "IdCode": idc,
                "Company": short,
                "FVYear": y,
                # NaN -> 0.0 mirrors the recompute's `section_total_at(...) or 0`
                # zero-fill so downstream .sum() / fmt_k_gel behave identically.
                "Revenue": float(rec["Revenue"]) if pd.notna(rec["Revenue"]) else 0.0,
                "EBITDA": float(rec["EBITDA"]) if pd.notna(rec["EBITDA"]) else 0.0,
                "NetProfit": float(rec["NetProfit"]) if pd.notna(rec["NetProfit"]) else 0.0,
                "TotalAssets": float(rec["TotalAssets"]) if pd.notna(rec["TotalAssets"]) else 0.0,
            })
    if not rows:
        # Named-but-empty frame: consumers guard on .empty, but a named frame
        # keeps groupby("FVYear") from KeyError-ing should a caller skip it.
        return pd.DataFrame(columns=_SECTOR_METRICS_COLUMNS), []
    return pd.DataFrame(rows, columns=_SECTOR_METRICS_COLUMNS), sorted(all_years)


@st.cache_data(show_spinner=False, ttl=600)
def _sector_metrics_recompute(
    db_path: str,
    idcodes_tuple: tuple[str, ...],
    ifrs_on: bool,
    assumed_term: float,
    interest_rate: float,
) -> tuple[pd.DataFrame, list[int]]:
    """The original (pre-Sprint-3) per-company recompute loop, verbatim.

    Serves the IFRS-on path always, and the non-IFRS path while
    ``PANEL_FAST_PATH_ENABLED`` stays False (see the gate comment above).
    """
    from lib.income_statement import build_is_sections, bank_operating_revenue
    from lib.balance_sheet import build_bs_sections
    from lib.data_loader import get_years_available, get_companies as _gc, get_form_type

    comps = _gc(db_path)
    rows: list[dict] = []
    all_years: set[int] = set()
    for idc in idcodes_tuple:
        yrs = get_years_available(db_path, idc)
        all_years.update(yrs)
        is_secs = build_is_sections(db_path, idc, yrs)
        if ifrs_on:
            from lib.ifrs16 import compute_implied_lease_cost, adjust_is_sections
            implied = compute_implied_lease_cost(
                db_path, idc, yrs,
                assumed_term=assumed_term, interest_rate=interest_rate,
            )
            is_secs = adjust_is_sections(is_secs, implied)
        bs_sections = build_bs_sections(db_path, idc, tuple(yrs))
        # Banks: the generic IS has no meaningful Revenue (IS_Revenue is null) —
        # use Operating income as the top line, matching the metrics panel so
        # the fast path and this recompute stay aligned (parity tripwire).
        bank_rev = (
            bank_operating_revenue(db_path, idc, yrs)
            if get_form_type(db_path, idc) == "bank" else {}
        )
        short = company_short_name(comps, idc)
        for y in yrs:
            rows.append({
                "IdCode": idc,
                "Company": short,
                "FVYear": y,
                "Revenue": bank_rev.get(int(y))
                           or section_total_at(is_secs, "Total Revenue", y),
                "EBITDA": section_total_at(is_secs, "EBITDA", y),
                "NetProfit": section_total_at(is_secs, "Net Profit / (Loss)", y),
                "TotalAssets": section_total_at(bs_sections, "TOTAL ASSETS", y),
            })
    return pd.DataFrame(rows), sorted(all_years)


# ---------------------------------------------------------------------------
# Metric-picker aggregation helpers — shared by Sector View and Compare so the
# user-picked metric columns are summed / derived / formatted identically in
# both. (Kept here, not in lib/metric_picker.py, which is owned elsewhere.)
# ---------------------------------------------------------------------------
# Money columns always shown in the aggregate-by-year table. Any additional
# picked money column is summed on top of these.
BASE_AGG_COLUMNS: tuple[str, ...] = ("Revenue", "EBITDA", "NetProfit", "TotalAssets")

# Margin columns derivable from summed bases: (margin_col, numerator, denom).
# Other percent/ratio metrics can't be aggregated meaningfully, so they're only
# offered in the per-company contribution matrix.
DERIVABLE_MARGINS: tuple[tuple[str, str, str], ...] = (
    ("GrossMargin", "GrossProfit", "Revenue"),
    ("EBITDAMargin", "EBITDA", "Revenue"),
    ("NetMargin", "NetProfit", "Revenue"),
)


def format_metric_value(value, col: str) -> str:
    """Format one metric value per its metric_picker classification.

    money -> K GEL (via fmt_k_gel); percent -> "x.x%" (fmt_pct, decimals);
    ratio -> "x.xx×". Blank for None/NaN.
    """
    from lib.format import fmt_k_gel, fmt_pct
    from lib.metric_picker import is_percent_column, is_ratio_column

    if value is None or (isinstance(value, float) and value != value):
        return ""
    if is_percent_column(col):
        return fmt_pct(value)
    if is_ratio_column(col):
        try:
            return f"{float(value):,.2f}×"
        except (TypeError, ValueError):
            return ""
    return fmt_k_gel(value)


def sidebar_group_header(title: str) -> None:
    """Render a consistent, uppercase sidebar section header with a trailing rule.

    Design-A grouping for the filter views (Compare / Sectors / Screener): a
    quiet micro-label that reads as a section divider rather than ad-hoc bold
    text, matching the uppercase widget-label treatment in the brand CSS. Styled
    by ``.fd-sbgroup`` in lib/ui.inject_brand_css. ``title`` is always a
    hardcoded literal at the call sites (no user input), so it's inlined raw.
    """
    st.sidebar.markdown(
        f'<div class="fd-sbgroup">{title}</div>',
        unsafe_allow_html=True,
    )


def render_ifrs_controls(disabled_help: str | None = None) -> tuple[bool, float, float]:
    """Render the IFRS 16 toggle + sliders into the CURRENT container.

    Container-agnostic: whatever ``with`` block (sidebar expander, on-page
    popover, plain column) is active when this is called is where the widgets
    land. Returns ``(ifrs_on, assumed_term, interest_rate)``. The widget keys
    (``ifrs_on_toggle`` + the sliders) are unchanged, so state carries across
    the sidebar↔on-page move.

    `disabled_help` (if provided) replaces the default toggle help text.
    """
    ifrs_on = st.toggle(
        "Reclassify lease costs (IFRS 16 reversal)",
        value=False,
        key="ifrs_on_toggle",
        help=(
            "Reverse the post-2019 IFRS 16 split: take the implied lease cost out of D&A "
            "AND Interest Expense, put it back into OpEx as implied rent. Makes EBITDA "
            "and EBIT comparable pre-2019 and across companies that adopted differently. "
            "Uses simple lease-term and rate assumptions (configure below)."
        ) if disabled_help is None else disabled_help,
    )
    assumed_term = st.slider(
        "Assumed lease term (years)",
        min_value=3.0,
        max_value=10.0,
        value=5.0,
        step=0.5,
        disabled=not ifrs_on,
        help="Annual implied rent ≈ Lease Payable (or RoU Assets if reported) / assumed term.",
    )
    interest_rate_pct = st.slider(
        "Assumed lease interest rate (%)",
        min_value=2.0,
        max_value=12.0,
        value=6.0,
        step=0.5,
        disabled=not ifrs_on,
        help=(
            "Used to split the implied annual lease cost into depreciation (D&A) and "
            "interest (Interest Expense) portions. Higher rate → more of the lease cost "
            "treated as interest and removed from Interest Expense rather than D&A. "
            "Roughly the Georgian incremental borrowing rate."
        ),
    )
    return ifrs_on, float(assumed_term), interest_rate_pct / 100.0


def sidebar_ifrs_controls(disabled_help: str | None = None) -> tuple[bool, float, float]:
    """Render the IFRS 16 controls inside a sidebar expander (filter views).

    Thin wrapper over ``render_ifrs_controls`` that keeps the collapsible
    sidebar expander used by Compare / Sectors — it's an advanced, off-by-default
    adjustment, so the expander stays tidy and auto-opens when the toggle is on
    (read from session_state) so an active adjustment is never hidden.

    Single Company renders ``render_ifrs_controls`` directly in an on-page
    toolbar popover instead (see views/single_company.py).
    """
    # Read the toggle's current state BEFORE rendering the expander so we can
    # decide whether it starts expanded. On first render the key is absent →
    # default False → collapsed.
    _ifrs_active = bool(st.session_state.get("ifrs_on_toggle", False))
    with st.sidebar.expander("IFRS 16 Adjustment", expanded=_ifrs_active):
        return render_ifrs_controls(disabled_help)
