import pandas as pd
from lib import finratios
from lib.cash_flow import cf_activity_totals
from lib.data_loader import get_dividends, get_financial_rows
from lib.income_statement import build_is_sections
from lib.balance_sheet import build_bs_sections

# Canonical BS inventory balances. The reportal taxonomy stores the inventory
# balance under EITHER 'Current Inventory' or 'Inventories' (both ItemType=TOTAL);
# the other inventory line items ('- inventories', 'Opening/Closing inventories',
# 'finished goods', …) are COMPONENT breakdowns that must NOT be summed in. Using
# only 'Current Inventory' (the old behaviour) missed ~half the universe — only
# ~1,596 of ~9k companies use that spelling vs ~3,949 for 'Inventories'.
INVENTORY_NAMES: tuple[str, ...] = ("Current Inventory", "Inventories")


def _section_total_by_label(sections: list[dict], label: str, year: int) -> float:
    """Return the total for a given section label at a given year, or 0 if missing."""
    for s in sections:
        if s["label"] == label:
            return s["total"].get(year, 0) or 0
    return 0


def _lookup_item(rows: list[dict], year: int, name: str) -> float:
    """Return the value of a specific LineItemENG for a given year, summed across matching rows."""
    target = name.lower().strip()
    total = 0.0
    for r in rows:
        if r["FVYear"] != year:
            continue
        if (r["LineItemENG"] or "").lower().strip() == target:
            total += r["Value"] or 0
    return total


def _lookup_first_of(rows: list[dict], year: int, names: tuple[str, ...]) -> float:
    """Return the value for the FIRST name in ``names`` that has a non-zero row
    in ``year`` — first-match-wins, NOT a sum across the name set.

    This matters for inventory: a company can carry both 'Current Inventory'
    and 'Inventories' as TOTAL rows in the same year (~331 such keys); summing
    them would double-count the balance. We prefer the first spelling present.
    Each individual name is still summed across its own matching rows (handles
    rare intra-name duplicates), matching ``_lookup_item`` semantics.
    """
    for nm in names:
        v = _lookup_item(rows, year, nm)
        if v:
            return v
    return 0.0


def _section_total_by_label_prefix(sections: list[dict], prefix: str, year: int) -> float:
    """Return the total for the first section whose label starts with `prefix`.

    Used to find sections that may have an ' (adj.)' suffix when IFRS 16
    adjustment is applied.
    """
    for s in sections:
        if s["label"].startswith(prefix):
            return s["total"].get(year, 0) or 0
    return 0


def _find_opex_section(sections: list[dict]) -> dict | None:
    """Locate the Operating Expenses section, with or without the '(adj.)' suffix."""
    for s in sections:
        if s["label"].startswith("Total Operating Expenses"):
            return s
    return None


def _rental_expense_for_year(is_sections: list[dict], year: int) -> float:
    """Return the absolute magnitude of 'Rental expenses' from the OpEx detail.

    When the IFRS 16 adjustment is applied, the implied lease cost (-X) is baked
    INTO this row, so its magnitude grows by X. That growth exactly offsets the
    -X reduction in EBITDA, keeping EBITDAR (= EBITDA + |Rental expenses|) stable
    across the adjustment toggle.
    """
    opex = _find_opex_section(is_sections)
    if opex is None:
        return 0.0
    for name, vals_by_year in opex.get("detail", []):
        if name == "Rental expenses":
            return abs(vals_by_year.get(year, 0) or 0)
    return 0.0


