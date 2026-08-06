"""Bank-specific Income Statement layout + KPI ratios.

The bank IS *section builder* (``build_bank_is_sections``) historically lives in
``lib.income_statement`` (existing tests import it from there). It is re-exported
here so callers can treat ``lib.statements_bank`` as the single home of all
bank-statement logic, matching ``lib.statements_insurance``.

What is genuinely new here is the **bank KPI block**: NIM, cost of funds,
cost/income, cost of risk, and ROAA/ROAE — the metrics a generic Gross-Margin /
EBITDA-Margin ratio table can't express for a bank.

All ratio functions are pure: they take ``db_path / idcode / years`` (read-only
DB access via ``get_financial_rows``) and return plain dicts. A ratio is OMITTED
(not shown as a wrong/zero number) when the data needed to compute it is missing.
"""
from __future__ import annotations

from collections import defaultdict

from lib.data_loader import get_financial_rows
from lib.profitability import _group_rows, _select_stored_row, PBT_PREFERRED_NAMES

# Re-export so `from lib.statements_bank import build_bank_is_sections` works.
from lib.income_statement import (  # noqa: F401  (re-exported)
    build_bank_is_sections,
    _category_total,
    _collect_detail_items,
    _partition_bank_opex,
    _sum_detail_totals,
    _sum_year_dicts,
    _BANK_NP_PREFERRED,
    _BANK_NP_EXCLUDES,
)

# ---------------------------------------------------------------------------
# Sector detection
# ---------------------------------------------------------------------------
# Data-driven: matched against companies.Sector (mirrored on company_search).
# Confirmed labels in the production DB: "Banks". MFO/leasing companies file on
# the bank form too (LatestFormType='bank') but are NOT in the "Banks" sector —
# the view layer treats either signal as "use the bank layout", which is the
# correct behaviour (they share the interest-driven IS shape).
BANK_SECTORS = frozenset({"Banks"})


# ---------------------------------------------------------------------------
# BS helpers for ratio denominators
# ---------------------------------------------------------------------------

def _bs_category_by_year(grouped_bs: dict, years: list[int], category: str) -> dict:
    """Return {year: stored-total-or-sum} for a BS category."""
    return _category_total(grouped_bs, years, category)


def _avg(curr: float | None, prev: float | None) -> float | None:
    """Average of two period-end balances. Falls back to the single available
    value when only one period is present (e.g. the first year in the dataset)."""
    if curr is None and prev is None:
        return None
    if prev is None:
        return curr
    if curr is None:
        return prev
    return (curr + prev) / 2.0


def _safe_div(numer: float | None, denom: float | None) -> float | None:
    if numer is None or denom is None or denom == 0:
        return None
    return numer / denom


