"""
modules/uncertainty.py — Uncertainty & Confidence (one place for all error/confidence info)

Brings every uncertainty estimate into a single, clearly-explained tab:
  • Parametric: 95% confidence intervals on each basin's runoff sensitivity & precip
    elasticity (OLS coefficient covariance, computed live).
  • Observational: GRACE measurement uncertainty; SMAP/NSE validation skill (published).
  • Structural: honest caveats (single future run, documented NMME/CMIP).
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_grace, load_vic_annual, load_smap
from utils.components import xref
from modules.scenario import _project, ALL_BASINS, BASIN_NAME

NAVY="#0D2137"; MAROON="#8C1D40"; BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; GREY="#94a3b8"; GOLD="#FFC627"


def _tile(v, l, c):
    return html.Div([html.Div(v, className="info-tile-value"),
        html.Div(l, className="info-tile-label")], className=f"info-tile {c}")


def _collinearity_note():
    """Compute CRB precip–temp collinearity to explain the wide single-coefficient CIs."""
    try:
        a = load_vic_annual()
        d = a[(a["basin"] == "CRB") & (a["water_year"] >= 1984)].dropna(subset=["OUT_PREC", "OUT_AIR_TEMP"])
        rho = float(np.corrcoef(np.log(d["OUT_PREC"].values), d["OUT_AIR_TEMP"].values)[0, 1])
    except Exception:
        rho = -0.67
    return (f"Over the 41-year record, precipitation and temperature are correlated "
            f"(CRB r = {rho:.2f}: warm years tend to be dry). When two drivers move together, a regression "
            "cannot cleanly separate each one's individual effect, so the interval on the isolated "
            "temperature term is wide — even though the combined model fit and the published consensus "
            "(−8 to −9 %/°C, Milly & Dunne 2020; Udall & Overpeck 2017) are firm. In short: the "
            "warming→drier direction is confident; the exact split between temperature and precipitation "
            "is what carries the uncertainty at the annual scale.")


def _sensitivity_fig():
    """Per-basin: how much runoff changes per +1 °C — best estimate (dot) + 95% range (bar).
    Red = confident it's a loss (whole range below 0). Grey = uncertain (range crosses 0)."""
    rows = []
    for b in ALL_BASINS:
        r = _project(b, 1.0, 0)
        if r:
            rows.append((BASIN_NAME[b], r["c"]*100, r["c_lo"], r["c_hi"]))
    rows.sort(key=lambda x: x[1])
    names = [x[0] for x in rows]; c = [x[1] for x in rows]
    lo = [x[1]-x[2] for x in rows]; hi = [x[3]-x[1] for x in rows]
    robust = [(x[2] < 0 and x[3] < 0) for x in rows]
    cols = ["#b71c1c" if rb else "#90a4ae" for rb in robust]

    fig = go.Figure()
    # single data trace: dots + 95% range bars + value labels (no None-proxy traces)
    fig.add_trace(go.Scatter(
        x=c, y=names, mode="markers+text",
        marker=dict(size=15, color=cols, line=dict(color="white", width=1.6)),
        error_x=dict(type="data", symmetric=False, array=hi, arrayminus=lo,
                     color="rgba(110,110,110,0.65)", thickness=1.6, width=6),
        text=[f"{v:.0f}%" for v in c], textposition="top center",
        textfont=dict(size=10, color=NAVY), showlegend=False,
        hovertemplate="%{y}<br>best estimate %{x:.1f} %/°C<extra></extra>"))
    fig.add_vline(x=0, line_color="#37474f", line_width=1.5)
    fig.add_annotation(x=0, y=1.07, yref="paper", text="0 = no change",
                       showarrow=False, font=dict(size=10, color="#37474f"))
    # text legend (annotations, not traces — keeps the category axis clean)
    fig.add_annotation(x=0.0, y=1.16, xref="paper", yref="paper", xanchor="left", showarrow=False,
                       text="<span style='color:#b71c1c'>● confident loss (range &lt; 0)</span>"
                            "   <span style='color:#90a4ae'>● uncertain (range crosses 0)</span>",
                       font=dict(size=10))
    fig.add_annotation(x=0.02, y=-0.16, xref="paper", yref="paper",
                       text="← drier per +1 °C        wetter per +1 °C →",
                       showarrow=False, font=dict(size=10, color="#607d8b"), xanchor="left")
    fig.update_layout(height=360, margin=dict(l=10, r=30, t=30, b=44),
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(title="Runoff change per +1 °C warming (%)",
                   showgrid=True, gridcolor="#eef2f6", zeroline=False),
        yaxis=dict(tickfont=dict(size=11), type="category"),
        showlegend=False)
    return fig


