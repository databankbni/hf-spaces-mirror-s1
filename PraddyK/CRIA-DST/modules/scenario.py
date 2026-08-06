"""
modules/scenario.py — Climate-Sensitivity Scenario Explorer (the decision-support core)

A true "what-if" scenario engine, grounded entirely in REAL observed data:
we fit the classic hydrologic-elasticity model to each basin's WY1984–2024 record,

        ln(Q) = a + b·ln(P) + c·T

where Q = runoff + baseflow (mm/yr), P = precipitation (mm/yr), T = air temp (°C).
 b = precipitation elasticity of runoff,  c = temperature sensitivity (per °C).
The user then dials a precipitation change ΔP (%) and a warming ΔT (°C); the tool
applies the empirically-fitted sensitivities to project the change in streamflow:

        Q_future / Q_base = exp( b·ln(1+ΔP/100) + c·ΔT )

This is an EMPIRICAL sensitivity scenario (not a dynamical GCM run). Every coefficient
is computed live from the real VIC record and shown to the user alongside each result.
The CRB temperature sensitivity (≈ −8%/°C) matches the project's published value and the
peer-reviewed consensus (Udall & Overpeck 2017; Milly & Dunne 2020; Vano et al. 2014).
"""
import functools
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual
from utils.components import xref, pub_evidence, pub_star, pub_author, info_dot, howto
from utils.charts import lollipop_h

MAROON="#8C1D40"; NAVY="#0D2137"; BLUE="#01579B"; GREEN="#2E7D32"
ORANGE="#E65100"; PURPLE="#4527A0"; GREY="#94a3b8"; GOLD="#FFC627"

# Basin areas (km²) → for depth(mm) → volume(MAF) translation for managers
AREA_KM2 = {"CRB": 654441, "UpperBasin": 293377, "LowerBasin": 361064, "Green": 110702,
            "SanJuan": 60870, "UpperColo": 64735, "GlenCanyon": 57070, "Gila": 161990,
            "GrandCanyon": 85133, "LittleColo": 69561, "LowerColo": 44379}

def _to_maf(depth_mm, basin):
    """Convert a basin-mean depth (mm) to basin-integrated volume in million acre-feet (MAF).
    1 acre-foot = 1233.48 m³;  volume(m³) = depth_mm/1000 × area_km² × 1e6."""
    area = AREA_KM2.get(basin)
    if not area or depth_mm != depth_mm:
        return float("nan")
    return depth_mm * area / 1.23348e6

BASIN_OPTIONS = [{"label": n, "value": b} for b, n in [
    ("CRB", "Colorado River Basin"), ("UpperBasin", "Upper Basin"),
    ("LowerBasin", "Lower Basin"), ("Green", "Green River"),
    ("SanJuan", "San Juan"), ("GrandCanyon", "Grand Canyon"), ("Gila", "Gila River")]]
BASIN_NAME = {o["value"]: o["label"] for o in BASIN_OPTIONS}
ALL_BASINS = [o["value"] for o in BASIN_OPTIONS]

# Plausibility reference scenarios (from the literature / project reports)
PRESETS = [
    {"label": "Today (no change)",        "dt": 0.0, "dp": 0},
    {"label": "Mid-century (+2°C, −5%P)", "dt": 2.0, "dp": -5},
    {"label": "Late-century (+4°C, −10%P)","dt": 4.0, "dp": -10},
]


@functools.lru_cache(maxsize=None)
def _fit(basin):
    """Fit ln(Q)=a+b ln(P)+c T on WY1984–2024 with OLS uncertainty.
    Returns (a,b,c,R2,Qbase,Pbase,Tbase,df, cov, n)."""
    a = load_vic_annual()
    if a.empty:
        return None
    d = a[(a["basin"] == basin) & (a["water_year"] >= 1984)].copy()
    if d.empty:
        return None
    d["Q"] = d["OUT_RUNOFF"] + d["OUT_BASEFLOW"]
    d = d.dropna(subset=["Q", "OUT_PREC", "OUT_AIR_TEMP"])
    d = d[d["Q"] > 0]
    if len(d) < 8:
        return None
    y = np.log(d["Q"].values); n = len(y)
    X = np.column_stack([np.ones(n), np.log(d["OUT_PREC"].values), d["OUT_AIR_TEMP"].values])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    r2 = 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))
    dof = max(1, n - 3)
    s2 = (resid @ resid) / dof
    cov = s2 * np.linalg.inv(X.T @ X)          # coefficient covariance matrix
    return (coef[0], coef[1], coef[2], r2,
            d["Q"].mean(), d["OUT_PREC"].mean(), d["OUT_AIR_TEMP"].mean(),
            d[["water_year", "Q"]].reset_index(drop=True), cov, n)


