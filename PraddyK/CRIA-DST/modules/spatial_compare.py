# ============================================================
# modules/spatial_compare.py
# Static side-by-side spatial comparison (no animation):
# two variables, one water year, each with its basin-average trend.
# ============================================================

from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
import numpy as np
import plotly.graph_objects as go

from utils.data_loader import load_spatial, load_vic_annual
from utils.basin_map import render_basin_map

MAROON = "#8C1D40"
LEAF_B = ["Green", "SanJuan", "UpperColo", "GlenCanyon",
          "Gila", "GrandCanyon", "LittleColo", "LowerColo"]

VARS = [
    ("OUT_SWE",        "Snow Water Equivalent", "mm"),
    ("OUT_RUNOFF",     "Runoff",                "mm/yr"),
    ("OUT_PREC",       "Precipitation",         "mm/yr"),
    ("OUT_EVAP",       "Total Evapotranspiration", "mm/yr"),
    ("OUT_SOIL_MOIST", "Soil Moisture",         "mm"),
    ("OUT_BASEFLOW",   "Baseflow",              "mm/yr"),
    ("OUT_AIR_TEMP",   "Air Temperature",       "°C"),
    ("OUT_SNOW_MELT",  "Snowmelt",              "mm/yr"),
]
OPTS = [{"label": f"{l} ({u})", "value": v} for v, l, u in VARS]
UNIT = {v: u for v, l, u in VARS}
NAME = {v: l for v, l, u in VARS}
CMAP = {"OUT_SWE": "Blues", "OUT_RUNOFF": "Blues", "OUT_PREC": "Blues",
        "OUT_EVAP": "YlGn", "OUT_SOIL_MOIST": "YlOrBr", "OUT_BASEFLOW": "Purples",
        "OUT_AIR_TEMP": "RdYlBu_r", "OUT_SNOW_MELT": "GnBu"}


def _map_card(side):
    # xs=6 at EVERY breakpoint → the two maps always stay face-to-face (side by
    # side); they just shrink together on smaller screens instead of stacking.
    return dbc.Col(html.Div([
        html.Div(id=f"spc-title-{side}", className="crb-card-header",
                 style={"fontWeight": "700", "fontSize": "12.5px"}),
        dcc.Loading(html.Div(
            html.Img(id=f"spc-img-{side}",
                     style={"width": "100%", "height": "auto",
                            "display": "block", "margin": "0 auto", "borderRadius": "8px"}),
            style={"padding": "6px", "textAlign": "center"}),
            type="circle", color=MAROON),
        dcc.Loading(dcc.Graph(id=f"spc-trend-{side}", config={"displayModeBar": False},
                              style={"height": "230px"}), type="circle", color=MAROON),
    ], className="crb-card"), xs=6, className="spc-col")


def layout():
    return html.Div([
        html.Div([
            html.H2("Compare by Year"),
            html.P("Purpose: freeze on a single water year and compare any two variables across "
                   "the basin side by side, each with its sub-basin values and basin-average "
                   "trend. Pick a year to inspect it in detail, or download all years as a PDF."),
        ], className="tab-header"),
        html.Div([
            dbc.Row([
                dbc.Col([html.Div("LEFT VARIABLE", className="control-label"),
                         dcc.Dropdown(id="spc-var-left", options=OPTS, value="OUT_SWE",
                                      clearable=False)], xs=12, md=4),
                dbc.Col([html.Div("RIGHT VARIABLE", className="control-label"),
                         dcc.Dropdown(id="spc-var-right", options=OPTS, value="OUT_RUNOFF",
                                      clearable=False)], xs=12, md=4),
                dbc.Col([html.Div("WATER YEAR", className="control-label"),
                         dcc.Slider(id="spc-year", min=1984, max=2024, step=1, value=2024,
                                    marks={y: str(y) for y in range(1990, 2025, 10)},
                                    tooltip={"placement": "bottom", "always_visible": False})],
                        xs=12, md=4),
            ], className="g-2 mb-2"),
            dbc.Row([_map_card("left"), _map_card("right")], className="g-3 spc-row"),
        ], className="tab-body"),
    ])


import json as _json, io as _io, base64 as _b64, os as _os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as _plt
import matplotlib.colors as _mcolors

_ASSETS = _os.path.join(_os.path.dirname(__file__), "..", "assets")
_EXTENT = (-117.2, -102.8, 29.4, 45.2)
_STATE = [("WYOMING", -108.7, 43.3), ("NEVADA", -116.2, 39.6), ("UTAH", -111.7, 39.7),
          ("COLORADO", -105.4, 39.1), ("CALIFORNIA", -116.4, 34.7),
          ("ARIZONA", -111.7, 33.1), ("NEW MEXICO", -105.0, 34.1)]


def _gj(p):
    try:
        return _json.load(open(_os.path.join(_ASSETS, p)))
    except Exception:
        return None


def _rings(g):
    out = []
    for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
        for r in poly:
            out.append(([q[0] for q in r], [q[1] for q in r]))
    return out


_BAS = _gj("crb_basins.geojson")
_RIV = _gj("crb_rivers.geojson")


