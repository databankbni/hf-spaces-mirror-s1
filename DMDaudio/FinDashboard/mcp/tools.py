#!/usr/bin/env python3
"""Shared tool definitions for the Georgian Financials MCP server.

This module is the **single source of truth** for the 11 read-only MCP tools and
their Pydantic input models. Both entrypoints register the exact same tools:

  - ``mcp/server.py``        — local **stdio** transport (Claude Desktop / Code).
  - ``mcp/remote_server.py`` — hosted **streamable-HTTP** transport (HF Space).

Neither entrypoint duplicates query logic: they each build a ``FastMCP`` instance
(with whatever transport/auth wiring they need) and call :func:`register_tools`
to attach the tools. This keeps the two deployments behaviourally identical.

Data sources (see ``mcp/db.py`` for resolution):
  - ``company_search``  — IdCode, name, Sector, SubSector, latest revenue.
  - ``metrics_panel``   — precomputed per-company-per-year metrics.
  - ``financial_data``  — raw IS / BS / CF line items.

Raw line items pass through ``lib.data_loader.canonicalize_rows`` (the read-layer
single source of truth for alias/dedup/merge), and the metrics match what
``lib.profitability.compute_profitability`` feeds into ``metrics_panel``.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:  # pragma: no cover
    # FastMCP is only needed to *register* the tools (register_tools, called by
    # the MCP server entrypoints). Importing it eagerly would force the whole
    # `mcp` SDK on any consumer that just wants to reuse the tool functions /
    # pydantic models (e.g. the dashboard's in-app chat). Annotations here are
    # strings (PEP 563 via `from __future__ import annotations`), so the guard is
    # enough for type-checkers while keeping the runtime import lazy.
    from mcp.server.fastmcp import FastMCP

# Make the repo root importable so we can reuse lib/* query logic regardless of
# the cwd the MCP client / container launches us from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lib.data_loader import canonicalize_rows  # noqa: E402  (path set above)
from lib.bia_brand import (  # noqa: E402  (path set above)
    build_trade_name_index,
    search_key,
    search_trade_names,
)
from lib.consolidation import (  # noqa: E402  (path set above)
    excluded_pairs,
    shadowed_company_years,
)

# Unit-mistag override dicts — the SAME source of truth the ingest pipeline
# reads (scripts/ingest/policies.py::reconcile_units_across_filings). Importing
# them here (rather than re-listing) means the MCP's data-quality signal can
# never drift from what was actually applied to the DB. The module is pure data
# (no streamlit / pandas), so this stays a lightweight import.
from scripts.ingest.manual_mappings import (  # noqa: E402
    UNIT_RECONCILER_COMPANY_OVERRIDES,
    UNIT_RECONCILER_LINE_OVERRIDES,
    UNIT_RECONCILER_ROW_OVERRIDES,
    UNIT_RECONCILER_YEAR_OVERRIDES,
)

# Local module (mcp/db.py). Support both "run as script" and "import as package".
try:
    from db import connect_ro, resolve_db_path  # type: ignore
except ImportError:  # pragma: no cover - package-style import
    from mcp.db import connect_ro, resolve_db_path  # type: ignore

# Numeric metric columns selectable from metrics_panel (everything except the
# IdCode/FVYear index). Used to validate `metrics=` arguments and to default to
# the headline set when the caller doesn't specify.
_HEADLINE_METRICS = [
    "Revenue", "EBITDA", "EBIT", "NetProfit", "GrossProfit",
    "EBITDAMargin", "NetMargin", "GrossMargin",
    "TotalAssets", "TotalEquity", "TotalDebt", "NetDebt",
    "ROE", "ROA", "ROIC", "NetDebtToEBITDA",
]

# Statement → (section_prefix passed to the canonicalizer). The canonicalizer
# re-applies section overrides (e.g. CF-polluted BS cash rows move to CF), so
# filtering through it is the correct, drift-free way to slice statements.
_STATEMENT_SECTION = {"IS": "IS", "BS": "BS_", "CF": "CF"}


# ---------------------------------------------------------------------------
# Metric metadata — so an LLM renders fractions vs GEL correctly.
# `unit` ∈ {"GEL", "fraction", "ratio"}; `is_additive` says whether the metric
# can be meaningfully summed across companies (money lines yes; margins/ratios/
# growth no — those must be derived from summed bases or shown per-company).
# Mirrors lib.metric_picker's PERCENT_COLUMNS / RATIO_COLUMNS classification so
# the MCP and the dashboard agree on how every column is interpreted.
# ---------------------------------------------------------------------------
_FRACTION_BASE = {"GrossMargin", "EBITDAMargin", "NetMargin", "ROE", "ROA", "ROIC"}
_RATIO_COLUMNS = {"NetDebtToEBITDA", "AssetTurnover"}

_METRIC_DEFINITIONS: dict[str, str] = {
    "Revenue": "Total operating revenue (turnover) for the year.",
    "GrossProfit": "Revenue minus cost of goods sold.",
    "EBITDA": "Earnings before interest, tax, depreciation and amortisation (canonical reconstruction).",
    "EBIT": "Operating profit — earnings before interest and tax.",
    "NetProfit": "Profit for the year after tax (canonical NetProfit).",
    "TotalAssets": "Balance-sheet total assets.",
    "TotalEquity": "Total shareholders' equity.",
    "TotalCash": "Cash and cash equivalents.",
    "TotalDebt": "Total interest-bearing debt (short + long term).",
    "NetDebt": "Total debt minus cash and cash equivalents.",
    "GrossMargin": "GrossProfit / Revenue.",
    "EBITDAMargin": "EBITDA / Revenue.",
    "NetMargin": "NetProfit / Revenue.",
    "ROE": "Return on equity — NetProfit / average (or period) equity.",
    "ROA": "Return on assets — NetProfit / total assets.",
    "ROIC": "Return on invested capital — EBITDA / (Equity + Net debt).",
    "NetDebtToEBITDA": "Leverage ratio — NetDebt / EBITDA (× multiple).",
    "AssetTurnover": "Revenue / total assets (× multiple).",
}


def _metric_meta(col: str) -> dict[str, Any]:
    """Return {column, unit, is_additive, kind, definition} for one metric.

    Growth columns (``*_YoY`` / ``*_NyrCAGR``) are fractions and never additive.
    """
    is_growth = col.endswith("_YoY") or "CAGR" in col
    if col in _FRACTION_BASE or is_growth:
        unit = "fraction"
        kind = "growth" if is_growth else "margin/return"
        additive = False
    elif col in _RATIO_COLUMNS:
        unit = "ratio"
        kind = "ratio"
        additive = False
    else:
        unit = "GEL"
        kind = "money"
        additive = True
    if is_growth:
        base, _, suffix = col.partition("_")
        period = "year-over-year" if suffix == "YoY" else suffix.replace("yrCAGR", "-year CAGR")
        definition = f"{base} growth, {period} (decimal: 0.10 = +10%)."
    else:
        definition = _METRIC_DEFINITIONS.get(col, "")
    return {
        "column": col,
        "unit": unit,
        "is_additive": additive,
        "kind": kind,
        "definition": definition,
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _metrics_panel_columns(conn: sqlite3.Connection) -> list[str]:
    """All numeric metric column names available in metrics_panel."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(metrics_panel)").fetchall()]
    return [c for c in cols if c not in ("IdCode", "FVYear")]


def _company_label(conn: sqlite3.Connection, idcode: str) -> Optional[dict[str, Any]]:
    """Return {IdCode, name, sector, subsector} for one company, or None."""
    row = conn.execute(
        "SELECT IdCode, CompanyName, Sector, SubSector FROM company_search WHERE IdCode = ?",
        (idcode,),
    ).fetchone()
    if not row:
        return None
    return {
        "IdCode": row["IdCode"],
        "name": row["CompanyName"],
        "sector": row["Sector"] or None,
        "subsector": row["SubSector"] or None,
    }


def _company_profile_row(conn: sqlite3.Connection, idcode: str) -> Optional[dict[str, Any]]:
    """Return the enrichment row from `companies` for one company, or None.

    `Description`/`Sector`/`SubSector` live on the `companies` table (not the
    cached `company_search`), so profile + Description lookups read here.
    """
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
    except sqlite3.Error:
        cols = set()
    want = [c for c in (
        "IdCode", "CompanyName", "Description", "DescriptionSources",
        "DescriptionUpdatedAt", "Sector", "SubSector",
    ) if c in cols]
    if "IdCode" not in want:
        return None
    row = conn.execute(
        f"SELECT {', '.join(want)} FROM companies WHERE IdCode = ?", (idcode,)
    ).fetchone()
    if not row:
        return None
    return {c: row[c] for c in want}


