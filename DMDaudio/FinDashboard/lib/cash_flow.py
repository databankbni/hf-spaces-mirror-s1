"""Cash Flow statement builder (3rd statement, mirrors income_statement / balance_sheet).

The reportal.ge Excel exports do **not** carry a fully itemised cash-flow
statement — for every company-year the ingest captures only the *summary*
figures:

    Category          ItemType   LineItemENG
    ----------------  ---------  -----------------------------------------------
    CF_Operating      COMPONENT  "Net Cash from Operating Activities"
    CF_Investing      TOTAL      "Net cash used in investing activities"
    CF_Financing      TOTAL      "Net cash raised in financing activities"
    CF_NetChange      COMPONENT  "Net cash inflow for the year"
    BS_Cash*          COMPONENT  "Cash at the beginning of the year"
    BS_Cash*          COMPONENT  "Cash at the end of the year"
    BS_Cash*          COMPONENT  "Effect of exchange rate changes on cash and cash equivalents"

    (* these three were stored under BS_Assets/BS_Cash but moved to Section='CF'
       by lib.data_loader.LINE_ITEM_SECTION_OVERRIDES, so a CF query picks them up.)

There are no per-line detail rows (no explicit capex line, no working-capital
adjustments), so unlike the IS/BS builders the CF sections are derived totals
rather than section_with_detail blocks. The output is the SAME section-dict
shape the IS/BS builders emit, so it renders through the existing
``lib.ui.render_statement`` path with no renderer changes:

    {"label": str, "kind": "section_with_detail"|"derived_total"|"final_total",
     "total": {year: value, ...}, "detail": [(name, {year: value}), ...]}

Identities the data satisfies (verified against the real DB):
    Net change before FX = OCF + Investing CF + Financing CF
                         = stored "Net cash inflow for the year"
    Closing cash − Opening cash = (Net change before FX) + FX effect

Derived rows added on top of the reported figures:
    * Free Cash Flow  — OCF − Capex. No explicit capex line exists in the
      source, so Capex is proxied by the net Investing outflow (investing CF is
      typically dominated by PPE purchases). Surfaced only when both OCF and a
      negative investing figure are present; clearly labelled as a proxy.
    * Net Change in Cash (before FX) — OCF + Investing + Financing.
    * Net Change in Cash (incl. FX)  — the above + FX-on-cash effect; equals
      Closing − Opening.

Banks / insurers degrade gracefully: their CF rows live in exactly the same
summary categories (verified — even Bank of Georgia stores only these 7
lines), so the same builder works. When a company has no CF rows at all
(e.g. a stub year) the builder returns an empty list and the view shows an
info message instead of crashing.
"""
from __future__ import annotations

from collections import defaultdict

from lib.data_loader import get_financial_rows

# Canonical line-item names the ingest writes for each summary figure. Matching
# is case-insensitive and tolerant of trailing punctuation so a small wording
# drift in a future export doesn't silently zero a section.
_OPERATING_NAMES = ("net cash from operating activities",)
_INVESTING_NAMES = ("net cash used in investing activities",)
_FINANCING_NAMES = ("net cash raised in financing activities",)
_NET_CHANGE_NAMES = ("net cash inflow for the year",)
_OPENING_NAMES = ("cash at the beginning of the year",)
_CLOSING_NAMES = ("cash at the end of the year",)
_FX_NAMES = ("effect of exchange rate changes on cash and cash equivalents",)


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def _group_cf_rows(rows: list[dict]) -> dict:
    """Group CF rows into {(year, category): {normalized_name: value}}.

    Keeps the largest-magnitude value when a normalized name collides within a
    (year, category) — defensive against duplicate filings; canonicalize_rows
    has already deduped on the strict key upstream, so collisions are rare.
    """
    out: dict = defaultdict(dict)
    for r in rows:
        key = (r["FVYear"], r["Category"])
        nm = _norm(r["LineItemENG"])
        v = r.get("Value") or 0
        if nm in out[key] and abs(v) <= abs(out[key][nm]):
            continue
        out[key][nm] = v
    return out


def _pick(grouped: dict, year: int, category: str, names: tuple[str, ...]) -> float:
    """Return the value for the first matching normalized name in a category, else 0."""
    cat = grouped.get((year, category), {})
    for want in names:
        if want in cat:
            return cat[want]
    return 0.0


def _has_any_nonzero(values_by_year: dict) -> bool:
    return any(v != 0 for v in values_by_year.values())


def cf_activity_totals(db_path: str, idcode: str, years: list[int],
                       table: str = "financial_data") -> dict[str, dict[int, float]]:
    """Summary net cash flow per activity: ``{'operating'|'investing'|'financing':
    {year: value}}``. Same source rows/picking as ``build_cf_sections`` — used by
    the Ratios table (OCF / FCF / cash-conversion rows) without building the full
    statement sections."""
    if not years:
        return {"operating": {}, "investing": {}, "financing": {}}
    rows = get_financial_rows(db_path, idcode, years, section_prefix="CF", table=table)
    grouped = _group_cf_rows(rows) if rows else {}
    return {
        "operating": {y: _pick(grouped, y, "CF_Operating", _OPERATING_NAMES) for y in years},
        "investing": {y: _pick(grouped, y, "CF_Investing", _INVESTING_NAMES) for y in years},
        "financing": {y: _pick(grouped, y, "CF_Financing", _FINANCING_NAMES) for y in years},
    }


