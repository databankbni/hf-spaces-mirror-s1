"""Consolidation de-dup for SECTOR-POOLED aggregates.

Some Georgian groups file separate reportal.ge returns for a consolidating
parent AND one or more subsidiaries it already fully consolidates. When all of
them sit in the same curated sector, any view that POOLS a sector and SUMS its
companies (Sector View, Compare's sector-vs-sector mode, the MCP
``get_sector_aggregate`` tool) counts the same underlying business two (or more)
times — the parent's consolidated Revenue/EBITDA/Assets already contain the
subsidiary's.

The confirmed motivating case (FY2024 PDF audit, 2026-07-10):

    GRPC Holding      404647325   consolidates ↓ (note 2 subsidiaries table)
      ├─ GRPC Operations 404642892   assets 256.0M  ─┐  cross-foot:
      └─ GRPC (legacy)   404500857   assets  71.4M  ─┴─ ≈ Holding 325.8M

All three file separately and all three are in Power & Utilities, so summing
the sector double-counts ~44M Revenue / ~33M EBITDA and triple-counts assets.

Policy
------
This module is the single source of truth for a curated ``subsidiary → parent``
map. De-dup is applied ONLY to pooled aggregates, and it is **year-aware**: a
subsidiary's row for year *Y* is dropped **only when its consolidating parent
also reported year *Y* within the same pool**. That kills the double-count in
overlapping years while PRESERVING years the parent did not cover — e.g. the
GRPC legacy entity filed FY2017–2021 (assets up to 229M) before the Holding
existed; those years are the sole representation of that business and must NOT
be dropped, or the sector would be *under*-counted.

Single-company views, per-company contribution matrices, rankings, peer lists,
the screener, and hand-picked Compare selections are deliberately left
untouched — only the automatic sector *sum* needs this.

Curation
--------
Entries are added only when the parent/subsidiary consolidation relationship is
confirmed (PDF subsidiaries note, or a near-certain revenue-match fingerprint —
see ``scripts/find_consolidation_chains.py``, which surfaces candidates for
review). Wrongly excluding a genuinely independent filer would distort a sector
the same way the double-count does, in the opposite direction, so the bar is
"confirmed", not "looks similar". If this map ever grows large it can be
promoted to a ``ConsolidationParent`` column on ``company_search``; today a
small curated dict is simpler and has no rebuild-pipeline coupling.

Pure module — stdlib only (the one pandas helper imports pandas lazily), so both
the Streamlit app and the MCP server can import it cheaply.
"""
from __future__ import annotations

from collections.abc import Iterable