def _descriptions_for(conn: sqlite3.Connection, idcodes: list[str]) -> dict[str, Optional[str]]:
    """Bulk {IdCode -> Description} from `companies` (empty/missing → None)."""
    if not idcodes:
        return {}
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()}
    except sqlite3.Error:
        cols = set()
    if "Description" not in cols:
        return {}
    placeholders = ",".join("?" * len(idcodes))
    rows = conn.execute(
        f"SELECT IdCode, Description FROM companies WHERE IdCode IN ({placeholders})",
        idcodes,
    ).fetchall()
    return {r["IdCode"]: (r["Description"] or None) for r in rows}


def _parse_sources(raw: Any) -> list[str]:
    """DescriptionSources is stored as a JSON array string — parse to a list."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        return [str(parsed)]
    except (json.JSONDecodeError, TypeError):
        return [str(raw)]


# ---------------------------------------------------------------------------
# Provenance / data-quality signal
# ---------------------------------------------------------------------------
# Some reportal.ge filings tag a row's unit column wrong (×1000 mistags — see
# project memory: Tashir Pizza, Liberty Bank, Santa-Transi, …). The ingest
# pipeline corrects these via four override tiers in scripts/ingest/
# manual_mappings.py. We surface that here so an LLM never narrates a corrected
# (or known-suspect) figure as raw fact. A multiplier of 1 means the stored
# value was DIVIDED back down (the source over-stated ×1000); 1000 means it was
# multiplied up (the source under-stated). We import the dicts directly so this
# signal is byte-identical to what the rebuild actually applied.

def _override_notes(idcode: str, year: int) -> list[dict[str, Any]]:
    """Return data-quality override notes that apply to (idcode, year).

    Each note: {scope, line_item?, applied_multiplier, meaning}. Covers the
    COMPANY (all years), YEAR (this year), and ROW (specific line items this
    year) tiers. LINE overrides (IdCode, line) are company-wide so are reported
    too. Empty list when nothing applies.
    """
    notes: list[dict[str, Any]] = []

    def _meaning(mult: int) -> str:
        if mult == 1:
            return ("source mistagged ×1000 too LARGE; ingest divided the value "
                    "back down to raw GEL")
        if mult == 1000:
            return ("source mistagged ×1000 too SMALL; ingest multiplied the "
                    "value up to raw GEL")
        return f"ingest forced unit multiplier {mult}"

    company_mult = UNIT_RECONCILER_COMPANY_OVERRIDES.get(idcode)
    if company_mult is not None:
        notes.append({
            "scope": "company", "applied_multiplier": company_mult,
            "meaning": _meaning(company_mult),
        })
    year_mult = UNIT_RECONCILER_YEAR_OVERRIDES.get((idcode, year))
    if year_mult is not None:
        notes.append({
            "scope": "year", "year": year, "applied_multiplier": year_mult,
            "meaning": _meaning(year_mult),
        })
    for (oid, line), mult in UNIT_RECONCILER_LINE_OVERRIDES.items():
        if oid == idcode:
            notes.append({
                "scope": "line", "line_item": line, "applied_multiplier": mult,
                "meaning": _meaning(mult),
            })
    for (oid, oyear, line), mult in UNIT_RECONCILER_ROW_OVERRIDES.items():
        if oid == idcode and oyear == year:
            notes.append({
                "scope": "row", "year": year, "line_item": line,
                "applied_multiplier": mult, "meaning": _meaning(mult),
            })
    return notes


def _line_override_multiplier(idcode: str, year: int, line_item: str) -> Optional[int]:
    """Forced multiplier for one (idcode, year, line_item), precedence ROW>LINE>YEAR>COMPANY.

    Mirrors reconcile_units_across_filings' precedence so a per-line-item flag
    matches exactly what the ingest applied to that row.
    """
    m = UNIT_RECONCILER_ROW_OVERRIDES.get((idcode, year, line_item))
    if m is not None:
        return m
    m = UNIT_RECONCILER_LINE_OVERRIDES.get((idcode, line_item))
    if m is not None:
        return m
    m = UNIT_RECONCILER_YEAR_OVERRIDES.get((idcode, year))
    if m is not None:
        return m
    return UNIT_RECONCILER_COMPANY_OVERRIDES.get(idcode)


def _years_with_overrides(idcode: str) -> set[int]:
    """All fiscal years for which any override tier touches this company."""
    years: set[int] = set()
    if idcode in UNIT_RECONCILER_COMPANY_OVERRIDES or any(
        oid == idcode for (oid, _line) in UNIT_RECONCILER_LINE_OVERRIDES
    ):
        # Company/line tiers apply to every year — caller intersects with the
        # years actually present. Signal with a sentinel-free empty set here and
        # let _override_notes report them per row.
        pass
    for (oid, yr) in UNIT_RECONCILER_YEAR_OVERRIDES:
        if oid == idcode:
            years.add(yr)
    for (oid, yr, _line) in UNIT_RECONCILER_ROW_OVERRIDES:
        if oid == idcode:
            years.add(yr)
    return years


# ---------------------------------------------------------------------------
# Macro GDP (read straight from macro_gdp — no streamlit dep on lib.cache).
# ---------------------------------------------------------------------------

def _gdp_by_year(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    """{year: {gdp_current_mln_gel, gdp_per_capita_gel, source}} from macro_gdp.

    Returns {} when the table is absent (pre-GDP DB). GDP is in MILLION GEL —
    callers comparing against metrics_panel Revenue (absolute GEL) must scale
    by 1e6. This mirrors lib.cache._gdp_by_year_cached without importing it
    (lib.cache pulls in streamlit).
    """
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "macro_gdp" not in names:
        return {}
    rows = conn.execute(
        "SELECT year, gdp_current_mln_gel, gdp_per_capita_gel, source FROM macro_gdp"
    ).fetchall()
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        if r["gdp_current_mln_gel"] is None:
            continue
        out[int(r["year"])] = {
            "gdp_current_mln_gel": float(r["gdp_current_mln_gel"]),
            "gdp_per_capita_gel": (
                float(r["gdp_per_capita_gel"]) if r["gdp_per_capita_gel"] is not None else None
            ),
            "source": r["source"],
        }
    return out


def _gdp_penetration(revenue_gel: float, gdp_mln_gel: float) -> Optional[float]:
    """Revenue (absolute GEL) / national nominal GDP (MILLION GEL, scaled ×1e6).

    Mirrors views.sector.gdp_penetration exactly. Returns a decimal proportion
    (0.123 == 12.3%), or None when GDP is missing/zero/invalid.
    """
    try:
        gdp_abs = float(gdp_mln_gel) * 1_000_000.0
    except (TypeError, ValueError):
        return None
    if gdp_abs <= 0:
        return None
    return float(revenue_gel) / gdp_abs


def _filter_years(years_value: Optional[list[int]]) -> Optional[set[int]]:
    return set(years_value) if years_value else None


def _err(message: str) -> str:
    """Uniform error payload (JSON string) so the model gets a parseable signal."""
    return json.dumps({"error": message}, ensure_ascii=False, indent=2)


def _dump(obj: Any) -> str:
    """Serialize a tool result to a JSON string (UTF-8, Georgian names intact)."""
    return json.dumps(obj, ensure_ascii=False, indent=2, default=float)


# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------

class SearchCompaniesInput(BaseModel):
    """Input for search_companies."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        description="Search text matched (case-insensitive substring) against the "
        "company name (usually Georgian), the 9-digit IdCode, AND the "
        "plain-English enrichment description — so English brand names like "
        "'Tegeta' resolve even though the stored legal name is Georgian "
        "(შპს თეგეტა მოტორსი). E.g. 'Tegeta', 'თეგეტა', '202177205', 'bank'.",
        min_length=1,
        max_length=200,
    )
    limit: int = Field(
        default=20,
        description="Maximum number of companies to return (1–100). Results are "
        "ordered by latest revenue, largest first.",
        ge=1,
        le=100,
    )


class CompanyFinancialsInput(BaseModel):
    """Input for get_company_financials."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    idcode: str = Field(
        ...,
        description="The company's 9-digit reportal.ge IdCode (e.g. '202177205' "
        "for Tegeta Motors). Get it from search_companies.",
        min_length=3,
        max_length=20,
    )
    statement: str = Field(
        default="IS",
        description="Which statement to return: 'IS' (income statement), "
        "'BS' (balance sheet) or 'CF' (cash flow).",
    )
    years: Optional[list[int]] = Field(
        default=None,
        description="Optional list of fiscal years to restrict to (e.g. [2022, 2023, 2024]). "
        "Omit for all available years.",
    )

    @field_validator("statement")
    @classmethod
    def _validate_statement(cls, v: str) -> str:
        v = v.upper()
        if v not in _STATEMENT_SECTION:
            raise ValueError("statement must be one of: IS, BS, CF")
        return v


class GetMetricsInput(BaseModel):
    """Input for get_metrics."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    idcode: str = Field(
        ...,
        description="The company's 9-digit IdCode (e.g. '202177205').",
        min_length=3,
        max_length=20,
    )
    metrics: Optional[list[str]] = Field(
        default=None,
        description="Optional subset of metric columns to return (e.g. "
        "['Revenue', 'EBITDA', 'EBITDAMargin', 'Revenue_YoY']). Omit for the "
        "headline set. Call list_metric_names() for the full column list.",
    )
    years: Optional[list[int]] = Field(
        default=None,
        description="Optional list of fiscal years to restrict to. Omit for all years.",
    )


