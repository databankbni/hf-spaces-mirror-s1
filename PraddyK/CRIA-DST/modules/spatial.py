"""
modules/spatial.py — Spatial Analysis Hub
Layers: Basin choropleth · SNOTEL (all 103) · HUC-10 · VIC grid heatmap
        Colorado River + tributaries · Trend & period analysis
Base maps: CartoDB Light/Dark · OpenStreetMap · ESRI Satellite · Terrain
"""
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, State, Patch, no_update
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from pathlib import Path
from utils.data_loader import load_spatial, load_vic_annual, load_snotel_annual, load_snotel_stations, load_snotel_annual_station, basin_label
from utils.charts import lollipop_h, dot_h, box_h, box_v
from utils.components import info_dot
from utils.basin_map import render_basin_map

MAROON="#8C1D40"; NAVY="#0D2137"; GOLD="#FFC627"; BLUE="#01579B"
GREEN="#2E7D32"; ORANGE="#E65100"; PURPLE="#4527A0"; TEAL="#00695C"
DATA_DIR   = Path(__file__).parent.parent / "data"
ASSETS_DIR = Path(__file__).parent.parent / "assets"# ── Preload GeoJSONs at import ─────────────────────────────
def _load_json(p):
    p = Path(p)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None

BASINS_GJ      = _load_json(ASSETS_DIR / "crb_basins.geojson")
HUC10_GJ       = _load_json(DATA_DIR   / "huc10_crb_simplified.geojson")
RIVERS_GJ      = _load_json(ASSETS_DIR / "crb_rivers.geojson")
BOUNDARIES_GJ  = _load_json(ASSETS_DIR / "crb_boundaries.geojson")

# All 103 SNOTEL stations — file lives in project root /data/, not crb-dst/data/
_SNOTEL_ALL_CSV = DATA_DIR.parent.parent / "data" / "snotel_stations_crb.csv"
if not _SNOTEL_ALL_CSV.exists():
    # fallback: try crb-dst/data/
    _SNOTEL_ALL_CSV = DATA_DIR / "snotel_stations_crb.csv"# ── Bright distinct sub-basin colors ──────────────────────
# Outline (line) colors + same for legend
BASIN_OUTLINE = {
    "CRB":         {"color": "#37474F", "width": 2.5, "label": "Colorado R. Basin"},
    "UpperBasin":  {"color": "#0277BD", "width": 2.5, "label": "Upper Basin"},
    "LowerBasin":  {"color": "#C62828", "width": 2.5, "label": "Lower Basin"},
    "Green":       {"color": "#2E7D32", "width": 2.0, "label": "Green River"},
    "SanJuan":     {"color": "#E65100", "width": 2.0, "label": "San Juan"},
    "GrandCanyon": {"color": "#6A1B9A", "width": 2.0, "label": "Grand Canyon"},
    "Gila":        {"color": "#00695C", "width": 2.0, "label": "Gila River"},
    "UpperColo":   {"color": "#1565C0", "width": 2.0, "label": "Upper Colorado"},
    "GlenCanyon":  {"color": "#00838F", "width": 2.0, "label": "Glen Canyon"},
    "LittleColo":  {"color": "#AD1457", "width": 2.0, "label": "Little Colorado"},
    "LowerColo":   {"color": "#EF6C00", "width": 2.0, "label": "Lower Colorado"},
}

# SNOTEL elevation tiers
SNOTEL_ELEV_TIERS = [
    (2000,  "#29B6F6", "< 2,000 m"),
    (2500,  "#66BB6A", "2,000–2,500 m"),
    (3000,  "#FFA726", "2,500–3,000 m"),
    (9999,  "#EF5350", "> 3,000 m"),
]

RIVER_COLORS = {
    "Colorado River":     "#1565C0",
    "Green River":        "#2E7D32",
    "San Juan River":     "#E65100",
    "Gila River":         "#00695C",
    "Little Colorado R.": "#7B1FA2",
    "Virgin River":       "#F57F17",
}

# Categorical basin fill colors (distinct, vivid — one per sub-basin)
BASIN_FILL_ORDER = ["CRB", "UpperBasin", "LowerBasin", "Green", "SanJuan", "GrandCanyon", "Gila"]
BASIN_FILL_COLORS = {
    "CRB":         "#546E7A",   # blue-grey  (whole basin outline)
    "UpperBasin":  "#1565C0",   # bright blue
    "LowerBasin":  "#C62828",   # bright red
    "Green":       "#2E7D32",   # bright green
    "SanJuan":     "#E65100",   # bright orange
    "GrandCanyon": "#6A1B9A",   # bright purple
    "Gila":        "#00695C",   # bright teal
}

def _basin_categorical_colorscale():
    """Step colorscale so each of 7 basins gets exactly one distinct color."""
    colors = [BASIN_FILL_COLORS[b] for b in BASIN_FILL_ORDER]
    n = len(colors)
    cs = []
    for i, c in enumerate(colors):
        cs.append([round(i / n, 6), c])
        cs.append([round((i + 1) / n - 0.0001, 6), c])
    cs[-1][0] = 1.0
    return cs

VAR_OPTIONS = [
    {"label": "Precipitation (mm/yr)",     "value": "OUT_PREC"},
    {"label": "Total ET (mm/yr)",           "value": "OUT_EVAP"},
    {"label": "Surface Runoff (mm/yr)",     "value": "OUT_RUNOFF"},
    {"label": "Baseflow (mm/yr)",           "value": "OUT_BASEFLOW"},
    {"label": "SWE (mm)",                   "value": "OUT_SWE"},
    {"label": "Soil Moisture (mm)",         "value": "OUT_SOIL_MOIST"},
    {"label": "Air Temperature (°C)",       "value": "OUT_AIR_TEMP"},
    {"label": "Snow Melt (mm/yr)",          "value": "OUT_SNOW_MELT"},
]

VAR_CMAPS = {
    "OUT_PREC":      "Blues",
    "OUT_EVAP":      "YlGn",
    "OUT_RUNOFF":    "Blues",
    "OUT_BASEFLOW":  "Purples",
    "OUT_SWE":       "ice",
    "OUT_SOIL_MOIST":"YlOrBr",
    "OUT_AIR_TEMP":  "RdYlBu_r",
    "OUT_SNOW_MELT": "Teal",
}

# Variables that have a pre-rendered spatial animation GIF (assets/animations/spatial_<VAR>.gif)
ANIM_VARS = set(VAR_CMAPS)

BASIN_ORDER = ["CRB", "UpperBasin", "LowerBasin", "Green", "SanJuan", "GrandCanyon", "Gila"]

BASEMAP_OPTIONS = [
    {"label": "Light (CartoDB)",    "value": "carto-positron"},
    {"label": " OpenStreetMap",       "value": "open-street-map"},
    {"label": "Satellite (ESRI)",    "value": "satellite"},
    {"label": " Dark (CartoDB)",      "value": "carto-darkmatter"},
    {"label": "Terrain",             "value": "stamen-terrain"},
]


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return pd.DataFrame()


def _empty(msg="Spatial data not available"):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper",
                       x=0.5, y=0.5, showarrow=False,
                       font=dict(size=12, color="#90a4ae"), align="center")
    fig.update_layout(paper_bgcolor="#f8f9fa", plot_bgcolor="#f8f9fa",
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      margin=dict(l=0, r=0, t=0, b=0), height=640)
    return fig


def _basin_label(bid):
    return {
        "CRB": "Colorado River Basin", "UpperBasin": "Upper Basin",
        "LowerBasin": "Lower Basin", "Green": "Green River",
        "SanJuan": "San Juan", "GrandCanyon": "Grand Canyon", "Gila": "Gila River",
    }.get(bid, bid)


def _snotel_elev_color(elev):
    for threshold, color, _ in SNOTEL_ELEV_TIERS:
        if elev < threshold:
            return color
    return SNOTEL_ELEV_TIERS[-1][1]