def build_cf_sections(
    db_path: str, idcode: str, years: list[int], include_fcf: bool = True,
    table: str = "financial_data",
) -> list[dict]:
    """Build a structured Cash Flow statement as a list of section dicts.

    Sections, in IFRS cash-flow order:

        Net Cash from Operating Activities      (Operating)
        Net Cash used in Investing Activities   (Investing)
        Free Cash Flow (OCF − Capex proxy)      (derived, when supportable)
        Net Cash from Financing Activities      (Financing)
        Net Change in Cash (before FX)          (derived = O + I + F)
        Effect of FX on Cash                    (when present)
        Net Change in Cash (incl. FX)           (derived; = Closing − Opening)
        Cash at Beginning of Year               (reconciliation)
        Cash at End of Year                     (final_total)

    ``include_fcf`` controls the Free Cash Flow row. The view passes ``False``
    for banks / insurers, whose investing cash flows are securities and lending
    rather than capex — an OCF − Investing "FCF" would be meaningless there.

    All money is raw GEL (the renderer scales to thousands). Returns ``[]`` when
    the company has no CF rows in the requested years — the caller degrades to
    an info message rather than rendering an all-zero table.
    """
    if not years:
        return []

    rows = get_financial_rows(db_path, idcode, years, section_prefix="CF", table=table)
    if not rows:
        return []

    grouped = _group_cf_rows(rows)

    operating = {y: _pick(grouped, y, "CF_Operating", _OPERATING_NAMES) for y in years}
    investing = {y: _pick(grouped, y, "CF_Investing", _INVESTING_NAMES) for y in years}
    financing = {y: _pick(grouped, y, "CF_Financing", _FINANCING_NAMES) for y in years}
    # Opening / closing / FX were moved into Section='CF' but keep Category='BS_Cash'.
    opening = {y: _pick(grouped, y, "BS_Cash", _OPENING_NAMES) for y in years}
    closing = {y: _pick(grouped, y, "BS_Cash", _CLOSING_NAMES) for y in years}
    fx = {y: _pick(grouped, y, "BS_Cash", _FX_NAMES) for y in years}
    # The reported "Net cash inflow for the year" (== O + I + F). Prefer the
    # stored figure when present; otherwise derive it from the three activities.
    reported_net_change = {y: _pick(grouped, y, "CF_NetChange", _NET_CHANGE_NAMES) for y in years}

    sections: list[dict] = []

    # ---- Operating ----
    if _has_any_nonzero(operating):
        sections.append({
            "label": "Net Cash from Operating Activities",
            "kind": "derived_total",
            "total": operating,
            "detail": [],
            "bar": "income",
        })

    # ---- Investing ----
    if _has_any_nonzero(investing):
        sections.append({
            "label": "Net Cash used in Investing Activities",
            "kind": "derived_total",
            "total": investing,
            "detail": [],
            "bar": "cost",
        })

    # ---- Free Cash Flow (derived) ----
    # No explicit capex line in the source; investing CF is the closest proxy
    # (PPE purchases dominate it). FCF = OCF + Investing CF (investing is stored
    # negative for outflows, so adding it subtracts the capex proxy). Only emit
    # when OCF is present and investing is a net outflow in at least one year —
    # adding it for pure-financing or net-divesting companies would mislead.
    fcf = {y: operating.get(y, 0) + investing.get(y, 0) for y in years}
    investing_is_outflow = any(investing.get(y, 0) < 0 for y in years)
    if include_fcf and _has_any_nonzero(operating) and investing_is_outflow and _has_any_nonzero(fcf):
        sections.append({
            "label": "Free Cash Flow (OCF − Capex proxy)",
            "kind": "derived_total",
            "total": fcf,
            "detail": [],
        })

    # ---- Financing ----
    if _has_any_nonzero(financing):
        sections.append({
            "label": "Net Cash from Financing Activities",
            "kind": "derived_total",
            "total": financing,
            "detail": [],
            "bar": "total",
        })

    # ---- Net Change in Cash (before FX) = O + I + F ----
    # Use the reported stored figure when available (most accurate); fall back
    # to the bottom-up sum of the three activities.
    net_change_before_fx: dict = {}
    for y in years:
        stored = reported_net_change.get(y, 0)
        if stored != 0:
            net_change_before_fx[y] = stored
        else:
            net_change_before_fx[y] = (
                operating.get(y, 0) + investing.get(y, 0) + financing.get(y, 0)
            )
    if _has_any_nonzero(net_change_before_fx):
        sections.append({
            "label": "Net Change in Cash (before FX)",
            "kind": "derived_total",
            "total": net_change_before_fx,
            "detail": [],
        })

    # ---- FX effect on cash ----
    if _has_any_nonzero(fx):
        sections.append({
            "label": "Effect of FX on Cash",
            "kind": "derived_total",
            "total": fx,
            "detail": [],
        })

    # ---- Net Change in Cash (incl. FX) = before-FX + FX ; ties to Closing − Opening ----
    net_change_incl_fx = {
        y: net_change_before_fx.get(y, 0) + fx.get(y, 0) for y in years
    }
    if _has_any_nonzero(net_change_incl_fx) or _has_any_nonzero(fx):
        sections.append({
            "label": "Net Change in Cash (incl. FX)",
            "kind": "derived_total",
            "total": net_change_incl_fx,
            "detail": [],
            "bar": "net",
        })

    # ---- Opening / Closing cash (reconciliation) ----
    if _has_any_nonzero(opening):
        sections.append({
            "label": "Cash at Beginning of Year",
            "kind": "derived_total",
            "total": opening,
            "detail": [],
        })
    if _has_any_nonzero(closing):
        sections.append({
            "label": "Cash at End of Year",
            "kind": "final_total",
            "total": closing,
            "detail": [],
            "bar": "net",
        })

    return sections
