"""Brand palette, typography, and UI helper functions.

Centralizes the brand identity so changes propagate everywhere. Phase A only
defines palette + font constants and the CSS injection helper. Later phases
will add the top nav renderer, global search dialog, and URL state helpers
to this module.
"""
from __future__ import annotations

import hashlib
import re

import pandas as pd
import streamlit as st

from lib.format import fmt_k_gel, fmt_pct

# --- Palette — "Terminal" rebrand (charcoal-bar + gold variant) ----------
# Constant NAMES are kept for back-compat (importers across views, tests, and
# excel_export); their VALUES carry the current identity — graphite structure
# + gold accent on a clean cool-white body. The dark command bar is styled in
# render_top_bar; theme-aware surfaces live in lib/theme.py.
NAVY = "#222B36"       # Graphite — primary structure: headers, table thead, primary buttons
SLATE = "#5B6470"      # Ink-muted — secondary text, meta info, borders
GOLD = "#C8922E"       # Gold — accent: active tab, focus rings, subtotal tint
BURGUNDY = "#B23A48"   # Negative numbers, destructive actions (refined)

BG_OFF_WHITE = "#DDE2E9"   # Graphite-grey canvas (matches config.toml backgroundColor)
BG_SAGE = "#EFF1F4"        # Sunk surface / zebra wells
BODY_TEXT = "#16181D"      # Ink — default text color

# Legacy aliases kept for back-compat; soft brand tints.
LIGHT_TEAL = "#E1EAE8"
LIGHT_GOLD = "#F7EFDC"

# Brand gradient — graphite→teal. Used on BOTH the top command bar (render_top_bar)
# and the Home search hero (views/home.py) so the header "fits" the hero design.
# Canonical value: keep both surfaces referencing this constant to prevent drift.
HERO_GRADIENT = f"linear-gradient(135deg, {NAVY} 0%, #1a4d52 100%)"

# --- Typography ----------------------------------------------------------
FONT_UI = "'Inter','Segoe UI',system-ui,sans-serif"
FONT_NUMERIC = "'IBM Plex Mono','SF Mono','Consolas','Menlo','Roboto Mono',monospace"

# --- Statement subtotal "bar" role colors --------------------------------
# Full-width colored bar rows (white bold text) are driven by a per-section
# ``"bar"`` role. The orchestrator fine-tunes the bar-vs-bold split in the
# browser, so these are kept as named constants for easy tweaking. Each role
# maps to a background color used by ``style_statement`` for bar rows.
#
#   income   — green   : top-of-statement income subtotals (e.g. Net interest
#                         income, Revenue, Gross profit, Total Equity)
#   total    — blue    : structural totals (e.g. Operating income, EBIT/PBT,
#                         Total Assets, Financing CF)
#   cost     — gray    : cost/contra totals (e.g. COGS, OpEx totals, Total
#                         Liabilities, Investing CF)
#   net      — d.green : the bottom line (Profit / Net Profit / Cash at end)
#   adjusted — orange  : "Profit adjusted for one-off items" (bank one-off line)
BAR_INCOME = "#0f6e57"     # green
BAR_TOTAL = "#1a4f86"      # blue
BAR_COST = "#4a4a48"       # gray
BAR_NET = "#2f5d12"        # dark green
BAR_ADJUSTED = "#c4631f"   # orange

# role -> background color lookup used by style_statement.
BAR_ROLE_COLORS: dict[str, str] = {
    "income": BAR_INCOME,
    "total": BAR_TOTAL,
    "cost": BAR_COST,
    "net": BAR_NET,
    "adjusted": BAR_ADJUSTED,
}


def safe_key(prefix: str, val: str) -> str:
    """Stable ASCII-safe widget key from an arbitrary (possibly Unicode) string.

    Unicode in widget keys triggered Streamlit's `Bad message format / SessionInfo
    before initialized` frontend error in some browsers. Hashing the value to
    a short hex digest sidesteps it.
    """
    h = hashlib.md5(val.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}_{h}"


def inject_brand_css() -> None:
    """Inject the Reportal Terminal fonts + brand CSS for the light "Paper" theme.

    Called once near the top of every run (after ``st.set_page_config``). The
    ``config.toml`` ``[theme]`` block themes stock widgets; this function:
      - loads the brand fonts (Archivo display, Inter UI, IBM Plex Mono numbers),
      - publishes the palette as ``--fd-*`` CSS variables (consumed by the custom
        HTML statement tables + future components),
      - and forces the brand heading font/colour past Streamlit's own heading CSS.

    Wave 0 is LIGHT ONLY. A dark "Terminal" mode was prototyped as a CSS overlay
    but pulled — Streamlit's ``st.dataframe`` (a canvas grid) themes off Streamlit's
    own light/dark setting and can't be re-themed from CSS, so it stayed an
    illegible white grid in dark. The ``is_dark`` branch below is dormant
    scaffolding for a future native dark-mode task; ``mode`` is pinned to "light".
    """
    from lib.theme import tokens, FONT_UI as _FU, FONT_MONO as _FM

    mode = "light"
    t = tokens(mode)
    is_dark = mode == "dark"  # always False in Wave 0; see note above

    css_vars = (
        f"--fd-canvas:{t['canvas']};--fd-surface:{t['surface']};"
        f"--fd-surface-sunk:{t['surface_sunk']};--fd-ink:{t['ink']};"
        f"--fd-muted:{t['ink_muted']};--fd-faint:{t['ink_faint']};"
        f"--fd-hairline:{t['hairline']};--fd-forest:{t['forest']};"
        f"--fd-brass:{t['brass']};--fd-positive:{t['positive']};"
        f"--fd-negative:{t['negative']};--fd-grid:{t['grid']};"
    )

    dark_overrides = ""
    if is_dark:
        dark_overrides = f"""
          html, body, [data-testid="stAppViewContainer"], .stApp,
          [data-testid="stHeader"] {{ background-color: {t['canvas']} !important; }}
          [data-testid="stSidebar"] {{ background-color: {t['surface_sunk']} !important; }}
          body, [data-testid="stMarkdownContainer"], p, span, label, li,
          [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{ color: {t['ink']}; }}
          .stTextInput input, .stNumberInput input, .stTextArea textarea,
          [data-baseweb="select"] > div, [data-baseweb="input"] > div {{
            background-color: {t['surface']} !important; color: {t['ink']} !important;
            border-color: {t['hairline']} !important;
          }}
          [data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"] {{
            background-color: {t['surface']} !important;
          }}
          /* Secondary / download buttons keep the light-config white background,
             so their labels (now light from the rule above) were invisible. Give
             them a dark surface. Primary buttons use the forest primaryColor and
             are already legible. */
          [data-testid="stBaseButton-secondary"],
          [data-testid="stBaseButton-tertiary"],
          [data-testid="stDownloadButton"] button {{
            background-color: {t['surface_raised']} !important;
            color: {t['ink']} !important;
            border-color: {t['hairline']} !important;
          }}
          [data-testid="stBaseButton-secondary"]:hover,
          [data-testid="stDownloadButton"] button:hover {{
            border-color: {t['brass']} !important;
          }}
          [data-testid="stExpander"] details {{
            background-color: {t['surface']}; border-color: {t['hairline']};
          }}
          [data-testid="stExpander"] summary {{
            background-color: {t['surface']} !important; color: {t['ink']} !important;
          }}
        """

    st.markdown(
        f"""
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
          :root {{ {css_vars} }}
          html, body, [class*="css"], .stApp {{ font-family: {_FU}; }}
          h1, h2, h3, h4, h5 {{
            font-family: 'Archivo','Segoe UI',system-ui,sans-serif !important;
            color: {t['forest']} !important;
            font-weight: 600;
            letter-spacing: -0.01em;
          }}
          code, pre, .stCode, [data-testid="stMetricValue"] {{ font-family: {_FM}; }}
          .stSidebar [data-testid="stWidgetLabel"] {{
            text-transform: uppercase;
            letter-spacing: 0.06em;
            font-size: 10px;
            color: {t['ink_muted']};
            font-weight: 600;
          }}
          /* KPI metric cards float as white surfaces on the grey canvas. */
          [data-testid="stMetric"] {{ background: {t['surface']}; border-radius: 8px; }}
          /* "Ask Claude" chat dock: rendered BEFORE the per-view controls (so it
             survives st.stop() on empty states) but shown LAST via flex order.
             The keyed container in views/chat.py marks it .st-key-ask_claude_dock. */
          section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"]
            > [data-testid="stLayoutWrapper"]:has(.st-key-ask_claude_dock) {{ order: 999; }}
          /* Sidebar group header (design-A grouping for the filter views) — a
             quiet uppercase micro-label with a trailing hairline rule. */
          .fd-sbgroup {{ display:flex; align-items:center; gap:8px; margin:14px 0 3px;
            font-size:10px; letter-spacing:0.07em; text-transform:uppercase;
            font-weight:700; color:{t['ink_faint']}; }}
          .fd-sbgroup::after {{ content:""; flex:1; height:1px; background:{t['hairline']}; }}
          /* Two-step sector picker (Sectoral Data empty state) — a sunk panel
             holding two rows of raised pills, so the taxonomy reads as one
             grouped control instead of loose text on the canvas. Selected pills
             take a brass tint rather than a solid fill: step 2 starts with EVERY
             sub-sector selected, and 18 solid-dark pills would read as a wall.
             See views/sector.py. */
          .st-key-fd_sectorpick {{ background:{t['surface_sunk']};
            border:1px solid {t['hairline']}; border-radius:12px;
            padding:14px 16px 16px; margin:10px 0 4px; }}
          /* Step header: numbered badge + label + inline hint. */
          .fd-step {{ display:flex; align-items:baseline; gap:8px; margin:0 0 9px; }}
          .fd-step-n {{ flex:none; width:19px; height:19px; border-radius:50%;
            background:{t['forest']}; color:#fff; font-size:11px; font-weight:700;
            display:inline-flex; align-items:center; justify-content:center;
            transform:translateY(2px); }}
          .fd-step-t {{ font-size:13px; font-weight:600; color:{t['ink']};
            letter-spacing:-0.005em; }}
          .fd-step-h {{ font-size:12px; color:{t['ink_muted']}; }}
          .fd-step-rule {{ height:1px; background:{t['hairline']};
            margin:14px 0 12px; }}
          /* Pills: content-width (Streamlit's stretch mode sets flex-grow:1,
             which blows the last row's pills up to fill the line), raised on the
             sunk panel, brass-tinted when selected. */
          .st-key-fd_sectorpick [data-baseweb="button-group"] {{ gap:6px !important; }}
          .st-key-fd_sectorpick button[kind="pills"],
          .st-key-fd_sectorpick button[kind="pillsActive"] {{
            flex:0 0 auto !important; min-height:30px !important;
            padding:5px 13px !important; border-radius:999px !important;
            font-size:12.5px !important; line-height:1.2 !important;
            transition:border-color .12s, background-color .12s; }}
          .st-key-fd_sectorpick button[kind="pills"] {{
            background:{t['surface']} !important;
            border:1px solid {t['hairline']} !important;
            color:{t['ink_muted']} !important; }}
          .st-key-fd_sectorpick button[kind="pills"]:hover {{
            border-color:{t['brass']} !important; color:{t['ink']} !important; }}
          .st-key-fd_sectorpick button[kind="pillsActive"] {{
            background:rgba(200,146,46,0.16) !important;
            border:1px solid {t['brass']} !important;
            color:{t['ink']} !important; font-weight:600 !important; }}
          /* Select all / Deselect all — quiet text buttons, not full-width slabs. */
          .st-key-fd_sectorpick .st-key-sectorview_browser_subs_all button,
          .st-key-fd_sectorpick .st-key-sectorview_browser_subs_none button {{
            background:transparent !important; border:none !important;
            color:{t['ink_muted']} !important; font-size:12px !important;
            padding:2px 6px !important; min-height:0 !important;
            text-decoration:underline; text-underline-offset:2px; }}
          .st-key-fd_sectorpick .st-key-sectorview_browser_subs_all button:hover,
          .st-key-fd_sectorpick .st-key-sectorview_browser_subs_none button:hover {{
            color:{t['forest']} !important; }}
          /* Continue: the one emphatic control in the panel. */
          .st-key-fd_sectorpick .st-key-sectorview_browser_go button {{
            border-radius:9px !important; padding:8px 18px !important;
            font-weight:600 !important; }}
          /* On-page section tabs (Single Company) — a segmented_control restyled
             as a Capital-IQ tab rail: ghost inactive, gold-underlined active,
             sitting on a hairline beneath the company header. */
          .st-key-fd_sectiontabs [role="radiogroup"] {{ background:transparent !important;
            border:none !important; border-bottom:1px solid {t['hairline']} !important;
            border-radius:0 !important; gap:2px !important; }}
          .st-key-fd_sectiontabs button[kind="segmented_control"],
          .st-key-fd_sectiontabs button[kind="segmented_controlActive"] {{
            background:transparent !important; border:none !important; border-radius:0 !important;
            border-bottom:2px solid transparent !important; margin-bottom:-1px !important;
            padding:9px 16px !important; font-size:14px !important; font-weight:500 !important;
            color:{t['ink_muted']} !important; }}
          .st-key-fd_sectiontabs button[kind="segmented_control"]:hover {{
            color:{t['forest']} !important; background:transparent !important; }}
          .st-key-fd_sectiontabs button[kind="segmented_controlActive"] {{
            color:{t['forest']} !important; font-weight:600 !important;
            border-bottom:2px solid {t['brass']} !important; }}
          /* Inline toolbars — a sunk strip holding popover chips right where
             they act: the Single-Company statement toolbar (Years + IFRS 16),
             the filter-view control toolbars, and Compare's peer-set toolbar
             (Companies / comp-sets / bulk-import). All share one look. */
          .st-key-fd_toolbar, .st-key-fd_toolbar_peers {{ background:{t['surface_sunk']}; border:1px solid {t['hairline']};
            border-radius:9px; padding:7px 11px; margin:12px 0 6px; }}
          .st-key-fd_toolbar [data-testid="stPopover"] button,
          .st-key-fd_toolbar_peers [data-testid="stPopover"] button {{
            background:{t['surface']} !important; border:1px solid {t['hairline']} !important;
            color:{t['ink']} !important; border-radius:8px !important; font-weight:500 !important; }}
          .st-key-fd_toolbar [data-testid="stPopover"] button:hover,
          .st-key-fd_toolbar_peers [data-testid="stPopover"] button:hover {{
            border-color:{t['brass']} !important; }}
          /* Subtle 'work in progress' strip under the nav — brass-tinted, low-key. */
          .fd-disclaimer {{ display:flex; align-items:center; gap:10px;
            margin:2px 0 6px; padding:6px 12px; border-radius:8px;
            background:rgba(200,146,46,0.08); border:1px solid rgba(200,146,46,0.30);
            font-size:12px; color:{t['ink_muted']}; }}
          .fd-disclaimer .fd-disc-badge {{ flex:none; font-size:10px; font-weight:700;
            letter-spacing:0.06em; color:#6b4d16; background:rgba(200,146,46,0.25);
            padding:2px 8px; border-radius:10px; }}
          .fd-disclaimer .fd-disc-text {{ line-height:1.4; }}
          {dark_overrides}
        </style>
        """,
        unsafe_allow_html=True,
    )


