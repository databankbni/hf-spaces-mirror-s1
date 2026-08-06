"""Streamlit cache layer for DB-backed lookups.

Sprint 4.2 extracts the ~16 ``@st.cache_data`` helpers that used to live at the
top of ``app.py`` into this dedicated module. Two goals:

1. **Shrink ``app.py``.** Pure structural move — no behaviour change.
2. **Auto-invalidate when the DB file is replaced.** Streamlit's cache keys on
   argument identity. Today every helper takes ``db_path: str`` as its first
   arg — when the DB file is replaced in-place, ``db_path`` doesn't change, so
   caches stay stale until manually cleared with a "Refresh data" button.

   Fix: each helper has two layers. A private ``_X_cached(db_version, ...)``
   primitive carries an mtime-based version token as its first positional
   argument; Streamlit hashes it, so a new mtime → new cache key → fresh read.
   The public ``X(db_path, ...)`` wrapper computes the token and forwards.

   Call sites still pass ``db_path`` as before; the version token is
   transparent to callers.
"""

from __future__ import annotations

import os
import sqlite3

import pandas as pd
import streamlit as st

from lib.data_loader import (
    get_companies,
    get_years_available,
    get_form_type as _get_form_type,
    get_report_pdf_urls as _get_report_pdf_urls,
    get_company_ownership as _get_company_ownership,
    get_dividends as _get_dividends,
    get_ownership_edges as _get_ownership_edges,
    get_consolidated_idcodes as _get_consolidated_idcodes,
    get_consolidated_company_years as _get_consolidated_company_years,
    get_insurance_gov_source_urls as _get_insurance_gov_source_urls,
    get_filing_meta as _get_filing_meta,
    get_latest_filing_meta as _get_latest_filing_meta,
    get_revaluation_rows as _get_revaluation_rows,
    universe_stats as _universe_stats_impl,
)
from lib.filing_provenance import revaluation_years as _revaluation_years
from lib.income_statement import build_is_sections
from lib.balance_sheet import build_bs_sections
from lib.cash_flow import build_cf_sections
from lib.ratios import build_ratios_table
from lib.ifrs16 import compute_implied_lease_cost
from lib.screener import build_metrics_table


# ---------------------------------------------------------------------------
# Cache-key strategy
# ---------------------------------------------------------------------------

def _db_version(db_path: str) -> str:
    """Return a cache-key token that changes whenever the DB file is replaced.

    Uses ``st_mtime_ns`` so even sub-second replacements bust the cache. If
    the file is missing we return a stable sentinel — the underlying call
    will surface the real error.
    """
    try:
        return str(os.stat(db_path).st_mtime_ns)
    except OSError:
        return "missing"


# ---------------------------------------------------------------------------
# Companies / years
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _companies_cached(db_version: str, db_path: str):
    return get_companies(db_path)


def companies(db_path: str):
    return _companies_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False)
def _years_cached(db_version: str, db_path: str, idcode: str, table: str):
    return get_years_available(db_path, idcode, table=table)


def years(db_path: str, idcode: str, table: str = "financial_data"):
    return _years_cached(_db_version(db_path), db_path, idcode, table)


@st.cache_data(show_spinner=False)
def _report_pdf_urls_cached(db_version: str, db_path: str, idcode: str) -> dict[int, str]:
    return _get_report_pdf_urls(db_path, idcode)


def report_pdf_urls(db_path: str, idcode: str) -> dict[int, str]:
    """Precomputed reportal.ge PDF links for a company, keyed by year."""
    return _report_pdf_urls_cached(_db_version(db_path), db_path, idcode)


@st.cache_data(show_spinner=False)
def _company_ownership_cached(db_version: str, db_path: str, idcode: str) -> dict | None:
    return _get_company_ownership(db_path, idcode)


def company_ownership(db_path: str, idcode: str) -> dict | None:
    """Precomputed companyinfo.ge ownership detail for a company (or None).

    Same dict shape as ``lib.companyinfo.fetch_company_detail``, served from the
    ``company_ownership`` table so the Single-Company page needs no live API call.
    """
    return _company_ownership_cached(_db_version(db_path), db_path, idcode)


@st.cache_data(show_spinner=False)
def _dividends_cached(db_version: str, db_path: str, idcode: str) -> dict:
    return _get_dividends(db_path, idcode)


def dividends(db_path: str, idcode: str) -> dict:
    """Dividends declared per year from ``equity_movements`` (SOCE exports).

    ``{"dividends": {FVYear: gel, negative = distribution}, "covered": {FVYear}}``;
    empty when the DB predates the feature. See ``lib.data_loader.get_dividends``.
    """
    return _dividends_cached(_db_version(db_path), db_path, idcode)


@st.cache_data(show_spinner=False)
def _ownership_edges_cached(db_version: str, db_path: str) -> list[dict]:
    return _get_ownership_edges(db_path)


