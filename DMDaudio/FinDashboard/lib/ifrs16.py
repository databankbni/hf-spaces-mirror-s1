"""IFRS 16 lease-cost adjustment.

Under IFRS 16 (effective 2019 for most Georgian companies), operating-lease rent
moved from OpEx (Rental Expenses) to D&A (RoU asset depreciation) + Interest Expense
(lease liability interest). For lease-heavy businesses this inflates post-2019 EBITDA
and makes pre/post-2019 financials non-comparable.

This module estimates the annual implied lease cost from balance-sheet lease data,
splits it into a depreciation portion (above EBIT) and an interest portion (below
EBIT), and provides a reversal that re-classifies that cost back to OpEx as rent.

Estimation chain (per year):
  1. Right-of-Use Assets / assumed_term   (cleaner; rare in this dataset)
  2. Finance Lease Payable / assumed_term (fallback; widely available)
  3. None                                  (no adjustment possible)

All values returned in GEL (the unit used elsewhere in the codebase).
"""
from __future__ import annotations
import copy
from lib.data_loader import get_financial_rows

# IFRS 16 became effective for most Georgian companies for fiscal years
# beginning on/after 1 Jan 2019. Before that, operating-lease rent sat in OpEx
# already, so the lease-liability-based reversal must NOT fire pre-2019 (it
# would double-count rent that was never reclassified out of OpEx). A
# Right-of-Use asset, when present, is itself proof of post-adoption accounting
# and overrides this gate.
IFRS16_EFFECTIVE_YEAR = 2019

# Line-item names (already canonicalized by data_loader) to look up.
ROU_ASSET_NAME = "Right-of-Use Assets"
LEASE_PAYABLE_NAMES = ("Finance lease payable", "Finance Lease Liabilities", "Lease Liabilities")
RENTAL_EXPENSE_NAMES = ("Rental expenses",)


def _sum_by_year(rows: list[dict], name_set: set[str]) -> dict[int, float]:
    """Sum values across rows whose LineItemENG is in name_set, grouped by year."""
    out: dict[int, float] = {}
    for r in rows:
        if r["LineItemENG"] in name_set:
            out[r["FVYear"]] = out.get(r["FVYear"], 0.0) + (r["Value"] or 0.0)
    return out


def get_rou_assets_by_year(db_path: str, idcode: str, years: list[int],
                           table: str = "financial_data") -> dict[int, float]:
    bs_rows = get_financial_rows(db_path, idcode, years, section_prefix="BS_", table=table)
    return _sum_by_year(bs_rows, {ROU_ASSET_NAME})


def get_lease_payable_by_year(db_path: str, idcode: str, years: list[int],
                              table: str = "financial_data") -> dict[int, float]:
    bs_rows = get_financial_rows(db_path, idcode, years, section_prefix="BS_", table=table)
    return _sum_by_year(bs_rows, set(LEASE_PAYABLE_NAMES))


def get_rental_expense_by_year(db_path: str, idcode: str, years: list[int],
                               table: str = "financial_data") -> dict[int, float]:
    """Returns the magnitude (positive) of Rental Expenses per year."""
    is_rows = get_financial_rows(db_path, idcode, years, section_prefix="IS", table=table)
    raw = _sum_by_year(is_rows, set(RENTAL_EXPENSE_NAMES))
    return {y: abs(v) for y, v in raw.items()}