def _anom_png(var, year, name):
    """Per-cell VIC data as % of the 1984–2024 mean, coloured red↔blue like Basin-Wide Overview."""
    df = load_spatial(var)
    if df is None or df.empty:
        return ""
    base = df.groupby(["lat", "lon"])["value"].mean().rename("b").reset_index()
    yv = df[df["water_year"] == year][["lat", "lon", "value"]].merge(base, on=["lat", "lon"])
    if yv.empty:
        return ""
    yv["anom"] = np.where(np.abs(yv["b"]) > 1e-6, yv["value"] / yv["b"] * 100.0, np.nan)
    piv = yv.pivot_table(index="lat", columns="lon", values="anom")
    lon = piv.columns.values.astype(float); lat = piv.index.values.astype(float)
    fig, ax = _plt.subplots(figsize=(6.4, 7.2), dpi=95); fig.patch.set_facecolor("white")
    norm = _mcolors.TwoSlopeNorm(vcenter=100, vmin=40, vmax=160)
    m = ax.pcolormesh(lon, lat, np.ma.masked_invalid(piv.values), cmap="RdBu",
                      norm=norm, shading="nearest", zorder=2, rasterized=True)
    for nm, lo, la in _STATE:
        ax.text(lo, la, nm, color="#9aa5b1", fontsize=8, weight="bold",
                ha="center", va="center", zorder=3)
    if _BAS:
        for f in _BAS["features"]:
            bid = f["properties"].get("basin_id")
            for xs, ys in _rings(f["geometry"]):
                ax.plot(xs, ys, color=("#0d2137" if bid == "CRB" else "#7a2740"),
                        lw=(1.7 if bid == "CRB" else 0.6), zorder=5 if bid == "CRB" else 4)
    if _RIV:
        for f in _RIV["features"]:
            for xs, ys in _rings(f["geometry"]):
                ax.plot(xs, ys, color="#0b4f9c", lw=0.7, zorder=4, alpha=0.55)
    ax.set_xlim(_EXTENT[0], _EXTENT[1]); ax.set_ylim(_EXTENT[2], _EXTENT[3])
    ax.set_aspect(1.0 / np.cos(np.deg2rad(37.5))); ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color("#cfd8dc")
    ax.text(0.03, 0.965, f"WY {year}", transform=ax.transAxes, color="#0d2137",
            fontsize=18, weight="bold", va="top", zorder=7)
    ax.text(0.03, 0.03, "red = below 1984–2024 mean (dry) · blue = above (wet)",
            transform=ax.transAxes, color="#6b7a8d", fontsize=7.3, va="bottom", zorder=7)
    cb = fig.colorbar(m, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label(f"{name} — % of 1984–2024 mean", fontsize=8.5); cb.ax.tick_params(labelsize=7.5)
    ax.set_title(f"Colorado River Basin — {name}", color=MAROON, fontsize=11, weight="bold", pad=8)
    fig.tight_layout()
    buf = _io.BytesIO(); fig.savefig(buf, format="png", facecolor="white", bbox_inches="tight", dpi=95)
    _plt.close(fig)
    return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()


def _render(var, year):
    # Gridded per-cell VIC data (viridis: perceptually-uniform, colorblind-safe) with
    # sub-basin value + rank labels — exactly the original static comparison maps.
    name = NAME.get(var, var)
    df = load_vic_annual()
    if df is None or df.empty or var not in df.columns:
        return "", go.Figure(), name
    yr = df[df["water_year"] == year][["basin", var]].dropna()
    yr_vals = dict(zip(yr["basin"], yr[var]))
    allv = yr[var]
    ranks = {b: (allv <= v).mean() * 100 for b, v in zip(yr["basin"], yr[var])}
    label_map = {}
    for b in LEAF_B:
        v = yr_vals.get(b)
        if v is not None:
            label_map[b] = f"{v:.1f}" + (f" · {ranks.get(b, 0):.0f}th" if b in ranks else "")
    gdf = load_spatial(var)
    grid = (gdf[gdf["water_year"] == year][["lat", "lon", "value"]]
            if gdf is not None and not gdf.empty else None)
    src = render_basin_map(grid, yr_vals, ranks, name, UNIT.get(var, ""), year,
                           mode_label="Grid", label_map=label_map, cmap="viridis") or ""
    crb = df[df["basin"] == "CRB"][["water_year", var]].dropna().sort_values("water_year")
    xs = crb["water_year"].to_numpy(dtype=float)
    ys = crb[var].to_numpy(dtype=float)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="#cbb3bd", width=1.4)))
    m = xs <= year
    fig.add_trace(go.Scatter(x=xs[m], y=ys[m], mode="lines", line=dict(color=MAROON, width=2.4)))
    cur = crb[crb["water_year"] == year]
    if not cur.empty:
        fig.add_trace(go.Scatter(x=[year], y=[float(cur[var].iloc[0])], mode="markers",
                      marker=dict(color=MAROON, size=11, line=dict(color="white", width=1.5))))
    fig.update_layout(margin=dict(l=46, r=10, t=22, b=26), height=230, showlegend=False,
                      paper_bgcolor="white", plot_bgcolor="white",
                      xaxis=dict(title="Water year", gridcolor="#eef2f6"),
                      yaxis=dict(title=f"{name} ({UNIT.get(var,'')})", gridcolor="#eef2f6"),
                      title=dict(text="basin-average trend", font=dict(size=11, color="#546e7a"),
                                 x=0.5, y=0.98))
    return src, fig, f"{name} · WY{year}"


def register_callbacks(app):
    @app.callback(
        Output("spc-img-left", "src"), Output("spc-trend-left", "figure"),
        Output("spc-title-left", "children"),
        Input("spc-var-left", "value"), Input("spc-year", "value"))
    def _left(var, year):
        return _render(var, year)

    @app.callback(
        Output("spc-img-right", "src"), Output("spc-trend-right", "figure"),
        Output("spc-title-right", "children"),
        Input("spc-var-right", "value"), Input("spc-year", "value"))
    def _right(var, year):
        return _render(var, year)