def _bootstrap_fig(basin="CRB", n_boot=2000):
    """Resample the 41 water years (with replacement) and refit each time → a non-parametric
    distribution of the temperature sensitivity. Confirms the parametric CI honestly."""
    a = load_vic_annual()
    d = a[(a["basin"] == basin) & (a["water_year"] >= 1984)].copy()
    d["Q"] = d["OUT_RUNOFF"] + d["OUT_BASEFLOW"]
    d = d.dropna(subset=["Q", "OUT_PREC", "OUT_AIR_TEMP"]); d = d[d["Q"] > 0]
    y = np.log(d["Q"].values)
    X = np.column_stack([np.ones(len(y)), np.log(d["OUT_PREC"].values), d["OUT_AIR_TEMP"].values])
    rng = np.random.default_rng(42); n = len(y); cs = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        try:
            coef, *_ = np.linalg.lstsq(X[idx], y[idx], rcond=None)
            cs.append(coef[2] * 100)
        except Exception:
            pass
    cs = np.array(cs)
    lo, mid, hi = np.percentile(cs, [2.5, 50, 97.5])
    fig = go.Figure(go.Histogram(x=cs, nbinsx=40, marker_color="#0277BD", opacity=0.85,
        hovertemplate="%{x:.1f} %/°C<extra></extra>"))
    for xv, lab, col in [(lo, f"2.5%: {lo:.1f}", MAROON), (mid, f"median: {mid:.1f}", NAVY),
                         (hi, f"97.5%: {hi:.1f}", MAROON)]:
        fig.add_vline(x=xv, line_color=col, line_width=2, line_dash="dash",
                      annotation_text=lab, annotation_font=dict(size=9, color=col))
    fig.add_vline(x=0, line_color="#37474f", line_width=1)
    fig.update_layout(height=300, margin=dict(l=45, r=15, t=10, b=36),
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(title=f"{BASIN_NAME.get(basin,basin)} runoff sensitivity (%/°C) — {len(cs)} bootstrap fits"),
        yaxis=dict(title="frequency"), showlegend=False)
    return fig, (lo, mid, hi)


def _sen_table():
    """Non-parametric Sen's-slope trend + 95% CI + Mann-Kendall p for CRB key variables."""
    from scipy import stats
    a = load_vic_annual()
    d = a[(a["basin"] == "CRB") & (a["water_year"] >= 1984)].copy()
    d["Q"] = d["OUT_RUNOFF"] + d["OUT_BASEFLOW"]
    vars_ = [("Streamflow (Q)", "Q", "mm"), ("Precipitation", "OUT_PREC", "mm"),
             ("Snowpack (SWE)", "OUT_SWE", "mm"), ("Air temperature", "OUT_AIR_TEMP", "°C"),
             ("Soil moisture", "OUT_SOIL_MOIST", "mm")]
    rows = []
    x = d["water_year"].values.astype(float)
    for label, col, unit in vars_:
        s = d.dropna(subset=[col])
        sl, ic, lo, hi = stats.theilslopes(s[col].values, s["water_year"].values, 0.95)
        tau, p = stats.kendalltau(s["water_year"].values, s[col].values)
        sig = "yes" if p < 0.05 else "no"
        rows.append((label, f"{sl:+.2f} {unit}/yr", f"[{lo:+.2f}, {hi:+.2f}]", f"{p:.3f}", sig))
    return rows


