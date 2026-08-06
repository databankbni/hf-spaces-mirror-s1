"""Insurance-specific Income Statement layout + underwriting ratios.

Builds an insurer P&L from the reportal.ge line items our ``financial_data``
table actually carries, then computes the standard non-life underwriting KPIs
(loss / expense / combined ratio, retention, underwriting & net margins).

Section dicts share the exact shape produced by
``lib.income_statement.build_is_sections`` — ``{label, kind, total, detail,
rolled_up}`` — so the existing ``render_statement`` renderer works unchanged.

Everything here is pure (read-only DB access via ``get_financial_rows``). Ratios
are OMITTED when the underlying data is missing rather than shown as wrong/zero.

Data note (gap): reportal exports give us *net premium earned* and *claims paid*
reliably, but NOT a clean split of gross-written vs gross-earned premium, nor
movement in the unearned-premium reserve as a separate signed line. We therefore
define the loss/expense ratios on **net earned premium** (the denominator the
stored data supports), which is the conventional non-life basis anyway.
"""
from __future__ import annotations

from lib.data_loader import get_financial_rows
from lib.profitability import _group_rows, _select_stored_row, compute_profitability

# Confirmed production-DB sector label for insurers.
INSURANCE_SECTORS = frozenset({"Insurance"})

# --- IFRS-17 recognised LineItemENG labels (FY2023+ insurer filings) ---
# Insurers adopted IFRS 17 (effective Jan 2023): the premium-based IFRS-4 P&L was
# replaced by an "Insurance revenue" / "Insurance service expenses" presentation.
# A filing is treated as IFRS-17 when an "Insurance Revenue" line is present.
IFRS17_REVENUE = ("Insurance Revenue", "Insurance revenue")
IFRS17_SERVICE_EXPENSES = ("Insurance service expenses",)
IFRS17_REINS_RECOVERIES = ("Amounts recoverable from reinsurers",)
IFRS17_REINS_ALLOCATION = ("Allocation of reinsurance premiums paid",)
IFRS17_REINS_FINANCE = (
    "Reinsurance finance income / (expenses)",
    "Finance Income / (Expenses) from Reinsurance Contracts",
)
IFRS17_DISCONTINUED = ("Discontinued Operations", "Discontinued operations")
# Categories rolled into the "Finance, Other Income & Expenses" residual bucket
# (everything below the insurance-service result and the net-investment line,
# down to PBT). Interest income is shown separately as "Net Investment Income".
_IFRS17_OTHER_CATEGORIES = (
    "IS_OpEx", "IS_DA", "IS_FeeIncome", "IS_InterestExpense",
    "IS_OtherIncome", "IS_OtherExpense",
)

# --- Recognised reportal.ge LineItemENG labels (exact, case-insensitive match) ---
GROSS_PREMIUM = "Insurance premium revenue"
PREMIUM_CEDED = "Insurance premium attributable to reinsurers"
NET_PREMIUM = "Net insurance premium revenue"
NET_INS_REVENUE = "Net insurance revenue"
CLAIMS_PAID = "Insurance benefits and claims paid"
REINS_CLAIMS = "Reinsurers’ share of gross insurance benefits and claims paid"
NET_INS_EXPENSE = "Net expense on insurance liabilities"
ACQUISITION_COST = "Acquisition cost of insurance contracts"
REGRESS = "Income from regress and salvages"

# Net-profit picker (same convention as the non-financial / bank builders).
_NP_PREFERRED = (
    "Profit/(loss)", "Profit / (loss)", "Profit for the year",
    "Net profit", "Net Profit",
)
_NP_EXCLUDES = (
    "before tax", "comprehensive", "owners", "non-controlling",
    "discontinued", "held for sale",
)
_PBT_PREFERRED = (
    "Profit/(loss) before tax from continuing operations",
    "Profit/(loss) before tax", "Profit before tax",
)
_PBT_EXCLUDES = ("comprehensive", "attributable", "non-controlling", "owners")


def _has_any_nonzero(d: dict) -> bool:
    return any(v not in (0, None) for v in d.values())


def _safe_div(numer, denom):
    if numer is None or denom is None or denom == 0:
        return None
    return numer / denom