class SectorAggregateInput(BaseModel):
    """Input for get_sector_aggregate."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    sector_or_subsector: str = Field(
        ...,
        description="A sector name (e.g. 'Healthcare Services', 'Banks') OR a "
        "sub-sector name. Matched case-insensitively against Sector first, then "
        "SubSector. Call list_sectors() for valid names.",
        min_length=1,
        max_length=120,
    )
    metrics: Optional[list[str]] = Field(
        default=None,
        description="Additive metric columns to aggregate (summed across companies "
        "per year), e.g. ['Revenue', 'EBITDA', 'NetProfit', 'TotalAssets']. "
        "Margins/ratios are NOT meaningfully summable; for those, the aggregate "
        "derives EBITDAMargin and NetMargin from the summed totals. Omit for the "
        "default ['Revenue', 'EBITDA', 'NetProfit', 'TotalAssets'].",
    )
    years: Optional[list[int]] = Field(
        default=None,
        description="Optional list of fiscal years to restrict to. Omit for all years.",
    )
    gdp_penetration: bool = Field(
        default=False,
        description="When true, add a 'gdp_penetration' field to each year's row: "
        "the sector's aggregate Revenue as a fraction of Georgia's nominal GDP "
        "that year (0.012 == 1.2% of GDP). This is the platform's most "
        "differentiated metric. Null in years with no GDP data.",
    )


class CompareCompaniesInput(BaseModel):
    """Input for compare_companies."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    idcodes: list[str] = Field(
        ...,
        description="Two or more 9-digit IdCodes to place side by side "
        "(e.g. ['202177205', '204441614']).",
        min_length=1,
        max_length=20,
    )
    metrics: Optional[list[str]] = Field(
        default=None,
        description="Metric columns to compare (e.g. ['Revenue', 'EBITDAMargin', "
        "'NetProfit']). Omit for the headline set.",
    )
    years: Optional[list[int]] = Field(
        default=None,
        description="Optional list of fiscal years to restrict to. Omit for all years.",
    )


class CompanyProfileInput(BaseModel):
    """Input for get_company_profile."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    idcode: str = Field(
        ...,
        description="The company's 9-digit IdCode (e.g. '202177205'). Get it "
        "from search_companies.",
        min_length=3,
        max_length=20,
    )


class MacroGdpInput(BaseModel):
    """Input for get_macro_gdp."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    years: Optional[list[int]] = Field(
        default=None,
        description="Optional list of calendar years to restrict to "
        "(e.g. [2022, 2023, 2024]). Omit for all available years.",
    )


class FindPeersInput(BaseModel):
    """Input for find_peers."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    idcode: str = Field(
        ...,
        description="The 9-digit IdCode of the company whose peers you want. "
        "Get it from search_companies.",
        min_length=3,
        max_length=20,
    )
    n: int = Field(
        default=10,
        description="Maximum number of peers to return (1–50). Ranked by latest "
        "revenue proximity to the target company.",
        ge=1,
        le=50,
    )


class RankCompaniesInput(BaseModel):
    """Input for rank_companies."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    sector_or_subsector: str = Field(
        ...,
        description="A sector (e.g. 'Healthcare Services', 'Banks') OR a "
        "sub-sector name. Matched case-insensitively, Sector first then "
        "SubSector. Call list_sectors() for valid names.",
        min_length=1,
        max_length=120,
    )
    metric: str = Field(
        default="Revenue",
        description="The metrics_panel column to rank by (e.g. 'Revenue', "
        "'EBITDA', 'EBITDAMargin', 'Revenue_YoY'). Call list_metric_names() "
        "for valid columns.",
        min_length=1,
        max_length=60,
    )
    year: Optional[int] = Field(
        default=None,
        description="Fiscal year to rank within. Omit to use each company's "
        "latest available year for the metric.",
    )
    top_n: int = Field(
        default=20,
        description="How many companies to return (1–100).",
        ge=1,
        le=100,
    )
    ascending: bool = Field(
        default=False,
        description="False (default) = largest/highest first (e.g. biggest "
        "revenue). True = smallest/lowest first.",
    )


# ---------------------------------------------------------------------------
# Tool implementations (transport-agnostic; registered onto a FastMCP instance
# by register_tools()).
# ---------------------------------------------------------------------------

async def list_sectors() -> str:
    """List every classified sector with its company count and its sub-sectors.

    Use this first to discover the exact sector/sub-sector names accepted by
    get_sector_aggregate and to understand the shape of the universe. Only
    companies that have been enrichment-classified appear; unclassified
    companies are omitted from the counts.

    Args:
        (none)

    Returns:
        str: JSON string with schema:
        {
            "total_classified_companies": int,
            "sectors": [
                {
                    "sector": str,            # e.g. "Healthcare Services"
                    "company_count": int,
                    "subsectors": [
                        {"subsector": str, "company_count": int}, ...
                    ]
                }, ...
            ]
        }
        Sectors are ordered by company_count descending.
    """
    try:
        with closing(connect_ro()) as conn:
            sector_rows = conn.execute(
                "SELECT Sector, COUNT(*) AS n FROM company_search "
                "WHERE Sector IS NOT NULL AND Sector != '' "
                "GROUP BY Sector ORDER BY n DESC"
            ).fetchall()
            sub_rows = conn.execute(
                "SELECT Sector, SubSector, COUNT(*) AS n FROM company_search "
                "WHERE Sector IS NOT NULL AND Sector != '' "
                "  AND SubSector IS NOT NULL AND SubSector != '' "
                "GROUP BY Sector, SubSector ORDER BY n DESC"
            ).fetchall()
        subs_by_sector: dict[str, list[dict[str, Any]]] = {}
        for r in sub_rows:
            subs_by_sector.setdefault(r["Sector"], []).append(
                {"subsector": r["SubSector"], "company_count": int(r["n"])}
            )
        sectors = [
            {
                "sector": r["Sector"],
                "company_count": int(r["n"]),
                "subsectors": subs_by_sector.get(r["Sector"], []),
            }
            for r in sector_rows
        ]
        return _dump({
            "total_classified_companies": sum(s["company_count"] for s in sectors),
            "sectors": sectors,
        })
    except Exception as e:  # noqa: BLE001
        return _err(f"Failed to list sectors: {type(e).__name__}: {e}")


_TRADE_NAME_INDEX: dict[str, dict[str, list[str]]] = {}


def _trade_name_index(conn: sqlite3.Connection, db_key: str) -> dict[str, list[str]]:
    """``{IdCode: [trade name, ...]}`` from bia.ge, built once per process.

    Keyed by DB path so a swapped-in Dataset file (see ``mcp/db.py``) is not
    served stale names. Returns {} when the DB predates ``bia_directory``.
    """
    cached = _TRADE_NAME_INDEX.get(db_key)
    if cached is not None:
        return cached
    import gzip

    try:
        names = {str(r[0]): (r[1] or "")
                 for r in conn.execute("SELECT IdCode, CompanyName FROM companies")}
        rows = conn.execute(
            "SELECT IdCode, DetailGz FROM bia_directory "
            "WHERE Status = 'ok' AND DetailGz IS NOT NULL"
        ).fetchall()
    except sqlite3.Error:
        _TRADE_NAME_INDEX[db_key] = {}
        return {}

    def _details():
        for row in rows:
            idcode = str(row[0])
            if idcode not in names:
                continue
            try:
                detail = json.loads(gzip.decompress(row[1]).decode("utf-8"))
            except (ValueError, TypeError, OSError):
                continue
            yield idcode, names[idcode], detail

    index = build_trade_name_index(_details())
    _TRADE_NAME_INDEX[db_key] = index
    return index


