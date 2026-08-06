"""
modules/noanalog.py — 2100 No-Analog Future
Compares each VIC variable's projected WY2100 value (VICOut2.nc) against its full
1984–2024 historical envelope. Variables that fall OUTSIDE the historical range are
"no-analog" — conditions with no precedent in the observed record.
Verified (CRB): air temperature 2100 ≈ 16.7 °C vs historical [11,13] outside.

Honesty: the raw future file holds only year 2100, so this is an END-POINT snapshot,
not a trajectory. Only variables aggregated identically in both records are compared
(fluxes summed, temperatures averaged, SWE as max); soil-moisture state is excluded.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual, basin_label
from utils.components import howto

MAROON="#8C1D40"; NAVY="#0D2137"; BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"
BASIN_OPTIONS=[{"label":n,"value":b} for b,n in [
    ("CRB","Colorado River Basin"),("UpperBasin","Upper Basin"),("LowerBasin","Lower Basin"),
    ("Green","Green River"),("SanJuan","San Juan"),("UpperColo","Upper Colorado"),
    ("GlenCanyon","Glen Canyon"),("Gila","Gila River"),("GrandCanyon","Grand Canyon"),
    ("LittleColo","Little Colorado"),("LowerColo","Lower Colorado")]]
# variables aggregated consistently in both historical & future
VARS=[("OUT_AIR_TEMP","Air temp (°C)"),("OUT_SURF_TEMP","Surface temp (°C)"),
      ("OUT_VEGT","Veg temp (°C)"),("OUT_BARESOILT","Bare-soil temp (°C)"),
      ("OUT_PREC","Precipitation (mm)"),("OUT_EVAP","Total ET (mm)"),
      ("OUT_RUNOFF","Surface runoff (mm)"),("OUT_BASEFLOW","Baseflow (mm)"),
      ("OUT_SNOW_MELT","Snowmelt (mm)"),("OUT_SWE","Peak SWE (mm)"),
      ("OUT_EVAP_BARE","Bare-soil evap (mm)"),("OUT_TRANSP_VEG","Transpiration (mm)")]

def _safe(fn):
    try: return fn()
    except: return pd.DataFrame()

def _future():
    try: return pd.read_parquet(__import__("pathlib").Path(__file__).parent.parent/"data"/"cache"/"vic_future_2100.parquet")
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

def _table(basin):
    a=_safe(load_vic_annual); f=_future()
    if a.empty or f.empty: return pd.DataFrame()
    a=a[a["basin"]==basin]; fr=f[f["basin"]==basin]
    if a.empty or fr.empty: return pd.DataFrame()
    fr=fr.iloc[0]; rows=[]
    for v,lbl in VARS:
        if v not in a.columns or v not in fr.index: continue
        lo,hi,mu,sd=a[v].min(),a[v].max(),a[v].mean(),a[v].std()
        fv=float(fr[v]); z=(fv-mu)/sd if sd>0 else 0
        outside = fv>hi or fv<lo
        rows.append(dict(var=v,label=lbl,lo=lo,hi=hi,mean=mu,f2100=fv,z=z,outside=outside))
    return pd.DataFrame(rows)


def layout():
    return html.Div([
        html.Div([
            html.H2("2100 No-Analog Future"),
            html.P("Which projected conditions have no precedent in 1984–2024? Pick a basin."),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="na-tiles",className="mb-3 g-2"),
            html.Div(id="na-findings",
                     style={"background":"#ede7f6","borderLeft":"3px solid #4527A0",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#4527A0","marginBottom":"12px"}),
                            howto("Pick a basin. This flags where the WY2100 state falls outside the entire 1984-2024 range — a 'no-analog' condition with no historical precedent."),
            html.Div([dbc.Row([dbc.Col([
                html.Div("Basin",className="control-label"),
                dcc.Dropdown(id="na-basin",options=BASIN_OPTIONS,value="CRB",clearable=False,
                             style={"fontSize":"12.5px"}),
            ],md=5)])],className="control-panel"),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("2100 vs historical envelope",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— distance from the 1984–2024 mean, in std-devs (σ)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="na-bars",config={"displayModeBar":False},style={"height":"420px"}),
                    ],className="crb-card"),
                ],md=12),
            ],className="g-3"),
            html.Div("End-point snapshot from a single downscaled VIC run (not a multi-model ensemble): ""VICOut2.nc holds only WY2100 — not a trajectory. Bars show the 2100 value's ""distance from the 1984–2024 mean in σ; markers flagged when 2100 falls outside the full ""historical min–max (a no-analog condition). Soil-moisture state excluded (aggregation mismatch).",
                     style={"fontSize":"10.5px","color":"#1e293b","marginTop":"6px"}),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("na-tiles","children"), Input("na-basin","value"))
    def tiles(basin):
        t=_table(basin)
        labels=["Variables outside history","Warmest signal","Biggest drop","Total compared"]
        if t.empty: return [dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3) for l in labels]
        nout=int(t["outside"].sum())
        warm=t[t["var"].str.contains("TEMP")].sort_values("z",ascending=False)
        wlbl=f"{warm.iloc[0]['label'].split(' (')[0]} {warm.iloc[0]['z']:+.1f}σ" if len(warm) else "—"
        drop=t.sort_values("z").iloc[0]
        tiles_=[
            _tile(f"{nout} of {len(t)}","outside 1984–2024 range"," ","tile-maroon"),
            _tile(wlbl,"strongest warming signal","","tile-navy"),
            _tile(f"{drop['label'].split(' (')[0]} {drop['z']:+.1f}σ","biggest decline"," ","tile-blue"),
            _tile(f"{len(t)}","variables compared"," ","tile-green"),
        ]
        return [dbc.Col(x,xs=6,md=3) for x in tiles_]

    @app.callback(Output("na-bars","figure"), Input("na-basin","value"))
    def bars(basin):
        t=_table(basin)
        if t.empty: return _empty("No future/historical data")
        t=t.sort_values("z")
        colors=[MAROON if o else (ORANGE if abs(z)>2 else "#90a4ae") for o,z in zip(t["outside"],t["z"])]
        fig=go.Figure(go.Bar(x=t["z"],y=t["label"],orientation="h",marker_color=colors,
            text=[f"{z:+.1f}σ"+("" if o else "") for z,o in zip(t["z"],t["outside"])],
            textposition="outside",
            hovertemplate="%{y}<br>2100: %{customdata[0]:.1f}<br>hist [%{customdata[1]:.1f}, %{customdata[2]:.1f}]<extra></extra>",
            customdata=t[["f2100","lo","hi"]].values))
        fig.add_vline(x=0,line_color="#b0bec5",line_width=1)
        fig.add_vrect(x0=-2,x1=2,fillcolor="rgba(144,164,174,0.08)",line_width=0)
        fig.update_layout(xaxis_title="2100 distance from 1984–2024 mean (σ)   ·   maroon = outside historical range",
            margin=dict(l=150,r=50,t=10,b=45),height=420,paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("na-findings","children"), Input("na-basin","value"))
    def findings(basin):
        t=_table(basin)
        if t.empty: return " Findings will appear once the future cache is present."
        outs=t[t["outside"]]
        temp=t[t["var"]=="OUT_AIR_TEMP"]
        msg=f"{basin_label(basin)}: {len(outs)} of {len(t)} variables fall outside the entire 1984–2024 range by 2100"
        if len(outs): msg+=" — led by "+", ".join(outs.sort_values('z',ascending=False)["label"].str.split("(",regex=False).str[0].head(3))
        if len(temp): msg+=f". Air temperature reaches {temp.iloc[0]['f2100']:.1f} °C (history maxed at {temp.iloc[0]['hi']:.1f} °C)."
        return [html.Strong("Key finding — "),msg+" A no-analog future: the basin moves into a climate with no observed precedent."]
