"""Insurer IS / BS / KPI builders backed by the regulator's 12-month return.

Reads the ``insurance_statements`` table (populated by
``scripts/build_insurance_statements.py`` from insurance.gov.ge forms) and produces
the same section-dict shape as :func:`lib.income_statement.build_is_sections` /
:func:`lib.balance_sheet.build_bs_sections` — ``{label, kind, total, detail, ...}`` —
so the shared ``lib.ui.render_statement`` renderer works unchanged.

Because the source form is a fixed, internally-consistent template anchored by line
**codes**, every headline subtotal here is taken DIRECTLY from a form code (net
earned premium = ``00050+00190``, underwriting result ``00320``, PBT ``00540``, net
profit ``00560`` …); the component lines beneath each subtotal are presented with
income-statement display signs (costs negative) and reconcile to it by construction.

All values are absolute GEL. Functions are pure read-only DB access; they degrade
gracefully (empty result) when the table is absent.
"""
from __future__ import annotations

import sqlite3

from lib import insurance_gov as ig


# --------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------
def _connect(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path)


def has_insurance_gov_data(db_path: str, idcode: str) -> bool:
    """True when the regulator dataset carries ANY year for this company."""
    try:
        con = _connect(db_path)
        try:
            r = con.execute(
                "SELECT 1 FROM insurance_statements WHERE IdCode=? LIMIT 1",
                (str(idcode),),
            ).fetchone()
            return r is not None
        finally:
            con.close()
    except sqlite3.OperationalError:
        return False  # table not present in this DB


def insurance_gov_years(db_path: str, idcode: str) -> list[int]:
    """Sorted fiscal years available for this company in the regulator dataset."""
    try:
        con = _connect(db_path)
        try:
            rows = con.execute(
                "SELECT DISTINCT FVYear FROM insurance_statements WHERE IdCode=? "
                "ORDER BY FVYear",
                (str(idcode),),
            ).fetchall()
            return [int(r[0]) for r in rows]
        finally:
            con.close()
    except sqlite3.OperationalError:
        return []


def _load(db_path: str, idcode: str, years: list[int], statement: str) -> dict:
    """Return ``{code: {year: value}}`` for one statement of one company."""
    out: dict[str, dict[int, float]] = {}
    if not years:
        return out
    placeholders = ",".join("?" * len(years))
    try:
        con = _connect(db_path)
        try:
            rows = con.execute(
                f"SELECT LineCode, FVYear, Value FROM insurance_statements "
                f"WHERE IdCode=? AND Statement=? AND FVYear IN ({placeholders})",
                (str(idcode), statement, *years),
            ).fetchall()
        finally:
            con.close()
    except sqlite3.OperationalError:
        return out
    for code, yr, val in rows:
        out.setdefault(str(code), {})[int(yr)] = float(val or 0.0)
    return out


# --------------------------------------------------------------------------
# Small value helpers (every total is built from form codes)
# --------------------------------------------------------------------------
def _row(vals: dict, code: str, years: list[int], sign: float = 1.0) -> dict:
    src = vals.get(code, {})
    return {y: sign * src.get(y, 0.0) for y in years}


def _sum_codes(vals: dict, codes, years: list[int], sign: float = 1.0) -> dict:
    out = {y: 0.0 for y in years}
    for code in codes:
        src = vals.get(code, {})
        for y in years:
            out[y] += src.get(y, 0.0)
    if sign != 1.0:
        out = {y: sign * v for y, v in out.items()}
    return out


def _combine(years: list[int], *parts) -> dict:
    """Element-wise sum of several {year: value} dicts."""
    out = {y: 0.0 for y in years}
    for p in parts:
        for y in years:
            out[y] += p.get(y, 0.0)
    return out


def _nonzero(d: dict) -> bool:
    return any(v not in (0, None) for v in d.values())