def _project(basin, dt, dp):
    """Projected change for ΔT(°C), ΔP(%), with 95% confidence interval (delta method)."""
    from scipy import stats
    f = _fit(basin)
    if f is None:
        return None
    a, b, c, r2, qbase, pbase, tbase, df, cov, n = f
    g = np.log(1 + dp / 100.0)                  # ln precip multiplier
    lin = b * g + c * dt                        # ln(Q_future/Q_base)
    factor = np.exp(lin)
    # variance of the linear predictor (uses b,c variances + their covariance)
    var = (g ** 2) * cov[1, 1] + (dt ** 2) * cov[2, 2] + 2 * g * dt * cov[1, 2]
    se = float(np.sqrt(max(var, 0)))
    tcrit = stats.t.ppf(0.975, max(1, n - 3))
    lo_f = np.exp(lin - tcrit * se); hi_f = np.exp(lin + tcrit * se)
    seb = float(np.sqrt(cov[1, 1])); sec = float(np.sqrt(cov[2, 2]))
    pct = (factor - 1) * 100
    # manager status (illustrative CRIA Normal/Caution/Critical band, by runoff loss)
    if pct >= -10:   status, scolor, stile = "Normal", "#2E7D32", "tile-green"
    elif pct > -25:  status, scolor, stile = "Caution", "#E65100", "tile-gold"
    else:            status, scolor, stile = "Critical", "#B71C1C", "tile-maroon"
    return {"b": b, "c": c, "r2": r2, "qbase": qbase, "pbase": pbase, "tbase": tbase,
            "factor": factor, "pct": pct, "qnew": qbase * factor,
            "pct_lo": (lo_f - 1) * 100, "pct_hi": (hi_f - 1) * 100,
            "qnew_lo": qbase * lo_f, "qnew_hi": qbase * hi_f,
            "qbase_maf": _to_maf(qbase, basin), "qnew_maf": _to_maf(qbase * factor, basin),
            "maf_lost": _to_maf(qbase, basin) - _to_maf(qbase * factor, basin),
            "status": status, "scolor": scolor, "stile": stile,
            "t_only": (np.exp(c * dt) - 1) * 100, "p_only": (np.exp(b * g) - 1) * 100,
            "c_lo": (c - tcrit * sec) * 100, "c_hi": (c + tcrit * sec) * 100,
            "b_lo": b - tcrit * seb, "b_hi": b + tcrit * seb,
            "df": df, "n": n}


@functools.lru_cache(maxsize=None)
def _precip_record(basin):
    """What the observed record has ACTUALLY delivered: precipitation as % of the
       1983–2010 baseline — wettest single year, wettest 10-year mean, recent decade."""
    a = load_vic_annual()
    if a.empty:
        return None
    d = a[a["basin"] == basin].dropna(subset=["OUT_PREC"]).sort_values("water_year")
    if len(d) < 15:
        return None
    base = d[(d.water_year >= 1983) & (d.water_year <= 2010)]["OUT_PREC"].mean()
    if not base:
        return None
    pct = (d["OUT_PREC"] - base) / base * 100.0
    roll = pct.rolling(10).mean()
    return {"best_year": float(pct.max()),
            "best_year_wy": int(d.loc[pct.idxmax(), "water_year"]),
            "best_decade": float(roll.max()),
            "recent": float(pct[d["water_year"] >= 2015].mean())}


