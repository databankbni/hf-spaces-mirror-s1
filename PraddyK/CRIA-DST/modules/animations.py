"""
modules/animations.py — Seasonal & Drought Animations

Static, looping animations (GIFs) built from the real PRISM-calibrated VIC reanalysis,
the Colorado River drainage network, and major dam locations. Files live in
assets/animations/ and are served directly by Dash (no callbacks / no tiles needed).
"""
from dash import html, dcc
import dash_bootstrap_components as dbc
import numpy as np
import plotly.graph_objects as go
from utils.components import howto
from utils.data_loader import load_spatial

MAROON = "#8C1D40"; NAVY = "#0D2137"


def _anim_graph(gvar, gmode):
    """Basin-average trend (whole CRB) for this animation's variable, by water year."""
    try:
        df = load_spatial(gvar)
        if df is None or df.empty:
            return None
        ts = df.groupby("water_year")["value"].mean().reset_index().sort_values("water_year")
        xs = ts["water_year"].to_numpy(dtype=float)
        ys = ts["value"].to_numpy(dtype=float)
    except Exception:
        return None
    fig = go.Figure()
    if gmode == "anomaly":
        base = float(np.nanmean(ys)) or 1.0
        ys = ys / base * 100.0
        fig.add_hline(y=100, line=dict(color="#b0bec5", width=1, dash="dash"))
        ytitle = "% of 1984–2024 mean"
    else:
        ytitle = "basin average"
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="#cbb3bd", width=1.4)))
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers",
                             line=dict(color=MAROON, width=2.2),
                             marker=dict(size=4, color=MAROON)))
    fig.update_layout(margin=dict(l=48, r=12, t=8, b=30), height=300, showlegend=False,
                      paper_bgcolor="white", plot_bgcolor="white",
                      xaxis=dict(title="Water year", gridcolor="#eef2f6"),
                      yaxis=dict(title=ytitle, gridcolor="#eef2f6"))
    return fig

ANIMS = [
    {
        "src": "/assets/animations/snow_swe.gif", "gvar": "OUT_SWE", "gmode": "trend",
        "title": "Seasonal snowpack — the basin's water tower",
        "what": "Monthly snow-water equivalent (SWE) across the basin through a year.",
        "read": "Snow builds up in the high headwaters through winter (Jan–Mar), then melts "
                "away by late summer (Jul–Sep) — the seasonal mountain 'water tower' that feeds "
                "the river. Watch the snow appear and then vanish.",
        "data": "VIC reanalysis · daily SWE → monthly mean (WY2023)",
    },
    {
        "src": "/assets/animations/runoff.gif", "gvar": "OUT_RUNOFF", "gmode": "trend",
        "title": "Seasonal runoff — the spring melt pulse",
        "what": "Monthly runoff / streamflow generation across the basin.",
        "read": "Most of the year's water enters the river during the spring melt pulse "
                "(Apr–Jun), concentrated in the high Upper-Basin headwaters. The arid lower "
                "basin generates very little runoff.",
        "data": "VIC reanalysis · daily runoff → monthly mean (WY2023)",
    },
    {
        "src": "/assets/animations/soil_moisture.gif", "gvar": "OUT_SOIL_MOIST", "gmode": "trend",
        "title": "Seasonal soil moisture — wet ↔ dry",
        "what": "Total-column soil moisture (green = wet, brown = dry).",
        "read": "The basin wets up after snowmelt and dries steadily through the summer. "
                "Soil-moisture state controls how much of each storm actually becomes runoff.",
        "data": "VIC reanalysis · daily soil moisture → monthly mean (WY2023)",
    },
    {
        "src": "/assets/animations/runoff_dams.gif", "gvar": "OUT_RUNOFF", "gmode": "trend",
        "title": "Runoff, drainage & dams — year by year (WY1984 → 2024)",
        "what": "Animated map of annual runoff (mm/yr) across the basin for every water year, "
                "with the Colorado River drainage network and the seven major dams.",
        "read": "Dark blue = high runoff. Watch the water-generating zones in the Rocky Mountain "
                "headwaters of the Upper Basin (Green, Upper Colorado, San Juan) expand in wet years "
                "(e.g. 2011, 2023) and shrink to almost nothing in drought years (e.g. 2002, 2021) — "
                "the arid Lower Basin generates little in any year. Blue lines are the Colorado River "
                "and tributaries; red ▼ are the major dams (Flaming Gorge, Blue Mesa, Navajo, Glen "
                "Canyon, Hoover, Davis, Parker). The colour scale is fixed across all years so they "
                "are directly comparable.",
        "data": "VIC reanalysis · annual runoff per water year (WY1984–2024) + Colorado River + 7 major dams",
    },
]