async def search_companies(params: SearchCompaniesInput) -> str:
    """Search the company universe by name (Georgian or English) or IdCode.

    The primary way to turn a human company name into the 9-digit IdCode that
    every other tool needs. Matches a case-insensitive substring against the
    company name, the IdCode, AND the plain-English enrichment Description —
    companies are stored under Georgian legal names (e.g. შპს თეგეტა მოტორსი),
    so English queries like 'Tegeta' resolve through the Description. Only
    enriched companies (~1.6k of ~9k, covering the significant names) are
    reachable by English text; a Georgian query or IdCode reaches everything.

    ALSO matches bia.ge TRADE NAMES, which is how a consumer brand resolves to
    the company that files: 'Carrefour' finds შპს მაჯიდ ალ ფუტაიმ ჰიპერმარკეტს
    ჯორჯია, 'SPAR' finds სს ფუდმარტი, 'Adjarabet' finds შპს ავიატორ. That match
    is PHONETIC and crosses scripts, because bia records brands as Georgian
    spellings of English words (კარფური, მაკდონალდსი) that no substring test can
    see through. 1,391 companies carry such a brand.

    Direct name/IdCode matches rank first, then trade-name matches, then
    description-only matches, each group ordered by latest revenue (largest
    first) so the most significant matches surface at the top.

    Args:
        params (SearchCompaniesInput):
            - query (str): name fragment or IdCode (e.g. 'Tegeta', '202177205', 'bank').
            - limit (int): max results, 1–100 (default 20).

    Returns:
        str: JSON string with schema:
        {
            "query": str,
            "count": int,
            "companies": [
                {
                    "IdCode": str,            # 9-digit code
                    "name": str,              # company name (often Georgian)
                    "sector": str | null,
                    "subsector": str | null,
                    "description": str | null,         # enrichment blurb when known
                    "trade_name": str | null,          # set when matched_on == 'trade_name'
                    "matched_on": "name" | "idcode" | "trade_name" | "description",
                    "latest_revenue": float | null,   # GEL, latest filed year
                    "latest_year": int | null
                }, ...
            ]
        }
        ``matched_on`` says which field the query hit — treat a "description"
        match with care: the query text may merely be *mentioned* in the blurb
        (e.g. a competitor). A "trade_name" match is stronger: the brand IS the
        company, and ``trade_name`` reports which brand answered. ``description``
        grounds what a Georgian-named company actually does; call
        get_company_profile for the full profile incl. sources. Returns count: 0
        with an empty list when nothing matches.
    """
    try:
        like = f"%{params.query}%"
        with closing(connect_ro()) as conn:
            # The enrichment Description lives on `companies` and is the only
            # English-text surface (names are Georgian). Older DBs may pre-date
            # the enrichment columns, so join it in only when present.
            try:
                has_desc = "Description" in {
                    r[1] for r in conn.execute("PRAGMA table_info(companies)").fetchall()
                }
            except sqlite3.Error:
                has_desc = False
            direct_hit = "(cs.CompanyName LIKE ? COLLATE NOCASE OR cs.IdCode LIKE ?)"
            # Over-fetch: the three match kinds are re-ranked in Python below, so
            # truncating to `limit` here would let description hits crowd out
            # stronger trade-name hits before they are even considered. "SPAR"
            # otherwise returns four blurbs that merely contain "spare parts"
            # and never reaches the company whose BRAND is SPAR.
            over_fetch = max(params.limit * 4, 40)
            if has_desc:
                rows = conn.execute(
                    "SELECT cs.IdCode, cs.CompanyName, cs.Sector, cs.SubSector, "
                    "       cs.LatestRevenue, cs.LatestFVYear, "
                    f"      {direct_hit} AS direct_hit "
                    "FROM company_search cs "
                    "LEFT JOIN companies c ON c.IdCode = cs.IdCode "
                    f"WHERE {direct_hit} OR c.Description LIKE ? COLLATE NOCASE "
                    "ORDER BY direct_hit DESC, cs.LatestRevenue DESC NULLS LAST, cs.IdCode "
                    "LIMIT ?",
                    (like, like, like, like, like, over_fetch),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT IdCode, CompanyName, Sector, SubSector, LatestRevenue, LatestFVYear "
                    "FROM company_search "
                    "WHERE CompanyName LIKE ? COLLATE NOCASE OR IdCode LIKE ? "
                    "ORDER BY LatestRevenue DESC NULLS LAST, IdCode "
                    "LIMIT ?",
                    (like, like, over_fetch),
                ).fetchall()
            # Trade names (bia.ge) are a PHONETIC, cross-script match, so an
            # English query reaches a brand bia stores in Georgian letters.
            # SQL LIKE cannot see through that, so it runs in Python over the
            # memoized index. ALWAYS run, never gated on leftover room: a brand
            # match outranks a description match.
            q_lower = params.query.lower()
            q_key = search_key(params.query)

            def _name_matches(row: sqlite3.Row) -> bool:
                """Literal OR phonetic match against the company's own name.

                The legal names are Georgian, so a Latin query never hit them
                literally and had to reach the company through its English
                blurb. Comparing phonetic keys fixes that: "Tegeta" now matches
                the NAME shown in the Georgian spelling, which is what it is,
                instead of ranking behind whichever blurb mentions the word.
                """
                name = row["CompanyName"] or ""
                if q_lower in name.lower():
                    return True
                return bool(q_key) and len(q_key) >= 3 and q_key in search_key(name)

            def _is_direct(row: sqlite3.Row) -> bool:
                return _name_matches(row) or q_lower in row["IdCode"]

            direct_codes = {r["IdCode"] for r in rows if _is_direct(r)}
            # search_trade_names returns best-match-first; keep that order as the
            # rank INSIDE the brand group. Sorting the group by revenue instead
            # let a big company's weak fuzzy hit outrank a small company's exact
            # brand ("Magniti" surfaced Magticom above Magniti's own operator).
            brand_hits = search_trade_names(
                _trade_name_index(conn, resolve_db_path()),
                params.query,
                limit=params.limit,
                exclude=direct_codes,
            )
            brand_of = {code: name for code, name, _ in brand_hits}
            brand_score = {code: score for code, _, score in brand_hits}
            seen_codes = {r["IdCode"] for r in rows}
            missing = [c for c in brand_of if c not in seen_codes]
            if missing:
                placeholders = ",".join("?" * len(missing))
                rows = list(rows) + conn.execute(
                    "SELECT IdCode, CompanyName, Sector, SubSector, "
                    "       LatestRevenue, LatestFVYear "
                    f"FROM company_search WHERE IdCode IN ({placeholders})",
                    tuple(missing),
                ).fetchall()

            # Re-rank: direct hits, then trade names, then description-only,
            # each group by latest revenue, then cut to the caller's limit.
            def _rank(row: sqlite3.Row) -> tuple:
                code = row["IdCode"]
                revenue = row["LatestRevenue"]
                by_revenue = -(revenue if revenue is not None else -1.0)
                if code in direct_codes:
                    return (0, by_revenue, code)
                if code in brand_of:
                    # Match quality first inside this group, revenue only to
                    # break ties between equally good brand matches — so the
                    # operator that runs a chain outranks a small franchisee
                    # whose brand string happens to match just as well.
                    return (1, -brand_score.get(code, 0.0), by_revenue, code)
                return (2, by_revenue, code)

            rows = sorted(rows, key=_rank)[: params.limit]
            # Descriptions live on `companies`, not the cached `company_search`.
            descriptions = _descriptions_for(conn, [r["IdCode"] for r in rows])

        q = params.query.lower()

        def _matched_on(r: sqlite3.Row) -> str:
            # Mirrors the ranking above, including the phonetic name match, so
            # matched_on never disagrees with why a row is where it is.
            if r["IdCode"] in direct_codes:
                return "idcode" if q in r["IdCode"] and q not in (
                    r["CompanyName"] or "").lower() else "name"
            if r["IdCode"] in brand_of:
                return "trade_name"
            return "description"

        companies = [
            {
                "IdCode": r["IdCode"],
                "name": r["CompanyName"],
                "sector": r["Sector"] or None,
                "subsector": r["SubSector"] or None,
                "description": descriptions.get(r["IdCode"]),
                "trade_name": brand_of.get(r["IdCode"]),
                "matched_on": _matched_on(r),
                "latest_revenue": float(r["LatestRevenue"]) if r["LatestRevenue"] is not None else None,
                "latest_year": int(r["LatestFVYear"]) if r["LatestFVYear"] is not None else None,
            }
            for r in rows
        ]
        return _dump({"query": params.query, "count": len(companies), "companies": companies})
    except Exception as e:  # noqa: BLE001
        return _err(f"Search failed: {type(e).__name__}: {e}")


