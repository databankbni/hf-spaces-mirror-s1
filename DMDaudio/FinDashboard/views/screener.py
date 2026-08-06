"""Screener view (Sprint 4.5 — extracted from app.py).

Filter the company universe by financial metrics (saved presets, year scope,
filter builder, results table + CSV/XLSX export).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.cache import (
    company_sector_map,
    individual_panel_available,
    metrics_table,
    reduce_screener_frame_cached,
    universe_stats,
)
from lib.format import STALE_MARKER, is_stale, stale_caption
from lib.screener import (
    DEFAULT_METRICS,
    METRIC_TO_COLUMN,
    OPERATORS,
    PERCENT_METRICS,
    RATIO_METRICS,
    apply_operator,
    parse_value_shorthand,
    raw_line_item_by_year,
)
from lib.metric_picker import (
    SCREENER_DEFAULT_COLUMNS,
    is_percent_column,
    is_ratio_column,
    label_for,
    render_metric_picker,
)
from lib.ui import safe_key

from views.shared import ViewContext

# Label for companies that have no SubSector — must match views/sector.py so the
# sub-sector picker behaves identically across the two views.
_UNCLASSIFIED = "(unclassified)"


@st.cache_data(show_spinner=False, ttl=3600)
def _raw_line_item_by_year_cached(
    db_version: str, db_path: str, line_item: str, table: str
) -> pd.DataFrame:
    """Version-keyed cache over the free-form line-item DB lookup, so repeat
    screens on the same typed metric don't re-query the statement table."""
    return raw_line_item_by_year(db_path, line_item, table=table)


def rank_rows(
    rows: list[dict], rank_col: str | None, descending: bool = True
) -> list[dict]:
    """Stable-sort screener result ``rows`` by one metric column for top-N.

    Pure helper (no Streamlit) so the server-side ranking that backs the
    Screener's "Rank by" control is unit-testable. ``rows`` are the per-company
    result dicts (keys = display column names). When ``rank_col`` is ``None`` or
    absent the list is returned unchanged (preserves the historical order).

    Missing / non-numeric / NaN values always sort to the BOTTOM regardless of
    direction, so the kept top-N is never padded with blank-metric rows. Python's
    ``sorted`` is stable, so ties keep their incoming relative order.
    """
    if not rank_col:
        return list(rows)

    def _key(rec: dict) -> float:
        v = rec.get(rank_col)
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = None
        if f is None or f != f:  # None / NaN
            return float("-inf") if descending else float("inf")
        return f

    return sorted(rows, key=_key, reverse=descending)


def _sector_universe_filter(db_path: str, sector_slot, subs_slot) -> set[str] | None:
    """On-page sector (+ sub-sector) popovers for the Screener toolbar.

    Mirrors the sector + sub-sector selection in ``views/sector.py`` (reusing
    ``lib.sectors`` for the union / sub-sector logic) so behaviour is identical
    across views. Renders into the two pre-allocated ``fd_toolbar`` column
    slots passed in (the sub-sector slot stays empty unless the selection
    spans 2+ sub-sectors). Returns the set of IdCodes the screen should be
    restricted to, or ``None`` when no sector is selected (= all companies,
    current behaviour).

    Sprint-26 safety: the multiselect session-state keys are only written
    BEFORE the corresponding widget is instantiated (the re-seed block), never
    after; the popover chip counts are pre-widget session READS. Sub-sector
    keys are derived via ``safe_key`` because sector / sub-sector names contain
    Georgian text.
    """
    from lib.data_loader import get_curated_sector_buckets, get_sub_sectors
    from lib import sectors as _sectors

    @st.cache_data(show_spinner=False, ttl=3600)
    def _curated_buckets(_db_path: str) -> dict:
        return get_curated_sector_buckets(_db_path)

    @st.cache_data(show_spinner=False, ttl=3600)
    def _sub_sector_map(_db_path: str) -> dict:
        return get_sub_sectors(_db_path)

    curated = _curated_buckets(db_path)
    if not curated:
        # DB pre-dates the Sector migration — no sector filter available.
        return None
    sub_sector_map = _sub_sector_map(db_path)

    sector_names = list(curated.keys())

    # Re-seed the multiselect from our own non-widget copy before it
    # instantiates — Streamlit GC's widget state for widgets that skip a run
    # (e.g. while the user drills into Single Company). Same-run-BEFORE-widget
    # writes are Sprint-26-safe.
    if (
        "screener_sector_pick" not in st.session_state
        and "_screener_sector_saved" in st.session_state
    ):
        st.session_state["screener_sector_pick"] = [
            s for s in st.session_state["_screener_sector_saved"] if s in sector_names
        ]
    _sec_state = st.session_state.get("screener_sector_pick")
    _n_secs = len(_sec_state) if _sec_state else 0
    with sector_slot:
        with st.popover(
            ":material/category: Sectors" + (f" · {_n_secs}" if _n_secs else ""),
            use_container_width=True,
        ):
            st.caption(
                f"{len(curated)} sectors · restrict the screen to selected "
                "sector(s). Empty = all companies."
            )
            chosen_sectors = st.multiselect(
                "Restrict to sectors",
                sector_names,
                default=[],
                format_func=lambda s: f"{s}  ({len(curated[s])})",
                key="screener_sector_pick",
                label_visibility="collapsed",
                help=(
                    "Restrict the screen to companies in the selected sector(s). "
                    "Leave empty to screen the whole universe."
                ),
            )
    st.session_state["_screener_sector_saved"] = list(chosen_sectors)

    if not chosen_sectors:
        return None

    picked_idcodes = _sectors.union_idcodes(curated, chosen_sectors)

    # Sub-sector filter — pooled across the selected sectors, shown only when
    # the selection spans 2+ distinct sub-sectors (same rule as Sector View).
    sub_counts = _sectors.subsector_counts(picked_idcodes, sub_sector_map, _UNCLASSIFIED)
    available_subs = sorted(sub_counts.keys(), key=lambda s: (-sub_counts[s], s))
    if len(available_subs) > 1:
        # Key off the chosen-sector set so changing the sector selection
        # resets the sub-sector picker to its (all-selected) default. The
        # popover chip count is a pre-widget session read (absent = all).
        _subs_key = safe_key("screener_subs", ",".join(sorted(chosen_sectors)))
        _subs_state = st.session_state.get(_subs_key)
        _n_subs = len(_subs_state) if _subs_state is not None else len(available_subs)
        with subs_slot:
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
                        "Narrow the sector selection to specific sub-sectors. Clearing "
                        "all falls back to the full sector selection."
                    ),
                )
        if chosen_subs and len(chosen_subs) < len(available_subs):
            picked_idcodes = _sectors.filter_by_subsectors(
                picked_idcodes, sub_sector_map, chosen_subs, _UNCLASSIFIED
            )

    return set(picked_idcodes)