def _required_dp(basin, dt, target_pct=0.0):
    """INVERSE scenario — solve the SAME fitted elasticity for precipitation instead
       of runoff: how much precipitation change (%) is required to reach a target
       change in water yield under dt °C of warming.
          ln(1+target/100) = b·ln(1+dP/100) + c·dt   →   dP"""
    f = _fit(basin)
    if f is None:
        return float("nan")
    b, c = f[1], f[2]
    if abs(b) < 1e-6:
        return float("nan")
    g = (np.log(1 + target_pct / 100.0) - c * dt) / b
    return float((np.exp(g) - 1) * 100.0)


def _required_fig(basin):
    """Required-precipitation curve vs warming, against what the record has delivered."""
    rec = _precip_record(basin)
    dts = np.arange(0, 4.01, 0.1)
    need = np.array([_required_dp(basin, float(t)) for t in dts])
    fig = go.Figure()
    if rec and need.size:
        top = max(float(np.nanmax(need)), rec["best_year"]) * 1.12
        fig.add_hrect(y0=rec["best_decade"], y1=top, fillcolor="rgba(183,28,28,0.06)",
                      line_width=0, layer="below")
    fig.add_trace(go.Scatter(
        x=dts, y=need, mode="lines", line=dict(color=MAROON, width=3.2),
        hovertemplate="+%{x:.1f} °C warming<br>needs %{y:+.1f}% precipitation<extra></extra>",
        name="Precipitation required"))
    if rec:
        fig.add_hline(y=rec["best_decade"], line=dict(color="#01579B", width=2, dash="dash"),
                      annotation_text=f"Wettest decade ever recorded  {rec['best_decade']:+.1f}%",
                      annotation_position="top left", annotation_font_size=11)
        fig.add_hline(y=rec["recent"], line=dict(color="#78909c", width=1.6, dash="dot"),
                      annotation_text=f"Recent decade  {rec['recent']:+.1f}%",
                      annotation_position="bottom left", annotation_font_size=11)
    fig.update_layout(height=330, margin=dict(l=62, r=18, t=14, b=50),
                      paper_bgcolor="white", plot_bgcolor="white", showlegend=False,
                      xaxis=dict(title="Warming (°C)", showgrid=False),
                      yaxis=dict(title="Precipitation change required (%)",
                                 gridcolor="rgba(13,33,55,0.07)", zeroline=True))
    return fig


def _tile(v, l, c):
    return html.Div([html.Div(v, className="info-tile-value"),
        html.Div(l, className="info-tile-label")], className=f"info-tile {c}")


def _empty(msg):
    fig = go.Figure(); fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font=dict(size=12, color="#90a4ae"))
    fig.update_layout(paper_bgcolor="white", plot_bgcolor="white",
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=10, b=10), height=320)
    return fig