def ownership_edges(db_path: str) -> list[dict]:
    """All company->company ownership edges (see lib.ownership). Cached per DB."""
    return _ownership_edges_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False)
def _consolidated_idcodes_cached(db_version: str, db_path: str) -> set[str]:
    return _get_consolidated_idcodes(db_path)


def consolidated_idcodes(db_path: str) -> set[str]:
    """IdCodes whose latest filing is consolidated (companies.LatestIsConsolidated)."""
    return _consolidated_idcodes_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False)
def _consolidated_company_years_cached(
    db_version: str, db_path: str
) -> set[tuple[str, int]]:
    return _get_consolidated_company_years(db_path)


@st.cache_data(show_spinner=False)
def _individual_basis_idcodes_cached(db_version: str, db_path: str) -> frozenset:
    conn = sqlite3.connect(db_path)
    try:
        have = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='financial_data_individual'").fetchone()
        if not have:
            return frozenset()
        return frozenset(
            r[0] for r in conn.execute(
                "SELECT DISTINCT IdCode FROM financial_data_individual"))
    finally:
        conn.close()


@st.cache_data(show_spinner=False)
def _individual_panel_available_cached(db_version: str, db_path: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        return bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='metrics_panel_individual'").fetchone())
    finally:
        conn.close()


def individual_panel_available(db_path: str) -> bool:
    """True when the individual-basis metrics twin exists in this DB — the
    Screener's basis control only renders then, so a DB without the table
    (e.g. an old deployed copy) simply never offers the option."""
    return _individual_panel_available_cached(_db_version(db_path), db_path)


def individual_basis_idcodes(db_path: str) -> frozenset:
    """IdCodes whose INDIVIDUAL-basis statements are available in the sidecar.

    Empty when the DB has no ``financial_data_individual`` table (e.g. the
    deployed copy before the basis toggle ships its data) — the Single-Company
    basis toggle only renders for companies in this set, so the feature
    degrades to invisible instead of erroring.
    """
    return _individual_basis_idcodes_cached(_db_version(db_path), db_path)


def consolidated_company_years(db_path: str) -> set[tuple[str, int]]:
    """``(IdCode, FVYear)`` filed on a consolidated basis THAT YEAR (filing_basis).

    Empty when the table is missing — callers fall back to
    :func:`consolidated_idcodes`. See lib/consolidation.py for why the per-year
    fact matters to the de-dup.
    """
    return _consolidated_company_years_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False)
def _insurance_gov_source_urls_cached(db_version: str, db_path: str, idcode: str) -> dict[int, str]:
    return _get_insurance_gov_source_urls(db_path, idcode)


def insurance_gov_source_urls(db_path: str, idcode: str) -> dict[int, str]:
    """insurance.gov.ge source-XLSX links for a regulator insurer, keyed by year."""
    return _insurance_gov_source_urls_cached(_db_version(db_path), db_path, idcode)


# ---------------------------------------------------------------------------
# Income statement / subtotals / balance sheet / ratios
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _is_sections_cached(
    db_version: str, db_path: str, idcode: str, years_tuple: tuple[int, ...],
    table: str,
) -> list[dict]:
    return build_is_sections(db_path, idcode, list(years_tuple), table=table)


def is_sections(db_path: str, idcode: str, years_tuple: tuple[int, ...],
                table: str = "financial_data") -> list[dict]:
    return _is_sections_cached(_db_version(db_path), db_path, idcode, years_tuple, table)


@st.cache_data(show_spinner=False)
def _bs_sections_cached(
    db_version: str, db_path: str, idcode: str, years_tuple: tuple[int, ...],
    table: str,
) -> list[dict]:
    return build_bs_sections(db_path, idcode, list(years_tuple), table=table)


def bs_sections(db_path: str, idcode: str, years_tuple: tuple[int, ...],
                table: str = "financial_data") -> list[dict]:
    return _bs_sections_cached(_db_version(db_path), db_path, idcode, years_tuple, table)


@st.cache_data(show_spinner=False)
def _cf_sections_cached(
    db_version: str, db_path: str, idcode: str, years_tuple: tuple[int, ...], include_fcf: bool,
    table: str,
) -> list[dict]:
    return build_cf_sections(db_path, idcode, list(years_tuple), include_fcf=include_fcf,
                             table=table)


def cf_sections(
    db_path: str, idcode: str, years_tuple: tuple[int, ...], include_fcf: bool = True,
    table: str = "financial_data",
) -> list[dict]:
    return _cf_sections_cached(_db_version(db_path), db_path, idcode, years_tuple, include_fcf,
                               table)