def render(ctx: ViewContext) -> None:
    # --- Statement basis (labeled; consolidated is the canonical basis) -----
    # The WIDGET lives in the Scope popover below; its committed value is read
    # here (pre-instantiation session read, Sprint-26-safe) so the whole screen
    # runs on one panel. Offered only when the individual twin exists in the DB.
    _basis_available = individual_panel_available(ctx.db_path)
    screen_basis = (
        "Individual"
        if _basis_available
        and str(st.session_state.get("screener_basis", "")).startswith("Individual")
        else "Consolidated"
    )
    _basis_fd_table = ("financial_data_individual" if screen_basis == "Individual"
                       else "financial_data")

    # Load the bulk metrics table (cached for an hour).
    metrics_df = metrics_table(
        ctx.db_path,
        panel_table=("metrics_panel_individual" if screen_basis == "Individual"
                     else "metrics_panel"),
    )
    if metrics_df.empty:
        st.warning("Metrics table is empty.")
        st.stop()

    # Saved screener presets — loaded up front; the LOAD buttons render in the
    # toolbar's Presets popover below, the save/delete flow lives in the
    # on-page expander inside the results fragment.
    from lib.filter_store import (
        load_filters as _load_screen_presets,
        add_filter_preset as _save_screen_preset,
        delete_filter_preset as _delete_screen_preset,
    )
    _screen_presets = _load_screen_presets()

    all_years_in_db = sorted(metrics_df.index.get_level_values("FVYear").unique())

    st.title("Screener")
    st.caption(
        "Filter the company universe by financial metrics. Values support shorthand: "
        "**100m** = 100M GEL, **1.5b** = 1.5B GEL, **20%** = 0.20 (margins/returns are stored as decimals)."
    )
    if screen_basis == "Individual":
        st.warning(
            ":material/swap_horiz: **Individual basis** — screening the recovered "
            "STANDALONE filings of the dual-basis filers only "
            f"({metrics_df.index.get_level_values('IdCode').nunique():,} companies). "
            "Every other company files a single basis and is screened under the "
            "standard consolidated panel. A parent's individual figures EXCLUDE "
            "its subsidiaries — don't sum rows across the two bases. Switch back "
            "under **Scope → Statement basis**.",
            icon=":material/swap_horiz:",
        )

    # ---- On-page controls (fd_toolbar popovers; was the sidebar) ------------
    # Same treatment as Single Company / Sector View: every screen-scope
    # control lives in a popover chip right above the filter builder. Chip
    # labels are pre-widget session READS (Sprint-26-safe). The preset LOAD
    # buttons must stay OUTSIDE the results fragment below: they write widget
    # keys (screener_metric_i / _op_i / _value_i) consumed by the filter rows
    # on the NEXT full run.
    _toolbar = st.container(key="fd_toolbar")
    _tc = _toolbar.columns([1.5, 1.5, 1.9, 1.6, 1.6, 1.4], vertical_alignment="center")

    # Scope: year scope + the optional IdCode-prefix restriction.
    _scope_state = str(st.session_state.get("screener_year_scope", "Latest"))
    _scope_short = "Avg 3y" if _scope_state.startswith("Average") else _scope_state
    if screen_basis == "Individual":
        _scope_short += " · Individual"
    year_scope_options = ["Latest"] + [str(y) for y in reversed(all_years_in_db)] + ["Average of last 3 years"]
    with _tc[0]:
        with st.popover(
            f":material/date_range: Scope · {_scope_short}",
            use_container_width=True,
        ):
            year_scope = st.selectbox(
                "Year scope",
                options=year_scope_options,
                index=0,
                key="screener_year_scope",
                help=(
                    "Latest: use each company's most-recent year.\n"
                    "<year>: use only that fiscal year.\n"
                    "Average of last 3 years: average each metric across each company's latest 3 reporting years."
                ),
            )
            # Activity / category text filter (optional).
            activity_filter = st.text_input(
                "Filter by IdCode prefix (optional)",
                value="",
                key="screener_idcode_filter",
                help="Narrow candidate companies by IdCode prefix substring before applying metric filters.",
            )
            if _basis_available:
                st.selectbox(
                    "Statement basis",
                    ["Consolidated (standard)", "Individual (dual-basis filers only)"],
                    key="screener_basis",
                    help=(
                        "Consolidated is the canonical screening basis (one row per "
                        "group, no double-counting). Individual switches to the "
                        "recovered STANDALONE filings — available only for the "
                        "~850 filers that submitted both bases; a parent's "
                        "individual figures exclude its subsidiaries."
                    ),
                )

    # ----- Sector / sub-sector universe filter (mirrors Sector View) ---------
    # Restricts the candidate universe to the chosen sector(s)/sub-sector(s)
    # BEFORE the metric filters run. Empty selection = all companies (current
    # behaviour). This is a "universe restriction" — like the IdCode-prefix
    # filter above, it applies LIVE on every full rerun (NOT gated on Run),
    # so flipping sectors immediately changes which companies a subsequent Run
    # screens over. The metric screen itself still applies only on Run and its
    # results stay pinned to the Run-time snapshot (see screener_ran_filters).
    #
    # Selection logic is reused from lib/sectors so the union / sub-sector
    # behaviour is identical to views/sector.py. Renders into toolbar slots
    # 1 + 2; returns the set of IdCodes the screen should be restricted to
    # (None = no sector filter / all companies).
    sector_restrict_idcodes = _sector_universe_filter(ctx.db_path, _tc[1], _tc[2])

    # ----- Metric columns picker (S&P Capital IQ comp-set style) -------------
    # Choose which metric columns appear in the results table (in addition to
    # the filter-derived metrics, which are always shown). Read here — BEFORE
    # the results fragment — so the chosen column list is captured by the
    # fragment closure and refreshed on every full rerun. The picker's own
    # session-state key persists the selection within the session (Sprint-26
    # safe: the picker never writes its key after the widget instantiates).
    _mp_state = st.session_state.get(safe_key("metric_picker", "screener"))
    with _tc[3]:
        with st.popover(
            ":material/view_column: Columns"
            + (f" · {len(_mp_state)}" if _mp_state else ""),
            use_container_width=True,
        ):
            picker_cols = render_metric_picker(
                ctx.db_path,
                "screener",
                SCREENER_DEFAULT_COLUMNS,
                label="Metrics to display",
                help=(
                    "Choose which metric columns appear in the results table. The "
                    "metrics you filter on are always shown in addition to these."
                ),
            )

    # ----- Saved screens — one-click preset load ------------------------------
    # Each preset is a list of {metric, op, value, logic} dicts that replaces
    # st.session_state["screener_filters"] on load. Save flow takes the current
    # filters under a new name (or overwrites an existing preset) in the
    # expander inside the fragment below.
    if _screen_presets:
        with _tc[4]:
            with st.popover(
                f":material/folder_open: Presets · {len(_screen_presets)}",
                use_container_width=True,
            ):
                st.caption(f"{len(_screen_presets)} saved · click to load")
                for _name in sorted(_screen_presets.keys()):
                    _filts = _screen_presets.get(_name, [])
                    if st.button(
                        f":material/folder_open: {_name}  ({len(_filts)} filters)",
                        key=safe_key("screener_load_preset", _name),
                        use_container_width=True,
                    ):
                        # Replace current filter list and rerun. Defensive copy
                        # so edits after load don't mutate the cached preset.
                        st.session_state["screener_filters"] = [
                            {
                                "metric": f.get("metric", "Revenue"),
                                "op": f.get("op", ">"),
                                "value": f.get("value", ""),
                                "logic": f.get("logic", "AND").upper(),
                            }
                            for f in _filts
                        ]
                        # Streamlit's text_input/selectbox widgets persist their
                        # session-state value across reruns, ignoring the `value=`
                        # parameter once the key exists. To make a "load preset"
                        # click actually update the visible widgets, set the widget
                        # session-state keys DIRECTLY here (allowed: st.rerun()
                        # aborts this run before those widgets instantiate in the
                        # fragment, so the writes land on the next run's widgets
                        # pre-instantiation). Pop any trailing keys from a
                        # previously-larger preset so they don't re-appear as
                        # ghost rows.
                        for i, f in enumerate(_filts):
                            st.session_state[f"screener_value_{i}"] = f.get("value", "")
                            st.session_state[f"screener_metric_{i}"] = f.get("metric", "Revenue")
                            st.session_state[f"screener_op_{i}"] = f.get("op", ">")
                            if i > 0:
                                st.session_state[f"screener_logic_{i}"] = (
                                    f.get("logic", "AND").upper()
                                )
                        for j in range(len(_filts), 20):  # generous trailing-row cleanup
                            for prefix in (
                                "screener_value_", "screener_metric_",
                                "screener_op_", "screener_logic_",
                                "screener_metric_legacy_",
                            ):
                                st.session_state.pop(f"{prefix}{j}", None)
                        st.session_state["screener_loaded_preset"] = _name
                        st.rerun()
                _loaded_preset = st.session_state.get("screener_loaded_preset")
                if _loaded_preset:
                    st.caption(
                        f"_Loaded: **{_loaded_preset}** (edit the filters, then "
                        "Save below to update)._"
                    )

    st.caption(
        f"Universe: {metrics_df.index.get_level_values('IdCode').nunique():,} companies "
        f"× {len(all_years_in_db)} years = {len(metrics_df):,} (company, year) rows."
    )

    # The reduced frame is the source of truth for metric values used in filters.
    # Cached by (db_path, year_scope) so adding/removing filter rows doesn't
    # re-do the groupby on 51k rows on every Streamlit rerun (was the cause of
    # the "lag/freeze when adding a second filter" issue).
    reduced, year_used_per_company = reduce_screener_frame_cached(ctx.db_path, year_scope)

    if activity_filter.strip():
        prefix = activity_filter.strip()
        keep = [idc for idc in reduced.index if prefix in idc]
        reduced = reduced.loc[keep]

    # Restrict to the chosen sector(s)/sub-sector(s), if any. Applied here (on
    # the full rerun, before the fragment captures `reduced`) so the sector
    # filter is a live universe restriction that a later Run screens over.
    if sector_restrict_idcodes is not None:
        keep = [idc for idc in reduced.index if idc in sector_restrict_idcodes]
        reduced = reduced.loc[keep]
        st.caption(
            f":material/filter_alt: Sector filter active — screening over **{len(reduced):,}** "
            f"companies in the selected sector(s)."
        )

    # ----- Filter builder + results fragment (Sprint 6) -------------------
    # Everything from the filter builder through the results table + drill
    # picker is one contiguous main-pane region whose interactions (add/remove
    # a filter row, edit a metric/op/value, Run, row-select) are pure in-view
    # work. Wrapping it in @st.fragment makes those interactions rerun ONLY
    # this function instead of the whole script (DB re-resolve, company-list
    # rebuild, sidebar, …).
    #
    # Closure captures (assigned above, refreshed on every full rerun, so they
    # cannot go stale): ctx, reduced, year_used_per_company, year_scope,
    # _screen_presets, _load_screen_presets, _save_screen_preset,
    # _delete_screen_preset.
    #
    # Rerun-scope discipline inside (st.rerun defaults to scope="app" even in
    # a fragment — Streamlit 1.56 signature):
    #   • + Add / - Remove filter  → NO st.rerun at all: the click already
    #     reruns just this fragment, and the row loop renders after the
    #     mutation in the same pass. (scope="fragment" would raise if the
    #     click were ever processed during a full app run, e.g. AppTest.)
    #   • Save / Delete preset     → st.rerun(scope="app")  (toolbar Presets popover)
    #   • Drill "Open in Single Company" → st.rerun(scope="app") (mode switch +
    #     _pending_single_pick is consumed at the top of single_company.render)
    # The toolbar preset-LOAD buttons stay outside the fragment: they write
    # widget keys consumed by widgets in here on the NEXT full run (Sprint-26
    # safe: write happens before those widgets instantiate on that run).
    @st.fragment
    def _filter_builder_and_results() -> None:
        # ----- Filter builder UI -----
        if "screener_filters" not in st.session_state:
            st.session_state["screener_filters"] = [
                {"metric": "Revenue", "op": ">", "value": "100m", "logic": "AND"}
            ]

        st.markdown("##### Filter builder")

        # Buttons row
        col_add, col_remove, col_run = st.columns([1, 1, 6])
        with col_add:
            if st.button("+ Add filter", key="screener_add_btn"):
                st.session_state["screener_filters"].append(
                    {"metric": "Revenue", "op": ">", "value": "", "logic": "AND"}
                )
                # No explicit st.rerun() needed: the click itself already
                # triggers a fragment-scoped rerun (the button lives in this
                # fragment), and the row loop below renders AFTER this
                # mutation in the same pass, so the new row appears
                # immediately. NB: st.rerun(scope="fragment") would raise
                # StreamlitAPIException whenever the click is processed
                # during a full app run (e.g. under AppTest) — avoid it here.
        with col_remove:
            if st.button("- Remove last", key="screener_remove_btn"):
                if len(st.session_state["screener_filters"]) > 1:
                    st.session_state["screener_filters"].pop()
                    # Same single-pass reasoning as "+ Add filter" — the row
                    # loop below already sees the popped list.
        with col_run:
            run_clicked = st.button("Run Screener", type="primary", key="screener_run_btn")

        # Save / overwrite the current filter set as a named preset. Name defaults
        # to the currently loaded preset (if any) so a quick edit-and-save acts as
        # "update this preset" rather than "save as new".
        with st.expander(":material/save: Save current filters as a preset…", expanded=False):
            save_col_name, save_col_btn = st.columns([5, 2])
            default_name = st.session_state.get("screener_loaded_preset", "")
            with save_col_name:
                new_preset_name = st.text_input(
                    "Preset name",
                    value=default_name,
                    key="screener_new_preset_name",
                    placeholder="e.g. 'My target shortlist'",
                    label_visibility="collapsed",
                )
            with save_col_btn:
                if st.button("Save preset", key="screener_save_preset_btn", use_container_width=True):
                    ok, msg = _save_screen_preset(
                        new_preset_name,
                        st.session_state.get("screener_filters", []),
                    )
                    if ok:
                        _load_screen_presets.clear()
                        st.session_state["screener_loaded_preset"] = new_preset_name.strip()
                        st.success(msg)
                        # App-scoped: the preset list lives in the TOOLBAR's
                        # Presets popover, outside this fragment — a fragment-
                        # scoped rerun would leave it stale.
                        st.rerun(scope="app")
                    else:
                        st.error(msg)
            # Delete dropdown for existing presets.
            if _screen_presets:
                del_col_pick, del_col_btn = st.columns([5, 2])
                with del_col_pick:
                    preset_to_delete = st.selectbox(
                        "Delete preset",
                        options=["—"] + sorted(_screen_presets.keys()),
                        index=0,
                        key="screener_delete_preset_pick",
                        label_visibility="collapsed",
                    )
                with del_col_btn:
                    if st.button(
                        "Delete preset",
                        key="screener_delete_preset_btn",
                        use_container_width=True,
                        disabled=(preset_to_delete == "—"),
                    ):
                        ok, msg = _delete_screen_preset(preset_to_delete)
                        if ok:
                            _load_screen_presets.clear()
                            if st.session_state.get("screener_loaded_preset") == preset_to_delete:
                                st.session_state.pop("screener_loaded_preset", None)
                            st.success(msg)
                            # App-scoped: the toolbar Presets popover must
                            # drop the deleted preset (it's outside this fragment).
                            st.rerun(scope="app")
                        else:
                            st.error(msg)

        metric_options = list(DEFAULT_METRICS)

        for i, flt in enumerate(st.session_state["screener_filters"]):
            cols = st.columns([1, 3, 2, 3])
            with cols[0]:
                if i == 0:
                    st.markdown("&nbsp;", unsafe_allow_html=True)
                    logic = "—"
                else:
                    logic = st.selectbox(
                        "Logic",
                        options=["AND", "OR"],
                        index=["AND", "OR"].index(flt.get("logic", "AND")),
                        key=f"screener_logic_{i}",
                        label_visibility="collapsed",
                    )
                    st.session_state["screener_filters"][i]["logic"] = logic
            with cols[1]:
                # Metric picker — accept_new_options for free-form line items.
                try:
                    metric_choice = st.selectbox(
                        "Metric",
                        options=metric_options,
                        index=metric_options.index(flt["metric"]) if flt["metric"] in metric_options else 0,
                        key=f"screener_metric_{i}",
                        accept_new_options=True,
                        label_visibility="collapsed",
                        placeholder="Pick a metric or type a raw LineItemENG…",
                    )
                except TypeError:
                    # Older Streamlit (<1.36) doesn't support accept_new_options — fall back.
                    metric_choice = st.selectbox(
                        "Metric",
                        options=metric_options,
                        index=metric_options.index(flt["metric"]) if flt["metric"] in metric_options else 0,
                        key=f"screener_metric_legacy_{i}",
                        label_visibility="collapsed",
                    )
                st.session_state["screener_filters"][i]["metric"] = metric_choice
            with cols[2]:
                op = st.selectbox(
                    "Op",
                    options=OPERATORS,
                    index=OPERATORS.index(flt["op"]) if flt["op"] in OPERATORS else 0,
                    key=f"screener_op_{i}",
                    label_visibility="collapsed",
                )
                st.session_state["screener_filters"][i]["op"] = op
            with cols[3]:
                value = st.text_input(
                    "Value",
                    value=flt.get("value", ""),
                    key=f"screener_value_{i}",
                    label_visibility="collapsed",
                    placeholder="e.g. 100m, 20%, -50m, or 50m,200m for between",
                )
                st.session_state["screener_filters"][i]["value"] = value

        st.markdown("&nbsp;", unsafe_allow_html=True)

        # ----- Evaluate filters when Run clicked -----
        # Snapshot the filter set at Run time so the results region survives
        # later reruns — st.button is truthy only on its click run, so gating
        # the results on run_clicked alone meant ANY post-run interaction
        # (e.g. picking a company in the drill selectbox) wiped the results
        # and made the drill-through button unreachable. Results stay pinned
        # to the snapshot until the next Run.
        if run_clicked:
            st.session_state["screener_ran_filters"] = [
                dict(f) for f in st.session_state["screener_filters"]
            ]
        ran_filters = st.session_state.get("screener_ran_filters")
        if ran_filters is not None:
            filters = ran_filters
            # Parse each filter's value upfront so we error early.
            parsed_filters: list[dict] = []
            parse_errors: list[str] = []
            for i, flt in enumerate(filters):
                raw_value = (flt.get("value") or "").strip()
                if not raw_value:
                    continue
                try:
                    if flt["op"] == "between":
                        parts = [p.strip() for p in raw_value.split(",")]
                        if len(parts) != 2:
                            raise ValueError(f"'between' value must be 'low,high' (got {raw_value!r})")
                        parsed_value: float | tuple[float, float] = (
                            parse_value_shorthand(parts[0]),
                            parse_value_shorthand(parts[1]),
                        )
                    else:
                        parsed_value = parse_value_shorthand(raw_value)
                except ValueError as exc:
                    parse_errors.append(f"Filter #{i + 1}: {exc}")
                    continue
                parsed_filters.append({
                    "metric": flt["metric"],
                    "op": flt["op"],
                    "value": parsed_value,
                    "logic": flt.get("logic", "AND"),
                })

            if parse_errors:
                for err in parse_errors:
                    st.error(err)

            if parsed_filters:
                # Per-run memo: _series_for_metric is called once per filter
                # AND once per free-form column per RESULT ROW below (the
                # 2026-07-02 review's worst screener hot spot) — without this
                # each call re-fetched + re-reduced the same frame.
                _series_memo: dict[str, pd.Series] = {}

                # Resolve each filter's metric to a Series indexed by IdCode aligned to `reduced`.
                def _series_for_metric(metric: str) -> pd.Series:
                    memo_hit = _series_memo.get(metric)
                    if memo_hit is not None:
                        return memo_hit
                    series = _series_for_metric_uncached(metric)
                    _series_memo[metric] = series
                    return series

                def _series_for_metric_uncached(metric: str) -> pd.Series:
                    if metric in METRIC_TO_COLUMN:
                        col = METRIC_TO_COLUMN[metric]
                        if col in reduced.columns:
                            return reduced[col]
                    # Free-form line item lookup. The user typed a raw LineItemENG —
                    # fetch a (IdCode, FVYear) frame and reduce it to the same scope.
                    from lib.cache import _db_version

                    raw_df = _raw_line_item_by_year_cached(
                        _db_version(ctx.db_path), ctx.db_path, metric, _basis_fd_table
                    )
                    if raw_df.empty:
                        return pd.Series(dtype=float, index=reduced.index)
                    if year_scope == "Latest":
                        # Pick the year that we used for this company in
                        # `reduced` — one vectorized MultiIndex reindex instead
                        # of a per-company .loc loop.
                        pairs = pd.MultiIndex.from_tuples(
                            [
                                (idc, year_used_per_company.get(idc))
                                for idc in reduced.index
                            ],
                            names=raw_df.index.names,
                        )
                        vals = raw_df["Value"].reindex(pairs)
                        return pd.Series(
                            vals.to_numpy(dtype=float), index=reduced.index
                        )
                    if year_scope == "Average of last 3 years":
                        raw_df_sorted = raw_df.sort_index()
                        last3 = raw_df_sorted.groupby(level="IdCode").tail(3)
                        return last3.groupby(level="IdCode")["Value"].mean()
                    # specific year
                    try:
                        year_int = int(year_scope)
                    except (TypeError, ValueError):
                        return pd.Series(dtype=float)
                    sub = raw_df.loc[raw_df.index.get_level_values("FVYear") == year_int]
                    return sub.reset_index(level="FVYear", drop=True)["Value"]

                # Build the mask left-to-right.
                combined: pd.Series | None = None
                for flt in parsed_filters:
                    series = _series_for_metric(flt["metric"])
                    if series.empty:
                        mask = pd.Series(False, index=reduced.index)
                    else:
                        aligned = series.reindex(reduced.index)
                        mask = apply_operator(aligned, flt["op"], flt["value"]).fillna(False)
                    if combined is None:
                        combined = mask
                    elif flt["logic"] == "OR":
                        combined = combined | mask
                    else:
                        combined = combined & mask

                if combined is None:
                    results = reduced.iloc[0:0]
                else:
                    results = reduced.loc[combined]

                # ----- Build result table -----
                company_lookup = dict(ctx.companies)
                sector_lookup = company_sector_map(ctx.db_path)
                metrics_used = [f["metric"] for f in parsed_filters]
                # De-dup while preserving order
                seen = set()
                ordered_metrics = []
                for m in metrics_used:
                    if m not in seen:
                        seen.add(m)
                        ordered_metrics.append(m)

                # Picker columns (metrics_panel column names, curated order)
                # become extra display columns IN ADDITION to the filter-derived
                # metrics. Skip any picker column that's already shown by a
                # filter metric (same underlying metrics_panel column) so a
                # filtered-on metric isn't duplicated. Each display column
                # carries its own format kind ("money" | "percent" | "ratio")
                # so the picker's classification helpers — not the screener's
                # label-based PERCENT_METRICS/RATIO_METRICS sets — drive the
                # NumberColumn format. Picker columns are keyed by their display
                # label (label_for) so they read as friendly headers.
                filter_cols_used = {
                    METRIC_TO_COLUMN[m] for m in ordered_metrics if m in METRIC_TO_COLUMN
                }
                picker_extra: list[tuple[str, str]] = []  # (display_label, panel_col)
                for col in picker_cols:
                    if col in filter_cols_used or col not in results.columns:
                        continue
                    picker_extra.append((label_for(col), col))

                # Map display-column name -> format kind for the formatter below.
                # Filter metrics use the screener's label-based sets; picker
                # columns use the metric_picker classification helpers.
                col_kind: dict[str, str] = {}
                for m in ordered_metrics:
                    if m in PERCENT_METRICS:
                        col_kind[m] = "percent"
                    elif m in RATIO_METRICS:
                        col_kind[m] = "ratio"
                    else:
                        col_kind[m] = "money"
                for disp_label, panel_col in picker_extra:
                    if is_percent_column(panel_col):
                        col_kind[disp_label] = "percent"
                    elif is_ratio_column(panel_col):
                        col_kind[disp_label] = "ratio"
                    else:
                        col_kind[disp_label] = "money"

                rows = []
                for idc, row in results.iterrows():
                    rec: dict = {
                        "IdCode": idc,
                        "Company": company_lookup.get(idc, ""),
                        "Sector": sector_lookup.get(idc, ""),
                        "FVYear": int(row["FVYear"]) if pd.notna(row.get("FVYear")) else None,
                    }
                    for m in ordered_metrics:
                        if m in METRIC_TO_COLUMN and METRIC_TO_COLUMN[m] in results.columns:
                            rec[m] = row[METRIC_TO_COLUMN[m]]
                        else:
                            # Free-form metric — pull from the raw_df
                            series = _series_for_metric(m)
                            rec[m] = series.get(idc)
                    for disp_label, panel_col in picker_extra:
                        rec[disp_label] = row[panel_col]
                    rows.append(rec)

                total_matches = len(rows)

                # ----- Server-side ranking (Sprint comp-set, Feature 2)
                # The analyst picks a "Rank by" metric + direction; we sort the
                # full match set (`rows`) by it. All matches are shown (paginated
                # below) — ranking just sets the order, so "largest first" / "top
                # decile by margin" reads naturally down the pages. (Historically
                # a hard 200-row cap sliced `rows` in arbitrary IdCode order and
                # hid everything past 200; ranking + pagination replaced it.)
                # Sprint-26-safe: the two widgets own their keys and are read
                # here, never written after instantiation.
                rank_options = list(ordered_metrics) + [
                    disp for disp, _col in picker_extra
                ]
                # De-dup while preserving order (a metric can appear in both
                # ordered_metrics and picker_extra in edge cases).
                _seen_rank: set[str] = set()
                rank_options = [
                    c for c in rank_options
                    if not (c in _seen_rank or _seen_rank.add(c))
                ]
                rank_col: str | None = None
                rank_desc = True
                if rank_options:
                    rk_col, rk_dir = st.columns([3, 2])
                    with rk_col:
                        rank_col = st.selectbox(
                            "Rank by",
                            options=rank_options,
                            index=0,
                            key="screener_rank_metric",
                            help=(
                                "Sort all matches by this metric. All matches are "
                                "shown (paginated below); this just sets the order."
                            ),
                        )
                    with rk_dir:
                        rank_dir_label = st.radio(
                            "Order",
                            options=["High → low", "Low → high"],
                            index=0,
                            horizontal=True,
                            key="screener_rank_dir",
                            help="Descending (largest first) or ascending (smallest first).",
                        )
                        rank_desc = rank_dir_label == "High → low"

                rows = rank_rows(rows, rank_col, descending=rank_desc)

                # ----- Pagination. All matches are kept (no cap); the table shows
                # one page at a time, while the download buttons below export the
                # FULL match set. Sprint-26-safe: both widgets own their keys and
                # are only read here, never written after instantiation.
                page_size_options = [25, 50, 100, 200, 500]
                pg_size_col, pg_num_col = st.columns([1, 3])
                with pg_size_col:
                    page_size = st.selectbox(
                        "Rows per page",
                        options=page_size_options,
                        index=page_size_options.index(50),
                        key="screener_page_size",
                    )
                n_pages = max(1, (total_matches + page_size - 1) // page_size)
                with pg_num_col:
                    page = int(st.number_input(
                        "Page",
                        min_value=1,
                        max_value=n_pages,
                        value=1,
                        step=1,
                        key="screener_page_num",
                        help=f"{n_pages:,} page(s) · {total_matches:,} matches total.",
                    ))
                # Clamp defensively in case a filter change shrank the match set
                # below the stored page number (the widget also clamps, but this
                # keeps the slice indices correct on the same run).
                page = min(page, n_pages)
                start = (page - 1) * page_size
                end = start + page_size
                shown_rows = rows[start:end]
                display_df = pd.DataFrame(shown_rows)

                if display_df.empty:
                    from lib.components import empty_state

                    empty_state(
                        "No companies match",
                        "Loosen a threshold, drop a filter, or widen the "
                        "sector / year scope — AND filters narrow quickly.",
                        icon="🎯",
                    )
                else:
                    # Keep values numeric so column-header sort sorts numerically
                    # (rather than lexicographically over pre-formatted strings).
                    # Money columns are converted to GEL thousands here so the unit
                    # in the header reads "(K GEL)" and the NumberColumn format
                    # uses a thousands separator. Percent columns stay as decimals
                    # and NumberColumn renders them as percentages with 1 decimal.
                    _dataset_max_year = universe_stats(ctx.db_path).get("year_max")

                    # Header renames + column_config depend only on which columns
                    # are present (same for the page and the full match set), so
                    # build them once. Money → "(K GEL)", percent → "(%)", ratio →
                    # "×" multiplier.
                    header_renames: dict[str, str] = {}
                    column_config: dict[str, object] = {}
                    for col in display_df.columns:
                        kind = col_kind.get(col)
                        if kind == "percent":
                            new = f"{col} (%)"
                            header_renames[col] = new
                            column_config[new] = st.column_config.NumberColumn(
                                new, format="percent",
                            )
                        elif kind == "ratio":
                            # Display as a multiplier with one decimal: "2.3×".
                            # No suffix in the header; the column label says everything.
                            new = f"{col}"
                            header_renames[col] = new
                            column_config[new] = st.column_config.NumberColumn(
                                new, format="%.2fx",
                            )
                        elif kind == "money":
                            new = f"{col} (K GEL)"
                            header_renames[col] = new
                            column_config[new] = st.column_config.NumberColumn(
                                new, format="%,d",
                            )

                    def _format_for_display(raw_df: pd.DataFrame) -> pd.DataFrame:
                        """Stale ⚠ markers + money→K GEL scaling + header renames.

                        Applied to the current page (for the table) and to the full
                        match set (for the downloads, which export every match, not
                        just the visible page). Keeps values numeric so the table's
                        column-header sort stays numeric. Stale marking runs BEFORE
                        header renames so "Company"/"FVYear" still have raw names.
                        """
                        f = raw_df.copy()
                        if "Company" in f.columns and "FVYear" in f.columns:
                            f["Company"] = [
                                f"{STALE_MARKER} {co}" if is_stale(fy, _dataset_max_year) else co
                                for co, fy in zip(f["Company"], f["FVYear"])
                            ]
                        for col, kind in col_kind.items():
                            if col in f.columns and kind == "money":
                                f[col] = pd.to_numeric(f[col], errors="coerce") / 1000.0
                        if header_renames:
                            f = f.rename(columns=header_renames)
                        return f

                    fmt_df = _format_for_display(display_df)

                    _last_shown = min(end, total_matches)
                    caption = (
                        f"Showing rows {start + 1:,}–{_last_shown:,} of "
                        f"{total_matches:,} matches (page {page:,} of {n_pages:,})."
                    )
                    if rank_col is not None:
                        _dir_word = "highest" if rank_desc else "lowest"
                        caption += f" Ranked by **{rank_col}** ({_dir_word} first)."
                    st.caption(caption)
                    st.caption(
                        "**Units** — money columns are in **GEL thousands** "
                        "(click the column header to sort). "
                        "Margin / return columns are percentages (decimals shown as `%`)."
                    )
                    _stale_cap = stale_caption(
                        [r.get("FVYear") for r in shown_rows], _dataset_max_year
                    )
                    if _stale_cap:
                        st.caption(_stale_cap)
                    # Use st.dataframe with single-row selection for drill-through.
                    try:
                        sel = st.dataframe(
                            fmt_df,
                            use_container_width=True,
                            hide_index=True,
                            height=600,
                            on_select="rerun",
                            selection_mode="single-row",
                            key="screener_results_table",
                            column_config=column_config,
                        )
                    except TypeError:
                        # Older Streamlit without selection support.
                        sel = None
                        st.dataframe(
                            fmt_df,
                            use_container_width=True,
                            hide_index=True,
                            height=600,
                            column_config=column_config,
                        )

                    # Export buttons — these export the FULL match set (every
                    # page), not just the page shown in the table above.
                    from lib.excel_export import dataframe_to_xlsx as _df_to_xlsx, dataframe_to_csv as _df_to_csv
                    all_df = pd.DataFrame(rows)          # all matches, raw numeric
                    full_fmt_df = _format_for_display(all_df)  # formatted for XLSX
                    export_subtitle = f"All {total_matches:,} matches"
                    if rank_col is not None:
                        _dir_word = "highest" if rank_desc else "lowest"
                        export_subtitle += f" · ranked by {rank_col} ({_dir_word} first)"
                    col_x, col_c = st.columns(2)
                    with col_x:
                        st.download_button(
                            f":material/download: Export all {total_matches:,} results (XLSX)",
                            data=_df_to_xlsx(
                                full_fmt_df, title=f"Screener Results",
                                subtitle=export_subtitle,
                                sheet_name="Screener",
                                label_col=full_fmt_df.columns[0] if len(full_fmt_df.columns) else None,
                                numeric_format=None,
                            ),
                            file_name="screener_results.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="screener_xlsx",
                        )
                    with col_c:
                        st.download_button(
                            f":material/download: All {total_matches:,} results (CSV)",
                            data=_df_to_csv(all_df),  # CSV uses raw numeric values
                            file_name="screener_results.csv",
                            mime="text/csv",
                            key="screener_csv",
                        )

                    # Drill-through: show a selectbox that pre-fills the Single Company picker.
                    idcodes_for_drill = [r["IdCode"] for r in shown_rows]
                    drill_labels = [
                        ctx.idcode_to_label.get(idc, idc) for idc in idcodes_for_drill
                    ]

                    # If a row was clicked, pre-select that one in the drill selectbox.
                    preselect = None
                    if sel is not None and getattr(sel, "selection", None) is not None:
                        sel_rows = sel.selection.get("rows", []) if isinstance(sel.selection, dict) else []
                        if sel_rows:
                            preselect_idx = sel_rows[0]
                            if 0 <= preselect_idx < len(drill_labels):
                                preselect = drill_labels[preselect_idx]

                    st.markdown("---")
                    col_pick, col_btn = st.columns([3, 1])
                    with col_pick:
                        drill = st.selectbox(
                            "Drill into a result",
                            options=drill_labels,
                            index=drill_labels.index(preselect) if preselect in drill_labels else None,
                            placeholder="Pick a company…",
                            key="screener_drill_picker",
                        )
                    with col_btn:
                        st.markdown("&nbsp;", unsafe_allow_html=True)  # vertical alignment spacer
                        if st.button(
                            ":material/open_in_new: Open in Single Company",
                            disabled=drill is None,
                            use_container_width=True,
                        ):
                            # Switch mode + pre-select the company in one click.
                            # App-scoped: navigation. The mode dispatch lives in
                            # app.py's top-level body and _pending_single_pick is
                            # consumed at the top of single_company.render() —
                            # neither runs on a fragment-scoped rerun.
                            st.session_state["_pending_single_pick"] = drill
                            st.session_state["mode"] = "Single Company"
                            st.rerun(scope="app")

    _filter_builder_and_results()