# ---------------------------------------------------------------------------
# Curated map: subsidiary IdCode -> parent (top consolidator) IdCode.
# The parent's consolidated statements already include the subsidiary, so the
# subsidiary is the "shadow" that gets dropped from a pooled sum (year-aware).
# ---------------------------------------------------------------------------
CONSOLIDATION_SHADOWS: dict[str, str] = {
    # --- GRPC / Georgian Renewable Energy (Power & Utilities) ---------------
    # Confirmed by FY2024 PDF audit (2026-07-10): Holding 404647325 owns 100%
    # of both and consolidates them (note 2). Ops & Holding report identical
    # Revenue every year; Holding assets = Ops + legacy (net of eliminations).
    "404642892": "404647325",  # GRPC Operations      -> GRPC Holding
    "404500857": "404647325",  # GRPC (legacy company) -> GRPC Holding
    # --- Buckswood International School Tbilisi (Education) -----------------
    # Parent 205089526 files consolidated accounts; 405712082 is a freshly
    # registered (2024) same-name subsidiary it consolidates. Overlap is FY2024
    # only, where the parent's 13.2M Revenue already contains the sub's 1.8M.
    "405712082": "205089526",  # Buckswood sub -> Buckswood parent
    # --- Tegeta Motors Group (mostly Auto & Auto Parts) --------------------
    # Confirmed against the company's own FY2024 CONSOLIDATED report
    # (202177205, GetFile/74033, Note 1 "Tegeta Motors Group", pp. 44-45):
    # 202177205 ("შპს თეგეტა მოტორსი") is the top consolidating filer — its
    # 98.78% shareholder TGM Group files no separate reportal statement — and
    # its consolidated Revenue/EBITDA/Assets already contain every subsidiary
    # below (all 100% held unless noted). Only subsidiaries that ALSO file a
    # separate reportal return (i.e. exist in this DB) are listed; the year-
    # aware de-dup drops each one only in the pool/years the parent co-reports.
    "405408811": "202177205",  # Tegeta Retail
    "405006461": "202177205",  # Toyota Center Tegeta
    "206239729": "202177205",  # Tegeta Truck & Bus (itself a sub-consolidator)
    "401950938": "202177205",  # Tegeta Premium Vehicles (Porsche/Mazda)
    "206316645": "202177205",  # Tegeta Construction Equipment (Industrial Goods)
    "445580773": "202177205",  # TBA Tegeta (Toyota)
    "405391437": "202177205",  # Tegeta Prime Products
    "405335766": "202177205",  # Scandinavian Auto Tegeta (Volvo)
    "405464929": "202177205",  # Tegeta Commercial Vehicles
    "405390553": "202177205",  # Tegeta Automotive Import
    "202372182": "202177205",  # Tegeta Logistics
    "405505500": "202177205",  # Tegeta Tire Imports
    "406207322": "202177205",  # Tegeta Car Rent (via Auto Gallery, 100%)
    "454412305": "202177205",  # Tegeta Rentals (via Tegeta International, 100%)
    "405391446": "202177205",  # Tegeta Industry
    "405522411": "202177205",  # Tegeta Approved (65% — controlled, fully consolidated)
    "405391080": "202177205",  # Tegeta Distribution
    "405232957": "202177205",  # Auto Gallery (non-Tegeta name; 100%)
    "405302836": "202177205",  # Caucasus Automotive (Volvo/Geely; 100%)
    "405601825": "202177205",  # Caucasus Machinery (100%, new 2024)
    "406338011": "202177205",  # Construction Machinery Georgia (Industrial Goods; 100%)
    # DELIBERATELY NOT MAPPED (name-match traps / not consolidated by 202177205):
    #   405523161 "Tegeta Green Planet"  — absent from the FY2024 subsidiaries note.
    #   436031768 "Caucasus Motors"      — a DIFFERENT group (BMW dealer), not a sub.
    #   405270727 "Segrex Auto Gallery"  — divested in 2024 / 50% assoc.; last filed 2020.
    #   Agroservice (431167328)          — note's Agroservice is an inactive Truck&Bus
    #                                      sub; common name, identity unconfirmed.
    #   Associates Tegeta Motors Meskheti (34%) & DSD Tegeta (25%) — equity method,
    #   NOT consolidated, and absent from this DB anyway.
}

# Human-readable notes keyed by subsidiary IdCode — used for captions /
# diagnostics only, never for logic. Safe to omit an entry.
SHADOW_LABELS: dict[str, str] = {
    "404642892": "GRPC Operations",
    "404500857": "GRPC (legacy)",
    "405712082": "Buckswood International School (subsidiary)",
    "405408811": "Tegeta Retail",
    "405006461": "Toyota Center Tegeta",
    "206239729": "Tegeta Truck & Bus",
    "401950938": "Tegeta Premium Vehicles",
    "206316645": "Tegeta Construction Equipment",
    "445580773": "TBA Tegeta",
    "405391437": "Tegeta Prime Products",
    "405335766": "Scandinavian Auto Tegeta",
    "405464929": "Tegeta Commercial Vehicles",
    "405390553": "Tegeta Automotive Import",
    "202372182": "Tegeta Logistics",
    "405505500": "Tegeta Tire Imports",
    "406207322": "Tegeta Car Rent",
    "454412305": "Tegeta Rentals",
    "405391446": "Tegeta Industry",
    "405522411": "Tegeta Approved",
    "405391080": "Tegeta Distribution",
    "405232957": "Auto Gallery",
    "405302836": "Caucasus Automotive",
    "405601825": "Caucasus Machinery",
    "406338011": "Construction Machinery Georgia",
}


