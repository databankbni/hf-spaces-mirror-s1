"""Compare view (Sprint 4.5 — extracted from app.py).

Side-by-side and aggregate comparison of multiple companies: picker + bulk
import + saved comp sets, IS/BS/Ratios side-by-side, aggregate chart and
per-company contribution matrix, CSV/XLSX export.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.cache import (
    bs_sections,
    is_sections,
    metrics_table,
    panel_columns_for_idcodes,
    ratios,
    years,
)
from lib.consolidation import dedup_panel_df, excluded_pairs
from lib.format import fmt_k_gel, fmt_pct
from lib.metric_picker import (
    COMPARE_DEFAULT_COLUMNS,
    is_money_column,
    label_for,
    render_metric_picker,
)
from lib.ratios import build_ratios_table
from lib.ui import BURGUNDY, safe_key, shared_table_styles
from lib.ui_chips import company_typeahead

from views.shared import (
    BASE_AGG_COLUMNS,
    DERIVABLE_MARGINS,
    ViewContext,
    adjusted_is_sections_for,
    company_short_name,
    format_metric_value,
    render_ifrs_controls,
    section_total_at,
    sector_metrics_panel,
)


# ---------------------------------------------------------------------------
# Pure helpers for the multi-year side-by-side table (Feature 3) — extracted so
# the column layout + record building are unit-testable without a Streamlit
# runtime or a DB. Sections are passed in as already-built dicts.
# ---------------------------------------------------------------------------

def compare_year_options(year_sets: dict[str, list[int]]) -> list[int]:
    """Selectable fiscal years for a picked peer set — the UNION, ascending.

    Union, deliberately, NOT the intersection: a year that ANY picked company
    filed must stay pickable. Intersecting made one lagging filer hide the year
    for the whole peer set (the FY2024-missing-from-Compare bug: six clinics,
    four of which had FY2024, but two peers whose latest filing was FY2023
    truncated the option list at 2023 for everyone). Companies with no filing
    for a selected year render blank cells instead — see ``unreported_pairs``.
    """
    if not year_sets:
        return []
    return sorted(set().union(*(set(int(y) for y in ys) for ys in year_sets.values())))


def unreported_pairs(
    year_sets: dict[str, list[int]],
    selected_years: list[int],
) -> set[tuple[str, int]]:
    """``(idcode, year)`` pairs the company has no filing for.

    Drives blank ("—"-style empty) cells for the peers that simply didn't report
    a selected year, so a union year list never shows a misleading 0 for a
    company that never filed. Keyed on *coverage*, not on the value, so a
    genuinely-zero line item is still rendered as 0.
    """
    sel = [int(y) for y in selected_years]
    return {
        (idc, y)
        for idc, ys in year_sets.items()
        for y in sel
        if y not in {int(x) for x in ys}
    }


def year_coverage_note(
    year_sets: dict[str, list[int]],
    selected_years: list[int],
    short_names: dict[str, str] | None = None,
) -> str | None:
    """Warning text when a selected year isn't filed by every picked company.

    ``None`` when every picked company covers every selected year (the common
    case — no warning shown). Otherwise names the thin years so the analyst
    knows the blank cells are missing filings, not zeros.
    """
    sel = sorted({int(y) for y in selected_years})
    if not sel or not year_sets:
        return None
    missing = unreported_pairs(year_sets, sel)
    if not missing:
        return None
    total = len(year_sets)
    names = short_names or {}
    bits = []
    for y in sel:
        absent = sorted(idc for idc, yr in missing if yr == y)
        if not absent:
            continue
        if len(absent) <= 2:
            who = " and ".join(names.get(idc, idc) for idc in absent)
            bits.append(f"FY{y}: no filing for {who}")
        else:
            bits.append(f"FY{y}: {len(absent)} of {total} companies have no filing")
    return (
        "Not every picked company reports every selected year — "
        + "; ".join(bits)
        + ". Those cells are left blank (no filing), not zero."
    )


def compare_column_specs(
    picked_idcodes: list[str],
    selected_years: list[int],
    short_names: dict[str, str],
) -> list[tuple[str, str, int]]:
    """Ordered ``(column_label, idcode, year)`` triples for the comparison table.

    Company-major, year-ascending. With a single year the column header is just
    the company short name (back-compat with the historical single-year table +
    its Excel export); with several years each column is ``"<short> · FY<year>"``
    so peers stay grouped and the years read left→right.
    """
    multi_year = len(selected_years) > 1

    def _col_label(idc: str, year: int) -> str:
        short = short_names.get(idc, idc)
        return f"{short} · FY{year}" if multi_year else short

    return [
        (_col_label(idc, y), idc, y)
        for idc in picked_idcodes
        for y in selected_years
    ]


def common_size_pct_str(v: float) -> str:
    """Decimal proportion -> margin-style percent string (matches lib.ui).

    Delegates to the shared ``lib.format.fmt_pct_signed`` (parenthesized
    negatives, blank zero, ≥1 decimal, honors the global precision setting).
    """
    from lib.format import fmt_pct_signed

    return fmt_pct_signed(v)


# Re-export the pure peer-percentile helper so callers (and tests) can reach it
# via views.compare while its canonical home stays lib.metric_picker.
from lib.metric_picker import percentile_within_group, fmt_percentile  # noqa: E402,F401


def summary_stats(series) -> dict[str, float]:
    """NaN-skipping mean + median of a numeric Series, as a plain dict.

    Used to append Mean / Median summary columns to the Compare side-by-side
    table. Returns ``{"mean": nan, "median": nan}`` when nothing is numeric so
    the caller renders a blank cell rather than raising.
    """
    import pandas as pd

    s = pd.to_numeric(pd.Series(series), errors="coerce").dropna()
    if s.empty:
        return {"mean": float("nan"), "median": float("nan")}
    return {"mean": float(s.mean()), "median": float(s.median())}


def build_compare_records(
    template_sections: list[dict],
    sections_by_idc: dict[str, list[dict]],
    col_specs: list[tuple[str, str, int]],
    kind: str,
    *,
    common_size: bool = False,
    unreported: set[tuple[str, int]] | None = None,
) -> tuple[list[dict], list[int]]:
    """Build the side-by-side record list + bold-row indices.

    Rows follow ``template_sections`` order (the first company's section list);
    every company's totals are looked up by label so a missing section simply
    reads 0. With ``common_size=True`` each value cell is a pre-formatted percent
    string of the per-(company, year) base (Revenue for IS, Total Assets for BS);
    otherwise cells are raw floats. Every row here is a section total, so all
    rows are bold.

    ``unreported`` (``{(idcode, year)}``, from ``unreported_pairs``) marks
    company-years with no filing at all: those cells render as the empty string
    so the union year list shows a blank rather than a misleading 0.
    """
    from lib.ui import common_size_base as _common_size_base
    from views.shared import section_total_at as _section_total_at

    # Per-(idc) base lookups, computed once.
    base_by_idc: dict[str, dict[int, float]] = {}
    if common_size:
        for _label, idc, _year in col_specs:
            if idc not in base_by_idc:
                base_by_idc[idc] = _common_size_base(sections_by_idc[idc], kind)

    blank = unreported or set()
    records: list[dict] = []
    bold_rows: list[int] = []
    for s in template_sections:
        lookup_label = s["label"].replace(" (adj.)", "")
        rec: dict = {"Line Item": lookup_label}
        for col_label, idc, year in col_specs:
            if (idc, int(year)) in blank:
                # No filing for this company-year — blank, not zero.
                rec[col_label] = ""
                continue
            raw = _section_total_at(sections_by_idc[idc], lookup_label, year)
            if common_size:
                base = base_by_idc.get(idc, {}).get(int(year), 0.0) or 0.0
                rec[col_label] = common_size_pct_str(raw / base) if base else ""
            else:
                rec[col_label] = raw
        records.append(rec)
        bold_rows.append(len(records) - 1)
    return records, bold_rows


def render(ctx: ViewContext) -> None:
    # Top-level entity toggle: compare COMPANIES (the historical Compare view)
    # or compare SECTORS / sub-sectors (aggregate-vs-aggregate). On the page
    # (was a sidebar radio) so the switch sits with the content it swaps. The
    # sector branch is a self-contained surface that reuses the same
    # metrics_panel aggregation rules as Sector View; it returns early so the
    # company-compare sidebar + body below never builds when sectors are being
    # compared.
    entity = st.radio(
        "Compare",
        ["Companies", "Sectors / sub-sectors"],
        horizontal=True,
        key="compare_entity",
        help=(
            "Companies: line-item / aggregate comparison of individual companies. "
            "Sectors: aggregate metrics (margins, returns, growth, size) across "
            "two or more sectors or sub-sectors, side by side."
        ),
    )
    if entity == "Sectors / sub-sectors":
        _render_sector_compare(ctx)
        return

    # URL → state: seed the peer set from ?companies=idc1,idc2,… on first
    # load so Compare links are shareable / bookmarkable (mirrors Single
    # Company's ?id=). Only when the picker key doesn't exist yet — after
    # that session state is the source of truth and we mirror it back into
    # the URL after the picker renders. `compare_picker` is a plain state
    # list (not a widget key), so writing it here is Sprint-26-safe.
    if "compare_picker" not in st.session_state:
        _url_cos = st.query_params.get("companies")
        if _url_cos:
            _seed_labels = [
                ctx.idcode_to_label[c.strip()]
                for c in _url_cos.split(",")
                if c.strip() in ctx.idcode_to_label
            ]
            if _seed_labels:
                st.session_state["compare_picker"] = _seed_labels

    # Unified peer-set workspace — company picker, saved sets, bulk import and
    # save/manage all live in an ON-PAGE toolbar of popover chips (only the
    # Ask-Claude dock stays in the sidebar). The main pane then toggles between
    # two views over the SAME picked set:
    #   • Side-by-side  — line-item × company table for one year (IS / BS /
    #                     Ratios tabs). Needs 2+ companies.
    #   • Aggregate     — sum across all companies, chart + per-company
    #                     contribution-by-year matrix. Works with 1+.
    # Replaces the former separate "Comp Sets" mode — same saved-set storage
    # (sector_store.json), same picker key, just one consolidated place.
    from lib.sector_store import (
        load_sectors, add_sector, delete_sector, parse_idcode_list,
    )

    saved_sectors = load_sectors()

    # ---- Header + peer-set toolbar (on-page; was the sidebar) ---------------
    # The title reads the picked count from session_state BEFORE the picker
    # instantiates — a pre-widget READ (Sprint-26-safe); it matches what the
    # picker returns on a normal run (the picker's Add/remove/clear paths all
    # st.rerun after mutating, so the next run's read is fresh).
    _n_picked = len(st.session_state.get("compare_picker", []))
    st.title(
        "Compare"
        + (f" — {_n_picked} {'company' if _n_picked == 1 else 'companies'}"
           if _n_picked else "")
    )

    _peers = st.container(key="fd_toolbar_peers")
    _pc = _peers.columns([1.8, 1.7, 1.7, 2.8], vertical_alignment="center")

    # ---- Companies picker chip ----
    with _pc[0]:
        _co_pop = st.popover(
            f":material/groups: Companies · {_n_picked}",
            use_container_width=True,
        )
    picked_labels = company_typeahead(
        ctx.db_path,
        key_prefix="compare",
        label="Companies",
        placeholder="Pick companies…",
        container=_co_pop,
    )
    picked_idcodes = [ctx.labels_to_idcode[label] for label in picked_labels]

    # state → URL: keep ?companies= in sync with the picked set so the link
    # is shareable and survives a refresh. Loop-safe (query_params assignment
    # doesn't rerun); dropped entirely when the selection is empty.
    _url_val = ",".join(picked_idcodes)
    if picked_idcodes:
        if st.query_params.get("companies") != _url_val:
            st.query_params["companies"] = _url_val
    elif "companies" in st.query_params:
        del st.query_params["companies"]

    # ---- Comp sets chip — one-click load + save/manage ----
    with _pc[1]:
        _cs_pop = st.popover(
            f":material/folder: Comp sets · {len(saved_sectors)}",
            use_container_width=True,
        )
    with _cs_pop:
        if saved_sectors:
            st.caption(f"{len(saved_sectors)} saved · click to load")
            for _name in sorted(saved_sectors.keys()):
                _codes = saved_sectors.get(_name, [])
                _in_db = sum(1 for c in _codes if c in ctx.idcode_to_label)
                if st.button(
                    f":material/folder_open: {_name}  ({_in_db} cos)",
                    key=safe_key("compare_load_sector", _name),
                    use_container_width=True,
                ):
                    st.session_state["compare_picker"] = [
                        ctx.idcode_to_label[c] for c in _codes if c in ctx.idcode_to_label
                    ]
                    st.session_state["compare_loaded_sector"] = _name
                    st.rerun()
            if st.button(":material/close: Clear selection", key="compare_clear_sector_btn"):
                st.session_state["compare_picker"] = []
                st.session_state.pop("compare_loaded_sector", None)
                st.rerun()
        else:
            st.caption(
                "_No saved comp sets yet. Pick companies, then use "
                "**Save current selection** below._"
            )
        st.markdown("---")
        # Save / manage the current selection as a named comp set.
        new_set_name = st.text_input(
            "Save current selection as…", key="compare_save_name",
            placeholder="e.g. Tier-1 banks",
        )
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button(":material/save: Save", key="compare_save_btn",
                         use_container_width=True,
                         disabled=not (picked_idcodes and new_set_name.strip())):
                ok, msg = add_sector(new_set_name, picked_idcodes)
                (st.success if ok else st.error)(msg)
                st.rerun()
        with col_b:
            if saved_sectors:
                to_delete = st.selectbox(
                    "Delete comp set",
                    ["—"] + sorted(saved_sectors.keys()),
                    key="compare_delete_picker",
                    label_visibility="collapsed",
                )
                if to_delete != "—" and st.button(
                    ":material/delete: Delete", key="compare_delete_btn",
                    use_container_width=True,
                ):
                    ok, msg = delete_sector(to_delete)
                    (st.success if ok else st.error)(msg)
                    st.rerun()

    # ---- Bulk import chip ----
    with _pc[2]:
        _bulk_pop = st.popover(
            ":material/content_paste: Bulk import",
            use_container_width=True,
        )
    with _bulk_pop:
        bulk_text = st.text_area(
            "Paste IdCodes (one per line, or comma/space-separated)",
            height=100,
            key="compare_bulk_import",
            placeholder="202177205\n200050675\n404399236",
        )
        if st.button("Add to selection", key="compare_bulk_apply"):
            requested = parse_idcode_list(bulk_text)
            valid = [c for c in requested if c in ctx.idcode_to_label]
            missing = [c for c in requested if c not in ctx.idcode_to_label]
            current = set(picked_idcodes)
            new_codes = [c for c in valid if c not in current]
            if new_codes:
                merged_labels = (
                    list(picked_labels) + [ctx.idcode_to_label[c] for c in new_codes]
                )
                st.session_state["compare_picker"] = merged_labels
                st.session_state.pop("compare_loaded_sector", None)
                st.success(f"Added {len(new_codes)} new IdCode(s).")
                if missing:
                    st.warning(f"Not found in DB: {', '.join(missing[:10])}"
                               + ("…" if len(missing) > 10 else ""))
                st.rerun()
            elif valid:
                st.info("All pasted IdCodes were already selected.")
            else:
                st.error(
                    "No valid IdCodes recognized. "
                    + (f"Tried: {', '.join(requested[:5])}…" if requested else "")
                )

    # ---- Empty state ----
    if not picked_idcodes:
        from lib.components import empty_state

        empty_state(
            "Build a peer set",
            "Use the **Companies** control above to pick companies, paste a "
            "list of IdCodes via **Bulk import**, or load a saved **Comp set** "
            "— then compare them side-by-side or as an aggregate.",
            icon="📊",
        )
        st.stop()

    # ---- View toggle (main pane) ----
    view_mode = st.radio(
        "View",
        ["Side-by-side", "Aggregate"],
        horizontal=True,
        key="compare_view_mode",
        help=(
            "Side-by-side: line-item × company table for one year (IS / BS / Ratios). "
            "Aggregate: sum across companies, chart + per-company contribution by year."
        ),
    )

    # ---- On-page controls (fd_toolbar popovers; was the sidebar) ------------
    # Years / display toggles / IFRS 16 / metric columns live in popover chips
    # right under the view toggle (same treatment as Single Company / Sector
    # View). Slot 0 swaps per view mode (fiscal years vs years-to-display),
    # slot 1 is Side-by-side-only; the IFRS and Metrics chips render for both
    # modes (as the sidebar always did) so their widget state never skips a
    # run within Compare. Chip labels are pre-widget session READS
    # (Sprint-26-safe).
    selected_year = None
    selected_years: list[int] = []
    year_note = None
    coverage_note: str | None = None
    unreported: set[tuple[str, int]] = set()
    agg_selected_years: list[int] | None = None
    MAX_COMPARE_YEARS = 5  # keep the N companies × Y years table readable

    # Per-company filed-year coverage, read once and shared by BOTH view modes so
    # their year pickers can never drift apart (they used to: side-by-side
    # intersected, Aggregate unioned).
    year_sets = {idc: list(years(ctx.db_path, idc)) for idc in picked_idcodes}

    _toolbar = st.container(key="fd_toolbar")
    _tc = _toolbar.columns([1.4, 1.6, 1.4, 1.5, 3.1], vertical_alignment="center")

    if view_mode == "Side-by-side":
        # Multi-year trend (Feature 3): the side-by-side table used to be
        # locked to a SINGLE fiscal year (only section totals). It now accepts
        # a year RANGE so the same line item shows across several years per
        # peer — the core CapIQ comp view. ``selected_years`` is the (sorted,
        # capped) display range; ``selected_year`` stays the single PRIMARY
        # year (the latest selected) used for the Revenue column-sort and the
        # Ratios tab (still single-year).
        # Year options are the UNION of the picked companies' filed years. This
        # used to be the INTERSECTION, which let a single lagging filer delete a
        # year from the option list for the entire peer set — the reported bug
        # (FY2024 unpickable across six clinics because two peers' latest filing
        # was FY2023). A peer with no filing for a selected year now renders
        # blank cells instead of hiding the year.
        year_choices = compare_year_options(year_sets)

        if year_choices:
            # Default to the latest year only (preserves the historical
            # single-year default); the analyst can add up to MAX_COMPARE_YEARS
            # for a trend. Keyed by the picked-company set so changing the peer
            # set re-seeds the default rather than carrying a stale pick.
            _yr_key = safe_key("compare_years_multi", ",".join(sorted(picked_idcodes)))
            _yr_state = st.session_state.get(_yr_key)
            _n_yrs = min(len(_yr_state), MAX_COMPARE_YEARS) if _yr_state else 1
            with _tc[0]:
                with st.popover(
                    f":material/date_range: Years · {_n_yrs}",
                    use_container_width=True,
                ):
                    picked_years = st.multiselect(
                        "Fiscal year(s)",
                        options=list(reversed(year_choices)),
                        default=[year_choices[-1]],
                        key=_yr_key,
                        help=(
                            f"Pick 1–{MAX_COMPARE_YEARS} years. With one year you get the "
                            "classic single-year side-by-side; with several you get a "
                            "multi-year trend per peer (line item × year per company)."
                        ),
                    )
            if not picked_years:
                picked_years = [year_choices[-1]]
            selected_years = sorted(int(y) for y in picked_years)
            if len(selected_years) > MAX_COMPARE_YEARS:
                # Keep the most-recent MAX_COMPARE_YEARS so the table stays legible.
                selected_years = selected_years[-MAX_COMPARE_YEARS:]
                year_note = (
                    (year_note + " ") if year_note else ""
                ) + (
                    f"Showing the most recent {MAX_COMPARE_YEARS} of the selected "
                    "years to keep the table readable."
                )
            # Primary year = latest selected — drives the Revenue sort + Ratios tab.
            selected_year = selected_years[-1]

            # Coverage: with union options a selected year may be unfiled by some
            # peers. Mark those company-years (blank cells) and say so, so the
            # gaps read as "didn't file", not as zero.
            unreported = unreported_pairs(year_sets, selected_years)
            coverage_note = year_coverage_note(
                year_sets,
                selected_years,
                {idc: company_short_name(ctx.companies, idc) for idc in picked_idcodes},
            )

            # Display toggles — common-size + (single-year only) peer summary.
            # Sprint-26-safe: the checkboxes own their keys and are read-only
            # after instantiation; the chip's "on" marker is a pre-widget read.
            _cs_on = bool(st.session_state.get("compare_common_size", False))
            _ps_on = (
                len(selected_years) == 1
                and bool(st.session_state.get("compare_peer_summary", False))
            )
            with _tc[1]:
                with st.popover(
                    ":material/percent: Display"
                    + ("  ·  on" if (_cs_on or _ps_on) else ""),
                    use_container_width=True,
                ):
                    # Common-size toggle (Feature 1 reaches Compare side-by-side
                    # here): re-express every IS line as % of Revenue and every
                    # BS line as % of Total Assets, per company per year.
                    st.checkbox(
                        "Common-size (% of Revenue / Total Assets)",
                        key="compare_common_size",
                        help=(
                            "Re-express each line as a percentage of Revenue (Income "
                            "Statement) or Total Assets (Balance Sheet) for that company "
                            "and year — the comparable, scale-free view."
                        ),
                    )
                    # Peer summary (Feature 4): append Mean / Median columns and
                    # highlight each row's max (green) / min (burgundy) across
                    # the peer columns. Only meaningful for a single year
                    # (multiple years would mix periods into one row stat), so
                    # it's offered only then.
                    if len(selected_years) == 1:
                        st.checkbox(
                            "Peer summary (Mean / Median + max/min highlight)",
                            key="compare_peer_summary",
                            help=(
                                "Add Mean and Median columns across the picked peers and "
                                "highlight each row's largest (green) and smallest "
                                "(burgundy) value — the classic comp-table summary."
                            ),
                        )
    else:
        # ---- Years to display (Aggregate view) ----
        # Mirrors the single_company.py year multiselect: build the union of
        # years across the picked companies, let the user narrow it, and filter
        # BEFORE the aggregate / contribution / CAGR are computed so every
        # downstream table and chart recomputes off the selection. Keyed by the
        # picked-company set so changing the selection resets to "all years"
        # rather than carrying a stale pick. Shares ``compare_year_options`` with
        # the side-by-side picker so the two modes offer the same year set.
        _agg_all_years = compare_year_options(year_sets)
        if _agg_all_years:
            _years_key = safe_key("compare_agg_years", ",".join(sorted(picked_idcodes)))
            _agg_state = st.session_state.get(_years_key)
            _n_agg = len(_agg_state) if _agg_state else len(_agg_all_years)
            with _tc[0]:
                with st.popover(
                    f":material/date_range: Years · {_n_agg} of {len(_agg_all_years)}",
                    use_container_width=True,
                ):
                    _picked_years = st.multiselect(
                        "Years to display",
                        options=list(reversed(_agg_all_years)),
                        default=list(_agg_all_years),
                        key=_years_key,
                        label_visibility="collapsed",
                        help=(
                            "Pick which fiscal years feed the aggregate chart, the "
                            "aggregate-by-year table, and the per-company matrix. "
                            "Empty = all years."
                        ),
                    )
            agg_selected_years = (
                sorted(_picked_years) if _picked_years else list(_agg_all_years)
            )

    with _tc[2]:
        _ifrs_active = bool(st.session_state.get("ifrs_on_toggle", False))
        with st.popover(
            ":material/tune: IFRS 16" + ("  ·  on" if _ifrs_active else ""),
            use_container_width=True,
        ):
            ifrs_on, assumed_term, interest_rate = render_ifrs_controls()

    # ---- Metric columns picker (feeds the Aggregate view) ----
    # Choose which metrics appear in the aggregate-by-year table (money columns
    # summed; standard margins derived from summed bases) and the per-company
    # contribution matrix. Read before the Aggregate branch so the chosen list
    # is captured by that branch's nested fragment closure.
    with _tc[3]:
        _mp_state = st.session_state.get(safe_key("metric_picker", "compare"))
        with st.popover(
            ":material/view_column: Metrics"
            + (f" · {len(_mp_state)}" if _mp_state else ""),
            use_container_width=True,
        ):
            compare_picker_cols = render_metric_picker(
                ctx.db_path,
                "compare",
                COMPARE_DEFAULT_COLUMNS,
                label="Metrics to display",
                help=(
                    "Choose which metrics appear in the Aggregate view's by-year table "
                    "and per-company contribution matrix."
                ),
            )

    # =========================================================================
    # Branch: Aggregate view
    # =========================================================================
    if view_mode == "Aggregate":
        metrics_df, sorted_all_years = sector_metrics_panel(
            ctx.db_path, tuple(picked_idcodes), ifrs_on, float(assumed_term),
            float(interest_rate),
        )
        if metrics_df.empty:
            st.warning("No data for the selected companies.")
            st.stop()

        # Apply the "Years to display" selection BEFORE anything is aggregated,
        # so the chart, the by-year table, and the per-company matrix all reflect
        # the chosen span.
        if agg_selected_years is not None:
            metrics_df = metrics_df[metrics_df["FVYear"].isin(set(agg_selected_years))]
            if metrics_df.empty:
                st.warning("No data in the selected year range.")
                st.stop()
            sorted_all_years = sorted(set(metrics_df["FVYear"].astype(int)))
        all_years = set(sorted_all_years)

        # Pull any picked metric columns not already in metrics_df from the panel
        # (incl. margin bases so margins can be derived), merged on (IdCode,
        # FVYear). Panel values are non-IFRS-adjusted.
        _wanted_extra = set(compare_picker_cols)
        for _m, _num, _den in DERIVABLE_MARGINS:
            if _m in _wanted_extra:
                _wanted_extra.update({_num, _den})
        _extra_cols = [c for c in _wanted_extra if c not in metrics_df.columns]
        if _extra_cols:
            _extra_panel = panel_columns_for_idcodes(ctx.db_path, picked_idcodes, _extra_cols)
            if not _extra_panel.empty:
                _extra_flat = _extra_panel.reset_index()
                _extra_flat["FVYear"] = _extra_flat["FVYear"].astype(int)
                metrics_df = metrics_df.merge(
                    _extra_flat, on=["IdCode", "FVYear"], how="left"
                )

        # Aggregate by year (sum across companies).
        agg = (
            metrics_df.groupby("FVYear", as_index=False)
            .agg(
                Revenue=("Revenue", "sum"),
                EBITDA=("EBITDA", "sum"),
                NetProfit=("NetProfit", "sum"),
                TotalAssets=("TotalAssets", "sum"),
                CompaniesContributing=("IdCode", "nunique"),
            )
            .sort_values("FVYear")
        )

        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        fig = make_subplots(specs=[[{"secondary_y": False}]])
        # Trace colours come from the brand colourway applied by chart_theme:
        # Revenue=forest bar, EBITDA=brass line, Net Profit=slate-blue line.
        fig.add_trace(go.Bar(
            x=agg["FVYear"], y=agg["Revenue"] / 1000,
            name="Revenue (K GEL)",
            hovertemplate="FY%{x}<br>Revenue: %{y:,.0f}K GEL<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=agg["FVYear"], y=agg["EBITDA"] / 1000,
            name="EBITDA (K GEL)", mode="lines+markers",
            line=dict(width=2),
            hovertemplate="FY%{x}<br>EBITDA: %{y:,.0f}K GEL<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=agg["FVYear"], y=agg["NetProfit"] / 1000,
            name="Net Profit (K GEL)", mode="lines+markers",
            line=dict(width=2, dash="dot"),
            hovertemplate="FY%{x}<br>Net Profit: %{y:,.0f}K GEL<extra></extra>",
        ))
        fig.update_layout(
            height=420,
            margin=dict(l=40, r=40, t=30, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
        )
        fig.update_xaxes(title_text="Year", tickmode="array", tickvals=sorted(all_years))
        fig.update_yaxes(title_text="GEL (thousands)")
        from lib.theme import chart_theme, polish_bar_line_chart
        chart_theme(fig)
        polish_bar_line_chart(fig)
        st.plotly_chart(fig, use_container_width=True, key="compare_agg_chart")

        # Aggregate-by-year table (transposed: years are columns). Honors the
        # metric picker: money columns are summed; the three standard margins
        # are derived from summed bases. (Non-derivable percent/ratio metrics
        # live in the per-company matrix below.)
        st.markdown("##### Aggregate by year")
        _sum_money_cols: list[str] = []
        for _c in list(BASE_AGG_COLUMNS) + list(compare_picker_cols):
            if (
                is_money_column(_c)
                and _c in metrics_df.columns
                and _c not in _sum_money_cols
            ):
                _sum_money_cols.append(_c)
        _agg_kwargs = {c: (c, "sum") for c in _sum_money_cols}
        for _m, _num, _den in DERIVABLE_MARGINS:
            if _m in compare_picker_cols:
                for _base in (_num, _den):
                    if _base in metrics_df.columns and _base not in _agg_kwargs:
                        _agg_kwargs[_base] = (_base, "sum")
        _agg_kwargs["CompaniesContributing"] = ("IdCode", "nunique")
        agg_full = (
            metrics_df.groupby("FVYear", as_index=False)
            .agg(**_agg_kwargs)
            .sort_values("FVYear")
        )

        agg_display = pd.DataFrame()
        agg_display["FVYear"] = agg_full["FVYear"].astype(int).astype(str)
        for _c in _sum_money_cols:
            agg_display[f"{label_for(_c)} (K)"] = agg_full[_c].map(fmt_k_gel)
        for _m, _num, _den in DERIVABLE_MARGINS:
            if (
                _m in compare_picker_cols
                and _num in agg_full.columns
                and _den in agg_full.columns
            ):
                denom = agg_full[_den].replace(0, pd.NA)
                agg_display[f"{label_for(_m)} (%)"] = (agg_full[_num] / denom).map(fmt_pct)
        agg_display["n"] = agg_full["CompaniesContributing"].astype(str)
        agg_pivot = (
            agg_display.set_index("FVYear").T.reset_index()
            .rename(columns={"index": "Metric"})
        )
        st.dataframe(agg_pivot, use_container_width=True, hide_index=True)

        # Per-company × year matrix + two-step export.
        # Sprint 6: nested @st.fragment so the metric radio and the
        # Prepare-export button rerun ONLY this block (pure reshape of the
        # already-built metrics_df) instead of the whole script. metrics_df
        # and picked_idcodes are captured by closure — the fragment is defined
        # after both are assigned and is redefined on every full rerun, so the
        # captures can never go stale. The Prepare button just stashes a frame
        # in session_state (its implicit rerun is fragment-scoped); download
        # buttons stream bytes. Nothing here navigates or touches the sidebar,
        # so no st.rerun(scope="app") is needed.
        # Matrix metric options are driven by the picker selection (display
        # label -> panel column), restricted to columns present in metrics_df.
        # Built outside the fragment so it's captured by closure; falls back to
        # the four base metrics if the picker can't be served here.
        agg_matrix_options: dict[str, str] = {}
        for _c in compare_picker_cols:
            if _c in metrics_df.columns:
                agg_matrix_options[label_for(_c)] = _c
        if not agg_matrix_options:
            agg_matrix_options = {
                "Revenue": "Revenue", "EBITDA": "EBITDA",
                "Net Profit": "NetProfit", "Total Assets": "TotalAssets",
            }

        @st.fragment
        def _agg_matrix_and_export() -> None:
            st.markdown("##### Per-company contribution by year")
            option_labels = list(agg_matrix_options.keys())
            chosen_label = st.radio(
                "Metric", option_labels, horizontal=True,
                key="compare_agg_metric", label_visibility="collapsed",
            )
            if chosen_label not in agg_matrix_options:
                chosen_label = option_labels[0]
            chosen_col = agg_matrix_options[chosen_label]
            # Margins/ratios are per-company values — average duplicates instead
            # of summing (one row per company per year, so a no-op in practice).
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
            for col in per_co_display.columns:
                if col not in ("IdCode", "Company"):
                    per_co_display[col] = per_co_display[col].map(
                        lambda v: format_metric_value(v, chosen_col)
                    )
            st.dataframe(per_co_display, use_container_width=True, hide_index=True)

            st.markdown("---")
            # Two-step export to avoid eager xlsx generation on every rerun.
            if st.button(":material/download: Prepare export (XLSX / CSV)", key="compare_agg_export_prep"):
                st.session_state["compare_agg_export_ready_for"] = tuple(picked_idcodes)
                st.session_state["compare_agg_export_per_co_df"] = per_co_display.copy()
                st.session_state["compare_agg_export_metric_label"] = chosen_label

            ready_for = st.session_state.get("compare_agg_export_ready_for")
            if ready_for == tuple(picked_idcodes):
                ready_df = st.session_state["compare_agg_export_per_co_df"]
                ready_metric = st.session_state.get("compare_agg_export_metric_label", "Revenue")
                from lib.excel_export import dataframe_to_xlsx as _df_to_xlsx, dataframe_to_csv as _df_to_csv
                col_x, col_c = st.columns(2)
                with col_x:
                    st.download_button(
                        "Download XLSX",
                        data=_df_to_xlsx(
                            ready_df, title=f"Comp Set — Per-company {ready_metric} by year",
                            subtitle=f"{len(picked_idcodes)} companies  ·  values in GEL thousands",
                            sheet_name="Comp Set",
                            label_col="Company",
                            numeric_format=None,
                        ),
                        file_name=f"compset_{len(picked_idcodes)}cos.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="compare_agg_xlsx",
                    )
                with col_c:
                    st.download_button(
                        "Download CSV",
                        data=_df_to_csv(ready_df),
                        file_name=f"compset_{len(picked_idcodes)}cos.csv",
                        mime="text/csv",
                        key="compare_agg_csv",
                    )
            elif ready_for:
                st.caption("_Selection changed — click Prepare again to regenerate the export._")

        _agg_matrix_and_export()

        # st.stop() must stay OUTSIDE the fragment: it ends the Aggregate
        # branch on full runs so we don't fall through to Side-by-side. (Inside
        # the fragment it would also abort fragment-only reruns mid-flight.)
        st.stop()  # Aggregate branch ends here; don't fall through to Side-by-side.

    # =========================================================================
    # Branch: Side-by-side view (line-item × company × one year)
    # =========================================================================
    if len(picked_idcodes) < 2:
        st.info(
            "Side-by-side view needs at least **2 companies**. Pick another, "
            "or switch to **Aggregate** above to see a single-company chart."
        )
        st.stop()
    if selected_year is None:
        st.warning("No reporting years available for the selected companies.")
        st.stop()

    common_size = bool(st.session_state.get("compare_common_size", False))
    _years_label = (
        f"FY {selected_years[0]}"
        if len(selected_years) == 1
        else f"FY {selected_years[0]}–{selected_years[-1]} ({len(selected_years)} years)"
    )
    _value_note = (
        "values as % of Revenue (IS) / Total Assets (BS)"
        if common_size
        else "values in GEL thousands"
    )
    st.caption(
        f"{_years_label}  ·  {_value_note}  ·  bold rows are derived totals  ·  "
        f"companies ordered by Revenue (largest first)."
    )
    if year_note:
        st.warning(year_note)
    if coverage_note:
        # Routine with union year options (a lagging filer is common), so this is
        # a quiet caption rather than a warning — it explains the blank cells.
        st.caption(f":material/info: {coverage_note}")

    # Sort picked companies by Revenue (primary/latest selected year), largest
    # first. Keeps column order intuitive — bigger peers on the left, smaller on
    # the right — and stable across reruns regardless of pick order. Falls back
    # to picker order when Revenue isn't available for the chosen year.
    _metrics_for_sort = metrics_table(ctx.db_path)
    def _rev_for(idc: str) -> float:
        key = (idc, selected_year)
        if key in _metrics_for_sort.index:
            v = _metrics_for_sort.at[key, "Revenue"]
            try:
                return float(v) if v == v else 0.0  # NaN-safe
            except (TypeError, ValueError):
                return 0.0
        return 0.0
    picked_idcodes = sorted(picked_idcodes, key=_rev_for, reverse=True)

    # Pre-build sections per company once (across ALL selected years) so all
    # three tabs are fast. Each company's sections carry every selected year's
    # total, so the multi-year table just looks up totals by (label, year).
    is_by_idc: dict[str, list[dict]] = {}
    bs_by_idc: dict[str, list[dict]] = {}
    for idc in picked_idcodes:
        is_by_idc[idc] = adjusted_is_sections_for(ctx.db_path,
            idc, selected_years, ifrs_on, assumed_term, interest_rate
        )
        bs_by_idc[idc] = bs_sections(ctx.db_path, idc, tuple(selected_years))

    short_names = {idc: company_short_name(ctx.companies, idc) for idc in picked_idcodes}

    # Ordered (column_label, idc, year) triples driving every value column.
    col_specs = compare_column_specs(picked_idcodes, selected_years, short_names)

    # Peer-summary columns (Feature 4) — single-year only (a row stat across
    # mixed years would be meaningless). The peer columns are the col_spec
    # labels; Mean / Median are appended after them.
    peer_summary = (
        len(selected_years) == 1
        and bool(st.session_state.get("compare_peer_summary", False))
    )
    _peer_cols = [c for c, _idc, _y in col_specs]
    _SUMMARY_COLS = ("Mean", "Median")

    def _compare_table(
        kind: str,
    ) -> tuple[pd.DataFrame, list[int]]:
        """Build (df, bold_row_indices) for the comparison table.

        kind == "is" or "bs". Rows = section labels. Cols = one per
        (company, year) in ``col_specs``. Only section totals are surfaced in
        Compare mode (no detail rows). In common-size mode every value cell is a
        pre-formatted percent string (% of Revenue for IS / Total Assets for BS,
        per that company and year). When ``peer_summary`` is on (single year),
        Mean and Median columns are appended — computed from the raw proportions
        / amounts and formatted to match the display mode.
        """
        sections_by_idc = is_by_idc if kind == "is" else bs_by_idc
        template = sections_by_idc[picked_idcodes[0]]
        records, bold_rows = build_compare_records(
            template, sections_by_idc, col_specs, kind,
            common_size=common_size, unreported=unreported,
        )
        if peer_summary:
            # Per-row raw numeric peer values (common-size → proportions),
            # independent of the display strings, so Mean/Median stay correct
            # even when the displayed cells are percent strings.
            base_by_idc = {}
            if common_size:
                from lib.ui import common_size_base as _csb
                base_by_idc = {idc: _csb(sections_by_idc[idc], kind) for idc in picked_idcodes}
            for rec in records:
                lookup_label = rec["Line Item"]
                vals = []
                for _col, idc, year in col_specs:
                    if (idc, int(year)) in unreported:
                        continue  # no filing — don't drag Mean/Median toward 0
                    raw = section_total_at(sections_by_idc[idc], lookup_label, year)
                    if common_size:
                        base = base_by_idc.get(idc, {}).get(int(year), 0.0) or 0.0
                        vals.append(raw / base if base else float("nan"))
                    else:
                        vals.append(float(raw))
                stats = summary_stats(vals)
                if common_size:
                    rec["Mean"] = common_size_pct_str(stats["mean"]) if stats["mean"] == stats["mean"] else ""
                    rec["Median"] = common_size_pct_str(stats["median"]) if stats["median"] == stats["median"] else ""
                else:
                    rec["Mean"] = stats["mean"]
                    rec["Median"] = stats["median"]
        df = pd.DataFrame(records)
        return df, bold_rows

    def _style_compare(df: pd.DataFrame, bold_rows: list[int]) -> str:
        """Render the comparison table with the same monospace styling.

        In common-size mode the value cells are already percent strings, so the
        formatter passes strings through unchanged and negatives (parenthesized
        strings) get the burgundy negative color. When peer-summary is on, each
        row's largest peer value is tinted green and the smallest burgundy
        (across the peer columns only, not the Mean/Median columns).
        """
        cols = [c for c in df.columns if c != "Line Item"]
        # Peer columns present in this df (max/min highlight target).
        hi_cols = [c for c in _peer_cols if c in df.columns] if peer_summary else []

        def _fmt_cell(v):
            # Common-size cells are pre-formatted strings — pass through.
            if isinstance(v, str):
                return v
            return fmt_k_gel(v)

        fmt_dict = {c: _fmt_cell for c in cols}
        styler = df.style.format(fmt_dict)

        def _num(v):
            """Coerce a cell (number or percent string) to float for max/min."""
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return None
                neg = s.startswith("(")
                s = s.strip("()%").replace(",", "")
                try:
                    f = float(s)
                except ValueError:
                    return None
                return -f if neg else f
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return f if f == f else None

        def _bold(row):
            if row.name in bold_rows:
                return ["font-weight: 700"] * len(row)
            return [""] * len(row)

        def _neg_color(row):
            out = []
            for col in row.index:
                if col == "Line Item":
                    out.append("")
                    continue
                v = row[col]
                if isinstance(v, str):
                    out.append(f"color:{BURGUNDY};" if v.startswith("(") else "")
                else:
                    try:
                        out.append(f"color:{BURGUNDY};" if float(v) < 0 else "")
                    except (TypeError, ValueError):
                        out.append("")
            return out

        def _hi_lo(row):
            """Tint the row's max peer value green, min burgundy (background)."""
            out = ["" for _ in row.index]
            if not hi_cols:
                return out
            pairs = [(c, _num(row[c])) for c in hi_cols]
            nums = [(c, n) for c, n in pairs if n is not None]
            if len(nums) < 2:
                return out
            cmax = max(nums, key=lambda t: t[1])[0]
            cmin = min(nums, key=lambda t: t[1])[0]
            if cmax == cmin:
                return out  # all equal — nothing to distinguish
            idx = {c: i for i, c in enumerate(row.index)}
            out[idx[cmax]] = "background-color:rgba(40,120,70,0.16);"
            out[idx[cmin]] = "background-color:rgba(123,32,56,0.14);"
            return out

        styler = styler.apply(_bold, axis=1)
        styler = styler.apply(_neg_color, axis=1)
        if hi_cols:
            styler = styler.apply(_hi_lo, axis=1)
        styler = styler.set_properties(subset=cols, **{"text-align": "right"})
        styler = styler.set_properties(subset=["Line Item"], **{"text-align": "left"})
        # Compare mode uses auto layout — N companies × years, widths shouldn't be fixed.
        styler = styler.set_table_styles(shared_table_styles("Line Item", cols, fixed_widths=False))
        styler = styler.hide(axis="index")
        return styler.to_html()

    tab_is, tab_bs, tab_r = st.tabs(["Income Statement", "Balance Sheet", "Ratios"])

    from lib.excel_export import dataframe_to_xlsx as _df_to_xlsx, dataframe_to_csv as _df_to_csv

    # Export framing differs by mode: absolute money exports as numeric K-GEL;
    # common-size cells are already percent strings, so they go out verbatim
    # (no in_thousands scaling, no numeric format).
    _year_tag = (
        f"FY{selected_years[0]}"
        if len(selected_years) == 1
        else f"FY{selected_years[0]}-{selected_years[-1]}"
    )
    _cs_tag = " (common-size)" if common_size else ""
    _xlsx_kwargs = (
        dict(numeric_format=None, in_thousands=False)
        if common_size
        else dict(numeric_format='#,##0;(#,##0);""', in_thousands=True)
    )

    with tab_is:
        if ifrs_on:
            st.info("IFRS 16 reversal applied to Income Statement values.")
        df_is, bold_is = _compare_table("is")
        st.markdown(_style_compare(df_is, bold_is), unsafe_allow_html=True)
        st.markdown("---")
        st.download_button(
            ":material/download: Export Compare — Income Statement (XLSX)",
            data=_df_to_xlsx(
                df_is, title=f"Income Statement Comparison — {_year_tag}{_cs_tag}",
                subtitle=f"{len(picked_idcodes)} companies",
                sheet_name="Compare IS",
                label_col="Line Item",
                **_xlsx_kwargs,
            ),
            file_name=f"compare_IS_{_year_tag}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="cmp_is_xlsx",
        )

    with tab_bs:
        df_bs, bold_bs = _compare_table("bs")
        st.markdown(_style_compare(df_bs, bold_bs), unsafe_allow_html=True)
        st.markdown("---")
        st.download_button(
            ":material/download: Export Compare — Balance Sheet (XLSX)",
            data=_df_to_xlsx(
                df_bs, title=f"Balance Sheet Comparison — {_year_tag}{_cs_tag}",
                subtitle=f"{len(picked_idcodes)} companies",
                sheet_name="Compare BS",
                label_col="Line Item",
                **_xlsx_kwargs,
            ),
            file_name=f"compare_BS_{_year_tag}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="cmp_bs_xlsx",
        )

    with tab_r:
        # Ratios table — already returns pre-formatted strings, so build a wide
        # DataFrame indexed by ratio label with one column per company.
        ratio_dfs: dict[str, pd.DataFrame] = {}
        for idc in picked_idcodes:
            if ifrs_on:
                ratio_dfs[idc] = build_ratios_table(
                    ctx.db_path, idc, [selected_year], is_sections=is_by_idc[idc]
                )
            else:
                ratio_dfs[idc] = ratios(ctx.db_path, idc, (selected_year,))
        # Each ratio_dfs[idc] has columns ['Ratio', selected_year]. Pivot into one
        # column per company keyed off Ratio.
        merged = None
        for idc, df in ratio_dfs.items():
            short = short_names[idc]
            # Year column is the selected year (int)
            sub = df[["Ratio", selected_year]].rename(columns={selected_year: short})
            if merged is None:
                merged = sub
            else:
                merged = merged.merge(sub, on="Ratio", how="outer")
        if merged is None or merged.empty:
            st.info("No ratio data available for the selected companies.")
        else:
            st.dataframe(merged, use_container_width=True, hide_index=True, height=700)
            st.markdown("---")
            col_x, col_c = st.columns(2)
            with col_x:
                st.download_button(
                    ":material/download: Export Compare — Ratios (XLSX)",
                    data=_df_to_xlsx(
                        merged, title=f"Ratios Comparison — FY {selected_year}",
                        subtitle=f"{len(picked_idcodes)} companies",
                        sheet_name="Compare Ratios",
                        label_col="Ratio",
                        numeric_format=None,
                    ),
                    file_name=f"compare_Ratios_FY{selected_year}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="cmp_r_xlsx",
                )
            with col_c:
                st.download_button(
                    ":material/download: Ratios (CSV)",
                    data=_df_to_csv(merged),
                    file_name=f"compare_Ratios_FY{selected_year}.csv",
                    mime="text/csv",
                    key="cmp_r_csv",
                )

    # ---- Peer percentile within sector (Feature 4a) ------------------------
    # metrics_panel holds the full per-year cross-section, so each picked
    # company's standing within ITS OWN sector for a chosen metric is a cheap
    # groupby().rank(pct=True). Shown for the primary (latest selected) year.
    _render_peer_percentile(ctx, picked_idcodes, short_names, selected_year)


def _render_peer_percentile(
    ctx: ViewContext,
    picked_idcodes: list[str],
    short_names: dict[str, str],
    year: int,
) -> None:
    """Show where each picked company ranks within its sector for one metric."""
    from lib.data_loader import get_curated_sector_buckets

    with st.expander(":material/bar_chart: Peer percentile within sector", expanded=False):
        @st.cache_data(show_spinner=False, ttl=3600)
        def _buckets(db_path: str) -> dict:
            return get_curated_sector_buckets(db_path)

        curated = _buckets(ctx.db_path)
        if not curated:
            st.caption(
                "No curated sectors in this database, so a within-sector "
                "percentile can't be computed."
            )
            return

        # idcode -> sector (first bucket it appears in).
        sector_of: dict[str, str] = {}
        for sector, members in curated.items():
            for idc in members:
                sector_of.setdefault(idc, sector)

        # Metric to rank on — the curated picker catalogue, ranked descending
        # (higher = better percentile). Default to EBITDA margin.
        from lib.metric_picker import CURATED_METRICS, label_for as _label_for
        metric_opts = [col for _lbl, col in CURATED_METRICS]
        default_idx = metric_opts.index("EBITDAMargin") if "EBITDAMargin" in metric_opts else 0
        metric_col = st.selectbox(
            "Rank metric",
            options=metric_opts,
            index=default_idx,
            format_func=_label_for,
            key="compare_pctile_metric",
            help=(
                "Percentile rank of each picked company within its own sector "
                f"for FY {year} (1.0 = top of the sector). Uses the full "
                "metrics_panel cross-section."
            ),
        )

        mt = metrics_table(ctx.db_path)
        if mt.empty or metric_col not in mt.columns:
            st.caption("Metric not available in this database's panel.")
            return
        # Cross-section for the primary year, with each company's sector attached.
        panel = mt.reset_index()
        panel = panel[panel["FVYear"] == year].copy()
        if panel.empty:
            st.caption(f"No panel rows for FY {year}.")
            return
        panel["Sector"] = panel["IdCode"].map(sector_of)
        panel = panel[panel["Sector"].notna()]
        if panel.empty:
            st.caption("None of the universe is sector-classified for this year.")
            return
        panel["_pctile"] = percentile_within_group(panel, metric_col, "Sector")
        by_idc = panel.set_index("IdCode")

        records: list[dict] = []
        for idc in picked_idcodes:
            if idc not in by_idc.index:
                records.append({
                    "Company": short_names.get(idc, idc),
                    "Sector": sector_of.get(idc, "(unclassified)"),
                    "Value": "",
                    "Percentile": "(no FY data)",
                })
                continue
            row = by_idc.loc[idc]
            records.append({
                "Company": short_names.get(idc, idc),
                "Sector": row.get("Sector", "(unclassified)"),
                "Value": format_metric_value(row.get(metric_col), metric_col),
                "Percentile": fmt_percentile(row.get("_pctile")),
            })
        st.dataframe(
            pd.DataFrame(records, columns=["Company", "Sector", "Value", "Percentile"]),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Percentile is within each company's own sector for the universe's "
            f"FY {year} cross-section (1st–100th; higher = larger value)."
        )


# ===========================================================================
# Sector-vs-sector (and sub-sector) comparison
# ===========================================================================

# Default metrics shown when the sector-compare surface first opens. A spread
# across size / margin / return / growth so the table is immediately useful.
_SECTOR_COMPARE_DEFAULT_COLS: list[str] = [
    "Revenue", "EBITDA", "NetProfit", "TotalAssets",
    "EBITDAMargin", "NetMargin", "ROE", "ROIC",
    "Revenue_YoY",
]

# Full curated metric set offered in the picker (mirrors metrics_panel's
# curated columns, in a sensible display order). Growth/CAGR variants are
# generated below.
_SECTOR_COMPARE_BASE_COLS: list[str] = [
    "Revenue", "GrossProfit", "EBITDA", "NetProfit",
    "TotalAssets", "TotalEquity", "TotalCash", "TotalDebt", "NetDebt",
    "GrossMargin", "EBITDAMargin", "NetMargin",
    "ROE", "ROA", "ROIC", "NetDebtToEBITDA", "AssetTurnover",
]
_SECTOR_COMPARE_GROWTH_COLS: list[str] = [
    f"{base}_{suf}"
    for base in ("Revenue", "EBITDA", "NetProfit", "GrossProfit", "TotalAssets")
    for suf in ("YoY", "2yrCAGR", "3yrCAGR")
]
_SECTOR_COMPARE_ALL_COLS: list[str] = _SECTOR_COMPARE_BASE_COLS + _SECTOR_COMPARE_GROWTH_COLS


def _render_sector_compare(ctx: ViewContext) -> None:
    """Aggregate-vs-aggregate comparison across sectors / sub-sectors.

    Mirrors the Company Compare layout but the columns are sectors (or
    sub-sectors). Each group's per-company × per-year ``metrics_panel`` slice
    is aggregated by :mod:`lib.sector_compare` (sum money, derive margins from
    summed bases, mean ratios/returns/growth) and shown metrics × group for a
    chosen year, plus a small per-metric bar chart.
    """
    import pandas as pd

    from lib import sector_compare as sc
    from lib import sectors as _sectors
    from lib.cache import metrics_table
    from lib.data_loader import get_curated_sector_buckets, get_sub_sectors
    from lib.ui import safe_key

    UNCLASSIFIED = "(unclassified)"

    @st.cache_data(show_spinner=False, ttl=3600)
    def _curated(db_path: str) -> dict:
        return get_curated_sector_buckets(db_path)

    @st.cache_data(show_spinner=False, ttl=3600)
    def _subs(db_path: str) -> dict:
        return get_sub_sectors(db_path)

    curated = _curated(ctx.db_path)
    sub_sector_map = _subs(ctx.db_path)

    if not curated:
        st.title("Compare sectors")
        st.warning(
            "No curated sectors found — the database may pre-date the Sector "
            "column migration. Run `scripts/enrich_company_descriptions.py` to "
            "seed it."
        )
        st.stop()

    # ---- Header + on-page controls ------------------------------------------
    # All sector-compare filters live ON the page (fd_toolbar popovers, same
    # treatment as Sector View): pick 2+ sectors, optionally drill to
    # sub-sectors, choose metrics. Chip labels are pre-widget session READS
    # (Sprint-26-safe).
    st.title("Compare sectors")
    st.caption(
        "Aggregate-vs-aggregate. Money metrics are **summed** across each "
        "group's companies; **margins** are recomputed from summed bases; "
        "**ratios, returns and growth** are **averaged** (NaN-skipping)."
    )

    _toolbar = st.container(key="fd_toolbar")
    _tc = _toolbar.columns([1.5, 1.9, 1.5, 4.1], vertical_alignment="center")

    sector_names = list(curated.keys())
    _pick_state = st.session_state.get("sectorcompare_pick")
    _n_secs = len(_pick_state) if _pick_state else 0
    with _tc[0]:
        with st.popover(
            f":material/category: Sectors · {_n_secs}",
            use_container_width=True,
        ):
            chosen_sectors = st.multiselect(
                "Pick sectors",
                sector_names,
                default=[],
                format_func=lambda s: f"{s}  ({len(curated[s])})",
                key="sectorcompare_pick",
                label_visibility="collapsed",
                help="Pick two or more sectors to compare their aggregate metrics.",
            )

    # Optional sub-sector drill-down. When ON, the comparison ENTITIES become
    # the sub-sectors pooled across the chosen sectors (so you can e.g. compare
    # "In-patient services" vs "Dental clinics" within Healthcare). When OFF,
    # entities are the sectors themselves. The sub-sector multiselect lives in
    # the same popover as the toggle and only renders while drilling (same
    # skip-a-run behaviour as the old sidebar layout).
    _drill_on = bool(st.session_state.get("sectorcompare_drill", False))
    _subs_key = safe_key("sectorcompare_subs", ",".join(sorted(chosen_sectors)))
    _subs_state = st.session_state.get(_subs_key)
    _n_subs = len(_subs_state) if _subs_state else 0
    chosen_subs: list[str] = []
    with _tc[1]:
        with st.popover(
            ":material/account_tree: Sub-sectors"
            + (f" · {_n_subs}" if _drill_on else "  ·  off"),
            use_container_width=True,
        ):
            drill = st.toggle(
                "Compare sub-sectors instead",
                value=False,
                key="sectorcompare_drill",
                help=(
                    "Off: each picked sector is one column. On: each sub-sector within "
                    "the picked sectors becomes its own column."
                ),
            )
            if drill:
                pooled = _sectors.union_idcodes(curated, chosen_sectors)
                sub_counts = _sectors.subsector_counts(pooled, sub_sector_map, UNCLASSIFIED)
                available_subs = sorted(sub_counts.keys(), key=lambda s: (-sub_counts[s], s))
                chosen_subs = st.multiselect(
                    "Pick sub-sectors",
                    options=available_subs,
                    default=[],
                    format_func=lambda s: f"{s}  ({sub_counts[s]})",
                    key=_subs_key,
                    help="Each picked sub-sector becomes a column in the comparison.",
                )

    # Build the entity → idcodes mapping.
    groups: dict[str, list[str]] = {}
    if not drill:
        for s in chosen_sectors:
            groups[s] = list(curated.get(s, []))
    else:
        for sub in chosen_subs:
            groups[sub] = _sectors.filter_by_subsectors(
                pooled, sub_sector_map, [sub], UNCLASSIFIED
            )

    # ---- Metric picker ------------------------------------------------------
    _met_state = st.session_state.get("sectorcompare_metrics")
    _n_mets = len(_met_state) if _met_state is not None else len(_SECTOR_COMPARE_DEFAULT_COLS)
    with _tc[2]:
        with st.popover(
            f":material/view_column: Metrics · {_n_mets}",
            use_container_width=True,
        ):
            chosen_metrics = st.multiselect(
                "Metrics",
                options=_SECTOR_COMPARE_ALL_COLS,
                default=_SECTOR_COMPARE_DEFAULT_COLS,
                format_func=sc.label_for,
                key="sectorcompare_metrics",
                label_visibility="collapsed",
                help="Which aggregate metrics to show. Money is summed; margins are "
                     "derived from summed bases; ratios/returns/growth are averaged.",
            )

    # ---- Empty states -------------------------------------------------------
    if len([g for g in groups if groups[g]]) < 2:
        if not chosen_sectors:
            st.info(
                "Pick **two or more sectors** with the **Sectors** control "
                "above to compare them."
            )
        elif drill:
            st.info(
                "Pick at least **two sub-sectors** (the **Sub-sectors** control "
                "above) to compare them, or turn off **Compare sub-sectors** to "
                "compare whole sectors."
            )
        else:
            st.info("Pick **at least two** sectors with companies to compare.")
        st.stop()
    if not chosen_metrics:
        st.info("Pick at least one **metric** with the **Metrics** control above.")
        st.stop()

    # ---- Aggregate each group ----------------------------------------------
    # Pull the full panel once (cached), slice per group. Aggregation is done
    # by the pure lib.sector_compare rules so numbers match Sector View.
    mt = metrics_table(ctx.db_path)
    if mt.empty:
        st.warning("No metrics available — the metrics_panel table is empty.")
        st.stop()
    panel = mt.reset_index()  # IdCode, FVYear back as columns

    per_group_agg: dict[str, pd.DataFrame] = {}
    group_years: set[int] = set()
    _group_exclusions: list[dict] = []
    for name, idcodes in groups.items():
        if not idcodes:
            continue
        slice_df = panel[panel["IdCode"].isin(idcodes)]
        # Consolidation de-dup (year-aware): drop subsidiary-year rows already
        # consolidated by a parent pooled in the SAME group, so a sector's sum
        # doesn't double-count parent + subsidiary. Matches Sector View.
        _group_exclusions.extend(
            excluded_pairs(
                zip(slice_df["IdCode"].tolist(), slice_df["FVYear"].tolist())
            )
        )
        slice_df = dedup_panel_df(slice_df)
        agg = sc.aggregate_group_by_year(slice_df, chosen_metrics)
        if agg.empty:
            continue
        per_group_agg[name] = agg
        group_years.update(int(y) for y in agg["FVYear"].tolist())

    if len(per_group_agg) < 2:
        st.warning("Fewer than two groups have data — broaden the selection.")
        st.stop()

    all_years = sorted(group_years)
    selected_year = st.selectbox(
        "Fiscal year",
        options=all_years,
        index=len(all_years) - 1,
        key="sectorcompare_year",
    )

    group_names = list(per_group_agg.keys())
    st.caption(
        f"FY {selected_year}  ·  {len(group_names)} groups  ·  money in GEL "
        f"thousands  ·  *n* = companies contributing that year."
    )
    if _group_exclusions:
        _subs = {e["subsidiary"] for e in _group_exclusions}
        _names = ", ".join(
            sorted(company_short_name(ctx.companies, s) for s in _subs)
        )
        st.caption(
            ":material/account_tree: Consolidation de-dup — excluded from the "
            f"group sums to avoid double-counting: {_names} (each already "
            "consolidated by a parent in the same group)."
        )

    # Standing disclaimer — de-dup only covers the curated map, so un-mapped
    # parent/subsidiary groups may still be summed more than once. (Matches
    # Sector View.)
    st.caption(
        ":material/info: Group sums include every filer selected. Known "
        "parent/subsidiary groups that file separately are de-duplicated; groups "
        "not yet curated may still be counted more than once."
    )

    # ---- Build the metrics × group table ------------------------------------
    # One row per metric (+ an "n" row), one column per group, for the chosen
    # year. Values pre-formatted per metric kind.
    year_values: dict[str, dict[str, float]] = {}
    for name, agg in per_group_agg.items():
        row = agg[agg["FVYear"] == selected_year]
        year_values[name] = (
            {c: row.iloc[0][c] for c in (["n"] + chosen_metrics)}
            if not row.empty else {}
        )

    records: list[dict] = []
    # Header "n companies" row first.
    n_rec: dict = {"Metric": "n (companies)"}
    for name in group_names:
        v = year_values[name].get("n")
        n_rec[name] = "" if v is None or pd.isna(v) else str(int(v))
    records.append(n_rec)
    for col in chosen_metrics:
        rec: dict = {"Metric": sc.label_for(col)}
        for name in group_names:
            rec[name] = sc.format_metric_value(col, year_values[name].get(col))
        records.append(rec)
    table_df = pd.DataFrame(records, columns=["Metric"] + group_names)
    st.dataframe(table_df, use_container_width=True, hide_index=True)

    # ---- Per-metric bar chart ----------------------------------------------
    st.markdown("##### Compare one metric across groups")
    chart_col = st.selectbox(
        "Metric to chart",
        options=chosen_metrics,
        format_func=sc.label_for,
        key="sectorcompare_chart_metric",
    )
    import plotly.graph_objects as go

    bar_x = group_names
    bar_y = [year_values[name].get(chart_col) for name in group_names]
    # Scale money to thousands for readability; percent to %.
    if sc.is_money_column(chart_col):
        bar_y = [(v / 1000.0) if (v is not None and not pd.isna(v)) else None for v in bar_y]
        y_title = "GEL (thousands)"
    elif sc.is_percent_column(chart_col):
        bar_y = [(v * 100.0) if (v is not None and not pd.isna(v)) else None for v in bar_y]
        y_title = "%"
    else:
        y_title = "x (ratio)"
    fig = go.Figure(go.Bar(x=bar_x, y=bar_y))  # forest from the brand colourway
    fig.update_layout(
        height=360,
        margin=dict(l=40, r=40, t=30, b=40),
        title=f"{sc.label_for(chart_col)} — FY {selected_year}",
    )
    fig.update_yaxes(title_text=y_title)
    from lib.theme import chart_theme, polish_bar_line_chart
    chart_theme(fig)
    polish_bar_line_chart(fig)
    st.plotly_chart(fig, use_container_width=True, key="sectorcompare_chart")

    # ---- Export -------------------------------------------------------------
    st.markdown("---")
    from lib.excel_export import dataframe_to_csv as _df_to_csv
    st.download_button(
        ":material/download: Download comparison (CSV)",
        data=_df_to_csv(table_df),
        file_name=f"sector_compare_FY{selected_year}.csv",
        mime="text/csv",
        key="sectorcompare_csv",
    )
