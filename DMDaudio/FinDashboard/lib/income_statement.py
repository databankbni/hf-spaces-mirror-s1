import pandas as pd
from lib.data_loader import get_financial_rows

# Sprint 5 SSOT: the canonical subtotal definitions, name lists and shared
# primitives moved to lib.profitability. Re-imported here (not aliased under
# new names) so every existing `from lib.income_statement import X` keeps
# working unchanged.
from lib.profitability import (  # noqa: F401  (re-exported for compatibility)
    GROSS_PROFIT_PREFERRED_NAMES,
    NET_PROFIT_EXCLUDE_SUBSTRINGS,
    NET_PROFIT_PREFERRED_NAMES,
    OPERATING_INCOME_PREFERRED_NAMES,
    PBT_PREFERRED_NAMES,
    _group_rows,
    _opex_nonfinancial_impairment_items,
    _opex_operating_income_items,
    _select_stored_row,
    _sum_category,
    compute_profitability,
)

CATEGORY_ORDER = [
    ("IS_Revenue", "REVENUE", "TOTAL REVENUE"),
    ("IS_COGS", "COGS", "TOTAL COGS"),
    (None, "GROSS PROFIT", None),
    ("IS_OpEx", "OPERATING EXPENSES", "TOTAL OPERATING EXPENSES"),
    (None, "EBITDA", None),
    ("IS_DA", "DEPRECIATION & AMORTIZATION", "TOTAL D&A"),
    (None, "EBIT", None),
    ("IS_InterestIncome", "INTEREST INCOME", "TOTAL INTEREST INCOME"),
    ("IS_InterestExpense", "INTEREST EXPENSE", "TOTAL INTEREST EXPENSE"),
    ("IS_FeeIncome", "FEE & COMMISSION INCOME", "TOTAL FEE & COMMISSION INCOME"),
    ("IS_OtherIncome", "OTHER INCOME", "TOTAL OTHER INCOME"),
    ("IS_OtherExpense", "OTHER EXPENSE", "TOTAL OTHER EXPENSE"),
    (None, "PROFIT BEFORE TAX", None),
    ("IS_Tax", "INCOME TAX", "TOTAL INCOME TAX"),
    (None, "NET PROFIT / (LOSS)", None),
]

def _strip_item_type(items: list) -> list[tuple[str, float]]:
    """Return [(name, value)] from a list of (name, value[, item_type]) tuples.

    Helper for callers that don't care about item type. Tolerates legacy 2-tuples.
    """
    return [(t[0], t[1]) for t in items]

def build_is_table(db_path: str, idcode: str, years: list[int]) -> pd.DataFrame:
    """Build a multi-year Income Statement DataFrame.

    Returns DataFrame with columns: ['Line Item', year1, year2, ...]
    """
    if not years:
        return pd.DataFrame(columns=["Line Item"])

    rows = get_financial_rows(db_path, idcode, years, section_prefix="IS")
    grouped = _group_rows(rows)

    table: list[dict] = []

    def row_for(label: str, values_by_year: dict) -> dict:
        rec = {"Line Item": label}
        for y in years:
            rec[y] = values_by_year.get(y, 0)
        return rec

    revenue_by_year: dict = {}
    cogs_by_year: dict = {}
    opex_by_year: dict = {}
    da_by_year: dict = {}
    int_inc_by_year: dict = {}
    int_exp_by_year: dict = {}
    fee_inc_by_year: dict = {}
    oth_inc_by_year: dict = {}
    oth_exp_by_year: dict = {}
    tax_by_year: dict = {}

    # Collect distinct detail items across years (preserve first-seen order)
    seen_items: dict = {}
    for category, header, total_label in CATEGORY_ORDER:
        if category is None:
            continue
        for y in years:
            _, details = _sum_category(grouped, y, category)
            for item, _v in details:
                key = (category, item)
                if key not in seen_items:
                    seen_items[key] = (category, item)

    def emit_section(category: str, header: str, total_label: str | None, totals_dict: dict):
        if category is None:
            return
        table.append(row_for(header, {y: None for y in years}))
        for key, (cat, item) in seen_items.items():
            if cat != category:
                continue
            values = {y: 0 for y in years}
            for y in years:
                items_yr = grouped.get((y, category), [])
                for i, v, *_ in items_yr:
                    if i == item and "Total" not in i and "TOTAL" not in i.upper():
                        values[y] = v
                        break
            if any(v != 0 for v in values.values()):
                table.append(row_for(f"  {item}", values))
        if total_label:
            totals = {}
            for y in years:
                total, _ = _sum_category(grouped, y, category)
                totals[y] = total
                totals_dict[y] = total
            table.append(row_for(total_label, totals))

    # Revenue
    emit_section("IS_Revenue", "REVENUE", "TOTAL REVENUE", revenue_by_year)
    # COGS
    emit_section("IS_COGS", "COGS", "TOTAL COGS", cogs_by_year)
    # Gross profit
    gp_by_year = {y: revenue_by_year.get(y, 0) + cogs_by_year.get(y, 0) for y in years}
    table.append(row_for("GROSS PROFIT", gp_by_year))
    # OpEx
    emit_section("IS_OpEx", "OPERATING EXPENSES", "TOTAL OPERATING EXPENSES", opex_by_year)
    # EBITDA
    ebitda_by_year = {y: gp_by_year[y] + opex_by_year.get(y, 0) for y in years}
    table.append(row_for("EBITDA", ebitda_by_year))
    # D&A
    emit_section("IS_DA", "DEPRECIATION & AMORTIZATION", "TOTAL D&A", da_by_year)
    # EBIT
    ebit_by_year = {y: ebitda_by_year[y] + da_by_year.get(y, 0) for y in years}
    table.append(row_for("EBIT / OPERATING INCOME", ebit_by_year))
    # Finance items
    emit_section("IS_InterestIncome", "INTEREST INCOME", "TOTAL INTEREST INCOME", int_inc_by_year)
    emit_section("IS_InterestExpense", "INTEREST EXPENSE", "TOTAL INTEREST EXPENSE", int_exp_by_year)
    emit_section("IS_FeeIncome", "FEE & COMMISSION INCOME", "TOTAL FEE & COMMISSION INCOME", fee_inc_by_year)
    # Other
    emit_section("IS_OtherIncome", "OTHER INCOME", "TOTAL OTHER INCOME", oth_inc_by_year)
    emit_section("IS_OtherExpense", "OTHER EXPENSE", "TOTAL OTHER EXPENSE", oth_exp_by_year)
    # PBT
    pbt_by_year = {
        y: ebit_by_year[y]
        + int_inc_by_year.get(y, 0)
        + int_exp_by_year.get(y, 0)
        + fee_inc_by_year.get(y, 0)
        + oth_inc_by_year.get(y, 0)
        + oth_exp_by_year.get(y, 0)
        for y in years
    }
    table.append(row_for("PROFIT BEFORE TAX", pbt_by_year))
    # Tax
    emit_section("IS_Tax", "INCOME TAX", "TOTAL INCOME TAX", tax_by_year)
    # Net Profit — prefer first non-zero stored IS_NetProfit row per year, else PBT + Tax
    np_by_year: dict = {}
    for y in years:
        stored = grouped.get((y, "IS_NetProfit"), [])
        stored_nonzero = next((t[1] for t in stored if t[1] != 0), None)
        if stored_nonzero is not None:
            np_by_year[y] = stored_nonzero
        else:
            np_by_year[y] = pbt_by_year[y] + tax_by_year.get(y, 0)
    table.append(row_for("NET PROFIT / (LOSS)", np_by_year))

    df = pd.DataFrame(table)
    cols = ["Line Item"] + years
    return df[cols]


