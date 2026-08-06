"""Single Company view (Sprint 4.5 — extracted from app.py).

Capital-IQ-style company workspace: a left-rail **section navigator**
(Tearsheet · Income Statement · Balance Sheet · Cash Flow · Ratios · Ownership)
drives one section into the main pane at a time, instead of the old tab strip.
The Tearsheet is a summary (headline KPIs + ownership pie); the statement
sections carry the IFRS-16 toggle, charts, and exports.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

from lib.cache import (
    audit_engagements as _audit_engagements_cache,
    bs_sections as _bs_sections_cache,
    cf_sections as _cf_sections_cache,
    company_ownership as _company_ownership_cache,
    ownership_edges as _ownership_edges_cache,
    consolidated_idcodes as _consolidated_idcodes_cache,
    individual_basis_idcodes as _individual_basis_idcodes_cache,
    metrics_table,
    options_sorted_by_revenue_cached,
    years as _years_cache,
    company_description,
    company_sector,
    dividends as _dividends_cache,
    filing_meta as _filing_meta_cache,
    latest_filing_meta as _latest_filing_meta_cache,
    revaluation_years as _revaluation_years_cache,
    form_type,
    implied_costs,
    insurance_gov_source_urls,
    is_sections,
    ratios,
)
from lib import ownership as _ownership
from lib.auditors import (
    audit_chip_icon as _audit_chip_icon,
    audit_chip_label as _audit_chip_label,
    has_audit_evidence as _has_audit_evidence,
    latest_engagement_for_basis as _latest_engagement_for_basis,
)
from lib.consolidation import (
    parent_of as _consol_parent_of,
    statement_basis_label as _statement_basis_label,
)
from lib.statements_bank import BANK_SECTORS
from lib.statements_insurance import INSURANCE_SECTORS
from lib.insurance_gov_statements import (
    build_insurance_gov_bs_sections,
    build_insurance_gov_is_sections,
    compute_insurance_gov_ratios,
    has_insurance_gov_data,
    insurance_gov_years,
)
from lib.filing_provenance import (
    audit_status as _audit_status,
    resolve_filing_provenance as _resolve_provenance,
)
from lib.ifrs16 import adjust_is_sections
from lib.ratios import build_ratios_table
from lib.theme import chart_theme
from lib.ui import (
    NAVY as _BRAND_NAVY,
    render_grouped_ratios,
    render_is_chart,
    render_reportal_pdf_caption,
    render_statement,
    safe_key,
)
from lib.format import fmt_k_gel, fmt_pct

from views.shared import ViewContext, render_ifrs_controls


# Left-rail sections (Capital-IQ-style). Order = display order.
SECTIONS = (
    "Tearsheet",
    "Income Statement",
    "Balance Sheet",
    "Cash Flow",
    "Ratios",
    "Ownership",
)


@dataclass
class _SectionState:
    """Everything a statement-section renderer needs, computed once by render().

    2026-07-02 decomposition: the section branches used to live inline in a
    ~1,000-line render() closing over ~20 locals — any edit risked three other
    sections and none of it was independently callable. Each field here is one
    of those former locals; the per-section renderers below take exactly this
    object, so their real dependencies are explicit and greppable.
    """
    ctx: ViewContext
    idcode: str
    company_name: str
    years: list[int]
    is_bank: bool
    is_insurer: bool
    use_gov_insurer: bool
    ifrs_on: bool
    assumed_term: float
    interest_rate: float
    is_sections_for_render: list
    implied_costs_map: dict
    bs_sections_for_render: list
    bs_caption: str | None
    file_base: str
    # Statement basis (stage 3 of the switcher): "Consolidated" (default) or
    # "Individual"; fd_table is the financial_data-shaped table that basis
    # reads from. Threaded to every section so IS/BS/CF/Ratios/KPIs agree.
    basis: str = "Consolidated"
    fd_table: str = "financial_data"
    # Year-header source-link kwargs for regulator-covered insurers (empty
    # otherwise); splatted into render_statement.
    gov_year_kwargs: dict = field(default_factory=dict)


def render(ctx: ViewContext) -> None:
    # Options pre-sorted by latest Revenue so big companies surface first when
    # Streamlit's selectbox runs its substring search.
    _single_options = options_sorted_by_revenue_cached(ctx.db_path)

    # Consume a pick STAGED by any other view/dialog (Home, Sector, Screener,
    # Ownership panel, global-search / person dialogs) here — BEFORE the
    # selectbox below is instantiated. Writing the widget's own session_state
    # key *after* it renders in the same run triggers Streamlit's "Bad message
    # format / SessionInfo before initialized" popup (Sprint 26 fix). All those
    # callers now set `_pending_single_pick`; this is the single point that
    # promotes it to the widget key.
    _pending_pick = st.session_state.pop("_pending_single_pick", None)
    if _pending_pick is not None:
        st.session_state["single_company_picker"] = _pending_pick

    # URL → state: preselect a company from ?id= on first load. Setting the
    # widget's session_state key before the widget renders is the supported
    # way to set its default. Guard on membership so a stale/invalid id is
    # ignored rather than raising.
    if "single_company_picker" not in st.session_state:
        _url_id = st.query_params.get("id")
        if _url_id and _url_id in ctx.idcode_to_label:
            _preselect_label = ctx.idcode_to_label[_url_id]
            if _preselect_label in _single_options:
                st.session_state["single_company_picker"] = _preselect_label

    # --- Company picker (on-page; no longer in the sidebar) -----------------
    # Placement depends on whether a company is already chosen. Read the prior
    # selection from session_state BEFORE instantiating the widget so we can
    # decide where it renders (Sprint-26-safe — this only READS the widget key):
    #   - none chosen → a visible picker in the main pane + empty state
    #   - chosen      → the picker tucks into a "Switch company" header popover,
    #                   so switching is one click and never hidden by a collapsed
    #                   sidebar (which is the whole point of this layout).
    _picker_kw = dict(
        options=_single_options,
        placeholder="Start typing…",
        key="single_company_picker",
        help="Sorted by latest Revenue (largest first). Type any part of the name or IdCode.",
    )
    _prior = st.session_state.get("single_company_picker")
    # Drop a stale stored pick (e.g. a DB swap dropped the company) before the
    # widget renders, so the selectbox never gets a value outside its options.
    if _prior and _prior not in _single_options:
        st.session_state.pop("single_company_picker", None)
        _prior = None

    if not _prior:
        # No company selected — clear any stale ?id= from the URL.
        if "id" in st.query_params:
            del st.query_params["id"]
        st.title("Georgia Financials")
        st.selectbox("Pick a company (name or IdCode)", index=None, **_picker_kw)
        from lib.components import empty_state

        def _open_search() -> None:
            # on_click callbacks run before the next script run, so setting the
            # dialog-trigger flag here is Sprint-26-safe.
            st.session_state["_open_search"] = True

        empty_state(
            "Pick a company to begin",
            "Use the picker above, or search the whole universe by name or "
            "IdCode — the search also opens with / or Ctrl-K.",
            actions=[("🔎 Search companies", "sc_empty_search", _open_search)],
        )
        st.stop()

    idcode = ctx.labels_to_idcode[_prior]

    # Header row: company identity on the left, a "Switch company" popover on the
    # right. Both column containers are created now; the switch popover renders
    # immediately, the title/captions fill the left column once we've resolved
    # the form type + available years below.
    _hdr_l, _hdr_r = st.columns([0.78, 0.22], vertical_alignment="center")
    with _hdr_r:
        with st.popover(":material/swap_horiz: Switch company", use_container_width=True):
            # No `index` here: the key already holds a value, so Streamlit drives
            # the selection from session_state (passing index would warn).
            st.selectbox("Pick a company (name or IdCode)", **_picker_kw)

    # state → URL: reflect the selected company so the link is shareable and
    # survives a refresh. Loop-safe (query_params assignment doesn't rerun).
    if st.query_params.get("id") != idcode:
        st.query_params["id"] = idcode

    # Detect form type; override IFRS controls for banks (no operating leases).
    # Sector-driven detection (data-driven labels) OR the legacy form-type flag —
    # either signal selects the financial-institution layout. Sector catches the
    # handful of banks/insurers whose LatestFormType is unset; form_type catches
    # MFO/leasing entities that file on the bank form but aren't in "Banks".
    _ft = form_type(ctx.db_path, idcode)
    _sector = company_sector(ctx.db_path, idcode)
    is_bank = _ft == "bank" or _sector in BANK_SECTORS
    is_insurer = (not is_bank) and (_ft == "insurer" or _sector in INSURANCE_SECTORS)
    # Insurers covered by the regulator dataset (insurance.gov.ge 12-month return)
    # are shown ENTIRELY from that source — IS/BS/Ratios and the visible years —
    # replacing the sparse reportal-derived statements. Insurers not in the
    # regulator dataset (e.g. brokers) keep the reportal fallback.
    use_gov_insurer = is_insurer and has_insurance_gov_data(ctx.db_path, idcode)

    # --- Statement basis (stage 3 of the switcher — RESUME.md). The WIDGET
    # lives in the toolbar below; its committed value is read here (a
    # pre-instantiation session read, Sprint-26-safe) so the year list, the
    # header badge and every section see ONE basis. Offered only when this
    # filer's individual statements exist in the sidecar (empty set when the
    # DB lacks the table -> the control never shows) and never for insurers
    # (regulator-covered ones don't render reportal statements at all, and the
    # reportal-fallback insurance builders are not basis-threaded).
    _basis_key = safe_key("sc_basis", idcode)
    _basis_saved = f"_sc_basis_saved_{idcode}"
    _dual_available = (
        not is_insurer
        and idcode in _individual_basis_idcodes_cache(ctx.db_path)
    )
    # The widget skips runs on sections without the toolbar (Ownership), and
    # Streamlit GC's skipped widgets' state - reseed from our own copy first.
    if _basis_key not in st.session_state and st.session_state.get(_basis_saved):
        st.session_state[_basis_key] = st.session_state[_basis_saved]
    basis = (
        "Individual"
        if _dual_available and st.session_state.get(_basis_key) == "Individual"
        else "Consolidated"
    )
    st.session_state[_basis_saved] = basis
    fd_table = "financial_data_individual" if basis == "Individual" else "financial_data"

    # Track recently-viewed companies (session-only, most-recent-first, max 5).
    # Surfaced on the Home tab.
    _recents = [c for c in st.session_state.get("recent_companies", []) if c != idcode]
    _recents.insert(0, idcode)
    st.session_state["recent_companies"] = _recents[:5]

    all_years = _years_cache(ctx.db_path, idcode, table=fd_table)
    # Regulator-covered insurers: restrict the whole view to the years the
    # regulator dataset carries (regulator-data-only — no reportal years mixed in).
    if use_gov_insurer:
        all_years = insurance_gov_years(ctx.db_path, idcode)

    if not all_years:
        st.warning(f"No financial data found for {idcode}.")
        st.stop()

    # --- Company header (fills the left column reserved above) --------------
    company_name = next(name for idc, name in ctx.companies if idc == idcode)
    with _hdr_l:
        st.title(company_name)
        st.caption(
            f"IdCode: {idcode}  ·  Available {min(all_years)}–{max(all_years)}  ·  "
            f"Values in GEL thousands"
        )
        # Group structure at-a-glance (companyinfo.ge ownership). Full detail +
        # click-through live in the Ownership section. Edges are cached, so the
        # lookup is cheap on every section render.
        _edges = _ownership_edges_cache(ctx.db_path)
        _par_edge = None
        _int_kids: list = []
        if _edges:
            _par_edge = _ownership.controlling_parent(idcode, _edges)
            _int_kids = [e for e in _ownership.children_of(idcode, _edges) if e["is_internal"]]
            if _par_edge is not None:
                _pnm = _par_edge.get("parent_name") or ctx.idcode_to_label.get(
                    _par_edge["parent"], _par_edge["parent"])
                st.caption(
                    f":material/account_tree: Subsidiary of **{_pnm}** "
                    f"({_par_edge['share']:.0f}%). See **Ownership** for the group "
                    f"structure and consolidation basis."
                )
            elif _int_kids:
                _n = len(_int_kids)
                st.caption(
                    f":material/account_tree: **Group parent** — controls **{_n}** "
                    f"{'company' if _n == 1 else 'companies'} that file separately. "
                    f"See **Ownership**."
                )
        # Statement basis (Consolidated vs Individual) — the filer's own
        # declaration (companies.LatestIsConsolidated). Header-level so it covers
        # every section, including a deep-link straight to IS/BS/CF. Suppressed
        # for regulator-covered insurers: their shown statements come from the
        # insurance.gov.ge return, not the reportal filing this flag describes.
        if not use_gov_insurer:
            _basis = _statement_basis_label(
                idcode in _consolidated_idcodes_cache(ctx.db_path),
                is_internal_parent=bool(_int_kids),
                is_internal_subsidiary=_par_edge is not None,
                latest_year=max(all_years),
            )
            if basis == "Individual":
                _basis = (
                    "Individual financial statements (switched)",
                    "You switched this company to its INDIVIDUAL (standalone) "
                    "filing via the basis toggle in the statement toolbar. "
                    "Figures exclude subsidiaries that the consolidated filing "
                    "includes.",
                )
            if _basis is not None:
                _blabel, _btip = _basis
                st.caption(f":material/account_balance_wallet: **{_blabel}**", help=_btip)
        # Filing provenance — what these figures ARE before anyone reads them:
        # the filer's SARAS category, the standard that follows from it, whether
        # an audit was legally required, and whether PP&E is carried at revalued
        # amount. Answers an analyst review (2026-07-31) whose common thread was
        # that the dashboard presents every filing with identical confidence.
        # Suppressed for regulator-covered insurers, whose displayed statements
        # come from the insurance.gov.ge return rather than the reportal filing
        # these labels describe.
        if not use_gov_insurer:
            _meta_by_year = _filing_meta_cache(ctx.db_path, idcode)
            _fallback = dict(_latest_filing_meta_cache(ctx.db_path, idcode))
            _fallback["latest_year"] = max(all_years)
            _prov_year, _prov_badges, _prov_change = _resolve_provenance(
                _meta_by_year,
                latest_fallback=_fallback,
                revaluation=_revaluation_years_cache(ctx.db_path, idcode),
            )
            if _prov_badges:
                _strip = " · ".join(
                    f":material/{b.icon}: **{b.label}**" for b in _prov_badges)
                _scope = f"FY{_prov_year} filing" if _prov_year else "Latest filing"
                st.caption(
                    f"{_scope}: {_strip}",
                    help="\n\n".join(
                        f"**{b.label}** — {b.tooltip}" for b in _prov_badges),
                )
            if _prov_change:
                st.caption(f":material/history: {_prov_change}")
            # Audit-status chip — who audited the LATEST filed year with an
            # `auditors` row, and what they concluded, matched to the current
            # statement basis where possible. Individual and consolidated
            # filings can carry DIFFERENT opinions from the same firm (see
            # lib/auditors.py's module docstring), so the pick matters; falls
            # back to whichever basis has a row when the preferred one
            # doesn't. Reuses `_meta_by_year`/`_fallback` from the provenance
            # strip above so the two never disagree about the filer's
            # category. Suppressed for regulator-covered insurers for the same
            # reason as the strip: their displayed statements aren't the
            # reportal filing the opinion covers.
            _audit_rows = _audit_engagements_cache(ctx.db_path, idcode)
            _audit_pick = _latest_engagement_for_basis(
                _audit_rows, is_consolidated_pref=(basis != "Individual"))
            if _audit_pick is not None:
                _ayear = _audit_pick["year"]
                _acategory = (
                    _meta_by_year.get(_ayear, {}).get("category")
                    or _fallback.get("category")
                )
                _afoot = []
                _apartner = " ".join(
                    p for p in (
                        _audit_pick.get("partner_first"),
                        _audit_pick.get("partner_last"),
                    ) if p
                )
                if _apartner:
                    _afoot.append(f"Engagement partner: {_apartner}.")
                _afee = _audit_pick.get("fee")
                _afee_s = fmt_k_gel(_afee) if _afee else ""
                if _afee_s:
                    _afoot.append(f"Audit fee: ₾{_afee_s}k.")
                if _has_audit_evidence(_audit_pick):
                    _albl = _audit_chip_label(
                        _audit_pick.get("opinion_code"), _audit_pick.get("firm"), _ayear)
                    _aicon = _audit_chip_icon(_audit_pick.get("opinion_code"))
                    _abasis_word = (
                        "consolidated" if _audit_pick["is_consolidated"] else "individual")
                    _afoot.append(
                        f"The opinion covers the FY{_ayear} filing, {_abasis_word} basis.")
                    st.caption(
                        f":material/{_aicon}: **{_albl}**", help=" ".join(_afoot))
                else:
                    _abadge = _audit_status(_acategory, has_audit_report=False)
                    if _abadge is not None:
                        _atip = _abadge.tooltip
                        if _afoot:
                            _atip = _atip + " " + " ".join(_afoot)
                        st.caption(
                            f":material/{_abadge.icon}: **{_abadge.label}**", help=_atip)
        if is_bank:
            st.caption(":material/account_balance: **Bank reporting format** — net interest income, fees, bank balance sheet (loans, deposits, capital), and bank KPIs (NIM, cost/income, cost of risk, ROAA/ROAE).")
        elif is_insurer and use_gov_insurer:
            st.caption(":material/verified_user: **Insurance regulatory return** — source: insurance.gov.ge 12-month statistical filing (replaces reportal data for this insurer). Premiums, claims, underwriting result, and KPIs (loss / expense / combined ratio).")
        elif is_insurer:
            st.caption(":material/verified_user: **Insurance reporting format** — premiums, claims, underwriting result, and KPIs (loss / expense / combined ratio).")

    # --- Section navigator — on-page tabs (was a sidebar radio) -------------
    # A Capital-IQ-style tab rail directly under the company header drives which
    # block renders. On the page (not the sidebar) so the most-used control can't
    # be hidden by a collapsed sidebar. The canonical choice lives in
    # `single_section` (persists across company switches, keyed without idcode);
    # `single_section_seg` is the widget key. An on_change callback captures a
    # pick, and we re-seed the widget whenever it disagrees with the canonical
    # value — which also makes the single-select un-deselectable (clicking the
    # active tab keeps it selected instead of clearing to None).
    st.session_state.setdefault("single_section", "Tearsheet")

    def _sync_section() -> None:
        _picked = st.session_state.get("single_section_seg")
        if _picked:
            st.session_state["single_section"] = _picked

    if st.session_state.get("single_section_seg") != st.session_state["single_section"]:
        st.session_state["single_section_seg"] = st.session_state["single_section"]
    with st.container(key="fd_sectiontabs"):
        st.segmented_control(
            "Section",
            SECTIONS,
            key="single_section_seg",
            selection_mode="single",
            label_visibility="collapsed",
            on_change=_sync_section,
        )
    section = st.session_state["single_section"]

    # --- Inline statement toolbar (was sidebar Years + IFRS 16) -------------
    # Years + the IFRS-16 reversal now live right on the statement, where they
    # act, in an inline toolbar. Ownership ignores both, so the toolbar is hidden
    # there. Banks / insurers don't use the lease adjustment, so the IFRS control
    # is omitted for them (forced off) — no misleading banner, EBITDA-free
    # layouts untouched. The Years widget is still keyed by idcode so switching
    # companies resets to "all years" rather than carrying a stale pick.
    _yk = f"year_pick_{idcode}_{basis}"
    if section == "Ownership":
        years = list(all_years)
        ifrs_on, assumed_term, interest_rate = False, 5.0, 0.06
    else:
        with st.container(key="fd_toolbar"):
            _tc = st.columns([1.4, 1.4, 2.2, 3.0], vertical_alignment="center")
            if _dual_available:
                with _tc[2]:
                    st.segmented_control(
                        "Statement basis",
                        ["Consolidated", "Individual"],
                        key=_basis_key,
                        default="Consolidated",
                        label_visibility="collapsed",
                        help=(
                            "This filer submitted BOTH consolidated and individual "
                            "statements for at least one year. Individual figures "
                            "come from the recovered standalone filings; year-header "
                            "PDF links still point at the report our scrape resolved "
                            "(usually the consolidated one)."
                        ),
                    )
            with _tc[0]:
                _prev = st.session_state.get(_yk)
                _nsel = len(_prev) if _prev else len(all_years)
                with st.popover(
                    f":material/date_range: Years · {_nsel} of {len(all_years)}",
                    use_container_width=True,
                ):
                    _picked_years = st.multiselect(
                        "Years to display",
                        options=list(reversed(all_years)),
                        default=list(all_years),
                        key=_yk,
                        label_visibility="collapsed",
                        help="Pick which fiscal years show in the statements. "
                             "CAGR recomputes over the selected span. Empty = all years.",
                    )
                years = sorted(_picked_years) if _picked_years else list(all_years)
            if is_bank or is_insurer:
                ifrs_on, assumed_term, interest_rate = False, 5.0, 0.06
            else:
                with _tc[1]:
                    _ifrs_active = bool(st.session_state.get("ifrs_on_toggle", False))
                    with st.popover(
                        ":material/tune: IFRS 16" + ("  ·  on" if _ifrs_active else ""),
                        use_container_width=True,
                    ):
                        ifrs_on, assumed_term, interest_rate = render_ifrs_controls()

    # For a regulator-covered insurer the statement year headers link to the
    # insurance.gov.ge source return (its actual data source, all years incl.
    # the latest), with reportal audited PDFs offered as a secondary caption.
    _gov_year_kwargs = (
        {"year_source": "insurance_gov",
         "year_source_urls": insurance_gov_source_urls(ctx.db_path, idcode)}
        if use_gov_insurer else {}
    )

    # --- Ownership data (companyinfo.ge public API; cached 24h upstream).
    # ONLY the Tearsheet (partners pie) and the Ownership section consume this.
    # fetch_company_detail makes up to TWO sequential HTTP calls (10s timeout
    # each); on a cold cache — which after every Space restart is the first view
    # of a company — that is up to ~20s of blocking. Fetching it unconditionally
    # put that round-trip on the critical path of EVERY section, so the Income
    # Statement / Balance Sheet / Cash Flow / Ratios (which don't use it) would
    # hang behind a slow upstream ("won't load income statements" on cpu-basic).
    # Gate the fetch on the active section so the statements never wait on it.
    from lib.companyinfo import fetch_company_detail, summarize_affiliations, companyinfo_url
    info_url = companyinfo_url(idcode)  # pure string; no network
    detail: dict | None = None
    partners: list[dict] = []
    mgmt: list[dict] = []
    if section in ("Tearsheet", "Ownership"):
        # Serve ownership from the precomputed company_ownership table (no
        # network; scripts/build_company_ownership.py). Only the Ownership page
        # falls back to a LIVE companyinfo.ge call for a company missing from the
        # table — so the Tearsheet and every statement section never block on the
        # API (which rate-limits and can hang ~10-20s; see the 2026-07-15 fix).
        detail = _company_ownership_cache(ctx.db_path, idcode)
        if detail is None and section == "Ownership":
            detail = fetch_company_detail(idcode)
        if detail:
            _affil = summarize_affiliations(detail)
            partners = _affil["partners"]
            mgmt = _affil["management"]

    # --- Compute the (possibly adjusted) IS sections once; reused across
    # sections (Tearsheet KPIs, Income Statement, Ratios).
    if is_bank:
        from lib.statements_bank import build_bank_is_sections
        is_sections_for_render = build_bank_is_sections(ctx.db_path, idcode, list(years),
                                                        table=fd_table)
        raw_is_sections = is_sections_for_render
        implied_costs_map: dict = {}
    elif is_insurer:
        if use_gov_insurer:
            is_sections_for_render = build_insurance_gov_is_sections(ctx.db_path, idcode, list(years))
        else:
            from lib.statements_insurance import build_insurance_is_sections
            is_sections_for_render = build_insurance_is_sections(ctx.db_path, idcode, list(years))
        raw_is_sections = is_sections_for_render
        implied_costs_map = {}
    else:
        raw_is_sections = is_sections(ctx.db_path, idcode, tuple(years), table=fd_table)
        implied_costs_map = {}
        if ifrs_on:
            implied_costs_map = implied_costs(
                ctx.db_path, idcode, tuple(years), float(assumed_term), float(interest_rate),
                table=fd_table,
            )
            is_sections_for_render = adjust_is_sections(raw_is_sections, implied_costs_map)
        else:
            is_sections_for_render = raw_is_sections

    # --- Build the Balance Sheet sections once (Tearsheet KPIs + BS section).
    # Per company type, mirroring the old per-tab branching. bs_caption is the
    # one-line note shown above the BS table (None for the plain reportal layout).
    bs_caption: str | None = None
    if is_bank:
        from lib.statements_bank import build_bank_bs_sections
        bs_sections_for_render = build_bank_bs_sections(ctx.db_path, idcode, list(years),
                                                        table=fd_table)
        bs_caption = (
            ":material/account_balance: **Bank balance sheet** — unclassified IFRS layout "
            "(no current / non-current split). Group totals are the "
            "reported figures; detail lines are the face-of-balance-sheet "
            "items reportal.ge captured. The **Balance Check** is "
            "Total Assets − (Total Liabilities + Total Equity) and should "
            "be ~0 when the statement ties."
        )
    elif use_gov_insurer:
        bs_sections_for_render = build_insurance_gov_bs_sections(ctx.db_path, idcode, list(years))
        bs_caption = (
            ":material/verified_user: **Insurance regulatory balance sheet** (insurance.gov.ge) — "
            "assets · liabilities · equity per the statutory return. "
            "Total Liabilities & Equity ties to Total Assets by construction."
        )
    else:
        bs_sections_for_render = _bs_sections_cache(ctx.db_path, idcode, tuple(years),
                                                    table=fd_table)

    # --- Insurer premium mix & class loss ratios (insurance.gov.ge market data) ---
    # Shown for insurers, above the section content; links through to the full
    # Insurance dashboard (Sector Overviews) for cross-company comparison.
    if is_insurer:
        from lib.cache import ins_company_class_mix
        _mix = ins_company_class_mix(ctx.db_path, idcode)
        if _mix is not None and not _mix.empty:
            _yr = int(_mix["FVYear"].max())
            _m = _mix[(_mix["FVYear"] == _yr) & (_mix["gwp"] > 0)].sort_values(
                "gwp", ascending=False)
            with st.expander(f":material/bar_chart: Premium mix & class loss ratios — FY{_yr} "
                             f"(insurance.gov.ge market data)", expanded=False):
                import plotly.graph_objects as go
                cmix, ctab = st.columns([1, 1])
                with cmix:
                    figm = go.Figure(go.Pie(
                        labels=_m["label"], values=_m["gwp"], hole=0.45,
                        hovertemplate="%{label}<br>₾%{value:,.0f}<br>%{percent}<extra></extra>"))
                    chart_theme(figm)
                    figm.update_layout(
                        height=300, margin=dict(l=10, r=10, t=10, b=10),
                        showlegend=True, legend=dict(font=dict(size=10)))
                    st.plotly_chart(figm, use_container_width=True,
                                    key=safe_key("sc_ins_mix", idcode))
                with ctab:
                    _tbl = pd.DataFrame({
                        "Class": _m["label"],
                        "GWP (K)": _m["gwp"].map(fmt_k_gel),
                        "Loss ratio": _m["net_loss_ratio"].map(fmt_pct),
                    })
                    st.dataframe(_tbl, use_container_width=True, hide_index=True)
                st.caption("Premium written and net loss ratio by insurance class. "
                           "See **Sector Overviews → Insurance** for full market comparison.")

    def _safe(s: str) -> str:
        return "".join(ch for ch in s if ch.isalnum() or ch in "-_")[:40] or "company"

    state = _SectionState(
        ctx=ctx,
        idcode=idcode,
        company_name=company_name,
        years=list(years),
        is_bank=is_bank,
        is_insurer=is_insurer,
        use_gov_insurer=use_gov_insurer,
        ifrs_on=ifrs_on,
        assumed_term=float(assumed_term),
        interest_rate=float(interest_rate),
        is_sections_for_render=is_sections_for_render,
        implied_costs_map=implied_costs_map,
        bs_sections_for_render=bs_sections_for_render,
        bs_caption=bs_caption,
        file_base=f"{_safe(company_name or idcode)}_{idcode}"
                  + ("_individual" if basis == "Individual" else ""),
        basis=basis,
        fd_table=fd_table,
        gov_year_kwargs=_gov_year_kwargs,
    )

    # =====================================================================
    # Section dispatch — each statement section is a module-level renderer
    # taking the explicit _SectionState (2026-07-02 decomposition).
    # =====================================================================
    if section == "Tearsheet":
        _render_tearsheet(ctx, idcode, company_name, years, partners, is_bank, is_insurer,
                          basis=basis)

    elif section == "Income Statement":
        _render_income_statement(state)

    elif section == "Balance Sheet":
        _render_balance_sheet(state)

    elif section == "Cash Flow":
        _render_cash_flow(state)

    elif section == "Ratios":
        _render_ratios(state)

    elif section == "Ownership":
        _render_ownership(ctx, idcode, detail, partners, mgmt, info_url)


# =========================================================================
# Statement-section renderers (module-level; extracted from render() in the
# 2026-07-02 decomposition — pure moves, no behavior change).
# =========================================================================


def _ifrs_status_banner(s: _SectionState, also_note_bs: bool = False) -> None:
    """Render the 'IFRS 16 reversal applied' info banner if toggle is on."""
    if not s.ifrs_on:
        return
    methods = {info["method"] for info in s.implied_costs_map.values()}
    methods.discard("none")
    if methods == {"rou"}:
        method_label = "Right-of-Use Assets"
    elif methods == {"lease_liability"}:
        method_label = "Finance Lease Payable"
    elif not methods:
        method_label = "no lease data found (no adjustment applied)"
    else:
        method_label = "mixed (RoU where available, Lease Payable otherwise)"
    msg = (
        f"**IFRS 16 reversal applied** · assumed lease term **{s.assumed_term:.1f} yrs** · "
        f"assumed rate **{s.interest_rate*100:.1f}%** · basis **{method_label}**. "
        f"`(adj.)` rows show restated values. EBITDA drops by full annual lease cost; "
        f"EBIT drops by the interest portion; PBT/Net Profit unchanged."
    )
    if also_note_bs:
        msg += "  \n_Note: adjustment is applied to the Income Statement only; the Balance Sheet below is unchanged._"
    st.info(msg)


def _cf_sections_for(s: _SectionState) -> list[dict]:
    """Cash-flow sections for this company, or [] when there is no CF statement.

    Regulator-covered insurers have none (the insurance.gov.ge 12-month return
    carries only BS + IS); FCF is suppressed for financial institutions, whose
    investing flows are securities and lending rather than capex.
    """
    if s.use_gov_insurer:
        return []
    return _cf_sections_cache(
        s.ctx.db_path, s.idcode, tuple(s.years),
        include_fcf=not (s.is_bank or s.is_insurer),
        table=s.fd_table,
    )


def _kpi_block(s: _SectionState) -> tuple[list[dict], str, str]:
    """Sector KPI rows + section title + methodology note for a bank / insurer.

    ``compute_*_ratios`` return rows shaped ``{"Ratio": str, <year>:
    float|None, "_fmt": "pct"|"num"}``; a ``None`` cell means the data couldn't
    support that ratio for that year and renders as "n/a".
    """
    if s.is_bank:
        from lib.statements_bank import compute_bank_ratios
        return (
            compute_bank_ratios(s.ctx.db_path, s.idcode, list(s.years),
                                table=s.fd_table),
            "Bank KPIs",
            "Balance-sheet-based ratios (NIM, cost of funds, cost of "
            "risk, ROAA/ROAE) use 2-period average balances. NIM = net "
            "interest income / avg interest-earning assets; cost/income "
            "= operating expenses (ex-provisions) / operating income; "
            "cost of risk = loan-loss provisions / avg gross loans.",
        )
    if s.use_gov_insurer:
        rows = compute_insurance_gov_ratios(s.ctx.db_path, s.idcode, list(s.years))
    else:
        from lib.statements_insurance import compute_insurance_ratios
        rows = compute_insurance_ratios(s.ctx.db_path, s.idcode, list(s.years))
    return (
        rows,
        "Underwriting KPIs",
        "Loss / expense / combined ratios are on a **net earned "
        "premium** basis. Combined ratio < 100% = underwriting profit. "
        "Retention = net / gross premium. ROE/ROA use period-end equity "
        "/ assets.",
    )


def _kpi_display_frame(kpi_rows: list[dict], years: list[int]) -> pd.DataFrame:
    """Format KPI rows into the display/export frame (pre-formatted strings)."""
    def _fmt_cell(v, fmt):
        if v is None:
            return "n/a"
        if fmt == "pct":
            from lib.format import fmt_pct_signed

            return fmt_pct_signed(v) or "0.0%"
        return f"{v:,.2f}"

    disp = []
    for r in kpi_rows:
        rec = {"Ratio": r["Ratio"]}
        for y in years:
            rec[str(y)] = _fmt_cell(r.get(y), r.get("_fmt", "num"))
        disp.append(rec)
    return pd.DataFrame(disp)


def _ratios_frame(s: _SectionState) -> pd.DataFrame:
    """The generic (non-bank/insurer) ratios frame.

    With the IFRS 16 adjustment on, ratios are recomputed against the adjusted
    IS so EBITDA/EBIT-based margins reflect the restated numbers.
    """
    if s.ifrs_on:
        return build_ratios_table(
            s.ctx.db_path, s.idcode, s.years, is_sections=s.is_sections_for_render,
            table=s.fd_table,
        )
    return ratios(s.ctx.db_path, s.idcode, tuple(s.years), table=s.fd_table)


def _ratio_sheet_spec(s: _SectionState) -> dict | None:
    """Bundle sheet spec for whichever ratio block this company type shows."""
    if s.is_bank or s.is_insurer:
        kpi_rows, kpi_title, _note = _kpi_block(s)
        if not kpi_rows:
            return None
        return {
            "kind": "dataframe", "name": "KPIs",
            "title": f"{kpi_title} — {s.company_name or s.idcode}",
            "df": _kpi_display_frame(kpi_rows, s.years),
            "label_col": "Ratio", "numeric_format": None,
        }
    df = _ratios_frame(s)
    return {
        "kind": "dataframe", "name": "Ratios",
        "title": f"Ratios — {s.company_name or s.idcode}",
        "df": df, "label_col": df.columns[0] if len(df.columns) else None,
        "numeric_format": None,
    }


def _bundle_export(s: _SectionState) -> None:
    """Prepare→Download ONE workbook holding every statement + the ratios.

    Replaces the old per-section single-sheet exports: pulling numbers for a
    company means wanting IS + BS + CF + Ratios together, not four separate
    downloads. Offered identically at the bottom of each statement section —
    only one section renders per run, so the widget keys can't collide.

    Two-step so the (heavy) workbook build runs only on the explicit Prepare
    click, not on every rerun. The prepared bytes + a "ready token" live in
    session_state; the Download buttons only show while the stored token matches
    the current (company, years, IFRS-toggle) selection, so switching any of
    them invalidates a stale prepared file automatically.
    """
    from lib.excel_export import bundle_to_xlsx, dataframe_to_csv, spec_has_content

    idcode, years = s.idcode, s.years
    ready_token = (idcode, tuple(years), s.ifrs_on)
    ready_key = "bundle_xlsx_ready_for"
    span = f"IdCode {idcode}  ·  FY {min(years)}–{max(years)}"
    ifrs_tag = "  ·  IFRS 16 adj." if s.ifrs_on else ""

    st.caption(
        ":material/description: One workbook, one download — **Income "
        "Statement · Balance Sheet · Cash Flow · Ratios**, each on its own "
        "sheet (a statement the filings don't carry is omitted). "
        "Operating-expense \"Other (N items)\" rollups are broken out into "
        "their individual lines."
    )
    if st.button(":material/download: Prepare full export (XLSX)", key="bundle_xlsx_prep"):
        specs = [
            {
                "kind": "sections", "name": "Income Statement",
                "title": f"Income Statement — {s.company_name or idcode}",
                "subtitle": span + ifrs_tag,
                "sections": s.is_sections_for_render, "years": years,
            },
            {
                "kind": "sections", "name": "Balance Sheet",
                "title": f"Balance Sheet — {s.company_name or idcode}",
                "subtitle": span + ("  ·  bank format" if s.is_bank else ""),
                "sections": s.bs_sections_for_render, "years": years,
            },
            {
                "kind": "sections", "name": "Cash Flow",
                "title": f"Cash Flow — {s.company_name or idcode}",
                "subtitle": span,
                "sections": _cf_sections_for(s), "years": years,
            },
        ]
        ratio_spec = _ratio_sheet_spec(s)
        if ratio_spec is not None:
            ratio_spec["subtitle"] = span + "  ·  money in GEL thousands" + ifrs_tag
            specs.append(ratio_spec)
        if not any(spec_has_content(spec) for spec in specs):
            st.info(
                "Nothing to export — no statement data for this company in the "
                "selected years."
            )
            st.session_state.pop(ready_key, None)
            return
        st.session_state[ready_key] = ready_token
        st.session_state["bundle_xlsx_data"] = bundle_to_xlsx(specs)
        # The ratio block also ships as a flat CSV — named for whichever block
        # this company type shows ("Ratios" / "KPIs").
        st.session_state["bundle_csv_data"] = (
            dataframe_to_csv(ratio_spec["df"]) if ratio_spec is not None else None
        )
        st.session_state["bundle_csv_name"] = (
            ratio_spec["name"] if ratio_spec is not None else None
        )
    if st.session_state.get(ready_key) == ready_token:
        col_x, col_c = st.columns(2)
        with col_x:
            st.download_button(
                "Download Financials.xlsx",
                data=st.session_state["bundle_xlsx_data"],
                file_name=f"{s.file_base}_Financials.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="bundle_xlsx",
            )
        with col_c:
            if st.session_state.get("bundle_csv_data") is not None:
                csv_name = st.session_state.get("bundle_csv_name") or "Ratios"
                st.download_button(
                    f"Download {csv_name}.csv",
                    data=st.session_state["bundle_csv_data"],
                    file_name=f"{s.file_base}_{csv_name}.csv",
                    mime="text/csv",
                    key="bundle_csv",
                )


def _render_income_statement(s: _SectionState) -> None:
    """Income Statement section: IFRS-16 banner + explainer, chart, statement
    table, export."""
    ctx, idcode, years = s.ctx, s.idcode, s.years
    is_sections_for_render = s.is_sections_for_render
    _ifrs_status_banner(s)
    with st.expander(":material/info: IFRS 16 — what changed in 2019 and how this dashboard handles it"):
        st.markdown(
            "**Background.** Before IFRS 16 (effective for most Georgian companies from 2019), "
            "operating-lease rent was a single line in Operating Expenses (`Rental Expenses`). "
            "Post-IFRS 16, each lease puts a right-of-use **asset** and a lease **liability** on "
            "the Balance Sheet. The annual lease payment is then split into two pieces on the P&L:\n\n"
            "1. **Depreciation** of the right-of-use asset \u2192 in **D&A** (above EBIT)\n"
            "2. **Interest** on the lease liability \u2192 in **Interest Expense** (below EBIT)\n\n"
            "Total economic cost is the same, but the **classification** changed. For lease-heavy "
            "businesses this artificially inflates **EBITDA** (rent no longer in OpEx) and **EBIT** "
            "(interest moved below the line) compared to pre-2019 numbers and to peers that had "
            "different lease accounting.\n\n"
            "---\n\n"
            "**This dashboard's adjustment.** Toggle **\"Reclassify lease costs (IFRS 16 reversal)\"** "
            "in the sidebar to estimate the pre-IFRS-16 P&L:\n\n"
            "- Annual lease cost **X** \u2248 `Finance Lease Payable / assumed term` "
            "(or `Right-of-Use Assets / assumed term` when reported separately)\n"
            "- Interest portion **I** \u2248 `rate \u00d7 Lease Payable / 2`\n"
            "- Depreciation portion **D** = X \u2212 I\n\n"
            "When ON, we add X back to OpEx as implied rent, remove D from D&A, and remove I from "
            "Interest Expense. Result: **EBITDA drops by X**, **EBIT drops by I**, and **PBT / Net "
            "Profit are unchanged** (the moves cancel out below EBITDA).\n\n"
            "Affected rows are labeled `(adj.)` and the assumptions appear in a status banner at "
            "the top of the Income Statement tab when the toggle is on. Always-on metrics like "
            "**EBITDAR** (`EBITDA + Rental Expenses`) don't need this adjustment \u2014 they're stable "
            "across the IFRS 16 transition regardless."
        )
    # Insurers that straddle the FY2023 IFRS-17 adoption get a unified layout
    # (signalled by the "Net Insurance Result" line, which only the
    # transition builder emits). Flag the basis break so the build-up rows
    # reading blank on one side of 2023 is understood, not mistaken for a gap.
    if s.is_insurer and any(
        sec["label"] == "Net Insurance Result" for sec in is_sections_for_render
    ):
        st.info(
            ":material/verified_user: **Reporting basis changes at FY2023 (IFRS 17 adoption).** "
            "Pre-2023 years use the premium-based IFRS-4 presentation; 2023+ "
            "use IFRS 17 (*Insurance revenue / service expenses*). The two are "
            "made comparable at the **Net Insurance Result** level (IFRS-4 "
            "underwriting result net of operating/admin expenses \u2248 IFRS-17 "
            "insurance service result); the detail rows beneath it show each "
            "basis's own build-up, so they're blank on the other side of 2023. "
            "*Net Investment Income, PBT and Net Profit are continuous; "
            "Other Income & Expenses (net) balances the chain to PBT.*"
        )
    render_is_chart(is_sections_for_render, years)
    render_statement(is_sections_for_render, years, statement_kind="is", idcode=idcode,
                     common_size_toggle=False, db_path=ctx.db_path, **s.gov_year_kwargs)
    if s.use_gov_insurer:
        render_reportal_pdf_caption(ctx.db_path, idcode, years)

    st.markdown("---")
    _bundle_export(s)


def _render_balance_sheet(s: _SectionState) -> None:
    """Balance Sheet section: IFRS banner, per-type caption, statement, export."""
    ctx, idcode, years = s.ctx, s.idcode, s.years
    bs_sections_for_render = s.bs_sections_for_render
    _ifrs_status_banner(s, also_note_bs=True)
    if s.is_bank and not bs_sections_for_render:
        st.info(
            ":material/account_balance: No balance-sheet line items found for this bank in the "
            "selected years."
        )
    else:
        if s.bs_caption:
            st.caption(s.bs_caption)
        render_statement(bs_sections_for_render, years, statement_kind="bs", idcode=idcode,
                         common_size_toggle=False, db_path=ctx.db_path, **s.gov_year_kwargs)
        if s.use_gov_insurer:
            render_reportal_pdf_caption(ctx.db_path, idcode, years)
        st.markdown("---")
        _bundle_export(s)


def _render_cash_flow(s: _SectionState) -> None:
    """Cash Flow section. The reportal.ge exports carry only the summary
    net-activity figures (Operating / Investing / Financing) plus the
    opening/closing cash reconciliation \u2014 there are no per-line detail rows
    in the source, so every CF row is a derived total. FCF is a capex-proxy
    derivation; it's suppressed for banks/insurers whose investing flows are
    securities/lending, not capex."""
    ctx, idcode, years = s.ctx, s.idcode, s.years
    if s.use_gov_insurer:
        # The regulatory 12-month return has only BS + IS sheets \u2014 no cash flow.
        st.info(
            ":material/verified_user: The insurance regulatory 12-month return (insurance.gov.ge) "
            "does not include a cash-flow statement, so none is shown here for "
            "this insurer."
        )
    cf_sections = _cf_sections_for(s)
    if not cf_sections:
        if not s.use_gov_insurer:
            st.info(
                "No cash-flow statement data found for this company in the "
                "selected years. The reportal.ge filings don't always include "
                "the cash-flow statement."
            )
    else:
        st.caption(
            "Summary cash-flow statement \u2014 net Operating / Investing / "
            "Financing flows, reconciled to opening & closing cash. Source "
            "filings carry only these summary figures (no per-line detail)."
        )
        if s.is_bank or s.is_insurer:
            st.caption(
                ":material/info: Free Cash Flow is omitted for financial institutions \u2014 "
                "their investing flows are securities and lending, not capex, "
                "so an OCF \u2212 Investing 'FCF' would be misleading."
            )
        else:
            st.caption(
                ":material/info: **Free Cash Flow** here is **OCF \u2212 Capex proxy**, where the "
                "capex proxy is the net Investing outflow (the source has no "
                "standalone capex line)."
            )
        render_statement(cf_sections, years, statement_kind="cf", idcode=idcode,
                         common_size_toggle=False, db_path=ctx.db_path)
        # Cash conversion (OCF / EBITDA) — the one derived ratio the GEL table
        # can't hold. EBITDA comes from the rendered IS sections so the figure
        # agrees with the Income Statement tab (incl. the IFRS-16 toggle).
        if not (s.is_bank or s.is_insurer):
            _ocf_row = next(
                (sec["total"] for sec in cf_sections
                 if sec["label"].startswith("Net Cash from Operating")), {})

            def _ebitda_for(y: int) -> float:
                for sec in s.is_sections_for_render:
                    if sec["label"].startswith("EBITDA"):
                        return sec["total"].get(y, 0) or 0
                return 0

            _conv_parts = []
            for y in years:
                _e, _o = _ebitda_for(y), _ocf_row.get(y, 0)
                _conv_parts.append(
                    f"FY{y} {_o / _e * 100:.0f}%" if (_o and _e > 0) else f"FY{y} n/a"
                )
            if any(not p.endswith("n/a") for p in _conv_parts):
                st.caption(
                    ":material/sync_alt: **Cash conversion (OCF / EBITDA):** "
                    + " · ".join(_conv_parts)
                )
        st.markdown("---")
        _bundle_export(s)


def _render_ratios(s: _SectionState) -> None:
    """Ratios section: bank/insurer KPI blocks or the generic ratios table."""
    ctx, idcode, years = s.ctx, s.idcode, s.years
    _ifrs_status_banner(s)
    if s.is_bank or s.is_insurer:
        kpi_rows, kpi_title, kpi_note = _kpi_block(s)
        if not kpi_rows:
            st.info("Not enough line-item data to compute sector KPIs for this company.")
        else:
            df = _kpi_display_frame(kpi_rows, years)
            st.subheader(kpi_title)
            st.dataframe(df, use_container_width=True, hide_index=True,
                         height=min(700, 60 + 35 * len(df)))
            st.caption(kpi_note)
            render_reportal_pdf_caption(ctx.db_path, idcode, list(years))
            st.markdown("---")
            _bundle_export(s)
    else:
        df = _ratios_frame(s)
        # Grouped display (Margins / Returns / Leverage / Liquidity & working
        # capital / Turnover / Cash flow) mirroring
        # the IS/BS layout; the flat `df` is kept for the export below.
        st.caption(
            "Money rows in **GEL thousands** unless noted · hover a metric "
            "name for its unit / definition · year headers link to the "
            "audited annual PDF."
        )
        render_grouped_ratios(df, list(years), db_path=ctx.db_path, idcode=idcode)
        st.markdown("---")
        _bundle_export(s)


def _kpi_nav(target: str) -> None:
    """KPI-card click-through: stage the section switch for the next run.

    ``on_click`` callbacks run before the next script run (Sprint-26-safe), and
    the top-of-render sync in ``render`` copies ``single_section`` into the
    segmented-control widget key before that widget instantiates.
    """
    st.session_state["single_section"] = target


def _render_tearsheet(
    ctx: ViewContext,
    idcode: str,
    company_name: str,
    years: list[int],
    partners: list[dict],
    is_bank: bool,
    is_insurer: bool,
    basis: str = "Consolidated",
) -> None:
    """Summary 'tearsheet': curated description, headline KPI cards, ownership pie."""
    # --- Curated company description (when present) ---
    _desc_row = company_description(ctx.db_path, idcode)
    if _desc_row and _desc_row.get("description"):
        _src_links = ""
        try:
            _sources = json.loads(_desc_row.get("sources") or "[]")
            if _sources:
                _src_links = (
                    " · "
                    + " · ".join(
                        f'<a href="{u}" target="_blank" rel="noopener" style="color:#888;">src {i+1}</a>'
                        for i, u in enumerate(_sources[:5])
                    )
                )
        except (ValueError, TypeError):
            pass
        _updated = _desc_row.get("updated_at") or ""
        _sector = _desc_row.get("sector") or ""
        _sub_sector = _desc_row.get("sub_sector") or ""
        _chip_parts: list[str] = []
        if _sector:
            _chip_parts.append(
                f'<span style="display:inline-block;padding:2px 8px;margin-right:6px;'
                f'background:{_BRAND_NAVY};color:#fff;border-radius:10px;font-size:11px;'
                f'font-weight:600;letter-spacing:0.3px;text-transform:uppercase;">'
                f'{_sector}</span>'
            )
        if _sub_sector:
            _chip_parts.append(
                f'<span style="display:inline-block;padding:2px 8px;margin-right:6px;'
                f'background:#fff;color:{_BRAND_NAVY};border:1px solid {_BRAND_NAVY};'
                f'border-radius:10px;font-size:11px;font-weight:600;letter-spacing:0.3px;'
                f'text-transform:uppercase;">{_sub_sector}</span>'
            )
        _sector_chip = "".join(_chip_parts) + "<br/>" if _chip_parts else ""
        st.markdown(
            f'<div style="padding:10px 14px;margin:6px 0;border-left:3px solid {_BRAND_NAVY};'
            f'background:rgba(17,58,63,0.04);border-radius:4px;font-size:14px;line-height:1.5;">'
            f'{_sector_chip}'
            f'<span style="color:#444;">{_desc_row["description"]}</span>'
            f'<span style="color:#999;font-size:12px;display:block;margin-top:4px;">'
            f'_curated {_updated}{_src_links}_</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # --- Headline KPI cards from the precomputed metrics_panel (canonical and
    # correct across normal / bank / insurer layouts; money is absolute GEL,
    # margins / returns are decimals). ---
    mt = metrics_table(
        ctx.db_path,
        panel_table=("metrics_panel_individual" if basis == "Individual"
                     else "metrics_panel"),
    )
    crow = None
    try:
        _sub = mt.xs(idcode, level="IdCode")
        crow = _sub if not _sub.empty else None
    except (KeyError, TypeError):
        crow = None

    avail = [y for y in years if crow is not None and y in crow.index]
    latest = max(avail) if avail else None
    prev = max((y for y in avail if y < latest), default=None) if latest is not None else None

    def _v(col, year):
        if crow is None or year is None or col not in crow.columns:
            return None
        try:
            val = crow.loc[year, col]
        except KeyError:
            return None
        if val is None or pd.isna(val):
            return None
        return float(val)

    # Shared compact-₾ formatter (honors the global Decimal-precision setting).
    from lib.format import fmt_money_compact as _money

    def _delta(col, kind):
        cur, pv = _v(col, latest), _v(col, prev)
        if cur is None or pv is None:
            return None
        if kind == "money":
            if pv == 0:
                return None
            pct = (cur - pv) / abs(pv) * 100.0
            return None if abs(pct) > 999 else f"{pct:+.1f}% YoY"
        if kind == "pct":
            return f"{(cur - pv) * 100:+.1f}pp"
        return None

    # Banks / insurers don't carry a meaningful EBITDA / ROIC / Net-debt-to-EBITDA
    # (those panel columns are garbage for them), so show a returns-on-capital
    # set instead. Each spec is (label, metrics_panel column, kind, section the
    # card click-throughs to).
    if is_bank or is_insurer:
        specs = [
            ("Revenue", "Revenue", "money", "Income Statement"),
            ("Net profit", "NetProfit", "money", "Income Statement"),
            ("Total assets", "TotalAssets", "money", "Balance Sheet"),
            ("Total equity", "TotalEquity", "money", "Balance Sheet"),
            ("ROE", "ROE", "pct", "Ratios"),
            ("ROA", "ROA", "pct", "Ratios"),
        ]
    else:
        specs = [
            ("Revenue", "Revenue", "money", "Income Statement"),
            ("EBITDA", "EBITDA", "money", "Income Statement"),
            ("Net profit", "NetProfit", "money", "Income Statement"),
            ("Total assets", "TotalAssets", "money", "Balance Sheet"),
            ("EBITDA margin", "EBITDAMargin", "pct", "Ratios"),
            ("Net margin", "NetMargin", "pct", "Ratios"),
            ("ROIC", "ROIC", "pct", "Ratios"),
            ("Net debt / EBITDA", "NetDebtToEBITDA", "ratio", "Ratios"),
        ]

    # Each card: (label, value_str, delta_str|None, delta_color, target_section)
    cards: list[tuple] = []
    for _label, _col, _kind, _target in specs:
        _val = _v(_col, latest)
        if _val is None:
            continue
        if _kind == "money":
            cards.append((_label, _money(_val), _delta(_col, "money"), "normal", _target))
        elif _kind == "pct":
            from lib.format import fmt_pct_signed

            # KPI tile needs a visible zero (blank would look broken).
            cards.append((_label, fmt_pct_signed(_val) or "0.0%", _delta(_col, "pct"),
                          "normal", _target))
        else:  # ratio (Net debt / EBITDA) — inverse delta: rising leverage is bad
            _pv_ratio = _v(_col, prev)
            _dlt_ratio = (
                f"{_val - _pv_ratio:+.1f}× YoY" if _pv_ratio is not None else None
            )
            cards.append((_label, f"{_val:.1f}×", _dlt_ratio, "inverse", _target))

    # --- Cash-flow cards (summary CF rows; FCF suppressed for banks/insurers
    # whose investing flows are securities/lending, not capex) ---
    fcf_card_added = False
    if latest is not None:
        cf_secs = _cf_sections_cache(
            ctx.db_path, idcode, tuple(years),
            include_fcf=not (is_bank or is_insurer),
            table=("financial_data_individual" if basis == "Individual"
                   else "financial_data"),
        )

        def _cf_total(prefix: str) -> dict:
            for sec in cf_secs:
                if sec["label"].startswith(prefix):
                    return sec["total"]
            return {}

        ocf_by_year = _cf_total("Net Cash from Operating")
        fcf_by_year = _cf_total("Free Cash Flow")

        def _yoy_money(by_year: dict):
            cur, pv = by_year.get(latest), by_year.get(prev)
            if cur is None or not pv:
                return None
            chg = (cur - pv) / abs(pv) * 100.0
            return None if abs(chg) > 999 else f"{chg:+.1f}% YoY"

        if ocf_by_year.get(latest):
            cards.append(("Operating cash flow", _money(ocf_by_year[latest]),
                          _yoy_money(ocf_by_year), "normal", "Cash Flow"))
        if fcf_by_year.get(latest) is not None and any(fcf_by_year.values()):
            cards.append(("Free cash flow*", _money(fcf_by_year[latest]),
                          _yoy_money(fcf_by_year), "normal", "Cash Flow"))
            fcf_card_added = True
        # Cash conversion = OCF / EBITDA (EBITDA is NULL for banks/insurers,
        # so the card self-suppresses there).
        _ebitda_cur, _ocf_cur = _v("EBITDA", latest), ocf_by_year.get(latest)
        if _ebitda_cur and _ebitda_cur > 0 and _ocf_cur:
            _conv = _ocf_cur / _ebitda_cur
            _ebitda_pv, _ocf_pv = _v("EBITDA", prev), ocf_by_year.get(prev)
            _conv_delta = (
                f"{(_conv - _ocf_pv / _ebitda_pv) * 100:+.1f}pp"
                if (_ebitda_pv and _ebitda_pv > 0 and _ocf_pv) else None
            )
            cards.append(("Cash conversion (OCF/EBITDA)", f"{_conv * 100:.0f}%",
                          _conv_delta, "normal", "Cash Flow"))

    # --- Dividends card (SOCE equity_movements; covered year with no dividend
    # row = declared zero, shown as ₾0 — distinct from "no SOCE data"). ---
    _div_info = _dividends_cache(ctx.db_path, idcode)
    _div_by_year = _div_info.get("dividends", {})
    _div_years = sorted(y for y in _div_info.get("covered", set()) if y in years)
    if _div_years:
        _dy = _div_years[-1]
        _dval = abs(_div_by_year.get(_dy, 0.0))
        _dprev_y = _div_years[-2] if len(_div_years) > 1 else None
        _ddelta = None
        if _dprev_y is not None:
            _dpv = abs(_div_by_year.get(_dprev_y, 0.0))
            if _dpv:
                _chg = (_dval - _dpv) / _dpv * 100.0
                _ddelta = None if abs(_chg) > 999 else f"{_chg:+.1f}% YoY"
        _dlabel = "Dividends declared" if _dy == latest else f"Dividends declared (FY{_dy})"
        cards.append((_dlabel, _money(_dval) if _dval else "₾0", _ddelta, "normal", "Ratios"))

    if cards and latest is not None:
        st.markdown(f"##### Key metrics · FY{latest}")
        # Full-card click-through: a transparent st.button overlays each tile
        # (absolutely positioned → adds no height) and jumps to the section
        # where the metric's detail lives; help= doubles as the hover hint.
        st.markdown(
            f"""
            <style>
            [class*="st-key-fd_kpicard_"] {{ position: relative; }}
            /* Streamlit's stElementContainer is position:relative itself, so it
               (not the inner stButton div) must become the absolute overlay for
               inset:0 to resolve against the card. Every layer below it — the
               stButton div, the help= tooltip spans, the button — just fills. */
            [class*="st-key-fd_kpicard_"]
                div[data-testid="stElementContainer"]:has(div[data-testid="stButton"]) {{
                position: absolute; inset: 0; z-index: 2; margin: 0;
                /* beat Streamlit's inline pixel width so inset controls both edges */
                width: auto !important;
            }}
            [class*="st-key-fd_kpicard_"] div[data-testid="stButton"],
            [class*="st-key-fd_kpicard_"] div[data-testid="stButton"] > div,
            [class*="st-key-fd_kpicard_"] div[data-testid="stButton"] span,
            [class*="st-key-fd_kpicard_"] div[data-testid="stButton"] button {{
                display: block; width: 100% !important; height: 100% !important;
                min-height: 0; position: static;
            }}
            [class*="st-key-fd_kpicard_"] div[data-testid="stButton"] button {{
                opacity: 0; cursor: pointer;
            }}
            [class*="st-key-fd_kpicard_"]:hover div[data-testid="stMetric"] {{
                border-color: {_BRAND_NAVY};
                box-shadow: 0 1px 6px rgba(17, 58, 63, 0.18);
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
        for i in range(0, len(cards), 4):
            row_cards = cards[i:i + 4]
            row_cols = st.columns(4)
            for j, (col, (lbl, val, dlt, dcolor, target)) in enumerate(zip(row_cols, row_cards)):
                # height="stretch" on container + metric keeps every tile in a
                # row the same height whether or not it carries a YoY delta
                # (a whitespace-delta spacer no longer works: st.metric dedents
                # a whitespace-only delta to "" and drops the delta block).
                with col, st.container(key=f"fd_kpicard_{i + j}", height="stretch"):
                    st.metric(lbl, val, dlt, delta_color=dcolor, border=True,
                              height="stretch")
                    st.button(
                        f"Open {target}",
                        key=f"fd_kpibtn_{i + j}",
                        help=f"Open {target}",
                        on_click=_kpi_nav,
                        args=(target,),
                    )
        if fcf_card_added:
            st.caption(
                "\\* Free cash flow = OCF − net investing outflow (the filings "
                "carry no standalone capex line)."
            )
    else:
        st.caption("No headline metrics available for this company in the selected years.")

    # --- Dividend history line (last 3 covered years from the SOCE filings) ---
    if _div_years:
        _last3 = _div_years[-3:]
        _parts = [
            f"FY{y} {_money(abs(_div_by_year[y]))}" if _div_by_year.get(y) else f"FY{y} ₾0"
            for y in _last3
        ]
        _tot3 = sum(abs(_div_by_year.get(y, 0.0)) for y in _last3)
        _tail = f" — {len(_last3)}-yr total {_money(_tot3)}" if len(_last3) > 1 and _tot3 else ""
        st.caption(
            ":material/payments: **Dividends declared** (per SOCE filings): "
            + " · ".join(_parts) + _tail
        )

    # --- Ownership breakdown pie (current shareholders by registered share) ---
    shareholders = [
        (p["name"], float(p.get("share") or 0))
        for p in partners
        if not p.get("ex") and (p.get("share") or 0) > 0
    ]
    st.markdown("##### Ownership breakdown")
    if shareholders:
        shareholders.sort(key=lambda t: t[1], reverse=True)
        labels = [n for n, _ in shareholders]
        values = [s for _, s in shareholders]
        total_share = sum(values)
        if total_share < 99.5:
            labels.append("Undisclosed / other")
            values.append(round(100.0 - total_share, 2))
        import plotly.graph_objects as go
        fig = go.Figure(
            go.Pie(
                labels=labels, values=values, hole=0.55, sort=False,
                textinfo="percent", textposition="inside",
                hovertemplate="%{label}: %{value:.1f}%<extra></extra>",
            )
        )
        chart_theme(fig)
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="v", x=1.0, y=0.5))
        col_pie, col_note = st.columns([3, 2])
        with col_pie:
            st.plotly_chart(fig, use_container_width=True)
        with col_note:
            st.caption(
                "Share of registered capital by current shareholder "
                "(former holders excluded). Source: companyinfo.ge. "
                "See the **Ownership** section for directors and drill-throughs."
            )
    else:
        st.caption("_No current shareholder records available from companyinfo.ge._")


