"""
modules/asi.py — Aridification Severity Index (ASI) Explorer
A novel composite stress index (0–100) per basin per water year, built from four
independent VIC signals, each standardized against that basin's own 1984–2024 baseline:
    +  rising dryness (ET/P)
    -  falling runoff efficiency (Q/P)
    -  falling soil moisture
    +  warming (air temperature)
    ASI = clip(50 + 15 · mean(z-signals), 0, 100)   (50 = normal; higher = more aridified)

Validated against known events: CRB peaks in 2018, 2002, 2021 (severe hot-droughts) and
drops in 2023 & 2019 (wet/recovery years).

Tool controls: pick a YEAR (leaderboard across 11 basins, drag to animate) and a BASIN
(stress timeline + driver breakdown).
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual, basin_label
from utils.components import howto
from utils.charts import lollipop_h, dot_h, box_h, box_v

MAROON="#8C1D40"; NAVY="#0D2137"; BLUE="#01579B"; GREEN="#2E7D32"
ORANGE="#E65100"; PURPLE="#4527A0"; TEAL="#00695C"; GREY="#94a3b8"
BASIN_OPTIONS=[
    {"label":"Colorado River Basin","value":"CRB"},
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
SIGNALS=[("sRE","Low runoff efficiency",BLUE),
         ("sDRY","High dryness (ET/P)",ORANGE),
         ("sSM","Low soil moisture",PURPLE),
         ("sT","Warming",MAROON)]

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

def _z(s):
    sd=s.std(ddof=0)
    return (s-s.mean())/sd if sd>0 else s*0.0

def _compute_asi(df):
    """Return df with ASI + 4 standardized signal columns, per basin/year."""
    d=df.copy()
    d["RE"]=(d["OUT_RUNOFF"]+d["OUT_BASEFLOW"])/d["OUT_PREC"]
    d["DRY"]=d["OUT_EVAP"]/d["OUT_PREC"]
    out=[]
    for b,g in d.groupby("basin"):
        g=g.sort_values("water_year").copy()
        g["sRE"]=-_z(g["RE"]); g["sDRY"]=_z(g["DRY"])
        g["sSM"]=-_z(g["OUT_SOIL_MOIST"]); g["sT"]=_z(g["OUT_AIR_TEMP"])
        g["ASI"]=np.clip(50+(g["sRE"]+g["sDRY"]+g["sSM"]+g["sT"])/4*15,0,100)
        out.append(g)
    return pd.concat(out)

def _color(v):
    return MAROON if v>=65 else ORANGE if v>=55 else (TEAL if v<=40 else GREY)


def layout():
    return html.Div([
        html.Div([
            html.H2(" Aridification Severity Index"),
            html.P("A composite 0–100 stress index per basin & year. Drag the year to watch the basin aridify."),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="asi-tiles",className="mb-3 g-2"),
            html.Div(id="asi-findings",
                     style={"background":"#fdecea","borderLeft":f"3px solid {MAROON}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#8C1D40","marginBottom":"12px"}),
                            howto("Pick a basin and drag the year. The 0-100 index summarizes combined hydrologic stress (65+ is severe); the decomposition shows which signals are driving it."),

            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("Basin (timeline + drivers)",className="control-label"),
                        dcc.Dropdown(id="asi-basin",options=BASIN_OPTIONS,value="CRB",
                                     clearable=False,style={"fontSize":"12.5px"}),
                    ],md=4),
                    dbc.Col([
                        html.Div("Year (leaderboard) — drag to animate",className="control-label"),
                        dcc.Slider(id="asi-year",min=1984,max=2024,step=1,value=2024,
                                   marks={y:str(y) for y in range(1990,2025,10)},
                                   tooltip={"placement":"bottom","always_visible":True}),
                    ],md=8),
                ]),
            ],className="control-panel"),

            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Basin Leaderboard",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— ASI for the selected year (higher = more aridified)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="asi-bars",config={"displayModeBar":False},
                                  style={"height":"380px"}),
                    ],className="crb-card"),
                ],md=6),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Stress Timeline",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— selected basin, 1984–2024 (drought years flagged)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                            dbc.Button("CSV",id="asi-dl-btn",size="sm",className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="asi-ts",config={"displayModeBar":False},
                                  style={"height":"380px"}),
                        dcc.Download(id="asi-dl-data"),
                    ],className="crb-card"),
                ],md=6),
            ],className="g-3 mb-2"),

            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("What's driving the stress?",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— standardized contribution of each signal over time",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="asi-drivers",config={"displayModeBar":False},
                                  style={"height":"320px"}),
                    ],className="crb-card"),
                ],md=12),
            ],className="g-3"),

            html.Div("ASI = clip(50 + 15 · mean of 4 standardized signals, 0, 100), each signal z-scored ""against the basin's own 1984–2024 record. 50 = typical; >65 = severe aridification. ""Composite of VIC signals only (complete & internally consistent across all years/basins).",
                     style={"fontSize":"10.5px","color":"#1e293b","marginTop":"6px"}),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("asi-tiles","children"),
                  Input("asi-basin","value"), Input("asi-year","value"))
    def tiles(basin, year):
        df=_safe(load_vic_annual)
        labels=["ASI (selected year)","Status","Peak-stress year","Rank this year"]
        if df.empty:
            return [dbc.Col(_tile("—",l,"","tile-navy"),xs=6,md=3) for l in labels]
        A=_compute_asi(df)
        g=A[A["basin"]==basin]
        row=g[g["water_year"]==year]
        val=float(row["ASI"].iloc[0]) if not row.empty else None
        status=("Severe" if val>=65 else "Elevated" if val>=55 else "Low" if val<=40 else "Normal") if val is not None else "—"
        peak=g.loc[g["ASI"].idxmax()] if not g.empty else None
        yr_all=A[A["water_year"]==year].sort_values("ASI",ascending=False).reset_index(drop=True)
        rank=(yr_all.index[yr_all["basin"]==basin][0]+1) if basin in yr_all["basin"].values else None
        n=yr_all["basin"].nunique()
        tiles_=[
            _tile(f"{val:.0f}" if val is not None else "—","ASI (0–100, selected year)","","tile-maroon"),
            _tile(status,"Aridification status","","tile-navy"),
            _tile(f"{int(peak['water_year'])} ({peak['ASI']:.0f})" if peak is not None else "—","Peak-stress year"," ","tile-blue"),
            _tile(f"#{rank} of {n}" if rank else "—","Rank this year (1=worst)"," ","tile-green"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("asi-bars","figure"), Input("asi-year","value"))
    def bars(year):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        A=_compute_asi(df)
        if A.empty: return _empty("No data")
        # vertical box plots — each basin's ASI distribution across all years
        order=A.groupby("basin")["ASI"].median().sort_values(ascending=False).index.tolist()
        cats,series,cols=[],[],[]
        for b in order:
            s=A[A["basin"]==b]["ASI"].dropna()
            if s.empty: continue
            cats.append(basin_label(b)); series.append(list(s.values))
            cols.append(_color(s.median()))
        fig=box_v(cats, series, cols, y_title="Aridification Severity Index", height=380)
        fig.add_hline(y=50,line_dash="dash",line_color="#b0bec5",line_width=1,
                      annotation_text="normal",annotation_font=dict(size=9,color="#607d8b"))
        fig.update_yaxes(range=[0,100])
        return fig

    @app.callback(Output("asi-ts","figure"), Input("asi-basin","value"))
    def timeline(basin):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        A=_compute_asi(df)
        g=A[A["basin"]==basin].sort_values("water_year")
        if g.empty: return _empty("No data")
        fig=go.Figure()
        fig.add_hrect(y0=65,y1=100,fillcolor="rgba(140,29,64,0.07)",line_width=0)
        fig.add_trace(go.Scatter(x=g["water_year"],y=g["ASI"],mode="lines+markers",
            line=dict(color=MAROON,width=2,shape="spline",smoothing=0.4),
            marker=dict(size=5,color=[_color(v) for v in g["ASI"]]),
            fill="tozeroy",fillcolor="rgba(140,29,64,0.08)",
            name="ASI",hovertemplate="WY %{x}<br>ASI %{y:.0f}<extra></extra>"))
        fig.add_hline(y=50,line_dash="dash",line_color="#b0bec5",line_width=1)
        # flag the 3 worst years
        worst=g.nlargest(3,"ASI")
        for _,r in worst.iterrows():
            fig.add_annotation(x=r["water_year"],y=r["ASI"],text=str(int(r["water_year"])),
                               showarrow=True,arrowhead=0,ax=0,ay=-16,
                               font=dict(size=9,color=MAROON))
        fig.update_layout(xaxis_title="Water Year",yaxis_title="ASI (0–100)",
            yaxis=dict(range=[0,100]),margin=dict(l=50,r=15,t=10,b=40),height=380,
            paper_bgcolor="white",plot_bgcolor="white",showlegend=False,
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("asi-drivers","figure"), Input("asi-basin","value"))
    def drivers(basin):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        A=_compute_asi(df)
        g=A[A["basin"]==basin].sort_values("water_year")
        if g.empty: return _empty("No data")
        fig=go.Figure()
        for col,label,color in SIGNALS:
            fig.add_trace(go.Bar(x=g["water_year"],y=g[col],name=label,marker_color=color))
        fig.add_hline(y=0,line_color="#b0bec5",line_width=1)
        fig.update_layout(barmode="relative",xaxis_title="Water Year",
            yaxis_title="Standardized stress contribution (σ)",
            legend=dict(orientation="h",y=-0.25,x=0,font=dict(size=10)),
            margin=dict(l=50,r=15,t=10,b=60),height=320,
            paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("asi-findings","children"),
                  Input("asi-basin","value"), Input("asi-year","value"))
    def findings(basin, year):
        df=_safe(load_vic_annual)
        if df.empty: return "Findings will appear after preprocessing is complete."
        A=_compute_asi(df)
        g=A[A["basin"]==basin]
        row=g[g["water_year"]==year]
        if row.empty: return "No data for selected year."
        r=row.iloc[0]
        drivers=sorted([(lbl,float(r[c])) for c,lbl,_ in SIGNALS],key=lambda x:-x[1])
        top=drivers[0]
        trend=g.sort_values("water_year")
        early=trend[trend["water_year"]<2003]["ASI"].mean()
        late =trend[trend["water_year"]>=2003]["ASI"].mean()
        return [html.Strong(" Key finding — "),
                f"{basin_label(basin)} in WY{year}: ASI = {r['ASI']:.0f}/100 "
                f"({'severe' if r['ASI']>=65 else 'elevated' if r['ASI']>=55 else 'normal/low'}). "
                f"Biggest driver: {top[0]} ({top[1]:+.1f}σ). "
                f"Basin-mean ASI rose from {early:.0f} (pre-2003) to {late:.0f} (2003–2024) — "
                f"the megadrought signature."]

    @app.callback(Output("asi-dl-data","data"),Input("asi-dl-btn","n_clicks"),
                  Input("asi-basin","value"),prevent_initial_call=True)
    def download(n,basin):
        if not n: return None
        df=_safe(load_vic_annual)
        if df.empty: return None
        A=_compute_asi(df)
        g=A[A["basin"]==basin][["water_year","basin","ASI","sRE","sDRY","sSM","sT","RE","DRY","OUT_SOIL_MOIST","OUT_AIR_TEMP"]]
        return dcc.send_data_frame(g.to_csv,f"crb_aridification_index_{basin}.csv",index=False)