async def get_company_financials(params: CompanyFinancialsInput) -> str:
    """Return the raw income-statement, balance-sheet, or cash-flow line items.

    Line items are pivoted to year columns for readability. Values are passed
    through the dashboard's own ``canonicalize_rows`` pipeline (alias collapsing,
    category/section overrides, dedup, and the Interest-Expense merge), so what
    you get matches exactly what the Single-Company view renders — including the
    CF-pollution fix that moves cash-reconciliation rows out of the balance sheet.
    All values are in GEL.

    Args:
        params (CompanyFinancialsInput):
            - idcode (str): 9-digit IdCode (from search_companies).
            - statement (str): 'IS', 'BS', or 'CF' (default 'IS').
            - years (list[int] | null): restrict to these fiscal years, else all.

    Returns:
        str: JSON string with schema:
        {
            "idcode": str,
            "name": str,
            "statement": str,         # 'IS' | 'BS' | 'CF'
            "years": [int, ...],      # sorted years present in the result
            "line_items": [
                {
                    "category": str,          # e.g. 'IS_Revenue', 'BS_Assets'
                    "item_type": str,         # 'TOTAL' | 'COMPONENT'
                    "line_item": str,         # canonical English label
                    "values": { "<year>": float, ... },  # GEL per year
                    "overridden_years": [int, ...]  # years whose value was unit-rescaled
                }, ...
            ],
            "data_quality_notes": [
                { "scope": str, "year": int?, "line_item": str?,
                  "applied_multiplier": int, "meaning": str }, ...
            ]
        }
        ``data_quality_notes`` (and the per-line ``overridden_years``) flag any
        value the ingest unit-rescaled because the source mis-tagged its ×1000
        units — so a suspect "billions" figure is never narrated as raw fact.
        Empty when no override touches this company/year.
        Returns {"error": ...} if the IdCode is unknown or has no data for the
        requested statement/years.
    """
    try:
        section_prefix = _STATEMENT_SECTION[params.statement]
        want_years = _filter_years(params.years)
        with closing(connect_ro()) as conn:
            label = _company_label(conn, params.idcode)
            if label is None:
                return _err(f"Unknown IdCode '{params.idcode}'. Use search_companies first.")
            sql = (
                "SELECT FVYear, Section, Category, ItemType, LineItemENG, Value "
                "FROM financial_data WHERE IdCode = ?"
            )
            sql_params: list[Any] = [params.idcode]
            if section_prefix.endswith("_"):
                sql += " AND Section LIKE ?"
                sql_params.append(section_prefix + "%")
            else:
                sql += " AND Section = ?"
                sql_params.append(section_prefix)
            raw = [dict(r) for r in conn.execute(sql, sql_params).fetchall()]

        # Reuse the dashboard's read-layer SSOT for alias/override/dedup/merge.
        canon = canonicalize_rows(raw, section_prefix)
        if want_years is not None:
            canon = [r for r in canon if r["FVYear"] in want_years]
        if not canon:
            return _err(
                f"No {params.statement} data for {params.idcode} "
                f"({label['name']})" + (f" in years {sorted(want_years)}" if want_years else "")
            )

        # Pivot to {line_item -> {year -> value}} preserving first-seen order.
        pivot: dict[tuple, dict[str, Any]] = {}
        years_present: set[int] = set()
        for r in canon:
            key = (r["Category"], r.get("ItemType") or "TOTAL", r["LineItemENG"])
            entry = pivot.setdefault(
                key,
                {
                    "category": r["Category"],
                    "item_type": r.get("ItemType") or "TOTAL",
                    "line_item": r["LineItemENG"],
                    "values": {},
                    "overridden_years": [],
                },
            )
            yr = int(r["FVYear"])
            years_present.add(yr)
            entry["values"][str(yr)] = float(r["Value"]) if r["Value"] is not None else 0.0
            # Per-line provenance: was THIS (year, line) unit-rescaled by ingest?
            if _line_override_multiplier(params.idcode, yr, r["LineItemENG"]) is not None:
                if yr not in entry["overridden_years"]:
                    entry["overridden_years"].append(yr)

        # Top-level data-quality summary across the years actually returned.
        quality_notes: list[dict[str, Any]] = []
        for yr in sorted(years_present):
            quality_notes.extend(_override_notes(params.idcode, yr))

        return _dump({
            "idcode": params.idcode,
            "name": label["name"],
            "statement": params.statement,
            "years": sorted(years_present),
            "line_items": list(pivot.values()),
            "data_quality_notes": quality_notes,
        })
    except Exception as e:  # noqa: BLE001
        return _err(f"Failed to load financials: {type(e).__name__}: {e}")


async def get_company_profile(params: CompanyProfileInput) -> str:
    """Return the enrichment profile (what the company actually does) for one company.

    Many companies are stored under a Georgian legal name (e.g.
    ``შპს თეგეტა მოტორსი``) that gives an LLM nothing to ground a narrative on.
    This returns the curated enrichment columns — a plain-English Description,
    its Sector/SubSector classification, and the Description's source URLs — so
    a narrative can be grounded in facts instead of guessed from the name.
    Pair it with get_metrics / get_company_financials for the numbers.

    Args:
        params (CompanyProfileInput):
            - idcode (str): 9-digit IdCode (from search_companies).

    Returns:
        str: JSON string with schema:
        {
            "idcode": str,
            "name": str,                       # company (often Georgian) name
            "sector": str | null,
            "subsector": str | null,
            "description": str | null,         # plain-English blurb, when enriched
            "description_sources": [str, ...], # URLs / provenance for the blurb
            "description_updated_at": str | null,  # ISO date the blurb was set
            "enriched": bool                   # true if a Description exists
        }
        Returns {"error": ...} for an unknown IdCode. A company with no
        enrichment still returns its name/sector with description=null and
        enriched=false.
    """
    try:
        with closing(connect_ro()) as conn:
            prof = _company_profile_row(conn, params.idcode)
            # Fall back to company_search for name/sector if the company exists
            # there but not in `companies` (defensive — both are keyed by IdCode).
            label = _company_label(conn, params.idcode)
        if prof is None and label is None:
            return _err(f"Unknown IdCode '{params.idcode}'. Use search_companies first.")
        prof = prof or {}
        name = prof.get("CompanyName") or (label["name"] if label else params.idcode)
        sector = prof.get("Sector") or (label["sector"] if label else None) or None
        subsector = prof.get("SubSector") or (label["subsector"] if label else None) or None
        description = prof.get("Description") or None
        return _dump({
            "idcode": params.idcode,
            "name": name,
            "sector": sector,
            "subsector": subsector,
            "description": description,
            "description_sources": _parse_sources(prof.get("DescriptionSources")),
            "description_updated_at": prof.get("DescriptionUpdatedAt") or None,
            "enriched": bool(description),
        })
    except Exception as e:  # noqa: BLE001
        return _err(f"Failed to load company profile: {type(e).__name__}: {e}")


async def get_metrics(params: GetMetricsInput) -> str:
    """Return precomputed per-year metrics for one company from metrics_panel.

    This is the fast path for headline figures and ratios — Revenue, EBITDA,
    EBIT, NetProfit, GrossProfit, the margins (EBITDAMargin, NetMargin,
    GrossMargin), balance-sheet aggregates (TotalAssets/Equity/Debt/NetDebt),
    return ratios (ROE/ROA/ROIC/NetDebtToEBITDA/AssetTurnover) and 30
    growth/CAGR columns (e.g. Revenue_YoY, EBITDA_3yrCAGR). EBITDA/NetProfit are
    the canonical values produced by lib.profitability.compute_profitability.

    Margins are fractions (0.138 = 13.8%); money columns are GEL.

    Args:
        params (GetMetricsInput):
            - idcode (str): 9-digit IdCode.
            - metrics (list[str] | null): subset of columns; omit for headline set.
              Call list_metric_names() for the full column list.
            - years (list[int] | null): restrict to these years, else all.

    Returns:
        str: JSON string with schema:
        {
            "idcode": str,
            "name": str,
            "metrics_returned": [str, ...],
            "rows": [
                { "FVYear": int, "overridden": bool, "<metric>": float | null, ... }, ...
            ],  # one row per year, ascending; `overridden` = ingest unit-rescaled this year
            "data_quality_notes": [ {scope, year?, applied_multiplier, meaning}, ... ]
        }
        ``overridden``/``data_quality_notes`` flag years whose underlying values
        were unit-rescaled because the source mis-tagged its ×1000 units — so an
        LLM never narrates a corrected/suspect figure as raw fact. Empty/false
        when no override touches this company.
        Returns {"error": ...} on unknown IdCode, no panel rows, or an invalid
        metric name (the error lists the valid columns).
    """
    try:
        want_years = _filter_years(params.years)
        with closing(connect_ro()) as conn:
            label = _company_label(conn, params.idcode)
            if label is None:
                return _err(f"Unknown IdCode '{params.idcode}'. Use search_companies first.")
            available = _metrics_panel_columns(conn)
            if params.metrics:
                chosen = [m for m in params.metrics]
                invalid = [m for m in chosen if m not in available]
                if invalid:
                    return _err(
                        f"Unknown metric(s): {invalid}. Valid columns: {available}"
                    )
            else:
                chosen = [m for m in _HEADLINE_METRICS if m in available]

            col_sql = ", ".join(["FVYear", *chosen])
            rows = conn.execute(
                f"SELECT {col_sql} FROM metrics_panel WHERE IdCode = ? ORDER BY FVYear",
                (params.idcode,),
            ).fetchall()
        override_years = _years_with_overrides(params.idcode)
        company_wide_override = (
            params.idcode in UNIT_RECONCILER_COMPANY_OVERRIDES
            or any(oid == params.idcode for (oid, _line) in UNIT_RECONCILER_LINE_OVERRIDES)
        )
        out_rows = []
        for r in rows:
            yr = int(r["FVYear"])
            if want_years is not None and yr not in want_years:
                continue
            rec: dict[str, Any] = {"FVYear": yr}
            for m in chosen:
                v = r[m]
                rec[m] = float(v) if v is not None else None
            rec["overridden"] = company_wide_override or (yr in override_years)
            out_rows.append(rec)
        if not out_rows:
            return _err(
                f"No metrics for {params.idcode} ({label['name']})"
                + (f" in years {sorted(want_years)}" if want_years else "")
            )
        quality_notes: list[dict[str, Any]] = []
        for yr in sorted({r["FVYear"] for r in out_rows}):
            quality_notes.extend(_override_notes(params.idcode, yr))
        return _dump({
            "idcode": params.idcode,
            "name": label["name"],
            "metrics_returned": chosen,
            "rows": out_rows,
            "data_quality_notes": quality_notes,
        })
    except Exception as e:  # noqa: BLE001
        return _err(f"Failed to load metrics: {type(e).__name__}: {e}")