def _ratio_set_for_year(
    is_sections: list[dict],
    bs_sections: list[dict],
    bs_rows: list[dict],
    year: int,
    cf: dict[str, dict[int, float]] | None = None,
    div_info: dict | None = None,
) -> dict[str, str]:
    """Compute all ratios for one year using the section subtotals."""
    revenue = _section_total_by_label_prefix(is_sections, "Total Revenue", year)
    cogs = _section_total_by_label_prefix(is_sections, "Total COGS", year)
    gross_profit = _section_total_by_label_prefix(is_sections, "Gross Profit", year)
    opex = _section_total_by_label_prefix(is_sections, "Total Operating Expenses", year)
    ebitda = _section_total_by_label_prefix(is_sections, "EBITDA", year)
    ebit = _section_total_by_label_prefix(is_sections, "EBIT / Operating Income", year)
    net_profit = _section_total_by_label_prefix(is_sections, "Net Profit / (Loss)", year)
    rent = _rental_expense_for_year(is_sections, year)
    ebitdar = ebitda + rent

    total_assets = _section_total_by_label(bs_sections, "TOTAL ASSETS", year)
    cur_assets = _section_total_by_label(bs_sections, "Total Current Assets", year)
    cur_liab = _section_total_by_label(bs_sections, "Total Current Liabilities", year)
    total_equity = _section_total_by_label(bs_sections, "Total Equity", year)
    total_debt = _section_total_by_label(bs_sections, "Total Debt", year)
    cash = _section_total_by_label(bs_sections, "Cash & Equivalents", year)
    net_debt = _section_total_by_label(bs_sections, "Net Debt", year)

    # Working capital line items — still looked up directly from raw rows.
    # Inventory accepts BOTH canonical spellings ('Current Inventory' /
    # 'Inventories'); first-match-wins so a company carrying both as TOTAL rows
    # isn't double-counted.
    inventory = _lookup_first_of(bs_rows, year, INVENTORY_NAMES)
    receivables = _lookup_item(bs_rows, year, "Trade Receivables")
    payables = _lookup_item(bs_rows, year, "Trade payables")

    # --- Working-capital levels ------------------------------------------------
    # Two complementary views, both reported:
    #   * Net working capital = the WHOLE current block (cash and short-term debt
    #     included) — the liquidity view, and the one the current/quick ratios
    #     are built on.
    #   * Trade (operating) working capital = only the three lines the
    #     DIO/DSO/DPO days are built from, so it moves with operations rather
    #     than with financing/cash swings — the CCC-consistent view.
    # BS liabilities are stored POSITIVE (see build_bs_sections), so both are
    # plain subtractions. A filing with no current/non-current split leaves both
    # subtotals at 0; flag that as unavailable rather than reporting NWC = 0.
    has_current_split = bool(cur_assets or cur_liab)
    nwc = cur_assets - cur_liab
    trade_wc = inventory + receivables - payables
    has_trade_wc = bool(inventory or receivables or payables)

    # Year-on-year movement in trade working capital (+ = working capital
    # absorbed cash). ``bs_rows`` only carries the SELECTED years, so when
    # ``year - 1`` wasn't selected all three prior lookups return 0 and the delta
    # would read as a full release of working capital — require the prior year to
    # actually be loaded before reporting it.
    prev_trade_wc = (
        _lookup_first_of(bs_rows, year - 1, INVENTORY_NAMES)
        + _lookup_item(bs_rows, year - 1, "Trade Receivables")
        - _lookup_item(bs_rows, year - 1, "Trade payables")
    )
    prev_year_loaded = any(r["FVYear"] == year - 1 for r in bs_rows)
    delta_trade_wc = trade_wc - prev_trade_wc
    has_delta_trade_wc = prev_year_loaded and (has_trade_wc or bool(prev_trade_wc))

    def pct(num, denom):
        if not denom:
            return "N/A"
        return f"{(num / denom) * 100:.1f}%"

    def money(val, available: bool = True):
        """Money cell in GEL thousands. ``available=False`` -> 'N/A'.

        Unlike the ``x if x else 'N/A'`` pattern used for the leverage money
        rows, this keeps a genuine zero/negative balance visible — a negative
        NWC or a working-capital release is information, not missing data.
        """
        if not available:
            return "N/A"
        return f"{val / 1000:,.0f}"

    def fmt_pct_val(val):
        """Format a pre-computed decimal ratio (e.g. 0.23) as '23.0%'; ``None`` -> 'N/A'."""
        if val is None:
            return "N/A"
        return f"{val * 100:.1f}%"

    def ratio(num, denom):
        if not denom:
            return "N/A"
        return f"{num / denom:.2f}x"

    inv_turn = (abs(cogs) / inventory) if inventory else 0
    dio = (365 / inv_turn) if inv_turn else 0
    rec_turn = (revenue / receivables) if receivables else 0
    dso = (365 / rec_turn) if rec_turn else 0
    pay_turn = (abs(cogs) / payables) if payables else 0
    dpo = (365 / pay_turn) if pay_turn else 0
    ccc = dio + dso - dpo

    # ROE / ROA / ROIC via the shared SSOT (lib.finratios) so this tab agrees
    # with the Screener / metrics_panel on guards + definitions:
    #   - ROE is None when equity <= 0 (a loss on negative equity is a FALSE
    #     positive return otherwise — sign-blindness)
    #   - ROA is None when total assets <= 0
    #   - ROIC uses NET-DEBT invested capital (Equity + Net Debt), None when <= 0
    roe_val = finratios.roe(net_profit, total_equity)
    roa_val = finratios.roa(net_profit, total_assets)
    roic_val = finratios.roic(ebit, total_equity, net_debt)

    # --- Cash flow & dividends -------------------------------------------------
    # The source filings carry only the summary net-activity CF figures (no capex
    # line), so FCF = OCF + net investing CF — the same capex proxy the Cash Flow
    # statement shows. "Cash Conversion" here is OCF / EBITDA (how much of EBITDA
    # turns into operating cash), distinct from the working-capital Cash
    # Conversion Cycle below. Dividends come from the SOCE exports
    # (equity_movements): a year covered by a SOCE filing but with no dividend
    # row means "declared zero" and shows as 0 rather than N/A.
    ocf = (cf or {}).get("operating", {}).get(year, 0) or 0
    inv_cf = (cf or {}).get("investing", {}).get(year, 0) or 0
    fcf = ocf + inv_cf
    div_by_year = (div_info or {}).get("dividends", {})
    div_covered = (div_info or {}).get("covered", set())
    dividend = abs(div_by_year.get(year, 0.0)) if year in div_covered else None

    return {
        "Gross Margin": pct(gross_profit, revenue),
        "EBITDA Margin": pct(ebitda, revenue),
        "EBITDAR": f"{ebitdar/1000:,.0f}" if ebitdar else "N/A",
        "EBITDAR Margin": pct(ebitdar, revenue),
        "EBIT Margin": pct(ebit, revenue),
        "Net Profit Margin": pct(net_profit, revenue),
        "Operating Expense % of Sales": pct(abs(opex), revenue),
        "Return on Assets (ROA)": fmt_pct_val(roa_val),
        "Return on Equity (ROE)": fmt_pct_val(roe_val),
        "ROIC [EBIT / Invested Capital]": fmt_pct_val(roic_val),
        "Debt-to-Assets": pct(total_debt, total_assets),
        "Debt-to-Equity": ratio(total_debt, total_equity),
        # Debt-to-EBITDA is meaningful only when EBITDA > 0 — a non-positive
        # EBITDA yields a misleading/negative leverage multiple. Guarded to
        # agree with the Screener's Net Debt / EBITDA guard.
        "Debt-to-EBITDA": ratio(total_debt, ebitda) if ebitda > 0 else "N/A",
        "Equity-to-Assets": pct(total_equity, total_assets),
        "Net Debt": f"{net_debt/1000:,.0f}" if net_debt else "N/A",
        "Cash & Equivalents": f"{cash/1000:,.0f}" if cash else "N/A",
        "Total Debt": f"{total_debt/1000:,.0f}" if total_debt else "N/A",
        # Liquidity — guarded on current liabilities > 0 (a zero base means the
        # filing carries no current/non-current split; a negative one is bad data
        # and would flip the ratio's sign).
        "Current Ratio": ratio(cur_assets, cur_liab) if cur_liab > 0 else "N/A",
        "Quick Ratio": (
            ratio(cur_assets - inventory, cur_liab) if cur_liab > 0 else "N/A"
        ),
        "Cash Ratio": ratio(cash, cur_liab) if cur_liab > 0 else "N/A",
        "Total Current Assets": money(cur_assets, bool(cur_assets)),
        "Total Current Liabilities": money(cur_liab, bool(cur_liab)),
        "Inventory": money(inventory, bool(inventory)),
        "Trade Receivables": money(receivables, bool(receivables)),
        "Trade Payables": money(payables, bool(payables)),
        "Net Working Capital": money(nwc, has_current_split),
        "Net Working Capital % of Revenue": (
            pct(nwc, revenue) if (has_current_split and revenue > 0) else "N/A"
        ),
        "Trade Working Capital": money(trade_wc, has_trade_wc),
        "Trade Working Capital % of Revenue": (
            pct(trade_wc, revenue) if (has_trade_wc and revenue > 0) else "N/A"
        ),
        "Change in Trade Working Capital": money(delta_trade_wc, has_delta_trade_wc),
        "Inventory Turnover": f"{inv_turn:.2f}x" if inv_turn else "N/A",
        "Days Inventory Outstanding (DIO)": f"{dio:.1f}" if dio else "N/A",
        "Receivables Turnover": f"{rec_turn:.2f}x" if rec_turn else "N/A",
        "Days Sales Outstanding (DSO)": f"{dso:.1f}" if dso else "N/A",
        "Payables Turnover": f"{pay_turn:.2f}x" if pay_turn else "N/A",
        "Days Payable Outstanding (DPO)": f"{dpo:.1f}" if dpo else "N/A",
        "Cash Conversion Cycle": f"{ccc:.1f} days" if ccc else "N/A",
        "Asset Turnover": ratio(revenue, total_assets),
        "Operating Cash Flow": f"{ocf/1000:,.0f}" if ocf else "N/A",
        "Free Cash Flow (OCF − Capex proxy)": f"{fcf/1000:,.0f}" if ocf else "N/A",
        "Cash Conversion (OCF / EBITDA)": pct(ocf, ebitda) if (ocf and ebitda > 0) else "N/A",
        "Dividends Declared": (
            f"{dividend/1000:,.0f}" if dividend is not None else "N/A"
        ),
        "Dividend Payout Ratio": (
            pct(dividend, net_profit)
            if (dividend is not None and net_profit > 0)
            else "N/A"
        ),
    }