# ── Legend HTML overlay (absolute over map) ─────────────────
def _map_legend(layers):
    items = []

    if "basins" in layers:
        items.append(html.Div("Sub-Basins", style={
            "fontSize": "10px", "fontWeight": "700", "color": "#37474f",
            "textTransform": "uppercase", "letterSpacing": "0.5px", "marginBottom": "4px"}))
        for bid in ["UpperBasin", "LowerBasin", "Green", "SanJuan", "GrandCanyon", "Gila"]:
            fill = BASIN_FILL_COLORS[bid]
            label = BASIN_OUTLINE[bid]["label"]
            items.append(html.Div([
                html.Span("■", style={"color": fill, "fontSize": "13px", "marginRight": "6px"}),
                html.Span(label, style={"fontSize": "10px", "color": "#37474f"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "3px"}))

    if "snotel" in layers:
        if items:
            items.append(html.Hr(style={"margin": "5px 0", "borderColor": "#e0e0e0"}))
        items.append(html.Div("SNOTEL Stations (Elevation)", style={
            "fontSize": "10px", "fontWeight": "700", "color": "#37474f",
            "textTransform": "uppercase", "letterSpacing": "0.5px", "marginBottom": "4px"}))
        for _, color, label in SNOTEL_ELEV_TIERS:
            items.append(html.Div([
                html.Span("●", style={"color": color, "fontSize": "14px", "marginRight": "6px"}),
                html.Span(label, style={"fontSize": "10px", "color": "#37474f"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "3px"}))
        items.append(html.Div("◉ larger = has SWE trend data",
                              style={"fontSize": "9px", "color": "#1e293b", "marginTop": "3px"}))

    if "rivers" in layers:
        if items:
            items.append(html.Hr(style={"margin": "5px 0", "borderColor": "#e0e0e0"}))
        items.append(html.Div("Rivers & Drainage", style={
            "fontSize": "10px", "fontWeight": "700", "color": "#37474f",
            "textTransform": "uppercase", "letterSpacing": "0.5px", "marginBottom": "4px"}))
        for name, color in RIVER_COLORS.items():
            items.append(html.Div([
                html.Span("━", style={"color": color, "fontWeight": "900",
                                      "fontSize": "13px", "marginRight": "6px"}),
                html.Span(name, style={"fontSize": "10px", "color": "#37474f"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "3px"}))

    if "huc10" in layers:
        if items:
            items.append(html.Hr(style={"margin": "5px 0", "borderColor": "#e0e0e0"}))
        items.append(html.Div([
            html.Span("─", style={"color": "rgba(78,52,46,0.6)", "fontWeight": "900",
                                   "fontSize": "12px", "marginRight": "6px"}),
            html.Span("HUC-10 Watersheds", style={"fontSize": "10px", "color": "#37474f"}),
        ], style={"display": "flex", "alignItems": "center"}))

    if not items:
        return html.Div()

    return html.Div(items, style={
        "position": "absolute",
        "bottom": "28px",
        "left": "8px",
        "zIndex": "1000",
        "background": "rgba(255,255,255,0.93)",
        "border": "1px solid #ddd",
        "borderRadius": "6px",
        "padding": "8px 10px",
        "minWidth": "160px",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.15)",
        "pointerEvents": "none",
    })


def layout():
    return html.Div([
        html.Div([
            html.H2("Maps Over Time"),
            html.P("Purpose: pick any two variables and watch them animate across the basin, water "
                   "year by water year (1984–2024). Each map has its own basin-average trend chart "
                   "in a separate panel below, so the maps stay large and clear."),
        ], className="tab-header"),

        html.Div([
            # Store for cycle-free map sync zoom
            dcc.Store(id="sp-zoom-store"),

            # ── Controls row: Left Var | Right Var | Year | Basemap | Mode | Layers ──
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("LEFT MAP", className="control-label"),
                        dcc.Dropdown(
                            id="sp-var", options=VAR_OPTIONS,
                            value="OUT_RUNOFF", clearable=False,
                            style={"fontSize": "12px"},
                        ),
                    ], xs=12, sm=6, md=4, lg=2),
                    dbc.Col([
                        html.Div("RIGHT MAP", className="control-label"),
                        dcc.Dropdown(
                            id="sp-var-right", options=VAR_OPTIONS,
                            value="OUT_SWE", clearable=False,
                            style={"fontSize": "12px"},
                        ),
                    ], xs=12, sm=6, md=4, lg=2),
                    dbc.Col([
                        html.Div("WATER YEAR", className="control-label"),
                        dcc.Slider(
                            id="sp-year", min=1983, max=2024, step=1, value=2024,
                            marks={y: str(y) for y in range(1990,2025,10)},
                            tooltip={"placement": "bottom", "always_visible": False},
                        ),
                    ], xs=12, sm=12, md=4, lg=3),
                    # BASE MAP control hidden — the maps are tile-free static images,
                    # so a basemap/satellite selector has no effect. Kept (display:none)
                    # only so the existing callbacks that read sp-basemap still resolve.
                    dbc.Col([
                        dcc.Dropdown(
                            id="sp-basemap", options=BASEMAP_OPTIONS,
                            value="carto-positron", clearable=False,
                        ),
                    ], style={"display": "none"}),
                    # MAP MODE + LAYERS live together in one column, side by side
                    dbc.Col([
                        html.Div([
                            # ── MAP MODE block ──
                            html.Div([
                                html.Div([
                                    html.Span("MAP MODE", className="control-label"),
                                    info_dot([
                                        html.Div([html.B("Basin"), " — each sub-basin shaded by its "
                                                  "average value (how managers see the basin)."]),
                                        html.Div([html.B("Grid"), " — the full ~6 km VIC grid: fine "
                                                  "spatial detail of where values are high or low."]),
                                        html.Div([html.B("Trend"), " — the long-term rate of change "
                                                  "at each location (where it is changing fastest)."]),
                                        html.Div([html.B("Period Δ"), " — the difference between two "
                                                  "periods you choose (recent vs earlier)."]),
                                    ]),
                                ], style={"display": "flex", "alignItems": "center"}),
                                dbc.RadioItems(
                                    id="sp-map-mode",
                                    options=[
                                        {"label": "Basin",   "value": "basin"},
                                        {"label": "Grid",    "value": "grid"},
                                        {"label": "Trend",   "value": "trend"},
                                        {"label": "Period Δ","value": "compare"},
                                    ],
                                    value="grid", inline=False,
                                    inputStyle={"marginRight": "5px"},
                                    labelStyle={"marginRight": "10px", "fontSize": "12px",
                                                "whiteSpace": "nowrap", "display": "block"},
                                ),
                            ], style={"flex": "1 1 95px", "minWidth": "90px"}),
                            # ── LAYERS block (right beside MAP MODE) ──
                            html.Div([
                                html.Div("LAYERS", className="control-label"),
                                dcc.Checklist(
                                    id="sp-layers",
                                    options=[
                                        {"label": " Basins", "value": "basins"},
                                        {"label": " SNOTEL", "value": "snotel"},
                                        {"label": " Rivers", "value": "rivers"},
                                        {"label": " HUC-10", "value": "huc10"},
                                    ],
                                    value=["basins", "snotel", "rivers"],
                                    inline=False,
                                    inputStyle={"marginRight": "5px"},
                                    labelStyle={"marginRight": "8px", "fontSize": "12px",
                                                "whiteSpace": "nowrap", "display": "block"},
                                ),
                            ], style={"flex": "1 1 95px", "minWidth": "90px"}),
                        ], style={"display": "flex", "flexWrap": "wrap", "gap": "18px"}),
                    ], xs=12, sm=12, md=6, lg=3),
                ]),
            ], className="control-panel"),

            # How-to-use strip
            html.Div([
                html.I(className="bi bi-info-circle", style={"marginRight": "7px", "color": BLUE}),
                html.B("How to use:  "),
                "hover a sub-basin for its average · click-drag to pan · scroll or +/− to zoom · "
                "the magnifier searches regions · use the toolbar to download the figure.  ",
                html.A("Methods & data →", href="/methods",
                       style={"color": BLUE, "fontWeight": "600", "textDecoration": "underline"}),
            ], className="howto-strip"),

            # SNOTEL disclaimer note
            html.Div(
                "Note: SNOTEL layer shows all 103 stations with available records in the CRB. ""SNOTEL stations do not have basin assignments in the current dataset — ""the basin selector above applies to VIC grid variables only.",
                style={"fontSize":"10.5px","color":"#1e293b","padding":"3px 10px 6px",
                       "fontStyle":"italic"}
            ),

            # Period compare controls (hidden unless mode=compare)
            html.Div(id="sp-compare-ctrl", style={"display": "none"}, children=[
                html.Div([
                    dbc.Row([
                        dbc.Col([
                            html.Div("PERIOD A", className="control-label"),
                            dcc.RangeSlider(
                                id="sp-period-a", min=1983, max=2024, step=1,
                                value=[1983, 2001],
                                marks={y: str(y) for y in [1983, 1990, 2001, 2010, 2024]},
                                tooltip={"placement": "bottom", "always_visible": False},
                            ),
                        ], md=5),
                        dbc.Col([
                            html.Div("PERIOD B", className="control-label"),
                            dcc.RangeSlider(
                                id="sp-period-b", min=1983, max=2024, step=1,
                                value=[2010, 2024],
                                marks={y: str(y) for y in [1983, 1990, 2001, 2010, 2024]},
                                tooltip={"placement": "bottom", "always_visible": False},
                            ),
                        ], md=5),
                        dbc.Col([
                            html.Div("SHOW", className="control-label"),
                            dbc.RadioItems(
                                id="sp-compare-show",
                                options=[{"label": "% Change", "value": "pct"},
                                         {"label": "Absolute Δ", "value": "abs"}],
                                value="pct", inline=True,
                                labelStyle={"fontSize": "12px", "marginRight": "8px"},
                            ),
                        ], md=2),
                    ]),
                ], className="control-panel mt-0 pt-2"),
            ]),

            # ── Info tiles ABOVE the maps (what is being shown) ───
            html.Div(id="sp-tiles", className="mb-2",
                     style={"display": "grid",
                            "gridTemplateColumns": "repeat(auto-fit,minmax(150px,1fr))",
                            "gap": "10px"}),

            html.Div(id="sp-findings", style={
                "background": "#e8f5e9", "border": "1px solid #a5d6a7",
                "borderRadius": "6px", "padding": "8px 16px",
                "fontSize": "12px", "color": "#2e7d32", "marginBottom": "12px",
            }),

            # ── Interactive mapbox maps + charts — hidden (superseded by the static image maps).
            #    Retained in the layout so their callbacks remain valid; not shown to the user.
            html.Div([
              dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div(id="sp-left-map-title", className="crb-card-header",
                                 style={"fontWeight": "700", "fontSize": "13px",
                                        "textAlign": "center"}),
                        html.Div([
                            dcc.Loading(
                                dcc.Graph(
                                    id="sp-left-map",
                                    config={
                                        "displayModeBar": True,
                                        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                                        "scrollZoom": True,
                                    },
                                    style={"height": "560px"},
                                ),
                                type="circle", color=MAROON,
                            ),
                            html.Div(id="sp-map-legend"),
                        ], style={"position": "relative"}),
                    ], className="crb-card"),
                ], md=6, className="mapduo-col"),

                dbc.Col([
                    html.Div([
                        html.Div(id="sp-right-map-title", className="crb-card-header",
                                 style={"fontWeight": "700", "fontSize": "13px",
                                        "textAlign": "center"}),
                        html.Div([
                            dcc.Loading(
                                dcc.Graph(
                                    id="sp-right-map",
                                    config={
                                        "displayModeBar": True,
                                        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                                        "scrollZoom": True,
                                    },
                                    style={"height": "560px"},
                                ),
                                type="circle", color=MAROON,
                            ),
                            html.Div(id="sp-map-legend-right"),
                        ], style={"position": "relative"}),
                    ], className="crb-card"),
                ], md=6, className="mapduo-col"),
            ], className="g-3 mb-2 mapduo-row"),

            # ── Charts BELOW the maps (the data behind each map) ──
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div(id="sp-left-chart-title", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "12.5px"}),
                    dcc.Loading(dcc.Graph(id="sp-left-chart", config={"displayModeBar": False},
                                          style={"height": "300px"}), type="circle", color=MAROON),
                ], className="crb-card"), md=6, className="mapduo-col"),
                dbc.Col(html.Div([
                    html.Div(id="sp-right-chart-title", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "12.5px"}),
                    dcc.Loading(dcc.Graph(id="sp-right-chart", config={"displayModeBar": False},
                                          style={"height": "300px"}), type="circle", color=MAROON),
                ], className="crb-card"), md=6, className="mapduo-col"),
              ], className="g-3 mb-2 mapduo-row"),
            ], style={"display": "none"}),  # end hidden maps + charts block

            # ── Map summary strip (full width) ────────────────────
            dbc.Row([
                dbc.Col([
                    html.Div(id="sp-map-summary-strip", style={
                        "background": "#f0f4f8", "border": "1px solid #cfd8dc",
                        "borderRadius": "6px", "padding": "8px 16px",
                        "fontSize": "12px", "color": "#1e293b",
                        "display": "flex", "flexWrap": "wrap", "gap": "20px",
                    }),
                ], xs=12),
            ], className="g-2 mb-2"),

            # ── Download the side-by-side comparison as a PDF (all years) ─
            html.Div([
                dbc.Button([html.I(className="bi bi-file-earmark-pdf"),
                            " Download comparison (all years, PDF)"],
                           id="sp-pdf-btn", size="sm", color="secondary", outline=True,
                           n_clicks=0),
                dcc.Download(id="sp-pdf-download"),
            ], style={"textAlign": "right", "marginBottom": "8px"}),

            # ── LEFT MAP + RIGHT MAP — two static image maps side by side ─
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div(id="sp-basin-choro-title", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "12.5px"}),
                    dcc.Loading(
                        html.Div(
                            html.Img(id="sp-basin-choro-img",
                                     style={"width": "100%", "maxWidth": "440px",
                                            "height": "auto", "display": "block",
                                            "margin": "0 auto", "borderRadius": "8px"}),
                            style={"padding": "12px", "textAlign": "center"}),
                        type="circle", color=MAROON),
                ], className="crb-card"), xs=12, lg=6, className="mapduo-col"),
                dbc.Col(html.Div([
                    html.Div(id="sp-basin-choro-title-right", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "12.5px"}),
                    dcc.Loading(
                        html.Div(
                            html.Img(id="sp-basin-choro-img-right",
                                     style={"width": "100%", "maxWidth": "440px",
                                            "height": "auto", "display": "block",
                                            "margin": "0 auto", "borderRadius": "8px"}),
                            style={"padding": "12px", "textAlign": "center"}),
                        type="circle", color=MAROON),
                ], className="crb-card"), xs=12, lg=6, className="mapduo-col"),
            ], className="g-3 mb-2 mapduo-row"),

            # ── Basin-average trend charts — SEPARATE containers below the maps ──
            #    (so the maps above stay large and uncluttered)
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div(id="sp-choro-graph-title", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "12.5px"}),
                    dcc.Loading(
                        html.Div(
                            html.Img(id="sp-choro-graph-img",
                                     style={"width": "100%", "maxWidth": "540px",
                                            "height": "auto", "display": "block",
                                            "margin": "0 auto"}),
                            style={"padding": "10px", "textAlign": "center"}),
                        type="circle", color=MAROON),
                ], className="crb-card"), xs=12, lg=6, className="mapduo-col"),
                dbc.Col(html.Div([
                    html.Div(id="sp-choro-graph-title-right", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "12.5px"}),
                    dcc.Loading(
                        html.Div(
                            html.Img(id="sp-choro-graph-img-right",
                                     style={"width": "100%", "maxWidth": "540px",
                                            "height": "auto", "display": "block",
                                            "margin": "0 auto"}),
                            style={"padding": "10px", "textAlign": "center"}),
                        type="circle", color=MAROON),
                ], className="crb-card"), xs=12, lg=6, className="mapduo-col"),
            ], className="g-3 mb-2 mapduo-row"),

            # table removed — the info is shown on the maps themselves.
            # hidden placeholder keeps the (unused) table callback valid.
            html.Div(id="sp-basin-table", style={"display": "none"}),

            # ── Findings bar ──────────────────────────────────────

            # ── Contextual Intelligence Panels ───────────────────
            html.Div(id="sp-context-panels", style={"marginTop": "8px"}),

            # Hidden dummy components kept for existing callbacks
            html.Div(style={"display": "none"}, children=[
                dcc.Graph(id="sp-main-map"),
                html.Div(id="sp-map-title"),
                html.Div(id="sp-table-title"),
                html.Div(id="sp-map-summary"),
            ]),

        ], className="tab-body"),
    ])