def layout():
    from modules.home import _scenario_mini  # the animated warming dial (relocated from the Overview)
    return html.Div([
        html.Div([
            html.H2("Climate-Sensitivity Scenario Explorer"),
            html.P("Dial a warming and a precipitation change — see the projected streamflow "
                   "response, computed from each basin's own observed climate sensitivity (WY1984–2024)."),
        ], className="tab-header"),
        # ── The at-a-glance warming dial (moved here from the Overview) ──
        html.Div(_scenario_mini(), className="tab-body", style={"paddingBottom": "0"}),
        html.Div([
            dbc.Row(id="sc-tiles", className="mb-3 g-2"),

            html.Div(id="sc-finding",
                     style={"background": "#e3f2fd", "borderLeft": f"3px solid {BLUE}",
                            "padding": "10px 14px", "borderRadius": "0 6px 6px 0",
                            "fontSize": "11.5px", "color": "#1565c0", "marginBottom": "12px"}),
                            pub_author("Milly & Dunne 2020", "https://www.science.org/doi/10.1126/science.aay9187", "Milly & Dunne 2020, Science (≈ -9.3%/°C)", "published"),

            # ── Controls ──
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("BASIN", className="control-label"),
                        dcc.Dropdown(id="sc-basin", options=BASIN_OPTIONS, value="CRB",
                                     clearable=False, style={"fontSize": "12.5px"}),
                    ], xs=12, md=3),
                    dbc.Col([
                        html.Div("WARMING  ΔT (°C)", className="control-label"),
                        dcc.Slider(id="sc-dt", min=0, max=5, step=0.5, value=2.0,
                                   marks={i: f"+{i}°" for i in range(0, 6)},
                                   tooltip={"placement": "bottom", "always_visible": True}),
                    ], xs=12, md=5),
                    dbc.Col([
                        html.Div("PRECIPITATION  ΔP (%)", className="control-label"),
                        dcc.Slider(id="sc-dp", min=-30, max=30, step=5, value=-5,
                                   marks={i: f"{i:+d}%" for i in range(-30, 31, 15)},
                                   tooltip={"placement": "bottom", "always_visible": True}),
                    ], xs=12, md=4),
                ]),
                html.Div([
                    html.Span("Quick scenarios: ", style={"fontSize": "11px", "fontWeight": "600",
                                                          "color": "#1e293b", "marginRight": "6px"}),
                    *[html.Button(p["label"], id={"type": "sc-preset", "i": i}, n_clicks=0,
                                  className="sc-preset-btn") for i, p in enumerate(PRESETS)],
                ], style={"marginTop": "10px"}),
            ], className="control-panel"),

            html.Div([
                html.I(className="bi bi-info-circle", style={"marginRight": "7px", "color": BLUE}),
                html.B("How to use:  "),
                "drag the warming (ΔT) and precipitation (ΔP) sliders — or tap a quick scenario — "
                "to see the projected streamflow response, what drives it, and how every basin compares.  ",
                html.A("Methods & data →", href="/methods",
                       style={"color": BLUE, "fontWeight": "600", "textDecoration": "underline"}),
            ], className="howto-strip"),

            # ── Main row: projection chart + tornado ──
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div([html.Span("Projected mean streamflow", style={"fontWeight": "700", "fontSize": "13px"}),
                        html.Span("observed record · scenario mean (dotted) · shaded = 95% confidence band",
                                  style={"color": "#1e293b", "fontSize": "11px"}),
                        info_dot("The dotted line is the projected mean streamflow for your chosen warming/drying "
                                 "scenario. The shaded band is the 95% confidence interval — the range the true "
                                 "response is likely to fall in. A wide band means more uncertainty (here, partly "
                                 "because precipitation and temperature are correlated in the record)."),
                        pub_star("https://www.science.org/doi/10.1126/science.aay9187", "Milly & Dunne 2020, Science 367:1252", "Published")], className="crb-card-header"),
                    dcc.Loading(dcc.Graph(id="sc-ts", config={"displayModeBar": False},
                                          style={"height": "360px"}), color=MAROON),
                ], className="crb-card"), md=7),
                dbc.Col(html.Div([
                    html.Div([html.Span("What drives the change?", style={"fontWeight": "700", "fontSize": "13px"}),
                        html.Span("warming vs precipitation", style={"color": "#1e293b", "fontSize": "11px"})],
                        className="crb-card-header"),
                    dcc.Loading(dcc.Graph(id="sc-tornado", config={"displayModeBar": False},
                                          style={"height": "360px"}), color=MAROON),
                ], className="crb-card"), md=5),
            ], className="g-3 mb-2"),

            # ── All-basin comparison at the chosen scenario ──
            html.Div([
                html.Div([html.Span("Same scenario across all basins", style={"fontWeight": "700", "fontSize": "13px"}),
                    html.Span("projected streamflow change (%)", style={"color": "#1e293b", "fontSize": "11px"})],
                    className="crb-card-header"),
                dcc.Loading(dcc.Graph(id="sc-allbasin", config={"displayModeBar": False},
                                      style={"height": "300px"}), color=MAROON),
            ], className="crb-card mb-2"),


            # ── INVERSE scenario: what would it take? ──
            html.Div([
                html.Div([
                    html.Span("What would it take?", style={"fontWeight": "700", "fontSize": "13px"}),
                    html.Span("the question managers actually ask — the same fitted elasticity, inverted",
                              style={"color": "#546e7a", "fontSize": "11px"}),
                ], className="crb-card-header"),
                howto("Every scenario tool answers 'what happens if'. This answers the reverse: how much "
                      "MORE precipitation the basin would need just to hold today's water supply as it "
                      "warms — and whether the observed record has ever delivered that much."),
                dbc.Row(id="sc-req-tiles", className="mb-2 g-2"),
                dcc.Loading(dcc.Graph(id="sc-required", config={"displayModeBar": False},
                                      style={"height": "330px"})),
                html.Div(id="sc-req-note",
                         style={"fontSize": "12px", "color": "#0D2137", "fontWeight": "700",
                                "background": "#faf5f2", "borderLeft": f"3px solid {MAROON}",
                                "padding": "10px 14px", "borderRadius": "0 6px 6px 0",
                                "marginTop": "10px", "lineHeight": "1.55"}),
                html.Div("Inverse of the same empirical elasticity (ln Q = a + b·ln P + c·T) fitted to this "
                         "basin's own WY1984–2024 record — not a dynamical climate model. It assumes the "
                         "historical precipitation–temperature–runoff relationship continues to hold. The "
                         "shaded band marks precipitation levels the observed record has never sustained.",
                         style={"fontSize": "10.5px", "color": "#546e7a", "marginTop": "8px",
                                "lineHeight": "1.5"}),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # ── Methods ──
            html.Div([
                html.Div("How this scenario is computed", style={"fontWeight": "700", "fontSize": "12px",
                                                                 "color": MAROON, "marginBottom": "4px"}),
                html.Div(id="sc-method", style={"fontSize": "11px", "color": "#37474f", "lineHeight": "1.6"}),
                html.Div("Empirical elasticity scenario — Q response is derived from each basin's own "
                         "observed WY1984–2024 sensitivity (ln Q = a + b·ln P + c·T), not a dynamical GCM "
                         "simulation. The CRB temperature sensitivity (≈ −8%/°C) matches the project's "
                         "published value and the peer-reviewed consensus (Udall & Overpeck 2017; "
                         "Milly & Dunne 2020; Vano et al. 2014).",
                         style={"fontSize": "10.5px", "color": "#1e293b", "marginTop": "6px"}),
            ], className="crb-card"),
            xref("Related analyses:", [("Per-basin warming leaderboard → Aridification", "/aridification"), ("Confidence bounds → Uncertainty", "/uncertainty")]),
        ], className="tab-body"),
    ])