def _row_by_name(grouped: dict, years: list[int], names) -> dict:
    """{year: value} for the first matching LineItemENG (case-insensitive),
    searched across ALL IS categories. Returns 0 for years with no match."""
    if isinstance(names, str):
        names = (names,)
    wanted = [n.lower() for n in names]
    out = {y: 0.0 for y in years}
    for y in years:
        for (yy, _cat), items in grouped.items():
            if yy != y:
                continue
            for t in items:
                nm = t[0]
                if nm.lower() in wanted and t[1] not in (0, None):
                    out[y] = t[1]
                    break
            if out[y]:
                break
    return out


def _category_total_local(grouped: dict, years: list[int], category: str) -> dict:
    from lib.income_statement import _category_total
    return _category_total(grouped, years, category)


def _year_reporting_basis(grouped: dict, years: list[int]) -> tuple[list[int], list[int]]:
    """Split ``years`` into (ifrs4_years, ifrs17_years) by reporting basis.

    A year is IFRS-17 when its filing carries an "Insurance Revenue" top line
    (insurers adopted IFRS 17 from FY2023); otherwise it's the premium-based
    IFRS-4 presentation. The check is per-year so a company that straddles the
    transition is classified column-by-column, not all-or-nothing.
    """
    ifrs17 = [
        y for y in years
        if _has_any_nonzero(_row_by_name(grouped, [y], IFRS17_REVENUE))
    ]
    ifrs17_set = set(ifrs17)
    ifrs4 = [y for y in years if y not in ifrs17_set]
    return ifrs4, ifrs17


def build_insurance_is_sections(db_path: str, idcode: str, years: list[int]) -> list[dict]:
    """Build an insurer IS as ordered section dicts (same shape as build_is_sections).

    Reporting basis is detected **per year** (not all-or-nothing): insurers
    adopted IFRS 17 from FY2023, replacing the premium-based IFRS-4 P&L with an
    "Insurance revenue" / "Insurance service expenses" presentation. Three cases:

    * all years IFRS-4  → premium/claims layout (:func:`_build_ifrs4_is_sections`)
    * all years IFRS-17 → :func:`_build_ifrs17_is_sections`
    * a span that straddles the FY2023 transition → :func:`_build_mixed_basis_is_sections`,
      which shows each year on its own basis (the other basis's rows stay blank
      in those columns) with one continuous PBT → Net Profit tail.

    IFRS-4 layout:
        Gross Premium Revenue
        Premiums Ceded to Reinsurers
        Net Premiums Earned                (derived: gross + ceded, or stored net)
        Net Insurance Claims & Benefits    (section)
        Acquisition Costs                  (section)
        Underwriting Result                (derived)
        Investment & Other Income          (interest + other income)
        Operating / Admin Expenses         (OpEx ex insurance-flow lines)
        Profit Before Tax                  (stored preferred, else derived)
        Income Tax
        Net Profit / (Loss)

    Sections all-zero across every year are omitted.
    """
    if not years:
        return []
    years = sorted(years)

    rows = get_financial_rows(db_path, idcode, years, section_prefix="IS")
    grouped = _group_rows(rows)

    ifrs4_years, ifrs17_years = _year_reporting_basis(grouped, years)
    # A span straddling the FY2023 IFRS-17 transition gets a single continuous
    # layout that maps both bases onto one comparable spine. (Forcing the whole
    # span into one single-basis layout left the other basis's rows blank AND
    # mis-computed pre-2023 PBT — compute_profitability is only valid for the
    # IFRS-17 line structure.)
    if ifrs4_years and ifrs17_years:
        return _build_unified_insurer_is_sections(grouped, ifrs4_years, ifrs17_years)
    if ifrs17_years:
        return _build_ifrs17_is_sections(grouped, years)
    return _build_ifrs4_is_sections(grouped, years)