def _legend_row(color, label):
    return html.Div([
        html.Span("●", style={"color": color, "fontSize": "16px", "marginRight": "8px"}),
        html.Span(label, style={"fontSize": "11px", "color": "#37474f"}),
    ], style={"marginBottom": "5px", "display": "flex", "alignItems": "center"})


# ── Contextual intelligence content per variable ─────────────
_VAR_CONTEXT = {
    "OUT_RUNOFF": {
        "description": (
            "Surface runoff [mm/yr] from the VIC (Variable Infiltration Capacity) model ""represents the fraction of precipitation that flows overland to streams. ""High runoff sub-basins (Green River, Upper Colorado) drive the majority of ""water supply stored in Lake Powell and Lake Mead."),
        "guided": [
            "Green River basin (dark green) consistently shows the highest runoff — ""its high-elevation Wyoming headwaters receive orographic precipitation and deep snowpack.",
            "Lower Basin sub-basins (Grand Canyon, Gila) show markedly lower runoff due to ""arid conditions; much precipitation is lost to ET before reaching streams.",
            "Compare WY2002 (severe drought) vs WY2011 (high snowpack year) to see the ""year-to-year runoff variability that drives reservoir storage swings.",
        ],
        "findings": [
            "CRB-wide runoff declined ~15–20% from WY1983–2023, driven by rising temperatures increasing ET.",
            "Green River contributes ~30% of total CRB natural flow despite covering only ~15% of basin area.",
            "Post-2000 megadrought (2000–2022) produced the lowest 20-year runoff average in the VIC record.",
            "Upper Basin runoff sensitivity to temperature: +1°C approximately −5 to −8% runoff reduction.",
        ],
        "policy": [
            "Lee Ferry compact point allocations (7.5 MAF/yr Upper + 7.5 MAF/yr Lower) were based on ""1906–1922 data — a historically wet period. VIC shows that baseline overstates long-run supply.",
            "Adaptive management should account for the runoff-temperature feedback: as the Colorado ""Plateau warms, reservoir inflows will continue declining even in normal precipitation years.",
            "Green River basin management (Flaming Gorge releases) is critical to maintaining downstream ""storage, especially during multi-year drought sequences.",
        ],
    },
    "OUT_SWE": {
        "description": (
            "Snow Water Equivalent [mm] represents the water stored in the snowpack on April 1st ""(peak accumulation). Snowmelt from the Rocky Mountain headwaters provides ~85% of the ""Colorado River's annual natural flow, making SWE the primary seasonal water supply forecast."),
        "guided": [
            "Deep purple/blue areas in the Green River and Upper Colorado basins mark high-elevation ""snowpack zones (>3,000 m). These areas generate disproportionate runoff relative to their area.",
            "Low-elevation Lower Basin shows near-zero SWE — water supply here depends entirely on ""upstream snowmelt transported via reservoir storage and river routing.",
            "Use the Trend Map mode to see where snowpack has declined most since 1982 — ""the losses are concentrated in the 2,000–2,800 m elevation band.",
        ],
        "findings": [
            "April 1 SWE has declined significantly across the CRB since the 1980s, consistent ""with warming-driven earlier melt onset.",
            "SNOTEL stations above 3,000 m show more stable trends vs mid-elevation stations ""where the rain-snow transition zone is shifting upward.",
            "Low-SWE years (e.g., 2002, 2018, 2021) directly precede critically low reservoir levels ""with a 6–12 month lag.",
            "The snow-to-rain ratio in the CRB has shifted, reducing the 'natural reservoir' ""function of snowpack and increasing flood-drought volatility.",
        ],
        "policy": [
            "Water managers rely on April 1 SWE for seasonal forecasts — declining reliability of ""this metric requires probabilistic ensemble forecasting methods.",
            "Infrastructure designed around historical snowmelt timing (April–June peak flows) ""may need redesign as earlier melt (Feb–April) becomes more common.",
            "Drought contingency plans should use SWE anomaly as an early trigger rather than ""waiting for reservoir levels to fall below critical thresholds.",
        ],
    },
    "OUT_EVAP": {
        "description": (
            "Total evapotranspiration [mm/yr] represents the combined water loss through ""evaporation from soil/water surfaces and transpiration by vegetation. ""ET is the dominant water loss term in the CRB water balance, consuming ""~80–90% of annual precipitation across most sub-basins."),
        "guided": [
            "High ET in the Lower Basin (Gila, Lower Colorado) reflects the combination of ""warm temperatures, irrigated agriculture, and riparian vegetation demand.",
            "Upper Basin shows lower absolute ET but is more sensitive to temperature changes — ""small warming drives outsized increases in potential ET due to vapor pressure deficit.",
            "Compare ET vs Runoff maps: where ET is high, runoff is low, illustrating the ""fundamental trade-off governing water availability.",
        ],
        "findings": [
            "VIC ET increased by +8 to +15 mm/yr per decade across most CRB sub-basins from WY1983–2023.",
            "Rising ET partially offsets any precipitation increases, meaning more rain does not ""necessarily translate to more runoff under warming scenarios.",
            "ET trends explain ~60% of the observed runoff decline in the Upper Basin — ""the remainder is attributable to precipitation variability.",
            "Gila River basin has the highest ET/precipitation ratio (>0.90), leaving minimal ""water for streamflow generation.",
        ],
        "policy": [
            "Agricultural irrigation efficiency improvements in the Lower Basin could reduce ""consumptive ET losses and free water for in-stream flows.",
            "Urban landscape conversion (turf removal, xeriscape) in Phoenix/Tucson metros ""can meaningfully reduce municipal ET demand.",
            "Climate projections (RCP 4.5/8.5) show ET increasing 10–25% by 2100, ""implying structural water deficits that cannot be managed through demand reduction alone.",
        ],
    },
    "OUT_PREC": {
        "description": (
            "Annual precipitation [mm/yr] from LIVNEH gridded meteorological data, ""disaggregated to VIC model grid cells. Precipitation in the CRB is highly ""variable in space (200–1,400 mm/yr) and time (ENSO-driven inter-annual swings), ""making drought prediction challenging."),
        "guided": [
            "Mountain ranges (San Juan Mtns, Uinta Mtns, Mogollon Rim) stand out as ""high-precipitation zones driven by orographic lifting.",
            "The Lower Basin receives much of its precipitation as summer monsoon rainfall (Jul–Sep), ""which is less efficient at generating runoff than winter snowfall.",
            "Compare precipitation vs runoff maps: the runoff coefficient (runoff/precip) is ""dramatically lower in the Lower Basin than Upper Basin.",
        ],
        "findings": [
            "No statistically significant long-term precipitation trend in the CRB as a whole, ""but variance has increased — wetter wet years, drier dry years.",
            "Winter precipitation (Oct–Mar) drives streamflow; summer monsoon precipitation ""is largely consumed by ET with minimal contribution to annual runoff.",
            "The 2000–2004 and 2020–2022 droughts were driven by both precipitation deficits ""and concurrent temperature anomalies amplifying ET losses.",
        ],
        "policy": [
            "Atmospheric river events provide a significant fraction of annual precipitation ""in wet years — forecasting these extreme events is critical for reservoir operations.",
            "Water supply planning should use probabilistic precipitation scenarios rather than ""single 'average' year assumptions given high inter-annual variability.",
        ],
    },
    "OUT_AIR_TEMP": {
        "description": (
            "Mean annual air temperature [°C] from LIVNEH gridded observations. ""Temperature is the primary driver of evapotranspiration demand and determines ""the rain-snow partitioning threshold critical to water supply timing."),
        "guided": [
            "Temperature decreases sharply with elevation — Lower Basin deserts (Gila, Lower Colo) ""average 15–22°C while Upper Basin headwaters average 2–8°C annually.",
            "Use the Trend Map mode to visualize warming rates: the CRB has warmed ""+1.0 to +1.5°C since 1982, with higher rates at lower elevations.",
            "Compare temperature trends to SWE trends — the elevation band where temperature ""crossed the 0°C winter threshold explains where snowpack has declined most.",
        ],
        "findings": [
            "The CRB has warmed approximately +1.2°C from WY1983–2023, faster than the global average.",
            "Warming is asymmetric — nighttime minimum temperatures have risen faster than ""daytime maxima, increasing overall ET demand.",
            "The elevation of the freezing isotherm has shifted upward by approximately ""150–200 m, reducing the area that receives snowfall vs rain.",
            "Temperature extremes (>35°C days) have increased significantly in the Lower Basin, ""increasing urban and agricultural cooling demand.",
        ],
        "policy": [
            "Temperature-based drought indices (PDSI, SPEI) better capture the compounding ""effect of warming on water stress than precipitation-only metrics.",
            "Energy-water nexus: increased cooling demand in hot years coincides with reduced ""hydropower generation — a double-stress on the western grid.",
            "Without significant emissions reductions, CRB temperatures may reach +3–5°C ""above pre-industrial levels by 2100, fundamentally altering water availability.",
        ],
    },
    "OUT_BASEFLOW": {
        "description": (
            "Baseflow [mm/yr] is the slow, sustained groundwater contribution to streamflow ""between storm events. It maintains perennial flows in rivers during dry seasons ""and is critical for aquatic ecosystems, riparian vegetation, and late-season water supply."),
        "guided": [
            "High baseflow in the Green and Upper Colorado basins reflects deep, well-developed ""alluvial aquifers recharged by snowmelt infiltration.",
            "Compare baseflow to surface runoff: sub-basins with high baseflow/total-flow ratios ""have more stable year-round streamflow and are more drought-resilient.",
            "Gila River basin shows very low baseflow due to its semi-arid geology and extensive ""groundwater pumping that has depleted shallow aquifers.",
        ],
        "findings": [
            "Baseflow has declined across the CRB in parallel with snowpack reductions, ""as shallower/earlier snowmelt reduces deep soil infiltration and aquifer recharge.",
            "The ratio of baseflow to total streamflow is declining, meaning rivers are becoming ""more 'flashy' — higher peak flows and lower low flows.",
            "Groundwater-dependent ecosystems (cottonwood-willow riparian corridors) are showing ""stress in sub-basins with declining baseflow trends.",
        ],
        "policy": [
            "Groundwater-surface water interactions are often ignored in water rights systems — ""pumping regulations need to account for impacts on baseflow and connected streams.",
            "Managed aquifer recharge (MAR) programs could help restore baseflow by banking ""surplus flood flows underground for later low-flow season release.",
        ],
    },
    "OUT_SOIL_MOIST": {
        "description": (
            "Vertically-integrated soil moisture [mm] across VIC model soil layers. ""Soil moisture determines how much subsequent precipitation becomes runoff vs ""infiltration, and controls vegetation water stress and ET rates."),
        "guided": [
            "High soil moisture in mountain zones reflects both precipitation and the slow ""release of snowmelt keeping soils wet through late spring.",
            "Lower Basin soils are persistently dry — the vadose zone (unsaturated soil) ""acts as a 'deficit reservoir' that must fill before runoff can occur.",
            "Compare pre-drought vs drought years: soil moisture anomalies in spring can ""predict summer runoff deficits 2–3 months in advance.",
        ],
        "findings": [
            "Soil moisture has declined across most CRB sub-basins since the 1980s, ""consistent with increasing atmospheric demand (ET) outpacing precipitation.",
            "Wet antecedent soil moisture conditions (La Niña to El Niño transitions) ""amplify runoff response to individual storm events.",
            "SMAP satellite soil moisture (2015–present) shows good agreement with VIC ""simulated soil moisture, validating the model's representation.",
        ],
        "policy": [
            "Soil moisture monitoring networks (SCAN, CoCoRaHS) can improve short-term ""streamflow and flood forecasting by providing real-time antecedent conditions.",
            "Post-fire hydrology in the CRB is strongly modulated by soil moisture — ""burned watersheds with dry soils are prone to debris flows after heavy rainfall.",
        ],
    },
    "OUT_SNOW_MELT": {
        "description": (
            "Annual snowmelt [mm/yr] represents the seasonal conversion of snowpack ""into liquid water available for runoff and infiltration. Peak snowmelt ""drives the spring freshet — the most important seasonal flow event ""for filling reservoirs and supporting aquatic ecosystems."),
        "guided": [
            "Snowmelt is concentrated in the high-elevation Green River and Upper Colorado ""sub-basins, where snowpack persists through April or May.",
            "Low-elevation areas show minimal snowmelt — their winter precipitation arrives ""as rain or melts immediately, with no storage in the snowpack.",
            "Compare snowmelt to SWE: sub-basins with high SWE but moderate snowmelt have ""efficient seasonal release; low-SWE high-melt areas have little storage buffer.",
        ],
        "findings": [
            "Snowmelt timing has shifted earlier by approximately 1–2 weeks since 1982, ""reducing late-season (Jun–Aug) flows when demand is highest.",
            "The melt rate (mm/day) during peak melt events has increased due to warming, ""increasing flood risk while shortening the melt season.",
            "Earlier snowmelt creates a longer dry season before monsoon onset, ""increasing summer fire risk and water stress for vegetation.",
        ],
        "policy": [
            "Reservoir operations must adapt to earlier peak inflows — current operating ""rules designed for May–June peak flows need revision for March–April peaks.",
            "Earlier snowmelt and longer dry periods increase late-summer wildfire risk, ""which in turn affects watershed hydrology through vegetation changes and erosion.",
        ],
    },
}

