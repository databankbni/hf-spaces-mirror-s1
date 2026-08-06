"""
modules/basinwide.py — Basin-Wide Overview (all sub-basins together)

Two views of the whole basin at once:
  1. An interactive spatial anomaly grid (soil moisture, SWE, precipitation, runoff) for a
     water year chosen with a slider (any year 1984–2024), coloured red (below mean) to blue
     (above), % of the 1984–2024 mean, with sub-basin boundaries. From the VIC reanalysis.
  2. An interactive multi-basin time series where every sub-basin is a coloured line,
     indexed to 100 = its own 1984–2024 average, so basins of different size are directly
     comparable on one chart.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, State
from utils.data_loader import load_vic_annual
from utils.multibasin import multi_basin_fig, BASIN_LABEL, DRAW_ORDER

# sub-basin picker: whole basin first, then upper, then lower
BASIN_LIST = [(b, BASIN_LABEL[b]) for b in
              ["CRB", "UpperBasin", "Green", "UpperColo", "SanJuan", "GlenCanyon",
               "LowerBasin", "GrandCanyon", "LittleColo", "Gila", "LowerColo"]
              if b in BASIN_LABEL]
BASIN_OPTIONS = [{"label": lab, "value": b} for b, lab in BASIN_LIST]
UPPER_SET = ["CRB", "UpperBasin", "Green", "UpperColo", "SanJuan", "GlenCanyon"]
LOWER_SET = ["CRB", "LowerBasin", "GrandCanyon", "LittleColo", "Gila", "LowerColo"]
from utils.anomaly_grid import render_anomaly_grid, render_mapchart_grid, available_years

MAROON = "#8C1D40"; NAVY = "#0D2137"

try:
    _YRS = available_years()
    _YMIN, _YMAX = (min(_YRS), max(_YRS)) if _YRS else (1984, 2024)
except Exception:
    _YMIN, _YMAX = 1984, 2024

BASIN_COLORS = {
    "CRB": "#0D2137", "UpperBasin": "#01579B", "LowerBasin": "#C62828", "Green": "#2E7D32",
    "SanJuan": "#E65100", "UpperColo": "#6A1B9A", "GlenCanyon": "#00838F", "Gila": "#00695C",
    "GrandCanyon": "#AD1457", "LittleColo": "#F9A825", "LowerColo": "#5D4037",
}
BASIN_LABEL = {
    "CRB": "Colorado R. Basin", "UpperBasin": "Upper Basin", "LowerBasin": "Lower Basin",
    "Green": "Green River", "SanJuan": "San Juan", "UpperColo": "Upper Colorado",
    "GlenCanyon": "Glen Canyon", "Gila": "Gila River", "GrandCanyon": "Grand Canyon",
    "LittleColo": "Little Colorado", "LowerColo": "Lower Colorado",
}
# drawn in this order so the whole-basin (CRB) line ends up on top
DRAW_ORDER = ["Green", "UpperColo", "SanJuan", "GlenCanyon", "UpperBasin", "LowerColo",
              "GrandCanyon", "LittleColo", "Gila", "LowerBasin", "CRB"]
VAR_OPTIONS = [
    {"label": "Runoff efficiency, Q/P (dimensionless)", "value": "RE"},
    {"label": "Runoff (mm/yr)", "value": "OUT_RUNOFF"},
    {"label": "Snow water equivalent, SWE (mm)", "value": "OUT_SWE"},
    {"label": "Soil moisture (mm)", "value": "OUT_SOIL_MOIST"},
    {"label": "Precipitation (mm/yr)", "value": "OUT_PREC"},
    {"label": "Air temperature (°C)", "value": "OUT_AIR_TEMP"},
]


def _safe():
    try:
        return load_vic_annual()
    except Exception:
        return pd.DataFrame()


def layout():
    return html.Div([
        html.Div([
            html.H2("Basin-Wide Overview — all sub-basins together"),
            html.P("See the whole Colorado River Basin and every sub-basin at once — spatial "
                   "anomalies year by year, and every sub-basin's trajectory on a single chart."),
        ], className="tab-header"),
        html.Div([
            # 1 · spatial anomaly + basin trend — interactive (play OR pick any year)
            html.Div([
                html.Div([
                    html.Span("Spatial anomalies + basin trends — by water year",
                              style={"fontWeight": "700", "fontSize": "13px"}),
                    html.A([html.I(className="bi bi-download", style={"marginRight": "6px"}), "Download maps (PDF)"], href="/assets/reports/basin_anomaly_maps.pdf",
                           download="CRB_basin_anomaly_maps.pdf", target="_blank",
                           style={"background": MAROON, "color": "white", "textDecoration": "none",
                                  "borderRadius": "6px", "padding": "5px 12px", "fontSize": "11.5px",
                                  "fontWeight": "700", "whiteSpace": "nowrap"}),
                ], className="crb-card-header",
                   style={"display": "flex", "justifyContent": "space-between", "alignItems": "center",
                          "gap": "12px", "flexWrap": "wrap"}),
                html.Div([
                    html.P("Top row: the four spatial anomaly maps (soil moisture, snow water equivalent, "
                           "precipitation, runoff) — red = below the 1984–2024 mean / dry, blue = above / "
                           "wet, with sub-basin boundaries. Bottom row: the matching basin-average trends, "
                           "with a dot on the current year. The animation plays smoothly on its own; drag "
                           "the slider to freeze on any water year and examine it, then press Resume. From "
                           "the VIC reanalysis — a spatial companion to Ghimire, Vivoni & Wang (2026, Water "
                           "Resources Research).",
                           style={"fontSize": "11.5px", "color": "#37474f", "marginBottom": "10px"}),
                    html.Div([
                        html.Button("▶ Resume animation", id="bw-mc-resume", n_clicks=0,
                                    style={"background": MAROON, "color": "white", "border": "none",
                                           "borderRadius": "6px", "padding": "6px 14px", "fontWeight": "700",
                                           "fontSize": "12px", "cursor": "pointer", "whiteSpace": "nowrap",
                                           "marginTop": "14px"}),
                        html.Div([
                            html.Div("WATER YEAR  ·  plays smoothly on its own — drag to freeze on a year, "
                                     "then Resume", className="control-label"),
                            dcc.Slider(id="bw-mc-year", min=_YMIN, max=_YMAX, step=1, value=_YMAX,
                                       marks={y: str(y) for y in range(1985, _YMAX + 1, 5)},
                                       tooltip={"placement": "bottom", "always_visible": False}),
                        ], style={"flex": "1 1 auto"}),
                    ], style={"display": "flex", "gap": "14px", "alignItems": "flex-start",
                              "maxWidth": "1000px", "margin": "0 auto 8px"}),
                    dcc.Loading(
                        html.Img(id="bw-mc-img", src="/assets/animations/anomaly_mapchart.gif",
                                 style={"width": "100%", "maxWidth": "1180px", "display": "block",
                                        "margin": "0 auto", "border": "1px solid #e2e8f0",
                                        "borderRadius": "6px"}),
                        type="circle", color=MAROON),
                ], style={"padding": "10px 16px 12px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # 2 · every sub-basin on one chart
            html.Div([
                html.Div("Every sub-basin on one chart (indexed to each basin's 1984–2024 mean)",
                         className="crb-card-header", style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([
                    html.Div([
                        html.Div([
                            html.Div("VARIABLE", className="control-label"),
                            dcc.Dropdown(id="bw-var", options=VAR_OPTIONS, value="RE",
                                         clearable=False,
                                         style={"fontSize": "12.5px"}),
                        ], style={"flex": "1 1 240px", "minWidth": "0"}),
                        html.Div([
                            html.Div("SUB-BASINS", className="control-label"),
                            dcc.Dropdown(id="bw-basins", options=BASIN_OPTIONS,
                                         value=[b for b, _ in BASIN_LIST], multi=True,
                                         placeholder="Choose sub-basins…",
                                         style={"fontSize": "12.5px"}),
                        ], style={"flex": "2 1 340px", "minWidth": "0"}),
                    ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap",
                              "marginBottom": "8px"}),
                    html.Div([
                        html.Button("All basins", id="bw-all", n_clicks=0, className="bw-preset"),
                        html.Button("Upper only", id="bw-upper", n_clicks=0, className="bw-preset"),
                        html.Button("Lower only", id="bw-lower", n_clicks=0, className="bw-preset"),
                    ], style={"display": "flex", "gap": "7px", "marginBottom": "10px",
                              "flexWrap": "wrap"}),
                    dcc.Graph(id="bw-graph", config={"displayModeBar": False}, style={"height": "440px"}),
                    html.Div("Each coloured line is a sub-basin, indexed to 100 = its own 1984–2024 "
                             "average, so basins of very different size are directly comparable. The dark "
                             "line is the whole Colorado River Basin. All values from the VIC reanalysis.",
                             style={"fontSize": "10.5px", "color": "#546e7a", "marginTop": "4px"}),
                ], style={"padding": "12px 16px"}),
            ], className="crb-card"),
        ], className="tab-body"),
    ])


def register_callbacks(app):
    # Smooth pre-rendered GIF plays on its own; dragging the slider freezes on a specific
    # year (a static server-rendered frame), and Resume returns to the animated GIF.
    _MC_GIF = "/assets/animations/anomaly_mapchart.gif"

    @app.callback(Output("bw-mc-img", "src"),
                  Input("bw-mc-year", "value"), Input("bw-mc-resume", "n_clicks"),
                  prevent_initial_call=True)
    def _mapchart(year, _resume):
        from dash import ctx
        if ctx.triggered_id == "bw-mc-resume":
            return _MC_GIF
        return render_mapchart_grid(int(year) if year else _YMAX) or _MC_GIF

    # preset buttons set the sub-basin selection
    @app.callback(Output("bw-basins", "value"),
                  Input("bw-all", "n_clicks"), Input("bw-upper", "n_clicks"),
                  Input("bw-lower", "n_clicks"), prevent_initial_call=True)
    def _preset(_a, _u, _l):
        from dash import ctx
        if ctx.triggered_id == "bw-upper":
            return UPPER_SET
        if ctx.triggered_id == "bw-lower":
            return LOWER_SET
        return [b for b, _ in BASIN_LIST]

    @app.callback(Output("bw-graph", "figure"),
                  Input("bw-var", "value"), Input("bw-basins", "value"))
    def _chart(var, basins):
        # Static interactive overlay (smooth lines + knots), shared with the per-basin views.
        df = _safe()
        if basins:
            keep = [b for b in DRAW_ORDER if b in set(basins)]
            if keep and not df.empty:
                df = df[df["basin"].isin(keep)]
        return multi_basin_fig(var, df=df, height=440)
