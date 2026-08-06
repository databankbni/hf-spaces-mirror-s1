"""
modules/aridification.py — Module: Aridification & Vanishing Runoff Explorer
Interactive tool: user picks a basin + year range and explores how much of the
river's water yield is being lost to WARMING (not just drought).

Charts:
  1. Runoff efficiency over time + Sen-slope trend
  2. Runoff efficiency vs basin temperature (the warming signal) + fit
  3. Per-basin warming sensitivity leaderboard (% runoff per +1 °C)
Method: multivariate elasticity  ln(Q) = a + b·ln(P) + c·T
        c = fractional change in water yield per +1 °C, precipitation held constant.
        (Benchmarks Milly & Dunne 2020 ≈ −9.3 %/°C.)
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual, basin_label, trend_slope, trend_ci
from utils.components import xref, pub_evidence, pub_star, pub_author, howto
from utils.charts import lollipop_h

MAROON="#8C1D40"; NAVY="#0D2137"; BLUE="#01579B"; GREEN="#2E7D32"
ORANGE="#E65100"; PURPLE="#4527A0"; TEAL="#00695C"; GREY="#94a3b8"
BASIN_OPTIONS=[
    {"label":"Colorado River Basin","value":"CRB"},
    {"label":"◆ All sub-basins (compare)","value":"ALL"},
    {"label":"Upper Basin","value":"UpperBasin"},
    {"label":"Lower Basin","value":"LowerBasin"},
    {"label":"Green River","value":"Green"},
    {"label":"San Juan","value":"SanJuan"},
    {"label":"Upper Colorado","value":"UpperColo"},
    {"label":"Glen Canyon","value":"GlenCanyon"},
    {"label":"Gila River","value":"Gila"},
    {"label":"Grand Canyon","value":"GrandCanyon"},
    {"label":"Little Colorado","value":"LittleColo"},
    {"label":"Lower Colorado","value":"LowerColo"},
]

def _safe(fn):
    try: return fn()
    except: return pd.DataFrame()

def _empty(msg="Run preprocessing first"):
    fig=go.Figure()
    fig.add_annotation(text=msg,xref="paper",yref="paper",x=0.5,y=0.5,
                       showarrow=False,font=dict(size=12,color="#90a4ae"))
    fig.update_layout(paper_bgcolor="white",plot_bgcolor="white",
                      xaxis=dict(visible=False),yaxis=dict(visible=False),
                      margin=dict(l=20,r=20,t=30,b=20),height=300)
    return fig

def _tile(val,label,icon,color):
    return html.Div([
        html.Div(str(val),className="info-tile-value"),
        html.Div(label,   className="info-tile-label"),
        html.Div(icon,    className="info-tile-icon"),
    ],className=f"info-tile {color}")

def _prep(df, basin, years):
    if basin=="ALL": basin="CRB"   # non-overlay panels show whole-basin context
    b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&(df["water_year"]<=years[1])].copy()
    if b.empty: return b
    b=b.sort_values("water_year")
    b["Q"]=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
    b["RE"]=b["Q"]/b["OUT_PREC"]*100
    return b

def _elasticity(b):
    """Return dict(pctC, tval, r2, n) from ln(Q)=a+b ln(P)+c T. None if too few."""
    d=b.dropna(subset=["Q","OUT_PREC","OUT_AIR_TEMP"])
    d=d[d["Q"]>0]
    if len(d)<10: return None
    X=np.column_stack([np.ones(len(d)), np.log(d["OUT_PREC"].values), d["OUT_AIR_TEMP"].values])
    y=np.log(d["Q"].values)
    beta,_,_,_=np.linalg.lstsq(X,y,rcond=None)
    resid=y-X@beta; ssr=float((resid**2).sum()); sst=float(((y-y.mean())**2).sum())
    r2=1-ssr/sst if sst>0 else np.nan
    n=len(d)
    try:
        se=np.sqrt(ssr/(n-3)*np.linalg.inv(X.T@X)[2,2]); tval=beta[2]/se if se>0 else np.nan
    except Exception:
        tval=np.nan
    return dict(pctC=beta[2]*100, tval=tval, r2=r2, n=n)


def layout():
    return html.Div([
        html.Div([
            html.H2("Aridification & Vanishing Runoff"),
            html.P("How much of the Colorado is lost to warming — not drought. Pick a basin and period to explore."),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="ar-tiles",className="mb-3 g-2"),
            html.Div(id="ar-findings",
                     style={"background":"#fdecea","borderLeft":f"3px solid {MAROON}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#8C1D40","marginBottom":"12px"}),
                            howto("Pick a basin and years. The warming sensitivity (percent runoff lost per degree C) and trends show how warming alone is reducing supply."),
                            pub_author("Milly & Dunne 2020", "https://www.science.org/doi/10.1126/science.aay9187", "Milly & Dunne 2020, Science 367:1252", "published"),

            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("Basin",className="control-label"),
                        dcc.Dropdown(id="ar-basin",options=BASIN_OPTIONS,value="CRB",
                                     clearable=False,style={"fontSize":"12.5px"}),
                    ],md=4),
                    dbc.Col([
                        html.Div("Year Range",className="control-label"),
                        dcc.RangeSlider(id="ar-years",min=1984,max=2024,step=1,
                                        value=[1984,2024],
                                        marks={y:str(y) for y in range(1990,2025,10)},
                                        tooltip={"placement":"bottom","always_visible":False}),
                    ],md=8),
                ]),
            ],className="control-panel"),

            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Runoff Efficiency Over Time",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— (runoff+baseflow)/precip; falling = less river per storm",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                            dbc.Button("CSV",id="ar-dl-btn",size="sm",className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                            pub_star("https://www.science.org/doi/10.1126/science.aay9187", "Milly & Dunne 2020, Science 367:1252", "Published"),
                        ],className="crb-card-header"),
                        dcc.Graph(id="ar-ts-chart",config={"displayModeBar":False},
                                  style={"height":"320px"}),
                        dcc.Download(id="ar-dl-data"),
                    ],className="crb-card"),
                ],md=6),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span(" Warmer Years Run Drier",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— runoff efficiency vs temperature",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="ar-scatter-chart",config={"displayModeBar":False},
                                  style={"height":"320px"}),
                    ],className="crb-card"),
                ],md=6),
            ],className="g-3 mb-2"),

            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Warming Sensitivity Leaderboard",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— % runoff lost per +1 °C (maroon = significant |t|>2)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="ar-bars-chart",config={"displayModeBar":False},
                                  style={"height":"380px"}),
                    ],className="crb-card"),
                ],md=12),
            ],className="g-3"),

            html.Div("Method: multivariate elasticity ln(Q)=a+b·ln(P)+c·T; c is the warming ""sensitivity with precipitation held constant. Benchmark: Milly & Dunne 2020 ≈ −9.3 %/°C.",
                     style={"fontSize":"10.5px","color":"#1e293b","marginTop":"6px"}),
            xref("Related analyses:", [("Explore interactively → Scenario", "/scenario"), ("Confidence bounds → Uncertainty", "/uncertainty")]),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("ar-tiles","children"),
                  Input("ar-basin","value"), Input("ar-years","value"))
    def tiles(basin, years):
        df=_safe(load_vic_annual)
        labels=["Warming (°C/decade)","Sensitivity (%/+1°C)","Implied flow loss","Runoff-ratio trend"]
        if df.empty:
            return [dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3) for l in labels]
        b=_prep(df,basin,years)
        if b.empty:
            return [dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3) for l in labels]
        tw=trend_slope(b["OUT_AIR_TEMP"],b["water_year"])
        warm_dec=tw["slope"]*10 if tw["slope"] is not None else None
        el=_elasticity(b)
        sens=el["pctC"] if el else None
        warming_total=(tw["slope"]*(b["water_year"].max()-b["water_year"].min())) if tw["slope"] else None
        implied=(sens/100*warming_total) if (sens is not None and warming_total is not None) else None
        tr=trend_slope(b["RE"]/100,b["water_year"])
        rr_dec=tr["slope"]*10 if tr["slope"] is not None else None
        tiles_=[
            _tile(f"{warm_dec:+.2f}" if warm_dec is not None else "—","Warming (°C/decade)","","tile-maroon"),
            _tile(f"{sens:+.1f}%" if sens is not None else "—","Runoff sensitivity (per +1°C)"," ","tile-navy"),
            _tile(f"{implied*100:+.1f}%" if implied is not None else "—","Implied flow loss to warming"," ","tile-blue"),
            _tile(f"{rr_dec:+.4f}" if rr_dec is not None else "—","Runoff-ratio trend /decade"," ","tile-green"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("ar-ts-chart","figure"),
                  Input("ar-basin","value"), Input("ar-years","value"))
    def ts_chart(basin, years):
        # "All sub-basins" → overlay every sub-basin's runoff efficiency (Q/P) on one chart.
        if basin == "ALL":
            from utils.multibasin import multi_basin_fig
            return multi_basin_fig("RE", years=years, height=320)
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        b=_prep(df,basin,years)
        if b.empty: return _empty("No data")
        b["r5"]=b["RE"].rolling(5,center=True).mean()
        t=trend_ci(b["RE"],b["water_year"])
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=b["water_year"],y=b["RE"],mode="lines+markers",
            line=dict(color=BLUE,width=1.5,shape="spline",smoothing=0.4),
            marker=dict(size=4,color=BLUE,opacity=0.6),fill="tozeroy",
            fillcolor="rgba(1,87,155,0.12)",name="Runoff efficiency (%)",
            hovertemplate="WY %{x}<br>RE: %{y:.1f}%<extra></extra>"))
        fig.add_trace(go.Scatter(x=b["water_year"],y=b["r5"],mode="lines",
            line=dict(color=NAVY,width=2.5),name="5-yr mean"))
        if t["slope"] is not None:
            xr=np.array([b["water_year"].min(),b["water_year"].max()])
            yf=t["slope"]*xr+(b["RE"].mean()-t["slope"]*b["water_year"].mean())
            sig=" (sig.)" if (t["pvalue"] is not None and t["pvalue"]<0.05) else ""
            ci_txt=(f" · 95% CI [{t['lo']*10:+.2f}, {t['hi']*10:+.2f}]"
                    if t.get("lo") is not None else "")
            fig.add_trace(go.Scatter(x=xr,y=yf,mode="lines",
                line=dict(color=MAROON,width=2,dash="dot"),
                name=f"Trend {t['slope']*10:+.2f}%/dec{ci_txt}{sig}"))
        fig.update_layout(xaxis_title="Water Year",yaxis_title="Runoff efficiency (%)",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=60),height=320,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("ar-scatter-chart","figure"),
                  Input("ar-basin","value"), Input("ar-years","value"))
    def scatter_chart(basin, years):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        b=_prep(df,basin,years)
        if b.empty: return _empty("No data")
        x=b["OUT_AIR_TEMP"].values; y=b["RE"].values
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=x,y=y,mode="markers",
            marker=dict(size=7,color=b["water_year"],colorscale="YlOrRd",
                        showscale=True,colorbar=dict(title="WY",thickness=10)),
            text=b["water_year"],
            hovertemplate="WY %{text}<br>T: %{x:.2f}°C<br>RE: %{y:.1f}%<extra></extra>",
            name="Water year"))
        if len(x)>2:
            m,c=np.polyfit(x,y,1)
            xr=np.array([x.min(),x.max()])
            fig.add_trace(go.Scatter(x=xr,y=m*xr+c,mode="lines",
                line=dict(color=MAROON,width=2),name=f"Slope {m:.1f}%/°C"))
        fig.update_layout(xaxis_title="Basin air temperature (°C)",
            yaxis_title="Runoff efficiency (%)",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=60),height=320,
            paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("ar-bars-chart","figure"), Input("ar-years","value"))
    def bars_chart(years):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        rows=[]
        for opt in BASIN_OPTIONS:
            bid=opt["value"]
            if bid=="ALL": continue   # skip the compare-overlay pseudo-option
            b=_prep(df,bid,years)
            el=_elasticity(b)
            if el is None: continue
            rows.append((opt["label"],el["pctC"],el["tval"]))
        if not rows: return _empty("Not enough data")
        rows.sort(key=lambda r:r[1])  # most negative first
        labels=[r[0] for r in rows]; vals=[r[1] for r in rows]
        colors=[MAROON if (abs(r[2])>2 if r[2]==r[2] else False) else GREY for r in rows]
        return lollipop_h(labels, vals, colors,
            x_title="% change in water yield per +1 °C  (maroon = significant |t|>2)",
            unit="%", height=380, diverging=True)

    @app.callback(Output("ar-findings","children"),
                  Input("ar-basin","value"), Input("ar-years","value"))
    def findings(basin, years):
        df=_safe(load_vic_annual)
        if df.empty: return " Findings will appear after preprocessing is complete."
        b=_prep(df,basin,years)
        if b.empty: return "No data for selected range."
        tw=trend_slope(b["OUT_AIR_TEMP"],b["water_year"])
        el=_elasticity(b)
        if not el or tw["slope"] is None:
            return "Not enough complete years in this range for a robust estimate."
        warming=tw["slope"]*(b["water_year"].max()-b["water_year"].min())
        implied=el["pctC"]/100*warming
        sigT="significant " if abs(el["tval"])>2 else "not significant"
        return [html.Strong("Key finding — "),
                f"{basin_label(basin)}: warmed {warming:+.2f} °C over WY{years[0]}–{years[1]} "
                f"({tw['slope']*10:+.2f} °C/decade). Runoff sensitivity {el['pctC']:+.1f}% per +1 °C "
                f"({sigT}, R²={el['r2']:.2f}) about {implied*100:+.1f}% of water yield lost to warming alone, "
                f"separate from any precipitation change."]

    @app.callback(Output("ar-dl-data","data"),Input("ar-dl-btn","n_clicks"),
                  Input("ar-basin","value"),prevent_initial_call=True)
    def download(n,basin):
        if not n: return None
        df=_safe(load_vic_annual)
        if df.empty: return None
        b=df[df["basin"]==basin].copy()
        b["Q"]=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
        b["runoff_efficiency_pct"]=b["Q"]/b["OUT_PREC"]*100
        cols=["water_year","basin","OUT_PREC","OUT_AIR_TEMP","OUT_RUNOFF","OUT_BASEFLOW","Q","runoff_efficiency_pct"]
        return dcc.send_data_frame(b[cols].to_csv,f"crb_vanishing_runoff_{basin}.csv",index=False)
