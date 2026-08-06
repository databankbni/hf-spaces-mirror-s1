from collections import defaultdict
import re
import pandas as pd
from lib.data_loader import get_financial_rows

# Explicit CURRENT asset/liability categories (everything else is non-current).
# The old keyword heuristic (`any(k in category.lower() for k in (...))`) mis-split
# the balance sheet TWO ways:
#   1. the substring "current" lives inside "noncurrent", so every BS_NonCurrent*
#      category (borrowings, lease payable, other) was classified CURRENT; and
#   2. BS_TradePayables carried no keyword, so trade payables — a textbook current
#      liability — fell into NON-CURRENT (Gepha 201991229 showed ₾156M trade
#      payables under a ₾115M non-current total; the detail didn't foot).
# The split is display-only (section totals are stored or derived), but it put
# lines under the wrong subtotal. An explicit set + a "non-current wins first"
# fallback fixes both directions.
_CURRENT_CATEGORIES = {
    # Assets
    "BS_Cash", "BS_TradeReceivables", "BS_Inventory", "BS_OtherCurrentAssets",
    # Liabilities
    "BS_CurrentBorrowings", "BS_CurrentInsuranceLiabilities",
    "BS_CurrentLeasePayable", "BS_CurrentTaxPayable",
    "BS_OtherCurrentLiabilities", "BS_TradePayables",
}

# Categories that hold stored section TOTALS / roll-ups — never component lines.
# Rows filed here must not render as balance-sheet *detail* items even when their
# label omits the word "Total" (e.g. "Net assets attributable to the bank's equity
# holders", "Opening Equity", "Closing Equity", "Reported liabilities"). Otherwise a
# total-valued row shows up alongside the real components and the detail no longer
# reconciles to the subtotal. The name-only "Total" filter used elsewhere misses
# these; the category is the reliable signal.
BS_TOTAL_CATEGORIES = {"BS_TotalAssets", "BS_TotalLiabilities", "BS_TotalEquity"}

# Statement-of-Changes-in-Equity MOVEMENT (flow) lines that reportal files into the
# equity section as COMPONENT rows. They are period *movements* (distributions,
# year-on-year changes), NOT closing balances, so they must not render as balance-
# sheet equity components — otherwise the detail no longer foots to the subtotal.
# They feed no total (all ItemType='COMPONENT'; the total logic sums only 'TOTAL'
# rows), so excluding them is display-only and moves no number. "Opening/Closing
# Equity" are movements too but are already dropped via BS_TOTAL_CATEGORIES.
# Matched as substrings of the canonical key (see _canonical_key).
_EQUITY_MOVEMENT_KEY_SUBSTRINGS = (
    "changes of equity",
    "changes of retained earnings",
    "distributions s to owners",
    "distributions to owners",
)


def _is_equity_movement(name: str) -> bool:
    """True for SOCE movement/flow lines that must not show as equity balances."""
    key = _canonical_key(name)
    return any(sub in key for sub in _EQUITY_MOVEMENT_KEY_SUBSTRINGS)

# Note: CF-statement reconciliation rows (opening/closing cash, FX-on-cash) used to be
# filtered here by name pattern. They're now corrected upstream — data_loader applies
# LINE_ITEM_SECTION_OVERRIDES so those rows land in Section='CF' and never reach this
# module from a BS query.

def _is_current_category(category: str) -> bool:
    """True if a BS category is a CURRENT asset/liability (else non-current).

    Explicit set for the known categories; a defensive fallback classifies any
    unlisted category by name — checking 'non-current' FIRST so it is never
    swallowed by the 'current' substring inside 'noncurrent'.
    """
    if category in _CURRENT_CATEGORIES:
        return True
    c = category.lower()
    if "noncurrent" in c or "non-current" in c or "non current" in c:
        return False
    return any(k in c for k in ("current", "cash", "receivable", "inventory"))