@st.cache_data(show_spinner=False)
def _ratios_cached(
    db_version: str, db_path: str, idcode: str, years_tuple: tuple[int, ...],
    table: str,
) -> pd.DataFrame:
    return build_ratios_table(db_path, idcode, list(years_tuple), table=table)


def ratios(db_path: str, idcode: str, years_tuple: tuple[int, ...],
           table: str = "financial_data") -> pd.DataFrame:
    return _ratios_cached(_db_version(db_path), db_path, idcode, years_tuple, table)


# ---------------------------------------------------------------------------
# IFRS 16 implied lease costs
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _implied_costs_cached(
    db_version: str,
    db_path: str,
    idcode: str,
    years_tuple: tuple[int, ...],
    assumed_term: float,
    interest_rate: float,
    table: str,
) -> dict:
    return compute_implied_lease_cost(
        db_path,
        idcode,
        list(years_tuple),
        assumed_term=assumed_term,
        interest_rate=interest_rate,
        table=table,
    )


def implied_costs(
    db_path: str,
    idcode: str,
    years_tuple: tuple[int, ...],
    assumed_term: float,
    interest_rate: float,
    table: str = "financial_data",
) -> dict:
    return _implied_costs_cached(
        _db_version(db_path), db_path, idcode, years_tuple, assumed_term, interest_rate,
        table,
    )