def compute_implied_lease_cost(
    db_path: str,
    idcode: str,
    years: list[int],
    assumed_term: float = 5.0,
    interest_rate: float = 0.06,
    table: str = "financial_data",
) -> dict[int, dict]:
    """Return {year: {...}} estimating annual rent equivalent of IFRS 16 leases.

    Each year dict contains:
      value:       float - total annual implied lease cost X (GEL, positive)
      dep_portion: float - depreciation portion D (GEL, positive). D = X - I.
      int_portion: float - interest portion I (GEL, positive). I = rate * base / 2.
      method:      str   - 'rou' | 'lease_liability' | 'none'
      base:        float - the BS balance used (RoU or Lease Payable; positive)

    Args:
      assumed_term:  Years used to amortize the BS lease balance into annual cost.
                     X = base / assumed_term. Default 5.
      interest_rate: Annual incremental borrowing rate used to estimate the
                     interest portion of the lease payment. Default 6%.
                     I ~= rate * base / 2 (mid-year average of declining liability).
                     When method is 'rou' we don't have a clean lease-liability
                     balance, so we apply the same fixed-rate proportion to the
                     RoU base; this is an acceptable approximation since the RoU
                     and lease liability are typically of similar magnitude.
    """
    if assumed_term <= 0:
        raise ValueError(f"assumed_term must be > 0, got {assumed_term}")
    if interest_rate < 0:
        raise ValueError(f"interest_rate must be >= 0, got {interest_rate}")

    rou = get_rou_assets_by_year(db_path, idcode, years, table=table)
    lease = get_lease_payable_by_year(db_path, idcode, years, table=table)

    out: dict[int, dict] = {}
    none_result = {
        "value": 0.0,
        "dep_portion": 0.0,
        "int_portion": 0.0,
        "method": "none",
        "base": 0.0,
    }
    for y in years:
        rou_val = rou.get(y, 0.0)
        lease_val = abs(lease.get(y, 0.0))
        if rou_val and rou_val != 0:
            # A Right-of-Use asset only exists under IFRS 16 (effective 2019),
            # so an RoU base is itself the signal that the year is post-adoption
            # — apply the reversal regardless of FVYear.
            base = rou_val
            method = "rou"
        elif lease_val and lease_val != 0:
            # Lease-liability fallback. IFRS 16 reclassified operating-lease rent
            # out of OpEx into D&A + interest starting 2019. BEFORE 2019, any
            # finance-lease rent was ALREADY booked in OpEx (rent line), so
            # reversing the lease-liability estimate back into OpEx would
            # DOUBLE-COUNT it. Gate the lease-liability path to FVYear >= 2019;
            # earlier years get no adjustment.
            if y < IFRS16_EFFECTIVE_YEAR:
                out[y] = dict(none_result)
                continue
            base = lease_val
            method = "lease_liability"
        else:
            out[y] = dict(none_result)
            continue
        x = base / assumed_term
        i = interest_rate * base / 2.0
        # Cap interest at total cost (defensive -- shouldn't happen with reasonable inputs)
        if i > x:
            i = x
        d = x - i
        out[y] = {
            "value": x,
            "dep_portion": d,
            "int_portion": i,
            "method": method,
            "base": base,
        }
    return out