def _lookup_stored_total(grouped: dict, year: int, section: str, line_item_name: str) -> float | None:
    """Return the stored value for an exact LineItemENG in a section, or None if not present.

    The schema stores reported totals as Category names (e.g. 'BS_TotalAssets') nested
    inside the parent Section (e.g. 'BS_Assets'). To make callers concise, this helper
    treats the `section` argument as either a real Section or a Category-style hint
    ('BS_TotalAssets', 'BS_TotalLiabilities', 'BS_TotalEquity') and searches the
    appropriate parent Section's category map.
    """
    # Map total-category hints to their parent section.
    parent_section_by_hint = {
        "BS_TotalAssets": "BS_Assets",
        "BS_TotalLiabilities": "BS_Liabilities",
        "BS_TotalEquity": "BS_Equity",
    }
    target = line_item_name.lower().strip()

    if section in parent_section_by_hint:
        parent = parent_section_by_hint[section]
        cat_items = grouped.get((year, parent), {}).get(section, [])
        for name, value, *_ in cat_items:
            if name.lower().strip() == target:
                return value
        return None

    cat_map = grouped.get((year, section), {})
    for items in cat_map.values():
        for name, value, *_ in items:
            if name.lower().strip() == target:
                return value
    return None

def _group_by_year_section(rows: list[dict]) -> dict:
    """Group rows by (year, section) -> {category: [(item, value, item_type), ...]}.

    item_type is 'TOTAL' or 'COMPONENT' (from financial_data.ItemType). Used to
    exclude COMPONENT sub-rows from section totals so they don't double-count
    with their parent TOTAL row.
    """
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        out[(r["FVYear"], r["Section"])][r["Category"]].append((
            r["LineItemENG"],
            r["Value"] or 0,
            r.get("ItemType") or "TOTAL",
        ))
    return out

def _sum_split(grouped: dict, year: int, section: str, current: bool) -> tuple[float, list]:
    """Sum either current or non-current items in a section. Returns (total, detail_rows).

    Excludes:
      - Items whose name contains 'Total' (stored roll-up totals)
      - Items with ItemType='COMPONENT' (breakdowns — would double-count with parent)
    """
    cat_map = grouped.get((year, section), {})
    total = 0.0
    detail: list = []
    for category, items in cat_map.items():
        is_curr = _is_current_category(category)
        if is_curr != current:
            continue
        if category in BS_TOTAL_CATEGORIES:
            continue  # stored totals/roll-ups, not components
        for t in items:
            item, value = t[0], t[1]
            item_type = t[2] if len(t) == 3 else "TOTAL"
            if value == 0:
                continue
            if "Total" in item or "TOTAL" in item.upper():
                continue
            detail.append((category, item, value))
            if item_type == "TOTAL":
                total += value
            # COMPONENT rows: shown in detail but NOT summed into section total
    return total, detail

def _sum_section(grouped: dict, year: int, section: str) -> float:
    cat_map = grouped.get((year, section), {})
    out = 0.0
    for items in cat_map.values():
        for t in items:
            name, v = t[0], t[1]
            item_type = t[2] if len(t) == 3 else "TOTAL"
            if v == 0:
                continue
            if "Total" in name or "TOTAL" in name.upper():
                continue
            if item_type != "TOTAL":
                continue
            out += v
    return out

def _calculate_debt(grouped: dict, year: int) -> tuple[float, float, float]:
    """Return (total_debt, cash, net_debt) for one year."""
    liab_map = grouped.get((year, "BS_Liabilities"), {})
    asset_map = grouped.get((year, "BS_Assets"), {})

    total_debt = 0.0
    for items in liab_map.values():
        for item, value, *_ in items:
            if value == 0:
                continue
            if "Total" in item or "TOTAL" in item.upper():
                continue
            lo = item.lower()
            if (
                "borrow" in lo
                or "debt securities" in lo
                or "finance lease" in lo
                or "lease payable" in lo
            ):
                total_debt += value

    cash = 0.0
    for items in asset_map.values():
        for item, value, *_ in items:
            if value == 0:
                continue
            if "Total" in item or "TOTAL" in item.upper():
                continue
            lo = item.lower()
            if "cash" in lo and "equivalents" in lo:
                cash = value
                break
        if cash:
            break

    return total_debt, cash, total_debt - cash