# Unit / definition per ratio, shown as a hover tooltip on the metric name in the
# grouped Ratios table (lib.ui.render_grouped_ratios). Money cells are bare
# numbers in GEL thousands — the table-level caption states the convention, and
# these tooltips carry the per-metric detail. Kept in sync with RATIO_ORDER by
# tests/test_ratios_groups.py.
RATIO_UNITS: dict[str, str] = {
    "Gross Margin": "% of revenue",
    "EBITDA Margin": "% of revenue",
    "EBITDAR": "GEL thousands — EBITDA + rental expense",
    "EBITDAR Margin": "% of revenue",
    "EBIT Margin": "% of revenue",
    "Net Profit Margin": "% of revenue",
    "Operating Expense % of Sales": "% of revenue",
    "Return on Assets (ROA)": "% — net profit / total assets",
    "Return on Equity (ROE)": "% — net profit / total equity",
    "ROIC [EBIT / Invested Capital]": "% — EBIT / (equity + net debt)",
    "Debt-to-Assets": "% of total assets",
    "Debt-to-Equity": "× — total debt / total equity",
    "Debt-to-EBITDA": "× — total debt / EBITDA",
    "Equity-to-Assets": "% of total assets",
    "Net Debt": "GEL thousands — total debt − cash",
    "Cash & Equivalents": "GEL thousands",
    "Total Debt": "GEL thousands",
    "Current Ratio": "× — current assets / current liabilities",
    "Quick Ratio": "× — (current assets − inventory) / current liabilities",
    "Cash Ratio": "× — cash & equivalents / current liabilities",
    "Total Current Assets": "GEL thousands",
    "Total Current Liabilities": "GEL thousands",
    "Inventory": "GEL thousands — closing balance",
    "Trade Receivables": "GEL thousands — closing balance",
    "Trade Payables": "GEL thousands — closing balance",
    "Net Working Capital": "GEL thousands — current assets − current liabilities",
    "Net Working Capital % of Revenue": "% of revenue",
    "Trade Working Capital": (
        "GEL thousands — inventory + trade receivables − trade payables"
    ),
    "Trade Working Capital % of Revenue": "% of revenue",
    "Change in Trade Working Capital": (
        "GEL thousands — YoY movement; positive = working capital absorbed cash"
    ),
    "Inventory Turnover": "× per year — |COGS| / inventory",
    "Days Inventory Outstanding (DIO)": "days",
    "Receivables Turnover": "× per year — revenue / trade receivables",
    "Days Sales Outstanding (DSO)": "days",
    "Payables Turnover": "× per year — |COGS| / trade payables",
    "Days Payable Outstanding (DPO)": "days",
    "Cash Conversion Cycle": "days — DIO + DSO − DPO",
    "Asset Turnover": "× — revenue / total assets",
    "Operating Cash Flow": "GEL thousands — net cash from operations",
    "Free Cash Flow (OCF − Capex proxy)": "GEL thousands — OCF − net investing outflow",
    "Cash Conversion (OCF / EBITDA)": "% of EBITDA converted to operating cash",
    "Dividends Declared": "GEL thousands — per SOCE filings",
    "Dividend Payout Ratio": "% of net profit",
}