def _make_context_panels(var, year, mode):
    """Build the contextual intelligence accordion below the map."""
    ctx = _VAR_CONTEXT.get(var, {})
    if not ctx:
        return html.Div()

    vname = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
    mode_label = {"basin": "Basin Choropleth", "grid": "VIC Grid",
                  "trend": "Trend Map", "compare": "Period Comparison",
                  "sidebyside": "Side-by-Side"}.get(mode, mode)

    def panel(color, border, title, icon, content_rows):
        return html.Div([
            html.Div(
                html.Div([
                    html.Span(icon, style={"marginRight": "8px"}),
                    html.Span(title, style={"fontWeight": "600"}),
                    html.Span("▾", style={"float": "right", "fontSize": "12px", "opacity": "0.6"}),
                ], style={"cursor": "pointer", "userSelect": "none"}),
                style={
                    "background": color, "padding": "10px 16px",
                    "borderRadius": "6px 6px 0 0" if True else "6px",
                    "color": "#fff", "fontSize": "13px",
                },
            ),
            html.Div(content_rows, style={
                "background": "#fff", "border": f"1px solid {border}",
                "borderTop": "none", "borderRadius": "0 0 6px 6px",
                "padding": "12px 16px", "fontSize": "12.5px", "color": "#37474f",
                "lineHeight": "1.7",
            }),
        ], style={"marginBottom": "8px"})

    def bullet_rows(items, bullet_color):
        return [html.Div([
            html.Span("●", style={"color": bullet_color, "marginRight": "8px",
                                   "fontSize": "10px", "verticalAlign": "middle"}),
            html.Span(item),
        ], style={"marginBottom": "6px"}) for item in items]

    return html.Div([
        # Figure description
        html.Div([
            html.Span("", style={"marginRight": "6px"}),
            html.Strong("Figure Description: "),
            f"Showing {vname} ({mode_label}) for the Colorado River Basin. ",
            ctx["description"],
            html.Br(),
            html.Span("Map values are computed live from the VIC reanalysis record. The “Findings” and "
                      "“Implications” panels below summarize published literature and domain context "
                      "(not all values are recomputed in this view).",
                      style={"fontSize": "10.5px", "color": "#1e293b", "fontStyle": "italic"}),
        ], style={
            "background": "#f0f4f8", "border": "1px solid #cfd8dc",
            "borderLeft": "4px solid #1565C0", "borderRadius": "0 6px 6px 0",
            "padding": "10px 16px", "fontSize": "12.5px", "color": "#37474f",
            "marginBottom": "10px", "lineHeight": "1.7",
        }),

        dbc.Row([
            # Guided Analysis
            dbc.Col(panel(
                "#1565C0", "#bbdefb", "Guided Analysis", " ",
                [html.Div([
                    html.Div(f"Step {i+1}:", style={"fontWeight": "600", "color": "#1565C0",
                                                     "marginBottom": "2px", "fontSize": "11px"}),
                    html.Div(step, style={"marginBottom": "10px"}),
                ], style={"borderLeft": "3px solid #bbdefb", "paddingLeft": "10px"})
                for i, step in enumerate(ctx.get("guided", []))],
            ), md=4),

            # Key Research Findings
            dbc.Col(panel(
                "#2E7D32", "#c8e6c9", "Key Research Findings", " ",
                bullet_rows(ctx.get("findings", []), "#2E7D32"),
            ), md=4),

            # Water Management Implications
            dbc.Col(panel(
                "#B71C1C", "#ffcdd2", "Water Management Implications", "",
                bullet_rows(ctx.get("policy", []), "#B71C1C"),
            ), md=4),
        ], className="g-2"),
    ])


# ─────────────────────────────────────────────────────────────
def _sp_tile(value, label, color):
    return html.Div([html.Div(value, className="info-tile-value"),
        html.Div(label, className="info-tile-label")], className=f"info-tile {color}")


def _data_chart(var, year, mode, pa, pb, cshow):
    """A bar chart of the data behind the map: per-basin values / trend / period-Δ."""
    df = _safe(load_vic_annual)
    vname = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
    if df.empty or var not in df.columns:
        return _empty("Run preprocessing to see the chart."), f"{vname}"
    basins = BASIN_ORDER
    recs = []
    if mode == "trend":
        from scipy import stats
        for b in basins:
            d = df[df["basin"] == b].sort_values("water_year").dropna(subset=[var])
            if len(d) < 5: continue
            sl, _, _, p, _ = stats.linregress(d["water_year"], d[var])
            recs.append((_basin_label(b), sl, p))
        recs.sort(key=lambda x: x[1])
        names = [r[0] for r in recs]; vals = [r[1] for r in recs]
        cols = ["#B71C1C" if v < 0 else "#1565C0" for v in vals]
        title = f"{vname} — Mann-Kendall trend (per year), WY1984–2024"
        xlab = "slope / yr"
    elif mode == "compare" and pa and pb:
        for b in basins:
            ma = df[(df["basin"] == b) & df["water_year"].between(pa[0], pa[1])][var].mean()
            mb = df[(df["basin"] == b) & df["water_year"].between(pb[0], pb[1])][var].mean()
            if pd.notna(ma) and pd.notna(mb) and abs(ma) > 0.01:
                v = (mb - ma) / abs(ma) * 100 if cshow == "pct" else (mb - ma)
                recs.append((_basin_label(b), v, None))
        recs.sort(key=lambda x: x[1])
        names = [r[0] for r in recs]; vals = [r[1] for r in recs]
        cols = ["#B71C1C" if v < 0 else "#1565C0" for v in vals]
        title = f"{vname} — change {pa[0]}–{pa[1]} → {pb[0]}–{pb[1]}"
        xlab = "% change" if cshow == "pct" else "absolute Δ"
    else:  # basin / grid → BOX PLOT: each sub-basin's annual distribution (1984–2024)
        cmap = {"OUT_RUNOFF": BLUE, "OUT_SWE": "#0277BD", "OUT_AIR_TEMP": "#C62828",
                "OUT_EVAP": GREEN, "OUT_PREC": NAVY, "OUT_SOIL_MOIST": ORANGE,
                "OUT_BASEFLOW": PURPLE, "OUT_SNOW_MELT": TEAL}
        col = cmap.get(var, MAROON)
        meds = []
        for b in basins:
            s = df[df["basin"] == b][var].dropna()
            if not s.empty:
                meds.append((b, s.median()))
        meds.sort(key=lambda x: x[1], reverse=True)
        cats = [_basin_label(b) for b, _ in meds]
        series = [list(df[df["basin"] == b][var].dropna().values) for b, _ in meds]
        if not cats:
            return _empty("No data"), vname
        fig = box_v(cats, series, [col] * len(cats), y_title=vname, height=300)
        return fig, f"{vname} — distribution by sub-basin (1984–2024)"
    if not recs:
        return _empty("No data"), vname
    diverging = mode in ("trend", "compare")
    fig = dot_h(names, vals, cols, x_title=xlab, height=300, diverging=diverging)
    return fig, title