def build_bs_table(db_path: str, idcode: str, years: list[int]) -> pd.DataFrame:
    """Build multi-year Balance Sheet DataFrame with debt analysis."""
    if not years:
        return pd.DataFrame(columns=["Line Item"])

    rows = get_financial_rows(db_path, idcode, years, section_prefix="BS_")
    grouped = _group_by_year_section(rows)

    table: list[dict] = []

    def row(label: str, values_by_year: dict) -> dict:
        rec = {"Line Item": label}
        for y in years:
            rec[y] = values_by_year.get(y, 0)
        return rec

    def collect_items(section: str, current: bool) -> list[tuple[str, str]]:
        seen: dict = {}
        for y in years:
            _, detail = _sum_split(grouped, y, section, current)
            for cat, item, _ in detail:
                key = (cat, item)
                if key not in seen:
                    seen[key] = key
        return list(seen.keys())

    def detail_values(section: str, cat: str, item: str) -> dict:
        out = {}
        for y in years:
            v = 0
            for c, items in grouped.get((y, section), {}).items():
                if c != cat:
                    continue
                for i, val, *_ in items:
                    if i == item:
                        v = val
                        break
            out[y] = v
        return out

    # ASSETS
    table.append(row("ASSETS", {y: None for y in years}))
    table.append(row("CURRENT ASSETS", {y: None for y in years}))
    for cat, item in collect_items("BS_Assets", current=True):
        vals = detail_values("BS_Assets", cat, item)
        if any(v != 0 for v in vals.values()):
            table.append(row(f"  {item}", vals))
    cur_assets_by_y = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalAssets", "Total current assets")
        if stored is not None and stored != 0:
            cur_assets_by_y[y] = stored
        else:
            cur_assets_by_y[y] = _sum_split(grouped, y, "BS_Assets", True)[0]
    table.append(row("TOTAL CURRENT ASSETS", cur_assets_by_y))

    table.append(row("NON-CURRENT ASSETS", {y: None for y in years}))
    for cat, item in collect_items("BS_Assets", current=False):
        vals = detail_values("BS_Assets", cat, item)
        if any(v != 0 for v in vals.values()):
            table.append(row(f"  {item}", vals))
    # Compute TOTAL ASSETS first (prefer stored, fallback to detail sum)
    total_assets_by_y = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalAssets", "Total Assets")
        if stored is not None and stored != 0:
            total_assets_by_y[y] = stored
        else:
            total_assets_by_y[y] = cur_assets_by_y[y] + _sum_split(grouped, y, "BS_Assets", False)[0]
    # Non-current = Total - Current to keep the subtotals mathematically consistent
    noncur_assets_by_y = {y: total_assets_by_y[y] - cur_assets_by_y[y] for y in years}
    table.append(row("TOTAL NON-CURRENT ASSETS", noncur_assets_by_y))
    table.append(row("TOTAL ASSETS", total_assets_by_y))

    # LIABILITIES
    table.append(row("LIABILITIES", {y: None for y in years}))
    table.append(row("CURRENT LIABILITIES", {y: None for y in years}))
    for cat, item in collect_items("BS_Liabilities", current=True):
        vals = detail_values("BS_Liabilities", cat, item)
        if any(v != 0 for v in vals.values()):
            table.append(row(f"  {item}", vals))
    cur_liab_by_y = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalLiabilities", "Total current liabilities")
        if stored is not None and stored != 0:
            cur_liab_by_y[y] = stored
        else:
            cur_liab_by_y[y] = _sum_split(grouped, y, "BS_Liabilities", True)[0]
    table.append(row("TOTAL CURRENT LIABILITIES", cur_liab_by_y))

    table.append(row("NON-CURRENT LIABILITIES", {y: None for y in years}))
    for cat, item in collect_items("BS_Liabilities", current=False):
        vals = detail_values("BS_Liabilities", cat, item)
        if any(v != 0 for v in vals.values()):
            table.append(row(f"  {item}", vals))
    # Compute TOTAL LIABILITIES first (prefer stored, fallback to detail sum)
    total_liab_by_y = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalLiabilities", "Total Liabilities")
        if stored is not None and stored != 0:
            total_liab_by_y[y] = stored
        else:
            total_liab_by_y[y] = cur_liab_by_y[y] + _sum_split(grouped, y, "BS_Liabilities", False)[0]
    # Non-current = Total - Current to keep the subtotals mathematically consistent
    noncur_liab_by_y = {y: total_liab_by_y[y] - cur_liab_by_y[y] for y in years}
    table.append(row("TOTAL NON-CURRENT LIABILITIES", noncur_liab_by_y))
    table.append(row("TOTAL LIABILITIES", total_liab_by_y))

    # EQUITY
    table.append(row("EQUITY", {y: None for y in years}))
    eq_items: dict = {}
    for y in years:
        for cat, items in grouped.get((y, "BS_Equity"), {}).items():
            if cat in BS_TOTAL_CATEGORIES:
                continue  # stored totals/roll-ups, not components
            for item, *_ in items:
                if "Total" in item or "TOTAL" in item.upper():
                    continue
                if _is_equity_movement(item):
                    continue  # SOCE flow line, not a balance component
                eq_items[(cat, item)] = (cat, item)
    for cat, item in eq_items.keys():
        vals = detail_values("BS_Equity", cat, item)
        if any(v != 0 for v in vals.values()):
            table.append(row(f"  {item}", vals))
    total_eq_by_y = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalEquity", "Total Equity")
        if stored is not None and stored != 0:
            total_eq_by_y[y] = stored
        else:
            total_eq_by_y[y] = _sum_section(grouped, y, "BS_Equity")
    table.append(row("TOTAL EQUITY", total_eq_by_y))

    # BS Check
    diff_by_y = {y: total_assets_by_y[y] - (total_liab_by_y[y] + total_eq_by_y[y]) for y in years}
    table.append(row("BALANCE CHECK (Assets - L&E)", diff_by_y))

    # Debt Analysis
    table.append(row("DEBT ANALYSIS", {y: None for y in years}))
    debt_by_y, cash_by_y, net_debt_by_y = {}, {}, {}
    for y in years:
        td, c, nd = _calculate_debt(grouped, y)
        debt_by_y[y] = td
        cash_by_y[y] = c
        net_debt_by_y[y] = nd
    table.append(row("TOTAL DEBT", debt_by_y))
    table.append(row("Cash & Equivalents", cash_by_y))
    table.append(row("NET DEBT", net_debt_by_y))

    df = pd.DataFrame(table)
    return df[["Line Item"] + years]