def adjust_is_sections(sections: list, implied_costs: dict[int, dict]) -> list:
    """Apply full IFRS 16 reversal to a copy of IS sections.

    For each year y, with X = total cost, D = depreciation portion, I = interest portion:
      - OpEx total:              total - X  (more negative)
      - OpEx detail:             'Rental expenses' row gets -X baked in (or new row if missing)
      - D&A total:               total + D  (less negative -- only D moved out)
      - D&A detail:              'Depreciation and amortisation' row gets +D baked in
      - Interest Expense total:  total + I  (less negative -- interest portion moved out)
      - Interest Expense detail: 'Interest Expense' row gets +I baked in

    Then recompute derived totals:
      - EBITDA = GP + new_OpEx                       (drops by X)
      - EBIT   = EBITDA + new_D&A                    (drops by I)
      - PBT    = EBIT + (new Interest + others)      (unchanged: -I from EBIT, +I from Interest)
      - Net Profit = stored row (untouched)          (unchanged)

    Labels gain '(adj.)' suffix where values changed: OpEx, D&A, Interest Expense,
    EBITDA, EBIT. PBT and Net Profit keep their original labels (values unchanged).

    Does NOT mutate input sections; returns a deep copy.
    """
    adjusted = copy.deepcopy(sections)
    by_label = {s["label"]: s for s in adjusted}

    def x_of(y: int) -> float:
        return implied_costs.get(y, {"value": 0.0}).get("value", 0.0)

    def d_of(y: int) -> float:
        return implied_costs.get(y, {"dep_portion": 0.0}).get("dep_portion", 0.0)

    def i_of(y: int) -> float:
        return implied_costs.get(y, {"int_portion": 0.0}).get("int_portion", 0.0)

    # OpEx: total -= X. Bake -X into the existing "Rental expenses" detail row.
    opex = by_label.get("Total Operating Expenses")
    if opex:
        for y in opex["total"]:
            opex["total"][y] -= x_of(y)
        opex["detail"] = list(opex.get("detail", []))
        _bake_into_detail(opex["detail"], "Rental expenses", {y: -x_of(y) for y in opex["total"]})
        # Re-sort detail by absolute magnitude (largest first) since "Rental expenses" may have grown
        opex["detail"] = _resort_opex_detail(opex["detail"])
        opex["label"] = "Total Operating Expenses (adj.)"

    # D&A: total += D. Bake +D into the existing "Depreciation and amortisation" detail row.
    da = by_label.get("Total D&A")
    if da:
        for y in da["total"]:
            da["total"][y] += d_of(y)
        da["detail"] = list(da.get("detail", []))
        _bake_into_detail(da["detail"], "Depreciation and amortisation", {y: d_of(y) for y in da["total"]})
        da["label"] = "Total D&A (adj.)"

    # Interest Expense: total += I. Bake +I into "Interest Expense" detail row (post-merge w/ Other fin exp).
    ie = by_label.get("Total Interest Expense")
    if ie:
        for y in ie["total"]:
            ie["total"][y] += i_of(y)
        ie["detail"] = list(ie.get("detail", []))
        _bake_into_detail(ie["detail"], "Interest Expense", {y: i_of(y) for y in ie["total"]})
        ie["label"] = "Total Interest Expense (adj.)"

    # 4. Recompute downstream derived totals from the new section values.
    gp = by_label.get("Gross Profit")
    # "Other Operating Income" is a new pre-EBITDA section introduced in
    # build_is_sections to lift the operating subset of IS_OtherIncome above
    # EBITDA. EBITDA = GP + OpEx + OtherOpInc; the recompute must include it.
    other_op_inc = by_label.get("Other Operating Income")
    ebitda = by_label.get("EBITDA")
    # "Impairment (non-financial)" is a section between D&A and EBIT that
    # build_is_sections emits when a non-financial write-down was lifted out of
    # EBITDA (kept in EBIT). It is untouched by the IFRS-16 reversal, but EBIT =
    # EBITDA + D&A + Impairment, so the recompute must carry it.
    impairment = by_label.get("Impairment (non-financial)")
    ebit = by_label.get("EBIT / Operating Income")
    pbt = by_label.get("Profit Before Tax")
    tax = by_label.get("Total Income Tax")
    int_inc = by_label.get("Total Interest Income")
    fee_inc = by_label.get("Total Fee & Commission Income")
    oth_inc = by_label.get("Total Other Income")
    oth_exp = by_label.get("Total Other Expense")
    # `opex`, `da`, `ie` may have been relabeled with "(adj.)"; we still have
    # direct references to those mutated section dicts.

    if ebitda is not None and gp is not None and opex is not None:
        for y in ebitda["total"].keys():
            ebitda["total"][y] = (
                gp["total"].get(y, 0)
                + opex["total"].get(y, 0)
                + (other_op_inc["total"].get(y, 0) if other_op_inc else 0)
            )
        ebitda["label"] = "EBITDA (adj.)"

    if ebit is not None and ebitda is not None and da is not None:
        for y in ebit["total"].keys():
            ebit["total"][y] = (
                ebitda["total"].get(y, 0)
                + da["total"].get(y, 0)
                + (impairment["total"].get(y, 0) if impairment else 0)
            )
        ebit["label"] = "EBIT / Operating Income (adj.)"

    # PBT: should equal pre-adjustment PBT (the +I and -I cancel). Recompute
    # for transparency from the new EBIT plus all finance/other items (which
    # now include the adjusted Interest Expense).
    if pbt is not None and ebit is not None:
        for y in pbt["total"].keys():
            other_finance = 0.0
            for s in (int_inc, ie, fee_inc, oth_inc, oth_exp):
                if s is None:
                    continue
                other_finance += s["total"].get(y, 0)
            pbt["total"][y] = ebit["total"].get(y, 0) + other_finance
        # PBT label keeps the original -- value is effectively unchanged.

    # Net Profit: do NOT touch. Stored row remains accurate; the adjustment
    # is value-neutral below EBITDA so Net Profit shouldn't move.

    return adjusted


def _bake_into_detail(detail_list: list, target_name: str, delta_by_year: dict[int, float]) -> None:
    """Add delta_by_year into the detail row whose name matches target_name.

    If a row with target_name already exists in detail_list, add the deltas to its
    year values in place. If no such row exists, append a new row with the deltas
    as its values.

    Mutates detail_list in place.
    """
    for i, (name, vals) in enumerate(detail_list):
        if name == target_name:
            all_years = set(vals.keys()) | set(delta_by_year.keys())
            updated = {y: vals.get(y, 0) + delta_by_year.get(y, 0) for y in all_years}
            detail_list[i] = (name, updated)
            return
    # Not present — append a new row with the deltas as initial values
    detail_list.append((target_name, dict(delta_by_year)))


def _resort_opex_detail(detail: list) -> list:
    """Re-sort OpEx detail by absolute magnitude across years (largest first).

    Preserves the synthetic top-5+Other structure if present: items beginning with
    'Other (' stay at the bottom of the visible list. The rolled_up list (if any)
    is left untouched.
    """
    if not detail:
        return detail
    # Separate the synthetic "Other (N items)" row from the rest
    other_rows = [item for item in detail if item[0].startswith("Other (")]
    regular_rows = [item for item in detail if not item[0].startswith("Other (")]
    regular_rows.sort(
        key=lambda x: -sum(abs(v) for v in x[1].values() if v is not None)
    )
    return regular_rows + other_rows