def register_callbacks(app):

    # ── Download the side-by-side comparison maps as a PDF ──
    @app.callback(
        Output("sp-pdf-download", "data"),
        Input("sp-pdf-btn", "n_clicks"),
        State("sp-var", "value"),
        State("sp-var-right", "value"),
        prevent_initial_call=True,
    )
    def _sp_download_pdf(n, varA, varB):
        import io as _io, numpy as _np
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages

        def _grid_page(pdf, var):
            df = _safe(load_spatial, var)
            if df is None or df.empty:
                return
            name = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
            years = sorted(int(y) for y in df["water_year"].unique())
            v = df["value"].to_numpy(dtype=float)
            vmin = float(_np.nanpercentile(v, 2)); vmax = float(_np.nanpercentile(v, 98))
            if vmax <= vmin:
                vmax = vmin + 1.0
            # VAR_CMAPS holds Plotly colorscale names; translate to a valid Matplotlib one
            _mpl = {"ice": "Blues", "Teal": "GnBu"}
            cmap = VAR_CMAPS.get(var, "viridis")
            cmap = _mpl.get(cmap, cmap)
            try:
                import matplotlib.cm as _cm
                _cm.get_cmap(cmap)
            except Exception:
                cmap = "viridis"
            ncol = 7
            nrow = int(_np.ceil(len(years) / ncol))
            fig, axes = plt.subplots(nrow, ncol, figsize=(11, 1.5 * nrow + 1.1), dpi=85)
            axes = _np.array(axes).reshape(-1)
            fig.suptitle(f"CORA — {name}: every water year, 1984–2024",
                         fontsize=13, weight="bold", color="#0d2137")
            mesh = None
            for i, y in enumerate(years):
                ax = axes[i]; ax.set_xticks([]); ax.set_yticks([])
                s = df[df["water_year"] == y]
                piv = s.pivot_table(index="lat", columns="lon", values="value")
                mesh = ax.pcolormesh(piv.columns.values, piv.index.values,
                                     _np.ma.masked_invalid(piv.values),
                                     cmap=cmap, vmin=vmin, vmax=vmax, shading="nearest",
                                     rasterized=True)
                ax.set_title(str(y), fontsize=7.5, color="#333")
                ax.set_aspect(1.0 / _np.cos(_np.deg2rad(37.5)))
                for sp in ax.spines.values():
                    sp.set_edgecolor("#cfd8dc")
            for j in range(len(years), len(axes)):
                axes[j].axis("off")
            if mesh is not None:
                cax = fig.add_axes([0.35, 0.035, 0.3, 0.012])
                cb = fig.colorbar(mesh, cax=cax, orientation="horizontal")
                cb.set_label(name, fontsize=8)
            fig.text(0.5, 0.005,
                     "Colorado River Basin · VIC 5.0 PRISM-calibrated reanalysis · "
                     "CHI Research Group, ASU · developed by Pradeepika (Praddy) Kaushik",
                     ha="center", fontsize=7, color="#666")
            fig.tight_layout(rect=[0, 0.06, 1, 0.955])
            pdf.savefig(fig); plt.close(fig)

        buf = _io.BytesIO()
        with PdfPages(buf) as pdf:
            _grid_page(pdf, varA)
            if varB and varB != varA:
                _grid_page(pdf, varB)
        buf.seek(0)
        return dcc.send_bytes(buf.read(), f"CORA_{varA}_vs_{varB}_1984-2024.pdf")

    # ── Info tiles above the maps + charts below ──────────────
    @app.callback(
        Output("sp-tiles", "children"),
        Input("sp-var", "value"), Input("sp-var-right", "value"),
        Input("sp-year", "value"), Input("sp-map-mode", "value"),
    )
    def _sp_tiles(varL, varR, year, mode):
        df = _safe(load_vic_annual)
        def stats_for(var, color):
            vname = next((o["label"].split("(")[0].strip() for o in VAR_OPTIONS if o["value"] == var), var)
            if df.empty or var not in df.columns:
                return [_sp_tile("—", vname, color)]
            sub = df[df["water_year"] == year]
            crb = sub[sub["basin"] == "CRB"][var]
            allb = sub[sub["basin"].isin(BASIN_ORDER)][var].dropna()
            crbv = f"{crb.iloc[0]:.0f}" if not crb.empty else "—"
            rng = f"{allb.min():.0f}–{allb.max():.0f}" if not allb.empty else "—"
            return [_sp_tile(crbv, f"{vname} — CRB · WY{year}", color),
                    _sp_tile(rng, f"{vname} — basin range", "tile-navy")]
        return stats_for(varL, "tile-maroon") + stats_for(varR, "tile-green")

    @app.callback(
        Output("sp-left-chart", "figure"), Output("sp-left-chart-title", "children"),
        Input("sp-var", "value"), Input("sp-year", "value"), Input("sp-map-mode", "value"),
        Input("sp-period-a", "value"), Input("sp-period-b", "value"), Input("sp-compare-show", "value"),
    )
    def _sp_left_chart(var, year, mode, pa, pb, cshow):
        fig, title = _data_chart(var, year, mode, pa, pb, cshow)
        return fig, "Left map data — " + title

    @app.callback(
        Output("sp-right-chart", "figure"), Output("sp-right-chart-title", "children"),
        Input("sp-var-right", "value"), Input("sp-year", "value"), Input("sp-map-mode", "value"),
        Input("sp-period-a", "value"), Input("sp-period-b", "value"), Input("sp-compare-show", "value"),
    )
    def _sp_right_chart(var, year, mode, pa, pb, cshow):
        fig, title = _data_chart(var, year, mode, pa, pb, cshow)
        return fig, "Right map data — " + title

    @app.callback(
        Output("sp-compare-ctrl", "style"),
        Input("sp-map-mode", "value"),
    )
    def toggle_compare(mode):
        return {"display": "block"} if mode == "compare" else {"display": "none"}

    @app.callback(
        Output("sp-map-title", "children"),
        Output("sp-table-title", "children"),
        Input("sp-var", "value"),
        Input("sp-map-mode", "value"),
        Input("sp-year", "value"),
    )
    def update_titles(var, mode, year):
        vname = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
        if mode == "basin":
            return f"Basin Values — {vname} · WY{year}", f" Basin Values — WY{year}"
        elif mode == "grid":
            return f"VIC Grid Heatmap — {vname} · WY{year}", f" Basin Means — WY{year}"
        elif mode == "trend":
            return f" Mann-Kendall Trend — {vname} · WY1983–2023", " Basin Trend Slopes"
        else:
            return f"Period Comparison — {vname}", " Period Change"

    # ── Legend overlay callbacks (left + right) ──────────────
    @app.callback(
        Output("sp-map-legend", "children"),
        Input("sp-layers", "value"),
    )
    def update_legend(layers):
        layers = layers or []
        return _map_legend(layers)

    @app.callback(
        Output("sp-map-legend-right", "children"),
        Input("sp-layers", "value"),
    )
    def update_legend_right(layers):
        layers = layers or []
        return _map_legend(layers)

    # ── Map summary strip (inline horizontal) ────────────────
    @app.callback(
        Output("sp-map-summary", "children"),
        Output("sp-map-summary-strip", "children"),
        Input("sp-var", "value"),
        Input("sp-year", "value"),
        Input("sp-layers", "value"),
        Input("sp-basemap", "value"),
    )
    def update_summary(var, year, layers, basemap):
        layers = layers or []
        bm_label = next((o["label"] for o in BASEMAP_OPTIONS if o["value"] == basemap), basemap)
        bm_clean = bm_label.replace(" ","").replace("","").replace(" ","").replace("","").replace(" ","")
        items = [
            ("WY", str(year)),
            (" Base Map", bm_clean),
            (" SNOTEL", "103 shown" if "snotel" in layers else "off"),
            ("HUC-10", "on" if "huc10" in layers else "off"),
            (" Rivers", "on" if "rivers" in layers else "off"),
            (" Boundaries", "CRB + Upper/Lower"),
            ("Area", "654,441 km²"),
        ]
        # Strip (horizontal, for new layout)
        strip_items = [
            html.Span([
                html.Strong(f"{label}: ", style={"color": "#37474f"}),
                html.Span(val, style={"color": "#1e293b"}),
            ], style={"whiteSpace": "nowrap"})
            for label, val in items
        ]
        return [], strip_items

    # ── Context panels callback ───────────────────────────────
    @app.callback(
        Output("sp-context-panels", "children"),
        Input("sp-var", "value"),
        Input("sp-year", "value"),
        Input("sp-map-mode", "value"),
    )
    def update_context(var, year, mode):
        return _make_context_panels(var, year, mode)

    # ── Main map callback ─────────────────────────────────────
    @app.callback(
        Output("sp-main-map", "figure"),
        Input("sp-var", "value"),
        Input("sp-year", "value"),
        Input("sp-map-mode", "value"),
        Input("sp-layers", "value"),
        Input("sp-period-a", "value"),
        Input("sp-period-b", "value"),
        Input("sp-compare-show", "value"),
        Input("sp-basemap", "value"),
    )
    def update_map(var, year, mode, layers, pa, pb, compare_show, basemap):
        layers = layers or []

        if mode == "basin":
            fig = _build_basin_choropleth(var, year, layers)
        elif mode == "grid":
            fig = go.Figure()
            df_sp = _safe(load_spatial, var)
            if df_sp.empty:
                return _empty(f"Run 01_basin_aggregation.py first\n(spatial/{var} not found)")
            sub = df_sp[df_sp["water_year"] == year]
            if sub.empty:
                return _empty(f"No data for WY{year}")
            cmap = VAR_CMAPS.get(var, "Viridis")
            fig.add_trace(go.Densitymapbox(
                lat=sub["lat"], lon=sub["lon"], z=sub["value"],
                radius=14, colorscale=cmap, opacity=0.75, showscale=True,
                colorbar=dict(thickness=12, len=0.6, x=0.01,
                              title=dict(text=var.replace("OUT_",""), font=dict(size=10))),
                hovertemplate="Lat: %{lat:.2f}<br>Lon: %{lon:.2f}<br>Value: %{z:.1f}<extra></extra>",
                name="VIC Grid",
            ))
            _add_overlays(fig, layers)
        elif mode == "trend":
            fig = _build_trend_map(var, layers)
        else:
            fig = _build_compare_map(var, pa, pb, compare_show, layers)

        # Basemap config — ESRI satellite as custom raster layer
        if basemap == "satellite":
            mapbox_cfg = dict(
                style="white-bg",
                center=dict(lat=37.5, lon=-111.5),
                zoom=5,
                layers=[{
                    "below": "traces",
                    "sourcetype": "raster",
                    "source": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
                    "sourceattribution": "Tiles © Esri",
                }],
            )
        else:
            mapbox_cfg = dict(
                style=basemap,
                center=dict(lat=37.5, lon=-111.5),
                zoom=5,
            )

        fig.update_layout(
            mapbox=mapbox_cfg,
            margin=dict(l=0, r=0, t=0, b=0),
            height=640,
            showlegend=False,
            paper_bgcolor="white",
            uirevision="map",
        )
        return fig

    # ── Side-by-Side map callbacks (always active) ───────────
    def _build_sbs_fig(var, year, layers, basemap, mode,
                       pa=None, pb=None, compare_show="pct"):
        if mode == "basin":
            fig = _build_basin_choropleth(var, year, layers)
        elif mode == "grid":
            fig = go.Figure()
            df_sp = _safe(load_spatial, var)
            if not df_sp.empty:
                sub = df_sp[df_sp["water_year"] == year]
                if not sub.empty:
                    cmap = VAR_CMAPS.get(var, "Viridis")
                    fig.add_trace(go.Densitymapbox(
                        lat=sub["lat"], lon=sub["lon"], z=sub["value"],
                        radius=14, colorscale=cmap, opacity=0.75, showscale=True,
                        colorbar=dict(thickness=12, len=0.6, x=0.01,
                                      title=dict(text=var.replace("OUT_",""), font=dict(size=10))),
                        hovertemplate="Lat: %{lat:.2f}<br>Lon: %{lon:.2f}<br>Value: %{z:.1f}<extra></extra>",
                    ))
            _add_overlays(fig, layers)
        elif mode == "trend":
            fig = _build_trend_map(var, layers)
        elif mode == "compare" and pa and pb:
            fig = _build_compare_map(var, pa, pb, compare_show, layers)
        else:
            fig = _build_basin_choropleth(var, year, layers)

        if basemap == "satellite":
            mapbox_cfg = dict(
                style="white-bg", center=dict(lat=37.5, lon=-111.5), zoom=5,
                layers=[{"below": "traces", "sourcetype": "raster",
                          "source": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
                          "sourceattribution": "Tiles © Esri"}],
            )
        else:
            mapbox_cfg = dict(style=basemap, center=dict(lat=37.5, lon=-111.5), zoom=5)
        fig.update_layout(
            mapbox=mapbox_cfg,
            margin=dict(l=0, r=0, t=0, b=0),
            height=560, showlegend=False,
            paper_bgcolor="white", uirevision=f"sbs-{var}",
        )
        return fig

    @app.callback(
        Output("sp-left-map", "figure"),
        Output("sp-left-map-title", "children"),
        Input("sp-var", "value"),
        Input("sp-year", "value"),
        Input("sp-layers", "value"),
        Input("sp-basemap", "value"),
        Input("sp-map-mode", "value"),
        Input("sp-period-a", "value"),
        Input("sp-period-b", "value"),
        Input("sp-compare-show", "value"),
    )
    def update_left_map(var, year, layers, basemap, mode, pa, pb, cshow):
        layers = layers or []
        vname = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
        mode_label = {"basin":"Basin Values","grid":"VIC Grid","trend":"Trend Map","compare":"Period Δ"}.get(mode,"")
        title = f" {vname}  |  {mode_label} · WY{year}"
        return _build_sbs_fig(var, year, layers, basemap, mode, pa, pb, cshow), title

    @app.callback(
        Output("sp-right-map", "figure"),
        Output("sp-right-map-title", "children"),
        Input("sp-var-right", "value"),
        Input("sp-year", "value"),
        Input("sp-layers", "value"),
        Input("sp-basemap", "value"),
        Input("sp-map-mode", "value"),
        Input("sp-period-a", "value"),
        Input("sp-period-b", "value"),
        Input("sp-compare-show", "value"),
    )
    def update_right_map(var_right, year, layers, basemap, mode, pa, pb, cshow):
        layers = layers or []
        vname = next((o["label"] for o in VAR_OPTIONS if o["value"] == var_right), var_right)
        mode_label = {"basin":"Basin Values","grid":"VIC Grid","trend":"Trend Map","compare":"Period Δ"}.get(mode,"")
        title = f"{vname}  |  {mode_label} · WY{year} "
        return _build_sbs_fig(var_right, year, layers, basemap, mode, pa, pb, cshow), title

    # ── Basin value table ─────────────────────────────────────
    @app.callback(
        Output("sp-basin-table", "children"),
        Input("sp-var", "value"),
        Input("sp-year", "value"),
        Input("sp-map-mode", "value"),
        Input("sp-period-a", "value"),
        Input("sp-period-b", "value"),
    )
    def update_table(var, year, mode, pa, pb):
        df = _safe(load_vic_annual)
        if df.empty or var not in df.columns:
            return html.P("Data not available",
                          style={"color": "#1e293b", "fontSize": "11px", "padding": "12px"})

        if mode in ("basin", "grid"):
            sub = df[df["water_year"] == year][["basin", var]].copy()
            sub = sub.sort_values(var, ascending=False)
            rows = [html.Tr([
                html.Th("Basin",        style=_th()),
                html.Th(f"WY{year}",    style={**_th(), "textAlign": "right"}),
                html.Th("Rank",         style={**_th(), "textAlign": "center"}),
            ])]
            all_vals = df[df["water_year"] == year][var].dropna()
            for _, row in sub.iterrows():
                v = row[var]
                pct = (all_vals <= v).mean() * 100 if not all_vals.empty else None
                bid = row["basin"]
                bc = BASIN_OUTLINE.get(bid, {}).get("color", NAVY)
                rows.append(html.Tr([
                    html.Td([
                        html.Span("■", style={"color": bc, "marginRight": "5px", "fontSize": "11px"}),
                        _basin_label(bid),
                    ], style=_td()),
                    html.Td(f"{v:.1f}", style={**_td(), "textAlign": "right",
                                               "fontWeight": "600", "color": NAVY}),
                    html.Td(f"{pct:.0f}th" if pct else "—",
                            style={**_td(), "textAlign": "center", "color": "#1e293b"}),
                ]))

        elif mode == "trend":
            from scipy import stats
            rows = [html.Tr([
                html.Th("Basin",     style=_th()),
                html.Th("Slope/yr",  style={**_th(), "textAlign": "right"}),
                html.Th("p-val",     style={**_th(), "textAlign": "right"}),
            ])]
            records = []
            for bid in BASIN_ORDER:
                b = df[df["basin"] == bid].sort_values("water_year").dropna(subset=[var])
                if len(b) < 5:
                    continue
                sl, _, _, p, _ = stats.linregress(b["water_year"], b[var])
                records.append((bid, sl, p))
            records.sort(key=lambda x: x[1])
            for bid, sl, p in records:
                sig = " " if p < 0.05 else ""
                c = "#D32F2F" if sl < 0 and p < 0.05 else "#1565C0" if sl > 0 else "#37474f"
                rows.append(html.Tr([
                    html.Td(_basin_label(bid), style=_td()),
                    html.Td(f"{sl:+.2f}{sig}",
                            style={**_td(), "textAlign": "right", "color": c, "fontWeight": "600"}),
                    html.Td(f"{p:.3f}", style={**_td(), "textAlign": "right", "color": "#1e293b"}),
                ]))

        elif mode == "compare":
            rows = [html.Tr([
                html.Th("Basin",     style=_th()),
                html.Th("% Change",  style={**_th(), "textAlign": "right"}),
            ])]
            records = []
            for bid in BASIN_ORDER:
                ma = df[(df["basin"] == bid) & (df["water_year"] >= pa[0]) &
                        (df["water_year"] <= pa[1])][var].mean()
                mb = df[(df["basin"] == bid) & (df["water_year"] >= pb[0]) &
                        (df["water_year"] <= pb[1])][var].mean()
                if pd.notna(ma) and pd.notna(mb) and abs(ma) > 0.01:
                    pct = (mb - ma) / abs(ma) * 100
                    records.append((bid, pct))
            records.sort(key=lambda x: x[1])
            for bid, pct in records:
                c = "#D32F2F" if pct < -10 else "#1565C0" if pct > 10 else "#37474f"
                rows.append(html.Tr([
                    html.Td(_basin_label(bid), style=_td()),
                    html.Td(f"{pct:+.1f}%",
                            style={**_td(), "textAlign": "right", "color": c, "fontWeight": "600"}),
                ]))
        else:
            return html.P("Select a mode above")

        return html.Table(rows, style={"width": "100%", "borderCollapse": "collapse",
                                       "fontSize": "11.5px"})

    # ── Two static map images (LEFT/RIGHT variable) — mode-aware ──
    LEAF_B = ["Green", "SanJuan", "UpperColo", "GlenCanyon",
              "Gila", "GrandCanyon", "LittleColo", "LowerColo"]

    def _basin_image(var, year, mode, pa, pb):
        import base64 as _b64
        def _svg_msg(msg):
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="820" height="360">'
                   f'<rect width="100%" height="100%" fill="#f4f4f1"/>'
                   f'<text x="50%" y="50%" font-family="Inter,sans-serif" font-size="19" '
                   f'fill="#8C1D40" text-anchor="middle" dominant-baseline="middle">{msg}</text>'
                   f'</svg>')
            return "data:image/svg+xml;base64," + _b64.b64encode(svg.encode()).decode()

        df = _safe(load_vic_annual)
        if BASINS_GJ is None or df.empty or var not in df.columns:
            return _svg_msg("Map data unavailable"), "Map — data unavailable"

        vlabel = next((o["label"].split("(")[0].strip() for o in VAR_OPTIONS
                       if o["value"] == var), var)
        full = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
        units = full.split("(")[-1].rstrip(")") if "(" in full else ""

        # values + percentile ranks for the chosen year (all basins, for context)
        yr = df[df["water_year"] == year][["basin", var]].dropna()
        yr_vals = dict(zip(yr["basin"], yr[var]))
        allv = yr[var]
        ranks = {b: (allv <= v).mean() * 100 for b, v in zip(yr["basin"], yr[var])}

        grid = None; fill_vals = None; label_map = {}
        diverging = False; cmap = "viridis"; cbar = None; mode_label = ""

        if mode == "grid":
            try:
                g = load_spatial(var)
                grid = g[g["water_year"] == year][["lat", "lon", "value"]]
            except Exception:
                grid = None
            for b in LEAF_B:
                v = yr_vals.get(b)
                if v is not None:
                    label_map[b] = f"{v:.1f}" + (f" · {ranks.get(b,0):.0f}th" if b in ranks else "")
            mode_label = "Grid"
        elif mode == "basin":
            fill_vals = {b: yr_vals.get(b) for b in LEAF_B}
            for b in LEAF_B:
                v = yr_vals.get(b)
                if v is not None:
                    label_map[b] = f"{v:.1f}" + (f" · {ranks.get(b,0):.0f}th" if b in ranks else "")
            mode_label = "Basin average"
        elif mode == "trend":
            from scipy import stats
            fill_vals = {}
            for b in LEAF_B:
                s = df[df["basin"] == b].dropna(subset=[var]).sort_values("water_year")
                if len(s) >= 5:
                    sl, _, _, p, _ = stats.linregress(s["water_year"], s[var])
                    fill_vals[b] = sl
                    label_map[b] = f"{sl:+.2f}/yr"
            diverging = True; mode_label = "Trend"
            cbar = f"{vlabel} trend ({units}/yr)" if units else f"{vlabel} trend /yr"
        elif mode == "compare":
            fill_vals = {}
            for b in LEAF_B:
                ma = df[(df["basin"] == b) & (df["water_year"] >= pa[0]) &
                        (df["water_year"] <= pa[1])][var].mean()
                mb = df[(df["basin"] == b) & (df["water_year"] >= pb[0]) &
                        (df["water_year"] <= pb[1])][var].mean()
                if pd.notna(ma) and pd.notna(mb) and abs(ma) > 0.01:
                    pct = (mb - ma) / abs(ma) * 100
                    fill_vals[b] = pct
                    label_map[b] = f"{pct:+.0f}%"
            diverging = True; cbar = "% change"
            mode_label = f"Period Δ  {pa[0]}–{pa[1]} → {pb[0]}–{pb[1]}"
        else:
            mode_label = ""

        src = render_basin_map(grid, yr_vals, ranks, vlabel, units, year,
                               mode_label=mode_label, fill_vals=fill_vals,
                               label_map=label_map, diverging=diverging,
                               cmap=cmap, cbar_label=cbar)
        if not src:
            return (_svg_msg("Install matplotlib to view this map  —  pip install matplotlib"),
                    "Map — matplotlib required")
        title = f"{vlabel}, WY{year}  ·  {mode_label}"
        return src, title

    @app.callback(
        Output("sp-basin-choro-img", "src"),
        Output("sp-basin-choro-title", "children"),
        Input("sp-var", "value"),
        Input("sp-year", "value"),
        Input("sp-map-mode", "value"),
        Input("sp-period-a", "value"),
        Input("sp-period-b", "value"),
    )
    def basin_choro_left(var, year, mode, pa, pb):
        # Default single-year view → show the animated GIF (spatial map across all
        # water years) so the comparison animates like the basin-wide tab.
        if var in ANIM_VARS and (mode in (None, "basin", "grid")):
            name = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
            return f"/assets/animations/spatial_{var}.gif", f"{name} · animated WY1984–2024"
        return _basin_image(var, year, mode, pa, pb)

    @app.callback(
        Output("sp-basin-choro-img-right", "src"),
        Output("sp-basin-choro-title-right", "children"),
        Input("sp-var-right", "value"),
        Input("sp-year", "value"),
        Input("sp-map-mode", "value"),
        Input("sp-period-a", "value"),
        Input("sp-period-b", "value"),
    )
    def basin_choro_right(var, year, mode, pa, pb):
        if var in ANIM_VARS and (mode in (None, "basin", "grid")):
            name = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
            return f"/assets/animations/spatial_{var}.gif", f"{name} · animated WY1984–2024"
        return _basin_image(var, year, mode, pa, pb)

    # ── Basin-average trend GIFs (separate containers below the maps) ──
    @app.callback(
        Output("sp-choro-graph-img", "src"),
        Output("sp-choro-graph-title", "children"),
        Input("sp-var", "value"),
        Input("sp-map-mode", "value"),
    )
    def basin_choro_graph_left(var, mode):
        if var in ANIM_VARS and (mode in (None, "basin", "grid")):
            name = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
            return f"/assets/animations/graph_spatial_{var}.gif", f"{name} · basin-average trend"
        return "", ""

    @app.callback(
        Output("sp-choro-graph-img-right", "src"),
        Output("sp-choro-graph-title-right", "children"),
        Input("sp-var-right", "value"),
        Input("sp-map-mode", "value"),
    )
    def basin_choro_graph_right(var, mode):
        if var in ANIM_VARS and (mode in (None, "basin", "grid")):
            name = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
            return f"/assets/animations/graph_spatial_{var}.gif", f"{name} · basin-average trend"
        return "", ""

    # ── Findings bar ──────────────────────────────────────────
    @app.callback(
        Output("sp-findings", "children"),
        Input("sp-var", "value"),
        Input("sp-map-mode", "value"),
        Input("sp-year", "value"),
    )
    def update_findings(var, mode, year):
        df = _safe(load_vic_annual)
        if df.empty or var not in df.columns:
            return " Run preprocessing to see spatial analysis."
        from scipy import stats
        crb = df[df["basin"] == "CRB"].sort_values("water_year").dropna(subset=[var])
        if len(crb) < 5:
            return "Insufficient data."
        sl, _, _, p, _ = stats.linregress(crb["water_year"], crb[var])
        vname = next((o["label"].split("(")[0] for o in VAR_OPTIONS if o["value"] == var), var)
        sig = " significant (p<0.05)" if p < 0.05 else f"not significant (p={p:.2f})"
        yr_val = df[(df["basin"] == "CRB") & (df["water_year"] == year)][var]
        yr_str = f" · WY{year}: {yr_val.iloc[0]:.1f}" if not yr_val.empty else ""
        return [
            html.Strong(f" {vname} — "),
            f"CRB mean: {crb[var].mean():.1f} (range {crb[var].min():.1f}–{crb[var].max():.1f}). ",
            f"Trend: {sl:+.2f}/yr — {sig}.{yr_str}",
        ]

    # ── Synchronized zoom: cycle-free via Store intermediary ─────────────
    # Step 1: either map's relayoutData write zoom/center to Store
    app.clientside_callback(
        """function(left_rl, right_rl) {
            var ctx = dash_clientside.callback_context;
            if (!ctx.triggered || !ctx.triggered.length)
                return dash_clientside.no_update;
            var src = ctx.triggered[0].prop_id;
            var data = src.indexOf('left') !== -1 ? left_rl : right_rl;
            if (!data) return dash_clientside.no_update;
            var zoom   = data['mapbox.zoom'];
            var center = data['mapbox.center'];
            if (zoom === undefined && !center) return dash_clientside.no_update;
            return {zoom: zoom, center: center, src: src};
        }
        """,
        Output("sp-zoom-store", "data"),
        Input("sp-left-map",  "relayoutData"),
        Input("sp-right-map", "relayoutData"),
        prevent_initial_call=True,
    )

    # Step 2: Store-patch the OTHER map's figure (no relayoutData involved, no cycle)
    @app.callback(
        Output("sp-left-map",  "figure", allow_duplicate=True),
        Output("sp-right-map", "figure", allow_duplicate=True),
        Input("sp-zoom-store", "data"),
        prevent_initial_call=True,
    )
    def _sync_zoom(store_data):
        if not store_data:
            raise PreventUpdate
        src    = store_data.get("src", "")
        zoom   = store_data.get("zoom")
        center = store_data.get("center")
        if zoom is None and not center:
            raise PreventUpdate
        p = Patch()
        if zoom is not None:
            p["layout"]["mapbox"]["zoom"] = zoom
        if center:
            p["layout"]["mapbox"]["center"] = center
        if "left" in src:
            return no_update, p   # left triggered sync right
        else:
            return p, no_update   # right triggered sync left