def statement_basis_label(
    is_consolidated: bool,
    *,
    is_internal_parent: bool = False,
    is_internal_subsidiary: bool = False,
    latest_year: int | None = None,
    is_regulator_insurer: bool = False,
) -> tuple[str, str] | None:
    """``(short_label, tooltip)`` describing the basis of a company's statements.

    Derived from the filer's own declaration (``companies.LatestIsConsolidated``,
    set when reportal's CategoryMain carries "ჯგუფი" / *group*). The DB supports a
    defensible **binary** — Consolidated vs Individual — not four independent
    states ("group"/"standalone" are synonyms of those two). This is a
    LATEST-FILING fact, not per-year: earlier years' displayed numbers may sit on
    a different basis, so the label is scoped to the most recent filing and the
    tooltip says per-year basis isn't separately tracked.

    Returns ``None`` when the label should be SUPPRESSED — currently only for
    regulator-covered insurers, whose displayed statements come from the
    insurance.gov.ge return, not the reportal filing this flag describes.

    ``is_internal_parent`` / ``is_internal_subsidiary`` (from the companyinfo.ge
    control graph) only REFINE the wording; they never change the
    consolidated/individual axis. A missing ownership edge is *unknown*, not
    *none*, so the refinement is additive and safe to omit.
    """
    if is_regulator_insurer:
        return None

    _fy = f" FY{latest_year}" if latest_year else ""
    _scope = (
        f" Reflects the most recent filing{_fy}; per-year basis is not "
        "separately tracked."
    )
    if is_consolidated:
        short = (
            "Consolidated statements · group parent"
            if is_internal_parent else "Consolidated statements"
        )
        tip = (
            "Group (consolidated) accounts — the parent's statements already "
            "include its controlled subsidiaries." + _scope
        )
        return short, tip

    # individual / unconsolidated / separate
    if is_internal_subsidiary:
        short = "Individual statements · subsidiary"
    elif is_internal_parent:
        short = "Individual statements · parent-only"
    else:
        short = "Individual statements"
    tip = (
        "Company-only (individual / unconsolidated / separate) statements." + _scope
    )
    return short, tip


def parent_of(idcode: str) -> str | None:
    """Return the consolidating-parent IdCode for a subsidiary, or None."""
    return CONSOLIDATION_SHADOWS.get(str(idcode))


def is_shadow(idcode: str) -> bool:
    """True if ``idcode`` is a consolidation-shadow subsidiary in the map."""
    return str(idcode) in CONSOLIDATION_SHADOWS


