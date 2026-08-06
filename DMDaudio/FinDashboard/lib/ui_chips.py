"""Company-picker chips + modal dialogs (extracted from app.py in Sprint 4.4).

Holds the interactive selection widgets that aren't tied to a single mode:

* ``company_typeahead`` — the sidebar one-input company picker with chips, used
  by Compare (and reusable elsewhere).
* ``global_search_dialog`` — the Cmd-K style "Jump to…" modal.
* ``person_dialog`` — the person-portfolio modal opened from the Ownership panel.

Following the Sprint 4.3 convention, these take their data dependencies
(``db_path``, the company option lists) as explicit arguments rather than
reaching for app.py module globals — so the module is import-safe and testable
in isolation.
"""
from __future__ import annotations

import streamlit as st

from lib.cache import (
    description_search_rows,
    latest_metrics_for_idcodes,
    options_sorted_by_revenue_cached,
)
from lib.format import fmt_k_gel
from lib.ui import safe_key


def company_typeahead(
    db_path: str,
    key_prefix: str,
    label: str,
    placeholder: str = "Search by name or IdCode…",
    container=None,
    **_kwargs,
) -> list[str]:
    """One-input company picker: selectbox + explicit Add button, chips below.

    The picked list lives in ``st.session_state[f"{key_prefix}_picker"]`` as
    a list of label strings (`"{IdCode} — {Name}"`). Saved-sectors and bulk
    import still write to this same key.

    Renders into ``container`` (any Streamlit container — a popover, column,
    or ``st.sidebar``); defaults to ``st.sidebar`` for back-compat. All widget
    keys are independent of the container, so moving the picker on-page keeps
    deep links / saved sets working unchanged.

    Uses an explicit ``Add`` button rather than an ``on_change`` callback —
    the callback pattern that mutated the widget's own value caused intermittent
    frontend errors ("Bad message format / SessionInfo not initialized").
    """
    target = container if container is not None else st.sidebar

    state_key = f"{key_prefix}_picker"
    if state_key not in st.session_state:
        st.session_state[state_key] = []

    sorted_options = options_sorted_by_revenue_cached(db_path)
    add_key = f"{key_prefix}_add_box"

    pick = target.selectbox(
        label,
        options=sorted_options,
        index=None,
        placeholder=placeholder,
        key=add_key,
        help=(
            "Type any part of the name (e.g. 'თეგეტა') or the IdCode "
            "(e.g. '2021772'). Suggestions sorted by latest Revenue. "
            "Names are Georgian — for English brand names (e.g. 'Tegeta') "
            "use the global search (the '/' shortcut or the top-bar pill)."
        ),
    )
    # An "Add" button is more reliable than an on_change callback that mutates
    # the widget's own state.
    if target.button(
        ":material/add: Add",
        key=f"{key_prefix}_add_btn",
        disabled=not pick,
        use_container_width=True,
    ):
        existing = list(st.session_state[state_key])
        if pick and pick not in existing:
            existing.append(pick)
            st.session_state[state_key] = existing
        st.rerun()

    selected = list(st.session_state[state_key])
    if selected:
        target.caption(f"**Selected ({len(selected)}):**")
        for lbl in selected:
            col_n, col_x = target.columns([6, 1])
            short = lbl if len(lbl) <= 32 else (lbl[:30] + "…")
            with col_n:
                st.markdown(
                    f"<div style='padding:2px 4px;font-size:13px'>{short}</div>",
                    unsafe_allow_html=True,
                )
            with col_x:
                if st.button(
                    "×",
                    key=safe_key(f"{key_prefix}_rm", lbl),
                    help="Remove",
                ):
                    st.session_state[state_key] = [
                        x for x in st.session_state[state_key] if x != lbl
                    ]
                    st.rerun()
        if target.button("Clear all", key=f"{key_prefix}_clear_all"):
            st.session_state[state_key] = []
            st.rerun()

    return list(st.session_state[state_key])