def _collect_detail_items(grouped: dict, years: list[int], category: str,
                         *, exclude_section_total: bool = False) -> list[tuple[str, dict]]:
    """Collect non-zero detail items for a category as [(name, {year: value}), ...].

    Skips items whose name contains 'Total' (those are stored grand-totals, not
    details). Skips items that are zero across every year. Both TOTAL and
    COMPONENT items appear here.

    ``exclude_section_total`` additionally drops the row that IS the section
    total, for the shape where reportal names the grand total WITHOUT the word
    "Total" — most commonly ``Net Revenue`` (``ItemType='TOTAL'``) sitting above
    ``- sale of goods`` / ``- rendering of services`` components. Because the
    name filter above cannot see it, that row renders as a detail line beneath
    the identical bold subtotal AND alongside the components, so the column does
    not add up (33,619 company-years on IS_Revenue, 4,613 on IS_COGS).

    It fires only when :func:`lib.profitability._sum_category` would have taken
    the total from exactly one ``ItemType='TOTAL'`` row (no "Total"-named
    roll-up present) AND at least one non-TOTAL row exists to serve as the
    breakdown. So sections whose sole row is that total (COGS, D&A, Interest for
    most filers) are left exactly as they render today — the goal is to stop the
    duplication that breaks footing, not to strip single-line sections.

    OPT-IN because the bank / insurance builders derive their section subtotals
    by RE-SUMMING these rows; dropping one there would move a reported number.
    Only pass it where the subtotal comes from ``lib.profitability`` (i.e. from
    ``_sum_category``, so total and detail stay consistent by construction).

    Detail rows that differ ONLY by capitalization / surrounding whitespace are
    merged into a single row — the reportal.ge export is inconsistent about case
    (a filer reports "Other income" in most years and "Other Income" in one, or
    even both spellings in the SAME year, e.g. GPG/405098399 FY2018). The
    first-seen spelling is kept as the display label and the per-year values are
    summed. This is DISPLAY-only: every section subtotal comes from
    ``lib.profitability`` (non-financial) or from re-summing these rows (bank /
    insurance builders, where sums are order-independent), so merging changes no
    reported number — it only stops the same line rendering twice.
    """
    skip_name: str | None = None
    if exclude_section_total:
        named_rollup = False
        total_names: set = set()
        other_rows = False
        for y in years:
            for t in grouped.get((y, category), []):
                name = t[0]
                item_type = t[2] if len(t) == 3 else "TOTAL"
                if "Total" in name or "TOTAL" in name.upper():
                    named_rollup = True
                elif item_type == "TOTAL":
                    total_names.add(name)
                else:
                    other_rows = True
        # A "Total"-named roll-up means _sum_category used THAT (already filtered
        # out below); >1 TOTAL row means it summed them, so each is a genuine
        # constituent and must stay.
        if not named_rollup and other_rows and len(total_names) == 1:
            skip_name = next(iter(total_names))

    by_item: dict = {}
    order: list = []
    for y in years:
        for t in grouped.get((y, category), []):
            item, value = t[0], t[1]
            if "Total" in item or "TOTAL" in item.upper():
                continue
            if skip_name is not None and item == skip_name:
                continue
            if item not in by_item:
                by_item[item] = {yr: 0 for yr in years}
                order.append(item)
            by_item[item][y] = value
    # Fold case-/whitespace-only variants together, preserving first-seen order
    # and the first-seen spelling as the display label.
    merged: dict = {}
    merged_order: list = []
    for name in order:
        key = name.strip().casefold()
        if key not in merged:
            merged[key] = {"label": name, "vals": {yr: 0 for yr in years}}
            merged_order.append(key)
        for y in years:
            merged[key]["vals"][y] += by_item[name].get(y, 0)
    out = []
    for key in merged_order:
        entry = merged[key]
        if any(v != 0 for v in entry["vals"].values()):
            out.append((entry["label"], entry["vals"]))
    return out