def _build_ifrs4_is_sections(grouped: dict, years: list[int]) -> list[dict]:
    """Build the premium-based (IFRS-4) insurer P&L for the given years.

    Layout + shape documented on :func:`build_insurance_is_sections`. Pure
    function over ``grouped`` (the year-grouped IS rows) — no DB access.
    """
    sections: list[dict] = []

    def emit(label, kind, total, detail=None):
        if not _has_any_nonzero(total):
            return
        sections.append({
            "label": label, "kind": kind, "total": total,
            "detail": detail or [], "rolled_up": [],
        })

    gross = _row_by_name(grouped, years, GROSS_PREMIUM)
    ceded = _row_by_name(grouped, years, PREMIUM_CEDED)
    net_prem_stored = _row_by_name(grouped, years, NET_PREMIUM)
    # Net earned premium: prefer the stored net line, else gross + ceded.
    net_prem = {}
    for y in years:
        if net_prem_stored.get(y):
            net_prem[y] = net_prem_stored[y]
        else:
            net_prem[y] = (gross.get(y) or 0) + (ceded.get(y) or 0)

    emit("Gross Premium Revenue", "section_with_detail", gross)
    emit("Premiums Ceded to Reinsurers", "section_with_detail", ceded)
    emit("Net Premiums Earned", "derived_total", net_prem)

    # Net claims & benefits — prefer the consolidated "Net expense on insurance
    # liabilities" line (claims net of reinsurance + reserve movement); else
    # build it from claims paid + reinsurers' share.
    net_ins_exp = _row_by_name(grouped, years, NET_INS_EXPENSE)
    claims_paid = _row_by_name(grouped, years, CLAIMS_PAID)
    reins_share = _row_by_name(grouped, years, REINS_CLAIMS)
    net_claims = {}
    for y in years:
        if net_ins_exp.get(y):
            net_claims[y] = net_ins_exp[y]
        else:
            net_claims[y] = (claims_paid.get(y) or 0) + (reins_share.get(y) or 0)
    emit("Net Insurance Claims & Benefits", "section_with_detail", net_claims)

    acq = _row_by_name(grouped, years, ACQUISITION_COST)
    emit("Acquisition Costs", "section_with_detail", acq)

    regress = _row_by_name(grouped, years, REGRESS)
    # Underwriting result = net premiums + claims (neg) + acquisition (neg) + regress income.
    underwriting = {
        y: (net_prem.get(y) or 0) + (net_claims.get(y) or 0)
           + (acq.get(y) or 0) + (regress.get(y) or 0)
        for y in years
    }
    if _has_any_nonzero(regress):
        emit("Income from Regress & Salvage", "section_with_detail", regress)
    emit("Underwriting Result", "derived_total", underwriting)

    # Investment & other income: interest income + other (non-insurance) income.
    interest_inc = _category_total_local(grouped, years, "IS_InterestIncome")
    other_inc = _category_total_local(grouped, years, "IS_OtherIncome")
    invest_other = {y: (interest_inc.get(y) or 0) + (other_inc.get(y) or 0) for y in years}
    emit("Investment & Other Income", "section_with_detail", invest_other)

    # Operating / admin expenses: IS_OpEx components MINUS the insurance-flow
    # lines already shown above (claims, acquisition, net premium/revenue
    # roll-ups). What remains is genuine admin / personnel / marketing opex.
    from lib.income_statement import _collect_detail_items, _sort_by_magnitude, _top5_with_other_split
    _insurance_flow = {
        s.lower() for s in (
            CLAIMS_PAID, REINS_CLAIMS, NET_INS_EXPENSE, ACQUISITION_COST,
            NET_INS_REVENUE, NET_PREMIUM, GROSS_PREMIUM,
            "Insurance contract liabilities:",
            "Reinsurers’ share of insurance liabilities provision",
            "Reinsurers’ share of gross change in insurance contracts",
            "Total operating expense",
        )
    }
    opex_all = _collect_detail_items(grouped, years, "IS_OpEx")
    admin_opex = [(n, v) for n, v in opex_all if n.lower() not in _insurance_flow]
    admin_total = {y: sum(v.get(y, 0) for _n, v in admin_opex) for y in years}
    visible, _rolled = _top5_with_other_split(admin_opex, years)
    emit("Operating / Admin Expenses", "section_with_detail", admin_total, _sort_by_magnitude(visible))

    # Profit before tax — prefer stored, else underwriting + invest + admin.
    tax = _category_total_local(grouped, years, "IS_Tax")
    computed_pbt = {
        y: (underwriting.get(y) or 0) + (invest_other.get(y) or 0) + (admin_total.get(y) or 0)
        for y in years
    }
    pbt = {}
    for y in years:
        np_rows = [(t[0], t[1]) for t in grouped.get((y, "IS_NetProfit"), [])]
        stored = _select_stored_row(np_rows, _PBT_PREFERRED, _PBT_EXCLUDES)
        pbt[y] = stored if stored is not None else computed_pbt.get(y, 0)
    emit("Profit Before Tax", "derived_total", pbt)

    emit("Income Tax", "section_with_detail", tax,
         _sort_by_magnitude(_collect_detail_items(grouped, years, "IS_Tax")))

    # Discontinued operations — itemised when the filing reports a separate
    # result below continuing-operations profit (e.g. a divested line). Shown
    # only when non-zero, so most insurers don't get the row; it lets PBT → Net
    # Profit reconcile and keeps the row consistent across the IFRS-17 columns
    # in a transition-straddling view.
    discontinued = _row_by_name(grouped, years, IFRS17_DISCONTINUED)
    if _has_any_nonzero(discontinued):
        emit("Discontinued Operations", "section_with_detail", discontinued)

    # Net profit — stored preferred, else PBT + tax + discontinued.
    np_total = {}
    for y in years:
        np_rows = [(t[0], t[1]) for t in grouped.get((y, "IS_NetProfit"), [])]
        picked = _select_stored_row(np_rows, _NP_PREFERRED, _NP_EXCLUDES)
        if picked is None:
            picked = (pbt.get(y) or 0) + (tax.get(y) or 0) + (discontinued.get(y) or 0)
        np_total[y] = picked
    emit("Net Profit / (Loss)", "final_total", np_total)

    return sections


