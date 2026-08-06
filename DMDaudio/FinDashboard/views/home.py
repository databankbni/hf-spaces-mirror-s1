"""Home landing view (Sprint 4.5 — extracted from app.py).

Search hero + saved comp sets + recently-viewed + universe stats.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pandas as pd
import streamlit as st

from lib.cache import finder_universe, options_sorted_by_revenue_cached, universe_stats
from lib.finder import (
    SIZE_BUCKETS,
    SORT_OPTIONS,
    filter_universe,
    sector_of,
    sort_universe,
    subsector_options,
)
from lib.format import STALE_MARKER, fmt_k_gel, is_stale
from lib.sector_store import load_sectors as _load_sectors_home
from lib.ui import GOLD as _GOLD, HERO_GRADIENT as _HERO_GRADIENT, safe_key

from views.shared import ViewContext

# Public endpoint of the hosted remote MCP server (mcp/REMOTE.md). OAuth is
# handled automatically by Claude clients — no token for the user to manage.
_MCP_URL = "https://dmdaudio-findashboard-mcp.hf.space/mcp"


def _render_mcp_connect() -> None:
    """Collapsed how-to for adding the platform's MCP connector to Claude."""
    with st.expander(
        ":material/smart_toy: Use this data in Claude (MCP connector)", expanded=False
    ):
        st.markdown(
            "The full dataset is available inside **Claude** through a read-only "
            "[MCP](https://modelcontextprotocol.io) connector — ask in plain language "
            "(*“2023 net profit and ROE for Aldagi”*, *“rank retailers by revenue "
            "growth”*) and Claude pulls the figures straight from this database."
        )
        st.markdown("**claude.ai · Claude Desktop · mobile**")
        st.markdown(
            "1. Open **Settings → Connectors → Add custom connector**.\n"
            "2. Paste the server URL below and confirm — authorization completes "
            "automatically in the browser."
        )
        st.code(_MCP_URL, language=None)
        st.markdown("**Claude Code (terminal)**")
        st.code(
            f"claude mcp add --transport http georgian-financials {_MCP_URL}",
            language="bash",
        )
        st.caption(
            "Tools exposed: company search, per-year statements, precomputed metrics "
            "and ratios, sector aggregates, and multi-company comparison. The "
            "connector is read-only and carries the same data-quality provenance "
            "flags as this dashboard."
        )