async def get_sector_aggregate(params: SectorAggregateInput) -> str:
    """Aggregate additive metrics across every company in a sector/sub-sector.

    Mirrors the Sector View's aggregate panel: additive money metrics (Revenue,
    EBITDA, NetProfit, TotalAssets, …) are SUMMED across the sector's companies
    per fiscal year, reading the precomputed metrics_panel. Pooled margins
    (EBITDAMargin, NetMargin) are derived from the summed totals — never averaged
    — which is the economically correct way to express a sector margin.

    The name is matched case-insensitively against Sector first, then SubSector,
    so you can aggregate either granularity. Use list_sectors() for valid names.

    Consolidation de-dup: some groups file separate returns for a consolidating
    parent AND subsidiaries it already fully consolidates (e.g. GRPC Holding +
    Operations + a legacy entity, all in Power & Utilities). Summing them naively
    would double-count the same business, so a subsidiary's year is dropped from
    the sum whenever its consolidating parent also filed that year within this
    sector (year-aware, so a legacy entity's pre-parent history is preserved).
    Any exclusions applied are listed in ``excluded_consolidation_shadows``, and
    ``company_count`` reflects the deduped, contributing universe.

    Optionally (gdp_penetration=true) each year also carries the sector's
    Revenue as a fraction of Georgia's nominal GDP that year — the platform's
    most differentiated metric. GDP is stored in MILLION GEL and Revenue in
    absolute GEL, so GDP is scaled ×1e6 before dividing (mirrors the dashboard's
    Sector View logic exactly).

    Args:
        params (SectorAggregateInput):
            - sector_or_subsector (str): e.g. 'Healthcare Services', 'Banks'.
            - metrics (list[str] | null): additive columns to sum; default
              ['Revenue', 'EBITDA', 'NetProfit', 'TotalAssets'].
            - years (list[int] | null): restrict to these years, else all.
            - gdp_penetration (bool): add per-year Revenue/GDP fraction.

    Returns:
        str: JSON string with schema:
        {
            "match": {"level": "Sector"|"SubSector", "name": str},
            "company_count": int,         # distinct companies contributing (deduped)
            "metrics_summed": [str, ...],
            "excluded_consolidation_shadows": [
                {"subsidiary": str, "subsidiary_name": str|null,
                 "parent": str, "parent_name": str|null, "years": [int, ...]}, ...
            ],                            # [] when no parent/subsidiary overlap
            "gdp_source": str | null,     # present when gdp_penetration=true
            "rows": [
                {
                    "FVYear": int,
                    "company_count": int,        # companies with data that year
                    "<metric>": float, ...,      # summed totals (GEL)
                    "EBITDAMargin": float,       # derived: sum(EBITDA)/sum(Revenue)
                    "NetMargin": float,          # derived: sum(NetProfit)/sum(Revenue)
                    "gdp_penetration": float|null  # only if gdp_penetration=true
                }, ...
            ]   # one row per year, ascending
        }
        Returns {"error": ...} if the name matches no sector/sub-sector.
    """
    try:
        want_years = _filter_years(params.years)
        with closing(connect_ro()) as conn:
            available = _metrics_panel_columns(conn)
            # Resolve the name: Sector first, then SubSector.
            level = "Sector"
            id_rows = conn.execute(
                "SELECT IdCode, CompanyName FROM company_search WHERE Sector = ? COLLATE NOCASE",
                (params.sector_or_subsector,),
            ).fetchall()
            if not id_rows:
                level = "SubSector"
                id_rows = conn.execute(
                    "SELECT IdCode, CompanyName FROM company_search WHERE SubSector = ? COLLATE NOCASE",
                    (params.sector_or_subsector,),
                ).fetchall()
            if not id_rows:
                return _err(
                    f"No sector or sub-sector named '{params.sector_or_subsector}'. "
                    "Call list_sectors() for valid names."
                )
            idcodes = [r["IdCode"] for r in id_rows]
            name_by_id = {r["IdCode"]: r["CompanyName"] for r in id_rows}

            metrics = params.metrics or ["Revenue", "EBITDA", "NetProfit", "TotalAssets"]
            invalid = [m for m in metrics if m not in available]
            if invalid:
                return _err(f"Unknown metric(s): {invalid}. Valid columns: {available}")
            # Always need Revenue/EBITDA/NetProfit for the derived margins.
            fetch_cols = list(dict.fromkeys([*metrics, "Revenue", "EBITDA", "NetProfit"]))
            fetch_cols = [c for c in fetch_cols if c in available]

            placeholders = ",".join("?" * len(idcodes))
            col_sql = ", ".join(["IdCode", "FVYear", *fetch_cols])
            rows = conn.execute(
                f"SELECT {col_sql} FROM metrics_panel WHERE IdCode IN ({placeholders})",
                idcodes,
            ).fetchall()
            gdp = _gdp_by_year(conn) if params.gdp_penetration else {}

        # Consolidation de-dup (year-aware): drop a subsidiary's year when its
        # consolidating parent also filed that year within this sector, so the
        # sum doesn't count a parent + the subsidiaries it already consolidates
        # twice (e.g. GRPC Holding + Operations + legacy, all Power & Utilities).
        # Mirrors the dashboard's Sector View. See lib/consolidation.py.
        company_years = [(r["IdCode"], int(r["FVYear"])) for r in rows]
        drop = shadowed_company_years(company_years)
        excluded = excluded_pairs(company_years)

        # Aggregate per year.
        agg: dict[int, dict[str, float]] = {}
        counts: dict[int, int] = {}
        contributing: set[str] = set()
        for r in rows:
            yr = int(r["FVYear"])
            if want_years is not None and yr not in want_years:
                continue
            if (r["IdCode"], yr) in drop:
                continue
            bucket = agg.setdefault(yr, {c: 0.0 for c in fetch_cols})
            counts[yr] = counts.get(yr, 0) + 1
            contributing.add(r["IdCode"])
            for c in fetch_cols:
                v = r[c]
                if v is not None:
                    bucket[c] += float(v)

        out_rows = []
        for yr in sorted(agg):
            b = agg[yr]
            rec: dict[str, Any] = {"FVYear": yr, "company_count": counts[yr]}
            for m in metrics:
                rec[m] = b.get(m, 0.0)
            rev = b.get("Revenue", 0.0)
            rec["EBITDAMargin"] = (b.get("EBITDA", 0.0) / rev) if rev else None
            rec["NetMargin"] = (b.get("NetProfit", 0.0) / rev) if rev else None
            if params.gdp_penetration:
                g = gdp.get(yr)
                rec["gdp_penetration"] = (
                    _gdp_penetration(rev, g["gdp_current_mln_gel"]) if g else None
                )
            out_rows.append(rec)

        if not out_rows:
            return _err(
                f"No metrics_panel rows for '{params.sector_or_subsector}'"
                + (f" in years {sorted(want_years)}" if want_years else "")
            )
        result: dict[str, Any] = {
            "match": {"level": level, "name": params.sector_or_subsector},
            "company_count": len(contributing),
            "metrics_summed": metrics,
            "excluded_consolidation_shadows": [
                {
                    "subsidiary": e["subsidiary"],
                    "subsidiary_name": name_by_id.get(e["subsidiary"]),
                    "parent": e["parent"],
                    "parent_name": name_by_id.get(e["parent"]),
                    "years": e["years"],
                }
                for e in excluded
            ],
            "rows": out_rows,
        }
        if params.gdp_penetration:
            # Surface the GDP series provenance; null if the DB has no macro_gdp.
            any_year = next(iter(gdp.values()), None)
            result["gdp_source"] = any_year["source"] if any_year else None
        return _dump(result)
    except Exception as e:  # noqa: BLE001
        return _err(f"Sector aggregate failed: {type(e).__name__}: {e}")