def compute_bank_ratios(db_path: str, idcode: str, years: list[int],
                        table: str = "financial_data") -> list[dict]:
    """Compute bank KPIs per year.

    Returns a list of row dicts shaped for a ratios table:
        {"Ratio": <label>, year1: <value|None>, year2: ..., "_fmt": "pct"|"num"}

    ``_fmt`` tells the caller how to format ("pct" => ×100 + "%"). ``None`` cells
    render as "n/a". A whole ratio row is dropped if it is ``None`` in every year.

    Definitions (denominators use 2-period averages where a balance is involved):
      - NIM                = Net interest income / avg interest-earning assets
                             (earning assets = customer loans + due-from-banks +
                              investment securities)
      - Cost of funds      = |Interest expense| / avg interest-bearing liabilities
                             (= customer deposits + bank borrowings + debt
                              securities + non-current borrowings)
      - Cost/income ratio  = Operating expenses (ex-provisions) / Operating income
      - Cost of risk       = |Loan-loss provisions| / avg gross customer loans
      - ROAA               = Net profit / avg total assets
      - ROAE               = Net profit / avg total equity
      - Net interest spread= NIM proxy already covers margin; spread omitted
                             (asset/liability yields need rate disclosures we lack)
    """
    if not years:
        return []
    years = sorted(years)

    is_rows = get_financial_rows(db_path, idcode, years, section_prefix="IS", table=table)
    bs_rows = get_financial_rows(db_path, idcode, years, section_prefix="BS_", table=table)
    g_is = _group_rows(is_rows)
    g_bs = _group_rows(bs_rows)

    # --- IS-side aggregates per year (reuse the bank IS partition logic) ---
    ii = _category_total(g_is, years, "IS_InterestIncome")
    ie = _category_total(g_is, years, "IS_InterestExpense")
    nii = _sum_year_dicts(ii, ie)

    opex_all = _collect_detail_items(g_is, years, "IS_OpEx")
    loan_loss_items, _fee_exp_items, opex_rest_items = _partition_bank_opex(opex_all)
    da_items = _collect_detail_items(g_is, years, "IS_DA")
    provisions = _sum_detail_totals(loan_loss_items, years)          # negative
    opex_ex_prov = _sum_detail_totals(opex_rest_items + da_items, years)  # negative

    fi = _category_total(g_is, years, "IS_FeeIncome")
    fee_exp = _sum_detail_totals(_fee_exp_items, years)
    net_fee = _sum_year_dicts(fi, fee_exp)
    other_inc = _category_total(g_is, years, "IS_OtherIncome")
    nii_after_prov = _sum_year_dicts(nii, provisions)
    operating_income = _sum_year_dicts(nii_after_prov, net_fee, other_inc)

    # Net profit (canonical bank picker, PBT+Tax fallback)
    tax = _category_total(g_is, years, "IS_Tax")
    _pbt_excludes = ("comprehensive", "attributable", "non-controlling",
                     "owners", "net assets", "discontinued", "held for sale")
    np_by_year: dict = {}
    for y in years:
        np_rows = [(t[0], t[1]) for t in g_is.get((y, "IS_NetProfit"), [])]
        picked = _select_stored_row(np_rows, _BANK_NP_PREFERRED, _BANK_NP_EXCLUDES)
        if picked is None:
            pbt = _select_stored_row(np_rows, PBT_PREFERRED_NAMES, _pbt_excludes)
            picked = (pbt or 0) + tax.get(y, 0)
        np_by_year[y] = picked

    # --- BS-side balances per year ---
    cust_loans = _bs_category_by_year(g_bs, years, "BS_CustomerLoans")
    bank_dep_asset = _bs_category_by_year(g_bs, years, "BS_BankDeposits")
    investments = _bs_category_by_year(g_bs, years, "BS_Investments")
    cust_deposits = _bs_category_by_year(g_bs, years, "BS_CustomerDeposits")
    bank_borrow = _bs_category_by_year(g_bs, years, "BS_BankBorrowings")
    debt_sec = _bs_category_by_year(g_bs, years, "BS_DebtSecurities")
    nc_borrow = _bs_category_by_year(g_bs, years, "BS_NonCurrentBorrowings")
    total_assets = _bs_category_by_year(g_bs, years, "BS_TotalAssets")
    total_equity = _bs_category_by_year(g_bs, years, "BS_TotalEquity")

    def _sum_balances(*dicts) -> dict:
        out: dict = {}
        for y in years:
            vals = [d.get(y) for d in dicts]
            present = [v for v in vals if v is not None]
            out[y] = sum(present) if present else None
        return out

    earning_assets = _sum_balances(cust_loans, bank_dep_asset, investments)
    funding = _sum_balances(cust_deposits, bank_borrow, debt_sec, nc_borrow)

    def _avg_year(balance: dict, y: int) -> float | None:
        prev = balance.get(y - 1) if (y - 1) in balance else None
        return _avg(balance.get(y), prev)

    rows: list[dict] = []

    def _emit(label: str, fmt: str, per_year: dict):
        if all(v is None for v in per_year.values()):
            return
        rec = {"Ratio": label, "_fmt": fmt}
        for y in years:
            rec[y] = per_year.get(y)
        rows.append(rec)

    nim = {y: _safe_div(nii.get(y), _avg_year(earning_assets, y)) for y in years}
    cof = {y: _safe_div(-(ie.get(y) or 0), _avg_year(funding, y)) for y in years}
    cir = {y: _safe_div(-(opex_ex_prov.get(y) or 0), operating_income.get(y)) for y in years}
    cor = {y: _safe_div(-(provisions.get(y) or 0), _avg_year(cust_loans, y)) for y in years}
    roaa = {y: _safe_div(np_by_year.get(y), _avg_year(total_assets, y)) for y in years}
    roae = {y: _safe_div(np_by_year.get(y), _avg_year(total_equity, y)) for y in years}
    fee_share = {y: _safe_div(net_fee.get(y), operating_income.get(y)) for y in years}

    _emit("Net Interest Margin (NIM)", "pct", nim)
    _emit("Cost of Funds", "pct", cof)
    _emit("Cost / Income Ratio", "pct", cir)
    _emit("Cost of Risk", "pct", cor)
    _emit("Net Fee Income / Operating Income", "pct", fee_share)
    _emit("Return on Avg Assets (ROAA)", "pct", roaa)
    _emit("Return on Avg Equity (ROAE)", "pct", roae)

    return rows


