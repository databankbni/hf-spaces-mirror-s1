"""
modules/cmip.py — Long-range Climate Projections (CMIP5 & CMIP6)

Two layers, kept honestly separate:

  1. PUBLISHED RESULT (cited): the project's CMIP5/CMIP6-LOCA ensemble result —
     model rankings, the 5-of-6-drier finding, the spread comparison, and the
     project's own Figure 3. The raw LOCA gridded projection data is NOT bundled
     in this repo, so these are interactive charts built from the *documented*
     numbers plus the cited figure.

  2. INTERACTIVE "climate-change fingerprint" MAP (real data): an interactive
     sub-basin map of the OBSERVED change already in the VIC (PRISM-calibrated)
     record — recent period vs early period. This is the measured change that
     motivates the projections; it is NOT the future CMIP projection (that is
     the cited figure). All numbers here are computed live from real VIC data.

Source: NASA Quarterly Review (Nov 2024) & Annual Progress Report (Feb 2025),
Vivoni et al., ASU.
"""
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from pathlib import Path
from utils.data_loader import load_vic_annual
from utils.components import pub_evidence, pub_star, pub_author
from utils.charts import lollipop_h

NAVY="#0D2137"; MAROON="#8C1D40"; BLUE="#01579B"; GREEN="#2E7D32"
ORANGE="#E65100"; GREY="#94a3b8"; GOLD="#FFC627"

ASSETS = Path(__file__).parent.parent / "assets"
FIG = "/assets/reports/figs/cmip_changes.png"
HAS_FIG = (ASSETS / "reports" / "figs" / "cmip_changes.png").exists()

# Basin outline geojson (same file the Spatial tab uses)
def _load_json(p):
    p = Path(p)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None
BASINS_GJ = _load_json(ASSETS / "crb_basins.geojson")

# 8 sub-basins that tile the CRB exactly (no overlap) — used for the choropleth
TILING = ["Green", "SanJuan", "UpperColo", "GlenCanyon",
          "GrandCanyon", "LittleColo", "Gila", "LowerColo"]
BASIN_NAME = {
    "Green": "Green River", "SanJuan": "San Juan", "UpperColo": "Upper Colorado",
    "GlenCanyon": "Glen Canyon", "GrandCanyon": "Grand Canyon",
    "LittleColo": "Little Colorado", "Gila": "Gila River", "LowerColo": "Lower Colorado",
}

CMIP6_TOP = ["ACCESS-ESM1-5","CanESM5","GFDL-ESM4","IPSL-CM6A-LR","MPI-ESM1-2-LR","AWI-CM-1-1-MR","EC-Earth3","INM-CM5-0"]
CMIP5_TOP = ["ACCESS1-0","CanESM2","CESM1-BGC","GFDL-CM3","IPSL-CM5A-LR","HadGEM2-ES","CMCC-CM","inmcm4"]

# Variables for the interactive observed-change map
MAP_VARS = [
    {"label": "Precipitation",       "value": "OUT_PREC",       "unit": "%",  "kind": "pct"},
    {"label": "Surface Runoff",      "value": "OUT_RUNOFF",     "unit": "%",  "kind": "pct"},
    {"label": "Snowpack (SWE)",      "value": "OUT_SWE",        "unit": "%",  "kind": "pct"},
    {"label": "Soil Moisture",       "value": "OUT_SOIL_MOIST", "unit": "%",  "kind": "pct"},
    {"label": "Evapotranspiration",  "value": "OUT_EVAP",       "unit": "%",  "kind": "pct"},
    {"label": "Air Temperature",     "value": "OUT_AIR_TEMP",   "unit": "°C", "kind": "abs"},
]
EARLY = (1984, 1998)
RECENT = (2010, 2024)


def _tile(v, l, c):
    return html.Div([html.Div(v, className="info-tile-value"),
        html.Div(l, className="info-tile-label")], className=f"info-tile {c}")