# ---------------------------------------------------------------------------
# Phase F: global search dialog (Cmd-K style). Opened by the top-bar search pill
# or the "/" / ⌘-K shortcut. Filters companies, the ownership register's people,
# and saved comp sets; clicking a result navigates (or opens the person dialog)
# and closes the modal.
# ---------------------------------------------------------------------------
def _description_matches(
    ql: str,
    desc_rows: list[tuple[str, str, str]],
    exclude_idcodes: set[str],
    idcode_to_label: dict[str, str],
    limit: int = 5,
) -> list[tuple[str, str, int]]:
    """Second-pass search: substring-match ``ql`` against the enrichment
    descriptions, skipping companies already surfaced by the direct label
    match. Returns ``(IdCode, Description, match_pos)`` tuples in the order
    of ``desc_rows`` (revenue desc). Pure — unit-testable without Streamlit.

    Single-character queries are ignored: one English letter matches nearly
    every blurb, which would bury the sector results under noise.
    """
    hits: list[tuple[str, str, int]] = []
    if len(ql) < 2:
        return hits
    for idc, desc, desc_l in desc_rows:
        if len(hits) >= limit:
            break
        if idc in exclude_idcodes or idc not in idcode_to_label:
            continue
        pos = desc_l.find(ql)
        if pos >= 0:
            hits.append((idc, desc, pos))
    return hits


def _desc_snippet(desc: str, pos: int, qlen: int, radius: int = 40) -> str:
    """The blurb fragment around the match, ellipsized on both sides."""
    start = max(0, pos - radius)
    end = pos + qlen + radius
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(desc) else ""
    return f"{prefix}{desc[start:end].strip()}{suffix}"