def register_callbacks(app):

    # ── INVERSE scenario: precipitation required to hold today's supply ──
    @app.callback(
        Output("sc-req-tiles", "children"), Output("sc-required", "figure"),
        Output("sc-req-note", "children"),
        Input("sc-basin", "value"),
    )
    def _inverse(basin):
        basin = basin or "CRB"
        rec = _precip_record(basin)
        n1, n2, n3 = (_required_dp(basin, t) for t in (1.0, 2.0, 3.0))
        tiles = [
            dbc.Col(_tile(f"{n1:+.1f}%", "precipitation needed at +1 °C", "tile-blue"), xs=6, md=4),
            dbc.Col(_tile(f"{n2:+.1f}%", "precipitation needed at +2 °C", "tile-gold"), xs=6, md=4),
            dbc.Col(_tile(f"{n3:+.1f}%", "precipitation needed at +3 °C", "tile-maroon"), xs=12, md=4),
        ]
        # honest 95% CI on the required precipitation (delta method on b and c)
        ci = ""
        f = _fit(basin)
        if f is not None and n2 == n2:
            from scipy import stats as _st
            b, c, cov, nobs = f[1], f[2], f[8], f[9]
            g = -c * 2.0 / b
            dgdb = c * 2.0 / b ** 2; dgdc = -2.0 / b
            var = dgdb ** 2 * cov[1, 1] + dgdc ** 2 * cov[2, 2] + 2 * dgdb * dgdc * cov[1, 2]
            se = float(np.sqrt(max(var, 0.0)))
            tcrit = _st.t.ppf(0.975, max(1, nobs - 3))
            lo = (np.exp(g - tcrit * se) - 1) * 100
            hi = (np.exp(g + tcrit * se) - 1) * 100
            sec = float(np.sqrt(cov[2, 2]))
            tc = c / sec if sec else float("nan")
            pc = 2 * (1 - _st.t.cdf(abs(tc), max(1, nobs - 3))) if tc == tc else float("nan")
            ci = (f" (95% CI {lo:+.1f}% to {hi:+.1f}%; the temperature term in this basin's fit is "
                  f"{'statistically significant' if pc < 0.05 else 'NOT statistically significant'}, "
                  f"p = {pc:.2f})")
        if rec and n2 == n2:
            gap = n2 - rec["best_decade"]
            note = [
                f"Central estimate: at +2 °C, {BASIN_NAME.get(basin, basin)} would need ",
                html.B(f"{n2:+.1f}% precipitation"),
                " to hold today's water supply", html.Span(ci, style={"fontWeight": "400"}),
                ". For scale, the wettest decade in the WY1984–2024 record delivered ",
                html.B(f"{rec['best_decade']:+.1f}%"),
                f" and the recent decade has run {rec['recent']:+.1f}%. Treat the central value as "
                "indicative only — the confidence range is wide, so this is an exploratory framing, "
                "not a prediction.",
            ]
        else:
            note = "No data available for this basin."
        return tiles, _required_fig(basin), note

    # preset buttons → set sliders
    from dash import ALL, ctx
    @app.callback(
        Output("sc-dt", "value"), Output("sc-dp", "value"),
        Input({"type": "sc-preset", "i": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def _apply_preset(_clicks):
        if not ctx.triggered_id:
            from dash.exceptions import PreventUpdate
            raise PreventUpdate
        i = ctx.triggered_id["i"]
        return PRESETS[i]["dt"], PRESETS[i]["dp"]

    @app.callback(
        Output("sc-tiles", "children"),
        Output("sc-ts", "figure"), Output("sc-tornado", "figure"),
        Output("sc-allbasin", "figure"),
        Output("sc-finding", "children"), Output("sc-method", "children"),
        Input("sc-basin", "value"), Input("sc-dt", "value"), Input("sc-dp", "value"),
    )
    def _update(basin, dt, dp):
        dt = dt or 0.0; dp = dp or 0
        r = _project(basin, dt, dp)
        if r is None:
            e = _empty("Run preprocessing to populate VIC basin data.")
            return ([], e, e, e, "No data.", "")
        name = BASIN_NAME.get(basin, basin)

        # Tiles — manager-first: status + % + volume in MAF
        pct = r["pct"]
        tiles = [
            _tile(r["status"], "Supply status (illustrative)", r["stile"]),
            _tile(f"{pct:+.1f}%", f"Projected Δ streamflow · 95% CI [{r['pct_lo']:+.0f}, {r['pct_hi']:+.0f}]%",
                  "tile-maroon" if pct < 0 else "tile-green"),
            _tile(f"{r['qnew_maf']:.1f} MAF", f"Scenario basin runoff (was {r['qbase_maf']:.1f} MAF)", "tile-navy"),
            _tile(f"{r['qnew_maf'] - r['qbase_maf']:+.1f} MAF", "Change in basin runoff volume", "tile-blue"),
        ]
        tiles = [dbc.Col(t, xs=6, md=3) for t in tiles]

        # Time series + scenario 95% confidence band
        df = r["df"]
        yrs = [df["water_year"].min(), df["water_year"].max()]
        ts = go.Figure()
        # CI band (drawn first, behind)
        ts.add_trace(go.Scatter(x=yrs + yrs[::-1],
            y=[r["qnew_hi"], r["qnew_hi"], r["qnew_lo"], r["qnew_lo"]],
            fill="toself", fillcolor="rgba(140,29,64,0.12)", line=dict(width=0),
            name="Scenario 95% CI", hoverinfo="skip"))
        ts.add_trace(go.Scatter(x=df["water_year"], y=df["Q"], mode="lines+markers",
            name="Observed", line=dict(color=NAVY, width=1.8), marker=dict(size=4)))
        ts.add_hline(y=r["qbase"], line_dash="dash", line_color=BLUE,
                     annotation_text=f"baseline {r['qbase']:.0f}", annotation_font=dict(size=10, color=BLUE))
        ts.add_hline(y=r["qnew"], line_dash="dot", line_color=MAROON, line_width=2.5,
                     annotation_text=f"scenario {r['qnew']:.0f}", annotation_font=dict(size=10, color=MAROON))
        ts.update_layout(height=360, margin=dict(l=55, r=15, t=10, b=40),
            paper_bgcolor="white", plot_bgcolor="white",
            xaxis=dict(title="Water Year"), yaxis=dict(title="Streamflow Q (mm/yr)"),
            legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=10)))

        # Tornado: T vs P contribution → lollipop (diverging)
        tor = lollipop_h(["Warming (ΔT)", "Precipitation (ΔP)", "Combined"],
                         [r["t_only"], r["p_only"], r["pct"]],
                         [ORANGE, BLUE, MAROON],
                         x_title="Contribution to Q change (%)", unit="%",
                         height=360, diverging=True)

        # All-basin comparison → lollipop (diverging)
        recs = []
        for b in ALL_BASINS:
            rr = _project(b, dt, dp)
            if rr:
                recs.append((BASIN_NAME[b], rr["pct"]))
        recs.sort(key=lambda x: x[1])
        names = [x[0] for x in recs]; vals = [x[1] for x in recs]
        cols = ["#b71c1c" if v < 0 else "#0d47a1" for v in vals]
        ab = lollipop_h(names, vals, cols, x_title="Δ Streamflow (%)", unit="%",
                        height=300, diverging=True)

        # Finding — manager bottom line first, then the technical detail
        driver = "warming" if abs(r["t_only"]) >= abs(r["p_only"]) else "lower precipitation"
        crosses0 = r["pct_lo"] < 0 < r["pct_hi"]
        sign = "lose" if r["maf_lost"] > 0 else "gain"
        bottom = (f"Under {dt:+.1f} °C and {dp:+d}% precipitation, {name} would {sign} about "
                  f"{abs(r['maf_lost']):.1f} MAF of basin runoff (≈ {abs(pct):.0f}%, {r['qbase_maf']:.1f} → "
                  f"{r['qnew_maf']:.1f} MAF) — an illustrative “{r['status']}” supply condition. "
                  "For scale, the 2022 Tier-1 shortage cut ~0.5 MAF of CAP deliveries.")
        finding = [
            html.Span("Summary   ", style={"fontWeight": "800", "color": r["scolor"]}),
            html.Span(bottom, style={"fontWeight": "600"}), html.Br(), html.Br(),
            html.Strong("Detail   "),
            f"projected {pct:+.1f}% streamflow change (95% CI {r['pct_lo']:+.0f}% to {r['pct_hi']:+.0f}%); "
            f"dominant driver: {driver}. Sensitivity {r['c']*100:+.1f}%/°C "
            f"(CI {r['c_lo']:+.1f} to {r['c_hi']:+.1f}); precipitation elasticity {r['b']:.2f}.",
            html.Br(),
            html.Span(("Confidence: the 95% interval spans zero at the annual scale, so the central "
                       "value should be read as indicative rather than definitive."
                       if crosses0 else
                       "Confidence: the 95% interval excludes zero — the projected direction is robust."),
                      style={"fontWeight": "600", "color": ("#E65100" if crosses0 else "#2E7D32")}),
        ]

        method = [
            f"Fitted on {name}, WY1984–2024 (n={r['n']}):  ",
            html.Span(f"ln Q = {_fit(basin)[0]:.2f} + {r['b']:.2f}·ln P  {r['c']:+.3f}·T",
                      style={"fontFamily": "monospace", "background": "#f1f5f9",
                             "padding": "1px 6px", "borderRadius": "4px"}),
            f"   (R² = {r['r2']:.2f}).  Uncertainty: 95% confidence intervals come from the OLS "
            "coefficient covariance, propagated to the projection by the delta method. "
            "Scenario Q = baseline × exp( b·ln(1+ΔP/100) + c·ΔT ).",
        ]
        return tiles, ts, tor, ab, finding, method