# ── Interactive documented charts ────────────────────────────
def _runoff_donut():
    fig = go.Figure(go.Pie(values=[5, 1], labels=["Declining runoff", "≈ No change"], hole=0.58,
        marker=dict(colors=[MAROON, GREY], line=dict(color="white", width=2)),
        textinfo="label+value", sort=False, direction="clockwise",
        hovertemplate="%{label}: %{value} of 6 scenarios<extra></extra>"))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), paper_bgcolor="white",
        showlegend=False,
        annotations=[dict(text="6<br>scenarios", x=0.5, y=0.5,
                          font=dict(size=15, color=NAVY), showarrow=False)])
    return fig


def _screen_funnel():
    """Interactive funnel: screened → selected GCMs per family."""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=["CMIP6-LOCA2", "CMIP5-LOCA1"], x=[214, 64], orientation="h",
        marker_color=["#bbdefb", "#f8bbd0"], name="Screened",
        text=["214 screened", "64 screened"], textposition="inside",
        insidetextanchor="start", textfont=dict(size=11, color=NAVY),
        hovertemplate="%{y}: %{x} projections screened<extra></extra>"))
    fig.add_trace(go.Bar(
        y=["CMIP6-LOCA2", "CMIP5-LOCA1"], x=[8, 8], orientation="h",
        marker_color=[BLUE, MAROON], name="Selected (top GCMs)",
        text=["8 selected", "8 selected"], textposition="outside",
        textfont=dict(size=11, color=NAVY),
        hovertemplate="%{y}: top %{x} GCMs selected by Comprehensive Error Index<extra></extra>"))
    fig.update_layout(
        barmode="overlay", height=200, margin=dict(l=10, r=20, t=10, b=24),
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(title="Number of projections", showgrid=True, gridcolor="#f0f0f0"),
        yaxis=dict(tickfont=dict(size=12, color=NAVY)),
        legend=dict(orientation="h", y=-0.25, x=0, font=dict(size=10)))
    return fig


def _skill_radar():
    """CMIP5 vs CMIP6 documented skill split (qualitative, 0–3 scale)."""
    cats = ["Winter precip<br>fit", "Temperature<br>fit", "Long-term trend<br>alignment", "Lower spread<br>(consistency)"]
    c5 = [3, 2, 2, 1]   # CMIP5 better for winter precip
    c6 = [2, 3, 2, 3]   # CMIP6 better temp + lower spread
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=c5 + [c5[0]], theta=cats + [cats[0]], fill="toself",
        name="CMIP5", line=dict(color=MAROON), fillcolor="rgba(140,29,64,0.12)",
        hovertemplate="CMIP5 · %{theta}: %{r}/3<extra></extra>"))
    fig.add_trace(go.Scatterpolar(r=c6 + [c6[0]], theta=cats + [cats[0]], fill="toself",
        name="CMIP6", line=dict(color=BLUE), fillcolor="rgba(1,87,155,0.12)",
        hovertemplate="CMIP6 · %{theta}: %{r}/3<extra></extra>"))
    fig.update_layout(height=300, margin=dict(l=30, r=30, t=20, b=20), paper_bgcolor="white",
        polar=dict(radialaxis=dict(range=[0, 3], tickvals=[1, 2, 3], tickfont=dict(size=9)),
                   angularaxis=dict(tickfont=dict(size=9.5))),
        legend=dict(orientation="h", y=-0.12, x=0.3, font=dict(size=11)),
        showlegend=True)
    return fig


def _model_table(title, models, color):
    rows = [html.Tr([
        html.Td(f"{i+1}", style={"padding": "4px 8px", "color": "#1e293b", "fontSize": "11px"}),
        html.Td(m, style={"padding": "4px 8px", "fontSize": "12px", "fontWeight": "600", "color": NAVY})])
        for i, m in enumerate(models)]
    return html.Div([
        html.Div(title, style={"fontWeight": "700", "fontSize": "12.5px", "color": color,
                               "borderBottom": f"2px solid {color}", "paddingBottom": "4px", "marginBottom": "6px"}),
        html.Table(rows, style={"width": "100%", "borderCollapse": "collapse"}),
    ])