async def compare_companies(params: CompareCompaniesInput) -> str:
    """Place several companies side by side on the same metrics, by year.

    Reads metrics_panel for each IdCode and returns a per-company series, so you
    can directly contrast e.g. Tegeta's EBITDA margin against a peer's. Unknown
    IdCodes are reported in ``not_found`` rather than failing the whole call.

    Args:
        params (CompareCompaniesInput):
            - idcodes (list[str]): 9-digit IdCodes to compare.
            - metrics (list[str] | null): columns to compare; omit for headline set.
            - years (list[int] | null): restrict to these years, else all.

    Returns:
        str: JSON string with schema:
        {
            "metrics_returned": [str, ...],
            "not_found": [str, ...],      # IdCodes with no company_search row
            "companies": [
                {
                    "IdCode": str,
                    "name": str,
                    "sector": str | null,
                    "rows": [ { "FVYear": int, "<metric>": float|null, ... }, ... ]
                }, ...
            ]
        }
        Returns {"error": ...} only if an invalid metric name is supplied.
    """
    try:
        want_years = _filter_years(params.years)
        results = []
        not_found = []
        with closing(connect_ro()) as conn:
            available = _metrics_panel_columns(conn)
            if params.metrics:
                chosen = list(params.metrics)
                invalid = [m for m in chosen if m not in available]
                if invalid:
                    return _err(f"Unknown metric(s): {invalid}. Valid columns: {available}")
            else:
                chosen = [m for m in _HEADLINE_METRICS if m in available]
            col_sql = ", ".join(["FVYear", *chosen])

            for idc in params.idcodes:
                label = _company_label(conn, idc)
                if label is None:
                    not_found.append(idc)
                    continue
                rows = conn.execute(
                    f"SELECT {col_sql} FROM metrics_panel WHERE IdCode = ? ORDER BY FVYear",
                    (idc,),
                ).fetchall()
                series = []
                for r in rows:
                    yr = int(r["FVYear"])
                    if want_years is not None and yr not in want_years:
                        continue
                    rec: dict[str, Any] = {"FVYear": yr}
                    for m in chosen:
                        v = r[m]
                        rec[m] = float(v) if v is not None else None
                    series.append(rec)
                results.append({
                    "IdCode": idc,
                    "name": label["name"],
                    "sector": label["sector"],
                    "rows": series,
                })
        return _dump({
            "metrics_returned": chosen,
            "not_found": not_found,
            "companies": results,
        })
    except Exception as e:  # noqa: BLE001
        return _err(f"Compare failed: {type(e).__name__}: {e}")


async def get_macro_gdp(params: MacroGdpInput) -> str:
    """Return Georgia's nominal GDP series (the denominator for GDP penetration).

    Reads the ``macro_gdp`` table (Geostat — GDP at current prices). GDP is in
    MILLION GEL; the per-capita figure is in GEL. Use this to contextualise a
    company or sector's scale against the whole economy, or to compute custom
    penetration ratios (note: metrics_panel Revenue is ABSOLUTE GEL, so scale
    GDP by 1e6 before dividing — get_sector_aggregate(gdp_penetration=true)
    does this for you).

    Args:
        params (MacroGdpInput):
            - years (list[int] | null): restrict to these calendar years, else all.

    Returns:
        str: JSON string with schema:
        {
            "source": str | null,    # e.g. "Geostat — GDP at current prices"
            "count": int,
            "rows": [
                {
                    "year": int,
                    "gdp_current_mln_gel": float,      # nominal GDP, MILLION GEL
                    "gdp_current_gel": float,          # same, scaled to absolute GEL
                    "gdp_per_capita_gel": float | null
                }, ...
            ]   # ascending by year
        }
        Returns {"error": ...} if the macro_gdp table is absent (pre-GDP DB).
    """
    try:
        want_years = _filter_years(params.years)
        with closing(connect_ro()) as conn:
            gdp = _gdp_by_year(conn)
        if not gdp:
            return _err(
                "No macro_gdp data in this database (it pre-dates the GDP import)."
            )
        rows = []
        source = None
        for yr in sorted(gdp):
            if want_years is not None and yr not in want_years:
                continue
            g = gdp[yr]
            source = source or g.get("source")
            rows.append({
                "year": yr,
                "gdp_current_mln_gel": g["gdp_current_mln_gel"],
                "gdp_current_gel": g["gdp_current_mln_gel"] * 1_000_000.0,
                "gdp_per_capita_gel": g["gdp_per_capita_gel"],
            })
        if not rows:
            return _err(
                f"No GDP rows for years {sorted(want_years)}."
                if want_years else "No GDP rows available."
            )
        return _dump({"source": source, "count": len(rows), "rows": rows})
    except Exception as e:  # noqa: BLE001
        return _err(f"Failed to load macro GDP: {type(e).__name__}: {e}")


async def find_peers(params: FindPeersInput) -> str:
    """Find a company's closest peers — same sector/sub-sector, similar size.

    Lets an LLM build a comparable set WITHOUT already knowing every IdCode in
    the universe. Peers are companies sharing the target's SubSector (when it
    has one) else its Sector, ranked by how close their latest revenue is to the
    target's (nearest first), so the result is a like-for-like, similarly-sized
    cohort ready to hand to compare_companies.

    Args:
        params (FindPeersInput):
            - idcode (str): the target company's 9-digit IdCode.
            - n (int): max peers to return, 1–50 (default 10).

    Returns:
        str: JSON string with schema:
        {
            "target": {"IdCode": str, "name": str, "sector": str|null,
                       "subsector": str|null, "latest_revenue": float|null,
                       "latest_year": int|null},
            "peer_group_level": "SubSector" | "Sector",
            "peer_group_name": str | null,
            "count": int,
            "peers": [
                {"IdCode": str, "name": str, "subsector": str|null,
                 "latest_revenue": float|null, "latest_year": int|null,
                 "revenue_ratio_to_target": float|null}, ...  # peer_rev / target_rev
            ]
        }
        Returns {"error": ...} for an unknown IdCode or a target with no
        sector/sub-sector classification (no peer group to draw from).
    """
    try:
        with closing(connect_ro()) as conn:
            target = conn.execute(
                "SELECT IdCode, CompanyName, Sector, SubSector, LatestRevenue, LatestFVYear "
                "FROM company_search WHERE IdCode = ?",
                (params.idcode,),
            ).fetchone()
            if target is None:
                return _err(f"Unknown IdCode '{params.idcode}'. Use search_companies first.")
            sector = target["Sector"] or None
            subsector = target["SubSector"] or None
            if not sector and not subsector:
                return _err(
                    f"{params.idcode} ({target['CompanyName']}) has no sector/sub-sector "
                    "classification, so it has no peer group. Try get_sector_aggregate "
                    "or list_sectors to explore the universe."
                )
            # Prefer the finer SubSector cohort when the target has one.
            if subsector:
                level, name = "SubSector", subsector
                peer_rows = conn.execute(
                    "SELECT IdCode, CompanyName, SubSector, LatestRevenue, LatestFVYear "
                    "FROM company_search WHERE SubSector = ? COLLATE NOCASE AND IdCode != ?",
                    (subsector, params.idcode),
                ).fetchall()
            else:
                level, name = "Sector", sector
                peer_rows = conn.execute(
                    "SELECT IdCode, CompanyName, SubSector, LatestRevenue, LatestFVYear "
                    "FROM company_search WHERE Sector = ? COLLATE NOCASE AND IdCode != ?",
                    (sector, params.idcode),
                ).fetchall()

        target_rev = float(target["LatestRevenue"]) if target["LatestRevenue"] is not None else None

        def _proximity(rev: Optional[float]) -> float:
            # Rank by absolute log-distance from the target revenue so a peer
            # 2× bigger and 2× smaller rank equally close; peers with no revenue
            # sink to the bottom. Falls back to raw size order if the target has
            # no revenue to anchor on.
            if rev is None or rev <= 0:
                return float("inf")
            if target_rev is None or target_rev <= 0:
                return -rev  # no anchor: largest first
            import math
            return abs(math.log(rev) - math.log(target_rev))

        scored = []
        for r in peer_rows:
            rev = float(r["LatestRevenue"]) if r["LatestRevenue"] is not None else None
            scored.append((_proximity(rev), r, rev))
        scored.sort(key=lambda t: t[0])

        peers = []
        for _score, r, rev in scored[: params.n]:
            peers.append({
                "IdCode": r["IdCode"],
                "name": r["CompanyName"],
                "subsector": r["SubSector"] or None,
                "latest_revenue": rev,
                "latest_year": int(r["LatestFVYear"]) if r["LatestFVYear"] is not None else None,
                "revenue_ratio_to_target": (
                    (rev / target_rev) if (rev is not None and target_rev) else None
                ),
            })
        return _dump({
            "target": {
                "IdCode": target["IdCode"],
                "name": target["CompanyName"],
                "sector": sector,
                "subsector": subsector,
                "latest_revenue": target_rev,
                "latest_year": int(target["LatestFVYear"]) if target["LatestFVYear"] is not None else None,
            },
            "peer_group_level": level,
            "peer_group_name": name,
            "count": len(peers),
            "peers": peers,
        })
    except Exception as e:  # noqa: BLE001
        return _err(f"Failed to find peers: {type(e).__name__}: {e}")