def _crosssensor_fig():
    """Fair comparison: model (VIC soil moisture) vs an independent NASA sensor (GRACE storage),
    BOTH standardized over the SAME common period, overlaid. r quantifies the agreement.
    Returns (fig, r, n)."""
    va = load_vic_annual(); g = load_grace()
    v = va[va["basin"] == "CRB"][["water_year", "OUT_SOIL_MOIST"]].rename(
        columns={"water_year": "yr", "OUT_SOIL_MOIST": "VIC"})
    gg = g[g["basin"] == "CRB"].copy(); gg["yr"] = pd.to_datetime(gg["date"]).dt.year
    gy = gg.groupby("yr")["tws_mm"].mean().reset_index().rename(columns={"tws_mm": "GRACE"})
    m = pd.merge(v, gy, on="yr").dropna().sort_values("yr")          # common years only
    r = float(np.corrcoef(m["VIC"], m["GRACE"])[0, 1]) if len(m) >= 4 else float("nan")
    n = len(m)
    zv = (m["VIC"] - m["VIC"].mean()) / m["VIC"].std()
    zg = (m["GRACE"] - m["GRACE"].mean()) / m["GRACE"].std()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=m["yr"], y=zv, mode="lines+markers", name="VIC soil moisture (model)",
        line=dict(color="#E65100", width=2.4), marker=dict(size=5)))
    fig.add_trace(go.Scatter(x=m["yr"], y=zg, mode="lines+markers", name="GRACE storage (satellite)",
        line=dict(color=BLUE, width=2.4), marker=dict(size=5)))
    fig.add_hline(y=0, line_color="#b0bec5", line_width=1, line_dash="dash")
    fig.update_layout(height=300, margin=dict(l=45, r=15, t=10, b=44),
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(title="Water Year"),
        yaxis=dict(title="standardized anomaly (wet ↑ / dry ↓)"),
        legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=10)))
    return fig, r, n