# ---------------------------------------------------------------------------
# Bank Balance Sheet framework
# ---------------------------------------------------------------------------
#
# Banks present an *unclassified* balance sheet (no current / non-current
# split) ordered roughly by liquidity. reportal.ge stores each face-of-BS line
# under a stable ``BS_*`` Category nested inside Section ``BS_Assets`` /
# ``BS_Liabilities`` / ``BS_Equity``. We map those categories to the canonical
# Lion Finance Group / Bank of Georgia layout:
#
#   Assets       Cash & balances with NBG · Due from banks · Loans to customers
#                (net) · Investment securities · Investment property · PP&E ·
#                Goodwill & intangibles · Derivative assets · Deferred tax asset
#                · Inventory of repossessed collateral · Other assets
#   Liabilities  Due to banks / borrowings · Customer deposits · Debt securities
#                issued · Subordinated debt · Derivative liabilities · Lease
#                liabilities · Provisions · Current / deferred tax · Other
#   Equity       Share capital · Share premium · Treasury shares · Retained
#                earnings · Reserves · Non-controlling interest
#
# The three grand totals (Total Assets / Total Liabilities / Total Equity) come
# from the authoritative stored ``BS_Total*`` rows — they tie exactly
# (Assets == Liabilities + Equity) for the real banks in the DB. Detail lines
# are one representative figure per category (the IFRS face line), preferring an
# ItemType='TOTAL' row and falling back to the sum of COMPONENT rows when no
# total exists. Categories absent for a given bank are simply omitted, so the
# layout adapts to whatever a bank actually reports.

# Friendly display label + ordering for each BS category. Order follows a
# standard bank balance sheet (most-liquid assets first; deposits-led funding
# first on the liability side; contributed capital before reserves on equity).
_BANK_BS_ASSET_CATEGORIES: list[tuple[str, str]] = [
    ("BS_Cash", "Cash & balances with central bank"),
    ("BS_BankDeposits", "Due from banks"),
    ("BS_CustomerLoans", "Loans & advances to customers (net)"),
    ("BS_Investments", "Investment securities"),
    ("BS_InvestmentProperty", "Investment property"),
    ("BS_PPE", "Property, plant & equipment"),
    ("BS_Goodwill", "Goodwill"),
    ("BS_Intangibles", "Intangible assets"),
    ("BS_DerivativeAssets", "Derivative financial assets"),
    ("BS_DeferredTaxAsset", "Deferred income tax asset"),
    ("BS_Inventory", "Inventory of repossessed collateral"),
    ("BS_OtherCurrentAssets", "Other assets"),
]

_BANK_BS_LIABILITY_CATEGORIES: list[tuple[str, str]] = [
    ("BS_BankBorrowings", "Due to banks"),
    ("BS_NonCurrentBorrowings", "Borrowings"),
    ("BS_CustomerDeposits", "Customer deposits"),
    ("BS_DebtSecurities", "Debt securities issued"),
    ("BS_DerivativeLiabilities", "Derivative financial liabilities"),
    ("BS_NonCurrentLeasePayable", "Lease liabilities"),
    ("BS_Provisions", "Provisions"),
    ("BS_CurrentTaxPayable", "Current income tax liability"),
    ("BS_DeferredTaxLiability", "Deferred income tax liability"),
    ("BS_OtherCurrentLiabilities", "Other current liabilities"),
    ("BS_OtherNonCurrentLiabilities", "Other liabilities"),
]

_BANK_BS_EQUITY_CATEGORIES: list[tuple[str, str]] = [
    ("BS_ShareCapital", "Share capital"),
    ("BS_SharePremium", "Share premium"),
    ("BS_TreasuryShares", "Treasury shares"),
    ("BS_RetainedEarnings", "Retained earnings"),
    ("BS_Reserves", "Reserves"),
    ("BS_NonControllingInterest", "Non-controlling interest"),
]

