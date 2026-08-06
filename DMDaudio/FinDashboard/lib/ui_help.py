"""Guided "How to use" tour — a step-by-step feature walkthrough dialog.

Follows the app's trigger-flag dialog pattern (see lib/ui_chips): a button
calls :func:`request_help_tour` (sets ``_open_help``), and app.py pops the
flag and calls :func:`help_dialog`. While the dialog is open, Streamlit
re-runs only the dialog body on internal interactions, so the Back/Next
``on_click`` callbacks (which run before that re-run) advance ``_help_step``
without ever closing it; the Done / jump buttons call ``st.rerun()`` which does.

``TOUR_STEPS`` is pure data so tests can validate it without a Streamlit run.
"""
from __future__ import annotations

import streamlit as st

# Each step: icon (material shortcode), title, markdown body, and optional
# ``jumps`` — (mode, button label) pairs that navigate there and close the tour.
# Modes must exist in lib.ui.MODES (guarded by tests/test_ui_help.py).
_ALL_TOUR_STEPS: tuple[dict, ...] = (
    {
        "icon": ":material/waving_hand:",
        "title": "Welcome to Georgia Financials",
        "body": (
            "Audited annual financials for **9,000+ Georgian companies**, compiled "
            "from public filings — reportal.ge statements, the insurance regulator's "
            "returns, and Geostat macro data.\n\n"
            "- **Income statements, balance sheets, cash flows and ratios**, with "
            "multi-year history per company.\n"
            "- All money figures are in **GEL thousands** unless labelled otherwise.\n"
            "- Move between features with the **tabs in the dark top bar** — the "
            "next steps walk through each one."
        ),
    },
    {
        "icon": ":material/search:",
        "title": "Find anything, fast",
        "body": (
            "- The **search pill in the top bar** opens the command palette — or press "
            "**/** or **Ctrl-K** (⌘-K on Mac) from any page.\n"
            "- Search by **company name or IdCode** (tax number); your saved comp sets "
            "show up in the results too.\n"
            "- **Home** keeps your **recently viewed** companies and one-click "
            "comp-set shortcuts.\n"
            "- The URL tracks what you're viewing, so any page can be **shared as a link**."
        ),
        "jumps": (("Home", "Open Home"),),
    },
    {
        "icon": ":material/apartment:",
        "title": "Company — the full picture",
        "body": (
            "Open any company for:\n"
            "- A **Tearsheet** of headline KPIs, then **Income Statement · Balance "
            "Sheet · Cash Flow · Ratios · Ownership** via the on-page section tabs.\n"
            "- Click a bold subtotal row to **expand its underlying line items**; the "
            "**CAGR** column summarises each line's trend.\n"
            "- The toolbar sets the **year range** and an optional **IFRS 16 reversal** "
            "(reclassify lease costs — an explainer sits under the statement).\n"
            "- **Year headers link to the original PDF filing** on reportal.ge.\n"
            "- **Ownership** lists shareholders and management — click a person to see "
            "their full portfolio.\n"
            "- Every statement exports to **Excel / CSV**."
        ),
        "jumps": (("Single Company", "Open Company"),),
    },
    {
        "icon": ":material/compare_arrows:",
        "title": "Compare — benchmark a peer set",
        "body": (
            "- Pick **two or more companies** (or bulk-paste a list of IdCodes).\n"
            "- **Side-by-side** — statements and ratios across companies for one year, "
            "with common-size (%) and peer mean/median options.\n"
            "- **Aggregate** — treats the basket as one company: summed by-year table, "
            "chart, and each company's **contribution**.\n"
            "- **Save the basket as a comp set** to reload in one click — from Home, "
            "the search palette, or Compare itself.\n"
            "- See each company's **percentile within its sector**, and export everything."
        ),
        "jumps": (("Compare", "Open Compare"),),
    },
    {
        "icon": ":material/donut_small:",
        "title": "Sectors — the industry lens",
        "body": (
            "- **Sectors** aggregates entire sectors or sub-sectors — size, growth, "
            "profitability, and share of GDP.\n"
            "- Filter down to **sub-sectors** to compare narrower peer groups.\n"
            "- **Overviews** hosts curated sector deep-dives, including the "
            "**Insurance** dashboard built on the regulator's premium & claims data."
        ),
        "jumps": (
            ("Sectoral Data", "Open Sectors"),
            ("Sector Overviews", "Open Overviews"),
        ),
    },
    {
        "icon": ":material/public:",
        "title": "Macro — Georgia's economy in one place",
        "body": (
            "- **GDP, labour, external trade, tourism, remittances and prices** from "
            "Geostat and NBG public data — 30 datasets, updated with each refresh.\n"
            "- Tabs mirror the questions: **Overview** KPIs, **GDP** structure and "
            "growth, **Labour** wages and unemployment, **External** trade partners "
            "and an inbound-tourism map, **Prices** inflation and the policy rate.\n"
            "- Company pages stay micro; this is the macro backdrop they sit against."
        ),
        "jumps": (("Macro", "Open Macro"),),
    },
    {
        "icon": ":material/filter_alt:",
        "title": "Screener — filter the whole universe",
        "body": (
            "- Restrict by **sector / sub-sector** and **year scope**, then stack "
            "metric filters on top.\n"
            "- **Choose your columns** — any metric from revenue and margins to "
            "leverage and growth rates.\n"
            "- Sort by any column, **save filter presets** for reuse, and export the "
            "result list."
        ),
        "jumps": (("Screener", "Open Screener"),),
    },
    {
        "icon": ":material/group:",
        "title": "Owners — the register the other way round",
        "body": (
            "Every other page starts from a company; **Owners** starts from the holder.\n"
            "- Owners **ranked by attributable portfolio** — Σ (their stake % × that "
            "company's latest filed figure) — switchable between revenue, net profit, "
            "assets, cash and equity.\n"
            "- **Search the whole register** by name or personal ID, then open anyone's "
            "portfolio: attributable KPIs, a breakdown chart, and every company they're "
            "attached to.\n"
            "- Stakes come from the **companyinfo.ge** registry, so holdings behind a "
            "nominee are understated, and holders with no Georgian personal ID on file "
            "(corporate, state or foreign) are badged rather than guessed at."
        ),
        "jumps": (("Owners", "Open Owners"),),
    },
    {
        "icon": ":material/lightbulb:",
        "title": "Good to know",
        "body": (
            "- **Settings** (top-right) — decimal precision, plus a **Refresh data** "
            "button that re-checks for a newer database.\n"
            "- **Ask Claude** — the sidebar chat answers data questions in plain "
            "language (where enabled).\n"
            "- **Use the data in your own Claude** — add the platform's **MCP "
            "connector** to claude.ai, Claude Desktop or Claude Code; setup "
            "instructions are at the bottom of **Home**.\n"
            "- Figures are compiled from public filings **as-is** — see *Data sources "
            "& methodology* under the nav bar, and verify important numbers against "
            "the linked original filings.\n"
            "- Reopen this tour anytime from the **Guide** button in the top bar."
        ),
    },
)