# ─────────────────────────────────────────────────────────────
# Style helpers
# ─────────────────────────────────────────────────────────────
def _th():
    return {"background": NAVY, "color": "white", "fontSize": "11px",
            "padding": "6px 10px", "fontWeight": "600"}

def _td():
    return {"fontSize": "11.5px", "padding": "5px 10px",
            "borderBottom": "1px solid #f0f0f0"}


# ─────────────────────────────────────────────────────────────
# Overlay builder — SNOTEL, HUC-10, Basins, Rivers
# ─────────────────────────────────────────────────────────────
def _add_overlays(fig, layers):
    """Add SNOTEL / HUC-10 / Basin outlines / River traces to an existing figure."""# ── Basin outlines (bright distinct colors) ───────────────
    if "basins" in layers and BASINS_GJ is not None:
        for feat in BASINS_GJ["features"]:
            bid = feat["properties"].get("basin_id", "CRB")
            info = BASIN_OUTLINE.get(bid, {"color": "#37474f", "width": 2.0, "label": bid})
            lats, lons = [], []
            geom = feat["geometry"]
            polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
            for poly in polys:
                for ring in poly:
                    for lon, lat in ring:
                        lats.append(lat); lons.append(lon)
                    lats.append(None); lons.append(None)
            fig.add_trace(go.Scattermapbox(
                lat=lats, lon=lons, mode="lines",
                line=dict(color=info["color"], width=info["width"]),
                hoverinfo="none",
                name=info["label"],
            ))

    # ── All SNOTEL stations ────────────────────────────────────
    if "snotel" in layers:
        # Use pre-built station parquet (has lat/lon, elev, mk_slope, etc.)
        sta_all = _safe(load_snotel_stations)
        if not sta_all.empty:
            sta_all = sta_all.drop_duplicates("site_id").copy()
            # Rename to match downstream code
            if "station_name" in sta_all.columns and "name" not in sta_all.columns:
                sta_all = sta_all.rename(columns={"station_name": "name"})
            # Compute median peak SWE per station from annual parquet
            df_ann_sta = _safe(load_snotel_annual_station)
            if not df_ann_sta.empty:
                med = df_ann_sta.groupby("site_id")["peak_swe_mm"].median().reset_index()
                med.columns = ["site_id", "med_swe"]
                sta_all = sta_all.merge(med, on="site_id", how="left")
            else:
                sta_all["med_swe"] = np.nan
            # has_swe: True for stations with valid mk_slope (i.e. enough SWE data)
            sta_all["has_swe"] = sta_all["mk_slope"].notna()

            # Elevation-based colors
            sta_all["color"] = sta_all["elev"].apply(_snotel_elev_color)

            # Size: larger for stations with SWE trend data
            sta_all["dot_size"] = sta_all["has_swe"].apply(lambda x: 10 if x else 6)

            # Trend-based border coloring for SWE stations
            def trend_border(row):
                if pd.isna(row.get("mk_slope")):
                    return row["color"]
                if row["mk_pvalue"] < 0.05 and row["mk_slope"] < -2:
                    return "#D32F2F"# significant decline
                if row["mk_slope"] < 0:
                    return "#FF8A65"# moderate decline
                return "#1565C0"# stable/increasing

            sta_all["border_color"] = sta_all.apply(
                lambda r: trend_border(r) if pd.notna(r.get("mk_slope")) else r["color"],
                axis=1
            )

            # Hover text
            def make_hover(row):
                name = str(row.get("site_name", "")).title().strip()
                state = row.get("state", "")
                elev = row.get("elev", 0)
                text = f"<b>{name}</b> ({state})<br>Elevation: {elev:,} m"
                if pd.notna(row.get("med_swe")) and row.get("has_swe"):
                    sl = row.get("mk_slope", np.nan)
                    pv = row.get("mk_pvalue", np.nan)
                    text += f"<br>Median peak SWE: {row['med_swe']:.0f} mm"
                    if pd.notna(sl):
                        sig = " sig." if pv < 0.05 else ""
                        text += f"<br>SWE trend: {sl:+.1f} mm/yr{sig}"
                    ny = row.get("n_years", 0)
                    if ny:
                        text += f"<br>Record: {int(ny)} years"
                else:
                    text += "<br><i>No SWE record</i>"
                return text

            sta_all["hover"] = sta_all.apply(make_hover, axis=1)

            # Single trace with all 103 stations
            fig.add_trace(go.Scattermapbox(
                lat=sta_all["latitude"],
                lon=sta_all["longitude"],
                mode="markers",
                marker=dict(
                    size=sta_all["dot_size"].tolist(),
                    color=sta_all["color"].tolist(),
                    opacity=0.88,
                ),
                text=sta_all["hover"],
                hoverinfo="text",
                name=f"SNOTEL ({len(sta_all)})",
            ))

    # ── Colorado River + tributaries (handles LineString & MultiLineString) ──
    if "rivers" in layers and RIVERS_GJ is not None:
        for feat in RIVERS_GJ["features"]:
            name = feat["properties"].get("name", "River")
            color = feat["properties"].get("color", RIVER_COLORS.get(name, "#1565C0"))
            width = feat["properties"].get("width", 1.5)
            geom = feat["geometry"]
            lats, lons = [], []
            if geom["type"] == "LineString":
                for lon, lat in geom["coordinates"]:
                    lats.append(lat); lons.append(lon)
            elif geom["type"] == "MultiLineString":
                for segment in geom["coordinates"]:
                    for lon, lat in segment:
                        lats.append(lat); lons.append(lon)
                    lats.append(None); lons.append(None)  # gap between segments
            fig.add_trace(go.Scattermapbox(
                lat=lats, lon=lons, mode="lines",
                line=dict(color=color, width=width),
                hovertemplate=f"<b>{name}</b><extra></extra>",
                name=name,
            ))

    # ── CRB / Upper Basin / Lower Basin outlines (from official shapefiles) ──
    if BOUNDARIES_GJ is not None:
        for feat in BOUNDARIES_GJ["features"]:
            bname  = feat["properties"].get("name", "Boundary")
            bcolor = feat["properties"].get("color", "#FFFFFF")
            bwidth = feat["properties"].get("width", 2.0)
            geom   = feat["geometry"]
            lats, lons = [], []
            polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
            for poly in polys:
                for ring in poly:
                    for lon, lat in ring:
                        lats.append(lat); lons.append(lon)
                    lats.append(None); lons.append(None)
            fig.add_trace(go.Scattermapbox(
                lat=lats, lon=lons, mode="lines",
                line=dict(color=bcolor, width=bwidth),
                hovertemplate=f"<b>{bname}</b><extra></extra>",
                name=bname,
            ))

    # ── HUC-10 watershed boundaries ───────────────────────────
    if "huc10" in layers and HUC10_GJ is not None:
        lats, lons = [], []
        for feat in HUC10_GJ["features"]:
            geom = feat["geometry"]
            if geom["type"] == "Polygon":
                for ring in geom["coordinates"]:
                    for lon, lat in ring:
                        lats.append(lat); lons.append(lon)
                    lats.append(None); lons.append(None)
            elif geom["type"] == "MultiPolygon":
                for poly in geom["coordinates"]:
                    for ring in poly:
                        for lon, lat in ring:
                            lats.append(lat); lons.append(lon)
                        lats.append(None); lons.append(None)
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode="lines",
            line=dict(color="rgba(78,52,46,0.35)", width=0.7),
            hoverinfo="none",
            name="HUC-10 Watersheds",
        ))