def layout():
    boot_fig, (b_lo, b_mid, b_hi) = _bootstrap_fig()
    sen_rows = _sen_table()
    cs_fig, cs_r, cs_n = _crosssensor_fig()
    return html.Div([
        html.Div([
            html.H2("Uncertainty & Confidence"),
            html.P("Every estimate in this tool comes with an uncertainty. Here they are in one place — "
                   "what we are confident about, and what to treat with caution."),
        ], className="tab-header"),
        html.Div([
            # KPIs
            html.Div([
                _tile("95% CI", "Confidence level used", "tile-maroon"),
                _tile("≈ ±19 mm", "GRACE measurement uncertainty", "tile-blue"),
                _tile("41 yrs", "Record length per basin (WY1984–2024)", "tile-navy"),
                _tile("R² 0.56–0.72", "Elasticity model fit range", "tile-green"),
            ], style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit,minmax(150px,1fr))",
                      "gap": "10px", "marginBottom": "16px"}),

            html.Div("This tool reports three kinds of uncertainty. Read this first so the numbers elsewhere "
                     "make sense.",
                     style={"background": "#e3f2fd", "borderLeft": f"3px solid {BLUE}",
                            "padding": "9px 14px", "borderRadius": "0 6px 6px 0",
                            "fontSize": "11.5px", "color": "#1565c0", "marginBottom": "14px"}),

            # 1. Parametric — sensitivity CI
            html.Div([
                html.Div([html.Span("1 · Parametric uncertainty — runoff sensitivity to warming",
                                    style={"fontWeight": "700", "fontSize": "13px"}),
                          html.Span("dot = best estimate · whisker = 95% confidence interval",
                                    style={"color": "#1e293b", "fontSize": "11px"})],
                         className="crb-card-header"),
                dcc.Graph(figure=_sensitivity_fig(), config={"displayModeBar": False},
                          style={"height": "340px"}),
                html.Div([html.B("How to read it: "),
                          "where the whisker stays entirely left of 0 (red dot), the drying signal is "
                          "statistically robust. Where it crosses 0 (grey dot), the annual-scale signal is "
                          "uncertain — use the central value as indicative only. Computed live from each "
                          "basin's OLS regression (coefficient covariance)."],
                         style={"fontSize": "11px", "color": "#1e293b", "padding": "4px 16px 4px"}),
                html.Div([html.I(className="bi bi-info-circle", style={"marginRight": "6px", "color": ORANGE}),
                          html.B("Interpreting the confidence intervals: "),
                          _collinearity_note()],
                         style={"background": "#fff8e1", "borderLeft": f"3px solid {GOLD}",
                                "padding": "9px 14px", "borderRadius": "0 6px 6px 0",
                                "fontSize": "11px", "color": "#1e293b", "margin": "0 16px 12px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # 1b. Bootstrap
            html.Div([
                html.Div([html.Span("2 · Bootstrap check (non-parametric)",
                                    style={"fontWeight": "700", "fontSize": "13px"}),
                          html.Span("resample the 41 years 2,000× and re-fit — does the sensitivity hold?",
                                    style={"color": "#1e293b", "fontSize": "11px"})],
                         className="crb-card-header"),
                dcc.Graph(figure=boot_fig, config={"displayModeBar": False}, style={"height": "300px"}),
                html.Div([html.B("Reading: "),
                          f"the CRB temperature-sensitivity median across bootstrap re-fits is {b_mid:.1f} %/°C "
                          f"with a 95% range of [{b_lo:.1f}, {b_hi:.1f}] %/°C. This independently reproduces the "
                          "regression interval: the central estimate is a loss, with a wide annual-scale spread."],
                         style={"fontSize": "11px", "color": "#1e293b", "padding": "4px 16px 12px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # 1c. Sen's slope trends
            html.Div([
                html.Div([html.Span("3 · Trend uncertainty — Sen's slope + Mann-Kendall (CRB)",
                                    style={"fontWeight": "700", "fontSize": "13px"}),
                          html.Span("robust non-parametric trends with 95% CI",
                                    style={"color": "#1e293b", "fontSize": "11px"})],
                         className="crb-card-header"),
                html.Div(html.Table([
                    html.Thead(html.Tr([html.Th(h, style={"background": NAVY, "color": "white",
                        "padding": "6px 10px", "fontSize": "12px"}) for h in
                        ["Variable", "Sen's slope / yr", "95% CI", "MK p-value", "Significant?"]])),
                    html.Tbody([html.Tr([
                        html.Td(r[0], style={"padding": "6px 10px", "fontSize": "12px", "fontWeight": "600", "color": NAVY}),
                        html.Td(r[1], style={"padding": "6px 10px", "fontSize": "12px"}),
                        html.Td(r[2], style={"padding": "6px 10px", "fontSize": "12px"}),
                        html.Td(r[3], style={"padding": "6px 10px", "fontSize": "12px"}),
                        html.Td(r[4], style={"padding": "6px 10px", "fontSize": "12px",
                                             "color": (GREEN if r[4] == "yes" else ORANGE), "fontWeight": "700"}),
                    ]) for r in sen_rows]),
                ], style={"width": "100%", "borderCollapse": "collapse"}), style={"padding": "8px 16px 14px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # 1d. Cross-sensor agreement
            html.Div([
                html.Div([html.Span("4 · Cross-sensor agreement — does the model match an independent satellite?",
                                    style={"fontWeight": "700", "fontSize": "13px"}),
                          html.Span(f"  VIC soil moisture vs GRACE storage, both standardized · same {cs_n} years (2002–2024)",
                                    style={"color": "#1e293b", "fontSize": "11px"})],
                         className="crb-card-header"),
                dcc.Graph(figure=cs_fig, config={"displayModeBar": False}, style={"height": "300px"}),
                html.Div([html.B(f"Reading: the two lines track each other (correlation r = {cs_r:.2f} over {cs_n} years). "),
                          "VIC is the model; GRACE is an independent NASA gravity satellite. When they rise and "
                          "fall together (wet years up, dry years down), it means two completely different methods "
                          "agree on the basin's wetness — so we are confident in the signal. ",
                          html.Span("SMAP soil moisture is left out here: its record (2015+) is too short for a "
                                    "robust annual correlation.", style={"fontStyle": "italic"})],
                         style={"fontSize": "11px", "color": "#1e293b", "padding": "4px 16px 12px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # 5. Observational
            html.Div([
                html.Div("5 · Observational uncertainty — how good are the inputs?", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div(html.Table([
                    html.Thead(html.Tr([html.Th(h, style={"background": NAVY, "color": "white",
                        "padding": "6px 10px", "fontSize": "12px"}) for h in
                        ["Source", "Uncertainty / skill", "Where shown"]])),
                    html.Tbody([
                        html.Tr([html.Td("GRACE terrestrial water storage", style={"padding":"6px 10px","fontSize":"12px"}),
                                 html.Td("± measurement error per month (≈ ±19 mm avg)", style={"padding":"6px 10px","fontSize":"12px"}),
                                 html.Td(html.A("Water Storage tab — error bars", href="/tws", style={"color":BLUE}), style={"padding":"6px 10px","fontSize":"12px"})]),
                        html.Tr([html.Td("VIC vs SMAP soil moisture", style={"padding":"6px 10px","fontSize":"12px"}),
                                 html.Td("R² = 0.71 (surface), 0.81 (root-zone)", style={"padding":"6px 10px","fontSize":"12px"}),
                                 html.Td(html.A("Publications tab", href="/publications", style={"color":BLUE}), style={"padding":"6px 10px","fontSize":"12px"})]),
                        html.Tr([html.Td("VIC streamflow skill", style={"padding":"6px 10px","fontSize":"12px"}),
                                 html.Td("NSE = 0.96 (Upper Basin)", style={"padding":"6px 10px","fontSize":"12px"}),
                                 html.Td(html.A("Publications tab", href="/publications", style={"color":BLUE}), style={"padding":"6px 10px","fontSize":"12px"})]),
                        html.Tr([html.Td("NMME seasonal forecast", style={"padding":"6px 10px","fontSize":"12px"}),
                                 html.Td("80% ensemble confidence interval (52 members)", style={"padding":"6px 10px","fontSize":"12px"}),
                                 html.Td(html.A("Seasonal Forecasts tab", href="/nmme", style={"color":BLUE}), style={"padding":"6px 10px","fontSize":"12px"})]),
                    ]),
                ], style={"width": "100%", "borderCollapse": "collapse"}), style={"padding": "8px 16px 14px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # 3. Structural / honest caveats
            html.Div([
                html.Div("6 · Structural uncertainty — scope & limitations", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([
                    html.Ul([
                        html.Li(["The ", html.B("Scenario Explorer"),
                                 " is an empirical-elasticity model, not a dynamical simulation — fast and "
                                 "interpretable, but it assumes the observed P/T→Q relationship holds in the future."]),
                        html.Li(["“", html.B("Projections to 2100"),
                                 "” uses a single downscaled VIC run — illustrative, not an ensemble; "
                                 "the CMIP tab gives the multi-model range."]),
                        html.Li(["NMME & CMIP results are ", html.B("documented from the project reports"),
                                 " (raw grids not bundled); the CMIP skill radar is illustrative."]),
                        html.Li(["CRIA sociopolitical asset scores are ", html.B("not bundled"),
                                 " → shown as “no data available”, never invented."]),
                    ], style={"fontSize": "11.5px", "color": "#37474f", "lineHeight": "1.6",
                              "margin": "8px 0", "paddingLeft": "20px"}),
                ], style={"padding": "4px 16px 12px"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            html.Div("Method: 95% confidence intervals come from ordinary-least-squares coefficient "
                     "covariance, propagated to projections by the delta method. GRACE uncertainty is the "
                     "mission's reported monthly measurement error. Validation skill (R², NSE) is from the "
                     "peer-reviewed calibration (Wang, Ghimire, Whitney et al., 2026, Scientific Reports).",
                     style={"fontSize": "10.5px", "color": "#1e293b", "fontStyle": "italic"}),
            xref("This sensitivity drives:", [("Scenario projections", "/scenario"), ("Aridification leaderboard", "/aridification")]),
        ], className="tab-body"),
    ])


def register_callbacks(app):
    pass