RATIO_ORDER = [
    "Gross Margin",
    "EBITDA Margin",
    "EBITDAR",
    "EBITDAR Margin",
    "EBIT Margin",
    "Net Profit Margin",
    "Operating Expense % of Sales",
    "Return on Assets (ROA)",
    "Return on Equity (ROE)",
    "ROIC [EBIT / Invested Capital]",
    "Debt-to-Assets",
    "Debt-to-Equity",
    "Debt-to-EBITDA",
    "Equity-to-Assets",
    "Net Debt",
    "Cash & Equivalents",
    "Total Debt",
    "Current Ratio",
    "Quick Ratio",
    "Cash Ratio",
    "Total Current Assets",
    "Total Current Liabilities",
    "Inventory",
    "Trade Receivables",
    "Trade Payables",
    "Net Working Capital",
    "Net Working Capital % of Revenue",
    "Trade Working Capital",
    "Trade Working Capital % of Revenue",
    "Change in Trade Working Capital",
    "Inventory Turnover",
    "Days Inventory Outstanding (DIO)",
    "Receivables Turnover",
    "Days Sales Outstanding (DSO)",
    "Payables Turnover",
    "Days Payable Outstanding (DPO)",
    "Cash Conversion Cycle",
    "Asset Turnover",
    "Operating Cash Flow",
    "Free Cash Flow (OCF − Capex proxy)",
    "Cash Conversion (OCF / EBITDA)",
    "Dividends Declared",
    "Dividend Payout Ratio",
]