@st.dialog("Jump to a company, person or sector")
def global_search_dialog(
    options: list[str],
    labels_to_idcode: dict[str, str],
    idcode_to_label: dict[str, str],
    db_path: str | None = None,
):
    q = st.text_input(
        "Search",
        key="global_search_query",
        placeholder="Company name (Georgian or English), IdCode, or an owner…",
        label_visibility="collapsed",
    )
    ql = (q or "").strip().lower()

    def _go_company(label: str):
        st.session_state["mode"] = "Single Company"
        st.session_state["_pending_single_pick"] = label
        st.query_params["mode"] = "single"
        st.query_params["id"] = labels_to_idcode[label]
        st.rerun()

    if ql:
        matches = [lbl for lbl in options if ql in lbl.lower()][:8]
        if matches:
            st.caption("COMPANIES")
            for lbl in matches:
                if st.button(lbl, key=safe_key("gs_co", lbl), use_container_width=True):
                    _go_company(lbl)
        # Second pass — company names are Georgian legal names, so English
        # queries ("Tegeta") only hit the plain-English enrichment blurbs.
        # Same approach as mcp/tools.py::search_companies: description-only
        # hits rank *after* direct name/IdCode hits, largest-revenue first.
        # The snippet shows why it matched — a blurb may merely *mention* the
        # query (e.g. "bank of georgia" also surfaces competitors' blurbs).
        desc_hits: list[tuple[str, str, int]] = []
        if db_path:
            _direct = {labels_to_idcode.get(lbl, "") for lbl in matches}
            desc_hits = _description_matches(
                ql, description_search_rows(db_path), _direct, idcode_to_label
            )
        if desc_hits:
            st.caption("MATCHED IN DESCRIPTION")
            for _idc, _desc, _pos in desc_hits:
                _lbl = idcode_to_label[_idc]
                if st.button(_lbl, key=safe_key("gs_desc", _lbl), use_container_width=True):
                    _go_company(_lbl)
                st.caption(_desc_snippet(_desc, _pos, len(ql)))
        # People — the ownership register (companyinfo.ge), searched by holder
        # name or personal ID. The top-bar pill has promised "people" since it
        # was written; this is the group that keeps the promise.
        #
        # Gated on the two-character minimum people_search itself enforces:
        # building the person index inverts ~9k registry payloads, and a
        # one-character query would pay that to be handed [] back.
        #
        # That build is ~20s cold (dominated by summarize_affiliations) and
        # st.cache_resource is process-wide, so exactly one searcher per Space
        # process waits and everyone after is instant. It still has to SAY so:
        # an unexplained 20s freeze on the most-used surface in the app reads as
        # a broken site, which is how the 2026-07-15 companyinfo stall was
        # experienced. The spinner is a no-op once the index is warm.
        people_hits: list[dict] = []
        if db_path and len(ql) >= 2:
            from lib.cache import person_index as _gs_person_index
            from lib.people import NO_GE_ID_BADGE, people_search as _gs_people_search
            with st.spinner("Indexing the ownership register (first search only)…"):
                _index = _gs_person_index(db_path)
            people_hits = _gs_people_search(_index, ql, limit=5)
        if people_hits:
            st.caption("PEOPLE")
            for _p in people_hits:
                # The dialog closes on rerun; app.py pops _open_person on the
                # next run and opens the (DB-backed, instant) person dialog.
                if st.button(
                    f":material/person: {_p['name']}",
                    key=safe_key("gs_person", str(_p["person_id"])),
                    use_container_width=True,
                ):
                    st.session_state["_open_person"] = _p["person_id"]
                    st.rerun()
                _bits = [f"{_p['owned_count']} owned of {_p['company_count']}"]
                if not _p["is_natural_person"]:
                    _bits.append(NO_GE_ID_BADGE)
                if _p["is_individual_entrepreneur"]:
                    _bits.append("individual entrepreneur")
                st.caption("  ·  ".join(_bits))
        # Saved comp sets
        from lib.sector_store import load_sectors as _gs_load_sectors
        _secs = _gs_load_sectors()
        sec_matches = [n for n in sorted(_secs) if ql in n.lower()][:5]
        if sec_matches:
            st.caption("SAVED COMP SETS")
            for _n in sec_matches:
                if st.button(f":material/folder_open: {_n}", key=safe_key("gs_sec", _n), use_container_width=True):
                    _codes = _secs[_n]
                    st.session_state["compare_picker"] = [
                        idcode_to_label[c] for c in _codes if c in idcode_to_label
                    ]
                    st.session_state["compare_loaded_sector"] = _n
                    st.session_state["mode"] = "Compare"
                    st.query_params["mode"] = "compare"
                    st.rerun()
        if not matches and not desc_hits and not people_hits and not sec_matches:
            st.caption("No matches.")
    else:
        # Empty query → show recently viewed as quick links.
        _recent = st.session_state.get("recent_companies", [])
        if _recent:
            st.caption("RECENTLY VIEWED")
            for _idc in _recent:
                _lbl = idcode_to_label.get(_idc, _idc)
                if st.button(_lbl, key=safe_key("gs_recent", _idc), use_container_width=True):
                    _go_company(_lbl)
        else:
            st.caption(
                "Start typing to search 9,000+ companies — Georgian or English "
                "(e.g. 'Tegeta') — or an owner from the ownership register."
            )


