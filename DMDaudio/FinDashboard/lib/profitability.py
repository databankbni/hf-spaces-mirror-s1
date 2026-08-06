"""Canonical EBITDA / Net Profit computation — the Sprint 5 single source of truth.

Both the Single-Company Income-Statement view (``lib.income_statement
.build_is_sections``) and the Screener / ``metrics_panel`` builder
(``lib.screener.build_metrics_table``) delegate every profitability subtotal to
:func:`compute_profitability` so the two surfaces can never silently diverge
(they disagreed for 52% of a 120-company sample before this module existed —
see docs/superpowers/plans/2026-06-10-sprint5-ebitda-ssot.md).

Canonical definitions (plan §3.2, analyst-confirmed 2026-06-12 — Option A,
matching the IS view):

- **Revenue / COGS / OpEx / D&A** — category totals via :func:`_sum_category`:
  prefer the stored grand-total row (name contains "Total"), else sum
  ``ItemType='TOTAL'`` rows, else sum components.
- **Gross Profit** = ``Revenue + COGS`` (COGS stored signed-negative). The
  stored ``IS_GrossProfit`` row is IGNORED for subtotal math.
- **Other Operating Income lift** — the subset of ``IS_OtherIncome`` whose
  line-item name contains "operating income" is lifted ABOVE EBITDA; the
  non-operating remainder (FX, dividends, disposal gains, ...) stays below
  EBIT. Filers that instead net an "Other operating income" line *inside*
  ``IS_OpEx`` get the same treatment (:func:`_opex_operating_income_items`):
  it is pulled out of the opex total into Other Operating Income so OpEx reads
  as pure cost — EBITDA-neutral, since both subtotals sit above EBITDA.
- **EBITDA** = ``Gross Profit + OpEx + Operating Other Income``.
- **EBIT** = ``EBITDA + D&A`` (D&A signed-negative).

  Those two lines require ``OpEx`` to be a **pre-D&A, pre-finance** cost base.
  reportal's stored "Total operating expense" row usually is NOT: it is the
  statement-FACE total, which carries the depreciation line (routed away to
  ``IS_DA``) and sometimes net interest. Two arbiters keep the wrong figure out —
  :func:`_reconcile_opex_rollup` (corrupt/partial roll-up, anchored on reported
  operating income) then :func:`_reconcile_opex_against_pbt` (face-total roll-up,
  anchored on reported PBT). Read both before touching the opex resolution.
- **PBT** = ``EBIT + Interest Income + Interest Expense + Fee Income +
  Non-operating Other Income + Other Expense`` (same accumulation order as the
  IS view's optional-section loop).
- **Net Profit** — an analyst/PDF-confirmed value override
  (:data:`NET_PROFIT_OVERRIDES`, keyed by ``(IdCode, FVYear)``) if one exists,
  else the stored canonical ``IS_NetProfit`` row (strict name/exclude matcher),
  falling back to ``PBT + Tax + Discontinued Operations`` when no stored row
  qualifies. ``net_profit_source`` records which branch fired.

This module is pure and DB-agnostic: it operates on already-grouped rows
(the shape :func:`_group_rows` produces) so both callers reuse their existing
row loading and unit tests can feed hand-built fixtures.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

# ---------------------------------------------------------------------------
# Canonical name lists (moved from lib.income_statement / lib.screener —
# both modules re-export them for import compatibility).
# ---------------------------------------------------------------------------

# Canonical Net Profit row names, in priority order. The first non-zero match wins.
# Items in IS_NetProfit category that DO NOT match any of these and DO match an
# exclude pattern are skipped entirely.
NET_PROFIT_PREFERRED_NAMES = (
    "Profit/(loss)",
    "Profit / (loss)",
    "Net Profit",
    "Net profit",
    "Profit for the year",
    "Profit / (Loss) for the year",
    "Profit/(loss) from continuing operations",
)

# Analyst / PDF-confirmed Net-Profit value overrides, keyed (IdCode, FVYear)
# -> net profit in absolute GEL.
#
# A subset of filers store *Total Comprehensive Income* in the reportal
# ``Profit/(loss)`` bottom-line TOTAL row (the row the picker selects), because a
# below-net-profit OCI item — typically an FX-translation difference — is
# mislabeled as "Discontinued Operations" and folded into that total. Because
# ``Profit/(loss)`` is a *stored value* (not recomputed at read time), the row
# picker cannot recover the true "profit for the year"; the correct figure
# survives in the separate ``Profit/(loss) from continuing operations`` row.
# These entries replace the TCI-contaminated total with the confirmed net profit.
#
# ONLY PDF-confirmed or clean-fingerprint entries belong here. The wider
# candidate population (44 tiny "Discontinued Operations"-fold company-years that
# LOOK like this but are indistinguishable from genuine small discontinued
# operations without the source PDF) is catalogued in
# docs/reviews/net-profit-tci-contamination.md for a later audit sweep — do NOT
# bulk-add it. A blanket "prefer continuing-operations" picker rule was rejected:
# it would change 184 company-years, most of them genuine discontinued ops with
# large, correct deltas (e.g. 404404550 FY2022: net 504.6M vs continuing -43.5M).
NET_PROFIT_OVERRIDES: dict[tuple[str, int], float] = {
    # Gepha (გეფა) 201991229 — pharma distributor. A recurring, tiny, usually-
    # negative FX-translation OCI item is mislabeled "Discontinued Operations"
    # and folded into Profit/(loss), making the stored bottom line equal TCI.
    # The true profit for the year is the continuing-operations value.
    # FY2023 / FY2024 confirmed against the source PDF (2026-07-10 audit);
    # FY2019 / FY2020 match the same clean fingerprint
    # (Profit/(loss) == TCI == continuing-ops + a <2%-of-profit "disc" line).
    ("201991229", 2019): 51_445_000.0,  # was 51,384,000 (TCI); +61k  (pattern)
    ("201991229", 2020): 43_458_000.0,  # was 43,448,000 (TCI); +10k  (pattern)
    ("201991229", 2023): 60_080_000.0,  # was 60,021,000 (TCI); +59k  (PDF-confirmed)
    ("201991229", 2024): 51_819_000.0,  # was 51,647,000 (TCI); +172k (PDF-confirmed)
}

# Analyst / PDF-confirmed EBITDA/EBIT overrides, keyed (IdCode, FVYear) ->
# (ebitda, ebit) in absolute GEL.
#
# For a small number of filers reportal's Excel export — and its stored "Operating
# income" (IS_EBIT) row — mis-states operating profit, typically by EXCLUDING an
# "other expenses" block that the audited statement places ABOVE operating profit.
# The bottom-up EBITDA/EBIT is then materially overstated even though Net Profit
# (from the stored bottom-line row) and the bottom-up PBT are already correct — the
# excluded expense sits in the below-EBIT "other income/(expense)" lines, so only the
# EBITDA/EBIT *subtotals* are wrong. This override replaces just those two subtotals;
# it is applied AFTER PBT / Net Profit are computed, leaving them untouched.
#
# Like NET_PROFIT_OVERRIDES, ONLY PDF-confirmed entries belong here, each carrying an
# analyst decision on the target operating-profit definition. The wider look-alike
# population is NOT auto-detectable — it is dominated by genuine non-operating FX,
# impairment and disposal items where the current below-EBIT treatment is correct
# (e.g. Pharmaxi 204975090 FY2020 has the identical shape and is right). Do NOT
# bulk-add. See docs/reviews/2026-07-21-operating-income-other-expenses-diagnosis.md.
OPERATING_PROFIT_OVERRIDES: dict[tuple[str, int], tuple[float, float]] = {
    # ABM / შპს „ეი-ბი ემ" 404917328 FY2022 — audited consolidated operating profit is
    # 311,669 (reportal GetFile/55097 p.13), but the stored "Operating income" row
    # (7,367,892) excludes note-9 "Other expenses" (7,056,223), overstating EBIT by
    # that amount. Target = audited operating profit (definition A). EBITDA = EBIT +
    # D&A (82,242) = 393,911. PBT (-244,399) and Net Profit (-543,099) are unchanged.
    ("404917328", 2022): (393_911.0, 311_669.0),
}

# Lower-case substrings that disqualify a row from being "Net Profit" even if positive.
NET_PROFIT_EXCLUDE_SUBSTRINGS = (
    "attributable",        # "Owners of the parent" / "Attributable to NCI"
    "comprehensive",       # Total comprehensive income / OCI
    "before tax",          # PBT
    "non-controlling",
    "owners",
    "net assets",          # BS leakage
    "discontinued",
    "held for sale",
)

# Canonical Operating Income (EBIT) row names — the company's *reported* EBIT row,
# not the displayed (bottom-up) total.
OPERATING_INCOME_PREFERRED_NAMES = (
    "Operating income",
    "Operating Income",
    "Operating profit",
    "EBIT",
)

# Canonical Profit-Before-Tax row names — the company's *reported* PBT row.
PBT_PREFERRED_NAMES = (
    "Profit/(loss) before tax from continuing operations",
    "Profit/(loss) before tax",
    "Profit before tax",
    "Profit / (Loss) before income tax",
    "Profit / (Loss) from Continuing Operations before Income Tax",
)

# Canonical Gross Profit row names — the company's *reported* Gross Profit row.
# NOTE: the canonical Gross Profit subtotal deliberately ignores the stored
# IS_GrossProfit row (§3.2).
GROSS_PROFIT_PREFERRED_NAMES = (
    "Gross Profit",
    "Gross profit",
    "Gross Margin",
)


# ---------------------------------------------------------------------------
# Shared primitives (moved from lib.income_statement)
# ---------------------------------------------------------------------------

def _group_rows(rows: list[dict]) -> dict:
    """Group rows by (year, category) -> list of (item, value, item_type).

    item_type is 'TOTAL' or 'COMPONENT' (from financial_data.ItemType). Used by
    `_sum_category` to avoid double-counting COMPONENT rows (which are breakdowns
    of a parent TOTAL row, e.g. '- sale of goods' is a sub-component of 'Net Revenue').
    """
    grouped: dict = defaultdict(list)
    for r in rows:
        grouped[(r["FVYear"], r["Category"])].append((
            r["LineItemENG"],
            r["Value"] or 0,
            r.get("ItemType") or "TOTAL",  # default TOTAL when missing for backwards-compat
        ))
    return grouped


def _sum_category(grouped: dict, year: int, category: str) -> tuple[float, list]:
    """Return (total, detail) for one category-year.

    Total = the stored grand-total row if present (name contains 'Total'), else
    the SUM of items marked ItemType='TOTAL'. COMPONENT items (breakdowns of a
    parent, e.g. '- sale of goods') are NEVER summed into the category total
    because they would double-count with the parent TOTAL row.

    NOTE: a corrupt/partial "Total operating expense" roll-up (wrong value or
    wrong sign) is handled one level up, in :func:`_reconcile_opex_rollup`,
    because deciding between the roll-up and the itemised sum needs the reported
    operating-income anchor (not available here). See that function.

    Detail = everything except the stored grand-total roll-up row. Both TOTAL
    and COMPONENT items appear in detail so they can be rendered beneath the
    section total.
    """
    items = grouped.get((year, category), [])
    # Roll-up row detection: items whose name contains "Total"/"TOTAL"
    rollup = next((v for t in items
                   for n, v, _ in [t if len(t) == 3 else (t[0], t[1], "TOTAL")]
                   if "Total" in n or "TOTAL" in n.upper()), None)
    detail = [(n, v) for t in items
              for n, v, _ in [t if len(t) == 3 else (t[0], t[1], "TOTAL")]
              if "Total" not in n and "TOTAL" not in n.upper()]
    if rollup is not None:
        return rollup, detail
    # No stored roll-up — sum ItemType='TOTAL' rows only (skip COMPONENT)
    total_items = [v for t in items
                   for n, v, it in [t if len(t) == 3 else (t[0], t[1], "TOTAL")]
                   if it == "TOTAL" and "Total" not in n and "TOTAL" not in n.upper()]
    if total_items:
        return sum(total_items), detail
    # Last resort — sum components (only if NO TOTAL items at all)
    return sum(v for _, v in detail), detail


# Tolerances for the corrupt-opex-roll-up arbiter (:func:`_reconcile_opex_rollup`).
# The itemised sum replaces the stored "Total operating expense" roll-up only when
# it ties to reported operating income within this band AND the roll-up misses by
# more than it. Tuned 2026-07-13 against the whole DB (max real fixes, ~zero
# over-corrections); see docs / the recon-sweep validation.
_OPEX_ROLLUP_TOL_ABS = 50_000.0     # absolute floor (GEL), for tiny filers
_OPEX_ROLLUP_TOL_PCT = 0.005        # or this fraction of revenue, whichever larger
_OPEX_ROLLUP_DECISIVE_RATIO = 0.25  # components must be >=4x closer to op income


def _reconcile_opex_rollup(grouped: dict, year: int,
                           opex: float, opex_detail: list,
                           gross_profit: float) -> float:
    """Guard against a corrupt/partial "Total operating expense" roll-up.

    reportal exports sometimes carry a wrong ``IS_OpEx`` "Total …" row — a value
    far too small, or even the wrong sign — which :func:`_sum_category` takes at
    face value, collapsing operating expenses and massively overstating EBITDA
    (found 2026-07-13 across the DB: UGT Group, Georgian Beverages, GHG-Pharmacy
    FY2018, …; up to ~₾6bn of gross EBITDA distortion).

    Naively "trust the itemised components instead" over-corrects the *opposite*
    data defect — a legitimate roll-up whose itemised rows double-count a
    cross-category line (e.g. a "Conversion costs" line filed in BOTH IS_COGS
    and IS_OpEx). Magnitude alone cannot tell the two apart, so this picks
    whichever opex makes bottom-up operating profit tie to the company's
    **reported operating income** (the stored ``IS_EBIT`` row) — the reliable
    arbiter. When there is no roll-up (opex already equals the itemised sum) or
    no reported operating-income anchor, behaviour is unchanged.

    ``gross_profit`` MUST be the caller's canonical Gross Profit — i.e. the one
    :func:`compute_profitability` builds, INCLUDING the stored-Gross-Profit COGS
    back-fill for filers that report Revenue + Gross Profit but no explicit COGS
    line (~933 companies). Recomputing it here as plain ``Revenue + COGS`` (as an
    earlier version did) uses ``Revenue`` for those filers — an anchor 25-40% too
    high — which silently defeats the arbiter and lets the corrupt roll-up stand
    (e.g. 445489169 Health Care Group FY2022/FY2023: EBITDA overstated by ~₾16-19M
    each year until the correct GP let the components win).
    """
    comp = sum(v for _, v in opex_detail)
    if not opex_detail or abs(comp - opex) <= 1:
        return opex  # no roll-up in play (opex already == components)
    reported_opinc = _select_stored_row(
        grouped.get((year, "IS_EBIT"), []), OPERATING_INCOME_PREFERRED_NAMES)
    if reported_opinc is None:
        return opex  # no arbiter -> keep _sum_category's roll-up choice
    revenue, _ = _sum_category(grouped, year, "IS_Revenue")
    da, _ = _sum_category(grouped, year, "IS_DA")
    gp = gross_profit

    def _residual(ox: float) -> float:
        # reportal's reported operating income is inconsistent about D&A (pre- on
        # some filers, post- on others), so accept a tie at EITHER the EBITDA or
        # the EBIT level — the two candidates differ by orders of magnitude in
        # the cases that matter, so this ambiguity never drives the choice.
        return min(abs(gp + ox - reported_opinc),
                   abs(gp + ox + da - reported_opinc))

    # Override the roll-up ONLY when it clearly misses reported operating income
    # AND the itemised sum is DECISIVELY closer (>=4x). The ratio tolerates
    # reportal's noisy op-income anchor (a correct itemised sum can still miss by
    # a little); the absolute floor stops flips when the roll-up is basically
    # fine; requiring the components to win decisively avoids over-correcting a
    # legit roll-up whose components double-count a cross-category line.
    tol = max(_OPEX_ROLLUP_TOL_ABS, _OPEX_ROLLUP_TOL_PCT * abs(revenue))
    res_rollup = _residual(opex)
    res_comp = _residual(comp)
    if res_rollup > tol and res_comp < _OPEX_ROLLUP_DECISIVE_RATIO * res_rollup:
        return comp
    return opex


# Tolerances for the reported-PBT arbiter (:func:`_reconcile_opex_against_pbt`).
# The tie should be exact — reportal carries whole-GEL figures — so these stay
# tight; they only absorb rounding on filers who report in thousands.
_PBT_ANCHOR_TOL_ABS = 50.0        # absolute floor (GEL)
_PBT_ANCHOR_TOL_PCT = 0.0005      # or this fraction of revenue, whichever larger
# Tolerance for "is the roll-up minus the itemised sum exactly a set of
# below-EBITDA lines?" (:func:`_opex_gap_is_below_ebitda`).
_OPEX_GAP_EXPLAIN_TOL = 2.0


def _opex_gap_is_below_ebitda(grouped: dict, year: int, gap: float) -> bool:
    """True if ``gap`` (roll-up minus itemised sum) is *exactly* some combination
    of the lines this module already accounts for BELOW EBITDA.

    reportal's ``IS_OpEx`` "Total operating expense" is the statement-FACE total,
    so it routinely carries items the itemised ``IS_OpEx`` rows do not:

    - **D&A** — the export's depreciation line is routed to its own ``IS_DA``
      category, so it is absent from the ``IS_OpEx`` detail but present in the
      face total (17.8% of company-years: gap == D&A exactly).
    - **net finance cost** — some filers cram interest inside the operating
      block (34.1%: gap == D&A + net interest).
    - **other income** — netted inside the expense block as a credit, making the
      negative total smaller (hence the ``+`` sign here).

    In every such case the itemised sum IS the pre-D&A operating cost this
    module wants, and the face total is that cost plus lines the chain adds again
    further down. When the gap is NOT explained this way the itemised rows are
    presumed *incomplete* (reportal under-itemising a real cost — the failure
    mode ``scripts/backfill_missing_opex_lines.py`` exists for) and the roll-up
    must be kept: 15.1% of company-years, ₾7.6bn of gap. This is the guard that
    keeps :func:`_reconcile_opex_against_pbt` off that population.
    """
    if abs(gap) <= _OPEX_GAP_EXPLAIN_TOL:
        return False
    da, _ = _sum_category(grouped, year, "IS_DA")
    ii, _ = _sum_category(grouped, year, "IS_InterestIncome")
    ie, _ = _sum_category(grouped, year, "IS_InterestExpense")
    operating_other, non_operating_other = split_other_income(grouped, year)
    terms = [t for t in (da, ii + ie, operating_other + non_operating_other)
             if abs(t) > _OPEX_GAP_EXPLAIN_TOL]
    for size in range(1, len(terms) + 1):
        for combo in combinations(terms, size):
            if abs(gap - sum(combo)) <= _OPEX_GAP_EXPLAIN_TOL:
                return True
    return False


def _bottom_up_pbt(grouped: dict, year: int,
                   gross_profit: float, opex: float) -> float:
    """Bottom-up PBT for a candidate ``opex``, mirroring
    :func:`compute_profitability`'s chain.

    Deliberately skips the non-financial-impairment lift and the
    other-operating-income lift: both are PBT-NEUTRAL (the impairment add-back
    nets out at EBIT, and the income lift only moves an amount between two
    subtotals above EBITDA), so this probe is exact.
    """
    operating_other, non_operating_other = split_other_income(grouped, year)
    da, _ = _sum_category(grouped, year, "IS_DA")
    interest_income, _ = _sum_category(grouped, year, "IS_InterestIncome")
    interest_expense, _ = _sum_category(grouped, year, "IS_InterestExpense")
    fee_income, _ = _sum_category(grouped, year, "IS_FeeIncome")
    other_expense, _ = _sum_category(grouped, year, "IS_OtherExpense")
    return (gross_profit + opex + operating_other + da
            + interest_income + interest_expense + fee_income
            + non_operating_other + other_expense)


def _reconcile_opex_against_pbt(grouped: dict, year: int,
                                opex: float, opex_detail: list,
                                gross_profit: float) -> float:
    """Second-stage arbiter: reject a roll-up that is not a PRE-D&A cost base.

    :func:`_reconcile_opex_rollup` anchors on the reported *operating income*
    row, but filers COMPUTE that row as ``Gross Profit - roll-up``, so for 31,376
    company-years the anchor is algebraically identical to the thing being
    tested: the residual is exactly 0 and the roll-up can never lose. That blind
    spot is why ``compute_profitability`` was handing a post-D&A figure to
    ``ebitda = gross_profit + opex`` and then subtracting D&A AGAIN at EBIT —
    understating EBITDA by |D&A| and EBIT by 2x|D&A| across 24,110 company-years
    / 6,640 companies (₾3.0bn gross).

    The reported **PBT** row is the independent anchor: it sits below every line
    the roll-up might have absorbed, so it cannot be a restatement of the
    roll-up. Switch to the itemised sum only when ALL of:

    1. a reported PBT row exists (else behaviour is unchanged);
    2. the roll-up/itemised gap is exactly a set of below-EBITDA lines
       (:func:`_opex_gap_is_below_ebitda`) — proves the same cost base plus
       double-counted tails, rather than a more complete cost base;
    3. the itemised sum makes bottom-up PBT TIE the reported PBT, and strictly
       better than the roll-up does.

    Validated on 206051396 (a school whose roll-up absorbs D&A *and* net
    interest): the switch makes bottom-up PBT tie its own reported PBT to the
    lari for all 7 filed years, and its FY2022 EBIT land on the 859,370 printed
    in the audited FY2023 report.
    """
    comp = sum(v for _n, v in opex_detail)
    if not opex_detail or abs(comp - opex) <= 1:
        return opex  # no roll-up in play
    reported_pbt = _select_stored_row(
        grouped.get((year, "IS_NetProfit"), []), PBT_PREFERRED_NAMES)
    if reported_pbt is None:
        return opex  # no independent anchor -> leave the earlier choice alone
    if not _opex_gap_is_below_ebitda(grouped, year, opex - comp):
        return opex  # itemised rows look incomplete, not merely pre-D&A
    revenue, _ = _sum_category(grouped, year, "IS_Revenue")
    tol = max(_PBT_ANCHOR_TOL_ABS, _PBT_ANCHOR_TOL_PCT * abs(revenue))
    res_comp = abs(_bottom_up_pbt(grouped, year, gross_profit, comp) - reported_pbt)
    res_rollup = abs(_bottom_up_pbt(grouped, year, gross_profit, opex) - reported_pbt)
    if res_comp <= tol and res_comp < res_rollup:
        return comp
    return opex


def _select_stored_row(
    rows: list[tuple[str, float]],
    preferred_names: tuple[str, ...],
    exclude_substrings: tuple[str, ...] = (),
) -> float | None:
    """Choose the best 'stored subtotal' value from rows of (name, value) pairs.

    Priority:
      1. Exact match against any preferred_name (in order, first non-zero wins).
      2. Case-insensitive match against any preferred_name (first non-zero wins).
      3. None — fall back to calculation.

    Rows whose name (lower-cased) contains any exclude_substring are skipped
    BEFORE matching, so e.g. "Profit / (Loss) Attributable to Non-Controlling Interests"
    never gets matched as "Profit/(loss)" because it contains "attributable".

    Returns the matched value, or None if nothing qualified.
    """
    if not rows:
        return None

    # Filter out excluded rows
    def is_excluded(name: str) -> bool:
        lo = name.lower()
        return any(sub in lo for sub in exclude_substrings)

    # Accept either 2-tuples (name, value) or 3-tuples (name, value, item_type).
    candidates = [(t[0], t[1]) for t in rows if not is_excluded(t[0])]

    # Try exact match first
    for preferred in preferred_names:
        for name, value in candidates:
            if name == preferred and value != 0:
                return value

    # Try case-insensitive match
    for preferred in preferred_names:
        preferred_lo = preferred.lower()
        for name, value in candidates:
            if name.lower() == preferred_lo and value != 0:
                return value

    return None


def split_other_income(grouped: dict, year: int) -> tuple[float, float]:
    """Split IS_OtherIncome for one year into (operating, non_operating) totals.

    Operating = line items whose name contains "operating income"
    (case-insensitive) — these lift EBITDA. Non-operating = everything else
    (FX, dividends, disposal gains, ...) — stays below EBIT. Stored "Total"
    roll-up rows are skipped (the IS view derives this category from detail
    items only).
    """
    operating = 0.0
    non_operating = 0.0
    for t in grouped.get((year, "IS_OtherIncome"), []):
        name, value = t[0], t[1]
        if "Total" in name or "TOTAL" in name.upper():
            continue
        if "operating income" in name.lower():
            operating += value
        else:
            non_operating += value
    return operating, non_operating


def _opex_operating_income_items(grouped: dict, year: int) -> list[tuple[str, float]]:
    """IS_OpEx lines that are really *operating income* the filer netted inside
    operating expenses (name contains "operating income") — returned ONLY when
    they are part of the summed opex total and can therefore be lifted out
    EBITDA-neutrally.

    That holds when :func:`_sum_category` summed the components, i.e. IS_OpEx has
    no stored "Total" roll-up row and no ``ItemType='TOTAL'`` rows (so every row,
    including this income line, went into the total). In that case the amount can
    move from the opex total into Other Operating Income (shown as its own line
    above EBITDA) without changing EBITDA.

    When a stored "Total" row or TOTAL-typed rows drive the opex figure, that
    total did not fold in this line, so lifting it would shift EBITDA — we return
    ``[]`` and leave the line inside Operating Expenses (unchanged behaviour).
    """
    items = grouped.get((year, "IS_OpEx"), [])
    norm = [t if len(t) == 3 else (t[0], t[1], "TOTAL") for t in items]
    has_rollup = any("Total" in n or "TOTAL" in n.upper() for n, _v, _it in norm)
    has_total_rows = any(
        _it == "TOTAL" and "Total" not in n and "TOTAL" not in n.upper()
        for n, _v, _it in norm
    )
    if has_rollup or has_total_rows:
        return []
    return [
        (n, v) for n, v, _it in norm
        if "operating income" in n.lower()
        and "Total" not in n and "TOTAL" not in n.upper()
    ]


# Impairment of NON-financial assets (PP&E, intangibles, goodwill) booked inside
# IS_OpEx. Unlike trade-receivable / financial-asset impairment — a genuine
# operating credit loss that correctly stays in EBITDA — a write-down of
# long-lived assets is a non-cash charge EBITDA must EXCLUDE (added back like
# D&A, so EBIT still carries it). Substrings mirror the bank framework's
# ``_BANK_LOAN_LOSS_EXCLUDE_SUBSTRINGS`` (lib.income_statement) so the "which
# impairments are non-operating" decision never diverges between the two.
_NONFIN_IMPAIRMENT_SUBSTRINGS = (
    "non-financial", "non- financial", "non financial",
    "property, plant", "property plant",
    "tangible",   # matches "tangible" and "intangible"
    "goodwill",
)


def _is_nonfinancial_impairment(name: str) -> bool:
    """True if an IS_OpEx line is a non-financial asset impairment (PP&E /
    intangibles / goodwill) — the kind EBITDA must exclude."""
    n = (name or "").lower()
    return "impair" in n and any(s in n for s in _NONFIN_IMPAIRMENT_SUBSTRINGS)


def _opex_nonfinancial_impairment_items(grouped: dict, year: int) -> list[tuple[str, float]]:
    """Non-financial impairment (name, value) detail lines sitting in IS_OpEx for
    one year (roll-up rows skipped). Enumerated for both the EBITDA add-back
    (:func:`compute_profitability`) and the IS-view display; the *decision*
    whether to lift them is made in compute_profitability (it lifts only the
    portion actually inside the opex figure)."""
    out: list[tuple[str, float]] = []
    for t in grouped.get((year, "IS_OpEx"), []):
        name, value = t[0], t[1]
        if "Total" in name or "TOTAL" in name.upper():
            continue
        if _is_nonfinancial_impairment(name):
            out.append((name, value))
    return out


def _discontinued_operations(grouped: dict, year: int) -> float:
    """Sum the IFRS 5 'Discontinued Operations' P&L line for one year, if present.

    A distinct line from continuing-operations PBT: some filers report
    ``Profit/(loss) from continuing operations`` PLUS a separate
    ``Discontinued Operations`` amount, and the two sum to the final
    ``Profit/(loss)`` total. It's excluded from NET_PROFIT_PREFERRED_NAMES
    matching (it's a bridge component, not the final total) but IS needed to
    reconstruct that total bottom-up. Matched by exact name (case-insensitive)
    to avoid the unrelated BS-ish "Non-current Assets/Liabilities Held for
    Sale and Discontinued Operations" lines that also appear in this category.
    """
    total = 0.0
    for t in grouped.get((year, "IS_NetProfit"), []):
        name, value = t[0], t[1]
        if name.strip().lower() == "discontinued operations":
            total += value
    return total


# ---------------------------------------------------------------------------
# The canonical function
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfitResult:
    """Canonical profitability subtotals for one (company, year)."""
    revenue: float
    cogs: float
    gross_profit: float
    opex: float
    operating_other_income: float
    ebitda: float
    da: float
    impairment: float  # non-financial asset impairment lifted out of EBITDA (kept in EBIT)
    ebit: float
    interest_income: float
    interest_expense: float
    fee_income: float
    non_operating_other_income: float
    other_expense: float
    pbt: float
    tax: float
    discontinued_operations: float
    net_profit: float
    net_profit_source: str  # 'override' | 'reported' | 'calculated'


def compute_profitability(grouped: dict, year: int,
                          idcode: str | None = None) -> ProfitResult:
    """Canonical EBITDA / Net Profit for one (company, year).

    ``grouped`` is ``{(FVYear, Category): [(name, value, item_type), ...]}`` —
    exactly the shape :func:`_group_rows` produces (legacy 2-tuples tolerated).
    Implements ONE definition of every subtotal; both
    ``lib.income_statement.build_is_sections`` and
    ``lib.screener.build_metrics_table`` delegate here.

    ``idcode`` is optional (``None`` for hand-built fixtures / DB-agnostic
    callers). When supplied, a matching ``(idcode, year)`` entry in
    :data:`NET_PROFIT_OVERRIDES` takes precedence over the stored/calculated
    Net Profit (``net_profit_source == 'override'``); everything else is
    unaffected, so the module stays pure and fixture-friendly.
    """
    revenue, _ = _sum_category(grouped, year, "IS_Revenue")
    cogs, _ = _sum_category(grouped, year, "IS_COGS")
    # Back-fill COGS for filers that report a Gross Profit subtotal but no
    # explicit Cost-of-Sales line (~933 companies — the reportal.ge export
    # carries Revenue + Gross Profit only). Without this, "Revenue + COGS"
    # collapses Gross Profit back to Revenue (implying a 100% margin), the COGS
    # line renders empty, and EBITDA is overstated by the entire cost base.
    # When IS_COGS has NO rows at all (genuinely missing — not merely netting to
    # zero) AND a stored Gross Profit exists, derive the cost line from it:
    #   COGS = stored Gross Profit - Revenue   (signed negative)
    # so the canonical "Gross Profit = Revenue + COGS" invariant still holds and
    # the bottom-up EBIT ties to the company's reported Operating Income.
    # This refines the original Sprint 5 §3.2 rule (which set GP = Revenue in
    # this case); validated against reported Operating Income across the whole
    # affected population (derive ties EBIT closer 530 vs 36 where they differ).
    if not grouped.get((year, "IS_COGS")):
        stored_gp = _select_stored_row(
            grouped.get((year, "IS_GrossProfit"), []),
            GROSS_PROFIT_PREFERRED_NAMES,
        )
        if stored_gp is not None:
            cogs = stored_gp - revenue
    # Gross Profit is ALWAYS Revenue + COGS; the stored IS_GrossProfit row is
    # never used directly for the subtotal (only back-filled into COGS above).
    gross_profit = revenue + cogs

    opex, opex_detail = _sum_category(grouped, year, "IS_OpEx")
    # Reject a corrupt/partial "Total operating expense" roll-up (see
    # _reconcile_opex_rollup): pick the opex that ties EBIT to reported
    # operating income when the roll-up and the itemised rows disagree. Pass the
    # canonical gross_profit (COGS back-fill applied) — the arbiter's anchor is
    # wrong without it for Revenue+GrossProfit-only filers.
    opex = _reconcile_opex_rollup(grouped, year, opex, opex_detail, gross_profit)
    # Second stage: reject a roll-up that is the statement-FACE total (D&A and/or
    # net finance cost baked in) rather than the pre-D&A cost base this chain
    # needs. Anchored on the reported PBT row — the only anchor independent of
    # the roll-up itself. See _reconcile_opex_against_pbt.
    opex = _reconcile_opex_against_pbt(grouped, year, opex, opex_detail, gross_profit)

    # Lift non-financial asset impairment (PP&E / intangibles / goodwill) OUT of
    # operating expenses: it is a non-cash write-down EBITDA must exclude (added
    # back like D&A), while EBIT keeps it. Lift only when the impairment is
    # actually inside the current opex figure — opex must be closer to
    # "components INCLUDING impairment" than to "components EXCLUDING it" — so a
    # roll-up that already sits below its impairment line is never double-removed.
    # Financial / trade-receivable impairment (a real operating credit loss) is
    # deliberately NOT matched and stays in EBITDA. See _is_nonfinancial_impairment.
    impairment = 0.0
    imp_sum = sum(v for _n, v in _opex_nonfinancial_impairment_items(grouped, year))
    if imp_sum:
        comp_sum = sum(v for _n, v in opex_detail)
        if abs(opex - comp_sum) <= abs(opex - (comp_sum - imp_sum)):
            opex -= imp_sum
            impairment = imp_sum

    operating_other, non_operating_other = split_other_income(grouped, year)

    # Some filers file "Other operating income" as a contra line *inside*
    # operating expenses rather than under IS_OtherIncome. When it was summed
    # into the opex total (components branch — see _opex_operating_income_items),
    # lift it out: subtract from opex so OpEx reads as pure cost, and add it to
    # Other Operating Income so it renders as its own line above EBITDA. This is
    # EBITDA-NEUTRAL — the amount only moves between two subtotals that both sit
    # above EBITDA, so ebitda/ebit/pbt/net_profit are unchanged.
    opex_operating_income = sum(v for _n, v in _opex_operating_income_items(grouped, year))
    opex -= opex_operating_income
    operating_other += opex_operating_income

    # EBITDA = Gross + Operating-OpEx + Other Operating Income (non-financial
    # impairment already lifted out of opex above).
    ebitda = gross_profit + opex + operating_other

    da, _ = _sum_category(grouped, year, "IS_DA")
    # EBIT carries D&A AND the lifted impairment (a genuine operating charge);
    # the add-back nets the lift out so EBIT / PBT / Net Profit are unchanged.
    ebit = ebitda + da + impairment

    interest_income, _ = _sum_category(grouped, year, "IS_InterestIncome")
    interest_expense, _ = _sum_category(grouped, year, "IS_InterestExpense")
    fee_income, _ = _sum_category(grouped, year, "IS_FeeIncome")
    other_expense, _ = _sum_category(grouped, year, "IS_OtherExpense")

    # Accumulate finance items in the same order build_is_sections emits its
    # optional sections, so PBT matches the IS view bit-for-bit.
    finance = 0
    for v in (interest_income, interest_expense, fee_income,
              non_operating_other, other_expense):
        finance += v
    pbt = ebit + finance

    tax, _ = _sum_category(grouped, year, "IS_Tax")
    discontinued_operations = _discontinued_operations(grouped, year)

    override_np = NET_PROFIT_OVERRIDES.get((idcode, year)) if idcode is not None else None
    if override_np is not None:
        net_profit = override_np
        net_profit_source = "override"
    else:
        stored_np = _select_stored_row(
            grouped.get((year, "IS_NetProfit"), []),
            NET_PROFIT_PREFERRED_NAMES,
            NET_PROFIT_EXCLUDE_SUBSTRINGS,
        )
        if stored_np is not None:
            net_profit = stored_np
            net_profit_source = "reported"
        else:
            net_profit = pbt + tax + discontinued_operations
            net_profit_source = "calculated"

    # Analyst/PDF-confirmed operating-profit override (see OPERATING_PROFIT_OVERRIDES):
    # replace the bottom-up EBITDA/EBIT for the rare filer whose reportal export
    # mis-states operating profit. Applied LAST so PBT / Net Profit — already correct
    # from the raw below-EBIT lines and the stored bottom-line row — stay untouched.
    op_override = (OPERATING_PROFIT_OVERRIDES.get((idcode, year))
                   if idcode is not None else None)
    if op_override is not None:
        ebitda, ebit = op_override

    return ProfitResult(
        revenue=revenue,
        cogs=cogs,
        gross_profit=gross_profit,
        opex=opex,
        operating_other_income=operating_other,
        ebitda=ebitda,
        da=da,
        impairment=impairment,
        ebit=ebit,
        interest_income=interest_income,
        interest_expense=interest_expense,
        fee_income=fee_income,
        non_operating_other_income=non_operating_other,
        other_expense=other_expense,
        pbt=pbt,
        tax=tax,
        discontinued_operations=discontinued_operations,
        net_profit=net_profit,
        net_profit_source=net_profit_source,
    )