def _years_by_id(company_years: Iterable[tuple[str, int]]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for idc, yr in company_years:
        out.setdefault(str(idc), set()).add(int(yr))
    return out


def shadowed_company_years(
    company_years: Iterable[tuple[str, int]],
) -> set[tuple[str, int]]:
    """The ``(subsidiary, year)`` rows to EXCLUDE from a pooled aggregate.

    ``company_years`` is any iterable of ``(IdCode, FVYear)`` present in the
    pool. Year-aware: a subsidiary-year is excluded only when its consolidating
    parent ALSO reported that year within the pool. Returns a set for O(1)
    membership tests in a filtering loop. Returns an empty set when no mapped
    parent/subsidiary pair is co-present.
    """
    by_id = _years_by_id(company_years)
    drop: set[tuple[str, int]] = set()
    for sub, parent in CONSOLIDATION_SHADOWS.items():
        sub_years = by_id.get(sub)
        parent_years = by_id.get(parent)
        if not sub_years or not parent_years:
            continue
        for y in sub_years & parent_years:
            drop.add((sub, y))
    return drop


def excluded_pairs(
    company_years: Iterable[tuple[str, int]],
) -> list[dict]:
    """Consolidation exclusions actually applied to a pool — for transparency.

    Returns one dict per co-present parent/subsidiary pair:
    ``{"subsidiary": id, "parent": id, "years": [sorted overlap years]}``.
    Only pairs that lost at least one year are reported (empty list otherwise).
    """
    by_id = _years_by_id(company_years)
    out: list[dict] = []
    for sub, parent in CONSOLIDATION_SHADOWS.items():
        sub_years = by_id.get(sub)
        parent_years = by_id.get(parent)
        if not sub_years or not parent_years:
            continue
        overlap = sorted(sub_years & parent_years)
        if overlap:
            out.append({"subsidiary": sub, "parent": parent, "years": overlap})
    return out


# ---------------------------------------------------------------------------
# Ownership-derived de-dup (opt-in, heuristic). The curated map above is the
# always-on, PDF-confirmed layer. This second layer uses the companyinfo.ge
# control graph (lib.ownership: internal >50% edges) to catch parent/subsidiary
# groups we haven't hand-verified — gated by a revenue signal so we don't drop a
# subsidiary whose "parent" clearly files STANDALONE (parent revenue < sub
# revenue ⇒ the parent can't already contain the sub ⇒ dropping it would
# UNDER-count). It is a NECESSARY-not-sufficient signal, so it's exposed as an
# opt-in toggle and always shown, never silently folded into the default sum.
# ---------------------------------------------------------------------------

def ownership_shadowed_company_years(
    rows, control_map: dict[str, str],
    consolidated_ids: set[str] | None = None,
    consolidated_company_years: set[tuple[str, int]] | None = None,
    edge_since: dict[tuple[str, str], str] | None = None,
) -> set[tuple[str, int]]:
    """``(subsidiary, year)`` rows to exclude via the ownership control graph.

    ``rows`` is an iterable of ``(IdCode, FVYear, Revenue)`` in the pool.
    ``control_map`` is ``{child -> parent}`` (see ``lib.ownership.build_control_map``).

    A sub-year is dropped only when its nearest present ancestor that year is a
    **consolidated filer** — i.e. that ancestor's statements actually already
    contain the sub. Revenue is kept as a secondary sanity guard (ancestor
    Revenue ≥ sub's, so a ×1000-mis-scaled sub bigger than its parent is never
    dropped).

    Two ways to supply the consolidation gate:

    * ``consolidated_ids`` — from ``companies.LatestIsConsolidated``. **This is
      what production uses today** (``views/sector.py``).
    * ``consolidated_company_years`` — ``(IdCode, FVYear)`` pairs that filed on a
      consolidated basis in that year, from the ``filing_basis`` table via
      ``data_loader.get_consolidated_company_years``. Takes precedence when
      given. Supported but **NOT wired into production** — see below.

    When both are None the gate falls back to the revenue signal alone (weakest).

    Why the per-year gate is not the default
    ----------------------------------------
    ``LatestIsConsolidated`` is only a *latest-filing* fact, so per-year basis
    looks like the obvious upgrade. Measured on 2026-07-28 it is not: market-wide
    it is revenue-neutral (FY2024 115.310bn -> 115.294bn) while moving 156
    company-years in and out of pools, including 70 NEW drops on weak evidence
    (e.g. საგა იმპექსი dropped under a parent only 1.06x its size — a parent
    barely larger than its subsidiary is unlikely to be consolidating it).

    The actual defect this was meant to fix lies elsewhere: **``ownership_edges``
    has no start date**, so present-day ownership is applied to all history.
    Roniko 203836974 filed CONSOLIDATED from FY2020 (the raw export carries both
    ``II`` and ``II ჯგუფი`` for FY2021-23), yet its FY2022 revenue of 23,164k
    excludes ArtTime 202356672 (12,830k) — not because the basis differed but
    because it had not acquired ArtTime yet. Ownership vintage is the fix; the
    per-year basis does not address it. Keep this parameter for when that lands
    (and for the planned individual/consolidated switcher), but do not switch the
    default without re-measuring.

    Ancestor-aware (walks multi-level chains to the nearest present *qualifying*
    ancestor) and cycle-safe. Curated shadows are handled separately
    (``shadowed_company_years``); this is the additional ownership layer only.
    """
    from collections import defaultdict

    rev: dict[tuple[str, int], float] = {}
    present: dict[str, set[int]] = defaultdict(set)
    for idc, yr, r in rows:
        idc = str(idc)
        yr = int(yr)
        rev[(idc, yr)] = float(r or 0)
        present[idc].add(yr)

    def _consolidates(idc: str, year: int) -> bool:
        """Did ``idc`` file on a consolidated basis in ``year``?

        Per-year fact when we have one, else the latest-filing flag, else
        unknown-so-permit (the revenue guard is the only remaining check).
        """
        if consolidated_company_years is not None:
            return (idc, year) in consolidated_company_years
        if consolidated_ids is not None:
            return idc in consolidated_ids
        return True

    def nearest_qualifying_ancestor(sub: str, year: int) -> tuple[str | None, int]:
        """Nearest ancestor present that year AND consolidated that year.

        Also returns the year the CHAIN to that ancestor was complete — the latest
        vintage on any edge along the path, because a two-level chain only links
        sub to ancestor once BOTH links exist. 0 when unknown, which permits.
        """
        seen = {sub}
        cur = control_map.get(sub)
        chain_year = 0
        prev = sub
        while cur and cur not in seen:
            if edge_since:
                when = edge_since.get((prev, cur))
                if when and len(when) >= 4 and when[:4].isdigit():
                    chain_year = max(chain_year, int(when[:4]))
            if year in present.get(cur, ()) and _consolidates(cur, year):
                return cur, chain_year
            seen.add(cur)
            prev = cur
            cur = control_map.get(cur)
        return None, chain_year

    drop: set[tuple[str, int]] = set()
    for sub in control_map:
        for y in present.get(sub, ()):
            anc, chain_year = nearest_qualifying_ancestor(sub, y)
            if anc is None:
                continue
            # OWNERSHIP VINTAGE. Drop only from the first FULL year of ownership.
            # An acquisition part-way through a year leaves the parent containing
            # only part of it, and the two errors are not symmetric: dropping a
            # year the parent never held deletes real revenue from the pool for
            # good, while keeping it double-counts a few months. The anchor case
            # agrees — Roniko acquired ArtTime 2022-11-03 and its FY2022 revenue
            # (23.2m) is optics-only, while FY2023 (38.3m) contains it.
            if chain_year and y <= chain_year:
                continue
            if rev.get((anc, y), 0.0) >= rev.get((sub, y), 0.0):
                drop.add((sub, y))
    return drop


def apply_ownership_dedup(df, control_map: dict[str, str],
                          consolidated_ids: set[str] | None = None,
                          id_col: str = "IdCode",
                          year_col: str = "FVYear", rev_col: str = "Revenue",
                          consolidated_company_years: set[tuple[str, int]] | None = None,
                          edge_since: dict[tuple[str, str], str] | None = None):
    """Drop ownership-control shadow rows from a panel-shaped ``df``.

    Returns ``(filtered_df, dropped)`` where ``dropped`` is the set of excluded
    ``(id, year)`` pairs. Pass ``consolidated_company_years`` (per-year basis,
    preferred) and/or ``consolidated_ids`` (latest-filing fallback) — see
    :func:`ownership_shadowed_company_years` for why the per-year set matters.
    No-op (returns input, empty set) when nothing qualifies or the required
    columns are missing. Curated de-dup should be applied first.
    """
    empty: set[tuple[str, int]] = set()
    if df is None or getattr(df, "empty", True):
        return df, empty
    # Require id, year AND revenue: the sanity guard is meaningless without
    # revenue, and defaulting it to 0 would over-drop (0>=0). No revenue → no-op.
    if id_col not in df.columns or year_col not in df.columns or rev_col not in df.columns:
        return df, empty
    drop = ownership_shadowed_company_years(
        zip(df[id_col].tolist(), df[year_col].tolist(), df[rev_col].tolist()),
        control_map, consolidated_ids, consolidated_company_years, edge_since,
    )
    if not drop:
        return df, empty
    mask = [
        (str(i), int(y)) not in drop
        for i, y in zip(df[id_col].tolist(), df[year_col].tolist())
    ]
    return df[mask], drop


def dedup_panel_df(df, id_col: str = "IdCode", year_col: str = "FVYear"):
    """Return ``df`` with consolidation-shadow subsidiary-year rows removed.

    ``df`` is a ``metrics_panel``-shaped frame (one row per company-year). Rows
    whose ``(id, year)`` is shadowed by a parent present in the same frame are
    dropped, year-aware (see :func:`shadowed_company_years`). Non-mutating:
    returns a filtered view/copy. A no-op (returns the input) when nothing is
    shadowed, so the common case pays almost nothing.
    """
    if df is None or getattr(df, "empty", True):
        return df
    if id_col not in df.columns or year_col not in df.columns:
        return df
    drop = shadowed_company_years(
        zip(df[id_col].tolist(), df[year_col].tolist())
    )
    if not drop:
        return df
    mask = [
        (str(i), int(y)) not in drop
        for i, y in zip(df[id_col].tolist(), df[year_col].tolist())
    ]
    return df[mask]