# The live tour: only steps whose jump targets are actually in the nav. A mode
# gated off (e.g. Macro while it's in development, hidden in production) drops
# its step here automatically, so the tour never advertises a hidden page.
from lib.ui import MODES as _MODES  # noqa: E402  (after the data literal, by design)

TOUR_STEPS: tuple[dict, ...] = tuple(
    step
    for step in _ALL_TOUR_STEPS
    if all(mode in _MODES for mode, _ in (step.get("jumps") or ()))
)


def request_help_tour() -> None:
    """Flag the tour to open (from step 1) on app.py's next dialog-wiring pass.

    Callers rendering AFTER that pass (e.g. a view body) must follow with
    ``st.rerun()``; the top-bar button renders before it, so it doesn't.
    """
    st.session_state["_open_help"] = True
    st.session_state["_help_step"] = 0


def _bump_step(delta: int) -> None:
    """Back/Next ``on_click`` callback — runs before the dialog re-renders."""
    cur = int(st.session_state.get("_help_step", 0))
    st.session_state["_help_step"] = max(0, min(len(TOUR_STEPS) - 1, cur + delta))


@st.dialog("How to use Georgia Financials", width="large")
def help_dialog() -> None:
    """Render the walkthrough dialog at the current ``_help_step``."""
    last = len(TOUR_STEPS) - 1
    idx = max(0, min(last, int(st.session_state.get("_help_step", 0))))
    step = TOUR_STEPS[idx]

    # Progress dots — brass for the current step, muted for the rest.
    dots = "".join(
        '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
        f'margin:0 3px;background:{"var(--fd-brass,#C8922E)" if i == idx else "rgba(128,128,128,0.35)"};">'
        "</span>"
        for i in range(len(TOUR_STEPS))
    )
    st.markdown(
        f'<div style="text-align:center;margin:0 0 10px;">{dots}'
        f'<span style="font-size:11px;color:var(--fd-muted,#5B6470);margin-left:10px;">'
        f"{idx + 1} / {len(TOUR_STEPS)}</span></div>",
        unsafe_allow_html=True,
    )

    st.markdown(f"#### {step['icon']} {step['title']}")
    st.markdown(step["body"])

    # Optional "take me there" buttons — navigate and close the dialog.
    jumps = step.get("jumps") or ()
    if jumps:
        cols = st.columns(max(3, len(jumps)))
        for i, (target_mode, label) in enumerate(jumps):
            if cols[i].button(
                label,
                key=f"help_jump_{idx}_{i}",
                icon=":material/arrow_forward:",
                use_container_width=True,
            ):
                st.session_state["mode"] = target_mode
                st.session_state["_help_step"] = 0
                st.rerun()  # full rerun → navigates and closes the dialog

    st.markdown(
        '<hr style="margin:14px 0 10px;border:none;border-top:1px solid '
        'var(--fd-hairline,rgba(20,24,31,0.10));">',
        unsafe_allow_html=True,
    )
    nav = st.columns([1.2, 3.6, 1.2])
    with nav[0]:
        st.button(
            "Back",
            key="help_back",
            disabled=idx == 0,
            on_click=_bump_step,
            args=(-1,),
            use_container_width=True,
        )
    with nav[2]:
        if idx < last:
            st.button(
                "Next",
                key="help_next",
                type="primary",
                on_click=_bump_step,
                args=(1,),
                use_container_width=True,
            )
        else:
            if st.button("Done", key="help_done", type="primary", use_container_width=True):
                st.session_state["_help_step"] = 0
                st.rerun()  # closes the dialog