# ---------------------------------------------------------------------------
# Person portfolio dialog: opened by clicking a name in the Ownership panel.
# Shows share-weighted attributable financials + a company list with open
# actions. Set st.session_state["_open_person"] = personId to trigger.
# ---------------------------------------------------------------------------
@st.dialog("Person portfolio", width="large")
def person_dialog(person_id, db_path: str, idcode_to_label: dict[str, str]):
    import plotly.graph_objects as _go
    from lib.companyinfo import (
        companyinfo_url as _ci_url,
        fetch_person as _fetch_person,
        portfolio_aggregate as _portfolio_agg,
        summarize_person_companies as _summ_person,
    )

    # DB first. `company_ownership` already holds the whole register, so the
    # portfolio is a dict lookup against the memoized person index — instant,
    # offline, and immune to companyinfo.ge's ~2 req/s rate limit. Only a person
    # the index doesn't cover (a company scraped as 'notfound', or a registry
    # update newer than the last scrape) needs the live round-trip.
    from lib.cache import (
        latest_portfolio_metrics,
        person_index,
        portfolio_metrics_for,
    )
    from lib.people import (
        VINTAGE_ACTIVE_KEY as _VINTAGE_KEY,
        active_cutoff_year as _active_cutoff,
        person_portfolio as _person_portfolio,
    )

    # Honour the Owners page's "Recent filers only" switch so a clicked row and the
    # portfolio it opens are computed on the SAME rule. Defaults to True for the
    # entry points that never set it (company Ownership panel, global search),
    # matching the Owners page default — see lib/people.filter_latest_by_year.
    _cutoff = _active_cutoff(latest_portfolio_metrics(db_path))
    _min_year = _cutoff if st.session_state.get(_VINTAGE_KEY, True) else None

    portfolio = _person_portfolio(
        person_index(db_path), portfolio_metrics_for(db_path, _min_year), person_id
    )

    if portfolio is not None:
        display_name = portfolio["name"] or "Unknown person"
        id_number = portfolio["id_number"]
        nationality = None
        companies = portfolio["companies"]
        truncated = False
    else:
        with st.spinner("Loading portfolio…"):
            pdetail = _fetch_person(person_id)
            if not pdetail:
                st.error(
                    "Couldn't load this person's profile — they're not in the "
                    "precomputed register and companyinfo.ge is unavailable."
                )
                return
            summary = _summ_person(pdetail, person_id)

        person = pdetail.get("person") or {}
        display_name = person.get("name") or "Unknown person"
        id_number = person.get("idNumber")
        nationality = person.get("nationality")
        companies = summary["companies"]
        truncated = summary["truncated"]

        # DB join: attach latest metrics; "in DB" == present in the metrics table.
        idcodes = tuple(c["idcode"] for c in companies if c.get("idcode"))
        metrics_by_id = latest_metrics_for_idcodes(db_path, idcodes)
        for c in companies:
            c["in_db"] = c.get("idcode") in metrics_by_id
            c["metrics"] = metrics_by_id.get(c.get("idcode"), {})

    in_db = [c for c in companies if c["in_db"]]

    # ---- Header ----
    st.markdown(f"### {display_name}")
    bits = []
    if id_number:
        bits.append(f"ID {id_number}")
    if nationality:
        bits.append(nationality)
    bits.append(f"{len(companies)} companies · {len(in_db)} in our financial DB")
    st.caption("  ·  ".join(bits))
    if truncated:
        st.caption("_Showing the first 60 companies (this person has more)._")

    # ---- Attributable portfolio ----
    agg = _portfolio_agg(in_db)
    if agg["owned_count"] > 0:
        st.markdown("##### Attributable portfolio")
        totals = agg["totals"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Revenue", fmt_k_gel(totals["Revenue"]))
        c2.metric("EBITDA", fmt_k_gel(totals["EBITDA"]))
        c3.metric("Net Profit", fmt_k_gel(totals["NetProfit"]))
        c4.metric("Total Assets", fmt_k_gel(totals["TotalAssets"]))
        c5, c6, c7, _c8 = st.columns(4)
        c5.metric("Total Cash", fmt_k_gel(totals["TotalCash"]))
        c6.metric("Total Debt", fmt_k_gel(totals["TotalDebt"]))
        c7.metric("Total Equity", fmt_k_gel(totals["TotalEquity"]))
        st.caption(
            f"Share-weighted across {agg['owned_count']} owned companies  ·  "
            "latest available year each  ·  in GEL thousands."
        )

        # Breakdown pie for a selected metric.
        _pie_metric_label = st.selectbox(
            "Breakdown by",
            options=["Revenue", "Total Assets", "Total Cash", "EBITDA"],
            index=0,
            key=safe_key("person_pie_metric", str(person_id)),
        )
        _label_to_key = {
            "Revenue": "Revenue", "Total Assets": "TotalAssets",
            "Total Cash": "TotalCash", "EBITDA": "EBITDA",
        }
        _mkey = _label_to_key[_pie_metric_label]
        slices = [(c["name"], c["attributable"][_mkey]) for c in agg["by_company"]]
        positive = [(n, v) for n, v in slices if v > 0]
        omitted = len(slices) - len(positive)
        if positive:
            _palette = ["#0E3B36", "#C8922E", "#3E6B8C", "#A6533F",
                        "#6B4E7A", "#5C7A52", "#2FA98A", "#E8B85C"]
            fig = _go.Figure(data=[_go.Pie(
                labels=[n for n, _ in positive],
                values=[v / 1000.0 for _, v in positive],
                hole=0.45,
                marker=dict(colors=_palette * (len(positive) // len(_palette) + 1)),
                hovertemplate="%{label}<br>%{value:,.0f}K GEL<br>%{percent}<extra></extra>",
            )])
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=10, b=10, l=10, r=10), height=300, showlegend=True,
            )
            from lib.theme import chart_theme
            chart_theme(fig)
            st.plotly_chart(fig, use_container_width=True, key=safe_key("person_pie", str(person_id)))
        if omitted:
            st.caption(f"_{omitted} company(ies) with non-positive {_pie_metric_label} omitted from the chart._")
    else:
        st.markdown("##### Attributable portfolio")
        st.caption("No equity stakes in companies we have financials for.")

    # ---- Company list ----
    st.markdown("##### Companies")
    ordered = sorted(companies, key=lambda c: (not c["in_db"], -(c.get("share_pct") or 0)))
    compare_pick: list[str] = []
    for c in ordered:
        roles = ", ".join(c.get("roles") or [])
        ex_tag = "  ·  _former_" if c.get("ex") else ""
        if c["in_db"]:
            col_btn, col_share, col_cmp = st.columns([6, 2, 2])
            label = idcode_to_label.get(c["idcode"], f"{c['idcode']} — {c['name']}")
            with col_btn:
                if st.button(f":material/open_in_new: {c['name']}", key=safe_key("person_open", str(person_id) + (c["idcode"] or "")), use_container_width=True):
                    st.session_state["mode"] = "Single Company"
                    st.session_state["_pending_single_pick"] = label
                    st.query_params["mode"] = "single"
                    st.query_params["id"] = c["idcode"]
                    st.rerun()
            with col_share:
                st.markdown(f"<div style='padding-top:8px'>{(c.get('share_pct') or 0):.2f}%</div>", unsafe_allow_html=True)
            with col_cmp:
                if st.checkbox("Compare", key=safe_key("person_cmp", str(person_id) + (c["idcode"] or ""))):
                    compare_pick.append(label)
            if roles:
                st.caption(f"&nbsp;&nbsp;{roles}{ex_tag}")
        else:
            st.markdown(
                f"<div style='opacity:0.6;padding:4px 0'>○ {c['name']} "
                f"<span style='font-size:11px'>{roles}{' · former' if c.get('ex') else ''} · "
                f"<a href='{_ci_url(c['idcode']) if c.get('idcode') else 'https://companyinfo.ge'}' target='_blank'>companyinfo.ge ↗</a></span></div>",
                unsafe_allow_html=True,
            )

    # ---- Compare action ----
    if len(compare_pick) >= 2:
        if st.button(f"Open {len(compare_pick)} in Compare", type="primary", use_container_width=True,
                     key=safe_key("person_compare_go", str(person_id))):
            st.session_state["compare_picker"] = compare_pick
            st.session_state["mode"] = "Compare"
            st.query_params["mode"] = "compare"
            st.rerun()
    elif compare_pick:
        st.caption("_Select at least 2 companies to open in Compare._")
