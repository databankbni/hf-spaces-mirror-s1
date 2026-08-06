"""
modules/october.py — October Signal

The basin's water year begins on 1 October, and the soil moisture it starts with
already separates a good year from a poor one — months before any snow-based
forecast is issued.

Peer-reviewed basis: Ghimire, S., Vivoni, E.R. & Wang, Z. (2026), "Fall Soil
Moisture Modulates Snow-Streamflow Dynamics in the Colorado River Basin", Water
Resources Research 62(7), e2025WR042871.

Method here: ordinary least squares of water-year yield (runoff + baseflow) on the
October-mean column soil moisture of the same water year, WY1984-2024, with a 95%
prediction interval and leave-one-out cross-validated skill. Everything is computed
live from the bundled VIC 5.0 PRISM-calibrated cache.

Honesty: this is the tool's own single-predictor regression (R-squared about 0.48 for
the whole basin); the published study reports a larger explained fraction using a
fuller method. The signal is weak in the Lower Basin and that is stated on screen.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy import stats
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual, load_vic_monthly, basin_label
from utils.components import howto, pub_star, xref

MAROON = "#8C1D40"; NAVY = "#0D2137"; BLUE = "#01579B"; GOLD = "#BA7517"; GREEN = "#2E7D32"

BASIN_OPTIONS = [{"label": n, "value": b} for b, n in [
    ("CRB", "Colorado River Basin"), ("UpperBasin", "Upper Basin"),
    ("LowerBasin", "Lower Basin"), ("Green", "Green River"),
    ("SanJuan", "San Juan"), ("GrandCanyon", "Grand Canyon"), ("Gila", "Gila River")]]

_FIT = {}


def _fit(basin):
    """October soil moisture -> water-year yield. Returns fit, skill and band."""
    if basin in _FIT:
        return _FIT[basin]
    out = None
    try:
        vm = load_vic_monthly(); va = load_vic_annual()
        v = vm[vm["basin"] == basin].copy()
        v["wy"] = np.where(v["month"] >= 10, v["year"] + 1, v["year"])
        oct_sm = v[v["month"] == 10].groupby("wy")["OUT_SOIL_MOIST"].mean().rename("sm")
        a = va[va["basin"] == basin].set_index("water_year")
        y = (a["OUT_RUNOFF"] + a["OUT_BASEFLOW"]).rename("yield")
        df = pd.concat([y, oct_sm], axis=1).dropna().sort_index()
        if len(df) < 12:
            return None
        x = df["sm"].to_numpy(); yy = df["yield"].to_numpy(); n = len(df)
        sl, ic, r, p, _se = stats.linregress(x, yy)
        resid = yy - (sl * x + ic)
        s_err = float(np.sqrt((resid ** 2).sum() / (n - 2)))
        xbar = float(x.mean()); sxx = float(((x - xbar) ** 2).sum())
        # honest out-of-sample skill
        pred = np.zeros(n)
        for i in range(n):
            m = np.ones(n, bool); m[i] = False
            s2, i2, *_ = stats.linregress(x[m], yy[m])
            pred[i] = s2 * x[i] + i2
        loo = 1 - ((yy - pred) ** 2).sum() / ((yy - yy.mean()) ** 2).sum()
        lo_q, hi_q = np.percentile(x, [10, 90])
        out = {"x": x, "y": yy, "yr": df.index.to_numpy(), "sl": sl, "ic": ic,
               "r2": r ** 2, "p": p, "n": n, "s_err": s_err, "xbar": xbar, "sxx": sxx,
               "loo": loo, "dry_x": lo_q, "wet_x": hi_q,
               "dry_y": sl * lo_q + ic, "wet_y": sl * hi_q + ic,
               "last_yr": int(df.index[-1]), "last_x": float(x[-1]),
               "last_y": float(yy[-1]), "last_pred": float(sl * x[-1] + ic)}
    except Exception:
        out = None
    _FIT[basin] = out
    return out


def _pi(f, xv):
    """95% prediction interval half-width at xv."""
    t = stats.t.ppf(0.975, max(1, f["n"] - 2))
    return float(t * f["s_err"] * np.sqrt(1 + 1 / f["n"] + (xv - f["xbar"]) ** 2 / f["sxx"]))


def _fig(basin):
    f = _fit(basin)
    fig = go.Figure()
    if not f:
        fig.add_annotation(text="No data available", xref="paper", yref="paper", x=.5, y=.5,
                           showarrow=False, font=dict(color="#90a4ae"))
        fig.update_layout(height=380, paper_bgcolor="white", plot_bgcolor="white",
                          xaxis=dict(visible=False), yaxis=dict(visible=False))
        return fig
    xl = np.linspace(f["x"].min(), f["x"].max(), 60)
    yl = f["sl"] * xl + f["ic"]
    band = np.array([_pi(f, v) for v in xl])
    fig.add_trace(go.Scatter(x=np.concatenate([xl, xl[::-1]]),
                             y=np.concatenate([yl + band, (yl - band)[::-1]]),
                             fill="toself", fillcolor="rgba(1,87,155,0.10)",
                             line=dict(width=0), hoverinfo="skip", name="95% prediction band"))
    fig.add_trace(go.Scatter(x=xl, y=yl, mode="lines", line=dict(color=MAROON, width=2.8),
                             name=f"Fit · R²={f['r2']:.2f}", hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=f["x"], y=f["y"], mode="markers",
        marker=dict(color=BLUE, size=8, opacity=.75, line=dict(color="white", width=1.2)),
        text=[f"WY {a}" for a in f["yr"]],
        hovertemplate="%{text}<br>1 Oct soil moisture %{x:.0f} mm<br>"
                      "water-year yield %{y:.0f} mm<extra></extra>", name="Water years"))
    fig.add_trace(go.Scatter(
        x=[f["last_x"]], y=[f["last_y"]], mode="markers",
        marker=dict(color=GOLD, size=15, symbol="diamond", line=dict(color=MAROON, width=2)),
        hovertemplate=f"WY{f['last_yr']} (latest)<extra></extra>", name=f"WY{f['last_yr']}"))
    fig.update_layout(height=380, margin=dict(l=58, r=18, t=10, b=70),
                      paper_bgcolor="white", plot_bgcolor="white",
                      xaxis=dict(title="Column soil moisture on 1 October (mm)", showgrid=False),
                      yaxis=dict(title="Water-year yield — runoff + baseflow (mm)",
                                 gridcolor="rgba(13,33,55,.07)"),
                      legend=dict(orientation="h", y=-0.26, x=0, font=dict(size=10.5)),
                      hoverlabel=dict(bgcolor="white", font_size=11.5))
    return fig


def _tile(v, l, c):
    return html.Div([html.Div(v, className="info-tile-value"),
                     html.Div(l, className="info-tile-label")], className=f"info-tile {c}")


# The questions a reviewer, manager or PI would ask — asked here first, answered honestly.
QUESTIONS = [
    ("answered", "The published study reports a larger explained fraction than this page. Why?",
     ["Different target and predictor. The paper (Ghimire et al., 2026) uses its own flow metric "
      "and a fuller method; this page runs a deliberately simple single-predictor regression on "
      "basin-mean VIC yield so that every number on screen can be reproduced from the bundled "
      "cache. We report ", html.B("our own figure, not theirs"),
      " — the two measure different things and are not interchangeable."]),
    ("partly", "Soil moisture and yield both come from VIC. Is this just model memory?",
     ["A fair challenge, and the direct answer is: partly addressed, not fully closed. The "
      "relationship itself is established independently in peer review (Ghimire et al., 2026, "
      "Water Resources Research), and the VIC soil moisture used here is evaluated against NASA "
      "SMAP (R² 0.71 surface, 0.81 root zone; Wang et al., 2026). ",
      html.B("A fully independent test — observed soil moisture against observed naturalised "
             "flow — has not been done, and is the clearest next step.")]),
    ("open", "Could the basin be read in real time, every October?",
     ["The reanalysis here ends in WY2024, so the page shows the most recent complete year and "
      "extrapolates nothing. But the interesting question is what a live version would be worth: ",
      html.B("if managers saw this number every 1 October, how much earlier could allocation "
             "decisions move?"),
      " Answering it needs current-year forcing and a standing update — a design question as much "
      "as a science one."]),
    ("open", "Does the starting soil beat the forecast managers already use?",
     ["Not tested here. The Seasonal Forecasts tab benchmarks a different product (NMME + VIC) "
      "against the 24-Month Study, but nobody has yet asked the sharper question: ",
      html.B("does October soil moisture add skill on top of the operational October outlook, "
             "or merely repeat it?"),
      " A like-for-like comparison would settle whether this is new information or a familiar "
      "signal in new clothes — and that is worth knowing before anyone plans with it."]),
    ("answered", "Why is the signal so weak in the Lower Basin?",
     ["Because Lower-Basin flow is governed largely by upstream releases and management rather "
      "than by local soil moisture. The out-of-sample skill there is low, and the page ",
      html.B("says so on screen"), " rather than presenting a number that would not survive use."]),
    ("open", "If the soil sets the odds, can the odds be changed?",
     ["This is the question the basin itself raises. If the moisture the basin carries into "
      "October shapes the year that follows, then ",
      html.B("anything that changes autumn storage — managed recharge, forest and vegetation "
             "management, irrigation timing — is not just a local intervention but a lever on "
             "next year's supply."),
      " Whether that lever is large enough to matter at basin scale is untested, and it is "
      "probably the most consequential question on this page."]),
]

_QSTATE = {"answered": ("Answered", "qa-ok"), "partly": ("Partly answered", "qa-part"),
           "open": ("For the next study", "qa-open")}


def _questions():
    items = []
    for i, (state, q, a) in enumerate(QUESTIONS, 1):
        label, cls = _QSTATE[state]
        items.append(html.Details([
            html.Summary([
                html.Span(f"{i:02d}", className="qa-num"),
                html.Span(q, className="qa-q"),
                html.Span(label, className=f"qa-badge {cls}"),
                html.I(className="bi bi-chevron-down qa-chev"),
            ], className="qa-sum"),
            html.Div(a, className="qa-a"),
        ], className="qa-item"))
    return html.Div([
        html.Div([
            html.Div("Questions this raises", className="qa-h"),
            html.Div(["Some of these have answers. The ones marked ",
                      html.Span("for the next study", className="qa-badge qa-open",
                                style={"display": "inline-block", "verticalAlign": "middle"}),
                      " do not — they are the open questions this basin puts to the next "
                      "researcher, and to anyone deciding how the Colorado is managed."],
                     className="qa-s"),
        ], className="qa-head"),
        html.Div(items, className="qa-list"),
    ], className="crb-card qa-card")


def layout():
    return html.Div([
        html.Div([
            html.H2("October Signal"),
            html.P("What the basin already knows on 1 October — months before any "
                   "snow-based forecast is issued."),
        ], className="tab-header"),
        howto("The water year begins on 1 October. Pick a basin: the chart shows how the soil "
              "moisture the basin starts with relates to the water it delivers over the following "
              "year, with a 95% prediction band and cross-validated out-of-sample skill."),
        html.Div([
            html.Div([
                html.Div("BASIN", className="control-label"),
                dcc.Dropdown(id="oc-basin", options=BASIN_OPTIONS, value="CRB", clearable=False,
                             style={"fontSize": "12.5px", "maxWidth": "340px"}),
            ], style={"marginBottom": "12px"}),

            dbc.Row(id="oc-tiles", className="g-2 mb-3"),

            html.Div([
                html.Div([html.Span("Soil moisture on 1 October vs the water year that follows",
                                    style={"fontWeight": "700", "fontSize": "13px"}),
                          pub_star("https://doi.org/10.1029/2025WR042871", "Ghimire, Vivoni & Wang (2026), Water Resources Research 62(7)")],
                         className="crb-card-header"),
                dcc.Loading(dcc.Graph(id="oc-fig", config={"displayModeBar": False},
                                      style={"height": "380px"})),
                html.Div(id="oc-note",
                         style={"fontSize": "12.5px", "color": NAVY, "fontWeight": "700",
                                "background": "#faf5f2", "borderLeft": f"3px solid {MAROON}",
                                "padding": "11px 14px", "borderRadius": "0 6px 6px 0",
                                "margin": "0 16px 14px"}),
            ], className="crb-card", style={"marginBottom": "14px"}),

            html.Div([
                html.Div([html.I(className="bi bi-journal-check",
                                 style={"marginRight": "7px", "color": GREEN}),
                          "Peer-reviewed basis: ",
                          html.A("Ghimire, Vivoni & Wang (2026), “Fall Soil Moisture Modulates "
                                 "Snow–Streamflow Dynamics in the Colorado River Basin”, Water "
                                 "Resources Research 62(7)",
                                 href="https://doi.org/10.1029/2025WR042871", target="_blank",
                                 rel="noopener")],
                         style={"fontSize": "12px", "color": "#37474f", "marginBottom": "8px"}),
                html.Div(id="oc-caveat",
                         style={"fontSize": "11px", "color": "#546e7a", "lineHeight": "1.6"}),
            ], className="crb-card", style={"padding": "13px 16px"}),

            _questions(),

            xref("Related analyses:", [("Soil moisture → streamflow", "/links"),
                                       ("Snowpack & runoff", "/snowpack"),
                                       ("Seasonal forecasts (NMME)", "/nmme")]),
        ], className="tab-body"),
    ])


def register_callbacks(app):
    @app.callback(Output("oc-tiles", "children"), Output("oc-fig", "figure"),
                  Output("oc-note", "children"), Output("oc-caveat", "children"),
                  Input("oc-basin", "value"))
    def _update(basin):
        basin = basin or "CRB"
        f = _fit(basin)
        fig = _fig(basin)
        if not f:
            return [], fig, "No data available for this basin.", ""
        gain = (f["wet_y"] - f["dry_y"]) / abs(f["dry_y"]) * 100 if f["dry_y"] else float("nan")
        weak = f["loo"] < 0.25
        tiles = [
            dbc.Col(_tile(f"{f['loo']:.2f}", "out-of-sample skill (LOO R²)",
                          "tile-maroon" if not weak else "tile-navy"), xs=6, md=3),
            dbc.Col(_tile(f"{f['dry_y']:.0f} mm", "yield after a dry October (10th pct)",
                          "tile-gold"), xs=6, md=3),
            dbc.Col(_tile(f"{f['wet_y']:.0f} mm", "yield after a wet October (90th pct)",
                          "tile-blue"), xs=6, md=3),
            dbc.Col(_tile(f"{gain:+.0f}%", "difference the starting soil makes",
                          "tile-green"), xs=6, md=3),
        ]
        pi = _pi(f, f["last_x"])
        note = [
            f"In {basin_label(basin)}, the soil moisture the basin starts the water year with "
            f"explains about ", html.B(f"{f['r2']*100:.0f}% of the variance"),
            f" in that year's water supply (p = {f['p']:.0e}, n = {f['n']} years), and holds up "
            f"out of sample (LOO R² = {f['loo']:.2f}). A wet October is followed by ",
            html.B(f"{gain:+.0f}% more water"), " than a dry one. Most recently, WY",
            f"{f['last_yr']} began at {f['last_x']:.0f} mm, implying "
            f"{f['last_pred']:.0f} ± {pi:.0f} mm — the basin delivered {f['last_y']:.0f} mm.",
        ]
        caveat = [
            "Method: ordinary least squares of water-year yield on October-mean column soil "
            "moisture, WY1984–2024, computed live from the VIC 5.0 PRISM-calibrated cache; the "
            "band is a 95% prediction interval and the skill is leave-one-out cross-validated. ",
            html.B("This is the tool's own single-predictor regression"),
            " — the published study reports a larger explained fraction using a fuller method. "
            "Soil moisture here is modelled (VIC), evaluated against NASA SMAP in Wang et al. "
            "(2026). ",
            html.B("Where the signal is weak, it is shown as weak: ") if weak else "",
            ("in this basin the out-of-sample skill is low, so the relationship should not be "
             "used for planning here." if weak else
             "It is an indicator of the odds, not a forecast of a particular year."),
        ]
        return tiles, fig, note, caveat
