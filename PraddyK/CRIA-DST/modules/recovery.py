"""
modules/recovery.py — The 2023 "Great Recovery" natural experiment
WY2023 brought near-record snow right after the worst megadrought years. This module
triangulates how much the basin recovered (SWE, soil moisture, runoff, GRACE storage)
and how quickly it relapsed in 2024 — the rare multi-sensor before/after the short
SMAP record happens to capture.
Verified (CRB): SWE 38 93 mm (WY22 23), runoff 23 38 mm, then fell back in 2024.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual, load_grace, basin_label
from utils.components import xref, pub_evidence, pub_star, pub_author, howto

MAROON="#8C1D40"; NAVY="#0D2137"; BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; PURPLE="#4527A0"
BASIN_OPTIONS=[{"label":n,"value":b} for b,n in [
    ("CRB","Colorado River Basin"),("UpperBasin","Upper Basin"),("LowerBasin","Lower Basin"),
    ("Green","Green River"),("SanJuan","San Juan"),("UpperColo","Upper Colorado"),
    ("GlenCanyon","Glen Canyon"),("Gila","Gila River"),("GrandCanyon","Grand Canyon"),
    ("LittleColo","Little Colorado"),("LowerColo","Lower Colorado")]]

def _safe(fn):
    try: return fn()
    except: return pd.DataFrame()

def _empty(msg="Run preprocessing first"):
    fig=go.Figure(); fig.add_annotation(text=msg,xref="paper",yref="paper",x=0.5,y=0.5,
        showarrow=False,font=dict(size=12,color="#90a4ae"))
    fig.update_layout(paper_bgcolor="white",plot_bgcolor="white",xaxis=dict(visible=False),
        yaxis=dict(visible=False),margin=dict(l=20,r=20,t=30,b=20),height=300); return fig

def _tile(val,label,icon,color):
    return html.Div([html.Div(str(val),className="info-tile-value"),
        html.Div(label,className="info-tile-label"),html.Div(icon,className="info-tile-icon")],
        className=f"info-tile {color}")

def _data(basin):
    a=_safe(load_vic_annual)
    if a.empty: return pd.DataFrame()
    b=a[(a["basin"]==basin)&(a["water_year"]>=2015)].sort_values("water_year").copy()
    if b.empty: return pd.DataFrame()
    b["Q"]=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
    return b


def layout():
    return html.Div([
        html.Div([
            html.H2("Drought Recovery — Water Year 2023"),
            html.P("One epic snow year after the megadrought — how much came back, and how fast it slipped away."),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="rc-tiles",className="mb-3 g-2"),
            html.Div(id="rc-findings",
                     style={"background":"#e8f5e9","borderLeft":f"3px solid {GREEN}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#1b5e20","marginBottom":"12px"}),
                            howto("Pick a basin. This indexes the 2023 recovery against the 2021-22 drought across sensors, showing how much a single wet year actually restored."),
                            pub_author("Abdelmohsen et al. 2025", "https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2025GL115593", "Abdelmohsen et al. 2025, GRL", "published"),
            html.Div([dbc.Row([dbc.Col([
                html.Div("Basin",className="control-label"),
                dcc.Dropdown(id="rc-basin",options=BASIN_OPTIONS,value="CRB",clearable=False,
                             style={"fontSize":"12.5px"}),
            ],md=5)])],className="control-panel"),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("Recovery & relapse (indexed to 2021–22 drought = 100)",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— SWE · soil moisture · runoff",style={"color":"#1e293b","fontSize":"11px"}),
                            dbc.Button("CSV",id="rc-dl-btn",size="sm",className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                            pub_star("https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2025GL115593", "Abdelmohsen et al. 2025, GRL", "Published"),
                        ],className="crb-card-header"),
                        dcc.Graph(id="rc-idx",config={"displayModeBar":False},style={"height":"350px"}),
                        dcc.Download(id="rc-dl-data"),
                    ],className="crb-card"),
                ],md=7),
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("Total storage (GRACE)",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— did the bank account refill?",style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="rc-grace",config={"displayModeBar":False},style={"height":"350px"}),
                    ],className="crb-card"),
                ],md=5),
            ],className="g-3"),
            html.Div("Indexed to the 2021–22 drought mean (=100). SMAP (Nov 2022–Sep 2024) independently ""covers this exact window; GRACE shows whether total storage actually refilled.",
                     style={"fontSize":"10.5px","color":"#1e293b","marginTop":"6px"}),
            xref("Related GRACE views:", [("Full storage record → Water Storage", "/tws"), ("Groundwater residual → Storage", "/storage")]),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("rc-tiles","children"), Input("rc-basin","value"))
    def tiles(basin):
        b=_data(basin)
        labels=["2023 snow vs 2022","2023 runoff vs drought","2024 retained","Status"]
        if b.empty or 2023 not in b["water_year"].values:
            return [dbc.Col(_tile("—",l,"","tile-navy"),xs=6,md=3) for l in labels]
        s=b.set_index("water_year")
        swe_jump=(s.loc[2023,"OUT_SWE"]/s.loc[2022,"OUT_SWE"]-1)*100 if 2022 in s.index and s.loc[2022,"OUT_SWE"]>0 else np.nan
        dnorm=s.loc[[y for y in (2021,2022) if y in s.index],"Q"].mean()
        q_rec=(s.loc[2023,"Q"]/dnorm-1)*100 if dnorm>0 else np.nan
        # 2024 retention: how much of the 2023 gain over drought was kept
        if 2024 in s.index and dnorm>0:
            gain=s.loc[2023,"Q"]-dnorm; kept=s.loc[2024,"Q"]-dnorm
            retain=kept/gain*100 if gain!=0 else np.nan
        else: retain=np.nan
        status="Strong but temporary" if (retain==retain and retain<60) else "Recovering"
        tiles_=[
            _tile(f"+{swe_jump:.0f}%" if swe_jump==swe_jump else "—","2023 peak SWE vs 2022","","tile-blue"),
            _tile(f"+{q_rec:.0f}%" if q_rec==q_rec else "—","2023 runoff vs drought"," ","tile-green"),
            _tile(f"{retain:.0f}%" if retain==retain else "—","of the gain kept in 2024"," ","tile-maroon"),
            _tile(status,"Recovery verdict","","tile-navy"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("rc-idx","figure"), Input("rc-basin","value"))
    def idx(basin):
        b=_data(basin)
        if b.empty: return _empty("No data")
        base=b[b["water_year"].isin([2021,2022])]
        if base.empty: return _empty("No drought baseline")
        fig=go.Figure()
        for col,lbl,color in [("OUT_SWE","Peak SWE",BLUE),("OUT_SOIL_MOIST","Soil moisture",PURPLE),("Q","Runoff",NAVY)]:
            bn=base[col].mean()
            if bn==0: continue
            fig.add_trace(go.Scatter(x=b["water_year"],y=b[col]/bn*100,name=lbl,mode="lines+markers",
                line=dict(color=color,width=2),marker=dict(size=5)))
        fig.add_hline(y=100,line_dash="dash",line_color="#b0bec5",line_width=1,
                      annotation_text="drought baseline",annotation_font=dict(size=9,color="#90a4ae"))
        fig.add_vrect(x0=2022.5,x1=2023.5,fillcolor="rgba(46,125,50,0.08)",line_width=0,
                      annotation_text="WY2023",annotation_font=dict(size=9,color=GREEN))
        fig.update_layout(xaxis_title="Water Year",yaxis_title="Index (drought 2021–22 = 100)",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=60),height=350,paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("rc-grace","figure"), Input("rc-basin","value"))
    def grace(basin):
        g=_safe(load_grace)
        if g.empty: return _empty("No GRACE")
        gg=g[(g["basin"]==basin)].copy()
        if gg.empty or "lwe_cm" not in gg.columns: return _empty("No GRACE for basin")
        gg["date"]=pd.to_datetime(gg["date"]); gg=gg[gg["date"]>="2018-01-01"].sort_values("date")
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=gg["date"],y=gg["lwe_cm"]*10,mode="lines",
            line=dict(color=MAROON,width=2),name="GRACE storage (mm)",
            hovertemplate="%{x|%Y-%m}<br>%{y:.0f} mm<extra></extra>"))
        fig.add_hline(y=0,line_dash="dash",line_color="#b0bec5",line_width=1)
        fig.add_vrect(x0="2022-10-01",x1="2023-09-30",fillcolor="rgba(46,125,50,0.08)",line_width=0,
                      annotation_text="WY2023",annotation_font=dict(size=9,color=GREEN))
        fig.update_layout(xaxis_title="",yaxis_title="GRACE storage anomaly (mm)",
            margin=dict(l=55,r=15,t=10,b=40),height=350,showlegend=False,
            paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("rc-findings","children"), Input("rc-basin","value"))
    def findings(basin):
        b=_data(basin)
        if b.empty or 2023 not in b["water_year"].values: return "Findings will appear after preprocessing."
        s=b.set_index("water_year")
        dnorm=s.loc[[y for y in (2021,2022) if y in s.index],"Q"].mean()
        q23=(s.loc[2023,"Q"]/dnorm-1)*100 if dnorm>0 else float("nan")
        retain=((s.loc[2024,"Q"]-dnorm)/(s.loc[2023,"Q"]-dnorm)*100) if (2024 in s.index and s.loc[2023,"Q"]!=dnorm) else float("nan")
        return [html.Strong(" Key finding — "),
                f"{basin_label(basin)}: WY2023 lifted runoff ~{q23:.0f}% above the 2021–22 drought, "
                f"but by 2024 only ~{retain:.0f}% of that gain remained — one extraordinary snow year "
                f"buys a single season of relief, not a refill of the 20-year deficit."]

    @app.callback(Output("rc-dl-data","data"),Input("rc-dl-btn","n_clicks"),
                  Input("rc-basin","value"),prevent_initial_call=True)
    def download(n,basin):
        if not n: return None
        b=_data(basin)
        if b.empty: return None
        cols=["water_year","basin","OUT_SWE","OUT_SOIL_MOIST","OUT_RUNOFF","OUT_BASEFLOW","Q"]
        return dcc.send_data_frame(b[cols].to_csv,f"crb_recovery_{basin}.csv",index=False)