# --------------------------------------------------------------------------
# Income statement
# --------------------------------------------------------------------------
def build_insurance_gov_is_sections(db_path: str, idcode: str, years: list[int]) -> list[dict]:
    """Insurer P&L from the regulator return, ordered section dicts.

    Layout (every subtotal is a form code; the build-up rows reconcile to it):
        Net Earned Premium / Insurance Revenue   (00050 + 00190)   [detail: GWP, ceded, ΔUPR]
        Net Insurance Claims & Benefits          (-(00110 + 00250)) [detail: claims, Δreserve, regress]
        Net Commission Income / (Expense)        (00130 + 00300)
        Accrued Bonuses                          (-(00120 + 00290))   (if present)
        Change in Life Insurance Reserve, net    (00280)              (if present)
        Net Underwriting Result                  (00320)            ← bar
        Net Result from Pension Activity         (00360)              (if present)
        Investment Income                        (00460)            [detail: per source]
        Operating & Administrative Expenses      (-(00470..00520))  [detail: per line]
        Other Income / (Expense), net            (00530)              (if present)
        Profit Before Tax                        (00540)            ← bar
        Income Tax                               (-(00550))
        Net Profit / (Loss)                      (00560)            ← final
    """
    years = sorted(years)
    v = _load(db_path, idcode, years, "IS")
    if not v:
        return []
    sections: list[dict] = []

    def emit(label, kind, total, detail=None, **extra):
        sections.append({"label": label, "kind": kind, "total": total,
                         "detail": detail or [], "rolled_up": [], **extra})

    # --- Net earned premium / insurance revenue (income) ---
    nep = _sum_codes(v, ig.IS_NET_EARNED_PREMIUM, years)
    gwp = _sum_codes(v, ig.IS_GROSS_WRITTEN_PREMIUM, years)
    ceded = _sum_codes(v, ("00020", "00160"), years, sign=-1.0)
    d_upr = _combine(years,
                     _sum_codes(v, ("00030", "00170"), years, sign=-1.0),
                     _sum_codes(v, ("00040", "00180"), years))
    rev_detail = [("Gross written premium", gwp),
                  ("Reinsurance premium ceded", ceded),
                  ("Change in unearned premium reserve, net", d_upr)]
    emit("Net Earned Premium / Insurance Revenue", "section_with_detail", nep,
         [(n, d) for n, d in rev_detail if _nonzero(d)],
         bar="income")

    # --- Net insurance claims & benefits (cost) ---
    net_claims = _sum_codes(v, ig.IS_NET_CLAIMS, years, sign=-1.0)
    claims_paid = _combine(years,
                           _sum_codes(v, ("00060", "00200"), years, sign=-1.0),
                           _sum_codes(v, ("00070", "00210"), years))
    d_loss = _combine(years,
                      _sum_codes(v, ("00080", "00220"), years, sign=-1.0),
                      _sum_codes(v, ("00090", "00230"), years))
    regress = _sum_codes(v, ("00100", "00240"), years)
    claims_detail = [("Claims paid, net of reinsurance", claims_paid),
                     ("Change in loss reserve, net", d_loss),
                     ("Income from regress & salvage", regress)]
    emit("Net Insurance Claims & Benefits", "section_with_detail", net_claims,
         [(n, d) for n, d in claims_detail if _nonzero(d)])

    # --- Commission / bonuses / life reserve (feed underwriting result) ---
    commission = _sum_codes(v, ("00130", "00300"), years)
    if _nonzero(commission):
        emit("Net Commission Income / (Expense)", "derived_total", commission)
    bonuses = _sum_codes(v, ("00120", "00290"), years, sign=-1.0)
    if _nonzero(bonuses):
        emit("Accrued Bonuses", "derived_total", bonuses)
    life_reserve = _row(v, "00280", years)
    if _nonzero(life_reserve):
        emit("Change in Life Insurance Reserve, net", "derived_total", life_reserve)

    # --- Underwriting result (form 00320) ---
    emit("Net Underwriting Result", "derived_total", _row(v, ig.IS_UW_RESULT_TOTAL, years),
         bar="total")

    # --- Pension result (rare) ---
    pension = _row(v, "00360", years)
    if _nonzero(pension):
        emit("Net Result from Pension Activity", "derived_total", pension)

    # --- Investment income (00460) with per-source detail ---
    inv_total = _row(v, ig.IS_INVESTMENT_INCOME, years)
    inv_codes = ("00370", "00380", "00390", "00400", "00410",
                 "00420", "00430", "00440", "00450")
    inv_detail = [(ig.IS_CODES[c][2], _row(v, c, years)) for c in inv_codes]
    emit("Investment Income", "section_with_detail", inv_total,
         [(n, d) for n, d in inv_detail if _nonzero(d)])

    # --- Operating & administrative expenses (00470..00520) ---
    opex_codes = ("00470", "00480", "00490", "00500", "00510", "00520")
    opex_total = _sum_codes(v, opex_codes, years, sign=-1.0)
    opex_detail = [(ig.IS_CODES[c][2], _row(v, c, years, sign=-1.0)) for c in opex_codes]
    emit("Operating & Administrative Expenses", "section_with_detail", opex_total,
         [(n, d) for n, d in opex_detail if _nonzero(d)])

    # --- Other income/(expense), net ---
    other = _row(v, "00530", years)
    if _nonzero(other):
        emit("Other Income / (Expense), net", "derived_total", other)

    # --- PBT / tax / net profit (form codes) ---
    emit("Profit Before Tax", "derived_total", _row(v, ig.IS_PBT, years), bar="total")
    emit("Income Tax", "derived_total", _row(v, ig.IS_INCOME_TAX, years, sign=-1.0))
    emit("Net Profit / (Loss)", "final_total", _row(v, ig.IS_NET_PROFIT, years), bar="net")

    return sections