def _split_detail_items(
    grouped: dict, years: list[int], section: str, current: bool
) -> list[tuple[str, dict]]:
    """Collect detail items in a section split by current/non-current.

    Returns [(item_name, {year: value, ...}), ...] with all-zero items dropped.
    Uses the same `_is_current_category` and exclusion rules as `_sum_split`.
    """
    by_item: dict = {}
    order: list = []
    for y in years:
        cat_map = grouped.get((y, section), {})
        for category, items in cat_map.items():
            if _is_current_category(category) != current:
                continue
            if category in BS_TOTAL_CATEGORIES:
                continue  # stored totals/roll-ups, not components
            for item, value, *_ in items:
                if "Total" in item or "TOTAL" in item.upper():
                    continue
                if item not in by_item:
                    by_item[item] = {yr: 0 for yr in years}
                    order.append(item)
                by_item[item][y] = value
    out = []
    for name in order:
        vals = by_item[name]
        if any(v != 0 for v in vals.values()):
            out.append((name, vals))
    return out


def _equity_detail_items(grouped: dict, years: list[int]) -> list[tuple[str, dict]]:
    """Collect equity detail items, excluding Total* rows."""
    by_item: dict = {}
    order: list = []
    for y in years:
        for _cat, items in grouped.get((y, "BS_Equity"), {}).items():
            if _cat in BS_TOTAL_CATEGORIES:
                continue  # stored totals/roll-ups, not components
            for item, value, *_ in items:
                if "Total" in item or "TOTAL" in item.upper():
                    continue
                if _is_equity_movement(item):
                    continue  # SOCE flow line, not a balance component
                if item not in by_item:
                    by_item[item] = {yr: 0 for yr in years}
                    order.append(item)
                by_item[item][y] = value
    out = []
    for name in order:
        vals = by_item[name]
        if any(v != 0 for v in vals.values()):
            out.append((name, vals))
    return out