def _render_group_structure(ctx: ViewContext, idcode: str) -> None:
    """Parent / subsidiary block from the companyinfo.ge ownership graph.

    Shows the company's corporate parent(s) and the subsidiaries that file
    separately, each click-through when it's in our universe, plus a
    consolidation note. Rendered even when this company's OWN companyinfo detail
    is missing (it may still be a parent of others). Silently no-ops when there
    are no corporate edges or the ownership_edges table is absent.
    """
    edges = _ownership_edges_cache(ctx.db_path)
    if not edges:
        return
    _consol_ids = _consolidated_idcodes_cache(ctx.db_path)
    all_parents = _ownership.parents_of(idcode, edges)
    kids = [e for e in _ownership.children_of(idcode, edges)
            if e["is_internal"] and e["child"] in ctx.idcode_to_label]
    if not all_parents and not kids:
        return

    def _nav(target: str) -> None:
        # on_click callback → runs before the next script run (Sprint-26-safe).
        st.session_state["mode"] = "Single Company"
        st.session_state["_pending_single_pick"] = ctx.idcode_to_label[target]
        st.query_params["mode"] = "single"
        st.query_params["id"] = target

    st.markdown("**Group structure**")
    st.caption(
        "Corporate ownership from companyinfo.ge (current registry snapshot). "
        "Offshore / holding layers may be incomplete — treat a missing link as "
        "_unknown_, not _none_."
    )

    if all_parents:
        for e in all_parents:
            controlling = (e.get("share") or 0) > _ownership.CONTROL_THRESHOLD
            nm = e.get("parent_name") or ctx.idcode_to_label.get(e["parent"], e["parent"])
            c_info, c_btn = st.columns([7, 3])
            with c_info:
                role = "Parent" if controlling else "Shareholder"
                line = f"**{nm}** — {role} · {e['share']:.2f}%"
                if not e["is_internal"]:
                    line += "  ·  _does not file with us_"
                st.markdown(line)
                if controlling and e["is_internal"]:
                    if _consol_parent_of(idcode) == e["parent"]:
                        st.caption(":material/verified: Verified — this parent's audited "
                                   "financials consolidate this entity.")
                    elif e["parent"] in _consol_ids:
                        st.caption(":material/account_balance: This parent files on a "
                                   "**consolidated** basis, so its figures already "
                                   "include this entity.")
                    else:
                        st.caption(":material/info: This parent files **standalone**, so "
                                   "this entity is likely reported separately (not "
                                   "consolidated into it).")
            with c_btn:
                if e["is_internal"] and e["parent"] in ctx.idcode_to_label:
                    st.button("Open parent →", key=safe_key("grp_par", e["parent"]),
                              on_click=_nav, args=(e["parent"],),
                              use_container_width=True)

    if kids:
        st.markdown(f"**Subsidiaries that file separately ({len(kids)})**")
        st.caption("This entity's consolidated financials may already include these; the "
                   "Sector view de-dups known groups to avoid double-counting.")
        for e in kids[:20]:
            nm = ctx.idcode_to_label.get(e["child"], e["child"])
            c_info, c_btn = st.columns([7, 3])
            with c_info:
                st.markdown(f"{nm} · {e['share']:.2f}%")
            with c_btn:
                st.button("Open →", key=safe_key("grp_kid", e["child"]),
                          on_click=_nav, args=(e["child"],),
                          use_container_width=True)
        if len(kids) > 20:
            st.caption(f"…and {len(kids) - 20} more.")

    st.divider()