# Category names that hold the authoritative stored grand totals.
_BANK_BS_GRAND_TOTAL_CATEGORIES = {
    "BS_TotalAssets",
    "BS_TotalLiabilities",
    "BS_TotalEquity",
}


def _bank_bs_grouped(db_path: str, idcode: str, years: list[int],
                     table: str = "financial_data") -> dict:
    """Group BS rows as {(year, Section): {Category: [(name, value, item_type), ...]}}.

    Mirrors lib.balance_sheet._group_by_year_section but local to this module so
    the bank BS builder is self-contained (per the single-home convention).
    """
    rows = get_financial_rows(db_path, idcode, years, section_prefix="BS_", table=table)
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        out[(r["FVYear"], r["Section"])][r["Category"]].append((
            r["LineItemENG"],
            r["Value"] or 0,
            r.get("ItemType") or "TOTAL",
        ))
    return out


def _is_rollup_name(name: str) -> bool:
    """True for stored roll-up rows that must never be a detail line.

    Catches 'Total Assets', 'Total current assets', 'Total Liabilities and
    Equity', etc. — anything whose name contains 'total'.
    """
    return "total" in name.lower()


def _bank_category_value(items: list[tuple], year_present: bool = True) -> float:
    """Representative value for one BS category in one year.

    ``items`` is the list of (name, value, item_type) tuples already filtered to
    a single (year, section, category). Rule:
      - Drop roll-up rows ('...Total...').
      - If any ItemType='TOTAL' row survives, sum those (the IFRS face line).
        Component breakdowns of that line are then ignored to avoid double count.
      - Otherwise sum the surviving COMPONENT rows (the line is only reported as
        components, e.g. Borrowings = Other Borrowed Funds + Subordinated Debt).
    """
    totals = [v for n, v, it in items if it == "TOTAL" and not _is_rollup_name(n)]
    if totals:
        return sum(totals)
    comps = [v for n, v, it in items if not _is_rollup_name(n)]
    return sum(comps)


def _bank_grand_total(grouped: dict, year: int, section: str, total_category: str) -> float | None:
    """Return the stored grand total for a section, or None if not present.

    Prefers a non-rollup-name match (e.g. 'Total Assets' / 'Total Equity'),
    falling back to the largest-magnitude stored value in the total category so
    that label-spelling drift across years/banks doesn't drop the total. Returns
    None when the total category is absent entirely.
    """
    cat_items = grouped.get((year, section), {}).get(total_category, [])
    if not cat_items:
        return None
    # Exclude the 'Total Liabilities and Equity' cross-foot and 'Total current
    # assets/liabilities' sub-roll-ups; keep the clean grand total.
    preferred_names = {
        "BS_TotalAssets": ("total assets",),
        "BS_TotalLiabilities": ("total liabilities",),
        "BS_TotalEquity": ("total equity", "total equity attributable to owners of parent"),
    }[total_category]
    excluded = ("and equity", "current")
    for want in preferred_names:
        for name, value, *_ in cat_items:
            lo = name.lower().strip()
            if lo == want and not any(x in lo for x in excluded):
                return value
    # Fallback: any non-excluded row, largest magnitude wins.
    candidates = [
        value for name, value, *_ in cat_items
        if not any(x in name.lower() for x in excluded)
    ]
    if candidates:
        return max(candidates, key=lambda v: abs(v or 0))
    return None


def _build_bank_bs_group(
    grouped: dict,
    years: list[int],
    section: str,
    category_layout: list[tuple[str, str]],
) -> tuple[dict, list[tuple[str, dict]]]:
    """Build (sum_of_detail_by_year, detail_lines) for one BS group.

    ``detail_lines`` are [(label, {year: value}), ...] in the layout order,
    dropping any category that is zero/absent in every year. ``sum_of_detail``
    is the per-year sum of those representative category values (used only as a
    fallback when the stored grand total is missing).
    """
    detail: list[tuple[str, dict]] = []
    sum_by_year: dict = {y: 0.0 for y in years}
    for category, label in category_layout:
        vals: dict = {}
        for y in years:
            items = grouped.get((y, section), {}).get(category, [])
            v = _bank_category_value(items) if items else 0
            vals[y] = v
            sum_by_year[y] += v
        if any(v != 0 for v in vals.values()):
            detail.append((label, vals))
    return sum_by_year, detail


