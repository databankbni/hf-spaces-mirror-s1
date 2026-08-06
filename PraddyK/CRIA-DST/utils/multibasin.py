"""
utils/multibasin.py — reusable "all sub-basins on one chart" figure.

A single Plotly figure that overlays every sub-basin as a smooth, distinctly
coloured line, each indexed to 100 = its own 1984–2024 mean (so basins of very
different size are directly comparable). Prominent peaks / troughs get stylish
"knot" markers. Used by the Basin-Wide Overview tab and offered as an
"All sub-basins (compare)" option inside the per-basin analysis views, so the
same comparison lives where users already pick one basin at a time.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from utils.data_loader import load_vic_annual

# The value used in a basin dropdown to request the all-sub-basins overlay.
ALL_BASINS = "ALL"

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
# draw order → whole-basin (CRB) line ends up on top
DRAW_ORDER = ["Green", "UpperColo", "SanJuan", "GlenCanyon", "UpperBasin", "LowerColo",
              "GrandCanyon", "LittleColo", "Gila", "LowerBasin", "CRB"]


def _series(g, var):
    """Return the y-series for a basin sub-frame and a variable key ('RE' = Q/P)."""
    if var == "RE":
        return (g["OUT_RUNOFF"] + g["OUT_BASEFLOW"]) / g["OUT_PREC"]
    if var in g.columns:
        return g[var]
    return None


def _peaks(y):
    """Indices of prominent local maxima / minima (scaled to each basin's own spread)."""
    n = len(y)
    if n < 5:
        return []
    prom = np.nanstd(y) * 0.75
    try:
        from scipy.signal import find_peaks
        hi, _ = find_peaks(y, prominence=prom)
        lo, _ = find_peaks(-y, prominence=prom)
        return sorted(set(hi) | set(lo))
    except Exception:
        hi = [i for i in range(1, n - 1) if y[i] > y[i - 1] and y[i] >= y[i + 1]
              and (y[i] - np.min(y)) > prom]
        lo = [i for i in range(1, n - 1) if y[i] < y[i - 1] and y[i] <= y[i + 1]
              and (np.max(y) - y[i]) > prom]
        return sorted(set(hi) | set(lo))


def multi_basin_fig(var, years=None, height=440, df=None, animate=False):
    """Smooth, knotted overlay of every sub-basin for `var`, % of each basin's mean.
    If animate=True, return a Plotly figure with built-in Play/Pause that progressively
    draws every sub-basin line from the first water year to the last.

    var    : a VIC annual column ('OUT_SWE', 'OUT_RUNOFF', ...) or 'RE' (Q/P).
    years  : optional (lo, hi) water-year range to restrict the x-axis.
    df     : optional preloaded VIC-annual frame (else loaded here).
    """
    if df is None:
        try:
            df = load_vic_annual()
        except Exception:
            df = pd.DataFrame()
    fig = go.Figure()
    if df is None or df.empty:
        fig.add_annotation(text="No data", xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(color="#90a4ae"))
        fig.update_layout(paper_bgcolor="white", plot_bgcolor="white",
                          xaxis=dict(visible=False), yaxis=dict(visible=False), height=height)
        return fig

    if animate:
        return _animated_fig(df, var, years, height)

    for b in DRAW_ORDER:
        g = df[df["basin"] == b].sort_values("water_year")
        if years:
            g = g[(g["water_year"] >= years[0]) & (g["water_year"] <= years[1])]
        if g.empty:
            continue
        y = _series(g, var)
        if y is None:
            continue
        base = float(np.nanmean(y.values))
        if base == 0 or np.isnan(base):
            continue
        crb = (b == "CRB")
        color = BASIN_COLORS[b]
        x = g["water_year"].values
        pct = (y / base * 100).values
        fig.add_trace(go.Scatter(
            x=x, y=pct, name=BASIN_LABEL[b], mode="lines", legendgroup=b,
            line=dict(color=color, width=3.2 if crb else 1.7, shape="spline", smoothing=0.6),
            opacity=1.0 if crb else 0.85,
            hovertemplate=f"{BASIN_LABEL[b]}<br>WY %{{x}}: %{{y:.0f}}% of mean<extra></extra>"))
        k = _peaks(pct)
        if k:
            fig.add_trace(go.Scatter(
                x=x[k], y=pct[k], mode="markers", legendgroup=b, showlegend=False,
                marker=dict(color=color, size=8 if crb else 6,
                            line=dict(color="white", width=1.4 if crb else 1.1)),
                hovertemplate=f"{BASIN_LABEL[b]}<br>WY %{{x}}: %{{y:.0f}}% of mean<extra></extra>"))

    fig.add_hline(y=100, line_dash="dash", line_color="#b0bec5", line_width=1)
    fig.update_layout(margin=dict(l=52, r=15, t=10, b=40), height=height,
                      paper_bgcolor="white", plot_bgcolor="white", hovermode="closest",
                      yaxis_title="% of 1984–2024 mean", xaxis_title="Water year",
                      legend=dict(orientation="h", y=-0.16, x=0, font=dict(size=9)))
    return fig


def _animated_fig(df, var, years, height):
    """Progressive-draw animation: Play reveals every sub-basin line year by year."""
    series = []
    for b in DRAW_ORDER:
        g = df[df["basin"] == b].sort_values("water_year")
        if years:
            g = g[(g["water_year"] >= years[0]) & (g["water_year"] <= years[1])]
        if g.empty:
            continue
        y = _series(g, var)
        if y is None:
            continue
        base = float(np.nanmean(y.values))
        if base == 0 or np.isnan(base):
            continue
        series.append(dict(b=b, x=g["water_year"].values, pct=(y / base * 100).values,
                           color=BASIN_COLORS[b], label=BASIN_LABEL[b], crb=(b == "CRB")))
    fig = go.Figure()
    if not series:
        fig.add_annotation(text="No data", xref="paper", yref="paper", x=0.5, y=0.5,
                           showarrow=False, font=dict(color="#90a4ae"))
        fig.update_layout(height=height, paper_bgcolor="white", plot_bgcolor="white")
        return fig
    all_years = sorted({int(v) for s in series for v in s["x"]})
    allpct = np.concatenate([s["pct"] for s in series])
    ymin, ymax = float(np.nanmin(allpct)), float(np.nanmax(allpct))
    pad = (ymax - ymin) * 0.06 or 5

    # base traces = full lines (the default, static view before pressing Play)
    for s in series:
        fig.add_trace(go.Scatter(
            x=s["x"], y=s["pct"], name=s["label"], mode="lines", legendgroup=s["b"],
            line=dict(color=s["color"], width=3.2 if s["crb"] else 1.7, shape="spline", smoothing=0.6),
            opacity=1.0 if s["crb"] else 0.85,
            hovertemplate=f"{s['label']}<br>WY %{{x}}: %{{y:.0f}}% of mean<extra></extra>"))

    # frames: reveal cumulatively up to each water year
    frames = []
    for yr in all_years:
        fdata = [go.Scatter(x=s["x"][s["x"] <= yr], y=s["pct"][s["x"] <= yr]) for s in series]
        frames.append(go.Frame(data=fdata, name=str(yr)))
    fig.frames = frames

    play = dict(label="▶ Play", method="animate",
                args=[None, {"frame": {"duration": 220, "redraw": True},
                             "transition": {"duration": 0}, "mode": "immediate"}])
    pause = dict(label="⏸ Pause", method="animate",
                 args=[[None], {"frame": {"duration": 0, "redraw": False},
                                "mode": "immediate", "transition": {"duration": 0}}])
    slider = dict(active=len(all_years) - 1, x=0.06, len=0.9, y=-0.08, pad=dict(t=0, b=0),
                  currentvalue=dict(prefix="WY ", font=dict(size=11)),
                  steps=[dict(method="animate", label=str(yr),
                              args=[[str(yr)], {"frame": {"duration": 0, "redraw": True},
                                                "mode": "immediate"}]) for yr in all_years])
    fig.add_hline(y=100, line_dash="dash", line_color="#b0bec5", line_width=1)
    fig.update_layout(
        margin=dict(l=52, r=15, t=44, b=64), height=height + 30,
        paper_bgcolor="white", plot_bgcolor="white", hovermode="closest",
        yaxis=dict(title="% of 1984–2024 mean", range=[ymin - pad, ymax + pad]),
        xaxis=dict(title="Water year", range=[all_years[0] - 0.5, all_years[-1] + 0.5]),
        legend=dict(orientation="h", y=-0.28, x=0, font=dict(size=9)),
        updatemenus=[dict(type="buttons", showactive=False, direction="left",
                          x=0.0, y=1.18, xanchor="left", yanchor="top",
                          pad=dict(t=0, r=6), buttons=[play, pause])],
        sliders=[slider])
    return fig