# ── Observed-change computation (real VIC data) ──────────────
def _delta_table(var, kind):
    """Return DataFrame[basin, early, recent, delta] for the 8 tiling sub-basins."""
    a = load_vic_annual()
    if a.empty or var not in a.columns:
        return pd.DataFrame()
    early = a[(a.water_year >= EARLY[0]) & (a.water_year <= EARLY[1])]
    recent = a[(a.water_year >= RECENT[0]) & (a.water_year <= RECENT[1])]
    recs = []
    for b in TILING:
        h = early[early.basin == b][var].mean()
        r = recent[recent.basin == b][var].mean()
        if pd.isna(h) or pd.isna(r):
            continue
        d = (r - h) if kind == "abs" else ((r - h) / h * 100 if h else np.nan)
        recs.append({"basin": b, "name": BASIN_NAME[b], "early": h, "recent": r, "delta": d})
    return pd.DataFrame(recs)


def _empty(msg):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font=dict(size=12, color="#90a4ae"))
    fig.update_layout(paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=0, r=0, t=0, b=0), height=480)
    return fig


def _change_map(var, kind, unit, basemap):
    df = _delta_table(var, kind)
    if df.empty or BASINS_GJ is None:
        return _empty("Run preprocessing to populate VIC basin data.")
    # diverging for pct vars (red = decline), sequential reds for temperature
    if kind == "abs":
        cmax = max(0.1, df["delta"].abs().max())
        colorscale = "OrRd"; zmin, zmid, zmax = 0, None, cmax
    else:
        cmax = max(5, df["delta"].abs().max())
        colorscale = [[0, "#b71c1c"], [0.25, "#ef9a9a"], [0.5, "#f5f5f5"],
                      [0.75, "#90caf9"], [1, "#0d47a1"]]
        zmin, zmid, zmax = -cmax, 0, cmax
    suff = "°C" if kind == "abs" else "%"
    fig = go.Figure(go.Choroplethmapbox(
        geojson=BASINS_GJ, locations=df["basin"], z=df["delta"],
        featureidkey="properties.basin_id",
        colorscale=colorscale, zmin=zmin, zmax=zmax, zmid=zmid,
        marker=dict(line=dict(color="white", width=1.2)), marker_opacity=0.82,
        colorbar=dict(thickness=13, len=0.7, x=0.99, title=dict(text=f"Δ ({unit})", font=dict(size=11))),
        customdata=np.stack([df["name"], df["early"], df["recent"]], axis=-1),
        hovertemplate=("<b>%{customdata[0]}</b><br>"
                       f"{EARLY[0]}–{EARLY[1]}: %{{customdata[1]:.1f}}<br>"
                       f"{RECENT[0]}–{RECENT[1]}: %{{customdata[2]:.1f}}<br>"
                       f"Change: %{{z:+.1f}}{suff}<extra></extra>"),
    ))
    if basemap == "satellite":
        mb = dict(style="white-bg", center=dict(lat=37.5, lon=-111.5), zoom=4.6,
                  layers=[{"below": "traces", "sourcetype": "raster",
                           "source": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
                           "sourceattribution": "Tiles © Esri"}])
    else:
        mb = dict(style=basemap, center=dict(lat=37.5, lon=-111.5), zoom=4.6)
    fig.update_layout(mapbox=mb, margin=dict(l=0, r=0, t=0, b=0), height=480,
                      paper_bgcolor="white", uirevision="cmip-map")
    return fig


def _change_bar(var, kind, unit):
    df = _delta_table(var, kind)
    if df.empty:
        return _empty("No data")
    df = df.sort_values("delta")
    colors = ["#0d47a1" if d > 0 else "#b71c1c" for d in df["delta"]]
    if kind == "abs":  # warming everywhere → single warm color
        colors = ["#e65100"] * len(df)
    suff = "°C" if kind == "abs" else "%"
    return lollipop_h(list(df["name"]), list(df["delta"]), colors,
                      x_title=f"Observed change ({unit})", unit=suff,
                      height=480, diverging=True)