async def rank_companies(params: RankCompaniesInput) -> str:
    """Rank the companies in a sector/sub-sector by any metric — a screener.

    Lets an LLM answer "who are the top N by X" without enumerating IdCodes
    first: pick a sector (or sub-sector), a metric, optionally a year, and get a
    ranked leaderboard straight from metrics_panel. With no year, each company's
    LATEST available value for the metric is used. Margins/ratios/growth columns
    rank just as well as money columns.

    Args:
        params (RankCompaniesInput):
            - sector_or_subsector (str): e.g. 'Healthcare Services', 'Banks'.
            - metric (str): metrics_panel column (default 'Revenue').
            - year (int | null): rank within this year, else each co's latest.
            - top_n (int): how many to return, 1–100 (default 20).
            - ascending (bool): False = highest first (default); True = lowest first.

    Returns:
        str: JSON string with schema:
        {
            "match": {"level": "Sector"|"SubSector", "name": str},
            "metric": str,
            "metric_unit": str,          # 'GEL' | 'fraction' | 'ratio'
            "year": int | "latest",
            "ascending": bool,
            "count": int,
            "ranking": [
                {"rank": int, "IdCode": str, "name": str, "FVYear": int,
                 "value": float, "overridden": bool}, ...
            ]
        }
        ``overridden`` flags a row whose underlying values were unit-rescaled by
        the ingest (see get_metrics) — treat its rank with care. Returns
        {"error": ...} for an unknown sector/sub-sector or an invalid metric.
    """
    try:
        with closing(connect_ro()) as conn:
            available = _metrics_panel_columns(conn)
            if params.metric not in available:
                return _err(
                    f"Unknown metric '{params.metric}'. Valid columns: {available}"
                )
            # Resolve the name: Sector first, then SubSector.
            level = "Sector"
            rows_id = conn.execute(
                "SELECT IdCode, CompanyName FROM company_search WHERE Sector = ? COLLATE NOCASE",
                (params.sector_or_subsector,),
            ).fetchall()
            if not rows_id:
                level = "SubSector"
                rows_id = conn.execute(
                    "SELECT IdCode, CompanyName FROM company_search WHERE SubSector = ? COLLATE NOCASE",
                    (params.sector_or_subsector,),
                ).fetchall()
            if not rows_id:
                return _err(
                    f"No sector or sub-sector named '{params.sector_or_subsector}'. "
                    "Call list_sectors() for valid names."
                )
            name_by_id = {r["IdCode"]: r["CompanyName"] for r in rows_id}
            idcodes = list(name_by_id)
            placeholders = ",".join("?" * len(idcodes))
            q = (
                f"SELECT IdCode, FVYear, {params.metric} AS v "
                f"FROM metrics_panel WHERE IdCode IN ({placeholders}) AND {params.metric} IS NOT NULL"
            )
            sql_params: list[Any] = list(idcodes)
            if params.year is not None:
                q += " AND FVYear = ?"
                sql_params.append(params.year)
            panel = conn.execute(q, sql_params).fetchall()

        # One value per company: the requested year, or the latest year present.
        best: dict[str, tuple[int, float]] = {}  # IdCode -> (FVYear, value)
        for r in panel:
            idc = r["IdCode"]
            yr = int(r["FVYear"])
            val = float(r["v"])
            cur = best.get(idc)
            if cur is None or yr > cur[0]:
                best[idc] = (yr, val)

        if not best:
            return _err(
                f"No '{params.metric}' values for '{params.sector_or_subsector}'"
                + (f" in {params.year}" if params.year is not None else "")
            )

        ranked = sorted(best.items(), key=lambda kv: kv[1][1], reverse=not params.ascending)
        out = []
        for i, (idc, (yr, val)) in enumerate(ranked[: params.top_n], start=1):
            out.append({
                "rank": i,
                "IdCode": idc,
                "name": name_by_id.get(idc, idc),
                "FVYear": yr,
                "value": val,
                "overridden": (
                    idc in UNIT_RECONCILER_COMPANY_OVERRIDES
                    or (idc, yr) in UNIT_RECONCILER_YEAR_OVERRIDES
                    or any(oid == idc and oyr == yr for (oid, oyr, _l) in UNIT_RECONCILER_ROW_OVERRIDES)
                    or any(oid == idc for (oid, _l) in UNIT_RECONCILER_LINE_OVERRIDES)
                ),
            })
        return _dump({
            "match": {"level": level, "name": params.sector_or_subsector},
            "metric": params.metric,
            "metric_unit": _metric_meta(params.metric)["unit"],
            "year": params.year if params.year is not None else "latest",
            "ascending": params.ascending,
            "count": len(out),
            "ranking": out,
        })
    except Exception as e:  # noqa: BLE001
        return _err(f"Ranking failed: {type(e).__name__}: {e}")


async def list_metric_names() -> str:
    """List every metric column available in metrics_panel, with unit metadata.

    Helper for discovering valid ``metrics=`` arguments for get_metrics,
    get_sector_aggregate and compare_companies (including all growth/CAGR
    columns). Each metric carries metadata so a value is rendered correctly:

      - unit: 'GEL' (absolute money), 'fraction' (0.138 == 13.8%), or
        'ratio' (a × multiple, e.g. NetDebt/EBITDA).
      - is_additive: whether the metric can be summed across companies (money
        yes; margins/ratios/growth no — derive those from summed bases).
      - kind: 'money' | 'margin/return' | 'ratio' | 'growth'.
      - definition: one-line plain-English meaning.

    Args:
        (none)

    Returns:
        str: JSON string:
        {
            "metrics": [str, ...],            # raw column names
            "headline_default": [str, ...],
            "metric_metadata": [
                {"column": str, "unit": str, "is_additive": bool,
                 "kind": str, "definition": str}, ...
            ]
        }
    """
    try:
        with closing(connect_ro()) as conn:
            cols = _metrics_panel_columns(conn)
        return _dump({
            "metrics": cols,
            "headline_default": _HEADLINE_METRICS,
            "metric_metadata": [_metric_meta(c) for c in cols],
        })
    except Exception as e:  # noqa: BLE001
        return _err(f"Failed to list metric names: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Registration — attach all 11 tools onto a FastMCP instance.
# ---------------------------------------------------------------------------

# Tool-level annotations (read-only hints) shared by both transports.
_RO = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

# (function, name, title) for every tool. The function objects above hold the
# rich docstrings FastMCP turns into tool descriptions.
_TOOLS = [
    (list_sectors, "list_sectors", "List Sectors With Company Counts"),
    (search_companies, "search_companies", "Search Companies By Name Or IdCode"),
    (get_company_profile, "get_company_profile", "Get A Company's Enrichment Profile"),
    (get_company_financials, "get_company_financials", "Get Raw Statement Line Items For A Company"),
    (get_metrics, "get_metrics", "Get Precomputed Metrics For A Company"),
    (get_sector_aggregate, "get_sector_aggregate", "Aggregate Metrics Across A Sector Or Sub-sector"),
    (compare_companies, "compare_companies", "Compare Metrics Across Companies Side By Side"),
    (find_peers, "find_peers", "Find A Company's Closest Peers"),
    (rank_companies, "rank_companies", "Rank Companies In A Sector By A Metric"),
    (get_macro_gdp, "get_macro_gdp", "Get Georgia's Nominal GDP Series"),
    (list_metric_names, "list_metric_names", "List Available Metric Column Names"),
]


def register_tools(mcp: FastMCP) -> FastMCP:
    """Register all 11 read-only tools onto ``mcp`` and return it.

    Both the stdio entrypoint (``server.py``) and the remote streamable-HTTP
    entrypoint (``remote_server.py``) call this so the two deployments expose
    byte-identical tool definitions. Idempotent enough for a single process —
    do not call twice on the same instance.
    """
    for fn, name, title in _TOOLS:
        mcp.tool(name=name, annotations={"title": title, **_RO})(fn)
    return mcp