# ---------------------------------------------------------------------------
# Company description (custom SQL, not a lib wrapper)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def _company_description_cached(
    db_version: str, db_path: str, idcode: str
) -> dict | None:
    """Read the curated description + sources + sector for a single company.

    Returns ``{"description": str, "sources": str (json), "updated_at": str,
    "sector": str}`` when the company has been enriched, else ``None``.
    Cached so the Single Company view doesn't hit the DB on every rerun.
    """
    conn = sqlite3.connect(db_path)
    try:
        # Defensive against stale DBs that pre-date the enrichment columns
        # (e.g. Space cached an older copy from the Dataset). Probe the schema
        # and only SELECT columns that exist; bail early if Description itself
        # is missing rather than letting the SQL error bubble to the UI.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "Description" not in cols:
            return None
        select_parts = ["Description"]
        for opt in ("DescriptionSources", "DescriptionUpdatedAt", "Sector", "SubSector"):
            if opt in cols:
                select_parts.append(opt)
            else:
                select_parts.append("NULL")
        select = ", ".join(select_parts)
        row = conn.execute(
            f"SELECT {select} FROM companies WHERE IdCode = ?",
            (idcode,),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    # SELECT always returns 5 columns now — missing schema columns are
    # padded with NULL in the SELECT list, so positions are stable.
    return {
        "description": row[0],
        "sources": row[1] or "[]",
        "updated_at": row[2] or "",
        "sector": row[3] or "",
        "sub_sector": row[4] or "",
    }


def company_description(db_path: str, idcode: str) -> dict | None:
    return _company_description_cached(_db_version(db_path), db_path, idcode)


@st.cache_data(show_spinner=False, ttl=3600)
def _company_sector_map_cached(db_version: str, db_path: str) -> dict[str, str]:
    from lib.data_loader import get_sectors

    return get_sectors(db_path)


def company_sector_map(db_path: str) -> dict[str, str]:
    """``{IdCode: Sector}`` for every classified company (cached, DB-versioned)."""
    return _company_sector_map_cached(_db_version(db_path), db_path)


# ---------------------------------------------------------------------------
# Screener metrics table + helpers
# ---------------------------------------------------------------------------

@st.cache_data(
    show_spinner="Loading screener metrics — this only happens once.",
    ttl=3600,
)
def _metrics_table_cached(db_version: str, db_path: str,
                          panel_table: str = "metrics_panel") -> pd.DataFrame:
    """Read the precomputed ``metrics_panel`` table — all columns, including growth.

    Sprint 2c: the growth/CAGR columns (Revenue_YoY, Revenue_2yrCAGR, …) are
    materialized into ``metrics_panel`` at build time by
    ``scripts/build_metrics_panel.py::_populate_growth_columns``. Read path
    drops to a single ``SELECT *`` — no runtime growth recompute. Each cell is
    the growth ending in that row's FVYear, so slicing the frame by year gives
    that year's growth (true only from 2026-07-30 — before that the builder
    broadcast the company's latest-year scalar onto every row).

    Cold call goes from ~18.5s (Sprint 2b — dominated by
    ``compute_growth_columns``) to <1s, completing the 144x speedup the
    Sprint 2b cutover promised.
    """
    conn = sqlite3.connect(db_path)
    try:
        if panel_table not in ("metrics_panel", "metrics_panel_individual"):
            raise ValueError(f"unsupported panel table: {panel_table!r}")
        df = pd.read_sql_query(f"SELECT * FROM {panel_table}", conn)
    finally:
        conn.close()
    if df.empty:
        # Preserve the MultiIndex shape so downstream .xs() / .loc[] calls
        # don't crash on an empty result.
        if "IdCode" in df.columns and "FVYear" in df.columns:
            return df.set_index(["IdCode", "FVYear"])
        return df

    return df.set_index(["IdCode", "FVYear"]).sort_index()


def metrics_table(db_path: str, panel_table: str = "metrics_panel") -> pd.DataFrame:
    return _metrics_table_cached(_db_version(db_path), db_path, panel_table)


@st.cache_data(show_spinner=False, ttl=3600)
def _panel_columns_for_idcodes_cached(
    db_version: str,
    db_path: str,
    idcodes_tuple: tuple[str, ...],
    columns_tuple: tuple[str, ...],
) -> pd.DataFrame:
    """Slice the requested ``metrics_panel`` columns for a set of companies.

    Returns a frame indexed by (IdCode, FVYear) with one column per requested
    metric column (only those that actually exist in the panel are returned).
    Used by Sector View / Compare to surface user-picked metric columns beyond
    the four the recompute path carries. Values are the raw (non-IFRS-adjusted)
    panel numbers — money in GEL, margins/returns as decimals, ratios as-is.

    Cached by (db_version, db_path, idcodes, columns) so flipping the picker or
    the company selection is an incremental cache miss, not a 51k-row re-slice
    on every Streamlit rerun.
    """
    mt = _metrics_table_cached(db_version, db_path)
    if mt.empty:
        return mt
    keep_cols = [c for c in columns_tuple if c in mt.columns]
    if not keep_cols:
        return mt.iloc[0:0][[]]
    want = set(idcodes_tuple)
    present = mt.index.get_level_values("IdCode").isin(want)
    return mt.loc[present, keep_cols]


def panel_columns_for_idcodes(
    db_path: str, idcodes: list[str], columns: list[str]
) -> pd.DataFrame:
    """Public wrapper: (IdCode, FVYear)-indexed frame of the requested metric
    columns for the given companies, read from the precomputed panel."""
    return _panel_columns_for_idcodes_cached(
        _db_version(db_path), db_path, tuple(idcodes), tuple(columns)
    )


@st.cache_data(show_spinner=False, ttl=3600)
def _latest_revenue_by_idcode_cached(
    db_version: str, db_path: str
) -> dict[str, float]:
    """Latest non-zero Revenue per company, read straight from the
    precomputed ``company_search`` table (Sprint 2b cutover). Used to sort
    typeahead suggestions by size so the largest matches surface first.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT IdCode, LatestRevenue FROM company_search "
            "WHERE LatestRevenue IS NOT NULL AND LatestRevenue > 0"
        ).fetchall()
    finally:
        conn.close()
    return {idc: float(rev) for idc, rev in rows}


def latest_revenue_by_idcode(db_path: str) -> dict[str, float]:
    return _latest_revenue_by_idcode_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False, ttl=3600)
def _finder_universe_cached(db_version: str, db_path: str) -> pd.DataFrame:
    """One row per company for the Home finder (T0.5): the ``company_search``
    row joined to that company's LATEST ``metrics_panel`` year for the size
    columns. ~9k rows, so the whole frame is cached and filtered in-memory
    by ``lib.finder``."""
    conn = sqlite3.connect(db_path)
    try:
        return pd.read_sql_query(
            """
            SELECT cs.IdCode, cs.CompanyName, cs.Sector, cs.SubSector,
                   cs.LatestFVYear, cs.FormType,
                   mp.Revenue, mp.NetProfit, mp.TotalAssets
            FROM company_search cs
            LEFT JOIN metrics_panel mp
              ON mp.IdCode = cs.IdCode AND mp.FVYear = cs.LatestFVYear
            """,
            conn,
        )
    finally:
        conn.close()


def finder_universe(db_path: str) -> pd.DataFrame:
    return _finder_universe_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False, ttl=3600)
def _universe_stats_cached(db_version: str, db_path: str) -> dict:
    return _universe_stats_impl(db_path)


def universe_stats(db_path: str) -> dict:
    return _universe_stats_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False, ttl=3600)
def _latest_metrics_for_idcodes_cached(
    db_version: str, db_path: str, idcodes: tuple[str, ...]
) -> dict:
    """Latest-year metrics per IdCode, drawn from the cached metrics table.

    Returns {idcode: {Revenue, EBITDA, NetProfit, TotalAssets, TotalCash,
    TotalDebt, TotalEquity}} only for idcodes present in the metrics table
    (i.e. companies we have financials for). Used by the person portfolio.
    """
    mt = _metrics_table_cached(db_version, db_path)
    if mt.empty:
        return {}
    wanted = ("Revenue", "EBITDA", "NetProfit", "TotalAssets",
              "TotalCash", "TotalDebt", "TotalEquity")
    present = set(mt.index.get_level_values("IdCode"))
    out: dict[str, dict] = {}
    for idc in idcodes:
        if idc not in present:
            continue
        sub = mt.xs(idc, level="IdCode").sort_index()
        latest = sub.iloc[-1]
        out[idc] = {m: float(latest.get(m) or 0.0) for m in wanted}
    return out


def latest_metrics_for_idcodes(db_path: str, idcodes: tuple[str, ...]) -> dict:
    return _latest_metrics_for_idcodes_cached(_db_version(db_path), db_path, idcodes)


# ---------------------------------------------------------------------------
# Macro: Georgia nominal GDP (current prices), for sector GDP-penetration
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def _gdp_by_year_cached(db_version: str, db_path: str) -> dict[int, dict]:
    """Read ``macro_gdp`` into ``{year: {"gdp_mln": float, "per_capita": float|None}}``.

    Returns ``{}`` when the table is missing (old DB that pre-dates the GDP
    import) so the Sector view degrades gracefully instead of crashing.
    GDP is stored in MILLION GEL; callers that compare against
    ``metrics_panel`` revenue (absolute GEL) must multiply by 1e6.
    """
    conn = sqlite3.connect(db_path)
    try:
        names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "macro_gdp" not in names:
            return {}
        rows = conn.execute(
            "SELECT year, gdp_current_mln_gel, gdp_per_capita_gel FROM macro_gdp"
        ).fetchall()
    finally:
        conn.close()
    return {
        int(y): {
            "gdp_mln": float(gdp),
            "per_capita": (float(pc) if pc is not None else None),
        }
        for y, gdp, pc in rows
        if gdp is not None
    }


def gdp_by_year(db_path: str) -> dict[int, dict]:
    return _gdp_by_year_cached(_db_version(db_path), db_path)


# ---------------------------------------------------------------------------
# Form type
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def _form_type_cached(db_version: str, db_path: str, idcode: str) -> str:
    """Cached wrapper around lib.data_loader.get_form_type."""
    return _get_form_type(db_path, idcode)


def form_type(db_path: str, idcode: str) -> str:
    return _form_type_cached(_db_version(db_path), db_path, idcode)


# ---------------------------------------------------------------------------
# Filing provenance (category / reporting standard / audit requirement)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def _filing_meta_cached(db_version: str, db_path: str, idcode: str) -> dict[int, dict]:
    """Cached wrapper around lib.data_loader.get_filing_meta (per-year)."""
    return _get_filing_meta(db_path, idcode)


def filing_meta(db_path: str, idcode: str) -> dict[int, dict]:
    return _filing_meta_cached(_db_version(db_path), db_path, idcode)


@st.cache_data(show_spinner=False, ttl=3600)
def _latest_filing_meta_cached(db_version: str, db_path: str, idcode: str) -> dict:
    """Cached wrapper around lib.data_loader.get_latest_filing_meta (latest only)."""
    return _get_latest_filing_meta(db_path, idcode)


def latest_filing_meta(db_path: str, idcode: str) -> dict:
    return _latest_filing_meta_cached(_db_version(db_path), db_path, idcode)


@st.cache_data(show_spinner=False, ttl=3600)
def _revaluation_years_cached(db_version: str, db_path: str, idcode: str) -> set[int]:
    """Years with a non-zero PP&E revaluation reserve (IAS 16 revaluation model)."""
    return _revaluation_years(_get_revaluation_rows(db_path, idcode))


def revaluation_years(db_path: str, idcode: str) -> set[int]:
    return _revaluation_years_cached(_db_version(db_path), db_path, idcode)


# ---------------------------------------------------------------------------
# Auditors (Single-Company audit-status chip) — the RMS `auditors` table,
# FY2018-2024. See lib/auditors.py for the pure row-pick/label helpers this
# feeds.
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def _audit_engagements_cached(db_version: str, db_path: str, idcode: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        have = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='auditors'"
        ).fetchone()
        if not have:
            return []
        rows = conn.execute(
            "SELECT FVYear, IsConsolidated, OpinionCode, AuditFirm, "
            "PartnerFirstName, PartnerLastName, AuditorPayment "
            "FROM auditors WHERE IdCode = ? "
            "ORDER BY FVYear DESC, IsConsolidated DESC",
            (idcode,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "year": int(year),
            "is_consolidated": bool(is_cons),
            "opinion_code": opinion_code,
            "firm": firm,
            "partner_first": partner_first,
            "partner_last": partner_last,
            "fee": fee,
        }
        for year, is_cons, opinion_code, firm, partner_first, partner_last, fee in rows
    ]


def audit_engagements(db_path: str, idcode: str) -> list[dict]:
    """This company's ``auditors`` rows — year/basis/opinion/firm/partner/fee.

    Empty list when the ``auditors`` table is absent from the DB (the deployed
    copy may lack it) — the audit-status chip degrades to invisible instead of
    erroring, same pattern as ``individual_basis_idcodes`` above.
    """
    return _audit_engagements_cached(_db_version(db_path), db_path, idcode)


# ---------------------------------------------------------------------------
# Sector (for sector-specific statement layouts)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def _company_sector_cached(db_version: str, db_path: str, idcode: str) -> str:
    """Return companies.Sector for a single company ('' when unset/missing).

    Independent of the curated-Description gate in `company_description` — a
    company can have a Sector with no Description. Used by the Single Company
    view to pick the bank / insurance statement layout.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "Sector" not in cols:
            return ""
        row = conn.execute(
            "SELECT Sector FROM companies WHERE IdCode = ?", (idcode,)
        ).fetchone()
    finally:
        conn.close()
    return (row[0] if row and row[0] else "") or ""


def company_sector(db_path: str, idcode: str) -> str:
    return _company_sector_cached(_db_version(db_path), db_path, idcode)


# ---------------------------------------------------------------------------
# Typeahead options + screener frame reducer
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def _options_sorted_by_revenue_cached_impl(
    db_version: str, db_path: str
) -> list[str]:
    """Pre-computed list of `"{IdCode} — {Name}"` labels sorted by latest
    Revenue desc. Used by the typeahead picker so the largest matching
    companies surface first when the user types.

    Sprint 2b cutover: ``company_search`` already carries the latest revenue
    per company, so we let SQLite do the ordering in a single query rather
    than joining a Python dict against the companies list.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT IdCode, CompanyName FROM company_search "
            "ORDER BY LatestRevenue DESC NULLS LAST, IdCode"
        ).fetchall()
    finally:
        conn.close()
    return [f"{idc} — {name}" for idc, name in rows]


def options_sorted_by_revenue_cached(db_path: str) -> list[str]:
    return _options_sorted_by_revenue_cached_impl(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False, ttl=3600)
def _description_search_rows_cached_impl(
    db_version: str, db_path: str
) -> list[tuple[str, str, str]]:
    """``(IdCode, Description, description_lower)`` for enriched companies,
    sorted by latest Revenue desc.

    Company names are Georgian legal names, so ``companies.Description``
    (the plain-English enrichment blurb, ~1.6k rows) is the only surface an
    English query like "Tegeta" can hit. The global search dialog runs a
    second-pass substring match over these rows after the direct label match
    — same approach as ``mcp/tools.py::search_companies``. The lowercase copy
    is precomputed so the per-keystroke scan doesn't re-lower ~1.6k blurbs.

    Restricted to companies present in ``company_search`` (the searchable
    universe) and ordered by its LatestRevenue so hits surface largest-first.
    Returns ``[]`` when the DB pre-dates the enrichment columns.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "Description" not in cols:
            return []
        rows = conn.execute(
            "SELECT cs.IdCode, c.Description "
            "FROM company_search cs "
            "JOIN companies c ON c.IdCode = cs.IdCode "
            "WHERE c.Description IS NOT NULL AND c.Description != '' "
            "ORDER BY cs.LatestRevenue DESC NULLS LAST, cs.IdCode"
        ).fetchall()
    finally:
        conn.close()
    return [(idc, desc, desc.lower()) for idc, desc in rows]


def description_search_rows(db_path: str) -> list[tuple[str, str, str]]:
    return _description_search_rows_cached_impl(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False, ttl=3600)
def _reduce_screener_frame_cached_impl(
    db_version: str, db_path: str, scope: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Reduce the (IdCode, FVYear) metrics panel to one row per company per the
    chosen year scope. Cached by (db_path, scope) so adding/removing filter
    rows doesn't re-do the 51k-row groupby on every Streamlit rerun.
    """
    df = _metrics_table_cached(db_version, db_path)
    if df.empty:
        return df, {}
    # Growth/CAGR columns come attached to df from the panel, one value per
    # (IdCode, FVYear) — the growth ending in that row's year. The reductions
    # below therefore give: "Latest"/<year> → that year's growth (tail/loc carry
    # every column), "Average of last 3 years" → the mean of the last three
    # years' growth rates, consistent with how the scope treats every other
    # metric. Before 2026-07-30 the builder stored the company's latest-year
    # scalar on every row, so the <year> scope silently filtered on latest-year
    # growth.

    if scope == "Latest":
        df_sorted = df.sort_index(level=[0, 1])
        latest = df_sorted.groupby(level="IdCode").tail(1)
        year_used = {idc: int(year) for (idc, year) in latest.index}
        out = latest.reset_index(level="FVYear", drop=False)
        return out, year_used
    if scope == "Average of last 3 years":
        df_sorted = df.sort_index(level=[0, 1])
        last3 = df_sorted.groupby(level="IdCode").tail(3)
        avg = last3.groupby(level="IdCode").mean(numeric_only=True)
        latest_year = last3.reset_index().groupby("IdCode")["FVYear"].max()
        avg["FVYear"] = latest_year
        year_used = {idc: int(y) for idc, y in latest_year.items()}
        return avg, year_used
    # Specific year string
    try:
        year_int = int(scope)
    except (TypeError, ValueError):
        return df.iloc[0:0], {}
    sub = df.loc[df.index.get_level_values("FVYear") == year_int]
    if sub.empty:
        return (
            sub.reset_index(level="FVYear", drop=False).set_index(df.index.names[0]),
            {},
        )
    out = sub.reset_index(level="FVYear", drop=False)
    year_used = {idc: year_int for idc in out.index}
    return out, year_used


def reduce_screener_frame_cached(
    db_path: str, scope: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    return _reduce_screener_frame_cached_impl(_db_version(db_path), db_path, scope)


# ---------------------------------------------------------------------------
# Insurance market dataset (premium/claims by class) — the "Insurance" view
# ---------------------------------------------------------------------------
from lib import insurance_market_analytics as _ima  # noqa: E402


@st.cache_data(show_spinner=False, ttl=3600)
def _ins_market_years_cached(db_version: str, db_path: str) -> list[int]:
    return _ima.available_years(db_path)


def ins_market_years(db_path: str) -> list[int]:
    return _ins_market_years_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False, ttl=3600)
def _ins_market_totals_cached(db_version: str, db_path: str) -> pd.DataFrame:
    return _ima.market_totals(db_path)


def ins_market_totals(db_path: str) -> pd.DataFrame:
    return _ins_market_totals_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False, ttl=3600)
def _ins_market_uw_profit_cached(db_version: str, db_path: str) -> pd.DataFrame:
    return _ima.market_uw_profit(db_path)


def ins_market_uw_profit(db_path: str) -> pd.DataFrame:
    return _ins_market_uw_profit_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False, ttl=3600)
def _ins_class_structure_cached(db_version: str, db_path: str, year: int) -> pd.DataFrame:
    return _ima.class_structure(db_path, year)


def ins_class_structure(db_path: str, year: int) -> pd.DataFrame:
    return _ins_class_structure_cached(_db_version(db_path), db_path, year)


@st.cache_data(show_spinner=False, ttl=3600)
def _ins_class_dynamics_cached(db_version: str, db_path: str) -> pd.DataFrame:
    return _ima.class_dynamics(db_path)


def ins_class_dynamics(db_path: str) -> pd.DataFrame:
    return _ins_class_dynamics_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False, ttl=3600)
def _ins_company_table_cached(db_version: str, db_path: str, year: int) -> pd.DataFrame:
    return _ima.company_table(db_path, year)


def ins_company_table(db_path: str, year: int) -> pd.DataFrame:
    return _ins_company_table_cached(_db_version(db_path), db_path, year)


@st.cache_data(show_spinner=False, ttl=3600)
def _ins_company_class_mix_cached(db_version: str, db_path: str, idcode: str) -> pd.DataFrame:
    return _ima.company_class_mix(db_path, idcode)


def ins_company_class_mix(db_path: str, idcode: str) -> pd.DataFrame:
    return _ins_company_class_mix_cached(_db_version(db_path), db_path, idcode)


@st.cache_data(show_spinner=False, ttl=3600)
def _ins_company_timeseries_cached(db_version: str, db_path: str, idcode: str) -> pd.DataFrame:
    return _ima.company_timeseries(db_path, idcode)


def ins_company_timeseries(db_path: str, idcode: str) -> pd.DataFrame:
    return _ins_company_timeseries_cached(_db_version(db_path), db_path, idcode)


@st.cache_data(show_spinner=False, ttl=3600)
def _ins_market_hhi_cached(db_version: str, db_path: str, year: int) -> float | None:
    return _ima.market_hhi(db_path, year)


def ins_market_hhi(db_path: str, year: int) -> float | None:
    return _ins_market_hhi_cached(_db_version(db_path), db_path, year)


def ins_has_market_data(db_path: str) -> bool:
    return _ima.has_market_data(db_path)


# ---------------------------------------------------------------------------
# Owners / people index (views/people.py + the person dialog)
# ---------------------------------------------------------------------------
# `st.cache_resource`, not `st.cache_data`, for both of these. cache_data hands
# back a fresh COPY of its value on every call, which for a ~16k-person nested
# dict costs more per rerun than the widget interaction that triggered it;
# cache_resource returns the one object. Safe because both structures are
# treated as read-only downstream (lib/people.py only ever builds new dicts from
# them). Invalidation still rides on the `db_version` token, so replacing the DB
# file yields a new cache key exactly as it does for the cache_data helpers.

@st.cache_resource(show_spinner="Building the ownership index…", max_entries=2)
def _person_index_cached(db_version: str, db_path: str) -> dict:
    from lib.companyinfo import summarize_affiliations
    from lib.data_loader import iter_ownership_details
    from lib.people import build_person_index

    names = dict(get_companies(db_path))
    return build_person_index(
        iter_ownership_details(db_path), names, summarize_affiliations
    )


def person_index(db_path: str) -> dict:
    """``{person_id: {name, id_number, companies: {...}}}`` — the register
    inverted. One pass over the ~9k ownership payloads (a few seconds cold),
    then memoized for the life of the DB file."""
    return _person_index_cached(_db_version(db_path), db_path)


@st.cache_resource(show_spinner=False, max_entries=2)
def _latest_portfolio_metrics_cached(db_version: str, db_path: str) -> dict:
    from lib.data_loader import get_latest_panel_metrics
    from lib.people import PORTFOLIO_METRICS

    return get_latest_panel_metrics(db_path, PORTFOLIO_METRICS)


def latest_portfolio_metrics(db_path: str) -> dict:
    """``{idcode: {"year", "metrics"}}`` for every company's latest filed year —
    the panel side of the attributable-portfolio join."""
    return _latest_portfolio_metrics_cached(_db_version(db_path), db_path)


@st.cache_resource(show_spinner=False, max_entries=4)
def _portfolio_metrics_filtered_cached(
    db_version: str, db_path: str, min_year: int | None
) -> dict:
    from lib.people import filter_latest_by_year

    return filter_latest_by_year(
        _latest_portfolio_metrics_cached(db_version, db_path), min_year
    )


def portfolio_metrics_for(db_path: str, min_year: int | None) -> dict:
    """The panel-side portfolio join, optionally restricted to recent filers.

    ``min_year=None`` keeps every vintage. See
    ``lib.people.filter_latest_by_year`` for why stale filings are dropped rather
    than zeroed."""
    return _portfolio_metrics_filtered_cached(_db_version(db_path), db_path, min_year)


@st.cache_resource(show_spinner="Ranking owners…", max_entries=16)
def _people_ranked_cached(
    db_version: str, db_path: str, metric: str, min_year: int | None
) -> dict:
    from lib.people import people_top

    return people_top(
        _person_index_cached(db_version, db_path),
        _portfolio_metrics_filtered_cached(db_version, db_path, min_year),
        metric=metric,
        limit=0,  # 0 = the FULL ranking; the view paginates it
    )


def people_ranked(db_path: str, metric: str, min_year: int | None = None) -> dict:
    """The COMPLETE owner ranking for ``metric`` (see ``lib.people.people_top``).

    Cached per (DB, metric, min_year) because the ranking walks every register
    entry and aggregates its portfolio — a few seconds over ~9k people. The Owners
    page paginates this, so without the cache every page turn would recompute the
    whole ranking. ``max_entries=16`` covers the rankable metrics x the two
    vintage settings.

    Returns the shared dict, so callers must treat ``people`` as READ-ONLY —
    slice it for display, never sort or mutate it in place.
    """
    return _people_ranked_cached(_db_version(db_path), db_path, metric, min_year)
# Macro-page datasets (macro_series / macro_dataset). See docs/macro-data-runbook.md.
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _macro_catalog_cached(db_version: str, db_path: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        try:
            return pd.read_sql_query(
                "SELECT dataset, title, category, unit, frequency, source, "
                "min_period, max_period, n_rows FROM macro_dataset ORDER BY category, dataset",
                conn)
        except pd.errors.DatabaseError:
            return pd.DataFrame()  # macro tables not present in this DB


def macro_catalog(db_path: str) -> pd.DataFrame:
    return _macro_catalog_cached(_db_version(db_path), db_path)


@st.cache_data(show_spinner=False)
def _macro_series_cached(db_version: str, db_path: str, dataset: str,
                         period_type: str | None) -> pd.DataFrame:
    q = ("SELECT period, period_type, breakdown, sub_breakdown, value, unit, source "
         "FROM macro_series WHERE dataset = ?")
    args: list = [dataset]
    if period_type:
        q += " AND period_type = ?"
        args.append(period_type)
    q += " AND value IS NOT NULL ORDER BY period"
    with sqlite3.connect(db_path) as conn:
        try:
            return pd.read_sql_query(q, conn, params=args)
        except pd.errors.DatabaseError:
            return pd.DataFrame()


def macro_series(db_path: str, dataset: str, period_type: str | None = None) -> pd.DataFrame:
    """Tidy rows for one macro dataset (optionally filtered to a period_type)."""
    return _macro_series_cached(_db_version(db_path), db_path, dataset, period_type)


def has_macro_data(db_path: str) -> bool:
    return not macro_catalog(db_path).empty