def _card(a):
    _map_img = {"width": "100%", "maxWidth": "420px", "height": "auto", "display": "block",
                "margin": "0 auto", "borderRadius": "8px", "border": "1px solid #e2e8f0"}
    _img = {"width": "100%", "maxWidth": "480px", "height": "auto", "display": "block",
            "margin": "0 auto", "borderRadius": "8px", "border": "1px solid #e2e8f0"}
    ggif = "/assets/animations/graph_" + a["src"].split("/")[-1]

    # Container 1 — the animated map
    map_card = html.Div([
        html.Div(html.Span(a["title"], style={"fontWeight": "700", "fontSize": "13.5px",
                                              "color": NAVY}), className="crb-card-header"),
        html.Div([
            html.Img(src=a["src"], style=_map_img),
            html.Div([
                html.Div([html.B("What it shows:  "), a["what"]],
                         style={"fontSize": "12.5px", "marginTop": "10px", "color": "#1e293b"}),
                html.Div([html.B("How to read it:  "), a["read"]],
                         style={"fontSize": "12.5px", "marginTop": "6px", "color": "#1e293b",
                                "lineHeight": "1.5"}),
                html.Div([html.Span("Data: ", style={"fontWeight": "700"}), a["data"]],
                         style={"fontSize": "11px", "marginTop": "8px", "color": "#64748b",
                                "fontStyle": "italic"}),
            ], style={"padding": "4px 6px 2px"}),
        ], className="crb-card-body"),
    ], className="crb-card", style={"height": "100%"})

    # Container 2 — the matching animated basin-average graph (plays in sync)
    graph_card = html.Div([
        html.Div("Basin-average trend — animated", className="crb-card-header",
                 style={"fontWeight": "700", "fontSize": "13px", "color": NAVY}),
        html.Div(html.Img(src=ggif, style=_img),
                 className="crb-card-body",
                 style={"display": "flex", "alignItems": "center", "justifyContent": "center"}),
    ], className="crb-card", style={"height": "100%"})

    return dbc.Row([
        dbc.Col(map_card, xs=12, lg=7, className="mapduo-col mapduo-map"),
        dbc.Col(graph_card, xs=12, lg=5, className="mapduo-col mapduo-graph"),
    ], className="g-3 mb-3 align-items-stretch mapduo-row")


def layout():
    return html.Div([
        html.Div([
            html.H2("Seasonal Cycles"),
            html.P("Purpose: watch how the basin's water moves through a year — snow builds and "
                   "melts, runoff peaks in spring, soils wet and dry — each animation paired with "
                   "its basin-average trend. Built from the PRISM-calibrated VIC reanalysis."),
        ], className="tab-header"),
        html.Div([
            html.Div([
                html.Span("In short — ", style={"fontWeight": "700"}),
                html.Span("these animations summarize the basin's whole water story: snow accumulates "
                          "and melts seasonally, runoff peaks in spring, soils wet and dry — and over "
                          "1984–2024 drought has become widespread and more frequent."),
            ], style={"background": "#e8f5e9", "border": "1px solid #a5d6a7",
                      "borderRadius": "6px", "padding": "10px 14px", "fontSize": "12.5px",
                      "color": "#1b5e20", "marginBottom": "12px"}),

            howto("Each clip loops automatically. The dark background is the basin; the cyan line is "
                  "the Colorado River drainage and red ▼ are major dams (Glen Canyon, Hoover, Flaming "
                  "Gorge, Navajo, Davis, Parker, Blue Mesa). Colour scales are fixed within each clip "
                  "so months / years are directly comparable."),

            _card(ANIMS[0]),
            _card(ANIMS[1]),
            _card(ANIMS[2]),
            _card(ANIMS[3]),

            html.Div("All animations derive from the peer-reviewed VIC 5.0 PRISM-calibrated "
                     "reanalysis (NSE 0.96). Snow, runoff and soil-moisture clips are a single "
                     "representative water year (WY2023); the drought clip spans WY1984–2024. "
                     "Geographic maps are rendered tile-free, so they display in any browser.",
                     style={"fontSize": "10.5px", "color": "#64748b", "marginTop": "14px",
                            "fontStyle": "italic"}),
        ], className="tab-body"),
    ])


def register_callbacks(app):
    # Static animations — no callbacks required.
    return
