"""Design tokens + chart theming for the "Reportal Terminal" rebrand (Wave 0).

Single source of truth for the palette in BOTH modes — light ("Paper") and dark
("Terminal"). ``lib/ui.inject_brand_css`` reads these to build the CSS-variable
layer; the Plotly ``chart_theme`` helper reads them too; later waves'
``lib/components`` will as well.

Pure Python + Plotly only — Streamlit is imported lazily inside ``active_theme``
so this module stays cheap to import and unit-testable without a Streamlit run.

Constant *names* in ``lib/ui`` (NAVY/GOLD/SLATE/…) are kept for back-compat; this
module is where the richer, theme-aware surface set lives.
"""
from __future__ import annotations

# --- Light content theme ("Terminal", charcoal-bar variant) ----------------
# Clean cool-white body, graphite structure, gold accent. The dark command bar
# is styled separately in lib/ui.render_top_bar.
LIGHT: dict[str, str] = {
    "canvas": "#DDE2E9",          # graphite-grey page background
    "surface": "#FFFFFF",         # cards, tables, panels
    "surface_sunk": "#EFF1F4",    # zebra wells
    "surface_raised": "#FFFFFF",
    "ink": "#16181D",             # primary text
    "ink_muted": "#5B6470",       # secondary text, captions
    "ink_faint": "#8A929C",       # hints, disabled
    "hairline": "rgba(20,24,31,0.10)",
    "forest": "#222B36",          # primary / structure (graphite)
    "brass": "#C8922E",           # accent (gold)
    "positive": "#1E7D5A",
    "negative": "#B23A48",
    "thead_bg": "#222B36",
    "thead_fg": "#FFFFFF",
    "grid": "rgba(20,24,31,0.10)",
    "zero": "rgba(20,24,31,0.45)",  # zero baseline — must read clearly above the grid
}

# --- Dark "Terminal" -------------------------------------------------------
DARK: dict[str, str] = {
    "canvas": "#0E1216",
    "surface": "#161C22",
    "surface_sunk": "#12171C",
    "surface_raised": "#1C242B",
    "ink": "#E6E9EC",
    "ink_muted": "#8A95A1",
    "ink_faint": "#6B7682",
    "hairline": "rgba(255,255,255,0.10)",
    "forest": "#2FA98A",          # lifted teal — forest is invisible on dark
    "brass": "#E8B85C",
    "positive": "#3FB984",
    "negative": "#E5707E",
    "thead_bg": "#1C242B",
    "thead_fg": "#E6E9EC",
    "grid": "rgba(255,255,255,0.10)",
    "zero": "rgba(255,255,255,0.42)",  # zero baseline — must read clearly above the grid
}

# Categorical palette for charts: graphite, gold, slate-blue, green, clay, plum.
CHART_CATEGORICAL = ["#222B36", "#C8922E", "#3E6B8C", "#1E7D5A", "#A6533F", "#6B4E7A"]
CHART_CATEGORICAL_DARK = ["#2FA98A", "#E8B85C", "#6FA8D8", "#D2876B", "#A892C0", "#8FB07F"]

FONT_UI = "Inter, 'Segoe UI', system-ui, sans-serif"
FONT_MONO = "'IBM Plex Mono', 'SF Mono', Consolas, Menlo, monospace"


def tokens(theme: str | None = None) -> dict[str, str]:
    """Return the colour-token dict for ``theme`` ('light' | 'dark')."""
    return DARK if theme == "dark" else LIGHT


def active_theme() -> str:
    """Read the user's chosen mode from session_state; default 'light'.

    Read-only — the sidebar toggle owns the ``ui_dark`` widget key. Safe to call
    at the very top of a run (Sprint-26): we never *write* the widget key here,
    so there's no "write-after-instantiate" hazard.
    """
    try:
        import streamlit as st

        return "dark" if st.session_state.get("ui_dark") else "light"
    except Exception:
        return "light"


def chart_theme(fig, theme: str | None = None):
    """Apply the Reportal Terminal look to a Plotly figure, in-place, and return it.

    Transparent backgrounds (so the figure blends into either mode), Inter font,
    hairline grid, brand colourway, and unified hover. Traces that set explicit
    colours keep them unless the caller recolours; traces with no colour pick up
    the brand colourway in order.
    """
    mode = theme or active_theme()
    t = tokens(mode)
    palette = CHART_CATEGORICAL_DARK if mode == "dark" else CHART_CATEGORICAL
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_UI, size=12, color=t["ink"]),
        colorway=palette,
        hoverlabel=dict(font=dict(family=FONT_UI, size=12)),
        legend=dict(font=dict(size=11)),
    )
    # Zero gets its own (much darker) ink: in the hairline grid colour the baseline was
    # indistinguishable from any other gridline, so charts that cross zero were unreadable.
    fig.update_xaxes(gridcolor=t["grid"], zerolinecolor=t["zero"], zerolinewidth=1.5,
                     linecolor=t["grid"])
    fig.update_yaxes(gridcolor=t["grid"], zerolinecolor=t["zero"], zerolinewidth=1.5,
                     linecolor=t["grid"])
    return fig


def polish_bar_line_chart(fig, *, bargap: float = 0.5):
    """Apply the rounded-bar / bold-line polish (from the Single-Company IS chart)
    to any bar+line combo chart, in-place. Call after ``chart_theme(fig)``.

    Rounds bar corners, thickens scatter lines/markers to 3.2px/7px, slims the bars,
    and bumps the base/legend font size a notch above ``chart_theme``'s defaults for
    legibility. This overwrites any line width / marker size the caller already set —
    don't use it on charts that intentionally use a different (e.g. bolder) line weight.
    """
    fig.update_traces(marker=dict(cornerradius=6), selector=dict(type="bar"))
    fig.update_traces(line=dict(width=3.2), marker=dict(size=7), selector=dict(type="scatter"))
    fig.update_layout(bargap=bargap, font=dict(size=13), legend=dict(font=dict(size=12)))
    return fig