def _build_ifrs17_is_sections(grouped: dict, years: list[int]) -> list[dict]:
    """Build an IFRS-17 insurer P&L (FY2023+) as ordered section dicts.

    Same shape as :func:`build_insurance_is_sections` (``{label, kind, total,
    detail, rolled_up}``) so ``render_statement`` works unchanged.

    Layout (each line ties into the next; PBT→Net Profit holds):
        Insurance Revenue
        Insurance Service Expenses
        Insurance Service Result before Reinsurance   (derived; only with reinsurance)
        Net Income / (Expense) from Reinsurance        (recoveries + ceded + finance)
        Insurance Service Result                       (derived)
        Net Investment Income                          (= interest income)
        Finance, Other Income & Expenses               (residual to PBT; detailed)
        Profit Before Tax                              (derived = compute_profitability PBT)
        Income Tax
        Discontinued Operations                        (only when present)
        Net Profit / (Loss)                            (stored, final)

    The "Finance, Other Income & Expenses" total is computed as the residual
    ``PBT − revenue − service expenses − reinsurance − investment income`` so the
    visible chain reconciles to PBT exactly; its detail rows are the remaining
    income-statement line items (they sum to that residual).
    """
    from lib.income_statement import (
        _collect_detail_items, _sort_by_magnitude, _top5_with_other_split,
    )

    sections: list[dict] = []

    def emit(label, kind, total, detail=None, rolled_up=None):
        if not _has_any_nonzero(total):
            return
        sections.append({
            "label": label, "kind": kind, "total": total,
            "detail": detail or [], "rolled_up": rolled_up or [],
        })

    revenue = _row_by_name(grouped, years, IFRS17_REVENUE)
    service_exp = _row_by_name(grouped, years, IFRS17_SERVICE_EXPENSES)
    svc_result_pre = {y: (revenue.get(y) or 0) + (service_exp.get(y) or 0) for y in years}

    recoveries = _row_by_name(grouped, years, IFRS17_REINS_RECOVERIES)
    ceded = _row_by_name(grouped, years, IFRS17_REINS_ALLOCATION)
    reins_fin = _row_by_name(grouped, years, IFRS17_REINS_FINANCE)
    reinsurance = {
        y: (recoveries.get(y) or 0) + (ceded.get(y) or 0) + (reins_fin.get(y) or 0)
        for y in years
    }
    svc_result = {y: svc_result_pre[y] + reinsurance[y] for y in years}

    interest = _category_total_local(grouped, years, "IS_InterestIncome")
    tax = _category_total_local(grouped, years, "IS_Tax")
    pbt = {y: compute_profitability(grouped, y).pbt for y in years}
    discontinued = _row_by_name(grouped, years, IFRS17_DISCONTINUED)

    # Residual finance/other bucket = PBT minus everything shown above it.
    other = {
        y: pbt[y] - (revenue.get(y) or 0) - (service_exp.get(y) or 0)
           - reinsurance[y] - (interest.get(y) or 0)
        for y in years
    }
    # Detail for the residual bucket: every remaining IS line (the reinsurance
    # recoveries/ceded/finance lines are shown in their own section, so drop them).
    _reins_names = {n.lower() for n in (
        IFRS17_REINS_RECOVERIES + IFRS17_REINS_ALLOCATION + IFRS17_REINS_FINANCE
    )}
    other_detail = [
        (n, v)
        for cat in _IFRS17_OTHER_CATEGORIES
        for (n, v) in _collect_detail_items(grouped, years, cat)
        if n.lower() not in _reins_names
    ]

    emit("Insurance Revenue", "section_with_detail", revenue)
    emit("Insurance Service Expenses", "section_with_detail", service_exp)

    has_reinsurance = _has_any_nonzero(reinsurance)
    if has_reinsurance:
        emit("Insurance Service Result before Reinsurance", "derived_total", svc_result_pre)
        reins_detail = [
            (name, vals) for name, vals in (
                ("Amounts recoverable from reinsurers", recoveries),
                ("Allocation of reinsurance premiums paid", ceded),
                ("Reinsurance finance income / (expenses)", reins_fin),
            ) if _has_any_nonzero(vals)
        ]
        emit("Net Income / (Expense) from Reinsurance", "section_with_detail",
             reinsurance, reins_detail)
    emit("Insurance Service Result", "derived_total", svc_result)

    emit("Net Investment Income", "section_with_detail", interest)
    visible, rolled = _top5_with_other_split(_sort_by_magnitude(other_detail), years)
    emit("Finance, Other Income & Expenses", "section_with_detail", other,
         visible, rolled)

    emit("Profit Before Tax", "derived_total", pbt)
    emit("Income Tax", "section_with_detail", tax,
         _sort_by_magnitude(_collect_detail_items(grouped, years, "IS_Tax")))
    if _has_any_nonzero(discontinued):
        emit("Discontinued Operations", "section_with_detail", discontinued)

    np_total = {}
    for y in years:
        np_rows = [(t[0], t[1]) for t in grouped.get((y, "IS_NetProfit"), [])]
        picked = _select_stored_row(np_rows, _NP_PREFERRED, _NP_EXCLUDES)
        if picked is None:
            picked = (pbt.get(y) or 0) + (tax.get(y) or 0) + (discontinued.get(y) or 0)
        np_total[y] = picked
    emit("Net Profit / (Loss)", "final_total", np_total)

    return sections