def _sort_by_magnitude_bs(details: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    return sorted(
        details,
        key=lambda kv: sum(abs(v) for v in kv[1].values()),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Detail-line label normalisation + small-item bucketing (display only)
#
# reportal.ge exports spell the same balance-sheet line several ways across
# filings — e.g. "Cash advances made to other parties" vs "Cash advances to
# other parties", "Inventories" vs "- inventories", "Retained earnings
# (Accumulated deficit)" vs "Retained earnings / (Accumulated deficit)". Those
# are the SAME economic line and should collapse to a single detail row.
#
# This is applied to the *display* only. Section subtotals are computed
# independently above (and prefer stored totals), so merging or bucketing detail
# rows never moves a total or the balance check — it just de-clutters the face.
# ---------------------------------------------------------------------------

# Filler words dropped when building the match key, so "… made to …" collapses
# onto "… to …". Kept deliberately tiny: over-aggressive stop-wording risks
# merging genuinely different lines.
_BS_LABEL_STOPWORDS = {"made"}

# Generic catch-all lines already present in some filings. When small items are
# swept into "Other", an existing generic line is folded into the same row
# instead of leaving two. Specific lines like "Other intangible assets" or
# "Other financial liabilities" are deliberately NOT here — they are real lines.
_OTHER_GENERIC_KEYS = {
    "other current assets",
    "other non current assets",
    "other assets",
    "other current liabilities",
    "other non current liabilities",
    "other liabilities",
    "other reserves",
    "other equity items",
    "other equity",
    "other",
}


def _canonical_key(name: str) -> str:
    """Normalise a line-item label to a match key for merging spelling variants.

    Lowercases, drops leading bullet/dash markers, turns punctuation into spaces,
    collapses whitespace, and drops a tiny set of filler words. Two labels with
    the same key are treated as the same line.
    """
    s = name.strip().lower().lstrip("-•– ").strip()
    s = re.sub(r"[()/:.,;\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    toks = [t for t in s.split(" ") if t and t not in _BS_LABEL_STOPWORDS]
    key = " ".join(toks)
    # Collapse reportal's two share-capital label conventions — "Share Capital" and
    # "Share capital (in case of Limited Liability Company - ...)" — onto one key so
    # a filer carrying both merges into a single detail row (max, not sum) instead
    # of double-counting the same balance. Share premium starts differently and is
    # unaffected.
    if key.startswith("share capital"):
        return "share capital"
    return key


def _merge_name_variants(details: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Collapse detail rows whose names normalise to the same key into one row.

    For each year the merged value is the variant with the largest magnitude (NOT
    the sum): the variants are one line reported under different spellings — and
    reportal often stores the breakdown COMPONENT with a value identical to its
    parent TOTAL — so summing would double-count. The display label is the most
    complete variant (prefers a non-bulleted name, then the largest line).
    """
    groups: dict[str, list[tuple[str, dict]]] = {}
    order: list[str] = []
    for name, vals in details:
        k = _canonical_key(name)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append((name, vals))

    merged: list[tuple[str, dict]] = []
    for k in order:
        variants = groups[k]
        if len(variants) == 1:
            merged.append(variants[0])
            continue
        years = {y for _, v in variants for y in v.keys()}
        vals: dict = {}
        for y in years:
            best = 0
            for _, v in variants:
                cand = v.get(y, 0) or 0
                if abs(cand) > abs(best):
                    best = cand
            vals[y] = best

        def _label_score(item: tuple[str, dict]) -> tuple:
            n, vv = item
            no_bullet = 0 if n.strip().startswith(("-", "•", "–")) else 1
            return (no_bullet, sum(abs(x) for x in vv.values()), len(n))

        label = max(variants, key=_label_score)[0]
        merged.append((label, vals))
    return merged


def _bucket_small_into_other(
    details: list[tuple[str, dict]],
    section_total: dict,
    years: list[int],
    default_label: str,
    threshold: float = 0.05,
    min_items: int = 2,
) -> list[tuple[str, dict]]:
    """Sweep consistently-small detail lines into a single 'Other …' row.

    A line is 'small' when |value| < ``threshold`` * |section total| in every year
    where the section total is non-zero. When at least ``min_items`` such lines
    exist they are summed into one row, and any pre-existing generic 'Other …' line
    is folded into the same row (so the page never shows two). Returns the details
    unchanged when too few lines qualify. The 'Other' row sorts to the bottom.
    """
    nonzero_years = [y for y in years if section_total.get(y, 0)]
    if not nonzero_years:
        return details

    existing_other: list[tuple[str, dict]] = []
    small: list[tuple[str, dict]] = []
    big: list[tuple[str, dict]] = []
    for name, vals in details:
        if _canonical_key(name) in _OTHER_GENERIC_KEYS:
            existing_other.append((name, vals))
            continue
        is_small = all(
            abs(vals.get(y, 0)) < threshold * abs(section_total[y])
            for y in nonzero_years
        )
        (small if is_small else big).append((name, vals))

    if len(small) < min_items:
        return details

    combined = {y: 0 for y in years}
    for _name, vals in small + existing_other:
        for y in years:
            combined[y] += vals.get(y, 0)
    label = existing_other[0][0] if existing_other else default_label
    return big + [(label, combined)]


def _finalize_detail(
    details: list[tuple[str, dict]],
    section_total: dict,
    years: list[int],
    other_label: str,
) -> list[tuple[str, dict]]:
    """Merge spelling variants, sort by magnitude, then bucket small items."""
    details = _merge_name_variants(details)
    details = _sort_by_magnitude_bs(details)
    return _bucket_small_into_other(details, section_total, years, other_label)


# Below this fraction of the section total (and this absolute floor) a foot gap is
# treated as rounding noise and left unreconciled — only genuine current/non-
# current splits get a reclassification line.
_RECON_MIN_FRAC = 0.01
_RECON_MIN_ABS = 50_000.0


def _reconciliation_line(
    details: list[tuple[str, dict]],
    section_total: dict,
    years: list[int],
    label: str,
) -> list[tuple[str, dict]]:
    """Append a reclassification line so the displayed detail foots to the
    authoritative section total each year.

    Georgian filers routinely report a long-term instrument (a finance lease, a
    bond, a bank loan) as ONE line — mapped to a non-current category — while the
    current slice due within a year is captured only inside the stored
    "Total current liabilities" subtotal. The category-level detail therefore
    undershoots current and overshoots non-current by the same amount (Gepha
    201991229 ₾48.8M, Tegeta 202177205 ₾313M, ~half the DB). This adds the
    reclassification the source netted into subtotals:
      - current section:      "Current portion of long-term debt & leases" (+)
      - non-current section:  "Less: current portion …"                    (-)
    so both foot to the same authoritative totals. Immaterial gaps (rounding)
    are ignored. Non-mutating. The line is placed directly beneath the long-term
    debt/lease line(s) it adjusts (so "Finance lease payable" and its "Less:
    current portion" read together), falling back to the end if none is present.

    NOTE: the amount is DERIVED (reported subtotal − sum of itemised lines), not a
    line taken from the filing — reportal never itemises the current portion of
    long-term debt (verified DB-wide: 0 companies). It is the exact gap between two
    reported figures, which for single-combined-instrument filers (Gepha, Tegeta)
    is that instrument's current portion.
    """
    resid = {
        y: section_total.get(y, 0) - sum(v.get(y, 0) for _, v in details)
        for y in years
    }
    material = any(
        abs(resid[y]) >= max(_RECON_MIN_ABS, _RECON_MIN_FRAC * abs(section_total.get(y, 0) or 0))
        for y in years
    )
    if not material:
        return details
    recon = (label, resid)
    # Place the reclassification directly beneath the long-term debt/lease line(s)
    # it adjusts, so they read as a pair. Anchor on the last debt/lease line.
    _DEBT_KEYS = ("lease", "borrow", "debt", "loan", "securit", "bond")
    last_debt = -1
    for i, (name, _v) in enumerate(details):
        if any(k in name.lower() for k in _DEBT_KEYS):
            last_debt = i
    if last_debt >= 0:
        return details[: last_debt + 1] + [recon] + details[last_debt + 1 :]
    return details + [recon]


def build_bs_sections(db_path: str, idcode: str, years: list[int],
                      table: str = "financial_data") -> list[dict]:
    """Build a structured Balance Sheet as a list of section dicts.

    Each section dict mirrors the IS structure:
        {
            "label": str,
            "kind": "section_with_detail" | "derived_total",
            "total": {year: value, ...},
            "detail": [(name, {year: value, ...}), ...],
        }

    Detail items are sorted by absolute magnitude across years (largest first).
    """
    if not years:
        return []

    rows = get_financial_rows(db_path, idcode, years, section_prefix="BS_", table=table)
    grouped = _group_by_year_section(rows)

    sections: list[dict] = []

    # Total Current Assets
    cur_assets_total: dict = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalAssets", "Total current assets")
        if stored is not None and stored != 0:
            cur_assets_total[y] = stored
        else:
            cur_assets_total[y] = _sum_split(grouped, y, "BS_Assets", True)[0]
    cur_assets_detail = _finalize_detail(
        _split_detail_items(grouped, years, "BS_Assets", current=True),
        cur_assets_total, years, "Other current assets",
    )
    cur_assets_detail = _reconciliation_line(
        cur_assets_detail, cur_assets_total, years,
        "Current portion of non-current assets",
    )
    sections.append({
        "label": "Total Current Assets",
        "kind": "section_with_detail",
        "total": cur_assets_total,
        "detail": cur_assets_detail,
    })

    # TOTAL ASSETS (computed first so non-current can be derived)
    total_assets: dict = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalAssets", "Total Assets")
        if stored is not None and stored != 0:
            total_assets[y] = stored
        else:
            total_assets[y] = cur_assets_total[y] + _sum_split(grouped, y, "BS_Assets", False)[0]

    # Total Non-Current Assets (derived for math consistency with totals)
    noncur_assets_total = {y: total_assets[y] - cur_assets_total[y] for y in years}
    noncur_assets_detail = _finalize_detail(
        _split_detail_items(grouped, years, "BS_Assets", current=False),
        noncur_assets_total, years, "Other non-current assets",
    )
    noncur_assets_detail = _reconciliation_line(
        noncur_assets_detail, noncur_assets_total, years,
        "Less: current portion of non-current assets",
    )
    sections.append({
        "label": "Total Non-Current Assets",
        "kind": "section_with_detail",
        "total": noncur_assets_total,
        "detail": noncur_assets_detail,
    })

    sections.append({
        "label": "TOTAL ASSETS",
        "kind": "derived_total",
        "total": total_assets,
        "detail": [],
        "bar": "total",
    })

    # Total Current Liabilities
    cur_liab_total: dict = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalLiabilities", "Total current liabilities")
        if stored is not None and stored != 0:
            cur_liab_total[y] = stored
        else:
            cur_liab_total[y] = _sum_split(grouped, y, "BS_Liabilities", True)[0]
    cur_liab_detail = _finalize_detail(
        _split_detail_items(grouped, years, "BS_Liabilities", current=True),
        cur_liab_total, years, "Other current liabilities",
    )
    cur_liab_detail = _reconciliation_line(
        cur_liab_detail, cur_liab_total, years,
        "Current portion of long-term debt & leases",
    )
    sections.append({
        "label": "Total Current Liabilities",
        "kind": "section_with_detail",
        "total": cur_liab_total,
        "detail": cur_liab_detail,
    })

    # TOTAL LIABILITIES (computed first)
    total_liab: dict = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalLiabilities", "Total Liabilities")
        if stored is not None and stored != 0:
            total_liab[y] = stored
        else:
            total_liab[y] = cur_liab_total[y] + _sum_split(grouped, y, "BS_Liabilities", False)[0]

    noncur_liab_total = {y: total_liab[y] - cur_liab_total[y] for y in years}
    noncur_liab_detail = _finalize_detail(
        _split_detail_items(grouped, years, "BS_Liabilities", current=False),
        noncur_liab_total, years, "Other non-current liabilities",
    )
    noncur_liab_detail = _reconciliation_line(
        noncur_liab_detail, noncur_liab_total, years,
        "Less: current portion of long-term debt & leases",
    )
    sections.append({
        "label": "Total Non-Current Liabilities",
        "kind": "section_with_detail",
        "total": noncur_liab_total,
        "detail": noncur_liab_detail,
    })

    sections.append({
        "label": "TOTAL LIABILITIES",
        "kind": "derived_total",
        "total": total_liab,
        "detail": [],
        "bar": "cost",
    })

    # Total Equity
    total_equity: dict = {}
    for y in years:
        stored = _lookup_stored_total(grouped, y, "BS_TotalEquity", "Total Equity")
        if stored is not None and stored != 0:
            total_equity[y] = stored
        else:
            total_equity[y] = _sum_section(grouped, y, "BS_Equity")
    equity_detail = _finalize_detail(
        _equity_detail_items(grouped, years), total_equity, years, "Other equity items",
    )
    sections.append({
        "label": "Total Equity",
        "kind": "section_with_detail",
        "total": total_equity,
        "detail": equity_detail,
        "bar": "income",
    })

    # Balance Check (Assets - L&E)
    balance_check = {y: total_assets[y] - (total_liab[y] + total_equity[y]) for y in years}
    sections.append({
        "label": "Balance Check (Assets - L&E)",
        "kind": "derived_total",
        "total": balance_check,
        "detail": [],
    })

    # Debt analysis
    debt_by_y, cash_by_y, net_debt_by_y = {}, {}, {}
    for y in years:
        td, c, nd = _calculate_debt(grouped, y)
        debt_by_y[y] = td
        cash_by_y[y] = c
        net_debt_by_y[y] = nd

    sections.append({
        "label": "Total Debt",
        "kind": "derived_total",
        "total": debt_by_y,
        "detail": [],
    })
    sections.append({
        "label": "Cash & Equivalents",
        "kind": "derived_total",
        "total": cash_by_y,
        "detail": [],
    })
    sections.append({
        "label": "Net Debt",
        "kind": "derived_total",
        "total": net_debt_by_y,
        "detail": [],
    })

    return sections