# Ratio categories for the grouped display (mirrors the IS/BS section layout:
# a bold category header, then its ratios indented beneath). Ordered; every label
# is one of RATIO_ORDER. Kept in sync with RATIO_ORDER by
# tests/test_ratios_groups.py so a newly-added ratio can't silently fall out of
# the grouped view.
RATIO_GROUPS: list[tuple[str, list[str]]] = [
    ("Margins", [
        "Gross Margin",
        "EBITDA Margin",
        "EBITDAR",
        "EBITDAR Margin",
        "EBIT Margin",
        "Net Profit Margin",
        "Operating Expense % of Sales",
    ]),
    ("Returns", [
        "Return on Assets (ROA)",
        "Return on Equity (ROE)",
        "ROIC [EBIT / Invested Capital]",
    ]),
    ("Leverage", [
        "Debt-to-Assets",
        "Debt-to-Equity",
        "Debt-to-EBITDA",
        "Equity-to-Assets",
        "Net Debt",
        "Cash & Equivalents",
        "Total Debt",
    ]),
    ("Liquidity & working capital", [
        "Current Ratio",
        "Quick Ratio",
        "Cash Ratio",
        "Total Current Assets",
        "Total Current Liabilities",
        "Net Working Capital",
        "Net Working Capital % of Revenue",
        "Inventory",
        "Trade Receivables",
        "Trade Payables",
        "Trade Working Capital",
        "Trade Working Capital % of Revenue",
        "Change in Trade Working Capital",
    ]),
    ("Turnover & efficiency", [
        "Asset Turnover",
        "Inventory Turnover",
        "Days Inventory Outstanding (DIO)",
        "Receivables Turnover",
        "Days Sales Outstanding (DSO)",
        "Payables Turnover",
        "Days Payable Outstanding (DPO)",
        "Cash Conversion Cycle",
    ]),
    ("Cash flow & dividends", [
        "Operating Cash Flow",
        "Free Cash Flow (OCF − Capex proxy)",
        "Cash Conversion (OCF / EBITDA)",
        "Dividends Declared",
        "Dividend Payout Ratio",
    ]),
]


def build_ratios_table(
    db_path: str,
    idcode: str,
    years: list[int],
    is_sections: list[dict] | None = None,
    table: str = "financial_data",
) -> pd.DataFrame:
    """Build multi-year ratios DataFrame.

    Pulls subtotals from `build_is_sections` and `build_bs_sections` so the
    ratios stay consistent with what the statement tabs render. Returns
    pre-formatted strings (percentages, ratios, currency).

    If `is_sections` is provided (e.g. an IFRS 16-adjusted version), it is used
    instead of rebuilding from the DB -- this lets callers compute ratios on top
    of an adjusted income statement.
    """
    if not years:
        return pd.DataFrame(columns=["Ratio"])

    if is_sections is None:
        is_sections = build_is_sections(db_path, idcode, years, table=table)
    bs_sections = build_bs_sections(db_path, idcode, years, table=table)
    bs_rows = get_financial_rows(db_path, idcode, years, section_prefix="BS_", table=table)
    cf = cf_activity_totals(db_path, idcode, years, table=table)
    div_info = get_dividends(db_path, idcode)

    per_year_ratios: dict = {}
    for y in years:
        per_year_ratios[y] = _ratio_set_for_year(
            is_sections, bs_sections, bs_rows, y, cf=cf, div_info=div_info
        )

    rows = []
    for label in RATIO_ORDER:
        rec = {"Ratio": label}
        for y in years:
            rec[y] = per_year_ratios[y].get(label, "N/A")
        rows.append(rec)

    df = pd.DataFrame(rows)
    return df[["Ratio"] + years]