def render(ctx: ViewContext) -> None:
    # --- Search hero ---------------------------------------------------------
    st.markdown(
        f"""
        <style>
          .findash-hero {{
            background: {_HERO_GRADIENT};
            padding: 26px 30px 18px 30px;
            border-radius: 10px;
            margin-bottom: 18px;
          }}
          .findash-hero h2 {{
            color: {_GOLD};
            font-size: 14px;
            letter-spacing: 0.10em;
            margin: 0 0 10px 0;
            font-weight: 600;
          }}
          .findash-hero p {{
            color: rgba(255,255,255,0.75);
            font-size: 12px;
            margin: 8px 0 0 0;
          }}
        </style>
        <div class="findash-hero">
          <h2>FIND A COMPANY</h2>
          <p>Pick a company below to open its full Income Statement, Balance Sheet, and Ratios.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _home_options = options_sorted_by_revenue_cached(ctx.db_path)
    home_pick = st.selectbox(
        "Find a company",
        options=_home_options,
        index=None,
        placeholder="Start typing a name or IdCode…",
        key="home_company_search",
        label_visibility="collapsed",
    )
    # Navigate only when the pick changes (prevents re-trapping on return to Home).
    if home_pick and home_pick != st.session_state.get("_home_nav_done"):
        st.session_state["_home_nav_done"] = home_pick
        _idc = ctx.labels_to_idcode[home_pick]
        st.session_state["mode"] = "Single Company"
        st.session_state["_pending_single_pick"] = home_pick
        st.query_params["mode"] = "single"
        st.query_params["id"] = _idc
        st.rerun()

    # New-user hint → the "How to use" tour dialog. Home renders AFTER app.py's
    # dialog-wiring pass, so the flag needs an explicit rerun to be picked up.
    if st.button(
        "New here? Take the quick tour of the platform",
        icon=":material/school:",
        key="home_open_tour",
        type="tertiary",
    ):
        from lib.ui_help import request_help_tour
        request_help_tour()
        st.rerun()

    # --- Company finder (T0.5) — browse by sector / size ----------------------
    # CapIQ-style: a filter rail over the whole universe with rich, clickable
    # results. Filtering/sorting semantics live in lib/finder.py (pure,
    # unit-tested); the frame comes from lib.cache.finder_universe
    # (company_search × latest metrics_panel year, cached on the DB version).
    st.markdown("##### Browse companies — sector, sub-sector, size")
    _uni = finder_universe(ctx.db_path)
    _dataset_max_year = universe_stats(ctx.db_path).get("year_max")

    _sector_counts = _uni["Sector"].map(sector_of).value_counts()
    _sector_opts = sorted(
        _sector_counts.index.tolist(), key=lambda s: (-int(_sector_counts[s]), s)
    )
    _fc = st.columns([2.2, 1.9, 1.9, 1.6, 1.8], vertical_alignment="bottom")
    with _fc[0]:
        _f_q = st.text_input(
            "Name / IdCode",
            key="home_finder_q",
            placeholder="Name contains, or IdCode starts with…",
        )
    with _fc[1]:
        _f_secs = st.multiselect(
            "Sectors",
            _sector_opts,
            key="home_finder_sectors",
            format_func=lambda s: f"{s}  ({int(_sector_counts[s])})",
            placeholder="All sectors",
        )
    with _fc[2]:
        # Options depend on the sector selection; keying the widget off that
        # selection resets stale picks when sectors change (absent key = empty
        # default — Sprint-26-safe, same pattern as Sectoral Data).
        _sub_opts = subsector_options(_uni, _f_secs)
        _f_subs = st.multiselect(
            "Sub-sectors",
            _sub_opts,
            key=safe_key("home_finder_subs", ",".join(sorted(_f_secs))),
            placeholder="All sub-sectors",
        )
    with _fc[3]:
        _f_size = st.selectbox(
            "Size (latest revenue)",
            [label for label, _lo, _hi in SIZE_BUCKETS],
            key="home_finder_size",
        )
    with _fc[4]:
        _f_sort = st.selectbox("Sort by", list(SORT_OPTIONS), key="home_finder_sort")

    _flt = sort_universe(
        filter_universe(
            _uni, query=_f_q, sectors=_f_secs, subsectors=_f_subs,
            size_bucket=_f_size,
        ),
        _f_sort,
    )
    _FINDER_LIMIT = 200
    _show = _flt.head(_FINDER_LIMIT).reset_index(drop=True)
    if _flt.empty:
        st.caption(":material/search_off: No companies match — loosen a filter.")
    else:
        _display = pd.DataFrame({
            "Company": [
                f"{STALE_MARKER} {n}" if is_stale(fy, _dataset_max_year) else str(n)
                for n, fy in zip(_show["CompanyName"], _show["LatestFVYear"])
            ],
            "IdCode": _show["IdCode"],
            "Sector": _show["Sector"].map(sector_of),
            "Sub-sector": _show["SubSector"].map(lambda v: sector_of(v) if v else "—"),
            "Latest FY": _show["LatestFVYear"].map(
                lambda y: str(int(y)) if pd.notna(y) else "—"),
            "Revenue (K)": _show["Revenue"].map(
                lambda v: fmt_k_gel(v) if pd.notna(v) else "—"),
            "Net Profit (K)": _show["NetProfit"].map(
                lambda v: fmt_k_gel(v) if pd.notna(v) else "—"),
            "Total Assets (K)": _show["TotalAssets"].map(
                lambda v: fmt_k_gel(v) if pd.notna(v) else "—"),
        })
        _cap = (
            f"{len(_flt):,} match — showing the top {_FINDER_LIMIT}"
            if len(_flt) > _FINDER_LIMIT else f"{len(_flt):,} "
            + ("company" if len(_flt) == 1 else "companies")
        )
        st.caption(_cap + " · click a row to open the company")
        _ev = st.dataframe(
            _display,
            key="home_finder_results",
            on_select="rerun",
            selection_mode="single-row",
            use_container_width=True,
            hide_index=True,
            height=min(38 + 35 * len(_display), 420),
        )
        _sel_rows = list(_ev.selection.rows) if _ev and _ev.selection else []
        if _sel_rows:
            _idc = str(_show.iloc[_sel_rows[0]]["IdCode"])
            # Navigate once per pick (same guard as the hero selectbox) so
            # returning to Home doesn't re-trap on the persisted selection.
            if _idc != st.session_state.get("_home_finder_nav_done"):
                st.session_state["_home_finder_nav_done"] = _idc
                st.session_state["mode"] = "Single Company"
                st.session_state["_pending_single_pick"] = ctx.idcode_to_label.get(
                    _idc, _idc)
                st.query_params["mode"] = "single"
                st.query_params["id"] = _idc
                st.rerun()

    st.markdown("---")

    # --- Saved comp sets -----------------------------------------------------
    _home_sectors = _load_sectors_home()
    if _home_sectors:
        st.markdown("##### Jump to a saved comp set")
        _sector_names = sorted(_home_sectors.keys())
        _cols = st.columns(min(4, len(_sector_names)))
        for _i, _name in enumerate(_sector_names):
            _codes = _home_sectors.get(_name, [])
            _in_db = sum(1 for c in _codes if c in ctx.idcode_to_label)
            with _cols[_i % len(_cols)]:
                if st.button(
                    f":material/folder_open: {_name}  ({_in_db})",
                    key=safe_key("home_sector", _name),
                    use_container_width=True,
                ):
                    st.session_state["compare_picker"] = [
                        ctx.idcode_to_label[c] for c in _codes if c in ctx.idcode_to_label
                    ]
                    st.session_state["compare_loaded_sector"] = _name
                    st.session_state["mode"] = "Compare"
                    st.query_params["mode"] = "compare"
                    st.rerun()

    st.markdown("---")

    # --- Recently viewed + Universe stats (two columns) ----------------------
    _left, _right = st.columns(2)

    with _left:
        st.markdown("##### Recently viewed")
        _recent = st.session_state.get("recent_companies", [])
        if _recent:
            for _idc in _recent:
                _lbl = ctx.idcode_to_label.get(_idc, _idc)
                if st.button(_lbl, key=safe_key("home_recent", _idc), use_container_width=True):
                    st.session_state["mode"] = "Single Company"
                    st.session_state["_pending_single_pick"] = ctx.idcode_to_label.get(_idc, _idc)
                    st.query_params["mode"] = "single"
                    st.query_params["id"] = _idc
                    st.rerun()
        else:
            st.caption("_No companies viewed yet this session. Use the search above._")

    with _right:
        st.markdown("##### Universe")
        _stats = universe_stats(ctx.db_path)
        _mtime = Path(ctx.db_path).stat().st_mtime if Path(ctx.db_path).exists() else 0
        _mtime_str = _dt.datetime.fromtimestamp(_mtime).strftime("%Y-%m-%d %H:%M") if _mtime else "—"
        st.markdown(
            f"""
            - **{_stats['n_companies']:,}** companies tracked
            - **FY {_stats['year_min']}–{_stats['year_max']}** coverage
            - **{_stats['n_rows']:,}** financial data points
            - **{len(_home_sectors)}** saved comp sets
            - DB last updated: **{_mtime_str}**
            """
        )

    st.markdown("---")

    # --- Claude / MCP connector how-to ----------------------------------------
    _render_mcp_connect()