# --------------------------------------------------------------------------
# Balance sheet
# --------------------------------------------------------------------------
def build_insurance_gov_bs_sections(db_path: str, idcode: str, years: list[int]) -> list[dict]:
    """Insurer balance sheet from the regulator return (assets / liabilities / equity)."""
    years = sorted(years)
    v = _load(db_path, idcode, years, "BS")
    if not v:
        return []
    sections: list[dict] = []

    def detail_for(codes):
        out = []
        for c in codes:
            d = _row(v, c, years)
            if _nonzero(d):
                out.append((ig.BS_CODES[c][2], d))
        return out

    asset_codes = [f"{i:05d}" for i in range(10, 190, 10)]       # 00010..00180
    liab_codes = [f"{i:05d}" for i in range(200, 300, 10)]        # 00200..00290
    equity_codes = [f"{i:05d}" for i in range(310, 370, 10)]      # 00310..00360

    sections.append({
        "label": "TOTAL ASSETS", "kind": "section_with_detail",
        "total": _row(v, ig.BS_TOTAL_ASSETS, years),
        "detail": detail_for(asset_codes), "bar": "total",
    })
    sections.append({
        "label": "TOTAL LIABILITIES", "kind": "section_with_detail",
        "total": _row(v, ig.BS_TOTAL_LIABILITIES, years),
        "detail": detail_for(liab_codes), "bar": "total",
    })
    sections.append({
        "label": "TOTAL EQUITY", "kind": "section_with_detail",
        "total": _row(v, ig.BS_TOTAL_EQUITY, years),
        "detail": detail_for(equity_codes), "bar": "total",
    })
    sections.append({
        "label": "TOTAL LIABILITIES & EQUITY", "kind": "derived_total",
        "total": _row(v, "00380", years), "detail": [], "bar": "total",
    })
    return sections


# --------------------------------------------------------------------------
# Underwriting KPIs
# --------------------------------------------------------------------------
def _safe_div(n, d):
    if n is None or d in (None, 0):
        return None
    return n / d


def compute_insurance_gov_ratios(db_path: str, idcode: str, years: list[int]) -> list[dict]:
    """Non-life underwriting KPIs on a net-earned-premium basis (row shape matches
    ``compute_insurance_ratios``: ``{"Ratio", <year>:.., "_fmt"}``)."""
    years = sorted(years)
    v = _load(db_path, idcode, years, "IS")
    bs = _load(db_path, idcode, years, "BS")
    if not v:
        return []

    nep = _sum_codes(v, ig.IS_NET_EARNED_PREMIUM, years)
    gwp = _sum_codes(v, ig.IS_GROSS_WRITTEN_PREMIUM, years)
    claims = _sum_codes(v, ig.IS_NET_CLAIMS, years)              # positive cost
    commission = _sum_codes(v, ("00130", "00300"), years)
    admin = _sum_codes(v, ("00470", "00480", "00490", "00500", "00510"), years)
    uw = _row(v, ig.IS_UW_RESULT_TOTAL, years)
    inv = _row(v, ig.IS_INVESTMENT_INCOME, years)
    npft = _row(v, ig.IS_NET_PROFIT, years)
    equity = _row(bs, ig.BS_TOTAL_EQUITY, years)
    assets = _row(bs, ig.BS_TOTAL_ASSETS, years)

    def per_year(fn):
        return {y: fn(y) for y in years}

    rows: list[dict] = []

    def emit(label, fmt, d):
        if all(x is None for x in d.values()):
            return
        rec = {"Ratio": label, "_fmt": fmt}
        rec.update({y: d[y] for y in years})
        rows.append(rec)

    nep_d = {y: (nep[y] or None) for y in years}
    loss = per_year(lambda y: _safe_div(abs(claims[y]), nep_d[y]))
    acq = per_year(lambda y: _safe_div(abs(commission[y]), nep_d[y]))
    admin_r = per_year(lambda y: _safe_div(abs(admin[y]), nep_d[y]))
    expense = per_year(lambda y: None if acq[y] is None and admin_r[y] is None
                       else (acq[y] or 0) + (admin_r[y] or 0))
    combined = per_year(lambda y: None if loss[y] is None and expense[y] is None
                        else (loss[y] or 0) + (expense[y] or 0))
    retention = per_year(lambda y: _safe_div(nep[y], gwp[y] or None))
    uw_margin = per_year(lambda y: _safe_div(uw[y], nep_d[y]))
    inv_yield = per_year(lambda y: _safe_div(inv[y], nep_d[y]))
    net_margin = per_year(lambda y: _safe_div(npft[y], nep_d[y]))
    roe = per_year(lambda y: _safe_div(npft[y], equity[y] or None))
    roa = per_year(lambda y: _safe_div(npft[y], assets[y] or None))

    emit("Loss Ratio", "pct", loss)
    emit("Acquisition / Commission Ratio", "pct", acq)
    emit("Admin Expense Ratio", "pct", admin_r)
    emit("Expense Ratio", "pct", expense)
    emit("Combined Ratio", "pct", combined)
    emit("Retention Ratio", "pct", retention)
    emit("Underwriting Margin", "pct", uw_margin)
    emit("Investment Income / Net Premiums", "pct", inv_yield)
    emit("Net Margin", "pct", net_margin)
    emit("ROE", "pct", roe)
    emit("ROA", "pct", roa)
    return rows