# ─────────────────────────────────────────────────────────────
# Map builder helpers
# ─────────────────────────────────────────────────────────────
def _build_basin_choropleth(var, year, layers):
    """Data choropleth — each sub-basin shaded by its VIC value of the selected
    variable for the chosen water year (colour encodes the data, not basin identity),
    with a colour bar. Changing the variable or year re-colours the map.
    """
    df = _safe(load_vic_annual)
    fig = go.Figure()

    if BASINS_GJ is None or df.empty or var not in df.columns:
        return _empty("Basin GeoJSON or VIC data not available")

    sub = df[df["water_year"] == year][["basin", var]].set_index("basin")[var]
    z_vals = [float(sub.get(b, float("nan"))) for b in BASIN_FILL_ORDER]
    valid = [v for v in z_vals if v == v]

    vname = var.replace("OUT_", "").replace("_", " ")
    var_unit = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), vname)
    # temperature variables -> diverging warm scale; everything else -> sequential
    is_temp = "TEMP" in var
    cscale = "RdYlBu_r" if is_temp else "YlGnBu"
    zmin = min(valid) if valid else 0
    zmax = max(valid) if valid else 1

    fig.add_trace(go.Choroplethmapbox(
        geojson=BASINS_GJ,
        locations=BASIN_FILL_ORDER,
        z=z_vals,
        featureidkey="properties.basin_id",
        colorscale=cscale,
        zmin=zmin, zmax=zmax,
        marker_opacity=0.72,
        marker_line_width=2.0,
        marker_line_color="white",
        showscale=True,
        colorbar=dict(title=dict(text=var_unit.split("(")[-1].rstrip(")") or vname,
                                 side="right"), thickness=14, len=0.7, x=0.99),
        text=[
            f"<b>{_basin_label(b)}</b>"
            f"<br>{vname}: <b>{(sub.get(b) if sub.get(b)==sub.get(b) else float('nan')):.1f}</b>"
            f"<br>WY{year}"
            for b in BASIN_FILL_ORDER
        ],
        hoverinfo="text",
        name="Sub-Basins",
    ))

    _add_overlays(fig, layers)
    return fig