# Interest-income line labels for the single "Net Investment Income" row. Taking
# the FIRST matching row (not a category SUM) sidesteps the double-count when a
# filing carries both "Interest Income" and an "Interest income from:" sub-header
# at the same value.
_NII_NAMES = (
    "Net interest income", "Interest Income", "Interest income from:",
    "Interest and similar income",
)


def _build_unified_insurer_is_sections(
    grouped: dict, ifrs4_years: list[int], ifrs17_years: list[int]
) -> list[dict]:
    """Single continuous insurer P&L across the FY2023 IFRS-17 transition.

    Insurers adopted IFRS 17 in FY2023, and the two bases aggregate expenses at
    different levels — IFRS-4's underwriting result is BEFORE admin/overhead,
    IFRS-17's insurance service result is AFTER attributable expenses — so they
    only become comparable at an **all-in net insurance result** level. For
    IFRS-4 years that's the underwriting result NET of operating/admin expenses;
    for IFRS-17 years it's the Insurance Service Result (these line up: e.g. TBC
    ~18.7% of revenue on both bases). Below it the Net Investment Income → PBT →
    Net Profit spine is genuinely comparable and shown as one continuous series.

    The basis-specific build-up (premiums/claims vs revenue/service-expenses) is
    kept as indented detail under the result line, each row populated only in its
    own years (the other basis's columns render blank). The "Other Income &
    Expenses (net)" line is the residual ``PBT − result − investment income`` so
    the visible chain reconciles to PBT every year (the pre-2023 IFRS-4 source
    components don't tie exactly, so this absorbs the difference).
    """
    from lib.income_statement import _collect_detail_items, _sort_by_magnitude

    years = sorted(set(ifrs4_years) | set(ifrs17_years))
    ifrs17_set = set(ifrs17_years)
    sections: list[dict] = []

    def emit(label, kind, total, detail=None):
        if not _has_any_nonzero(total):
            return
        sections.append({
            "label": label, "kind": kind, "total": total,
            "detail": detail or [], "rolled_up": [],
        })

    def _span(d: dict, yrs: list[int]) -> dict:
        """Value dict limited to ``yrs`` (other years absent → render blank)."""
        return {y: d.get(y, 0) for y in yrs}

    # ---- IFRS-4 insurance build-up (premium / claims / acquisition / admin) --
    gross = _row_by_name(grouped, ifrs4_years, GROSS_PREMIUM)
    ceded = _row_by_name(grouped, ifrs4_years, PREMIUM_CEDED)
    net_prem_stored = _row_by_name(grouped, ifrs4_years, NET_PREMIUM)
    net_prem = {
        y: (net_prem_stored.get(y) or (gross.get(y, 0) + ceded.get(y, 0)))
        for y in ifrs4_years
    }
    net_ins_exp = _row_by_name(grouped, ifrs4_years, NET_INS_EXPENSE)
    claims_paid = _row_by_name(grouped, ifrs4_years, CLAIMS_PAID)
    reins_share = _row_by_name(grouped, ifrs4_years, REINS_CLAIMS)
    net_claims = {
        y: (net_ins_exp.get(y) or (claims_paid.get(y, 0) + reins_share.get(y, 0)))
        for y in ifrs4_years
    }
    acq = _row_by_name(grouped, ifrs4_years, ACQUISITION_COST)
    regress = _row_by_name(grouped, ifrs4_years, REGRESS)
    _insurance_flow = {
        s.lower() for s in (
            CLAIMS_PAID, REINS_CLAIMS, NET_INS_EXPENSE, ACQUISITION_COST,
            NET_INS_REVENUE, NET_PREMIUM, GROSS_PREMIUM,
            "Insurance contract liabilities:",
            "Reinsurers’ share of insurance liabilities provision",
            "Reinsurers’ share of gross change in insurance contracts",
            "Total operating expense",
        )
    }
    opex_all = _collect_detail_items(grouped, ifrs4_years, "IS_OpEx")
    admin = {
        y: sum(v.get(y, 0) for n, v in opex_all if n.lower() not in _insurance_flow)
        for y in ifrs4_years
    }

    # ---- IFRS-17 insurance build-up (revenue / service exp / reinsurance) ----
    revenue = _row_by_name(grouped, ifrs17_years, IFRS17_REVENUE)
    service_exp = _row_by_name(grouped, ifrs17_years, IFRS17_SERVICE_EXPENSES)
    recoveries = _row_by_name(grouped, ifrs17_years, IFRS17_REINS_RECOVERIES)
    ceded17 = _row_by_name(grouped, ifrs17_years, IFRS17_REINS_ALLOCATION)
    reins_fin = _row_by_name(grouped, ifrs17_years, IFRS17_REINS_FINANCE)
    reins17 = {
        y: recoveries.get(y, 0) + ceded17.get(y, 0) + reins_fin.get(y, 0)
        for y in ifrs17_years
    }

    # ---- Net Insurance Result (all-in; comparable across the break) ----------
    nir = {y: 0.0 for y in years}
    for y in ifrs4_years:
        nir[y] = (net_prem.get(y, 0) + net_claims.get(y, 0) + acq.get(y, 0)
                  + regress.get(y, 0) + admin.get(y, 0))
    for y in ifrs17_years:
        nir[y] = revenue.get(y, 0) + service_exp.get(y, 0) + reins17.get(y, 0)

    nir_detail = [
        ("Net premiums earned", _span(net_prem, ifrs4_years)),
        ("Net insurance claims & benefits", _span(net_claims, ifrs4_years)),
        ("Acquisition costs", _span(acq, ifrs4_years)),
    ]
    if _has_any_nonzero(regress):
        nir_detail.append(("Income from regress & salvage", _span(regress, ifrs4_years)))
    nir_detail.append(("Operating & admin expenses", _span(admin, ifrs4_years)))
    nir_detail.append(("Insurance revenue", _span(revenue, ifrs17_years)))
    nir_detail.append(("Insurance service expenses", _span(service_exp, ifrs17_years)))
    if _has_any_nonzero(reins17):
        nir_detail.append(("Net reinsurance result", _span(reins17, ifrs17_years)))
    emit("Net Insurance Result", "section_with_detail", nir, nir_detail)

    # ---- Net Investment Income (single interest line; both bases) ------------
    nii = _row_by_name(grouped, years, _NII_NAMES)
    emit("Net Investment Income", "section_with_detail", nii)

    # ---- PBT per basis: IFRS-4 prefers the stored 'before tax' row; IFRS-17
    # uses compute_profitability (valid only for the IFRS-17 line structure). ---
    pbt = {}
    for y in years:
        np_rows = [(t[0], t[1]) for t in grouped.get((y, "IS_NetProfit"), [])]
        if y in ifrs17_set:
            pbt[y] = compute_profitability(grouped, y).pbt
        else:
            stored = _select_stored_row(np_rows, _PBT_PREFERRED, _PBT_EXCLUDES)
            pbt[y] = stored if stored is not None else compute_profitability(grouped, y).pbt

    # Residual so the visible chain (result + investment + other) ties to PBT.
    other = {y: pbt[y] - nir.get(y, 0) - (nii.get(y) or 0) for y in years}
    emit("Other Income & Expenses (net)", "section_with_detail", other)

    emit("Profit Before Tax", "derived_total", pbt)

    tax = _category_total_local(grouped, years, "IS_Tax")
    emit("Income Tax", "section_with_detail", tax,
         _sort_by_magnitude(_collect_detail_items(grouped, years, "IS_Tax")))

    discontinued = _row_by_name(grouped, years, IFRS17_DISCONTINUED)
    if _has_any_nonzero(discontinued):
        emit("Discontinued Operations", "section_with_detail", discontinued)

    np_total = {}
    for y in years:
        np_rows = [(t[0], t[1]) for t in grouped.get((y, "IS_NetProfit"), [])]
        picked = _select_stored_row(np_rows, _NP_PREFERRED, _NP_EXCLUDES)
        if picked is None:
            picked = pbt.get(y, 0) + (tax.get(y) or 0) + (discontinued.get(y) or 0)
        np_total[y] = picked
    emit("Net Profit / (Loss)", "final_total", np_total)

    return sections


