"""Bulk metrics table for the Screener mode.

Precomputes one row per (IdCode, FVYear) with all common screener metrics so the
UI can apply pandas boolean masks for filtering, rather than re-running
per-company section builders for thousands of companies.

Heavy lift lives in :func:`build_metrics_table`. The Streamlit caller wraps it
in ``@st.cache_data(ttl=3600)``; this module stays cache-free so it can be
imported safely from tests.
"""
from __future__ import annotations

import re
import sqlite3

import pandas as pd

# Metrics surfaced as default chips in the screener UI. Users can also type any
# raw LineItemENG via free-form input.
# Base metrics that get growth/CAGR variants generated.
_GROWTH_BASE: tuple[tuple[str, str], ...] = (
    ("Revenue", "Revenue"),
    ("EBITDA", "EBITDA"),
    ("Net Profit", "NetProfit"),
    ("Gross Profit", "GrossProfit"),
    ("Total Assets", "TotalAssets"),
)

# Growth periods to expose: 1yr (YoY) + 2-6yr CAGR.
_GROWTH_PERIODS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)


def _growth_label(metric: str, n: int) -> str:
    return f"{metric} YoY" if n == 1 else f"{metric} {n}yr CAGR"


def _growth_column(col: str, n: int) -> str:
    return f"{col}_YoY" if n == 1 else f"{col}_{n}yrCAGR"


# Generate the growth metric names + columns at import time.
_GROWTH_METRIC_NAMES: tuple[str, ...] = tuple(
    _growth_label(label, n)
    for label, _col in _GROWTH_BASE
    for n in _GROWTH_PERIODS
)
_GROWTH_METRIC_COLUMNS: dict[str, str] = {
    _growth_label(label, n): _growth_column(col, n)
    for label, col in _GROWTH_BASE
    for n in _GROWTH_PERIODS
}


DEFAULT_METRICS: tuple[str, ...] = (
    # Size (raw GEL)
    "Revenue",
    "Gross Profit",
    "Net Profit",
    "EBITDA",
    "Total Assets",
    "Total Cash",
    "Total Debt",
    "Net Debt",
    # Returns / margins (percent — stored as decimals, e.g. 0.12 = 12%)
    "Gross Margin",
    "EBITDA Margin",
    "Net Margin",
    "ROE",
    "ROA",
    "ROIC",
    # Leverage + capital intensity (pure ratios — not percent, not GEL)
    "Net Debt / EBITDA",
    "Asset Turnover",
) + _GROWTH_METRIC_NAMES

# Mapping of metric name -> internal column name in the metrics table.
METRIC_TO_COLUMN: dict[str, str] = {
    "Revenue": "Revenue",
    "Gross Profit": "GrossProfit",
    "Net Profit": "NetProfit",
    "EBITDA": "EBITDA",
    "Total Assets": "TotalAssets",
    "Total Cash": "TotalCash",
    "Total Debt": "TotalDebt",
    "Net Debt": "NetDebt",
    "Total Equity": "TotalEquity",
    "Gross Margin": "GrossMargin",
    "EBITDA Margin": "EBITDAMargin",
    "Net Margin": "NetMargin",
    "ROE": "ROE",
    "ROA": "ROA",
    "ROIC": "ROIC",
    "Net Debt / EBITDA": "NetDebtToEBITDA",
    "Asset Turnover": "AssetTurnover",
    **_GROWTH_METRIC_COLUMNS,
}

# Ratio metrics — pure numbers (not money, not percent). Used by the UI to
# decide formatting (e.g. "2.3x" not "2.3 K GEL", and no percent sign).
RATIO_METRICS: frozenset[str] = frozenset({"Net Debt / EBITDA", "Asset Turnover"})

# Decimal-percent metrics (values stored as 0.20 == 20%).
# Growth/CAGR metrics are also stored as decimals (0.15 == 15%).
PERCENT_METRICS: frozenset[str] = frozenset(
    {"Gross Margin", "EBITDA Margin", "Net Margin", "ROE", "ROA", "ROIC"}
    | set(_GROWTH_METRIC_NAMES)
)