# --- Top-tabs navigation ----------------------------------------------------

# Visual order of the top tabs. Stored as a tuple so it's hashable + ordered.
# Add new modes by appending; the call site dispatches in app.py.


def _macro_enabled() -> bool:
    """The Macro page is still in development (user call, 2026-08-03): visible in
    local dev, hidden on the deployed HF Space until it's ready. HF Spaces always
    set ``SPACE_ID``, so that's the production tell; ``FINDASH_MACRO`` (a Space
    secret / env var) overrides in either direction — set it to 1 to launch the
    page in production, or to 0 to hide it locally."""
    import os

    flag = os.environ.get("FINDASH_MACRO", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    return "SPACE_ID" not in os.environ


def _build_modes() -> tuple[str, ...]:
    modes = [
        "Home",
        "Single Company",
        "Compare",
        "Sectoral Data",
        "Sector Overviews",
        "Macro",
        "Screener",
        "Owners",
    ]
    if not _macro_enabled():
        modes.remove("Macro")
    return tuple(modes)


MODES: tuple[str, ...] = _build_modes()


# Short URL-friendly slugs for each mode (used in ?mode= deep-links).
MODE_SLUGS: dict[str, str] = {
    "Home": "home",
    "Single Company": "single",
    "Compare": "compare",
    "Sectoral Data": "sector",       # slug kept as 'sector' for old bookmarks
    "Sector Overviews": "overviews",
    "Macro": "macro",
    "Screener": "screener",
    # "Owners", not "People": the register legitimately contains corporate,
    # state and foreign holders, and they belong in an ownership view.
    "Owners": "owners",
}
_SLUG_TO_MODE: dict[str, str] = {slug: mode for mode, slug in MODE_SLUGS.items()}

# Legacy URL slugs that should redirect to a current mode. Lets bookmarked
# links keep working after a rename/merge — e.g. ?mode=compset → Compare
# after the Comp-Sets-into-Compare consolidation.
_LEGACY_SLUG_REDIRECTS: dict[str, str] = {
    "compset": "Compare",
    "insurance": "Sector Overviews",  # Insurance moved into the Sector Overviews hub
}


def mode_to_slug(mode: str) -> str:
    """Map a mode display name to its URL slug; default ``home`` for unknowns."""
    return MODE_SLUGS.get(mode, "home")


def slug_to_mode(slug: str | None) -> str:
    """Map a URL slug back to its mode display name; default ``Home``.

    Honors ``_LEGACY_SLUG_REDIRECTS`` so retired slugs (e.g. ``compset``)
    land on the mode that absorbed their functionality.
    """
    if not slug:
        return "Home"
    if slug in _LEGACY_SLUG_REDIRECTS:
        return _LEGACY_SLUG_REDIRECTS[slug]
    return _SLUG_TO_MODE.get(slug, "Home")


def resolve_active_mode(candidate: str | None) -> str:
    """Validate a mode string against the known set; default to ``Home``.

    Used by callers that read ``st.session_state["mode"]`` (Phase B) or
    ``st.query_params["mode"]`` (Phase C) to coerce the raw value to a known
    mode. Case-sensitive — we match the exact canonical strings in ``MODES``.
    """
    if not candidate or candidate not in MODES:
        return "Home"
    return candidate


# Short nav labels for the compact top command bar. Display-only — the app
# still dispatches on the canonical MODES strings (and ?mode= slugs). Derived
# from MODES (same order) so a gated-off mode never renders a tab.
_ALL_NAV_SHORT_LABELS: dict[str, str] = {
    "Home": "Home",
    "Single Company": "Company",
    "Compare": "Compare",
    "Sectoral Data": "Sectors",
    "Sector Overviews": "Overviews",
    "Macro": "Macro",
    "Screener": "Screener",
    "Owners": "Owners",
}
NAV_SHORT_LABELS: dict[str, str] = {m: _ALL_NAV_SHORT_LABELS[m] for m in MODES}
_SHORT_TO_MODE: dict[str, str] = {short: mode for mode, short in NAV_SHORT_LABELS.items()}


def render_top_bar(active: str) -> tuple[str, bool]:
    """Render the persistent top command bar; return ``(chosen_mode, refresh_clicked)``.

    Capital-IQ-style TWO rows inside one slate band:
      row 1 — ``[◆ brand]  [ big centered search ]  [settings]``
      row 2 — ``[ navigation tabs ]`` (split off by a hairline).
    Replaces the old button-row ``render_top_nav`` and absorbs the global controls
    that used to clutter the sidebar (search trigger, decimal precision, refresh),
    leaving the sidebar for per-view controls only.

    - **Search pill** — an ``st.button`` restyled (via its ``.st-key-topbar_search``
      container class) to look like a search field. Clicking sets
      ``st.session_state["_open_search"]``; app.py opens the command-palette dialog.
      The "/" and ⌘/Ctrl-K shortcuts click this same button.
    - **Navigation** — a single-select ``st.segmented_control`` keyed ``nav_seg``.
      We re-seed it to ``active`` BEFORE it instantiates each run so EXTERNAL
      navigation (e.g. a company drill-through flipping the mode) keeps the
      highlight correct; a user click overrides the seed and is returned.
    - **Settings** — a ``st.popover`` holding the decimal-precision selectbox
      (key ``display_decimals``, read by the formatters) and the Refresh-data
      button. Refresh is returned as a bool so app.py keeps ownership of the
      ``_db_path`` cache-bust + rerun.
    """
    import streamlit as st  # local import keeps unit tests light

    st.markdown(
        """
        <style>
          /* Pull our bar up to the very top edge and pin it there, like a real
             app top bar (CapIQ). Streamlit reserves an empty native header
             (just its toolbar, top-right) + ~84px of body padding above the
             first element — collapse that so the slate bar owns the top. The
             native header is made transparent so no grey strip shows through;
             its toolbar menu still floats over the right edge. */
          [data-testid="stMainBlockContainer"], .block-container {
            padding-top:0.6rem !important; }
          [data-testid="stHeader"] { background:transparent !important; }
          /* Capital-IQ-style command bar: a lifted slate strip with a gold
             accent and light text, distinct from the clean white content below.
             Sticky so it stays pinned to the top while the page scrolls. */
          /* Background (graphite→teal gradient) is set from HERO_GRADIENT in a
             separate f-string below so the bar matches the Home search hero. */
          .st-key-fd_topbar { border:1px solid #35505A;
            border-radius:10px; padding:8px 18px; margin-bottom:18px;
            position:sticky; top:0.4rem; z-index:999; }
          /* Keep every bar control on ONE line — no mid-word breaks ("Setti ngs")
             when the columns get narrow; long labels truncate with an ellipsis. */
          .st-key-fd_topbar button { white-space:nowrap !important; }
          .st-key-fd_topbar button p,
          .st-key-fd_topbar button [data-testid="stMarkdownContainer"] {
            white-space:nowrap !important; overflow:hidden !important; text-overflow:ellipsis !important; }
          .fd-brandmark { display:flex; align-items:center; gap:9px; color:#FFFFFF;
            font-family:'Archivo','Segoe UI',sans-serif; white-space:nowrap; }
          .fd-brandmark .diamond { color:var(--fd-brass); font-size:18px; line-height:1; }
          .fd-brandmark .fd-brandtext { display:flex; flex-direction:column;
            line-height:1.1; overflow:hidden; }
          .fd-brandmark .fd-brandtitle { font-weight:700; font-size:16px;
            letter-spacing:-0.01em; overflow:hidden; text-overflow:ellipsis; }
          .fd-brandmark .fd-brandsub { font-weight:500; font-size:10px;
            letter-spacing:0.02em; color:rgba(255,255,255,0.62); margin-top:1px;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
          /* Search pill — the dominant CapIQ-style search field, centered in
             row 1: a dark inset on the slate bar, wide and a touch taller so it
             reads as the header's primary control. */
          .st-key-topbar_search button { justify-content:flex-start !important;
            background:#1C222B !important; border:1px solid #3A4250 !important;
            border-radius:999px !important; color:#9AA1AC !important; font-weight:400 !important;
            box-shadow:none !important; max-width:720px !important; margin:0 auto !important;
            padding-top:11px !important; padding-bottom:11px !important; }
          .st-key-topbar_search button:hover { border-color:var(--fd-brass) !important;
            color:#CFD3DA !important; }
          /* Hairline splitting row 1 (brand/search/settings) from row 2 (nav). */
          .fd-bar-sep { height:1px; background:rgba(255,255,255,0.08);
            margin:9px 0 3px; }
          /* Nav segments: ghost inactive (light grey), gold-underlined active. */
          .st-key-fd_topbar [role="radiogroup"] { background:transparent !important; border:none !important; }
          .st-key-fd_topbar button[kind="segmented_control"] {
            background:transparent !important; color:#AEB4BD !important; border-color:transparent !important;
            padding:9px 20px !important; font-size:14px !important; font-weight:500 !important; }
          .st-key-fd_topbar button[kind="segmented_control"]:hover {
            background:rgba(255,255,255,0.06) !important; color:#FFFFFF !important; }
          .st-key-fd_topbar button[kind="segmented_controlActive"] {
            background:rgba(255,255,255,0.10) !important; color:#FFFFFF !important;
            border-bottom:2px solid var(--fd-brass) !important;
            padding:9px 20px !important; font-size:14px !important; font-weight:500 !important; }
          /* Settings trigger on the dark bar. */
          .st-key-fd_topbar [data-testid="stPopover"] button {
            background:#1C222B !important; color:#CFD3DA !important; border:1px solid #3A4250 !important; }
          .st-key-fd_topbar [data-testid="stPopover"] button:hover { border-color:var(--fd-brass) !important; }
          /* Guide (how-to-use tour) trigger — same dark chip as Settings. */
          .st-key-topbar_help button {
            background:#1C222B !important; color:#CFD3DA !important;
            border:1px solid #3A4250 !important; box-shadow:none !important; }
          .st-key-topbar_help button:hover {
            border-color:var(--fd-brass) !important; color:#FFFFFF !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Command-bar background — the graphite→teal HERO_GRADIENT, so the header
    # visually matches the Home search hero. Injected separately (f-string) to
    # reuse the shared constant without escaping every brace in the block above.
    st.markdown(
        f"<style>.st-key-fd_topbar {{ background:{HERO_GRADIENT} !important; }}</style>",
        unsafe_allow_html=True,
    )

    # Render the whole bar inside a keyed container so the band CSS above can
    # target it (and so the nav/search/settings all live under .st-key-fd_topbar).
    # Capital-IQ-style TWO-ROW header: row 1 is brand + a dominant centered
    # search + settings; row 2 is the navigation tabs underneath, split off by a
    # hairline. The whole thing lives in one slate band.
    bar = st.container(key="fd_topbar")

    # --- Row 1: brand · big centered search · guide · settings -------------
    row1 = bar.columns([2.6, 5.2, 1.0, 1.4], vertical_alignment="center")

    with row1[0]:
        st.markdown(
            '<div class="fd-brandmark">'
            '<span class="diamond">◆</span>'
            '<span class="fd-brandtext">'
            '<span class="fd-brandtitle">Georgia Financials</span>'
            '<span class="fd-brandsub">Georgian market intelligence platform</span>'
            '</span></div>',
            unsafe_allow_html=True,
        )

    with row1[1]:
        if st.button(
            "Search companies, sectors, people…   /",
            icon=":material/search:",
            key="topbar_search",
            use_container_width=True,
        ):
            st.session_state["_open_search"] = True

    with row1[2]:
        # Opens the step-by-step "How to use" tour. Renders BEFORE app.py's
        # dialog-wiring pass pops the flag, so no explicit rerun is needed.
        if st.button(
            "Guide",
            icon=":material/school:",
            key="topbar_help",
            use_container_width=True,
            help="Step-by-step walkthrough of the platform's features.",
        ):
            from lib.ui_help import request_help_tour
            request_help_tour()

    refresh_clicked = False
    with row1[3]:
        with st.popover("Settings", icon=":material/tune:", use_container_width=True):
            st.selectbox(
                "Decimal precision",
                options=[0, 1, 2],
                index=0,
                key="display_decimals",
                help="Decimal places for monetary values (K GEL) and percentages across all tables.",
            )
            refresh_clicked = st.button(
                "Refresh data",
                icon=":material/refresh:",
                use_container_width=True,
                help="Clear cached financials and re-read the DB file (also re-checks the HF Dataset for a newer DB on the Space).",
            )

    # Hairline between the two rows.
    bar.markdown('<div class="fd-bar-sep"></div>', unsafe_allow_html=True)

    # --- Row 2: navigation tabs underneath ---------------------------------
    with bar:
        # An on_change callback captures a segment click into the canonical
        # ``mode`` key. Callbacks run at the START of the click's rerun — BEFORE
        # the script body re-seeds ``nav_seg`` below — so the click is recorded
        # before the seed can clobber it. The re-seed then keeps the highlight in
        # sync with EXTERNAL navigation (e.g. a company drill-through flipping the
        # mode), which doesn't fire the callback.
        def _sync_nav_to_mode() -> None:
            picked_short = st.session_state.get("nav_seg")
            if picked_short:
                st.session_state["mode"] = _SHORT_TO_MODE.get(picked_short, "Home")

        # Conditional re-seed: only when the segment disagrees with the active
        # mode (i.e. mode was changed EXTERNALLY). On a click run the callback
        # has already set mode to match the segment, so they agree and we leave
        # the widget untouched — never clobbering a fresh click.
        _desired_short = NAV_SHORT_LABELS.get(active, "Home")
        if st.session_state.get("nav_seg") != _desired_short:
            st.session_state["nav_seg"] = _desired_short
        picked = st.segmented_control(
            "Navigation",
            options=list(NAV_SHORT_LABELS.values()),
            key="nav_seg",
            selection_mode="single",
            label_visibility="collapsed",
            on_change=_sync_nav_to_mode,
        )
        chosen = _SHORT_TO_MODE.get(picked, active)

    return chosen, refresh_clicked


# Data sources shown in the disclaimer strip's "Data sources & methodology"
# disclosure. (source label, what it provides, URL).
DATA_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("reportal.ge", "Company financial statements — audited IFRS annual filings (income statement, balance sheet, cash flow).", "https://reportal.ge"),
    ("companyinfo.ge", "Ownership, shareholders, directors and legal-registry details.", "https://companyinfo.ge"),
    ("insurance.gov.ge", "Insurers' statutory 12-month returns and the premium / claims market data behind the Insurance view.", "https://insurance.gov.ge"),
    ("Geostat (geostat.ge)", "National accounts — nominal GDP, used for the macro / GDP-penetration figures.", "https://geostat.ge"),
)


def render_disclaimer_bar() -> None:
    """Render a subtle 'work in progress' strip under the nav + a collapsed
    'Data sources & methodology' disclosure.

    Deliberately low-key (a thin brass-tinted strip that scrolls away with the
    page, not the sticky nav) — visible but not in-your-face. Rendered once from
    app.py, above the active view, so it shows on every page.
    """
    st.markdown(
        '<div class="fd-disclaimer">'
        '<span class="fd-disc-badge">BETA · WIP</span>'
        '<span class="fd-disc-text">Work in progress. Figures are compiled from '
        'public filings and provided as-is for research — verify against the '
        'original filings before relying on them.</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.expander(":material/database: Data sources & methodology", expanded=False):
        st.markdown(
            "Financial data is compiled from public Georgian filings and registries "
            "(**not** proprietary feeds). Statements are read from **reportal.ge** "
            "Excel exports — this dashboard does not re-key numbers from PDFs. "
            "Values are shown in **GEL thousands** unless noted."
        )
        for name, desc, url in DATA_SOURCES:
            st.markdown(
                f'- **[{name}]({url})** — {desc}',
            )
        st.caption(
            "EBITDA / EBIT / Net profit and the standard ratios are computed by the "
            "dashboard from the reported line items; sector classification is a GCAP "
            "taxonomy. Per-year figures link to their source filing where available."
        )


# ---------------------------------------------------------------------------
# Statement table rendering (extracted from app.py in Sprint 4.3).
#
# `sections_to_dataframe` flattens IS/BS sections into a single DataFrame.
# `shared_table_styles` and `style_statement` provide the shared brand look.
# `render_statement` and `render_is_chart` are the high-level renderers wired
# up from Single Company mode.
# ---------------------------------------------------------------------------


# Section labels that belong under the "Debt Analysis" block in the Balance Sheet.
DEBT_ANALYSIS_LABELS = ("Total Debt", "Cash & Equivalents", "Net Debt")

# Column sizing. The label (col0) is now FLEXIBLE — it absorbs whatever width is
# left over after the numeric columns take their fixed widths (under
# ``table-layout:fixed``, a column with no explicit width claims the remainder),
# so long line-item names get room to breathe instead of the numeric columns
# stretching to fill. ``LABEL_MIN_WIDTH_PX`` feeds the table's ``min-width`` (with
# the numeric columns) so a narrow container scrolls horizontally (its own
# overflow wrapper) rather than crushing the labels or clipping the numbers.
# YEAR/CAGR are the *defaults*; ``style_statement`` passes a content-adaptive year
# width so the columns are only as wide as the widest number they actually carry.
LABEL_MIN_WIDTH_PX = 260
YEAR_COL_WIDTH_PX = 92
CAGR_COL_WIDTH_PX = 64


def _label_indent_px(label) -> int:
    """Hanging-indent depth (px) for a Line-Item label from its leading spaces.

    Detail rows are emitted with 4 leading spaces per level (see
    ``sections_to_dataframe``). We turn that into a left PADDING on the cell so
    wrapped continuation lines align under the first line — instead of relying on
    ``white-space:pre-wrap`` (which indents only the first visual line and leaves
    wrapped lines flush-left, the reported ragged look)."""
    if not isinstance(label, str):
        return 0
    depth = (len(label) - len(label.lstrip(" "))) // 4
    return depth * 16


def _numeric_col_width_px(df, cols, floor: int = YEAR_COL_WIDTH_PX, cap: int = 170) -> int:
    """Content-adaptive width for the numeric columns: only as wide as the widest
    formatted value they carry, so the columns don't stretch past their info.

    Measured against the SAME formatting the styler applies (``fmt_k_gel`` for
    numbers, pass-through for pre-formatted strings) at the monospace numeric
    font. Clamped to ``[floor, cap]``; ``cap`` + the horizontal-scroll wrapper keep
    even a wide bank figure fully visible."""
    maxlen = 4  # a 4-digit year header
    for c in cols:
        if c in df.columns:
            for v in df[c]:
                s = v if isinstance(v, str) else fmt_k_gel(v)
                if s:
                    maxlen = max(maxlen, len(str(s)))
    return max(floor, min(cap, int(maxlen * 7.3) + 24))


def _scroll_wrap(html: str) -> str:
    """Wrap a rendered table so it scrolls horizontally within its own container
    instead of overflowing the page when the viewport is narrower than the
    table's ``min-width`` — the page body itself never scrolls sideways."""
    return f'<div class="fd-tbl-scroll" style="overflow-x:auto;max-width:100%;">{html}</div>'


def common_size_base(sections: list[dict], statement_kind: str) -> dict[int, float]:
    """Return the per-year denominator for common-sizing a statement.

    Income statements are sized against Total Revenue; balance sheets against
    Total Assets. The lookup matches by the same label prefixes the renderers
    use, so it works for the regular IS/BS layouts and the bank BS (whose
    "TOTAL ASSETS" total carries the reported figure).

    Returns ``{year: base_value}`` with zero/missing bases preserved as 0.0 so
    the caller can render an empty cell (division would be undefined).
    """
    if statement_kind == "is":
        prefixes = ("Total Revenue",)
    else:
        prefixes = ("TOTAL ASSETS", "Total Assets")
    for s in sections:
        label = s.get("label", "")
        for pre in prefixes:
            if label.startswith(pre):
                return {int(y): float(v or 0) for y, v in s.get("total", {}).items()}
    return {}


def sections_to_dataframe(
    sections: list[dict],
    years: list[int],
    common_size: bool = False,
    base_by_year: dict[int, float] | None = None,
) -> tuple[pd.DataFrame, list[int], int | None, list[int], dict[int, str]]:
    """Flatten sections into a single DataFrame for compact rendering.

    Returns ``(df, bold_row_indices, debt_separator_row, margin_row_indices,
    bar_roles)``:
      - bold_row_indices: row indices that should render bold (the totals).
      - debt_separator_row: index of the first Debt-Analysis row (Total Debt),
        or None if the statement has no debt-analysis block.
      - margin_row_indices: row indices that carry pre-formatted % strings.
      - bar_roles: ``{row_index: role}`` for subtotal rows that opt into a
        full-width colored *bar* (white bold text) instead of plain bold. Role
        is one of ``income|total|cost|net|adjusted`` (see ``BAR_ROLE_COLORS``).
        Empty for statements that don't tag any section with ``"bar"``.

    Rules mirror the previous cell-by-cell renderer:
      - Every section emits a total row (bold by default).
      - kind in {derived_total, final_total} -> no detail rendered.
      - section_with_detail with 0 or 1 detail items -> no detail rendered
        (1-item detail would duplicate the total).
      - section_with_detail with 2+ items -> emit each as an indented row.

    New optional per-section fields (all backward-compatible — sections that
    omit them behave exactly as before):
      - ``"details_first": True`` — emit the section's detail rows BEFORE its
        subtotal row (reading order: inputs first, then the subtotal below),
        matching the bank "income statement highlights" layout. Without the
        flag, detail rows follow the total (legacy order).
      - ``"bar": <role>`` — render the section's subtotal as a full-width
        colored bar. Records ``{row_index: role}`` in the returned ``bar_roles``.
      - ``"emphasis": "line"`` — keep the row NON-bold (a faint/plain line),
        used for income detail lines that aren't true subtotals.

    Common-size mode (``common_size=True``): every numeric line is rendered as a
    percentage of the per-year base (``base_by_year`` — Revenue for IS, Total
    Assets for BS) using the same pre-formatted-percent-string path the margin
    rows use, so :func:`style_statement` renders them without re-formatting. The
    base rows themselves show 100.0%. Margin rows (already %) pass through
    unchanged. CAGR is blanked — a CAGR of percentages isn't meaningful.
    """
    base_by_year = base_by_year or {}

    from lib.format import fmt_pct_signed as _pct_str

    def _common_size_cell(value: float, year: int) -> str:
        """value / base[year] as a percent string; blank when base is 0/absent."""
        base = base_by_year.get(int(year), 0) or 0
        if not base:
            return ""
        return _pct_str(value / base)
    # CAGR over the visible year span. Computed from first non-zero year to
    # last non-zero year — gives a meaningful rate even when leading years are
    # zero (e.g. a company that started reporting mid-range). For expense lines
    # (both endpoints negative) we compound magnitudes so "growth of costs" has
    # a sensible CAGR.
    #
    # A CAGR summarises COMPOUND growth over a span, so it is "not meaningful"
    # (labelled "nmf" rather than blanked — so the reader can tell "no
    # meaningful rate" apart from "we forgot one") whenever any precondition
    # fails:
    #   • fewer than two data points / zero span — nothing to compound over
    #     (the single-year line the user flagged);
    #   • a sign flip between endpoints (loss → profit) — the ratio is negative
    #     and a fractional root is undefined;
    #   • an immaterial starting base — a near-zero first value (rounding dust
    #     that renders as a blank cell) explodes the ratio into a five-figure %
    #     describing the noise, not the trend (the "185,…" / "149,…" rows);
    #   • an absurd resulting magnitude — a belt-and-suspenders cap on the same
    #     blow-up when the tiny base clears the fraction floor but still detonates.
    # Formatted as a percent string so it composes with the margin-row path.
    NMF = "nmf"
    # Start must be at least this fraction of the series' peak magnitude, else
    # the denominator is immaterial and any rate it anchors is an artefact.
    MIN_BASE_FRACTION = 0.001  # 0.1% of the peak year
    # A genuine multi-year CAGR never approaches this; above it is a dust-base
    # blow-up, so treat as not meaningful.
    MAX_ABS_CAGR = 10.0  # 1000%/yr

    def _cagr_for(values_by_year: dict) -> str:
        # Single-year VIEW: the column is globally irrelevant, so blank every
        # cell rather than stamping a wall of "nmf". (Per-ROW "one data point in
        # a multi-year view" is still nmf — handled below.)
        if len(years) < 2:
            return ""
        non_zero = [(y, values_by_year.get(y, 0)) for y in years if values_by_year.get(y, 0)]
        # No data at all -> blank (an "nmf" beside an all-empty row is just
        # noise). Exactly one data point -> nmf (a value, but no span).
        if not non_zero:
            return ""
        if len(non_zero) < 2:
            return NMF
        start_year, start_val = non_zero[0]
        end_year, end_val = non_zero[-1]
        n = end_year - start_year
        if n <= 0:
            return NMF
        # Sign flip between endpoints (loss <-> profit) — CAGR undefined.
        if (start_val > 0) != (end_val > 0):
            return NMF
        sv = abs(start_val)
        ev = abs(end_val)
        # Immaterial starting base: the earliest non-zero value is rounding dust
        # relative to the series peak, so the rate it anchors is an artefact.
        peak = max(abs(v) for _, v in non_zero)
        if sv == 0 or sv < MIN_BASE_FRACTION * peak:
            return NMF
        try:
            r = (ev / sv) ** (1.0 / n) - 1.0
        except (ValueError, ZeroDivisionError, OverflowError):
            return NMF
        if abs(r) > MAX_ABS_CAGR:
            return NMF
        from lib.format import fmt_pct_signed

        return fmt_pct_signed(r)

    rows: list[dict] = []
    bold: list[int] = []
    margin_row_indices: list[int] = []
    bar_roles: dict[int, str] = {}
    debt_separator_row: int | None = None
    # (anchor_row, [child_rows]) for every section that emits >=2 detail rows —
    # consumed by render_statement's inline collapse/expand. Captured HERE (not
    # re-derived downstream) so it's correct for both the legacy "subtotal then
    # detail" order and the "details_first" order without any guesswork.
    collapse_groups: list[dict] = []

    def _emit_total_row(section: dict) -> int:
        """Append the section's subtotal row, recording bold / bar role.

        Returns the appended row's index (the accordion anchor)."""
        label = section["label"]
        total = section["total"]
        total_row: dict = {"Line Item": label}
        for y in years:
            raw = total.get(y, 0)
            total_row[y] = _common_size_cell(raw, y) if common_size else raw
        total_row["CAGR"] = "" if common_size else _cagr_for(total)
        rows.append(total_row)
        idx = len(rows) - 1
        # A "bar" role makes this a full-width colored bar (still counts as a
        # bold/emphasised row for layout); record its role for the styler.
        bar = section.get("bar")
        if bar in BAR_ROLE_COLORS:
            bar_roles[idx] = bar
            bold.append(idx)
        elif section.get("emphasis") != "line":
            bold.append(idx)
        return idx

    def _emit_detail_rows(section: dict) -> list[int]:
        """Append the section's indented detail rows (skipping duplicates).

        Returns ``(child_rows, other_row, rolled_rows)``:
          - ``child_rows``  — indices of the section's direct detail rows.
          - ``other_row``   — index of the "Other (N items)" rollup row, or None.
          - ``rolled_rows`` — indices of the individual items that "Other (N
            items)" aggregates, emitted (deeper-indented) right after it so the
            renderer can nest a second-level accordion under the rollup. Empty
            unless the section carries ``rolled_up`` (Operating Expenses)."""
        total = section["total"]
        detail = section.get("detail", [])
        if len(detail) <= 1:
            # 0 detail -> nothing to show; 1 detail -> duplicates total
            return [], None, []

        # Hide detail rows whose values exactly match the section total in every
        # non-zero year — these duplicate the section header (e.g. 'Net Revenue'
        # == 'Total Revenue') and add visual noise without information.
        def _row_equals_total(values_by_year: dict) -> bool:
            nonzero_years = [y for y in years if total.get(y, 0) != 0]
            if not nonzero_years:
                return False
            return all(values_by_year.get(y, 0) == total.get(y, 0) for y in nonzero_years)

        def _append(line_item: str, values: dict) -> int:
            row: dict = {"Line Item": line_item}
            for y in years:
                raw = values.get(y, 0)
                row[y] = _common_size_cell(raw, y) if common_size else raw
            row["CAGR"] = "" if common_size else _cagr_for(values)
            rows.append(row)
            return len(rows) - 1

        appended: list[int] = []
        for name, values in detail:
            if _row_equals_total(values):
                continue
            appended.append(_append(f"    {name}", values))

        # Second level: expand the "Other (N items)" rollup into its constituents
        # (deeper indent), emitted immediately after it. ``rolled_up`` is already
        # sorted by magnitude descending.
        rolled = section.get("rolled_up") or []
        other_row: int | None = None
        rolled_rows: list[int] = []
        if rolled:
            for i in appended:
                li = str(rows[i]["Line Item"]).strip()
                if li.startswith("Other (") and li.endswith("items)"):
                    other_row = i
                    break
            if other_row is not None:
                for name, values in rolled:
                    rolled_rows.append(_append(f"        {name}", values))
        return appended, other_row, rolled_rows

    def _record_group(anchor: int, children: list[int]) -> None:
        """A subtotal is a collapse anchor only when it owns >=2 detail rows."""
        if len(children) >= 2:
            collapse_groups.append({"anchor": anchor, "children": children})

    def _record_nested(parent: int, other_row: int | None, rolled_rows: list[int]) -> None:
        """Register the "Other (N items)" rollup as a second-level accordion whose
        rows only show when BOTH it and its parent subtotal are expanded."""
        if other_row is not None and len(rolled_rows) >= 2:
            collapse_groups.append(
                {"anchor": other_row, "children": rolled_rows, "parent": parent}
            )

    for section in sections:
        label = section["label"]
        total = section["total"]
        kind = section["kind"]

        if label in DEBT_ANALYSIS_LABELS and debt_separator_row is None:
            debt_separator_row = len(rows)

        # Margin rows: decimal values formatted inline as "21.3%" strings so
        # mixed-dtype cells render correctly through the existing fmt_k_gel path
        # (which passes strings through unchanged). Not bolded — they're
        # secondary info under the bold total row above.
        if kind == "margin":
            from lib.format import fmt_pct_signed

            margin_row: dict = {"Line Item": label}
            for y in years:
                margin_row[y] = fmt_pct_signed(total.get(y, 0))
            # CAGR of a ratio isn't meaningful — leave blank.
            margin_row["CAGR"] = ""
            rows.append(margin_row)
            margin_row_indices.append(len(rows) - 1)
            continue

        details_first = bool(section.get("details_first")) and kind not in (
            "derived_total",
            "final_total",
        )

        if details_first:
            # Reading order: inputs (faint detail) first, subtotal below.
            children, other_row, rolled_rows = _emit_detail_rows(section)
            anchor = _emit_total_row(section)
            _record_group(anchor, children)
            _record_nested(anchor, other_row, rolled_rows)
        else:
            # Legacy order: subtotal first, detail rows beneath it.
            anchor = _emit_total_row(section)
            if kind not in ("derived_total", "final_total"):
                children, other_row, rolled_rows = _emit_detail_rows(section)
                _record_group(anchor, children)
                _record_nested(anchor, other_row, rolled_rows)

    df = pd.DataFrame(rows, columns=["Line Item"] + list(years) + ["CAGR"])
    # Stash the accordion grouping on the frame (df.attrs) so the 5-tuple return
    # signature — relied on by many call sites/tests — stays unchanged.
    df.attrs["collapse_groups"] = collapse_groups
    return df, bold, debt_separator_row, margin_row_indices, bar_roles


# ---------------------------------------------------------------------------
# Shared table styling — works in both light and dark Streamlit themes.
# Uses the brand palette: Navy header, alternating row tints, monospace numbers,
# fixed column widths so years align across every table on the page.
# ---------------------------------------------------------------------------


def shared_table_styles(
    first_col_name: str,
    numeric_cols: list,
    fixed_widths: bool = True,
    year_width: int = YEAR_COL_WIDTH_PX,
    cagr_width: int = CAGR_COL_WIDTH_PX,
    label_min_width: int = LABEL_MIN_WIDTH_PX,
) -> list[dict]:
    """Return Pandas-Styler ``set_table_styles`` rules with the shared brand look.

    - Navy header band with white text — visible against both light and dark
      Streamlit themes (the dashboard theme override doesn't touch inline styles).
    - **Flexible label + fixed narrow numeric columns.** The numeric columns take
      ``year_width`` px each (``cagr_width`` for a trailing "CAGR" column) and the
      label column (col0) is left unsized, so under ``table-layout:fixed`` it
      claims the remaining width. The table also gets a ``min-width`` (label floor
      + numeric columns) so a narrow container scrolls (via the caller's
      ``_scroll_wrap``) instead of squashing labels / clipping numbers.
    - Compact (2px vertical padding), monospace numeric font for fast scan.
    - Subtle row borders + alternating row tint with `:nth-child(even)`.
    """
    # Table min-width: label floor + each numeric column at its fixed width. Keeps
    # the numbers fully visible on narrow screens (the wrapper scrolls instead).
    min_w = label_min_width + sum(
        cagr_width if str(c) == "CAGR" else year_width for c in numeric_cols
    )
    root_props = [
        ("border-collapse", "collapse"),
        ("width", "100%"),
        ("table-layout", "fixed" if fixed_widths else "auto"),
        ("font-family", "'Inter','Segoe UI',system-ui,sans-serif"),
    ]
    if fixed_widths:
        root_props.append(("min-width", f"{min_w}px"))
    rules = [
        {"selector": "", "props": root_props},
        {"selector": "thead", "props": [("background-color", NAVY)]},
        {"selector": "thead th", "props": [
            ("padding", "8px 12px"),
            ("font-size", "12px"),
            ("font-weight", "600"),
            ("color", "#FFFFFF"),
            ("background-color", NAVY),
            ("text-align", "right"),
            ("border-bottom", "2px solid " + NAVY),
            ("letter-spacing", "0.02em"),
            # Keep the header visible while scrolling long statements. The solid
            # navy background means there's no see-through gap as rows slide under.
            ("position", "sticky"),
            ("top", "0"),
            ("z-index", "3"),
        ]},
        # First header (label column) is left-aligned and slightly bolder.
        {"selector": "thead th.col_heading.level0.col0", "props": [
            ("text-align", "left"),
            ("font-weight", "700"),
        ]},
        {"selector": "td", "props": [
            ("padding", "4px 10px"),
            ("font-size", "12px"),
            ("border-bottom", "1px solid rgba(128,128,128,0.18)"),
            ("white-space", "nowrap"),
            ("overflow", "hidden"),
            ("text-overflow", "ellipsis"),
        ]},
        # Label column (col0): show the FULL line-item name (wrap instead of
        # truncating). `white-space:normal` collapses the leading-space indent so
        # wrapped continuation lines don't sit ragged; the section-hierarchy
        # indent is re-applied as a per-row left PADDING (see style_statement's
        # `_indent`) so every line of a wrapped label shares one hanging indent.
        {"selector": "td.col0", "props": [
            ("white-space", "normal"),
            ("overflow", "visible"),
            ("text-overflow", "clip"),
            ("word-break", "break-word"),
            ("line-height", "1.35"),
            ("vertical-align", "top"),
        ]},
        # Numeric columns: monospace font, right-aligned.
        {"selector": "td:nth-child(n+2)", "props": [
            ("font-family", "'IBM Plex Mono','SF Mono','Consolas','Menlo',monospace"),
            ("text-align", "right"),
            ("font-variant-numeric", "tabular-nums"),
        ]},
        # Alternating row tint — uses rgba so it works on light AND dark themes.
        {"selector": "tbody tr:nth-child(even) td", "props": [
            ("background-color", "rgba(128,128,128,0.05)"),
        ]},
        {"selector": "tbody tr:hover td", "props": [
            ("background-color", "rgba(219,185,104,0.18)"),  # light gold tint
        ]},
    ]
    if fixed_widths:
        # Pandas' Styler emits NO <colgroup>, so width has to go on the cells.
        # Under table-layout:fixed the first row (thead th) governs the column
        # widths; we size the header + body cells of each NUMERIC column and
        # deliberately leave col0 (label) UNSIZED so it absorbs the remaining
        # width. CAGR is narrower than the year columns.
        for i, name in enumerate(numeric_cols):
            w = cagr_width if str(name) == "CAGR" else year_width
            rules.append({"selector": f"th.col{i+1}", "props": [("width", f"{w}px")]})
            rules.append({"selector": f"td.col{i+1}", "props": [("width", f"{w}px")]})
    return rules


def style_statement(df: pd.DataFrame, bold_rows: list[int], years: list[int], margin_rows: list[int] | None = None, common_size: bool = False, bar_roles: dict[int, str] | None = None):
    """Style an IS/BS DataFrame with the shared brand table look.

    `margin_rows` are row indices whose values are pre-formatted percentage
    strings (e.g. "21.3%" or "(5.2%)"). The formatter passes strings through
    unchanged so mixed-dtype cells render correctly.

    `common_size` signals that EVERY year cell is a pre-formatted percent string
    (the common-size view), so negative-value coloring is driven by the
    parenthesized-string convention for all rows, not just margin rows.

    `bar_roles` maps ``row_index -> role`` for subtotal rows that should render
    as a full-width COLORED BAR (white bold text) — role colors come from
    ``BAR_ROLE_COLORS``. Bar rows take precedence over the plain bold style.
    The white-on-color treatment also overrides the burgundy negative color
    (a bar already communicates the line's role), so negative values stay
    legible against the dark bar.
    """
    margin_rows = margin_rows or []
    bar_roles = bar_roles or {}

    def _fmt_cell(v):
        # Margin rows pre-format their cells to strings like "21.3%" or "(5.2%)";
        # pass those through so they aren't re-formatted as GEL amounts.
        if isinstance(v, str):
            return v
        return fmt_k_gel(v)

    fmt_dict = {y: _fmt_cell for y in years}
    # CAGR column also passes through pre-formatted strings.
    if "CAGR" in df.columns:
        fmt_dict["CAGR"] = _fmt_cell
    styler = df.style.format(fmt_dict)

    margin_set = set(margin_rows)
    has_cagr = "CAGR" in df.columns

    def _bold(row):
        # Subtotals render as plain BOLD with a subtle tint + a top rule —
        # matching the platform's Excel-export look (no full-width colored bars).
        # The grand total / bottom line ("net" role, e.g. Profit / Net profit)
        # gets a heavier rule so it's unmistakable (single-rule subtotal /
        # heavier-rule grand-total accounting convention). `!important` on the
        # tint beats the zebra `tr:nth-child(even) td` rule on even rows.
        role = bar_roles.get(row.name)
        if row.name in margin_set:
            return ["font-style:italic;color:var(--fd-muted,#6b7280);"] * len(row)
        if (role in BAR_ROLE_COLORS) or (row.name in bold_rows):
            rule = (
                "border-top:2px solid rgba(17,58,63,0.45);"
                if role == "net"
                else "border-top:1px solid rgba(17,58,63,0.20);"
            )
            return [
                f"font-weight:700;background-color:rgba(17,58,63,0.08) !important;{rule}"
            ] * len(row)
        # Detail / input / income-component rows render MUTED so the bold
        # subtotals are what the eye lands on first (quiet details, loud totals).
        # A readable gray (~5:1 on the off-white bg, WCAG-OK), not a faint wash.
        # Negative cells are still recolored burgundy by _neg_color (after this).
        return ["color:var(--fd-muted,#5f6670);"] * len(row)

    _year_set = set(years)

    def _neg_color(row):
        out = []
        # Subtotals are now plain bold dark text (not white-on-color), so
        # negatives there should be burgundy like everywhere else — no skip.
        # In common-size mode every year cell is a percent string, so the
        # parenthesized-string convention drives coloring for all rows.
        is_margin = (row.name in margin_set) or common_size
        for col in row.index:
            v = row[col]
            if col == "CAGR":
                # CAGR column: parenthesized strings ("(3.2%)") indicate negative.
                if isinstance(v, str) and v.startswith("("):
                    out.append(f"color:{BURGUNDY};")
                else:
                    out.append("")
                continue
            if col in _year_set:
                if is_margin:
                    if isinstance(v, str) and v.startswith("("):
                        out.append(f"color:{BURGUNDY};")
                    else:
                        out.append("")
                    continue
                try:
                    out.append(f"color:{BURGUNDY};" if float(v) < 0 else "")
                except (TypeError, ValueError):
                    out.append("")
            else:
                out.append("")
        return out

    # Hanging indent for the label column: re-apply the section-hierarchy indent
    # (stripped visually by td.col0 `white-space:normal`) as a per-row left
    # padding on the "Line Item" cell, so wrapped continuation lines align under
    # the first line instead of running flush-left.
    def _indent(row):
        # `!important` beats the base `td { padding: 4px 10px }` table rule (which
        # has higher specificity than pandas' per-cell id rule and would otherwise
        # reset padding-left, swallowing the indent).
        pad = _label_indent_px(row.get("Line Item"))
        return [f"padding-left:{10 + pad}px !important;" if col == "Line Item" and pad else ""
                for col in row.index]

    styler = styler.apply(_bold, axis=1)
    styler = styler.apply(_neg_color, axis=1)
    styler = styler.apply(_indent, axis=1)
    right_align_cols = list(years) + (["CAGR"] if has_cagr else [])
    styler = styler.set_properties(subset=right_align_cols, **{"text-align": "right"})
    styler = styler.set_properties(subset=["Line Item"], **{"text-align": "left"})
    # Content-adaptive column widths so numeric columns are only as wide as the
    # widest value they carry (the label column absorbs the slack). CAGR gets the
    # same treatment but floored at its narrow default: it stays compact when all
    # values are short positive rates ("8.8%") and only grows to fit parenthesized
    # negatives ("(41.2%)", 7ch) — which the fixed 64px clipped to "(41...".
    year_w = _numeric_col_width_px(df, list(years))
    cagr_w = (
        _numeric_col_width_px(df, ["CAGR"], floor=CAGR_COL_WIDTH_PX)
        if has_cagr
        else CAGR_COL_WIDTH_PX
    )
    styler = styler.set_table_styles(
        shared_table_styles(
            "Line Item", right_align_cols, year_width=year_w, cagr_width=cagr_w
        )
    )
    # Visual separator + italic styling for the CAGR column so it reads as
    # "derived metric, not a year".
    if has_cagr:
        styler = styler.set_properties(subset=["CAGR"], **{
            "border-left": "1px solid rgba(128,128,128,0.3)",
            "font-style": "italic",
            "color": "var(--fd-faint,#555)",
        })
    styler = styler.hide(axis="index")
    return styler


def render_grouped_ratios(
    df: pd.DataFrame,
    years: list[int],
    db_path: str | None = None,
    idcode: str | None = None,
) -> None:
    """Render the ratios table grouped by category, mirroring the IS/BS look.

    Takes the flat ``build_ratios_table`` frame (columns ``["Ratio"] + years``,
    pre-formatted string cells) and re-lays it out with a bold category header
    bar per group (Margins · Returns · Leverage · Liquidity & working capital ·
    Turnover · Cash flow, from
    ``lib.ratios.RATIO_GROUPS``) and the ratios indented beneath — the same navy
    header, subtotal-bar, muted-detail, monospace-number design language as the
    statement tables, in a horizontal-scroll wrapper.

    When ``db_path``/``idcode`` are given, the year headers become reportal.ge
    annual-PDF links (stored ``report_pdf_links`` only — no live resolution),
    matching the IS/BS/CF statement tables.
    """
    from lib.ratios import RATIO_GROUPS, RATIO_UNITS

    year_cols = [y for y in years if y in df.columns]
    if df.empty or not year_cols:
        st.caption("No ratios available for this company in the selected years.")
        return

    present = {row["Ratio"]: row for _, row in df.iterrows()}
    grouped_labels = {lbl for _, labels in RATIO_GROUPS for lbl in labels}
    # Any ratio not assigned to a group (future additions) lands under "Other" so
    # nothing silently disappears from the view.
    leftover = [lbl for lbl in present if lbl not in grouped_labels]
    groups = list(RATIO_GROUPS) + ([("Other", leftover)] if leftover else [])

    disp_rows: list[dict] = []
    header_rows: list[int] = []
    for category, labels in groups:
        labels_here = [lbl for lbl in labels if lbl in present]
        if not labels_here:
            continue
        header_rows.append(len(disp_rows))
        disp_rows.append({"Ratio": category, **{y: "" for y in year_cols}})
        for lbl in labels_here:
            src = present[lbl]
            # Unit/definition rides as a native hover tooltip on the metric name
            # (dotted underline = the affordance). Leading spaces stay OUTSIDE
            # the span so _label_indent_px still sees them. Styler doesn't
            # escape cell values, so the span renders as HTML.
            unit = RATIO_UNITS.get(lbl)
            label_cell = (
                "    "
                + (f'<span title="{unit}" style="cursor:help;border-bottom:'
                   f'1px dotted rgba(95,102,112,0.5);">{lbl}</span>' if unit else lbl)
            )
            disp_rows.append({
                "Ratio": label_cell,
                **{y: ("" if src.get(y) in (None, "N/A") else src.get(y)) for y in year_cols},
            })

    disp = pd.DataFrame(disp_rows, columns=["Ratio"] + year_cols)
    header_set = set(header_rows)

    _HEADER = ("font-weight:700;background-color:rgba(17,58,63,0.08) !important;"
               "border-top:1px solid rgba(17,58,63,0.20);")
    _MUTED = "color:var(--fd-muted,#5f6670);"

    def _rowstyle(row):
        return [_HEADER if row.name in header_set else _MUTED] * len(row)

    def _indent(row):
        # `!important` beats the base `td { padding }` rule (higher specificity
        # than the per-cell id rule) so the indent isn't reset.
        pad = _label_indent_px(row.get("Ratio"))
        return [f"padding-left:{10 + pad}px !important;" if col == "Ratio" and pad else ""
                for col in row.index]

    styler = disp.style
    styler = styler.apply(_rowstyle, axis=1)
    styler = styler.apply(_indent, axis=1)
    styler = styler.set_properties(subset=year_cols, **{"text-align": "right"})
    styler = styler.set_properties(subset=["Ratio"], **{"text-align": "left"})
    year_w = _numeric_col_width_px(disp, year_cols)
    styler = styler.set_table_styles(
        shared_table_styles("Ratio", year_cols, year_width=year_w)
    )
    styler = styler.hide(axis="index")
    html = styler.to_html()
    if db_path and idcode:
        try:
            from lib.cache import report_pdf_urls as _stored_pdf_urls
            pdf_urls = dict(_stored_pdf_urls(db_path, idcode))
        except Exception:
            pdf_urls = {}
        html = wrap_year_headers_with_reportal_link(html, year_cols, idcode, pdf_urls)
    st.markdown(_scroll_wrap(html), unsafe_allow_html=True)


def render_is_chart(sections: list[dict], years: list[int]) -> None:
    """Optional chart visualizing Revenue (bars) + Gross / EBITDA / Net margins
    (lines on secondary axis) across years. Renders inside an st.expander so the
    user can opt in.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    def section_total(label_prefix: str):
        for s in sections:
            if s["label"].startswith(label_prefix):
                return s["total"]
        return {}

    revenue = section_total("Total Revenue")
    gp = section_total("Gross Profit")
    ebitda = section_total("EBITDA")
    net = section_total("Net Profit / (Loss)")

    if not any(revenue.values()):
        return  # nothing to chart

    sorted_years = sorted(years)

    def margin_pct(num_by_year: dict) -> list:
        out = []
        for y in sorted_years:
            r = revenue.get(y, 0)
            n = num_by_year.get(y, 0)
            out.append((n / r * 100) if r else None)
        return out

    gross_margin = margin_pct(gp)
    ebitda_margin = margin_pct(ebitda)
    net_margin = margin_pct(net)

    with st.expander(":material/bar_chart: Show chart — Revenue + margins"):
        from lib.theme import (
            CHART_CATEGORICAL,
            CHART_CATEGORICAL_DARK,
            active_theme,
            chart_theme,
            tokens,
        )

        mode = active_theme()
        t = tokens(mode)
        palette = CHART_CATEGORICAL_DARK if mode == "dark" else CHART_CATEGORICAL
        bar_color = palette[2]       # slate-blue — a calm anchor for the bars
        gross_color = t["positive"]  # green
        ebitda_color = t["brass"]    # gold
        net_color = palette[4]       # clay/terracotta — distinct from green & gold

        # Adaptive revenue unit so a billion-GEL filer doesn't read as "1M" on a
        # "K GEL" axis (mirrors the KPI tiles' bn/m/k scaling).
        max_rev = max((revenue.get(y, 0) or 0) for y in sorted_years)
        if max_rev >= 1e9:
            div, unit, dec = 1e9, "bn GEL", 2
        elif max_rev >= 1e6:
            div, unit, dec = 1e6, "m GEL", 1
        else:
            div, unit, dec = 1e3, "K GEL", 0
        rev_scaled = [(revenue.get(y, 0) or 0) / div for y in sorted_years]
        x_cats = [str(y) for y in sorted_years]

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Bar(
                x=x_cats, y=rev_scaled, name=f"Revenue ({unit})",
                marker=dict(color=bar_color, cornerradius=6, line=dict(width=0)),
                opacity=0.9,
                text=rev_scaled, texttemplate=f"%{{y:,.{dec}f}}",
                textposition="outside",
                textfont=dict(size=12, color=t["ink_muted"]),
                cliponaxis=False,
                hovertemplate=f"%{{x}}<br>Revenue: %{{y:,.{dec}f}} {unit}<extra></extra>",
            ),
            secondary_y=False,
        )
        for y_vals, nm, col, dash in [
            (gross_margin, "Gross margin", gross_color, "solid"),
            (ebitda_margin, "EBITDA margin", ebitda_color, "dash"),
            (net_margin, "Net margin", net_color, "dot"),
        ]:
            fig.add_trace(
                go.Scatter(
                    x=x_cats, y=y_vals, name=nm, mode="lines+markers",
                    line=dict(color=col, width=3.2, dash=dash),
                    marker=dict(size=7),
                    hovertemplate="%{x}<br>" + nm + ": %{y:.1f}%<extra></extra>",
                ),
                secondary_y=True,
            )

        # Revenue axis: anchor at zero with headroom so the outside bar labels fit.
        rev_max = max(rev_scaled) if rev_scaled else 0
        fig.update_yaxes(
            title_text=f"Revenue ({unit})", secondary_y=False,
            range=[0, rev_max * 1.18] if rev_max else None,
        )
        # Margin axis: gridless companion so the two scales don't clutter each other.
        m_vals = [m for m in (gross_margin + ebitda_margin + net_margin) if m is not None]
        if m_vals:
            lo, hi = min(m_vals), max(m_vals)
            lo_r = min(0, lo)
            span = (hi - lo_r) or 1
            m_range = [lo_r - (0.05 * span if lo_r < 0 else 0), hi + 0.15 * span]
        else:
            m_range = None
        fig.update_yaxes(
            title_text="Margin (%)", secondary_y=True, ticksuffix="%",
            range=m_range, zeroline=False,
        )
        fig.update_xaxes(title_text="Year", type="category", showgrid=False)
        fig.update_layout(
            height=380,
            margin=dict(l=40, r=40, t=42, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            bargap=0.5,
        )
        chart_theme(fig)
        # Nudge the base font above chart_theme's 12px for axis/legend legibility.
        fig.update_layout(font=dict(size=13), legend=dict(font=dict(size=12)))
        # chart_theme re-grids every y-axis; keep the grid on the revenue scale only
        # so the margin lines read cleanly against a single set of gridlines.
        fig.update_yaxes(showgrid=False, secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)


def reportal_company_url(idcode: str) -> str:
    """Public URL of a company's reports page on reportal.ge."""
    return f"https://reportal.ge/ka/Reports/Report?q={idcode}"


def _wrap_year_headers(
    html: str,
    years: list[int],
    urls: dict[int, str | None],
    fallback_url: str,
    direct_title_tpl: str,
    fallback_title_tpl: str,
) -> str:
    """Generic core: wrap each ``>YEAR<`` header cell in an anchor.

    Per year: link to ``urls[year]`` when present (``direct_title_tpl``), else
    ``fallback_url`` (``fallback_title_tpl``). Both title templates take ``{y}``.
    Only the FIRST ``>YEAR<`` occurrence is replaced (the <th> header) — body
    cells like "2017" must not be linkified; pandas Styler emits the header
    before any body row, so first-match reliably targets the header.
    """
    for y in years:
        marker = f">{y}<"
        if marker not in html:
            continue
        target = urls.get(int(y)) or fallback_url
        is_direct = bool(urls.get(int(y)))
        title = (direct_title_tpl if is_direct else fallback_title_tpl).format(y=y)
        html = html.replace(
            marker,
            f'><a href="{target}" target="_blank" rel="noopener" '
            f'title="{title}" '
            f'style="color:inherit;text-decoration:underline;">{y}</a><',
            1,
        )
    return html


def wrap_year_headers_with_reportal_link(
    html: str,
    years: list[int],
    idcode: str,
    pdf_urls: dict[int, str | None] | None = None,
) -> str:
    """Link each year header to that year's reportal.ge annual PDF, falling back
    to the company's reports page when no direct PDF is known.

    Clicking the direct PDF link only downloads if the user's browser is logged
    in to reportal.ge — same session cookie that we use server-side.
    """
    if not idcode:
        return html
    return _wrap_year_headers(
        html, years, pdf_urls or {}, reportal_company_url(idcode),
        "Download {y} consolidated annual PDF (reportal.ge)",
        "Open this company's reports page on reportal.ge (no direct {y} PDF available)",
    )


def wrap_year_headers_with_source_link(
    html: str,
    years: list[int],
    urls: dict[int, str | None],
) -> str:
    """Link each year header to its insurance.gov.ge source return (the actual
    data source for a regulator-covered insurer), falling back to the regulator
    statistics index when a year's source id is unknown."""
    from lib.insurance_gov import INSURANCE_GOV_INDEX_URL
    return _wrap_year_headers(
        html, years, urls or {}, INSURANCE_GOV_INDEX_URL,
        "Open {y} insurance.gov.ge source return (XLSX)",
        "Open the insurance.gov.ge statistics index",
    )


def render_reportal_pdf_caption(db_path: str | None, idcode: str | None, years: list[int]) -> None:
    """Render a compact caption of reportal.ge audited-annual-PDF links for the
    given years, if any are known in ``report_pdf_links``.

    Used as a *secondary* affordance under regulator-insurer statements, whose
    year headers link to the insurance.gov.ge source return instead. No-op when
    no PDFs are known (e.g. reportal has no filing for the shown years)."""
    if not (db_path and idcode):
        return
    try:
        from lib.cache import report_pdf_urls as _stored_pdf_urls
        stored = _stored_pdf_urls(db_path, idcode)
    except Exception:
        return
    links = [f"[{y}]({stored[y]})" for y in sorted(years) if stored.get(int(y))]
    if links:
        st.caption("📄 Audited annual report (reportal.ge): " + " · ".join(links))


# ---------------------------------------------------------------------------
# Inline collapse / expand for statement detail rows (CSS-only accordion).
# ---------------------------------------------------------------------------
# The statement renders as ONE static HTML <table> via st.markdown(unsafe_
# allow_html=True). Streamlit widgets can't live inside a table row, but a pure
# HTML+CSS "checkbox hack" survives Streamlit's sanitizer (verified: <input>,
# <label>, <style> all pass through). Each subtotal that owns >=2 detail rows
# becomes a disclosure: a hidden checkbox before the table + a <label> arrow in
# the subtotal cell + a per-group CSS rule that reveals the detail rows when
# checked. Fully client-side — no rerun — so toggling is instant (state resets
# on the next Streamlit rerun, which is acceptable).


def _inject_collapsible_sections(
    html: str, groups: list[dict], uid: str, default_collapsed: bool = True
) -> str:
    """Rewrite a rendered statement's HTML so subtotal rows that own detail rows
    become CSS-only accordions.

    ``groups`` is ``[{"anchor": row_idx, "children": [row_idx, ...]}, ...]`` with
    indices into the table's tbody rows (0-based, render order) — captured at
    emission time by :func:`sections_to_dataframe`, so it is correct whether the
    layout lists the subtotal BEFORE its detail (IS legacy order) or AFTER it
    (BS "inputs first" / ``details_first``). Returns the HTML unchanged on any
    structural surprise (so a Styler-output change can't break rendering)."""
    if not groups:
        return html
    m = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    if not m:
        return html
    tbody_inner = m.group(1)
    tr_spans = list(re.finditer(r"<tr\b[^>]*>.*?</tr>", tbody_inner, re.S))
    max_idx = max(
        [g["anchor"] for g in groups] + [c for g in groups for c in g["children"]]
    )
    if max_idx >= len(tr_spans):
        return html  # index/<tr> mismatch — don't risk mangling the table

    anchor_to_gid = {g["anchor"]: g["anchor"] for g in groups}
    child_to_gid = {c: g["anchor"] for g in groups for c in g["children"]}

    def _add_tr_class(tr: str, cls: str) -> str:
        mm = re.match(r"<tr\b([^>]*)>", tr)
        attrs, rest = mm.group(1), tr[mm.end():]
        if 'class="' in attrs:
            attrs = re.sub(
                r'class="([^"]*)"',
                lambda x: 'class="' + x.group(1) + " " + cls + '"',
                attrs,
                count=1,
            )
        else:
            attrs = attrs + ' class="' + cls + '"'
        return "<tr" + attrs + ">" + rest

    def _inject_label(tr: str, gid: int) -> str:
        label = (
            '<label class="fd-t" for="fd-c-' + uid + "-" + str(gid) + '">'
            '<span class="fd-a"></span></label>'
        )
        return re.sub(r"(<td\b[^>]*>)", lambda x: x.group(1) + label, tr, count=1)

    new_trs: list[str] = []
    for idx, mt in enumerate(tr_spans):
        tr = mt.group(0)
        # A row can be BOTH a child (of its parent group) and an anchor (of a
        # nested group) — e.g. the "Other (N items)" rollup row. Apply both: the
        # child class so it hides with its parent, and the label so it toggles
        # its own nested rows.
        if idx in child_to_gid:
            tr = _add_tr_class(tr, "fd-d fd-g" + uid + "-" + str(child_to_gid[idx]))
        if idx in anchor_to_gid:
            tr = _inject_label(tr, anchor_to_gid[idx])
        new_trs.append(tr)

    new_tbody = "<tbody>" + "".join(new_trs) + "</tbody>"
    html = html[: m.start()] + new_tbody + html[m.end():]

    rules = [
        "input.fd-cc{position:absolute;opacity:0;height:0;width:0;pointer-events:none;}",
        "tr.fd-d{display:none;}",
        "label.fd-t{cursor:pointer;user-select:none;}",
        # currentColor + opacity so the arrow stays legible on both plain rows
        # (dark text) and colored subtotal bars (white text) — e.g. BS totals.
        "label.fd-t .fd-a{display:inline-block;width:1em;margin-left:-0.2em;"
        "color:currentColor;opacity:0.55;font-size:0.72em;vertical-align:middle;}",
        'label.fd-t .fd-a::before{content:"\\25B6";}',
    ]
    inputs: list[str] = []
    for g in groups:
        a = g["anchor"]
        cid = "fd-c-" + uid + "-" + str(a)
        checked = "" if default_collapsed else " checked"
        inputs.append('<input type="checkbox" class="fd-cc" id="' + cid + '"' + checked + ">")
        # A nested group (a rollup under a subtotal) reveals its rows only when
        # BOTH its own checkbox and its parent's are checked — the parent input
        # is emitted earlier in this same sibling list, so the chained-`~`
        # combinator holds. Top-level groups need just their own checkbox.
        parent = g.get("parent")
        if parent is None:
            gate = "#" + cid + ":checked ~ "
        else:
            pcid = "fd-c-" + uid + "-" + str(parent)
            gate = "#" + pcid + ":checked ~ #" + cid + ":checked ~ "
        rules.append(gate + "table tr.fd-g" + uid + "-" + str(a) + "{display:table-row;}")
        rules.append('#' + cid + ':checked ~ table label[for="' + cid + '"] .fd-a::before{content:"\\25BC";}')
    block = "<style>" + "".join(rules) + "</style>" + "".join(inputs)

    ti = html.find("<table")
    if ti == -1:
        return html
    return html[:ti] + block + html[ti:]


def render_statement(
    sections: list[dict],
    years: list[int],
    statement_kind: str,
    idcode: str | None = None,
    common_size_toggle: bool = True,
    common_size_key: str | None = None,
    db_path: str | None = None,
    year_source: str = "reportal",
    year_source_urls: dict[int, str] | None = None,
) -> None:
    """Render an IS or BS as a styled HTML table.

    For BS, if a Debt-Analysis block is present, the table is split into two:
    a main BS table followed by a divider, a "Debt Analysis" subheader, and a
    smaller table containing Total Debt / Cash & Equivalents / Net Debt.

    When `idcode` is provided, every year column header becomes a hyperlink.
    ``year_source`` selects what it points at:
      - ``"reportal"`` (default): that year's reportal.ge annual PDF (from the
        precomputed ``report_pdf_links`` store, else live-resolved with a
        cookie, else the company's reports page).
      - ``"insurance_gov"``: the insurance.gov.ge source return for that year —
        the actual data source for a regulator-covered insurer. Pass the
        per-year URLs in ``year_source_urls`` (from
        ``lib.cache.insurance_gov_source_urls``); reportal is offered separately
        by the caller as a secondary caption.

    When ``common_size_toggle`` is True, a "Common-size" checkbox is rendered
    above the table; ticking it re-renders every line as a percentage of the
    per-year base (Revenue for IS, Total Assets for BS) — the single most common
    thing an analyst rebuilds in Excel after export. ``common_size_key`` keys
    the checkbox so the IS and BS toggles stay independent (defaults to
    ``f"common_size_{statement_kind}"``). Sprint-26-safe: the checkbox owns its
    session-state key; we read it but never write it after it instantiates.
    """
    common_size = False
    if common_size_toggle:
        key = common_size_key or f"common_size_{statement_kind}"
        base_label = "Revenue" if statement_kind == "is" else "Total Assets"
        common_size = st.checkbox(
            f"Common-size (show every line as % of {base_label})",
            key=key,
            help=(
                "Re-express each line as a percentage of "
                f"{base_label} for that year — the comparable, scale-free view. "
                "CAGR is hidden since a growth rate of percentages isn't meaningful."
            ),
        )

    base_by_year = common_size_base(sections, statement_kind) if common_size else None
    df, bold_rows, debt_row, margin_rows, bar_roles = sections_to_dataframe(
        sections, years, common_size=common_size, base_by_year=base_by_year
    )

    # Resolve the per-year header links, then a `_wrap` closure applies them to
    # each rendered table's <th> cells. For a regulator insurer the header
    # points at the insurance.gov.ge source return (its actual data source);
    # otherwise it points at the reportal.ge annual PDF.
    pdf_urls: dict[int, str | None] = {}
    # Whether to show the "click a year to open its reportal PDF" hint under the
    # table — only on the default reportal path (insurers link to their
    # insurance.gov source return instead and get a separate caption).
    show_reportal_year_hint = False
    if idcode and year_source == "insurance_gov":
        pdf_urls = dict(year_source_urls or {})

        def _wrap(html: str) -> str:
            return wrap_year_headers_with_source_link(html, years, pdf_urls)
    elif idcode:
        # reportal, two-tier:
        #   1) Precomputed links from the DB (report_pdf_links) — instant, no
        #      cookie needed; the normal path.
        #   2) Any year not in the store: live-resolve IF a cookie is set
        #      (covers brand-new years not yet scraped).
        # Neither → the wrap helper falls back to the company reports page.
        if db_path:
            try:
                from lib.cache import report_pdf_urls as _stored_pdf_urls
                pdf_urls = dict(_stored_pdf_urls(db_path, idcode))
            except Exception:
                pdf_urls = {}
        missing = [y for y in years if not pdf_urls.get(int(y))]
        if missing:
            try:
                from lib.reportal_pdf import cookie_available, get_pdf_urls_for_years
                if cookie_available():
                    live = get_pdf_urls_for_years(idcode, missing)
                    pdf_urls.update({y: u for y, u in live.items() if u})
            except Exception:
                # Never let a reportal hiccup break statement rendering.
                pass

        show_reportal_year_hint = True

        def _wrap(html: str) -> str:
            return wrap_year_headers_with_reportal_link(html, years, idcode, pdf_urls)
    else:
        def _wrap(html: str) -> str:
            return html

    # Inline collapse/expand for detail rows (IS + BS). The parent→children
    # grouping was captured at emission on ``df.attrs`` so it's correct for both
    # layout orders. Each rendered table gets its own uid tag + a row-range so
    # element IDs stay unique across the page (the BS main + Debt-Analysis
    # sub-tables in particular are separate st.markdown blocks).
    _collapsible = statement_kind in ("is", "bs")
    _uid_base = re.sub(r"[^A-Za-z0-9]", "", f"{statement_kind}{idcode or ''}") or "s"
    _all_groups = df.attrs.get("collapse_groups", []) if _collapsible else []

    def _collapse(html: str, tag: str, lo: int, hi: int) -> str:
        """Inject the accordions whose rows fall in [lo, hi), reindexed to the
        sub-table (offset by -lo)."""
        if not _collapsible:
            return html

        def _in(i: int) -> bool:
            return lo <= i < hi

        sub = []
        for g in _all_groups:
            if not (_in(g["anchor"]) and all(_in(c) for c in g["children"])):
                continue
            parent = g.get("parent")
            if parent is not None and not _in(parent):
                continue  # nested group split from its parent — drop the nesting
            entry = {"anchor": g["anchor"] - lo,
                     "children": [c - lo for c in g["children"]]}
            if parent is not None:
                entry["parent"] = parent - lo
            sub.append(entry)
        return _inject_collapsible_sections(html, sub, _uid_base + tag)

    # Discoverability callout for the clickable year headers, placed directly
    # above the table (adjacent to the year row). A gold-framed banner rather
    # than a faint caption so the affordance is actually noticed. Body text uses
    # `inherit` so it stays legible in both the light and any dark theme; the
    # gold accent (#C8922E) frame + tint read on both. Reportal path only —
    # insurers get their own source-link caption.
    if show_reportal_year_hint:
        n_direct = sum(1 for y in years if pdf_urls.get(int(y)))
        _body = (
            "click any <u>year</u> in the table header to open that year's "
            "audited annual-report PDF on reportal.ge (where available)."
            if n_direct else
            "click any <u>year</u> in the table header to open this company's "
            "filings on reportal.ge."
        )
        st.markdown(
            '<div style="border:1px solid #C8922E;border-left:4px solid #C8922E;'
            'border-radius:6px;background:rgba(200,146,46,0.12);'
            'padding:8px 12px;margin:2px 0 10px;font-size:0.9em;">'
            '<span style="color:#C8922E;font-weight:700;">📄 Original filing —</span>'
            f'<span style="font-weight:600;"> {_body}</span></div>',
            unsafe_allow_html=True,
        )

    if statement_kind == "bs" and debt_row is not None:
        df_main = df.iloc[:debt_row].reset_index(drop=True)
        bold_main = [i for i in bold_rows if i < debt_row]
        margin_main = [i for i in margin_rows if i < debt_row]
        bar_main = {i: r for i, r in bar_roles.items() if i < debt_row}
        html_main = style_statement(
            df_main, bold_main, years, margin_main, common_size=common_size,
            bar_roles=bar_main,
        ).to_html()
        html_main = _collapse(_wrap(html_main), "m", 0, debt_row)
        st.markdown(_scroll_wrap(html_main), unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("##### Debt Analysis")

        df_debt = df.iloc[debt_row:].reset_index(drop=True)
        bold_debt = [i - debt_row for i in bold_rows if i >= debt_row]
        margin_debt = [i - debt_row for i in margin_rows if i >= debt_row]
        bar_debt = {i - debt_row: r for i, r in bar_roles.items() if i >= debt_row}
        html_debt = style_statement(
            df_debt, bold_debt, years, margin_debt, common_size=common_size,
            bar_roles=bar_debt,
        ).to_html()
        html_debt = _collapse(_wrap(html_debt), "d", debt_row, len(df))
        st.markdown(_scroll_wrap(html_debt), unsafe_allow_html=True)
    else:
        html_full = style_statement(
            df, bold_rows, years, margin_rows, common_size=common_size,
            bar_roles=bar_roles,
        ).to_html()
        html_full = _collapse(_wrap(html_full), "", 0, len(df))
        st.markdown(_scroll_wrap(html_full), unsafe_allow_html=True)

    # The OpEx "Other (N items)" rollup used to expand into a separate st.expander
    # below the table; it's now a second-level inline accordion nested under the
    # "Other (N items)" row itself (see sections_to_dataframe / _record_nested),
    # so no separate disclosure is needed.