def _sort_by_magnitude(details: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Sort detail items descending by sum of abs(value) across years."""
    return sorted(
        details,
        key=lambda kv: sum(abs(v) for v in kv[1].values()),
        reverse=True,
    )


def _add_implied_other(
    details: list[tuple[str, dict]],
    section_total: dict[int, float],
    years: list[int],
    threshold_pct: float = 0.005,
) -> list[tuple[str, dict]]:
    """If the section has '- prefix' breakdowns that don't sum to the parent
    total, append a synthetic '- Other (implied)' row carrying the diff.

    Rules:
      - Only applies when at least one '- prefix' detail item exists in the section.
      - Computes per-year: ``implied = total - sum_of_prefix_components``.
      - Includes the row only if the implied value is materially non-zero in at
        least one year (|implied| > threshold_pct * |total| AND not just rounding).
      - Direction can be positive (unreported component) or negative (overstatement
        / reclassification). Both are surfaced — the sign tells the analyst whether
        the parent under- or over-states the breakdown.

    The synthetic row is sorted into the existing detail order via the caller's
    subsequent _sort_by_magnitude call (if any).
    """
    prefix_items = [(n, v) for n, v in details if n.startswith("- ")]
    if not prefix_items:
        return details
    nonzero_year_count = 0
    implied: dict[int, float] = {}
    for y in years:
        total_y = section_total.get(y, 0)
        comp_sum = sum(vals.get(y, 0) for _, vals in prefix_items)
        diff = total_y - comp_sum
        implied[y] = diff
        if total_y != 0 and abs(diff) > threshold_pct * abs(total_y) and abs(diff) > 1:
            nonzero_year_count += 1
    if nonzero_year_count == 0:
        return details
    return list(details) + [("- Other (implied)", implied)]


def _top5_with_other(details: list[tuple[str, dict]], years: list[int]) -> list[tuple[str, dict]]:
    """Return top-5 items by magnitude plus an aggregated 'Other (N items)' row.

    Special case: when exactly one item would land in the "Other" bucket, show
    that item inline (as its real name) instead of wrapping it in a single-item
    Other row — the rollup adds no information when N=1.
    """
    sorted_items = _sort_by_magnitude(details)
    if len(sorted_items) <= 5:
        return sorted_items
    top5 = sorted_items[:5]
    rest = sorted_items[5:]
    if len(rest) == 1:
        return top5 + rest
    other_vals = {y: 0 for y in years}
    for _name, vals in rest:
        for y in years:
            other_vals[y] += vals.get(y, 0)
    top5.append((f"Other ({len(rest)} items)", other_vals))
    return top5


def _top5_with_other_split(
    details: list[tuple[str, dict]], years: list[int]
) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """Like `_top5_with_other` but also returns the rolled-up items as a separate list.

    Returns (visible_detail, rolled_up):
      - visible_detail: top-5 + 'Other (N items)' row when there are >5 items, else
        the sorted items unchanged.
      - rolled_up: the items aggregated into 'Other', sorted by magnitude descending.
        Empty list when there are <=5 items.

    Special case: when exactly one item would land in the "Other" bucket, show
    that item inline (as its real name) instead of wrapping it in a single-item
    Other row — the rollup adds no information when N=1, and the renderer's
    "Expand 'Other'" disclosure is suppressed because rolled_up is empty.
    """
    sorted_items = _sort_by_magnitude(details)
    if len(sorted_items) <= 5:
        return sorted_items, []
    top5 = sorted_items[:5]
    rest = sorted_items[5:]
    if len(rest) == 1:
        return top5 + rest, []
    other_vals = {y: 0 for y in years}
    for _name, vals in rest:
        for y in years:
            other_vals[y] += vals.get(y, 0)
    visible = top5 + [(f"Other ({len(rest)} items)", other_vals)]
    return visible, rest


def _category_total(grouped: dict, years: list[int], category: str) -> dict:
    """Return {year: total} for a category, preferring the stored Total row if present."""
    totals = {}
    for y in years:
        total, _ = _sum_category(grouped, y, category)
        totals[y] = total
    return totals


def _has_any_nonzero(values_by_year: dict) -> bool:
    return any(v != 0 for v in values_by_year.values())


def build_is_sections(db_path: str, idcode: str, years: list[int],
                      table: str = "financial_data") -> list[dict]:
    """Build a structured Income Statement as a list of section dicts.

    Each section dict has the shape:
        {
            "label": str,
            "kind": "section_with_detail" | "derived_total" | "final_total",
            "total": {year: value, ...},
            "detail": [(name, {year: value, ...}), ...],
            "rolled_up": [(name, {year: value, ...}), ...],  # OpEx only when >5 items
        }

    Values are raw GEL (not thousands). Detail items are sorted by absolute
    magnitude across years (largest first). The Operating Expenses section
    uses a Top-5 + Other rollup; the items that were aggregated into "Other"
    are also exposed in the `rolled_up` key (sorted by magnitude descending).
    All other sections have `rolled_up=[]`.

    Optional finance/other sections are omitted entirely when every year's
    total is zero, as is the trailing Other Comprehensive Income / Total
    Comprehensive Income block (shown for any filer that reports a non-zero OCI
    movement, sourced from the IS_OCI category, the "other comprehensive" line
    misfiled under IS_NetProfit, or — for override-corrected filers only —
    derived as stored TCI minus Net Profit; see the block below for the rules).
    """
    if not years:
        return []

    rows = get_financial_rows(db_path, idcode, years, section_prefix="IS", table=table)
    grouped = _group_rows(rows)

    # Sprint 5 SSOT — every profitability subtotal below (Revenue, COGS, Gross
    # Profit, OpEx, Other-Operating-Income lift, EBITDA, D&A, EBIT, PBT, Tax,
    # Net Profit) is sourced from the canonical function shared with the
    # Screener / metrics_panel builder. Only the per-section DETAIL lists are
    # assembled locally (display concern).
    prof = {y: compute_profitability(grouped, y, idcode=idcode) for y in years}

    sections: list[dict] = []

    # Total Revenue — income-role line with its detail breakdown (total first,
    # component line items indented beneath the bold Revenue total).
    revenue_total = {y: prof[y].revenue for y in years}
    revenue_detail_raw = _collect_detail_items(grouped, years, "IS_Revenue",
                                               exclude_section_total=True)
    revenue_detail_raw = _add_implied_other(revenue_detail_raw, revenue_total, years)
    revenue_detail = _sort_by_magnitude(revenue_detail_raw)
    sections.append({
        "label": "Total Revenue",
        "kind": "section_with_detail",
        "total": revenue_total,
        "detail": revenue_detail,
        "rolled_up": [],
        "bar": "income",
    })

    # Total COGS — cost-role total; total first, details beneath.
    cogs_total = {y: prof[y].cogs for y in years}
    cogs_detail_raw = _collect_detail_items(grouped, years, "IS_COGS",
                                            exclude_section_total=True)
    cogs_detail_raw = _add_implied_other(cogs_detail_raw, cogs_total, years)
    cogs_detail = _sort_by_magnitude(cogs_detail_raw)
    sections.append({
        "label": "Total COGS",
        "kind": "section_with_detail",
        "total": cogs_total,
        "detail": cogs_detail,
        "rolled_up": [],
        "bar": "cost",
    })

    # Gross Profit (derived) — canonical: Revenue + COGS; stored IS_GrossProfit ignored.
    gross_profit = {y: prof[y].gross_profit for y in years}
    sections.append({
        "label": "Gross Profit",
        "kind": "derived_total",
        "total": gross_profit,
        "detail": [],
        "rolled_up": [],
        "bar": "income",
    })

    # Gross Margin — decimal (0.30 = 30%), formatted as % at render time.
    def _safe_margin(numer: dict, denom: dict) -> dict:
        out: dict = {}
        for y in years:
            d = denom.get(y, 0)
            out[y] = (numer.get(y, 0) / d) if d else 0
        return out

    sections.append({
        "label": "Gross Margin",
        "kind": "margin",
        "total": _safe_margin(gross_profit, revenue_total),
        "detail": [],
        "rolled_up": [],
    })

    # Other Operating Income — the operating subset of IS_OtherIncome (name
    # contains "operating income") PLUS any "Other operating income" the filer
    # netted inside IS_OpEx, which compute_profitability lifts out (see
    # _opex_operating_income_items). Operating items lift EBITDA; the
    # non-operating remainder (FX, dividends, disposal gains, ...) stays below
    # EBIT.
    #
    # Displayed ABOVE Operating Expenses so the reader sees the full operating
    # income base (Revenue + other operating income) before the cost lines that
    # net against it — the same order an analyst EBITDA bridge uses. Placement
    # and the opex/other-income regrouping are DISPLAY concerns only: the lift is
    # EBITDA-neutral (compute_profitability), so no subtotal changes.
    other_inc_all = _collect_detail_items(grouped, years, "IS_OtherIncome")
    operating_other = [
        (name, vals) for name, vals in other_inc_all
        if "operating income" in name.lower()
    ]
    non_operating_other = [
        (name, vals) for name, vals in other_inc_all
        if "operating income" not in name.lower()
    ]
    # "Other operating income" lines lifted out of IS_OpEx, assembled per year
    # into {year: value} dicts so they render like any other detail row.
    ooi_from_opex: dict[str, dict] = {}
    for y in years:
        for name, val in _opex_operating_income_items(grouped, y):
            ooi_from_opex.setdefault(name, {yy: 0 for yy in years})[y] = val
    operating_other_from_opex = [(name, vals) for name, vals in ooi_from_opex.items()]
    lifted_opex_names = set(ooi_from_opex)

    operating_other_total = {y: prof[y].operating_other_income for y in years}
    # Emit only if there's any non-zero year (avoid an empty row on the IS view).
    if _has_any_nonzero(operating_other_total):
        sections.append({
            "label": "Other Operating Income",
            "kind": "section_with_detail",
            "total": operating_other_total,
            "detail": _sort_by_magnitude(operating_other + operating_other_from_opex),
            "rolled_up": [],
        })

    # Non-financial asset impairment (PP&E / intangibles / goodwill) that
    # compute_profitability lifted OUT of EBITDA — assembled per year from the
    # years where it was actually lifted (prof[y].impairment != 0). Rendered as
    # its own line below D&A; removed from the OpEx detail below so Operating
    # Expenses reads as pure cost and reconciles to the bold total (prof.opex,
    # already net of it).
    impairment_detail_map: dict[str, dict] = {}
    for y in years:
        if prof[y].impairment != 0:
            for name, val in _opex_nonfinancial_impairment_items(grouped, y):
                impairment_detail_map.setdefault(name, {yy: 0 for yy in years})[y] = val
    lifted_impairment_names = set(impairment_detail_map)

    # Total Operating Expenses (Top-5 + Other with rolled_up preserved) — pure
    # operating cost. Any "operating income" line lifted into Other Operating
    # Income above is excluded from the detail so it is not shown twice; the bold
    # total (prof.opex) is already net of it.
    opex_total = {y: prof[y].opex for y in years}
    opex_all = _collect_detail_items(grouped, years, "IS_OpEx")
    opex_expense_only = []
    for name, vals in opex_all:
        if name in lifted_opex_names:
            continue
        if name in lifted_impairment_names:
            # Drop the amount only in the years it was lifted below D&A; keep any
            # non-lifted year's value in OpEx (mixed roll-up / components years).
            vals = {y: (0 if prof[y].impairment != 0 else vals.get(y, 0)) for y in years}
            if not any(vals.values()):
                continue
        opex_expense_only.append((name, vals))
    opex_detail, opex_rolled_up = _top5_with_other_split(opex_expense_only, years)
    sections.append({
        "label": "Total Operating Expenses",
        "kind": "section_with_detail",
        "total": opex_total,
        "detail": opex_detail,
        "rolled_up": opex_rolled_up,
        "bar": "cost",
    })

    # EBITDA = Gross + Operating-OpEx + Other Operating Income (canonical).
    ebitda = {y: prof[y].ebitda for y in years}
    sections.append({
        "label": "EBITDA",
        "kind": "derived_total",
        "total": ebitda,
        "detail": [],
        "rolled_up": [],
        "bar": "total",
    })

    sections.append({
        "label": "EBITDA Margin",
        "kind": "margin",
        "total": _safe_margin(ebitda, revenue_total),
        "detail": [],
        "rolled_up": [],
    })

    # Total D&A
    da_total = {y: prof[y].da for y in years}
    da_detail = _sort_by_magnitude(
        _collect_detail_items(grouped, years, "IS_DA")
    )
    sections.append({
        "label": "Total D&A",
        "kind": "section_with_detail",
        "total": da_total,
        "detail": da_detail,
        "rolled_up": [],
    })

    # Impairment (non-financial) — a non-cash write-down of PP&E / intangibles /
    # goodwill, lifted out of EBITDA but retained in EBIT (like D&A). Emitted only
    # when a year actually carried a lifted impairment.
    impairment_total = {y: prof[y].impairment for y in years}
    if _has_any_nonzero(impairment_total):
        sections.append({
            "label": "Impairment (non-financial)",
            "kind": "section_with_detail",
            "total": impairment_total,
            "detail": _sort_by_magnitude(list(impairment_detail_map.items())),
            "rolled_up": [],
            "bar": "cost",
        })

    # EBIT (derived)
    ebit = {y: prof[y].ebit for y in years}
    sections.append({
        "label": "EBIT / Operating Income",
        "kind": "derived_total",
        "total": ebit,
        "detail": [],
        "rolled_up": [],
        "bar": "total",
    })

    # Optional finance/other sections — include only if any year is non-zero.
    # IS_OtherIncome is handled specially: the "operating income" subset has
    # already been lifted above EBITDA (see the split above), so here we emit
    # only the non-operating remainder (FX, dividends, disposal gains, etc.).
    non_op_other_total = {y: prof[y].non_operating_other_income for y in years}
    optional_specs = [
        ("Total Interest Income",
         {y: prof[y].interest_income for y in years}, None),
        ("Total Interest Expense",
         {y: prof[y].interest_expense for y in years}, None),
        ("Total Fee & Commission Income",
         {y: prof[y].fee_income for y in years}, None),
        # IS_OtherIncome: pre-computed non-operating subset (operating part is
        # already above EBITDA). Use the precomputed total + detail.
        ("Total Other Income", non_op_other_total, non_operating_other),
        ("Total Other Expense",
         {y: prof[y].other_expense for y in years}, None),
    ]
    optional_detail_categories = {
        "Total Interest Income": "IS_InterestIncome",
        "Total Interest Expense": "IS_InterestExpense",
        "Total Fee & Commission Income": "IS_FeeIncome",
        "Total Other Expense": "IS_OtherExpense",
    }
    for label, total, preset_detail in optional_specs:
        if preset_detail is None:
            detail = _sort_by_magnitude(
                _collect_detail_items(grouped, years,
                                      optional_detail_categories[label],
                                      exclude_section_total=True)
            )
        else:
            detail = _sort_by_magnitude(preset_detail or [])
        if not _has_any_nonzero(total):
            continue
        sections.append({
            "label": label,
            "kind": "section_with_detail",
            "total": total,
            "detail": detail,
            "rolled_up": [],
        })

    # Profit Before Tax (derived, canonical)
    pbt = {y: prof[y].pbt for y in years}
    sections.append({
        "label": "Profit Before Tax",
        "kind": "derived_total",
        "total": pbt,
        "detail": [],
        "rolled_up": [],
        "bar": "total",
    })

    # Total Income Tax
    tax_total = {y: prof[y].tax for y in years}
    tax_detail = _sort_by_magnitude(
        _collect_detail_items(grouped, years, "IS_Tax")
    )
    sections.append({
        "label": "Total Income Tax",
        "kind": "section_with_detail",
        "total": tax_total,
        "detail": tax_detail,
        "rolled_up": [],
    })

    # Net Profit — canonical: stored IS_NetProfit row matched by strict
    # name/exclude lists, else PBT + Tax fallback (computed in
    # compute_profitability; net_profit_source records which branch fired).
    np_by_year = {y: prof[y].net_profit for y in years}
    np_source_by_year = {y: prof[y].net_profit_source for y in years}
    sections.append({
        "label": "Net Profit / (Loss)",
        "kind": "final_total",
        "total": np_by_year,
        "detail": [],
        "rolled_up": [],
        "bar": "net",
    })

    sections.append({
        "label": "Net Margin",
        "kind": "margin",
        "total": _safe_margin(np_by_year, revenue_total),
        "detail": [],
        "rolled_up": [],
    })

    # Other Comprehensive Income + Total Comprehensive Income. The reportal
    # export files OCI in three mutually-exclusive shapes; we source it from
    # whichever is present so the reconciliation block renders for every filer
    # that actually reports OCI (not just the ~169 with a clean IS_OCI category):
    #
    #   1. IS_OCI category — the granular "Other items of OCI (with/without
    #      reclassification option)" components. PREFERRED when present.
    #   2. IS_NetProfit "Total other comprehensive (loss) income" line — the OCI
    #      movement misfiled into the net-profit block (~1,346 co-yrs). 166 of the
    #      169 IS_OCI filers ALSO carry this line, so we take source (1) OR (2),
    #      never both, or OCI double-counts. (Note the line name contains "Total",
    #      so _collect_detail_items would drop it — collected explicitly below.)
    #   3. Neither — the OCI is folded into a mislabeled "Discontinued Operations"
    #      line and only the TCI grand-total survives (Gepha). Recoverable only
    #      when Net Profit is already an analyst/PDF override we trust: derive
    #      OCI = stored TCI − Net Profit. Gated to net_profit_source == "override"
    #      (and a unit-sane TCI-row pick) so the ~27 filers whose stored TCI row is
    #      mis-scaled ×1000 can never produce a bogus plug.
    #
    # NP excludes comprehensive-income rows by name (NET_PROFIT_EXCLUDE_SUBSTRINGS),
    # so TCI is shown as Net Profit + OCI — internally consistent with the
    # canonical Net Profit, and ties to the filer's stored TCI row for ~95%.
    def _collect_np_oci() -> list[tuple[str, dict]]:
        """OCI movement lines misfiled under IS_NetProfit (name has 'other
        comprehensive'); unlike _collect_detail_items this keeps 'Total'-named
        rows, since the line is literally 'Total other comprehensive ...'."""
        by_item: dict = {}
        order: list = []
        for y in years:
            for t in grouped.get((y, "IS_NetProfit"), []):
                name, value = t[0], t[1]
                if "other comprehensive" not in name.lower():
                    continue
                if name not in by_item:
                    by_item[name] = {yr: 0 for yr in years}
                    order.append(name)
                by_item[name][y] = value
        return [(n, by_item[n]) for n in order if any(v != 0 for v in by_item[n].values())]

    isoci_detail = _collect_detail_items(grouped, years, "IS_OCI")
    oci_detail = _sort_by_magnitude(isoci_detail if isoci_detail else _collect_np_oci())
    oci_total = {y: sum(vals.get(y, 0) for _, vals in oci_detail) for y in years}

    # Fallback (3): override-gated TCI-minus-NP plug for the mislabel class.
    if not _has_any_nonzero(oci_total):
        derived: dict = {}
        for y in years:
            if np_source_by_year.get(y) != "override":
                continue
            np_y = np_by_year.get(y, 0)
            tci_candidates = [
                t[1] for t in grouped.get((y, "IS_NetProfit"), [])
                if "comprehensive" in t[0].lower()
                and "other" not in t[0].lower()
                and t[1] != 0
            ]
            if not tci_candidates:
                continue
            # Pick the TCI row closest in magnitude to NP → rejects ×1000-quirk rows.
            tci_val = min(tci_candidates, key=lambda v: abs(abs(v) - abs(np_y)))
            d = tci_val - np_y
            if d != 0:
                derived[y] = d
        if derived:
            oci_detail = [("Other comprehensive income / (loss)",
                           {y: derived.get(y, 0) for y in years})]
            oci_total = {y: derived.get(y, 0) for y in years}

    if _has_any_nonzero(oci_total):
        sections.append({
            "label": "Other Comprehensive Income",
            "kind": "section_with_detail",
            "total": oci_total,
            "detail": oci_detail,
            "rolled_up": [],
        })
        sections.append({
            "label": "Total Comprehensive Income",
            "kind": "final_total",
            "total": {y: np_by_year.get(y, 0) + oci_total.get(y, 0) for y in years},
            "detail": [],
            "rolled_up": [],
            "bar": "net",
        })

    return sections




# ---------------------------------------------------------------------------
# Bank IS framework
# ---------------------------------------------------------------------------

# Within IS_OpEx, items containing these substrings are LOAN-LOSS PROVISIONS
# (financial/credit-asset impairment) — they belong above Net Interest Income
# after Provisions (in "Cost of risk"), not in operating expenses. Beyond the
# generic "financial assets" phrase, reportal.ge filings also carry narrower
# credit-exposure impairment lines by name — e.g. "Impairment of receivables
# from financial lease" / "Impairment of amounts due from banks" — that are
# economically the same credit-loss provision (confirmed against Bank of
# Georgia's audited FY2017-2019 P&L: these lines sit in the filing's "Cost of
# risk" grouping, not operating expenses).
_BANK_LOAN_LOSS_INCLUDE = "impairment"
_BANK_CREDIT_IMPAIRMENT_SUBSTRINGS = (
    "financial assets",
    "financial lease",
    "amounts due from banks",
    "investment securities",
    "due from credit institutions",
)
# Non-financial / operating impairments that must stay in OpEx even though
# they contain "impairment" (PP&E, intangibles, trade receivables, repossessed
# collateral, or ambiguous "other assets" note lines).
_BANK_LOAN_LOSS_EXCLUDE_SUBSTRINGS = (
    "non-financial",
    "non- financial",
    "non financial",
    "trade receivables",
    "repossessed collateral",
    "property, plant",
    "tangible",  # also excludes "intangible"
    "other assets",
)

# Within IS_OpEx, this exact substring marks the fee/commission expense leg
# (belongs in Net Fee & Commission Income, not OpEx).
_BANK_FEE_EXPENSE_SUBSTR = "fee and commission expense"

# --- IS_OtherIncome classification (bank net-presentation layout) ----------
# IS_OtherIncome for banks is a grab-bag. We split it three ways:
#   1. FX           -> "Net foreign currency gain / (loss)"  (operating)
#   2. associates   -> "Profit / (loss) from associates"     (below OpInc)
#   3. net-other    -> "Net other income"                    (operating)
# plus a guarded ARTEFACT bucket that is kept OUT of the operating subtotals
# (see _BANK_OTHER_INCOME_ARTEFACT_NAMES below).
_BANK_FX_SUBSTRINGS = (
    "trading in foreign currencies",
    "foreign exchange",
    "financial derivatives",
)
_BANK_ASSOCIATE_SUBSTRINGS = (
    "share of result",   # "Share of result of associates" / "Share of results of joint ventures"
)
# Large, ambiguous IS_OtherIncome lines that reportal carries gross — they are
# the income produced by interest-earning assets and are ALREADY captured inside
# the stored "Interest income from:" TOTAL row (IS_InterestIncome). Including
# them in "Net other income" double-counts and massively overstates Revenue.
# For Bank of Georgia FY2024 the bottom-up PBT ties to the stored PBT row to the
# GEL only when these two are excluded (verified: 2,127,472,000 == stored).
# Matched case-insensitively, EXACT name (after lower/strip) to avoid catching
# legitimate "disposals of investment securities" gain lines.
_BANK_OTHER_INCOME_ARTEFACT_NAMES = (
    "investment securities",
    "other assets",
)


def _classify_bank_other_income(name: str) -> str:
    """Classify an IS_OtherIncome detail item.

    Returns one of: "fx", "associate", "artefact", "net_other".
    """
    n = name.lower().strip()
    if n in _BANK_OTHER_INCOME_ARTEFACT_NAMES:
        return "artefact"
    if any(s in n for s in _BANK_ASSOCIATE_SUBSTRINGS):
        return "associate"
    if any(s in n for s in _BANK_FX_SUBSTRINGS):
        return "fx"
    return "net_other"


def _partition_bank_other_income(
    details: list[tuple[str, dict]],
) -> tuple[list, list, list, list]:
    """Partition IS_OtherIncome detail items into (fx, associate, net_other, artefact).

    Pure function — easy to unit-test against fixture rows.
    """
    fx: list = []
    associate: list = []
    net_other: list = []
    artefact: list = []
    bucket = {"fx": fx, "associate": associate, "net_other": net_other, "artefact": artefact}
    for name, vals in details:
        bucket[_classify_bank_other_income(name)].append((name, vals))
    return fx, associate, net_other, artefact


def _is_loan_loss_item(name: str) -> bool:
    """True if an IS_OpEx detail item is a loan-loss / credit-asset impairment."""
    n = name.lower()
    if _BANK_LOAN_LOSS_INCLUDE not in n:
        return False
    if any(exc in n for exc in _BANK_LOAN_LOSS_EXCLUDE_SUBSTRINGS):
        return False
    return any(inc in n for inc in _BANK_CREDIT_IMPAIRMENT_SUBSTRINGS)


def _is_fee_expense_item(name: str) -> bool:
    """True if an IS_OpEx detail item is the fee & commission expense leg."""
    return _BANK_FEE_EXPENSE_SUBSTR in name.lower()


def _partition_bank_opex(
    details: list[tuple[str, dict]],
) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]], list[tuple[str, dict]]]:
    """Partition IS_OpEx detail items into (loan_loss, fee_expense, opex_rest).

    Pure function — easy to unit-test against fixture rows.
    """
    loan_loss: list = []
    fee_exp: list = []
    rest: list = []
    for name, vals in details:
        if _is_loan_loss_item(name):
            loan_loss.append((name, vals))
        elif _is_fee_expense_item(name):
            fee_exp.append((name, vals))
        else:
            rest.append((name, vals))
    return loan_loss, fee_exp, rest


def _sum_year_dicts(*year_dicts: dict) -> dict:
    """Element-wise sum of {year: value} dicts. Missing keys treated as 0."""
    out: dict = {}
    for d in year_dicts:
        for y, v in d.items():
            out[y] = out.get(y, 0) + v
    return out


def _sum_detail_totals(details: list[tuple[str, dict]], years: list[int]) -> dict:
    """Sum every detail item's per-year values into {year: total}."""
    out = {y: 0 for y in years}
    for _name, vals in details:
        for y in years:
            out[y] += vals.get(y, 0)
    return out


# Canonical Net Profit picker for banks: prefer "Profit/(loss)" stored row,
# exclude PBT/comprehensive/owners/etc. (same shape used by the screener).
_BANK_NP_PREFERRED = (
    "Profit/(loss)",
    "Profit / (loss)",
    "Profit for the year",
    "Net profit",
    "Net Profit",
)
_BANK_NP_EXCLUDES = (
    "before tax",
    "comprehensive",
    "owners",
    "non-controlling",
    "discontinued",
    "held for sale",
)


def _classify_bank_nonrecurring(name: str) -> bool:
    """True if an IS_OtherIncome/Expense detail item is a NON-RECURRING /
    one-off item (restructuring, one-off gains/losses, impairment of goodwill,
    legal settlements, etc.).

    reportal.ge bank filings almost never carry an explicit non-recurring line,
    so this returns False for everything by default; it exists so the BOG ladder
    can light up its non-recurring / one-off rungs if a bank ever reports them.
    """
    n = name.lower()
    return any(
        s in n
        for s in (
            "non-recurring",
            "non recurring",
            "one-off",
            "one off",
            "restructuring",
        )
    )


def build_bank_is_sections(db_path: str, idcode: str, years: list[int],
                           table: str = "financial_data") -> list[dict]:
    """Build a bank Income Statement in the Lion Finance / Bank of Georgia
    "Income statement highlights" layout as ordered section dicts.

    Reading order is INPUTS FIRST then the SUBTOTAL BELOW (``details_first``):
    each subtotal is preceded by the faint detail rows that feed it. The four
    role-tagged BARs (full-width colored rows) are Net interest income (income),
    Operating income (total), Profit (net), and — only when present — Profit
    adjusted for one-off items (adjusted/orange). The intermediate subtotals are
    bold-only. Every detail row is a faint ``emphasis="line"`` line.

    Layout (top -> bottom; **BAR**/**bold** = subtotal):

        Interest income                              (detail)
        Interest expense                             (detail, negative)
        **Net interest income** (BAR · income)       = II + IE
        Net fee and commission income                (line)
        Net foreign currency gain / (loss)           (line; kept SEPARATE)
        Net other income                             (line)
        **Operating income** (BAR · total)           = NII + fee + FX + other
        ── staff / admin / D&A breakdown ──          (faint detail)
        **Operating expenses** (bold; negative)      = staff + admin + D&A
        Profit / (loss) from associates              (line; OMITTED if absent)
        **Operating income before cost of risk**     = OpInc + OpEx + assoc
        Cost of risk                                 (line, negative)
        **Net operating income before non-recurring items**  = prev + CoR
        Net non-recurring items                      (line; OMITTED if none)
        **Profit before income tax**                 (stored PBT preferred)
        Income tax expense                           (detail, negative)
        **Profit adjusted for one-off items** (BAR · adjusted) = PBT + tax
                                                     (rendered ONLY if one-offs exist)
        One off items                                (line; OMITTED if none)
        **Profit** (BAR · net)                       (final stored net profit)
        Net profit margin                            (italic %)

    ROBUSTNESS / "be smart":
      - Rows with NO data (associates, non-recurring, one-off items) are OMITTED
        entirely rather than shown as empty/zero rows.
      - When there are NO non-recurring items (the common reportal.ge case) the
        ladder collapses: "Net operating income before non-recurring items" ==
        "Profit before income tax" — only the single ``Profit before income tax``
        subtotal is rendered (no duplicate adjacent subtotal). Likewise when
        there are NO one-off items, "Profit adjusted for one-off items" == the
        final "Profit", so the adjusted row is skipped and only ``Profit`` shows.
      - Any IS item that doesn't map to a known bucket is still captured: the
        "Net other income" line absorbs the unclassified IS_OtherIncome
        remainder, so NOTHING is dropped and the bottom line still ties to the
        bank's stored reported net profit.
      - If bottom-up PBT diverges from the stored PBT for a company (data quirk),
        the STORED subtotals are preferred so the statement still ties out.

    Sections whose total is zero in every year are omitted (matching the
    non-financial builder's convention).

    DATA-QUALITY NOTE: ``IS_OtherIncome`` for the big banks carries two large,
    ambiguous gross lines — "Investment Securities" and "Other Assets" — that
    are the income of interest-earning assets, already captured inside the
    stored "Interest income from:" total. They are classified as ARTEFACTS and
    excluded from Operating income (otherwise it is overstated by ~₾0.9bn for
    BoG). With them excluded, the bottom-up PBT ties to the bank's stored PBT
    row to the GEL.
    """
    if not years:
        return []

    rows = get_financial_rows(db_path, idcode, years, section_prefix="IS", table=table)
    grouped = _group_rows(rows)
    sections: list[dict] = []

    def _safe_margin(numer: dict, denom: dict) -> dict:
        out: dict = {}
        for y in years:
            d = denom.get(y, 0)
            out[y] = (numer.get(y, 0) / d) if d else 0
        return out

    def emit(label, kind, total, detail=None, rolled_up=None, emphasis=None,
             bar=None, details_first=False, force=False):
        # OMIT all-zero sections (rows with no data) unless explicitly forced.
        if not force and not _has_any_nonzero(total):
            return
        sec = {
            "label": label,
            "kind": kind,
            "total": total,
            "detail": detail or [],
            "rolled_up": rolled_up or [],
        }
        if emphasis is not None:
            sec["emphasis"] = emphasis
        if bar is not None:
            sec["bar"] = bar
        if details_first:
            sec["details_first"] = True
        sections.append(sec)

    # ---- Interest income / expense (details) + Net interest income (BAR) ----
    ii_total = _category_total(grouped, years, "IS_InterestIncome")
    ie_total = _category_total(grouped, years, "IS_InterestExpense")
    nii_total = _sum_year_dicts(ii_total, ie_total)
    nii_detail: list[tuple[str, dict]] = []
    if _has_any_nonzero(ii_total):
        nii_detail.append(("Interest income", dict(ii_total)))
    if _has_any_nonzero(ie_total):
        nii_detail.append(("Interest expense", dict(ie_total)))

    # ---- Partition IS_OpEx into (loan_loss, fee_expense, opex_rest) ----
    opex_all = _collect_detail_items(grouped, years, "IS_OpEx")
    loan_loss_items, fee_exp_items, opex_rest_items = _partition_bank_opex(opex_all)

    # ---- Net fee & commission income = Fee income + fee-expense leg ----
    fi_total = _category_total(grouped, years, "IS_FeeIncome")
    fee_exp_total = _sum_detail_totals(fee_exp_items, years)
    net_fee_total = _sum_year_dicts(fi_total, fee_exp_total)

    # ---- Classify IS_OtherIncome (FX / associates / net-other / artefact) ----
    other_inc_all = _collect_detail_items(grouped, years, "IS_OtherIncome")
    fx_items, assoc_items, net_other_items, artefact_items = (
        _partition_bank_other_income(other_inc_all)
    )
    # Split the net-other remainder into recurring vs non-recurring/one-off so
    # the BOG one-off rungs can light up when a bank actually reports them.
    nonrec_items = [kv for kv in net_other_items if _classify_bank_nonrecurring(kv[0])]
    net_other_recurring = [kv for kv in net_other_items if not _classify_bank_nonrecurring(kv[0])]
    fx_total = _sum_detail_totals(fx_items, years)
    assoc_total = _sum_detail_totals(assoc_items, years)
    net_other_total = _sum_detail_totals(net_other_recurring, years)
    nonrec_total = _sum_detail_totals(nonrec_items, years)

    # ===== Income block: subtotal FIRST, then its indented detail rows below
    # (matches the platform's downloaded-Excel layout). =====
    emit("Net interest income", "section_with_detail", nii_total,
         nii_detail, bar="income", emphasis="line")

    # ---- The remaining three income lines (faint) ----
    emit("Net fee and commission income", "section_with_detail", net_fee_total,
         bar="income")
    # FX kept SEPARATE from net-other on purpose.
    emit("Net foreign currency gain / (loss)", "section_with_detail", fx_total,
         _sort_by_magnitude(fx_items), bar="income")
    # Combine the two investment-gain detail lines into one (revaluation/disposal
    # of investment property + disposals of investment securities), per the
    # requested bank-IS layout.
    _inv = [(n, v) for n, v in net_other_recurring
            if "disposal" in n.lower() and "investment" in n.lower()]
    if len(_inv) >= 2:
        _rest = [(n, v) for n, v in net_other_recurring
                 if not ("disposal" in n.lower() and "investment" in n.lower())]
        net_other_display = _rest + [
            ("Net gains/(losses) on investments & disposals",
             _sum_detail_totals(_inv, years))
        ]
    else:
        net_other_display = net_other_recurring
    emit("Net other income", "section_with_detail", net_other_total,
         _sort_by_magnitude(net_other_display), bar="income")

    # ---- Operating income (BAR · total) = sum of the income lines ----
    op_income_total = _sum_year_dicts(nii_total, net_fee_total, fx_total, net_other_total)
    emit("Operating income", "derived_total", op_income_total, bar="total")

    # ---- Operating expenses (bold · cost) with staff/admin/D&A detail ABOVE ----
    da_detail = _collect_detail_items(grouped, years, "IS_DA")
    opex_combined = opex_rest_items + da_detail
    if len(opex_combined) <= 8:
        opex_visible, opex_rolled = _sort_by_magnitude(opex_combined), []
    else:
        opex_visible, opex_rolled = _top5_with_other_split(opex_combined, years)
    opex_total = _sum_detail_totals(opex_combined, years)
    emit("Operating expenses", "section_with_detail", opex_total,
         opex_visible, opex_rolled)

    # ---- Profit / (loss) from associates (faint; OMITTED if absent) ----
    emit("Profit / (loss) from associates", "section_with_detail",
         assoc_total, _sort_by_magnitude(assoc_items), emphasis="line")

    # ---- Operating income before cost of risk (bold) = OpInc + OpEx + assoc ----
    op_income_before_cor = _sum_year_dicts(op_income_total, opex_total, assoc_total)
    emit("Operating income before cost of risk", "derived_total", op_income_before_cor)

    # ---- Cost of risk (faint, negative) = loan-loss / financial-asset impairment ----
    # Banks split this into "Impairment ...of financial assets" + "Impairment of
    # other financial assets"; combine into a SINGLE impairment detail line. The
    # combined value equals the Cost of risk total, so the duplicate-suppression
    # in sections_to_dataframe collapses it and Cost of risk reads as one clean line.
    cor_total = _sum_detail_totals(loan_loss_items, years)
    cor_detail = (
        [("Impairment of financial assets", cor_total)] if loan_loss_items else []
    )
    emit("Cost of risk", "section_with_detail", cor_total, cor_detail, emphasis="line")

    # ---- Net operating income before non-recurring items (bold) = prev + CoR ----
    net_op_income = _sum_year_dicts(op_income_before_cor, cor_total)

    # ---- Profit before income tax (bold; STORED preferred for tie-out) ----
    computed_pbt = _sum_year_dicts(net_op_income, nonrec_total)
    _bank_pbt_excludes = (
        "comprehensive", "attributable", "non-controlling", "owners",
        "net assets", "discontinued", "held for sale",
    )
    pbt_total: dict = {}
    for y in years:
        np_rows_pbt = [(t[0], t[1]) for t in grouped.get((y, "IS_NetProfit"), [])]
        stored_pbt = _select_stored_row(np_rows_pbt, PBT_PREFERRED_NAMES, _bank_pbt_excludes)
        pbt_total[y] = stored_pbt if stored_pbt is not None else computed_pbt.get(y, 0)

    has_nonrecurring = _has_any_nonzero(nonrec_total)
    if has_nonrecurring:
        # Full ladder: distinct "Net operating income before non-recurring items"
        # subtotal, then the non-recurring line, then PBT.
        emit("Net operating income before non-recurring items", "derived_total",
             net_op_income)
        emit("Net non-recurring items", "section_with_detail", nonrec_total,
             _sort_by_magnitude(nonrec_items), emphasis="line")
        emit("Profit before income tax", "derived_total", pbt_total)
    else:
        # COLLAPSE: with no non-recurring items, "Net operating income before
        # non-recurring items" == "Profit before income tax". Render a single
        # subtotal (avoid duplicate adjacent subtotals with identical values).
        emit("Profit before income tax", "derived_total", pbt_total)

    # ---- Income tax expense (faint detail, negative) ----
    tax_total = _category_total(grouped, years, "IS_Tax")
    tax_detail = _sort_by_magnitude(_collect_detail_items(grouped, years, "IS_Tax"))
    emit("Income tax expense", "section_with_detail",
         tax_total, tax_detail, emphasis="line")

    # ---- Final Profit (BAR · net; STORED net profit preferred) ----
    np_total: dict = {}
    for y in years:
        np_rows = [(t[0], t[1]) for t in grouped.get((y, "IS_NetProfit"), [])]
        picked = _select_stored_row(np_rows, _BANK_NP_PREFERRED, _BANK_NP_EXCLUDES)
        if picked is None:
            picked = pbt_total.get(y, 0) + tax_total.get(y, 0)
        np_total[y] = picked

    # ---- Profit adjusted for one-off items (BAR · adjusted) = PBT + tax ----
    # One-off items live in IS_OtherExpense lines flagged non-recurring; absent
    # for virtually all reportal.ge banks. Render the adjusted subtotal + the
    # one-off line ONLY when such items exist; otherwise "Profit adjusted for
    # one-off items" == "Profit", so we collapse to the single "Profit" bar.
    other_exp_all = _collect_detail_items(grouped, years, "IS_OtherExpense")
    oneoff_items = [kv for kv in other_exp_all if _classify_bank_nonrecurring(kv[0])]
    oneoff_total = _sum_detail_totals(oneoff_items, years)
    if _has_any_nonzero(oneoff_total):
        profit_adj = _sum_year_dicts(pbt_total, tax_total)
        emit("Profit adjusted for one-off items", "derived_total", profit_adj,
             bar="adjusted")
        emit("One off items", "section_with_detail", oneoff_total,
             _sort_by_magnitude(oneoff_items), emphasis="line")

    emit("Profit", "final_total", np_total, bar="net")

    # ---- Net profit margin (italic %) = Profit / Operating income ----
    emit("Net profit margin", "margin", _safe_margin(np_total, op_income_total))

    return sections


def bank_operating_revenue(db_path: str, idcode: str, years) -> dict[int, float]:
    """Return ``{year: Operating income}`` for a BANK — its top-line revenue analog.

    A bank's "Operating income" (Net interest income + net fee & commission
    income + FX + other operating income) is the revenue equivalent for a
    financial institution, since the generic ``IS_Revenue`` is null for banks.
    Used to give banks a meaningful Revenue in the metrics panel and the Sector/
    Compare aggregates (otherwise ΣRevenue is undercounted and aggregate margins
    blow up). Single source of truth so the panel builder, the recompute path,
    and the parity tests all agree.

    Returns only non-zero years; ``{}`` when the bank IS has no Operating-income
    section (so callers fall back to the generic Revenue).
    """
    sections = build_bank_is_sections(db_path, idcode, list(years))
    for s in sections:
        if s.get("label") == "Operating income":
            return {
                int(y): float(v or 0)
                for y, v in s.get("total", {}).items()
                if v
            }
    return {}