def compute_growth_columns(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute per-year growth and CAGR metrics from a company/year panel.

    Input: ``panel`` indexed by (IdCode, FVYear) with metric columns like
    ``Revenue``, ``EBITDA``, ``NetProfit``, etc. (the output of
    :func:`build_metrics_table`, or a ``SELECT *`` off ``metrics_panel``).

    Output: DataFrame on the SAME (IdCode, FVYear) index with one column per
    ``{base_metric}_{period}`` combination. Every cell is the growth *ending in
    that row's year*:

      * YoY (n=1)   ``(v[y] - v[y-1]) / abs(v[y-1])``
      * CAGR (n≥2)  ``(v[y] / v[y-n]) ** (1/n) - 1``

    So ``Revenue_YoY`` on the FY2023 row is FY2023-vs-FY2022 — not the
    company's latest YoY.

    The lookback is **calendar-strict**: it reads the row for ``FVYear - n``, so
    a filing gap yields NaN instead of silently measuring growth over a longer
    span (a "3yr CAGR" that actually spans five years is not a 3yr CAGR).
    NaN also when the lookback row/value is missing, when the YoY base is zero,
    or — for CAGR — when either endpoint is non-positive, since a rate across a
    sign flip is meaningless. YoY keeps ``abs(base)`` in the denominator so a
    swing out of a loss doesn't come back with an inverted sign.

    Until 2026-07-30 this returned one scalar per company (computed off its last
    n+1 non-null observations), which callers broadcast onto every year row —
    see :func:`scripts.build_metrics_panel._populate_growth_columns`.
    """
    if panel.empty:
        return pd.DataFrame()

    # Normalize the key dtypes once: the lookback is a hash lookup on
    # (IdCode, FVYear - n), so a float-vs-int FVYear would silently miss.
    idcodes = panel.index.get_level_values("IdCode")
    years = panel.index.get_level_values("FVYear").astype("int64")
    norm_index = pd.MultiIndex.from_arrays(
        [idcodes, years], names=["IdCode", "FVYear"]
    )
    nan = float("nan")

    out: dict[str, pd.Series] = {}
    for _label, col in _GROWTH_BASE:
        if col not in panel.columns:
            continue
        cur = pd.to_numeric(panel[col], errors="coerce")
        # Lookback source: same values, normalized key, unique (the panel is
        # PK'd on (IdCode, FVYear) — dedupe defensively so reindex can't raise).
        lookup = pd.Series(cur.to_numpy(dtype="float64"), index=norm_index)
        lookup = lookup[~lookup.index.duplicated(keep="first")]

        for n in _GROWTH_PERIODS:
            prior = pd.Series(
                lookup.reindex(
                    pd.MultiIndex.from_arrays([idcodes, years - n])
                ).to_numpy(),
                index=panel.index,
            )
            res = pd.Series(nan, index=panel.index, dtype="float64")
            if n == 1:
                ok = cur.notna() & prior.notna() & (prior != 0)
                res[ok] = (cur[ok] - prior[ok]) / prior[ok].abs()
            else:
                # Positive endpoints only. NaN compares False, so this also
                # filters out the missing-value rows.
                ok = (cur > 0) & (prior > 0)
                res[ok] = (cur[ok] / prior[ok]) ** (1.0 / n) - 1.0
            out[_growth_column(col, n)] = res

    return pd.DataFrame(out, index=panel.index) if out else pd.DataFrame()


# ---------------------------------------------------------------------------
# Value-shorthand parsing
# ---------------------------------------------------------------------------

_SHORTHAND_RE = re.compile(
    r"""^\s*
        (?P<paren>\()?
        \s*
        (?P<sign>[+-])?
        \s*
        (?P<num>\d+(?:[\.,]\d+)?)
        \s*
        (?P<suffix>[kmbtKMBT%])?
        \s*
        (?P<closeparen>\))?
        \s*$
    """,
    re.VERBOSE,
)

_SUFFIX_MULTIPLIER: dict[str, float] = {
    "k": 1_000.0,
    "m": 1_000_000.0,
    "b": 1_000_000_000.0,
    "t": 1_000_000_000_000.0,
}


def parse_value_shorthand(text: str) -> float:
    """Parse common shorthand for filter values into a float.

    Examples:
        "100m"   -> 100_000_000
        "1.5b"   -> 1_500_000_000
        "100k"   -> 100_000
        "20%"    -> 0.20
        "-50m"   -> -50_000_000
        "(50m)"  -> -50_000_000   (accounting-style negative)
        "1,234"  -> 1234           (commas tolerated as thousands separators)

    Raises:
        ValueError: if the input cannot be parsed.
    """
    if text is None:
        raise ValueError("value is empty")
    raw = str(text).strip()
    if not raw:
        raise ValueError("value is empty")

    m = _SHORTHAND_RE.match(raw)
    if not m:
        raise ValueError(f"could not parse value: {text!r}")

    paren = m.group("paren") is not None
    closeparen = m.group("closeparen") is not None
    if paren ^ closeparen:
        raise ValueError(f"unbalanced parentheses in value: {text!r}")

    num_str = m.group("num").replace(",", ".")
    # If the value had both a thousands-separator comma AND a decimal point we'd
    # already have errored out (regex only matches one numeric token). Comma in
    # absence of a dot is treated as a decimal separator above. Strip stray
    # commas if any remain.
    try:
        value = float(num_str)
    except ValueError as exc:
        raise ValueError(f"could not parse value: {text!r}") from exc

    suffix = m.group("suffix")
    if suffix:
        suffix_lo = suffix.lower()
        if suffix_lo == "%":
            value = value / 100.0
        else:
            value *= _SUFFIX_MULTIPLIER[suffix_lo]

    sign = m.group("sign")
    if sign == "-" or paren:
        value = -value
    return value


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------

# Sprint 5 SSOT: the IS-side name lists now live in lib.profitability —
# re-exported here under the screener's historical names so existing imports
# keep working. The IS-side metrics themselves (Revenue, GrossProfit, EBITDA,
# EBIT, NetProfit) are no longer derived via these lists; they come from
# lib.profitability.compute_profitability (see build_metrics_table).
from lib.profitability import (  # noqa: E402
    GROSS_PROFIT_PREFERRED_NAMES as GROSS_PROFIT_NAMES,
    NET_PROFIT_EXCLUDE_SUBSTRINGS as NET_PROFIT_EXCLUDES,
    NET_PROFIT_PREFERRED_NAMES as NET_PROFIT_NAMES,
    ProfitResult,
    _group_rows,
    compute_profitability,
)
from lib.data_loader import canonicalize_rows  # noqa: E402
from lib import finratios  # noqa: E402

# LEGACY (pre-Sprint-5): the screener's single-row Revenue pick list. No longer
# used by build_metrics_table (Revenue is the canonical category total now);
# kept only so existing imports don't break.
REVENUE_NAMES: tuple[str, ...] = (
    "Net Revenue",
    "Revenue",
    "Total Revenue",
    "Total revenue",
    "Interest Income",
    "Premiums earned",
)

# Per-metric preference lists for the BS-side "pick-first" metrics. Each tuple
# is searched in order; first non-zero row found per (IdCode, FVYear) wins.
# Names match what lives in the v2 DB after the ingest pipeline ran.
TOTAL_ASSETS_NAMES: tuple[str, ...] = (
    "Total assets",
    "Total Assets",
)
TOTAL_EQUITY_NAMES: tuple[str, ...] = (
    "Total equity",
    "Total Equity",
    "Total equity attributable to owners of parent",
)
CASH_NAMES: tuple[str, ...] = (
    "Cash and Cash Equivalents",
    "Cash and cash equivalents",
    "Cash and Equivalents",
)
DA_NAMES: tuple[str, ...] = (
    "Depreciation and amortisation",
    "Depreciation and Amortization",
    "Depreciation",
    "Amortisation",
)

# BS categories that count toward Total Debt (interest-bearing).
DEBT_CATEGORIES: tuple[str, ...] = (
    "BS_CurrentBorrowings",
    "BS_NonCurrentBorrowings",
    "BS_DebtSecurities",
    "BS_NonCurrentLeasePayable",
    "BS_BankBorrowings",
)


def _pick_value(
    rows: list[tuple[str, float]],
    preferred: tuple[str, ...],
    excludes: tuple[str, ...] = (),
) -> float:
    """Return the first non-zero value from rows whose name matches preferred[i]
    (in order), skipping names containing any exclude substring (case-insensitive).
    Falls back to 0.0 if nothing qualified.
    """
    if not rows:
        return 0.0
    excluded = [(n, v) for n, v in rows if not any(sub in n.lower() for sub in excludes)] if excludes else rows
    # Exact match priority
    for target in preferred:
        for name, value in excluded:
            if name == target and value != 0:
                return float(value)
    # Case-insensitive fallback
    for target in preferred:
        lo = target.lower()
        for name, value in excluded:
            if name.lower() == lo and value != 0:
                return float(value)
    return 0.0


def _sum_category(rows: list[tuple[str, str, float]], categories: tuple[str, ...]) -> float:
    """Sum values across rows whose Category is in `categories`, skipping any
    row whose LineItemENG name contains 'Total' (to avoid double-counting the
    stored grand-total alongside detail line items).
    """
    out = 0.0
    cat_set = set(categories)
    for cat, name, value in rows:
        if cat not in cat_set:
            continue
        if value == 0:
            continue
        if "Total" in name or "TOTAL" in name.upper():
            continue
        out += float(value)
    return out


def build_metrics_table(
    db_path: str, source_table: str = "financial_data"
) -> pd.DataFrame:
    """Return DataFrame with one row per (IdCode, FVYear) and columns for each metric.

    ``source_table`` selects which financial_data-shaped table feeds the build:
    the default production table, or the ``financial_data_individual`` sidecar
    (dual-basis filers' individual statements, built by
    ``scripts/build_individual_basis.py``). Restricted to that allowlist —
    the name is interpolated into SQL.

    Long-form pivot from the source table. The result is indexed by
    ``['IdCode', 'FVYear']`` for fast positional access and includes columns:

      Revenue, GrossProfit, NetProfit, EBITDA, TotalAssets, TotalCash, TotalDebt,
      NetDebt, TotalEquity, GrossMargin, EBITDAMargin, NetMargin, ROE, ROA, ROIC.

    Sprint 5 SSOT: the IS-side metrics (Revenue, GrossProfit, EBITDA, EBIT,
    NetProfit) come from ``lib.profitability.compute_profitability`` fed with
    ``lib.data_loader.canonicalize_rows``-processed rows — the exact read layer
    and arithmetic the Single-Company IS view uses, so the Screener and the IS
    view can never silently diverge. BS-side metrics keep the original raw-row
    extraction (Total Assets/Cash/Debt/Equity were never part of the
    divergence).

    Note: this scans the entire financial_data table once, so it's expensive —
    callers should cache it. The dashboard reads the materialized
    ``metrics_panel`` table instead (built by scripts/build_metrics_panel.py).
    """
    if source_table not in ("financial_data", "financial_data_individual"):
        raise ValueError(f"unsupported source_table: {source_table!r}")
    conn = sqlite3.connect(db_path)
    try:
        # IS rows: mirror lib.data_loader.get_financial_rows' per-company query
        # exactly (DISTINCT, NO zero/NULL filter — a stored zero 'Total' row is
        # load-bearing for _sum_category — and the same intra-company ORDER BY
        # so dedup/merge tie-breaks behave identically).
        is_df = pd.read_sql_query(
            f"""
            SELECT DISTINCT IdCode, FVYear, Section, Category, ItemType,
                            LineItemENG, Value
            FROM {source_table}
            WHERE Section = 'IS'
            ORDER BY IdCode, FVYear, Section, Category, LineItemENG
            """,
            conn,
        )
        bs_df = pd.read_sql_query(
            f"""
            SELECT IdCode, FVYear, Section, Category, LineItemENG, Value
            FROM {source_table}
            WHERE Section IN ('BS_Assets', 'BS_Liabilities', 'BS_Equity')
              AND Value IS NOT NULL
              AND Value != 0
            """,
            conn,
        )
    finally:
        conn.close()

    if is_df.empty and bs_df.empty:
        return pd.DataFrame(
            columns=[
                "Revenue",
                "GrossProfit",
                "NetProfit",
                "EBITDA",
                "TotalAssets",
                "TotalCash",
                "TotalDebt",
                "NetDebt",
                "TotalEquity",
                "GrossMargin",
                "EBITDAMargin",
                "NetMargin",
                "ROE",
                "ROA",
                "ROIC",
            ]
        ).rename_axis(index=["IdCode", "FVYear"])

    # ---- IS side: canonical profitability via the shared read layer ----
    # Universe note: (IdCode, FVYear) keys qualify only when at least one
    # non-zero stored IS row exists — identical to the pre-Sprint-5 builder,
    # which read a zero-filtered frame (keeps the panel's row universe stable).
    profit_by_key: dict[tuple[str, int], ProfitResult] = {}
    is_keys: set[tuple[str, int]] = set()
    if not is_df.empty:
        nz = is_df[is_df["Value"].notna() & (is_df["Value"] != 0)]
        is_keys = {(idc, int(y)) for idc, y in zip(nz["IdCode"], nz["FVYear"])}

        rows_by_company: dict[str, list[dict]] = {}
        for idc, year, section, cat, item_type, name, value in is_df[
            ["IdCode", "FVYear", "Section", "Category", "ItemType", "LineItemENG", "Value"]
        ].itertuples(index=False, name=None):
            rows_by_company.setdefault(idc, []).append({
                "FVYear": int(year),
                "Section": section,
                "Category": cat,
                "ItemType": item_type,
                "LineItemENG": name,
                "Value": value,
            })
        for idc, company_rows in rows_by_company.items():
            # canonicalize_rows dedups on (FVYear, Section, Category, LineItemENG)
            # — per company, exactly like the per-company get_financial_rows call.
            canon = canonicalize_rows(company_rows, "IS")
            grouped = _group_rows(canon)
            for y in {yr for (yr, _cat) in grouped}:
                profit_by_key[(idc, y)] = compute_profitability(grouped, y, idcode=idc)

    # Pre-split BS per Section for cheaper per-group iteration.
    bs_assets_df = bs_df[bs_df["Section"] == "BS_Assets"]
    bs_liab_df = bs_df[bs_df["Section"] == "BS_Liabilities"]
    bs_equity_df = bs_df[bs_df["Section"] == "BS_Equity"]

    # Build per-(IdCode, FVYear) lookup of BS rows by category for the
    # "pick-first" metrics. Group once into Python dicts to avoid per-key
    # dataframe slicing (much faster over 1.9M rows than groupby+apply).
    def _to_grouped_rows(frame: pd.DataFrame) -> dict[tuple[str, int], dict[str, list[tuple[str, float]]]]:
        """Return {(IdCode, FVYear): {Category: [(LineItemENG, Value), ...]}}."""
        out: dict[tuple[str, int], dict[str, list[tuple[str, float]]]] = {}
        for idc, year, cat, name, value in frame[
            ["IdCode", "FVYear", "Category", "LineItemENG", "Value"]
        ].itertuples(index=False, name=None):
            key = (idc, int(year))
            by_cat = out.setdefault(key, {})
            by_cat.setdefault(cat, []).append((name, float(value)))
        return out

    assets_grouped = _to_grouped_rows(bs_assets_df)
    liab_grouped = _to_grouped_rows(bs_liab_df)
    equity_grouped = _to_grouped_rows(bs_equity_df)

    # Universe of (IdCode, FVYear) keys: union of IS + all three BS sections so
    # a company that has only BS data still shows up (Revenue will simply be 0).
    all_keys: set[tuple[str, int]] = (
        is_keys
        | set(assets_grouped.keys())
        | set(liab_grouped.keys())
        | set(equity_grouped.keys())
    )

    # --- Bank top line ------------------------------------------------------
    # The generic IS_Revenue is null for banks (they report interest income),
    # so compute_profitability leaves Revenue=0. That undercounts the sector
    # top line and blows up aggregate margins (NetMargin = ΣNetProfit / ΣRevenue
    # → 238% for the Banks sector). Substitute the bank's reported top line:
    # "Operating income" (Net interest income + net fees + other operating
    # income), from the same builder the Single-Company bank IS uses.
    #
    # Insurers are deliberately NOT handled here: their reportal filings are too
    # sparse/inconsistent for a reliable top line (most carry no premium detail,
    # and build_insurance_is_sections doesn't even tie PBT to the stored net
    # profit for many of them), so deriving a revenue would fabricate negative /
    # garbage figures. Insurer revenue needs the dedicated insurance-statements
    # work (tracked separately); until then their Revenue stays 0.
    fin_revenue: dict[tuple[str, int], float] = {}
    _ft_conn = sqlite3.connect(db_path)
    try:
        bank_idcodes = {
            idc for (idc,) in _ft_conn.execute(
                "SELECT IdCode FROM companies WHERE LatestFormType = 'bank'"
            ).fetchall()
        }
    finally:
        _ft_conn.close()
    if bank_idcodes:
        from lib.income_statement import bank_operating_revenue

        bank_years: dict[str, set[int]] = {}
        for (idc, yr) in all_keys:
            if idc in bank_idcodes:
                bank_years.setdefault(idc, set()).add(int(yr))
        for idc, yrs in bank_years.items():
            try:
                op_rev = bank_operating_revenue(db_path, idc, sorted(yrs))
            except Exception:
                continue  # fall back to Revenue=0 — no worse than before
            for y, v in op_rev.items():
                fin_revenue[(idc, y)] = v

    records: list[dict] = []
    for key in all_keys:
        idc, year = key
        ast_cats = assets_grouped.get(key, {})
        liab_cats = liab_grouped.get(key, {})
        eq_cats = equity_grouped.get(key, {})

        # --- Income Statement metrics — the canonical (IS-view) values ---
        pr = profit_by_key.get(key)
        if pr is not None:
            revenue = float(pr.revenue)
            gross_profit = float(pr.gross_profit)
            ebitda = float(pr.ebitda)
            ebit = float(pr.ebit)
            net_profit = float(pr.net_profit)
        else:  # BS-only key — no IS rows at all for this (company, year).
            revenue = gross_profit = ebitda = ebit = net_profit = 0.0

        # Banks: replace the (null) generic Revenue with the reported top line
        # (Operating income) so margins, AssetTurnover and sector aggregates are
        # meaningful instead of dividing by zero. (See fin_revenue above.)
        if key in fin_revenue:
            revenue = fin_revenue[key]

        # --- Balance Sheet metrics ---
        # Total Assets: stored row in BS_TotalAssets category, "Total assets".
        total_assets = _pick_value(ast_cats.get("BS_TotalAssets", []), TOTAL_ASSETS_NAMES)
        total_equity = _pick_value(eq_cats.get("BS_TotalEquity", []), TOTAL_EQUITY_NAMES)
        total_cash = _pick_value(ast_cats.get("BS_Cash", []), CASH_NAMES)

        # Total Debt: sum of interest-bearing categories. Flatten Category rows across
        # the liabilities lookup.
        debt_rows = []
        for cat in DEBT_CATEGORIES:
            for n, v in liab_cats.get(cat, []):
                debt_rows.append((cat, n, v))
        total_debt = _sum_category(debt_rows, DEBT_CATEGORIES)
        net_debt = total_debt - total_cash

        # --- Margins / returns ---
        def safe_div(num: float, den: float) -> float | None:
            if not den or den == 0:
                return None
            return num / den

        gross_margin = safe_div(gross_profit, revenue)
        ebitda_margin = safe_div(ebitda, revenue)
        net_margin = safe_div(net_profit, revenue)
        # ROE / ROA / ROIC come from the shared SSOT in lib.finratios so the
        # panel and the Single-Company Ratios tab agree on guards + definitions:
        #   - ROE is None when equity <= 0 (sign-blind otherwise)
        #   - ROA is None when total assets <= 0
        #   - ROIC uses NET-DEBT invested capital (Equity + Net Debt), None when <= 0
        roe = finratios.roe(net_profit, total_equity)
        roa = finratios.roa(net_profit, total_assets)
        roic = finratios.roic(ebit, total_equity, net_debt)

        # Leverage: Net Debt / EBITDA. Meaningful only when EBITDA > 0 (a
        # negative EBITDA produces a meaningless or misleading ratio). Returns
        # None when EBITDA <= 0 — filters then naturally exclude the company.
        net_debt_to_ebitda = safe_div(net_debt, ebitda) if (ebitda or 0) > 0 else None
        # Capital intensity proxy: Revenue / Total Assets. Higher = more
        # capital-light (more revenue per GEL of assets). >1.0× ≈ capital-light.
        asset_turnover = safe_div(revenue, total_assets)

        records.append({
            "IdCode": idc,
            "FVYear": year,
            "Revenue": revenue,
            "GrossProfit": gross_profit,
            "NetProfit": net_profit,
            "EBITDA": ebitda,
            "EBIT": ebit,
            "TotalAssets": total_assets,
            "TotalCash": total_cash,
            "TotalDebt": total_debt,
            "NetDebt": net_debt,
            "TotalEquity": total_equity,
            "GrossMargin": gross_margin,
            "EBITDAMargin": ebitda_margin,
            "NetMargin": net_margin,
            "ROE": roe,
            "ROA": roa,
            "ROIC": roic,
            "NetDebtToEBITDA": net_debt_to_ebitda,
            "AssetTurnover": asset_turnover,
        })

    out = pd.DataFrame.from_records(records)
    out = out.set_index(["IdCode", "FVYear"]).sort_index()

    # Attach per-year growth / CAGR columns. compute_growth_columns returns a
    # frame on the same (IdCode, FVYear) index, so this joins 1:1 — each row
    # carries the growth ending in ITS year.
    growth = compute_growth_columns(out)
    if not growth.empty:
        out = out.join(growth, how="left")
    return out


def list_screenable_line_items(db_path: str) -> list[str]:
    """Return a sorted list of all distinct LineItemENG values for free-form
    metric input (so users can pick any line item, not just defaults).
    """
    conn = sqlite3.connect(db_path)
    try:
        return [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT LineItemENG FROM financial_data "
                "WHERE LineItemENG IS NOT NULL ORDER BY LineItemENG"
            )
        ]
    finally:
        conn.close()


def raw_line_item_by_year(db_path: str, line_item: str,
                          table: str = "financial_data") -> pd.DataFrame:
    """Return ``(IdCode, FVYear) -> value`` for a free-form LineItemENG lookup.

    Used by the screener UI when the user types a raw line item name that isn't
    one of the pre-built metric columns. Sums duplicate rows within a
    (IdCode, FVYear) bucket (rare but possible across Section/Category combos).
    ``table`` follows the screener's statement basis (allowlisted).
    """
    if table not in ("financial_data", "financial_data_individual"):
        raise ValueError(f"unsupported financial table: {table!r}")
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            f"""
            SELECT IdCode, FVYear, SUM(Value) AS Value
            FROM {table}
            WHERE LineItemENG = ?
              AND Value IS NOT NULL
            GROUP BY IdCode, FVYear
            """,
            conn,
            params=(line_item,),
        )
    finally:
        conn.close()
    if df.empty:
        return df
    df["FVYear"] = df["FVYear"].astype(int)
    return df.set_index(["IdCode", "FVYear"]).sort_index()


# ---------------------------------------------------------------------------
# Filter evaluation
# ---------------------------------------------------------------------------

OPERATORS: tuple[str, ...] = (">", ">=", "<", "<=", "=", "!=", "between")


def apply_operator(series: pd.Series, op: str, value: float | tuple[float, float]) -> pd.Series:
    """Apply a comparison operator to a numeric series, returning a boolean mask.

    For "between", `value` must be a (low, high) tuple (inclusive).
    NaN / None values always return False (matching SQL semantics).
    """
    s = pd.to_numeric(series, errors="coerce")
    if op == ">":
        return s > value  # type: ignore[operator]
    if op == ">=":
        return s >= value  # type: ignore[operator]
    if op == "<":
        return s < value  # type: ignore[operator]
    if op == "<=":
        return s <= value  # type: ignore[operator]
    if op == "=":
        return s == value  # type: ignore[operator]
    if op == "!=":
        return s != value  # type: ignore[operator]
    if op == "between":
        if not isinstance(value, tuple) or len(value) != 2:
            raise ValueError("'between' operator requires a (low, high) tuple")
        lo, hi = value
        return s.between(lo, hi, inclusive="both")
    raise ValueError(f"unknown operator: {op}")