def _build_trend_map(var, layers):
    df = _safe(load_vic_annual)
    df_sp = _safe(load_spatial, var)
    fig = go.Figure()

    if BASINS_GJ is None or df.empty:
        return _empty("Data not available")

    from scipy import stats
    basin_slopes = {}
    for bid in BASIN_ORDER:
        b = df[df["basin"] == bid].sort_values("water_year").dropna(subset=[var])
        if len(b) < 5:
            basin_slopes[bid] = 0.0
            continue
        sl, _, _, p, _ = stats.linregress(b["water_year"], b[var])
        basin_slopes[bid] = float(sl)

    slopes = list(basin_slopes.values())
    abs_max = max(abs(s) for s in slopes) or 1

    fig.add_trace(go.Choroplethmapbox(
        geojson=BASINS_GJ,
        locations=list(basin_slopes.keys()),
        z=slopes,
        featureidkey="properties.basin_id",
        colorscale="RdBu",
        zmid=0, zmin=-abs_max, zmax=abs_max,
        marker_opacity=0.60,
        marker_line_width=0,
        colorbar=dict(
            thickness=14, len=0.65, x=0.01, xanchor="left",
            title=dict(text="Slope /yr", font=dict(size=10)),
            tickfont=dict(size=10),
        ),
        text=[f"<b>{_basin_label(b)}</b><br>Slope: {s:+.3f}/yr"
        for b, s in basin_slopes.items()],
        hoverinfo="text",
        name="MK Trend",
    ))

    if not df_sp.empty:
        from scipy import stats as scipy_stats
        records = []
        for (lat, lon), grp in df_sp.groupby(["lat", "lon"]):
            grp = grp.sort_values("water_year").dropna(subset=["value"])
            if len(grp) < 8:
                continue
            sl, _, _, p, _ = scipy_stats.linregress(grp["water_year"], grp["value"])
            records.append({"lat": lat, "lon": lon, "slope": sl, "sig": p < 0.05})
        if records:
            df_t = pd.DataFrame(records)
            sig = df_t[df_t["sig"]]
            if not sig.empty:
                colors = ["#D32F2F" if s < 0 else "#1565C0" for s in sig["slope"]]
                fig.add_trace(go.Scattermapbox(
                    lat=sig["lat"], lon=sig["lon"], mode="markers",
                    marker=dict(size=4, color=colors, opacity=0.5),
                    text=[f"{s:+.3f}" for s in sig["slope"]],
                    hovertemplate="Lat:%{lat:.2f} Lon:%{lon:.2f}<br>Slope:%{text}/yr<extra></extra>",
                    name="Grid trend (p<0.05)",
                ))

    _add_overlays(fig, layers)
    return fig


def _build_compare_map(var, pa, pb, show, layers):
    df = _safe(load_vic_annual)
    fig = go.Figure()

    if BASINS_GJ is None or df.empty or var not in df.columns:
        return _empty("Data not available")

    basin_deltas = {}
    for bid in BASIN_ORDER:
        ma = df[(df["basin"] == bid) & (df["water_year"] >= pa[0]) &
                (df["water_year"] <= pa[1])][var].mean()
        mb = df[(df["basin"] == bid) & (df["water_year"] >= pb[0]) &
                (df["water_year"] <= pb[1])][var].mean()
        if pd.notna(ma) and pd.notna(mb) and abs(ma) > 0.01:
            delta = (mb - ma) / abs(ma) * 100 if show == "pct" else mb - ma
        else:
            delta = 0.0
        basin_deltas[bid] = float(delta)

    deltas = list(basin_deltas.values())
    abs_max = max(abs(d) for d in deltas) or 1
    label = "% Change" if show == "pct" else "Absolute Δ"
    fig.add_trace(go.Choroplethmapbox(
        geojson=BASINS_GJ,
        locations=list(basin_deltas.keys()),
        z=deltas,
        featureidkey="properties.basin_id",
        colorscale="RdBu",
        zmid=0, zmin=-abs_max, zmax=abs_max,
        marker_opacity=0.60,
        marker_line_width=0,
        colorbar=dict(
            thickness=14, len=0.65, x=0.01, xanchor="left",
            title=dict(text=label, font=dict(size=10)),
            tickfont=dict(size=10),
        ),
        text=[f"<b>{_basin_label(b)}</b><br>{label}: {d:+.1f}"
        for b, d in basin_deltas.items()],
        hoverinfo="text",
        name="Period Δ",
    ))

    _add_overlays(fig, layers)
    return fig