def compute_insurance_ratios(db_path: str, idcode: str, years: list[int]) -> list[dict]:
    """Compute non-life underwriting KPIs per year.

    Row shape matches compute_bank_ratios: {"Ratio", year..., "_fmt"}.

    Definitions (all on a NET-earned-premium basis — see module docstring):
      - Loss ratio       = |Net claims & benefits| / Net premiums earned
      - Acquisition ratio= |Acquisition costs| / Net premiums earned
      - Admin/expense ratio = |Operating/admin expenses| / Net premiums earned
      - Expense ratio    = Acquisition + Admin ratios
      - Combined ratio   = Loss ratio + Expense ratio  (>100% = underwriting loss)
      - Retention ratio  = Net premiums earned / Gross premium revenue
      - Underwriting margin = Underwriting result / Net premiums earned
      - Net margin       = Net profit / Total revenue (Net premiums earned proxy
                            when Total Revenue is absent)
    """
    if not years:
        return []
    years = sorted(years)
    rows = get_financial_rows(db_path, idcode, years, section_prefix="IS")
    grouped = _group_rows(rows)

    gross = _row_by_name(grouped, years, GROSS_PREMIUM)
    ceded = _row_by_name(grouped, years, PREMIUM_CEDED)
    net_prem_stored = _row_by_name(grouped, years, NET_PREMIUM)
    net_prem = {}
    for y in years:
        net_prem[y] = net_prem_stored[y] if net_prem_stored.get(y) else (
            (gross.get(y) or 0) + (ceded.get(y) or 0)
        )

    net_ins_exp = _row_by_name(grouped, years, NET_INS_EXPENSE)
    claims_paid = _row_by_name(grouped, years, CLAIMS_PAID)
    reins_share = _row_by_name(grouped, years, REINS_CLAIMS)
    net_claims = {}
    for y in years:
        net_claims[y] = net_ins_exp[y] if net_ins_exp.get(y) else (
            (claims_paid.get(y) or 0) + (reins_share.get(y) or 0)
        )
    acq = _row_by_name(grouped, years, ACQUISITION_COST)
    regress = _row_by_name(grouped, years, REGRESS)

    from lib.income_statement import _collect_detail_items
    _insurance_flow = {
        s.lower() for s in (
            CLAIMS_PAID, REINS_CLAIMS, NET_INS_EXPENSE, ACQUISITION_COST,
            NET_INS_REVENUE, NET_PREMIUM, GROSS_PREMIUM,
            "Insurance contract liabilities:",
            "Reinsurers’ share of insurance liabilities provision",
            "Reinsurers’ share of gross change in insurance contracts",
            "Total operating expense",
        )
    }
    opex_all = _collect_detail_items(grouped, years, "IS_OpEx")
    admin_total = {
        y: sum(v.get(y, 0) for n, v in opex_all if n.lower() not in _insurance_flow)
        for y in years
    }

    interest_inc = _category_total_local(grouped, years, "IS_InterestIncome")
    other_inc = _category_total_local(grouped, years, "IS_OtherIncome")
    tax = _category_total_local(grouped, years, "IS_Tax")
    total_rev = _category_total_local(grouped, years, "IS_Revenue")

    np_total = {}
    for y in years:
        np_rows = [(t[0], t[1]) for t in grouped.get((y, "IS_NetProfit"), [])]
        picked = _select_stored_row(np_rows, _NP_PREFERRED, _NP_EXCLUDES)
        np_total[y] = picked

    underwriting = {
        y: (net_prem.get(y) or 0) + (net_claims.get(y) or 0)
           + (acq.get(y) or 0) + (regress.get(y) or 0)
        for y in years
    }

    def _abs(d, y):
        v = d.get(y)
        return abs(v) if v not in (None, 0) else (0 if v == 0 else None)

    out_rows: list[dict] = []

    def _emit(label, fmt, per_year):
        if all(v is None for v in per_year.values()):
            return
        rec = {"Ratio": label, "_fmt": fmt}
        for y in years:
            rec[y] = per_year.get(y)
        out_rows.append(rec)

    loss = {y: _safe_div(_abs(net_claims, y), net_prem.get(y) or None) for y in years}
    acq_r = {y: _safe_div(_abs(acq, y), net_prem.get(y) or None) for y in years}
    admin_r = {y: _safe_div(_abs(admin_total, y), net_prem.get(y) or None) for y in years}
    expense = {}
    combined = {}
    for y in years:
        a, b = acq_r.get(y), admin_r.get(y)
        if a is None and b is None:
            expense[y] = None
        else:
            expense[y] = (a or 0) + (b or 0)
        if loss.get(y) is None and expense[y] is None:
            combined[y] = None
        else:
            combined[y] = (loss.get(y) or 0) + (expense[y] or 0)
    retention = {y: _safe_div(net_prem.get(y), gross.get(y) or None) for y in years}
    uw_margin = {y: _safe_div(underwriting.get(y), net_prem.get(y) or None) for y in years}
    rev_denom = {y: (total_rev.get(y) or net_prem.get(y) or None) for y in years}
    net_margin = {y: _safe_div(np_total.get(y), rev_denom.get(y)) for y in years}
    invest_yield = {y: _safe_div((interest_inc.get(y) or 0) + (other_inc.get(y) or 0),
                                 net_prem.get(y) or None) for y in years}

    _emit("Loss Ratio", "pct", loss)
    _emit("Acquisition Cost Ratio", "pct", acq_r)
    _emit("Admin Expense Ratio", "pct", admin_r)
    _emit("Expense Ratio", "pct", expense)
    _emit("Combined Ratio", "pct", combined)
    _emit("Retention Ratio", "pct", retention)
    _emit("Underwriting Margin", "pct", uw_margin)
    _emit("Investment & Other / Net Premiums", "pct", invest_yield)
    _emit("Net Margin", "pct", net_margin)

    return out_rows
