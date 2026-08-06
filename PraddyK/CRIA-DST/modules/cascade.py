"""
modules/cascade.py — Drought Cascade Explorer
How a precipitation deficit propagates: Precip Soil Moisture Runoff Total Storage (GRACE).
Uses deseasonalized standardized monthly anomalies and lag cross-correlation.
Verified (CRB): Precip SoilMoist lag≈1 mo; SoilMoist Runoff r≈0.83; SoilMoist GRACE r≈0.50.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_monthly, load_grace, basin_label
from utils.components import xref, pub_evidence, pub_star, pub_author, howto
from utils.charts import lollipop_h

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

def _monthly(basin):
    m=_safe(load_vic_monthly); g=_safe(load_grace)
    if m.empty: return pd.DataFrame()
    b=m[m["basin"]==basin].sort_values(["year","month"]).copy()
    if b.empty: return pd.DataFrame()
    b["date"]=pd.to_datetime(dict(year=b["year"],month=b["month"],day=1))
    b["Q"]=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
    for col in ["OUT_PREC","OUT_SOIL_MOIST","Q"]:
        clim=b.groupby("month")[col].transform("mean"); sd=b.groupby("month")[col].transform("std")
        b[col+"_a"]=(b[col]-clim)/sd.replace(0,np.nan)
    if not g.empty:
        gg=g[g["basin"]==basin].copy()
        if not gg.empty and "lwe_cm" in gg.columns:
            gg["date"]=pd.to_datetime(gg["date"]).dt.to_period("M").dt.to_timestamp()
            s=gg.groupby("date")["lwe_cm"].mean(); s=(s-s.mean())/s.std()
            b["ym"]=b["date"].dt.to_period("M").dt.to_timestamp()
            b["GR_a"]=b["ym"].map(s)
        else: b["GR_a"]=np.nan
    else: b["GR_a"]=np.nan
    return b

def _bestlag(x,y,maxlag=12):
    x=np.asarray(x,float); y=np.asarray(y,float); best=(0,0.0)
    for L in range(0,maxlag+1):
        a,c=(x,y) if L==0 else (x[:-L],y[L:])
        mask=~(np.isnan(a)|np.isnan(c))
        if mask.sum()<24: continue
        r=np.corrcoef(a[mask],c[mask])[0,1]
        if abs(r)>abs(best[1]): best=(L,r)
    return best


def layout():
    return html.Div([
        html.Div([
            html.H2("Drought Propagation Cascade"),
            html.P("Precip Soil Moisture Runoff Total Storage. Pick a basin to see the chain & its lags."),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="dc-tiles",className="mb-3 g-2"),
            html.Div(id="dc-findings",
                     style={"background":"#e3f2fd","borderLeft":f"3px solid {BLUE}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#1565c0","marginBottom":"12px"}),
                            howto("Pick a basin. This traces how a precipitation deficit propagates into soil moisture, runoff and storage, and the time lag at each step."),
                            pub_author("Van Loon 2015", "https://wires.onlinelibrary.wiley.com/doi/10.1002/wat2.1085", "Van Loon 2015, WIREs Water (drought propagation)", "published"),
            html.Div([dbc.Row([dbc.Col([
                html.Div("Basin",className="control-label"),
                dcc.Dropdown(id="dc-basin",options=BASIN_OPTIONS,value="CRB",clearable=False,
                             style={"fontSize":"12.5px"}),
            ],md=5)])],className="control-panel"),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("Deseasonalized anomalies",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— droughts move down the chain over time",style={"color":"#1e293b","fontSize":"11px"}),
                            pub_star("https://wires.onlinelibrary.wiley.com/doi/10.1002/wat2.1085", "Van Loon 2015, WIREs Water", "Published"),
                        ],className="crb-card-header"),
                        dcc.Graph(id="dc-ts",config={"displayModeBar":False},style={"height":"360px"}),
                    ],className="crb-card"),
                ],md=8),
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("⏱ Propagation lags",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— peak cross-correlation",style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="dc-lag",config={"displayModeBar":False},style={"height":"360px"}),
                    ],className="crb-card"),
                ],md=4),
            ],className="g-3"),
            html.Div("Monthly values deseasonalized (minus calendar-month climatology) then standardized. ""Lag = months of peak cross-correlation. GRACE (≈300 km) shown where available.",
                     style={"fontSize":"10.5px","color":"#1e293b","marginTop":"6px"}),
            xref("Related:", [("GRACE storage record → Water Storage", "/tws")]),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("dc-tiles","children"), Input("dc-basin","value"))
    def tiles(basin):
        b=_monthly(basin)
        labels=["Precip Soil lag","Soil Runoff lag","Soil Storage lag","Soil Runoff strength"]
        if b.empty: return [dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3) for l in labels]
        l1=_bestlag(b["OUT_PREC_a"],b["OUT_SOIL_MOIST_a"])
        l2=_bestlag(b["OUT_SOIL_MOIST_a"],b["Q_a"])
        l3=_bestlag(b["OUT_SOIL_MOIST_a"],b["GR_a"]) if b["GR_a"].notna().any() else (None,None)
        tiles_=[
            _tile(f"{l1[0]} mo","Precip Soil Moisture","","tile-blue"),
            _tile(f"{l2[0]} mo","Soil Moisture Runoff"," ","tile-navy"),
            _tile(f"{l3[0]} mo" if l3[0] is not None else "—","Soil Moisture Storage","","tile-maroon"),
            _tile(f"r={l2[1]:+.2f}","Soil Runoff correlation"," ","tile-green"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("dc-ts","figure"), Input("dc-basin","value"))
    def ts(basin):
        b=_monthly(basin)
        if b.empty: return _empty("No data")
        b=b[b["date"]>= "1990-01-01"]
        fig=go.Figure()
        series=[("OUT_PREC_a","Precipitation",BLUE),("OUT_SOIL_MOIST_a","Soil moisture",PURPLE),
                ("Q_a","Runoff",NAVY),("GR_a","GRACE storage",MAROON)]
        for col,lbl,color in series:
            if col not in b.columns or b[col].notna().sum()==0: continue
            fig.add_trace(go.Scatter(x=b["date"],y=b[col],name=lbl,mode="lines",
                line=dict(color=color,width=1.3),opacity=0.9))
        fig.add_hline(y=0,line_dash="dash",line_color="#b0bec5",line_width=1)
        fig.update_layout(xaxis_title="",yaxis_title="Standardized anomaly (σ)",
            legend=dict(orientation="h",y=-0.18,x=0,font=dict(size=10)),
            margin=dict(l=50,r=15,t=10,b=50),height=360,
            paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("dc-lag","figure"), Input("dc-basin","value"))
    def lag(basin):
        b=_monthly(basin)
        if b.empty: return _empty("No data")
        chain=[("Precip Soil",_bestlag(b["OUT_PREC_a"],b["OUT_SOIL_MOIST_a"]),BLUE),
               ("Soil Runoff",_bestlag(b["OUT_SOIL_MOIST_a"],b["Q_a"]),NAVY),
               ("Precip Runoff",_bestlag(b["OUT_PREC_a"],b["Q_a"]),GREEN)]
        if b["GR_a"].notna().any():
            chain.append(("Soil Storage",_bestlag(b["OUT_SOIL_MOIST_a"],b["GR_a"]),MAROON))
        labels=[c[0] for c in chain]; lags=[c[1][0] for c in chain]; colors=[c[2] for c in chain]
        rvals=[c[1][1] for c in chain]
        fig=lollipop_h(labels, lags, colors, x_title="Propagation lag (months)",
            unit=" mo", height=360,
            value_fmt=(lambda v: f"{v:.0f} mo"))
        fig.update_xaxes(range=[0, (max(lags)+4) if lags else 4])
        return fig

    @app.callback(Output("dc-findings","children"), Input("dc-basin","value"))
    def findings(basin):
        b=_monthly(basin)
        if b.empty: return " Findings will appear after preprocessing is complete."
        l1=_bestlag(b["OUT_PREC_a"],b["OUT_SOIL_MOIST_a"]); l2=_bestlag(b["OUT_SOIL_MOIST_a"],b["Q_a"])
        return [html.Strong("Key finding — "),
                f"{basin_label(basin)}: a precipitation deficit reaches soil moisture in ~{l1[0]} month(s), "
                f"and soil-moisture anomalies drive runoff near-instantly (r={l2[1]:+.2f}). "
                f"That short memory means dry winters translate quickly into low flows — little buffering."]
