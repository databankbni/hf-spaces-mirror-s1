"""Sector View — one metric picker drives four tabs (2026-07-20 spec).

Multi-select curated sectors → pooled companies, sub-sector filter, then
Overview (KPI tiles) · Companies (snapshot + drill + per-company matrix) ·
Trends (aggregate chart + by-year table) · Export. The aggregate is computed
once per run by :mod:`lib.sector_aggregate` — money summed, ratios weighted
from summed bases, growth on the aggregate series — after consolidation
de-dup (`lib.consolidation`).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.cache import (
    consolidated_idcodes,
    gdp_by_year,
    ownership_edges,
    panel_columns_for_idcodes,
    universe_stats,
)
from lib.consolidation import apply_ownership_dedup, dedup_panel_df, excluded_pairs
from lib.ownership import build_control_map
from lib.format import STALE_MARKER, fmt_k_gel, fmt_pct, is_stale, stale_caption
from lib.metric_picker import (
    SECTOR_DEFAULT_COLUMNS,
    is_money_column,
    is_percent_column,
    is_ratio_column,
    label_for,
    render_metric_picker,
)
from lib.sector_aggregate import aggregate_by_year, bases_needed
from lib.ui import safe_key

from views.shared import (
    BASE_AGG_COLUMNS,
    ViewContext,
    render_ifrs_controls,
    sector_metrics_panel,
)

# Local alias for the shared fallback columns (kept for readability).
_BASE_AGG_COLUMNS = BASE_AGG_COLUMNS

# Hide a year from the sector-aggregate chart/table when fewer than this
# fraction of the selection's companies have data for it. A brand-new fiscal
# year with a single early filer would otherwise make the aggregate collapse
# to near-zero and read as a sector-wide crash.
_AGG_MIN_COVERAGE = 0.10


def _company_column_config(names) -> dict[str, object]:
    """Size the ``Company`` column to its longest name so full names show when
    they fit, with a cap so one very long name can't blow out the layout
    (Streamlit truncates past the cap, exactly as the default did)."""
    longest = max((len(str(n)) for n in names), default=0)
    # ~9px per glyph + cell padding; clamp between a tidy minimum and a cap.
    width_px = min(max(longest * 9 + 24, 140), 520)
    return {"Company": st.column_config.TextColumn("Company", width=width_px)}


def gdp_penetration(revenue_gel: float, gdp_mln_gel: float) -> float | None:
    """Sector aggregate revenue as a fraction of national nominal GDP.

    ``revenue_gel`` is in ABSOLUTE GEL (the ``metrics_panel`` convention);
    ``gdp_mln_gel`` is in MILLION GEL (the Geostat ``macro_gdp`` convention),
    so GDP is scaled up by 1e6 before dividing. Returns a decimal proportion
    (0.123 == 12.3 %), or ``None`` when GDP is missing/zero/invalid.
    """
    try:
        gdp_abs = float(gdp_mln_gel) * 1_000_000.0
    except (TypeError, ValueError):
        return None
    if gdp_abs <= 0:
        return None
    return float(revenue_gel) / gdp_abs


@st.cache_data(show_spinner=False, ttl=600)
def _build_sector_financial_xlsx(db_path: str, idcodes_tuple: tuple[str, ...], sectors_label: str) -> bytes:
    """Flat Excel of every financial_data line item for the selected companies.

    Cached by (db_path, selection) so the two-step Generate→Download doesn't
    rebuild on every rerun. Returns the xlsx as bytes.
    """
    from lib.data_loader import get_companies, get_financial_data_bulk
    from lib.excel_export import raw_table_to_xlsx

    df = get_financial_data_bulk(db_path, list(idcodes_tuple))
    name_by_id = dict(get_companies(db_path))
    df.insert(1, "Company", df["IdCode"].map(lambda c: name_by_id.get(c, c)))
    df = df.rename(columns={"FVYear": "Year", "LineItemENG": "Line Item", "ItemType": "Item Type"})
    title = f"Financial data — {sectors_label}"
    subtitle = (
        f"{df['IdCode'].nunique()} companies · {len(df):,} line-item rows · "
        f"raw stored values in GEL (IS / BS / CF)"
    )
    return raw_table_to_xlsx(df, title, subtitle, sheet_name="Financial data")


def render(ctx: ViewContext) -> None:
    from lib.data_loader import get_curated_sector_buckets, get_sub_sectors
    from lib import sectors as _sectors

    @st.cache_data(show_spinner=False, ttl=3600)
    def _curated_buckets_for_view(db_path: str) -> dict:
        return get_curated_sector_buckets(db_path)

    @st.cache_data(show_spinner=False, ttl=3600)
    def _sub_sector_map(db_path: str) -> dict:
        return get_sub_sectors(db_path)

    curated = _curated_buckets_for_view(ctx.db_path)
    sub_sector_map = _sub_sector_map(ctx.db_path)
    if not curated:
        st.title("Sectoral Data")
        st.warning(
            "No curated sectors found — the database may pre-date the Sector "
            "column migration. Run `scripts/enrich_company_descriptions.py` to "
            "seed it."
        )
        st.stop()

    UNCLASSIFIED = "(unclassified)"

    # ---- Header + on-page controls -------------------------------------------
    # All Sector-View filters now live ON the page (same fd_toolbar treatment as
    # Single Company) — the sidebar holds only the Ask-Claude dock. The page
    # title renders BEFORE the toolbar, so it reads the selection from
    # session_state (committed before this run started; a read, so
    # Sprint-26-safe) — the seed block below runs first and guarantees the
    # pre-widget value matches what the multiselect returns.
    sector_names = list(curated.keys())
    # Streamlit GC's widget state for widgets that skip a run (e.g. while the
    # user drills into Single Company), so re-seed the multiselect from our own
    # copy before it instantiates. Same-run-before-widget writes are safe
    # (Sprint 26 only forbids writes AFTER the widget instantiated).
    if "sectorview_pick_multi" not in st.session_state:
        if "_sectorview_pick_saved" in st.session_state:
            st.session_state["sectorview_pick_multi"] = [
                s for s in st.session_state["_sectorview_pick_saved"] if s in sector_names
            ]
        else:
            # URL → state: seed from ?sectors=Name1,Name2 on first load so
            # sector selections are shareable/bookmarkable (mirrors Single
            # Company's ?id=). Session state wins thereafter; we mirror the
            # selection back into the URL after the widget renders.
            _url_secs = st.query_params.get("sectors")
            if _url_secs:
                _seed = [
                    s for s in (p.strip() for p in _url_secs.split(","))
                    if s in sector_names
                ]
                if _seed:
                    st.session_state["sectorview_pick_multi"] = _seed
    _pending_secs = [
        s for s in st.session_state.get("sectorview_pick_multi", []) if s in sector_names
    ]
    if _pending_secs:
        st.title(
            "Sectoral Data — "
            + (_pending_secs[0] if len(_pending_secs) == 1 else f"{len(_pending_secs)} sectors")
        )
    else:
        st.title("Sectoral Data")

    _toolbar = st.container(key="fd_toolbar")
    _tc = _toolbar.columns([1.5, 1.8, 1.4, 1.5, 2.8], vertical_alignment="center")
    with _tc[0]:
        with st.popover(
            f":material/category: Sectors · {len(_pending_secs)}",
            use_container_width=True,
        ):
            st.caption(
                f"{len(curated)} buckets · "
                f"{sum(len(v) for v in curated.values())} cos · GCAP taxonomy"
            )
            # No `default=` — this key is also written from session state (the
            # seed block above and the two-step picker's Continue button), and
            # declaring a default alongside that makes Streamlit log "created
            # with a default value but also had its value set via the Session
            # State API" on every commit. Absent key ⇒ empty, i.e. what
            # default=[] meant anyway.
            chosen_sectors = st.multiselect(
                "Pick sectors",
                sector_names,
                format_func=lambda s: f"{s}  ({len(curated[s])})",
                key="sectorview_pick_multi",
                label_visibility="collapsed",
                help=(
                    "Select one or more sectors. Companies from every picked sector are "
                    "pooled into one combined view (companies list, aggregate, matrix)."
                ),
            )
    st.session_state["_sectorview_pick_saved"] = list(chosen_sectors)
    # state → URL: keep ?sectors= in sync so the link survives refresh/share.
    # Loop-safe (query_params assignment doesn't rerun).
    _url_val = ",".join(chosen_sectors)
    if chosen_sectors:
        if st.query_params.get("sectors") != _url_val:
            st.query_params["sectors"] = _url_val
    elif "sectors" in st.query_params:
        del st.query_params["sectors"]
    if not chosen_sectors:
        # ---- Two-step picker: sectors → sub-sectors → Continue ---------------
        # Step 1 STAGES the sector picks rather than applying them, so step 2 can
        # offer that selection's sub-sectors in the same pill style before any
        # data loads. Nothing is committed until Continue, which is the only
        # place `sectorview_pick_multi` gets written.
        # The whole wizard sits in one keyed panel so lib.ui can style it as a
        # single grouped control (.st-key-fd_sectorpick).
        _pick_panel = st.container(key="fd_sectorpick")
        _step = (
            "<div class='fd-step'><span class='fd-step-n'>{n}</span>"
            "<span class='fd-step-t'>{t}</span>"
            "<span class='fd-step-h'>{h}</span></div>"
        )
        with _pick_panel:
            st.markdown(
                _step.format(
                    n="1", t="Pick one or more sectors",
                    h="— companies from every picked sector are pooled into one "
                      "combined view",
                ),
                unsafe_allow_html=True,
            )
            # No width="stretch": that sets flex-grow:1 on every pill, which
            # stretches the last row's pills across the full line.
            staged_sectors = st.pills(
                "Browse sectors",
                sector_names,
                selection_mode="multi",
                format_func=lambda s: f"{s}  ({len(curated[s])})",
                key="sectorview_browser",
                label_visibility="collapsed",
            ) or []

        if not staged_sectors:
            st.stop()

        # ---- Step 2: sub-sectors of the staged selection --------------------
        _staged_ids = _sectors.union_idcodes(curated, list(staged_sectors))
        _stage_counts = _sectors.subsector_counts(
            _staged_ids, sub_sector_map, UNCLASSIFIED
        )
        _stage_subs = sorted(_stage_counts, key=lambda s: (-_stage_counts[s], s))
        # Key off the staged sector set: changing sectors must start the
        # sub-sector picks over, or a stale pick could fall outside the new
        # options. Deliberately NOT seeded and NOT given a `default=`: step 2
        # starts with NOTHING picked, so an untouched step 2 means "whole
        # sector". Starting all-selected read as "I filtered to these" when the
        # user hadn't picked anything, which made an unrelated company look
        # mis-classified. An absent key is exactly an empty selection, and not
        # passing `default=` keeps Streamlit quiet about "created with a default
        # value but also had its value set via the Session State API" — the
        # Select all / Deselect all buttons write this same key.
        _stage_subs_key = safe_key(
            "sectorview_browser_subs", ",".join(sorted(staged_sectors))
        )

        # Fallback for a sector with a single sub-sector (step 2 is skipped):
        # nothing to narrow, so the whole selection loads.
        staged_subs: list[str] = []
        with _pick_panel:
            if len(_stage_subs) > 1:
                st.markdown(
                    "<div class='fd-step-rule'></div>"
                    + _step.format(
                        n="2", t="Narrow by sub-sector",
                        h=f"— optional; pick none of the {len(_stage_subs)} to "
                          "load the whole sector",
                    ),
                    unsafe_allow_html=True,
                )

                def _set_stage_subs(key: str, value: list[str]) -> None:
                    # on_click runs before the next script run, so writing the
                    # pills widget's key here is safe (Sprint 26 forbids writes
                    # only AFTER that widget instantiated in the same run).
                    st.session_state[key] = list(value)

                # Content-width buttons in tight columns — as full-width slabs
                # they out-shouted the pills they act on.
                _sa, _da, _ = st.columns([1, 1, 7], gap="small")
                with _sa:
                    st.button(
                        "Select all",
                        key="sectorview_browser_subs_all",
                        on_click=_set_stage_subs,
                        args=(_stage_subs_key, _stage_subs),
                        width="content",
                    )
                with _da:
                    st.button(
                        "Deselect all",
                        key="sectorview_browser_subs_none",
                        on_click=_set_stage_subs,
                        args=(_stage_subs_key, []),
                        width="content",
                    )
                staged_subs = st.pills(
                    "Browse sub-sectors",
                    _stage_subs,
                    selection_mode="multi",
                    format_func=lambda s: f"{s}  ({_stage_counts[s]})",
                    key=_stage_subs_key,
                    label_visibility="collapsed",
                ) or []

        # ---- Continue: commit the staged selection --------------------------
        # No sub-sector picked (the default) means "no sub-sector filter" — the
        # whole sector — matching how the toolbar's Sub-sectors control treats
        # empty. Picking every one is the same thing, so it also skips the filter.
        _will_load = (
            _sectors.filter_by_subsectors(
                _staged_ids, sub_sector_map, list(staged_subs), UNCLASSIFIED
            )
            if staged_subs and len(staged_subs) < len(_stage_subs)
            else _staged_ids
        )

        def _apply_staged(sectors: list[str], subs: list[str],
                          all_subs: list[str]) -> None:
            """Commit the wizard's staged picks and let the page render.

            Runs as an on_click callback — before the next script run — so
            writing the toolbar widgets' keys here is Sprint-26-safe.
            """
            st.session_state["sectorview_pick_multi"] = list(sectors)
            _key = safe_key("sectorview_subs", ",".join(sorted(sectors)))
            if subs and len(subs) < len(all_subs):
                st.session_state[_key] = list(subs)
            else:
                st.session_state.pop(_key, None)  # absent ⇒ widget default = all
            # Reset the wizard so it starts clean the next time the selection
            # is cleared from the toolbar.
            st.session_state["sectorview_browser"] = []

        with _pick_panel:
            st.markdown("<div class='fd-step-rule'></div>", unsafe_allow_html=True)
            st.button(
                f"Continue — {len(_will_load)} "
                f"{'company' if len(_will_load) == 1 else 'companies'}"
                "  :material/arrow_forward:",
                key="sectorview_browser_go",
                type="primary",
                on_click=_apply_staged,
                args=(list(staged_sectors), list(staged_subs), _stage_subs),
                disabled=not _will_load,
                width="content",
                help="Load the sector view for this selection",
            )
            if not _will_load:
                st.caption(
                    ":material/info: That combination has no companies — adjust "
                    "the sub-sector picks above."
                )
        st.stop()

    picked_idcodes = _sectors.union_idcodes(curated, chosen_sectors)
    total_in_selection = len(picked_idcodes)

    # ---- Sub-sector filter — pooled across the selected sectors. Each
    # company's sub-sector comes from companies.SubSector (populated by the GCAP
    # enrichment imports). Shown only when the selection spans 2+ distinct
    # sub-sectors. Companies with no sub-sector are grouped under
    # "(unclassified)" so they remain reachable.
    sub_counts = _sectors.subsector_counts(picked_idcodes, sub_sector_map, UNCLASSIFIED)
    available_subs = sorted(sub_counts.keys(), key=lambda s: (-sub_counts[s], s))

    sub_filter_active = False
    chosen_subs: list[str] = []
    if len(available_subs) > 1:
        # Key off the chosen-sector set so changing the sector selection
        # resets the sub-sector picker to its (all-selected) default. The
        # popover label count is a pre-widget session read (absent = all).
        _subs_key = safe_key("sectorview_subs", ",".join(sorted(chosen_sectors)))
        _subs_state = st.session_state.get(_subs_key)
        _n_subs = len(_subs_state) if _subs_state is not None else len(available_subs)
        with _tc[1]:
            with st.popover(
                f":material/account_tree: Sub-sectors · {_n_subs}/{len(available_subs)}",
                use_container_width=True,
            ):
                chosen_subs = st.multiselect(
                    "Filter by sub-sector",
                    options=available_subs,
                    default=available_subs,
                    format_func=lambda s: f"{s}  ({sub_counts[s]})",
                    key=_subs_key,
                    label_visibility="collapsed",
                    help=(
                        "Narrow the selection to specific sub-sectors. Affects the "
                        "companies list, aggregate chart, and per-company contribution "
                        "matrix. Clearing all falls back to the full selection."
                    ),
                )
        if chosen_subs and len(chosen_subs) < len(available_subs):
            picked_idcodes = _sectors.filter_by_subsectors(
                picked_idcodes, sub_sector_map, chosen_subs, UNCLASSIFIED
            )
            sub_filter_active = True

    with _tc[2]:
        _ifrs_active = bool(st.session_state.get("ifrs_on_toggle", False))
        with st.popover(
            ":material/tune: IFRS 16" + ("  ·  on" if _ifrs_active else ""),
            use_container_width=True,
        ):
            ifrs_on, assumed_term, interest_rate = render_ifrs_controls()

    # ---- Metric columns picker ----------------------------------------------
    # Lets the user choose which metrics appear in the aggregate-by-year table
    # (money columns are summed; the three standard margins are derived from
    # summed bases) and the per-company contribution matrix (any chosen metric).
    # Extra columns are read straight from the precomputed panel (non-IFRS).
    with _tc[3]:
        _mp_state = st.session_state.get(safe_key("metric_picker", "sector"))
        with st.popover(
            ":material/view_column: Metrics"
            + (f" · {len(_mp_state)}" if _mp_state else ""),
            use_container_width=True,
        ):
            picker_cols = render_metric_picker(
                ctx.db_path,
                "sector",
                SECTOR_DEFAULT_COLUMNS,
                label="Metrics to display",
                help=(
                    "Choose which metrics appear in the aggregate-by-year table and the "
                    "per-company contribution matrix below."
                ),
            )

    # ---- Main pane -----------------------------------------------------------
    _sectors_label = (
        ", ".join(chosen_sectors) if len(chosen_sectors) <= 4
        else f"{len(chosen_sectors)} sectors"
    )
    # (page title already rendered above the toolbar; suffix kept for the export
    # filename below)
    _title_suffix = chosen_sectors[0] if len(chosen_sectors) == 1 else f"{len(chosen_sectors)} sectors"
    if sub_filter_active:
        st.caption(
            f"{len(picked_idcodes)} of {total_in_selection} companies "
            f"({_sectors_label} · filtered to {len(chosen_subs)} of "
            f"{len(available_subs)} sub-sectors) · sorted by latest Revenue "
            f"(InterestIncome for banks) descending"
        )
    else:
        st.caption(
            f"{len(picked_idcodes)} companies across {_sectors_label} · "
            f"sorted by latest Revenue (InterestIncome for banks) descending"
        )

    # Build the same per-company per-year metrics table the Comp Sets mode uses.
    metrics_df, _ = sector_metrics_panel(
        ctx.db_path, tuple(picked_idcodes), ifrs_on, float(assumed_term),
        float(interest_rate),
    )
    if metrics_df.empty:
        st.warning(f"No financial data for the {len(picked_idcodes)} companies in this bucket.")
        st.stop()

    # Pull any picked metric columns that aren't already in metrics_df straight
    # from the precomputed panel, and merge them on (IdCode, FVYear) so both the
    # aggregate tabs and the contribution matrix can surface them. Every money
    # base a picked ratio/growth metric needs (lib.sector_aggregate.bases_needed)
    # is fetched too, so the aggregate can DERIVE weighted ratios and growth from
    # summed bases. Panel values are non-IFRS-adjusted.
    _wanted_extra = set(picker_cols) | bases_needed(picker_cols)
    _extra_cols = [c for c in _wanted_extra if c not in metrics_df.columns]
    if _extra_cols:
        _extra_panel = panel_columns_for_idcodes(ctx.db_path, picked_idcodes, _extra_cols)
        if not _extra_panel.empty:
            _extra_flat = _extra_panel.reset_index()
            _extra_flat["FVYear"] = _extra_flat["FVYear"].astype(int)
            metrics_df = metrics_df.merge(
                _extra_flat, on=["IdCode", "FVYear"], how="left"
            )

    # ---- Aggregate, computed ONCE — every tab consumes it --------------------
    # Consolidation de-dup: drop subsidiary-year rows whose consolidating parent
    # is also pooled here (year-aware), so a parent that already consolidates a
    # same-sector subsidiary isn't summed twice (e.g. GRPC Holding + Operations
    # + legacy, all in Power & Utilities). Applied to the AGGREGATE ONLY —
    # metrics_df (companies list + per-company matrix) still shows every entity.
    _agg_pool = dedup_panel_df(metrics_df)
    _excluded = excluded_pairs(
        zip(metrics_df["IdCode"].tolist(), metrics_df["FVYear"].tolist())
    )

    # The ownership-dedup toggle WIDGET lives in the Trends tab; its committed
    # value is read here (pre-instantiation session read — Sprint-26-safe) so
    # the Overview tiles and the Trends chart/table see the same pool.
    _own_dedup = bool(st.session_state.get("sector_ownership_dedup", False))
    _own_drop: list = []
    if _own_dedup:
        _edges = ownership_edges(ctx.db_path)
        _cmap = build_control_map(_edges)
        # OWNERSHIP VINTAGE (added 2026-08-03) — `ownership_edges` carries
        # `SinceDate`: the earliest date the parent appears as a partner in the
        # CHILD's own companyinfo affiliation history. Without it today's links
        # were applied to all history and 457 pre-acquisition company-years were
        # dropped, deleting GEL 6.23bn of real revenue from the pools.
        _since = {(e["child"], e["parent"]): e["since"]
                  for e in _edges if e.get("since")}
        # NOTE: still the LATEST-filing flag here, not the per-year `filing_basis`
        # table (which exists and is correct — see cache.consolidated_company_years).
        # That swap was measured on 2026-07-28 and is NOT an improvement:
        # revenue-neutral market-wide (FY2024 115.310bn -> 115.294bn) while moving
        # 156 company-years in and out of the pool, including 70 NEW drops on weak
        # evidence (e.g. საგა იმპექსი dropped under a parent only 1.06x its size).
        # Now that the vintage defect is fixed it is worth RE-measuring, but do not
        # switch it without doing so.
        _agg_pool, _own_drop = apply_ownership_dedup(
            _agg_pool, _cmap, consolidated_idcodes(ctx.db_path),
            edge_since=_since)

    # Low-coverage years are excluded from the aggregate (chart AND table):
    # summing 1 early filer's revenue next to 50 companies' prior years reads
    # as a sector collapse. The per-company matrix still shows them.
    _total_cos = int(_agg_pool["IdCode"].nunique())
    _year_counts = _agg_pool.groupby("FVYear")["IdCode"].nunique()
    _covered_years = {
        int(y) for y, n in _year_counts.items()
        if _total_cos and n / _total_cos >= _AGG_MIN_COVERAGE
    }
    if not _covered_years:  # degenerate selection — never blank the section
        _covered_years = {int(y) for y in _year_counts.index}
    _hidden_years = sorted(
        int(y) for y in _year_counts.index if int(y) not in _covered_years
    )
    _agg_metrics = _agg_pool[
        _agg_pool["FVYear"].astype(int).isin(_covered_years)
    ]

    # One picker drives the whole page (2026-07-20 spec): the aggregate table
    # carries exactly the picked metrics, each by its kind's rule (money -> Σ,
    # ratio -> weighted from summed bases, growth -> on the aggregate series).
    agg_cols: list[str] = list(picker_cols) or list(_BASE_AGG_COLUMNS)
    agg_table = aggregate_by_year(_agg_metrics, agg_cols)

    # Financial-sector mix (spec §2 open Q1, resolved as "show + say so"):
    # banks/insurers carry Revenue but NULL EBITDA/EBIT/GrossProfit in the
    # panel, so EBITDA-based aggregates and ratios understate a mixed pool.
    _by_co = metrics_df.groupby("IdCode").agg(
        _e=("EBITDA", "count"), _r=("Revenue", "count"))
    _n_financial = int(((_by_co["_e"] == 0) & (_by_co["_r"] > 0)).sum())

    def _fin_mix_caption() -> None:
        if _n_financial:
            st.caption(
                f":material/account_balance: {_n_financial} financial-sector "
                f"{'filer contributes' if _n_financial == 1 else 'filers contribute'} "
                "revenue but no EBITDA / EBIT / gross profit (banks and insurers "
                "report neither) — EBITDA-based aggregates and ratios understate "
                "this pool."
            )

    def _fmt_agg_cell(col: str, v) -> str:
        if pd.isna(v):
            return "—"
        if is_percent_column(col):
            return fmt_pct(v)
        if is_ratio_column(col):
            return f"{float(v):,.2f}×"
        return fmt_k_gel(v)

    _gdp = gdp_by_year(ctx.db_path)

    # ---- Tabs -----------------------------------------------------------------
    tab_overview, tab_companies, tab_trends, tab_export = st.tabs(
        [":material/dashboard: Overview", ":material/table_rows: Companies",
         ":material/show_chart: Trends", ":material/download: Export"]
    )

    # Latest-year-per-company snapshot — used by Companies AND the Overview
    # header. Sorted by latest Revenue descending.
    latest = (
        metrics_df.sort_values("FVYear")
        .groupby(["IdCode", "Company"], as_index=False)
        .last()
    )
    latest = latest.sort_values("Revenue", ascending=False, na_position="last")

    # ---- Overview: KPI tiles for the latest covered year ---------------------
    with tab_overview:
        if agg_table.empty:
            st.info("No aggregate data for this selection.")
        else:
            _last = agg_table.iloc[-1]
            _prev = agg_table.iloc[-2] if len(agg_table) > 1 else None
            _latest_fy = int(_last["FVYear"])
            _head = (
                f"FY{_latest_fy} aggregate · {int(_last['n'])} of "
                f"{len(picked_idcodes)} companies reporting"
            )
            if _gdp and "Revenue" in agg_table.columns:
                _g = _gdp.get(_latest_fy)
                _pen = gdp_penetration(_last["Revenue"], _g["gdp_mln"]) if _g else None
                if _pen is not None:
                    _head += f" · {fmt_pct(_pen)} of nominal GDP"
            st.caption(_head)

            _TILES_PER_ROW = 4
            for _ri in range(0, len(agg_cols), _TILES_PER_ROW):
                _row_cols = agg_cols[_ri:_ri + _TILES_PER_ROW]
                for _slot, _col in zip(st.columns(_TILES_PER_ROW), _row_cols):
                    _val = _last.get(_col)
                    _delta = None
                    if _prev is not None and not pd.isna(_val):
                        _pv = _prev.get(_col)
                        if not pd.isna(_pv):
                            if is_percent_column(_col):
                                _delta = f"{(_val - _pv) * 100:+.1f} pp"
                            elif is_ratio_column(_col):
                                _delta = f"{_val - _pv:+.2f}×"
                            elif _pv != 0:
                                _delta = f"{(_val - _pv) / abs(_pv):+.1%}"
                    with _slot:
                        st.metric(
                            label_for(_col),
                            _fmt_agg_cell(_col, _val),
                            delta=_delta,
                            # More debt reads as red, not green.
                            delta_color=("inverse" if _col in
                                         ("TotalDebt", "NetDebt", "NetDebtToEBITDA")
                                         else "normal"),
                            help=f"vs FY{int(_prev['FVYear'])}" if _delta else None,
                        )
            _fin_mix_caption()

    # ---- Companies: snapshot + drill + per-company matrix --------------------
    with tab_companies:
        st.markdown("##### Companies in selection")
        snapshot_cols = ["FVYear", "Revenue", "EBITDA", "NetProfit", "TotalAssets"]
        snapshot_df = latest[["IdCode", "Company"] + snapshot_cols].copy()

        # Stale flagging: a company is "stale" when its latest filed year lags the
        # dataset-wide max year. Mark the row with a ⚠ prefix and surface a caption.
        _dataset_max_year = universe_stats(ctx.db_path).get("year_max")
        snapshot_df["Company"] = [
            f"{STALE_MARKER} {co}" if is_stale(fy, _dataset_max_year) else co
            for co, fy in zip(snapshot_df["Company"], snapshot_df["FVYear"])
        ]

        # Decorate with SubSector when available — shows the finer-grained
        # classification right next to the company name without forcing the user
        # to drill into Single Company.
        snapshot_df.insert(
            2, "SubSector",
            snapshot_df["IdCode"].map(lambda c: sub_sector_map.get(c, "") or "—"),
        )
        snapshot_df["FVYear"] = snapshot_df["FVYear"].astype(int).astype(str)
        for col in ("Revenue", "EBITDA", "NetProfit", "TotalAssets"):
            snapshot_df[col] = snapshot_df[col].map(fmt_k_gel)
        # Drop the SubSector column entirely when no company in this bucket has
        # one — keeps narrow tables tidy.
        if (snapshot_df["SubSector"] == "—").all():
            snapshot_df = snapshot_df.drop(columns=["SubSector"])
        snapshot_df = snapshot_df.rename(columns={
            "FVYear": "Latest FY",
            "SubSector": "Sub-sector",
            "Revenue": "Revenue (K)",
            "EBITDA": "EBITDA (K)",
            "NetProfit": "Net Profit (K)",
            "TotalAssets": "Total Assets (K)",
        })
        st.dataframe(
            snapshot_df, use_container_width=True, hide_index=True,
            column_config=_company_column_config(snapshot_df["Company"]),
        )
        _stale_cap = stale_caption(latest["FVYear"], _dataset_max_year)
        if _stale_cap:
            st.caption(_stale_cap)

        # Per-company "jump into Single Company" drill. Small buckets get the
        # familiar button grid; big buckets get a searchable selectbox instead —
        # 200+ st.button instantiations per rerun were a measurable render cost
        # AND an unusable wall of buttons (2026-07-02 review).
        _DRILL_BUTTON_MAX = 30

        def _go_single(_idc: str, _co: str) -> None:
            st.session_state["mode"] = "Single Company"
            st.session_state["_pending_single_pick"] = ctx.idcode_to_label.get(_idc, _co)
            st.query_params["mode"] = "single"
            st.query_params["id"] = _idc
            st.rerun()

        with st.expander(f":material/search: Drill into a company ({len(latest)} options)"):
            _drill_pairs = list(zip(latest["IdCode"].tolist(), latest["Company"].tolist()))
            if len(_drill_pairs) <= _DRILL_BUTTON_MAX:
                _drill_cols = st.columns(2)
                for _i, (_idc, _co) in enumerate(_drill_pairs):
                    with _drill_cols[_i % 2]:
                        if st.button(
                            f"{_co}",
                            key=safe_key("sv_drill", _idc),
                            use_container_width=True,
                        ):
                            _go_single(_idc, _co)
            else:
                _by_label = {f"{_co}  ({_idc})": (_idc, _co) for _idc, _co in _drill_pairs}
                _pick = st.selectbox(
                    "Company",
                    list(_by_label),
                    index=None,
                    placeholder="Start typing a name or IdCode…",
                    key="sv_drill_pick",
                    label_visibility="collapsed",
                )
                if st.button(
                    ":material/open_in_new: Open in Single Company",
                    key="sv_drill_go",
                    disabled=not _pick,
                ):
                    _go_single(*_by_label[_pick])

    # ---- Trends: the aggregate over time, driven by the same picker ----------
    with tab_trends:
        if _excluded:
            _name_by_id = dict(zip(metrics_df["IdCode"], metrics_df["Company"]))

            def _yspan(years: list[int]) -> str:
                return f"FY{years[0]}" + (f"–{years[-1]}" if len(years) > 1 else "")

            _parts = [
                f"{_name_by_id.get(e['subsidiary'], e['subsidiary'])} "
                f"(consolidated within {_name_by_id.get(e['parent'], e['parent'])}; "
                f"{_yspan(e['years'])})"
                for e in _excluded
            ]
            st.caption(
                ":material/account_tree: Consolidation de-dup — excluded from the "
                "aggregate to avoid double-counting: " + "; ".join(_parts)
                + ". Each still appears individually in the Companies tab."
            )

        # Opt-in second layer: ownership-graph de-dup. The POOL was already
        # computed above from this toggle's committed value; the widget lives
        # here so the control sits next to the aggregate it changes.
        st.toggle(
            "Also consolidate ownership-linked groups (experimental)",
            value=False,
            key="sector_ownership_dedup",
            help="Uses companyinfo.ge ownership + the reportal consolidated-filing basis: "
                 "drops a subsidiary when a >50% parent in this selection filed "
                 "consolidated accounts THAT YEAR (so its figures already include the "
                 "sub). Years the parent filed individual are left alone. "
                 "Curated, PDF-confirmed groups are always de-duped regardless.",
        )
        if _own_dedup:
            if _own_drop:
                _name_by_id = dict(zip(metrics_df["IdCode"], metrics_df["Company"]))
                _by_sub: dict[str, list[int]] = {}
                for _sid, _yr in _own_drop:
                    _by_sub.setdefault(_sid, []).append(_yr)
                _op = [
                    f"{_name_by_id.get(s, s)} (FY{min(ys)}"
                    + (f"–{max(ys)}" if len(ys) > 1 else "") + ")"
                    for s, ys in _by_sub.items()
                ]
                st.caption(
                    f":material/account_tree: Ownership de-dup (experimental) — also "
                    f"excluded {len(_by_sub)} "
                    f"{'entity' if len(_by_sub) == 1 else 'entities'}: "
                    + "; ".join(_op[:12]) + ("; …" if len(_op) > 12 else "")
                    + ". Each still appears individually in the Companies tab."
                )
            else:
                st.caption(":material/account_tree: Ownership de-dup: no additional "
                           "ownership-linked entities found in this selection.")

        # Standing disclaimer: de-dup only covers the curated CONSOLIDATION_SHADOWS
        # map, so a group that files a consolidating parent AND subsidiaries which we
        # haven't confirmed yet can still be summed more than once. Say so honestly.
        st.caption(
            ":material/info: Aggregates sum every filer in the selection. Known "
            "parent/subsidiary groups that file separately are de-duplicated to avoid "
            "double-counting; groups not yet curated may still be counted more than once."
        )
        if _hidden_years:
            st.caption(
                ":material/visibility_off: Excluded from the aggregate — fewer than "
                f"{_AGG_MIN_COVERAGE:.0%} of the {_total_cos} companies in this "
                "selection have reported: "
                + ", ".join(
                    f"FY{y} ({int(_year_counts[y])} of {_total_cos})"
                    for y in _hidden_years
                )
                + ". These years still appear in the per-company matrix."
            )
        _fin_mix_caption()

        if agg_table.empty:
            st.info("No aggregate data for this selection.")
        else:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots

            _money_cols = [c for c in agg_cols if is_money_column(c)]
            _rate_cols = [c for c in agg_cols if not is_money_column(c)]
            _years_axis = [int(y) for y in agg_table["FVYear"]]

            fig = make_subplots(specs=[[{"secondary_y": bool(_rate_cols)}]])
            for _i, _c in enumerate(_money_cols):
                if _i == 0:
                    fig.add_trace(go.Bar(
                        x=_years_axis, y=agg_table[_c] / 1000,
                        name=f"{label_for(_c)} (K GEL)",
                        hovertemplate=("FY%{x}<br>" + label_for(_c)
                                       + ": %{y:,.0f}K GEL<extra></extra>"),
                    ))
                else:
                    fig.add_trace(go.Scatter(
                        x=_years_axis, y=agg_table[_c] / 1000,
                        name=f"{label_for(_c)} (K GEL)",
                        mode="lines+markers",
                        line=dict(width=2, dash="dot" if _i > 1 else None),
                        hovertemplate=("FY%{x}<br>" + label_for(_c)
                                       + ": %{y:,.0f}K GEL<extra></extra>"),
                    ))
            _all_pct = all(is_percent_column(c) for c in _rate_cols)
            for _c in _rate_cols:
                fig.add_trace(go.Scatter(
                    x=_years_axis, y=agg_table[_c],
                    name=label_for(_c) + ("" if _all_pct else " (×)"),
                    mode="lines+markers", line=dict(width=2, dash="dash"),
                    hovertemplate=("FY%{x}<br>" + label_for(_c)
                                   + (": %{y:.1%}<extra></extra>" if is_percent_column(_c)
                                      else ": %{y:.2f}×<extra></extra>")),
                ), secondary_y=True)
            fig.update_layout(
                height=420,
                margin=dict(l=40, r=40, t=30, b=40),
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1),
                hovermode="x unified",
            )
            fig.update_xaxes(title_text="Year", tickmode="array",
                             tickvals=_years_axis)
            if _money_cols:
                fig.update_yaxes(title_text="GEL (thousands)", secondary_y=False)
            if _rate_cols:
                fig.update_yaxes(
                    title_text="ratio" if not _all_pct else "percent",
                    tickformat=".0%" if _all_pct else None,
                    secondary_y=True,
                )
            from lib.theme import chart_theme, polish_bar_line_chart
            chart_theme(fig)
            polish_bar_line_chart(fig)
            st.plotly_chart(fig, use_container_width=True, key="sectorview_chart")

            # Aggregate-by-year table — one row per picked metric, each by its
            # kind's rule; plus GDP penetration (when Revenue is picked) and the
            # contributing-company count.
            _year_labels = [str(y) for y in _years_axis]
            _rows: list[list[str]] = []
            for _c in agg_cols:
                _unit = (" (K)" if is_money_column(_c)
                         else " (%)" if is_percent_column(_c) else " (×)")
                _rows.append([label_for(_c) + _unit]
                             + [_fmt_agg_cell(_c, v) for v in agg_table[_c]])
            if _gdp and "Revenue" in agg_table.columns:
                _pen_vals = []
                for _yr, _rev in zip(_years_axis, agg_table["Revenue"]):
                    _g = _gdp.get(int(_yr))
                    _pen = gdp_penetration(_rev, _g["gdp_mln"]) if _g else None
                    _pen_vals.append(fmt_pct(_pen) if _pen is not None else "—")
                if any(v != "—" for v in _pen_vals):
                    _rows.append(["Revenue as % of GDP"] + _pen_vals)
            _rows.append(["n (companies)"]
                         + [str(int(n)) for n in agg_table["n"]])
            agg_pivot = pd.DataFrame(_rows, columns=["Metric"] + _year_labels)
            st.dataframe(agg_pivot, use_container_width=True, hide_index=True)
            if _gdp and any(r[0] == "Revenue as % of GDP" for r in _rows):
                _gdp_years = sorted(_gdp.keys())
                st.caption(
                    "GDP penetration = sector aggregate Revenue ÷ Georgia nominal GDP "
                    f"(current prices, {_gdp_years[0]}–{_gdp_years[-1]}). "
                    "Source: Geostat — GDP at current prices."
                )

    # ---- Export: everything the page shows, downloadable ----------------------
    with tab_export:
        _export_key = tuple(picked_idcodes)
        _safe_name = "".join(ch if ch.isalnum() else "_" for ch in _title_suffix)[:40] or "sector"
        if st.button(
            f":material/download: Generate Excel — all financial data ({len(picked_idcodes)} companies)",
            key="sector_xlsx_gen",
            help="Build a single-sheet Excel of every IS / BS / CF line item × year for all companies in the current selection.",
        ):
            with st.spinner(f"Building Excel for {len(picked_idcodes)} companies…"):
                st.session_state["_sector_xlsx"] = _build_sector_financial_xlsx(
                    ctx.db_path, _export_key, _sectors_label
                )
                st.session_state["_sector_xlsx_for"] = _export_key
        if (
            st.session_state.get("_sector_xlsx_for") == _export_key
            and st.session_state.get("_sector_xlsx")
        ):
            st.download_button(
                ":material/download: Download Excel",
                data=st.session_state["_sector_xlsx"],
                file_name=f"financial_data_{_safe_name}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="sector_xlsx_dl",
            )
        # Light CSVs of what the Trends and Companies tabs show — raw
        # (unformatted) values so they load straight into a model.
        if not agg_table.empty:
            st.download_button(
                ":material/download: CSV — aggregate by year (picked metrics)",
                data=agg_table.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"sector_aggregate_{_safe_name}.csv",
                mime="text/csv",
                key="sector_agg_csv",
            )
        _co_export_cols = ["IdCode", "Company", "FVYear"] + [
            c for c in agg_cols if c in metrics_df.columns
        ]
        st.download_button(
            ":material/download: CSV — per-company metrics by year",
            data=metrics_df[_co_export_cols]
            .sort_values(["Company", "FVYear"])
            .to_csv(index=False)
            .encode("utf-8-sig"),
            file_name=f"sector_companies_{_safe_name}.csv",
            mime="text/csv",
            key="sector_co_csv",
        )

    # ---- Per-company × year matrix — lives in the Companies tab ------------
    with tab_companies:
        # Sprint 6: nested @st.fragment so toggling the metric radio re-runs ONLY
        # this block (a pure reshape of the already-built metrics_df) instead of
        # the whole script (DB re-resolve, company-list rebuild, snapshot table,
        # Plotly chart, …). metrics_df is captured by closure — the fragment is
        # defined after metrics_df is assigned and redefined on every full rerun,
        # so the captured frame can never go stale. No st.rerun() inside: the
        # radio interaction naturally reruns just the fragment.
        # Metric radio options are driven by the picker selection — one entry per
        # picked column that's actually present in metrics_df, by display label.
        # Falls back to the four base metrics if the user cleared the picker down to
        # columns the panel can't serve here.
        matrix_options: dict[str, str] = {}
        for _c in picker_cols:
            if _c in metrics_df.columns:
                matrix_options[label_for(_c)] = _c
        if not matrix_options:
            matrix_options = {
                "Revenue": "Revenue", "EBITDA": "EBITDA",
                "Net Profit": "NetProfit", "Total Assets": "TotalAssets",
            }

        @st.fragment
        def _per_company_matrix() -> None:
            st.markdown("##### Per-company contribution by year")
            option_labels = list(matrix_options.keys())
            chosen_label = st.radio(
                "Metric", option_labels, horizontal=True,
                key="sectorview_per_co_metric", label_visibility="collapsed",
            )
            # The radio's session value may be stale (a label removed from the
            # picker) on the run the options change — guard before indexing.
            if chosen_label not in matrix_options:
                chosen_label = option_labels[0]
            chosen_col = matrix_options[chosen_label]
            # Margins/ratios are per-company values — average duplicates rather than
            # sum them (a company appears once per year, so this is a no-op in
            # practice, but it keeps percent/ratio cells meaningful either way).
            aggfunc = "mean" if not is_money_column(chosen_col) else "sum"

            per_co_pivot = metrics_df.pivot_table(
                index=["IdCode", "Company"], columns="FVYear",
                values=chosen_col, aggfunc=aggfunc,
            )
            if not per_co_pivot.empty:
                revenue_pivot = metrics_df.pivot_table(
                    index=["IdCode", "Company"], columns="FVYear",
                    values="Revenue", aggfunc="sum",
                )
                latest_year_col = revenue_pivot.columns.max()
                rank_by_revenue = revenue_pivot[latest_year_col].sort_values(
                    ascending=False, na_position="last"
                ).index
                per_co_pivot = per_co_pivot.reindex(rank_by_revenue)
            per_co_pivot.columns = [str(int(y)) for y in per_co_pivot.columns]
            per_co_display = per_co_pivot.copy().reset_index()
            # Classify the metric ONCE and map a cheap formatter per column —
            # format_metric_value re-imported + re-classified per CELL, which
            # dominated render time on big sectors (100 cos × 15 yrs).
            from lib.format import fmt_k_gel, fmt_pct
            from lib.metric_picker import is_percent_column, is_ratio_column

            if is_percent_column(chosen_col):
                _fmt_one = fmt_pct
            elif is_ratio_column(chosen_col):
                _fmt_one = lambda v: f"{float(v):,.2f}×"  # noqa: E731
            else:
                _fmt_one = fmt_k_gel
            for col in per_co_display.columns:
                if col not in ("IdCode", "Company"):
                    per_co_display[col] = per_co_display[col].map(
                        lambda v: "" if pd.isna(v) else _fmt_one(v)
                    )
            st.dataframe(
                per_co_display, use_container_width=True, hide_index=True,
                column_config=_company_column_config(per_co_display["Company"]),
            )

        _per_company_matrix()