def _render_ownership(
    ctx: ViewContext,
    idcode: str,
    detail: dict | None,
    partners: list[dict],
    mgmt: list[dict],
    info_url: str,
) -> None:
    """Full ownership & directors panel (was an inline expander; now a section)."""
    _render_group_structure(ctx, idcode)
    if not detail:
        st.caption(
            f"_Ownership data unavailable from companyinfo.ge for this IdCode._ "
            f"[Try companyinfo.ge directly ↗]({info_url})"
        )
        return

    corp = detail.get("corporation", {}) or {}
    legal = detail.get("legalFormEn") or detail.get("legalFormKa") or ""
    reg = (corp.get("registrationDate") or {}).get("date", "")
    reg_year = reg[:4] if reg else ""
    email = corp.get("email") or ""
    header_bits = [b for b in [legal, f"reg. {reg_year}" if reg_year else "", email] if b]
    if header_bits:
        st.caption("  ·  ".join(header_bits) + f"  ·  [companyinfo.ge ↗]({info_url})")

    st.caption(
        ":material/lightbulb: Use **Open full profile** next to any person to see their "
        "share-weighted holdings across companies — and jump into those financials."
    )

    def _open_person_profile(person_id):
        st.session_state["_open_person"] = person_id
        st.rerun()

    def _open_company_direct(company_idcode):
        st.session_state["mode"] = "Single Company"
        st.session_state["_pending_single_pick"] = ctx.idcode_to_label[company_idcode]
        st.query_params["mode"] = "single"
        st.query_params["id"] = company_idcode
        st.rerun()

    if partners:
        st.markdown("**Partners / Shareholders**")
        for _i, p in enumerate(partners):
            col_info, col_btn = st.columns([7, 3])
            with col_info:
                if p.get("is_company"):
                    _badge = "  ·  _company_"
                elif p.get("is_individual_entrepreneur"):
                    _badge = "  ·  _individual entrepreneur_"
                else:
                    _badge = ""
                _nm = p["name"] + _badge
                _meta = f"{p['role_en']}  ·  {p['share']:.2f}%"
                if p["ex"]:
                    _meta += "  ·  former"
                st.markdown(
                    f"**{_nm}**<br><span style='font-size:12px;color:#587578'>{_meta}</span>",
                    unsafe_allow_html=True,
                )
            with col_btn:
                _bkey = safe_key("own_partner", f"{_i}_{p.get('personId')}_{p.get('id_number')}")
                if p.get("is_company"):
                    if p.get("company_idcode") in ctx.idcode_to_label:
                        if st.button(":material/open_in_new: Open company", key=_bkey, use_container_width=True):
                            _open_company_direct(p["company_idcode"])
                    else:
                        st.caption("_not in our DB_")
                elif p.get("personId") is not None:
                    if st.button(":material/badge: Open full profile", key=_bkey, use_container_width=True):
                        _open_person_profile(p["personId"])
            st.divider()
    else:
        st.caption("_No non-zero shareholder records found._")

    active_mgmt = [m for m in mgmt if not m["ex"]]
    ex_mgmt = [m for m in mgmt if m["ex"]]
    if active_mgmt:
        st.markdown("**Active directors & board**")
        for _i, m in enumerate(active_mgmt):
            col_info, col_btn = st.columns([7, 3])
            with col_info:
                st.markdown(
                    f"**{m['name']}**<br><span style='font-size:12px;color:#587578'>{m['role_en']}</span>",
                    unsafe_allow_html=True,
                )
            with col_btn:
                if m.get("personId") is not None:
                    _bkey = safe_key("own_mgmt", f"{_i}_{m.get('personId')}_{m.get('id_number')}")
                    if st.button(":material/badge: Open full profile", key=_bkey, use_container_width=True):
                        _open_person_profile(m["personId"])
            st.divider()

    if ex_mgmt:
        with st.expander(f"Show {len(ex_mgmt)} former director(s) / board member(s)"):
            ex_df = pd.DataFrame([
                {
                    "Name": m["name"],
                    "Role": m["role_en"],
                    "ID number": m["id_number"],
                    "Date": m["date"] or "",
                }
                for m in ex_mgmt
            ])
            st.dataframe(ex_df, use_container_width=True, hide_index=True)

    # Hint to look up a partner that's itself a company (excluding
    # individual-entrepreneur partners — they're people, opened via the Person
    # Profile button above, not company drill-throughs).
    partner_companies = [
        p for p in partners
        if p.get("is_company") and not p.get("is_individual_entrepreneur")
    ]
    if partner_companies:
        lines = ["**Partner companies you can drill into:**"]
        for p in partner_companies:
            code = p["id_number"]
            if code and code in ctx.idcode_to_label:
                lines.append(f"- {p['name']} (`{code}`) — available in this dashboard")
            elif code:
                lines.append(f"- {p['name']} (`{code}`) — not in our DB")
        if len(lines) > 1:
            st.markdown("\n".join(lines))

    st.caption(
        "Source: [companyinfo.ge](https://companyinfo.ge) via their public API. "
        f"[Full profile ↗]({info_url})"
    )
