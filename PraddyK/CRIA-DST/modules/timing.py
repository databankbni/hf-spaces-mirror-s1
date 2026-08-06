"""
modules/timing.py — Melt Timing & Flash Drought (daily-resolution metrics)
Reads data/cache/vic_daily_metrics.parquet (produced by 00_build_cache_corrected.py):
  melt_com_doy  — snowmelt center-of-timing, day-of-water-year (lower = earlier melt)
  peak_swe_doy  — day-of-water-year of maximum SWE
  flash_drop_mm — largest 30-day soil-moisture decline in the water year (rapid-onset drought)
If the file is absent, the page explains how to populate it (one pipeline re-run).
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from pathlib import Path
from utils.data_loader import basin_label
from utils.components import pub_evidence, pub_star, pub_author, howto

MAROON="#8C1D40"; NAVY="#0D2137"; BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"
CACHE=Path(__file__).parent.parent/"data"/"cache"/"vic_daily_metrics.parquet"
_TM_BASINS=[
    ("CRB","Colorado River Basin"),("UpperBasin","Upper Basin"),("LowerBasin","Lower Basin"),
    ("Green","Green River"),("SanJuan","San Juan"),("UpperColo","Upper Colorado"),
    ("GlenCanyon","Glen Canyon"),("Gila","Gila River"),("GrandCanyon","Grand Canyon"),
    ("LittleColo","Little Colorado"),("LowerColo","Lower Colorado")]
BASIN_OPTIONS=([{"label":"Colorado River Basin","value":"CRB"},
                {"label":"◆ All sub-basins (compare)","value":"ALL"}]
               +[{"label":n,"value":b} for b,n in _TM_BASINS if b!="CRB"])

def _load():
    try: return pd.read_parquet(CACHE)
    except: return pd.DataFrame()

def _empty(msg):
    fig=go.Figure(); fig.add_annotation(text=msg,xref="paper",yref="paper",x=0.5,y=0.5,
        showarrow=False,font=dict(size=11,color="#90a4ae"),align="center")
    fig.update_layout(paper_bgcolor="white",plot_bgcolor="white",xaxis=dict(visible=False),
        yaxis=dict(visible=False),margin=dict(l=20,r=20,t=30,b=20),height=320); return fig

def _tile(val,label,icon,color):
    return html.Div([html.Div(str(val),className="info-tile-value"),
        html.Div(label,className="info-tile-label"),html.Div(icon,className="info-tile-icon")],
        className=f"info-tile {color}")

def _sen(x,y):
    if len(x)<5: return None,None
    m,b=np.polyfit(x,y,1)
    yh=m*np.array(x)+b; ss=((np.array(y)-yh)**2).sum(); sxx=((np.array(x)-np.mean(x))**2).sum()
    se=np.sqrt(ss/(len(x)-2)/sxx) if sxx>0 else np.nan
    return m,(m/se if se and se>0 else np.nan)

_NEED="Daily metrics not found.\nRun  preprocessing/00_build_cache_corrected.py  (or run_all.command)\nonce to populate vic_daily_metrics.parquet, then reload."
def layout():
    return html.Div([
        html.Div([
            html.H2(" Melt Timing & Flash Drought"),
            html.P("Is snowmelt arriving earlier, and are rapid-onset (flash) droughts intensifying? Pick a basin."),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="tm-tiles",className="mb-3 g-2"),
            html.Div(id="tm-findings",
                     style={"background":"#e3f2fd","borderLeft":f"3px solid {BLUE}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#1565c0","marginBottom":"12px"}),
                            howto("Pick a basin. These panels show how snowmelt and peak-flow timing have shifted earlier in the year — earlier melt stresses late-summer water supply."),
                            pub_author("Stewart et al.; Nature 2024", "https://www.nature.com/articles/s41586-024-07299-y", "Stewart et al. 2005; Streamflow seasonality 2024, Nature", "published"),
            html.Div([dbc.Row([dbc.Col([
                html.Div("Basin",className="control-label"),
                dcc.Dropdown(id="tm-basin",options=BASIN_OPTIONS,value="CRB",clearable=False,
                             style={"fontSize":"12.5px"}),
            ],md=5)])],className="control-panel"),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([html.Span(" Snowmelt & peak-SWE timing",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— day of water year (lower = earlier)",style={"color":"#1e293b","fontSize":"11px"}),
                            pub_star("https://www.nature.com/articles/s41586-024-07299-y", "Streamflow seasonality 2024, Nature 629", "Published"),
                        ],className="crb-card-header"),
                        dcc.Graph(id="tm-melt",config={"displayModeBar":False},style={"height":"340px"}),
                    ],className="crb-card"),
                ],md=6),
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("Flash-drought intensity",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— largest 30-day soil-moisture drop per year",style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="tm-flash",config={"displayModeBar":False},style={"height":"340px"}),
                    ],className="crb-card"),
                ],md=6),
            ],className="g-3"),
            html.Div("Daily-resolution metrics from the raw VIC files (not monthly proxies). ""Melt center-of-timing weights each day by that day's snowmelt; flash metric is the steepest ""30-day soil-moisture decline.",
                     style={"fontSize":"10.5px","color":"#1e293b","marginTop":"6px"}),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("tm-tiles","children"), Input("tm-basin","value"))
    def tiles(basin):
        if basin=="ALL": basin="CRB"   # side panels show whole-basin context
        d=_load()
        labels=["Melt timing trend","Peak-SWE trend","Worst flash year","Flash trend"]
        if d.empty:
            return [dbc.Col(_tile("run pipeline",l,"","tile-navy"),xs=6,md=3) for l in labels]
        g=d[d["basin"]==basin].dropna(subset=["water_year"]).sort_values("water_year")
        if g.empty: return [dbc.Col(_tile("—",l,"","tile-navy"),xs=6,md=3) for l in labels]
        mm,_=_sen(g["water_year"],g["melt_com_doy"]) if "melt_com_doy" in g else (None,None)
        ms,_=_sen(g["water_year"],g["peak_swe_doy"]) if "peak_swe_doy" in g else (None,None)
        worst=g.loc[g["flash_drop_mm"].idxmax()] if "flash_drop_mm" in g and g["flash_drop_mm"].notna().any() else None
        mf,_=_sen(g["water_year"],g["flash_drop_mm"]) if "flash_drop_mm" in g else (None,None)
        tiles_=[
            _tile(f"{mm*10:+.1f} d/dec" if mm is not None else "—","Melt center-of-timing","","tile-blue"),
            _tile(f"{ms*10:+.1f} d/dec" if ms is not None else "—","Peak-SWE day","","tile-navy"),
            _tile(f"{int(worst['water_year'])}" if worst is not None else "—","Worst flash-drought year"," ","tile-maroon"),
            _tile(f"{mf*10:+.1f} mm/dec" if mf is not None else "—","Flash-drop trend"," ","tile-green"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("tm-melt","figure"), Input("tm-basin","value"))
    def melt(basin):
        d=_load()
        if d.empty: return _empty(_NEED)
        # "All sub-basins" → overlay every sub-basin's melt center-of-timing on one chart
        # (actual day-of-water-year, so basins are directly comparable — no indexing needed).
        if basin == "ALL" and "melt_com_doy" in d.columns:
            from utils.multibasin import BASIN_COLORS, BASIN_LABEL
            order=["Green","UpperColo","SanJuan","GlenCanyon","UpperBasin","LowerColo",
                   "GrandCanyon","LittleColo","Gila","LowerBasin","CRB"]
            fig=go.Figure()
            for b in order:
                gb=d[d["basin"]==b].dropna(subset=["water_year","melt_com_doy"]).sort_values("water_year")
                if gb.empty: continue
                crb=(b=="CRB")
                fig.add_trace(go.Scatter(x=gb["water_year"],y=gb["melt_com_doy"],
                    name=BASIN_LABEL.get(b,b),mode="lines",
                    line=dict(color=BASIN_COLORS.get(b,NAVY),width=3.2 if crb else 1.7,
                              shape="spline",smoothing=0.6),opacity=1.0 if crb else 0.85,
                    hovertemplate=f"{BASIN_LABEL.get(b,b)}<br>WY %{{x}}: melt day %{{y:.0f}}<extra></extra>"))
            fig.update_layout(xaxis_title="Water Year",
                yaxis_title="Melt center-of-timing (day of water year, Oct 1 = 0)",
                legend=dict(orientation="h",y=-0.16,x=0,font=dict(size=9)),
                margin=dict(l=55,r=15,t=10,b=40),height=340,
                paper_bgcolor="white",plot_bgcolor="white",hovermode="closest")
            return fig
        g=d[d["basin"]==basin].dropna(subset=["water_year"]).sort_values("water_year")
        if g.empty: return _empty("No data")
        fig=go.Figure()
        if "melt_com_doy" in g:
            fig.add_trace(go.Scatter(x=g["water_year"],y=g["melt_com_doy"],name="Melt center-of-timing",
                mode="lines+markers",line=dict(color=BLUE,width=2),marker=dict(size=4)))
            m,_=_sen(g["water_year"],g["melt_com_doy"])
            if m is not None:
                xr=np.array([g["water_year"].min(),g["water_year"].max()])
                fig.add_trace(go.Scatter(x=xr,y=m*xr+(g["melt_com_doy"].mean()-m*g["water_year"].mean()),
                    mode="lines",line=dict(color=MAROON,width=2,dash="dot"),name=f"Trend {m*10:+.1f} d/dec"))
        if "peak_swe_doy" in g:
            fig.add_trace(go.Scatter(x=g["water_year"],y=g["peak_swe_doy"],name="Peak-SWE day",
                mode="lines",line=dict(color=NAVY,width=1.5,dash="dash")))
        fig.update_layout(xaxis_title="Water Year",yaxis_title="Day of water year (Oct 1 = 0)",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=60),height=340,paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("tm-flash","figure"), Input("tm-basin","value"))
    def flash(basin):
        if basin=="ALL": basin="CRB"
        d=_load()
        if d.empty: return _empty(_NEED)
        g=d[d["basin"]==basin].dropna(subset=["water_year"]).sort_values("water_year")
        if g.empty or "flash_drop_mm" not in g: return _empty("No data")
        fig=go.Figure(go.Bar(x=g["water_year"],y=g["flash_drop_mm"],marker_color=ORANGE,
            hovertemplate="WY %{x}<br>%{y:.0f} mm 30-day drop<extra></extra>"))
        m,_=_sen(g["water_year"],g["flash_drop_mm"])
        if m is not None:
            xr=np.array([g["water_year"].min(),g["water_year"].max()])
            fig.add_trace(go.Scatter(x=xr,y=m*xr+(g["flash_drop_mm"].mean()-m*g["water_year"].mean()),
                mode="lines",line=dict(color=MAROON,width=2,dash="dot"),name=f"Trend {m*10:+.1f} mm/dec"))
        fig.update_layout(xaxis_title="Water Year",yaxis_title="Max 30-day soil-moisture drop (mm)",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=60),height=340,paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("tm-findings","children"), Input("tm-basin","value"))
    def findings(basin):
        if basin=="ALL": basin="CRB"
        d=_load()
        if d.empty:
            return [html.Strong(" Daily metrics not yet built — "),
                    "run the updated pipeline once (run_all.command) to populate vic_daily_metrics.parquet; ""this page then shows melt timing & flash-drought trends at true daily resolution."]
        g=d[d["basin"]==basin].dropna(subset=["water_year"]).sort_values("water_year")
        if g.empty: return "No data for this basin."
        mm,_=_sen(g["water_year"],g["melt_com_doy"]) if "melt_com_doy" in g else (None,None)
        mf,_=_sen(g["water_year"],g["flash_drop_mm"]) if "flash_drop_mm" in g else (None,None)
        bits=[]
        if mm is not None: bits.append(f"snowmelt center-of-timing shifting {mm*10:+.1f} days/decade ({'earlier' if mm<0 else 'later'})")
        if mf is not None: bits.append(f"flash-drought intensity {mf*10:+.1f} mm/decade")
        return [html.Strong(" Key finding — "),f"{basin_label(basin)}: "+"; ".join(bits)+"."]