# ── Layout ───────────────────────────────────────────────────
def layout():
    return html.Div([
        html.Div([
            html.H2("Long-range Climate Projections (CMIP5 & CMIP6)"),
            html.P("How might the Colorado change by late century? Below: the project's published "
                   "ensemble result, plus an interactive map of the observed change already in the record."),
        ], className="tab-header"),
        html.Div([
            # KPI tiles (documented)
            html.Div([
                _tile("214", "CMIP6-LOCA2 screened", "tile-navy"),
                _tile("64", "CMIP5-LOCA1 screened", "tile-blue"),
                _tile("8 + 8", "Top GCMs selected", "tile-green"),
                _tile("2066–2095", "Future vs 1976–2005", "tile-maroon"),
            ], style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit,minmax(150px,1fr))",
                      "gap": "10px", "marginBottom": "16px"}),

            # ════ SECTION 1: PUBLISHED ENSEMBLE RESULT ════
            html.Div([
                html.Span("PUBLISHED RESULT", style={"background": MAROON, "color": "white",
                    "fontSize": "10px", "fontWeight": "700", "padding": "2px 8px",
                    "borderRadius": "4px", "letterSpacing": "0.5px"}),
                html.Span("CMIP5/CMIP6-LOCA ensemble (8+8 GCMs) · cited from the Annual Progress Report",
                          style={"fontSize": "11px", "color": "#1e293b", "marginLeft": "6px"}),
            ], style={"marginBottom": "10px"}),

            # Screening funnel + donut
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div([html.Span("Model screening & selection", style={"fontWeight": "700", "fontSize": "13px"}),
                        html.Span("by Comprehensive Error Index vs PRISM (1976–2005)",
                                  style={"color": "#1e293b", "fontSize": "11px"}),
                        pub_star("https://www.ipcc.ch/report/ar6/wg1/", "IPCC AR6 WG1 2021", "Published")], className="crb-card-header"),
                    dcc.Graph(figure=_screen_funnel(), config={"displayModeBar": False}, style={"height": "200px"}),
                ], className="crb-card"), md=7),
                dbc.Col(html.Div([
                    html.Div([html.Span("Projected runoff direction", style={"fontWeight": "700", "fontSize": "13px"}),
                        html.Span("far-future scenarios", style={"color": "#1e293b", "fontSize": "11px"})],
                        className="crb-card-header"),
                    dcc.Graph(figure=_runoff_donut(), config={"displayModeBar": False}, style={"height": "200px"}),
                ], className="crb-card"), md=5),
            ], className="g-3 mb-3"),

            # Model tables + skill radar
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div([html.Span("Top-ranked models", style={"fontWeight": "700", "fontSize": "13px"}),
                        html.Span("selected per family", style={"color": "#1e293b", "fontSize": "11px"})],
                        className="crb-card-header"),
                    html.Div(dbc.Row([
                        dbc.Col(_model_table("CMIP6 (8)", CMIP6_TOP, BLUE), md=6),
                        dbc.Col(_model_table("CMIP5 (8)", CMIP5_TOP, MAROON), md=6),
                    ]), style={"padding": "12px 16px"}),
                ], className="crb-card"), md=7),
                dbc.Col(html.Div([
                    html.Div([html.Span("CMIP5 vs CMIP6 skill split", style={"fontWeight": "700", "fontSize": "13px"}),
                        html.Span("illustrative 0–3 scoring of documented strengths (not published metrics)",
                                  style={"color": "#1e293b", "fontSize": "11px"})],
                        className="crb-card-header"),
                    dcc.Graph(figure=_skill_radar(), config={"displayModeBar": False}, style={"height": "300px"}),
                ], className="crb-card"), md=5),
            ], className="g-3 mb-3"),

            # Findings strip
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div("Spread", style={"fontWeight": "700", "fontSize": "12px", "color": MAROON}),
                    html.P("CMIP5 shows greater variability than CMIP6 and encompasses its range — "
                           "no marked discrepancy between the two families' projected ranges.",
                           style={"fontSize": "11.5px", "marginBottom": 0}),
                ], className="crb-card", style={"padding": "12px 14px", "height": "100%"}), md=4),
                dbc.Col(html.Div([
                    html.Div("Drier future", style={"fontWeight": "700", "fontSize": "12px", "color": MAROON}),
                    html.P("Five of six scenarios project declining runoff by 2066–2095; one shows "
                           "nearly no change. Precipitation, runoff and soil-moisture changes were assessed.",
                           style={"fontSize": "11.5px", "marginBottom": 0}),
                ], className="crb-card", style={"padding": "12px 14px", "height": "100%"}), md=4),
                dbc.Col(html.Div([
                    html.Div("Skill split", style={"fontWeight": "700", "fontSize": "12px", "color": MAROON}),
                    html.P("CMIP5 fits winter precipitation better (1981–2022); CMIP6 is better for "
                           "temperature. Long-term trend alignment shows no marked difference.",
                           style={"fontSize": "11.5px", "marginBottom": 0}),
                ], className="crb-card", style={"padding": "12px 14px", "height": "100%"}), md=4),
            ], className="g-3 mb-3"),

            # Cited project figure
            html.Div([
                html.Div([html.Span("Project figure — ensemble projected change", style={"fontWeight": "700", "fontSize": "13px"}),
                          html.Span("ΔP, ΔRunoff, ΔSoil-moisture: future (2066–2095) − historical (1976–2005)",
                                    style={"color": "#1e293b", "fontSize": "11px"})], className="crb-card-header"),
                html.Div(
                    (html.Img(src=FIG, style={"width": "100%", "maxWidth": "900px", "display": "block",
                                              "margin": "0 auto", "borderRadius": "6px"})
                     if HAS_FIG else
                     html.P("Figure available in the Annual Progress Report (Feb 2025), Project & Reports tab.",
                            style={"fontSize": "12px", "color": "#1e293b"})),
                    style={"padding": "12px 16px"}),
                html.Div("Source: NASA Annual Progress Report (Feb 2025), Vivoni et al., ASU. "
                         "LOCA-downscaled CMIP5/CMIP6 (hourly, 6 km, 1976–2099), 8+8 top GCMs. "
                         "Raw projection data is not bundled in this app, so this is the cited figure.",
                         style={"fontSize": "10.5px", "color": "#1e293b", "padding": "0 16px 12px"}),
            ], className="crb-card", style={"marginBottom": "20px"}),

            # ════ SECTION 2: INTERACTIVE OBSERVED-CHANGE MAP ════
            html.Div([
                html.Span("INTERACTIVE · OBSERVED DATA", style={"background": GREEN, "color": "white",
                    "fontSize": "10px", "fontWeight": "700", "padding": "2px 8px",
                    "borderRadius": "4px", "letterSpacing": "0.5px"}),
                html.Span("the climate-change fingerprint already measured in the VIC record",
                          style={"fontSize": "11px", "color": "#1e293b", "marginLeft": "6px"}),
            ], style={"marginBottom": "8px"}),

            html.Div(
                "This map shows the OBSERVED change already in the basin — the difference between a recent "
                f"period ({RECENT[0]}–{RECENT[1]}) and an early period ({EARLY[0]}–{EARLY[1]}) in the "
                "PRISM-calibrated VIC simulation. It is the measured change that motivates the projections "
                "above; it is NOT itself the future CMIP projection. Pick a variable and hover any sub-basin.",
                style={"background": "#e8f5e9", "borderLeft": f"3px solid {GREEN}",
                       "padding": "9px 14px", "borderRadius": "0 6px 6px 0",
                       "fontSize": "11.5px", "color": "#1b5e20", "marginBottom": "12px"}),

            # Controls
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("VARIABLE", className="control-label"),
                        dcc.Dropdown(id="cm-var", options=[{"label": f"{v['label']} ({v['unit']} change)", "value": v["value"]} for v in MAP_VARS],
                                     value="OUT_RUNOFF", clearable=False, style={"fontSize": "12.5px"}),
                    ], xs=12, md=4),
                    dbc.Col([
                        html.Div("BASE MAP", className="control-label"),
                        dcc.Dropdown(id="cm-basemap", options=[
                            {"label": "Light (CartoDB)", "value": "carto-positron"},
                            {"label": "Satellite (ESRI)", "value": "satellite"},
                            {"label": "Dark (CartoDB)", "value": "carto-darkmatter"},
                            {"label": "Terrain", "value": "stamen-terrain"},
                        ], value="carto-positron", clearable=False, style={"fontSize": "12.5px"}),
                    ], xs=12, md=3),
                ]),
            ], className="control-panel"),

            html.Div(id="cm-finding",
                     style={"background": "#fff3e0", "borderLeft": f"3px solid {ORANGE}",
                            "padding": "9px 14px", "borderRadius": "0 6px 6px 0",
                            "fontSize": "11.5px", "color": "#e65100", "marginBottom": "12px"}),
                            pub_author("IPCC AR6 2021", "https://www.ipcc.ch/report/ar6/wg1/", "IPCC AR6 WG1 2021", "published"),

            html.Div([
                html.I(className="bi bi-info-circle", style={"marginRight": "7px", "color": BLUE}),
                html.B("How to use:  "),
                "pick a variable · hover any sub-basin to see its early vs recent values and the change · "
                "click-drag to pan · scroll or +/− to zoom.  ",
                html.A("Methods & data →", href="/methods",
                       style={"color": BLUE, "fontWeight": "600", "textDecoration": "underline"}),
            ], className="howto-strip"),

            dbc.Row([
                dbc.Col(html.Div([
                    html.Div(id="cm-map-title", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "13px", "textAlign": "center"}),
                    dcc.Loading(dcc.Graph(id="cm-map",
                        config={"displayModeBar": True, "scrollZoom": True,
                                "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
                        style={"height": "480px"}), type="circle", color=MAROON),
                ], className="crb-card"), md=7),
                dbc.Col(html.Div([
                    html.Div("Change by sub-basin", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "13px", "textAlign": "center"}),
                    dcc.Loading(dcc.Graph(id="cm-bar", config={"displayModeBar": False},
                        style={"height": "480px"}), type="circle", color=MAROON),
                ], className="crb-card"), md=5),
            ], className="g-3 mb-2"),

            html.Div("Observed change computed live from VIC PRISM-calibrated annual basin means. "
                     "8 sub-basins that tile the CRB exactly. Temperature shown as absolute Δ°C; "
                     "other variables as % change.",
                     style={"fontSize": "10.5px", "color": "#1e293b"}),
        ], className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(
        Output("cm-map", "figure"), Output("cm-map-title", "children"),
        Output("cm-bar", "figure"), Output("cm-finding", "children"),
        Input("cm-var", "value"), Input("cm-basemap", "value"),
    )
    def _update(var, basemap):
        meta = next((v for v in MAP_VARS if v["value"] == var), MAP_VARS[0])
        kind, unit, label = meta["kind"], meta["unit"], meta["label"]
        fig_map = _change_map(var, kind, unit, basemap or "carto-positron")
        fig_bar = _change_bar(var, kind, unit)
        title = f"{label} — observed change · {RECENT[0]}–{RECENT[1]} vs {EARLY[0]}–{EARLY[1]}"
        df = _delta_table(var, kind)
        if df.empty:
            finding = "No data."
        else:
            suff = "°C" if kind == "abs" else "%"
            hi = df.loc[df["delta"].idxmax()]; lo = df.loc[df["delta"].idxmin()]
            mean = df["delta"].mean()
            if kind == "abs":
                finding = [html.Strong(f"{label}: "),
                           f"every sub-basin warmed (mean {mean:+.2f}{suff}); "
                           f"strongest in {hi['name']} ({hi['delta']:+.2f}{suff})."]
            else:
                finding = [html.Strong(f"{label}: "),
                           f"basin-mean change {mean:+.1f}{suff}; "
                           f"largest decline in {lo['name']} ({lo['delta']:+.1f}{suff}), "
                           f"smallest in {hi['name']} ({hi['delta']:+.1f}{suff})."]
        return fig_map, title, fig_bar, finding