def build_bank_bs_sections(db_path: str, idcode: str, years: list[int],
                           table: str = "financial_data") -> list[dict]:
    """Build a bank Balance Sheet as ordered section dicts.

    Same section shape consumed by ``lib.ui.render_statement`` /
    ``sections_to_dataframe`` and ``lib.excel_export.sections_to_xlsx`` —
    {label, kind, total, detail, rolled_up} — so the renderer is unchanged.

    Layout (Lion Finance Group / Bank of Georgia structure):
        Total Assets           (section_with_detail; per-category asset lines)
        Total Liabilities      (section_with_detail; deposits-led funding lines)
        Total Equity           (section_with_detail; capital + reserves lines)
        Total Liabilities & Equity  (derived_total — the cross-foot)
        Balance Check (A - L&E)     (derived_total — ~0 when the BS ties)

    The three group totals use the authoritative stored ``BS_Total*`` rows;
    when a stored grand total is missing for a year, the sum of the
    representative detail lines is used as a fallback. Detail lines are one
    representative figure per reported category (IFRS face line). Sections whose
    total is zero in every year are omitted.
    """
    if not years:
        return []
    years = sorted(years)
    grouped = _bank_bs_grouped(db_path, idcode, years, table=table)

    sections: list[dict] = []

    def _has_any_nonzero_local(d: dict) -> bool:
        return any(v not in (0, None) for v in d.values())

    # --- Assets ---
    asset_sum, asset_detail = _build_bank_bs_group(
        grouped, years, "BS_Assets", _BANK_BS_ASSET_CATEGORIES
    )
    total_assets: dict = {}
    for y in years:
        stored = _bank_grand_total(grouped, y, "BS_Assets", "BS_TotalAssets")
        total_assets[y] = stored if stored not in (None, 0) else asset_sum.get(y, 0)
    if _has_any_nonzero_local(total_assets) or asset_detail:
        sections.append({
            "label": "Total Assets",
            "kind": "section_with_detail",
            "total": total_assets,
            "detail": asset_detail,
            "rolled_up": [],
            "bar": "total",
        })

    # --- Liabilities ---
    liab_sum, liab_detail = _build_bank_bs_group(
        grouped, years, "BS_Liabilities", _BANK_BS_LIABILITY_CATEGORIES
    )
    total_liab: dict = {}
    for y in years:
        stored = _bank_grand_total(grouped, y, "BS_Liabilities", "BS_TotalLiabilities")
        total_liab[y] = stored if stored not in (None, 0) else liab_sum.get(y, 0)
    if _has_any_nonzero_local(total_liab) or liab_detail:
        sections.append({
            "label": "Total Liabilities",
            "kind": "section_with_detail",
            "total": total_liab,
            "detail": liab_detail,
            "rolled_up": [],
            "bar": "cost",
        })

    # --- Equity ---
    eq_sum, eq_detail = _build_bank_bs_group(
        grouped, years, "BS_Equity", _BANK_BS_EQUITY_CATEGORIES
    )
    total_equity: dict = {}
    for y in years:
        stored = _bank_grand_total(grouped, y, "BS_Equity", "BS_TotalEquity")
        total_equity[y] = stored if stored not in (None, 0) else eq_sum.get(y, 0)
    if _has_any_nonzero_local(total_equity) or eq_detail:
        sections.append({
            "label": "Total Equity",
            "kind": "section_with_detail",
            "total": total_equity,
            "detail": eq_detail,
            "rolled_up": [],
            "bar": "income",
        })

    # --- Total Liabilities & Equity (cross-foot) ---
    tle = {y: (total_liab.get(y, 0) or 0) + (total_equity.get(y, 0) or 0) for y in years}
    if _has_any_nonzero_local(tle):
        sections.append({
            "label": "Total Liabilities & Equity",
            "kind": "derived_total",
            "total": tle,
            "detail": [],
            "rolled_up": [],
        })

    # --- Balance Check (Assets - L&E) — should be ~0 when the BS ties ---
    balance_check = {y: (total_assets.get(y, 0) or 0) - (tle.get(y, 0) or 0) for y in years}
    # Only emit when we actually have both sides for at least one year.
    if _has_any_nonzero_local(total_assets) and _has_any_nonzero_local(tle):
        sections.append({
            "label": "Balance Check (Assets - L&E)",
            "kind": "derived_total",
            "total": balance_check,
            "detail": [],
            "rolled_up": [],
        })

    return sections
