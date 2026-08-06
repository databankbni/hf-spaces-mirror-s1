"""
modules/budyko.py — Budyko Migration: are basins drifting from energy- to water-limited?
Each basin's annual point in Budyko space: x = aridity index PET/P, y = evaporative index ET/P.
Over 1984–2024 the points drift up-and-right toward the water-limited corner = aridification.

PET via the Hamon temperature method (monthly VIC air temperature + basin-centroid latitude).
Verified physically: CRB PET/P ≈ 2.1 (arid), EI < min(1,AI) (Budyko-consistent), AI rising over time.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual, load_vic_monthly, basin_label, trend_ci
from utils.components import howto, pub_star

MAROON="#8C1D40"; NAVY="#0D2137"; BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"
LAT={"SanJuan":36.775,"LowerBasin":34.559,"GlenCanyon":37.964,"GrandCanyon":36.735,
     "UpperBasin":39.095,"Gila":33.119,"UpperColo":38.943,"LowerColo":34.407,
     "CRB":36.658,"Green":40.944,"LittleColo":35.214}
_BK_BASINS=[
    ("CRB","Colorado River Basin"),("UpperBasin","Upper Basin"),("LowerBasin","Lower Basin"),
    ("Green","Green River"),("SanJuan","San Juan"),("UpperColo","Upper Colorado"),
    ("GlenCanyon","Glen Canyon"),("Gila","Gila River"),("GrandCanyon","Grand Canyon"),
    ("LittleColo","Little Colorado"),("LowerColo","Lower Colorado")]
BASIN_OPTIONS=([{"label":"Colorado River Basin","value":"CRB"},
                {"label":"◆ All sub-basins (compare)","value":"ALL"}]
               +[{"label":n,"value":b} for b,n in _BK_BASINS if b!="CRB"])
DIM={1:31,2:28,3:31,4:30,5:31,6:30,7:31,8:31,9:30,10:31,11:30,12:31}

def _safe(fn):
    try: return fn()
    except: return pd.DataFrame()

def _empty(msg="Run preprocessing first"):
    fig=go.Figure()
    fig.add_annotation(text=msg,xref="paper",yref="paper",x=0.5,y=0.5,showarrow=False,
                       font=dict(size=12,color="#90a4ae"))
    fig.update_layout(paper_bgcolor="white",plot_bgcolor="white",xaxis=dict(visible=False),
                      yaxis=dict(visible=False),margin=dict(l=20,r=20,t=30,b=20),height=300)
    return fig

def _tile(val,label,icon,color):
    return html.Div([html.Div(str(val),className="info-tile-value"),
        html.Div(label,className="info-tile-label"),
        html.Div(icon,className="info-tile-icon")],className=f"info-tile {color}")

def _hamon(Tc, latd, month):
    phi=np.radians(latd); J=int(month*30.4-15); dec=0.409*np.sin(2*np.pi/365*J-1.39)
    ws=np.arccos(np.clip(-np.tan(phi)*np.tan(dec),-1,1)); N=24/np.pi*ws
    es=6.108*np.exp(17.27*Tc/(Tc+237.3)); rho=216.7*es/(Tc+273.3)
    return max(0.1651*(N/12)*rho,0.0)

def _budyko_df(basin):
    if basin=="ALL": basin="CRB"   # non-overlay panels show whole-basin context
    mon=_safe(load_vic_monthly); ann=_safe(load_vic_annual)
    if mon.empty or ann.empty or basin not in LAT: return pd.DataFrame()
    m=mon[mon["basin"]==basin].copy()
    if m.empty or "OUT_AIR_TEMP" not in m.columns: return pd.DataFrame()
    m["pet"]=[_hamon(t,LAT[basin],mo)*DIM[mo] for t,mo in zip(m["OUT_AIR_TEMP"],m["month"])]
    pet=m.groupby("year")["pet"].sum()
    a=ann[ann["basin"]==basin].set_index("water_year")
    yrs=sorted(set(pet.index)&set(a.index))
    if not yrs: return pd.DataFrame()
    d=pd.DataFrame({"year":yrs})
    d["PET"]=pet.loc[yrs].values; d["P"]=a.loc[yrs,"OUT_PREC"].values; d["ET"]=a.loc[yrs,"OUT_EVAP"].values
    d["AI"]=d["PET"]/d["P"]; d["EI"]=d["ET"]/d["P"]
    return d

def _budyko_curve(ai):  # Fu (1981) with w=2.6
    w=2.6
    return 1+ai-(1+ai**w)**(1/w)


def layout():
    return html.Div([
        html.Div([
            html.H2("Budyko Water–Energy Balance"),
            html.P("Watch a basin drift toward the water-limited corner as it aridifies. Pick a basin."),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="bk-tiles",className="mb-3 g-2"),
            html.Div(id="bk-findings",
                     style={"background":"#ede7f6","borderLeft":f"3px solid #4527A0",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#4527A0","marginBottom":"12px"}),
                            howto("Pick a basin. Its position in Budyko space shows the balance between water and energy limits; drift up-and-right over time signals aridification."),
            html.Div([dbc.Row([dbc.Col([
                html.Div("Basin",className="control-label"),
                dcc.Dropdown(id="bk-basin",options=BASIN_OPTIONS,value="CRB",clearable=False,
                             style={"fontSize":"12.5px"}),
            ],md=5)])],className="control-panel"),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("Budyko diagram",style={"fontWeight":"700","fontSize":"13px"}), pub_star("https://www.nature.com/articles/s43247-025-03136-w", "Runoff efficiency in the Upper Colorado, Commun. Earth Environ. (2025)"),
                            html.Span("— each point = one water year; arrow = 1984–2003 2004–2024 drift",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                            dbc.Button("CSV",id="bk-dl-btn",size="sm",className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="bk-diagram",config={"displayModeBar":False},style={"height":"380px"}),
                        dcc.Download(id="bk-dl-data"),
                    ],className="crb-card"),
                ],md=7),
                dbc.Col([
                    html.Div([
                        html.Div([html.Span(" Aridity index over time",style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— PET/P trend",style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="bk-ai",config={"displayModeBar":False},style={"height":"380px"}),
                    ],className="crb-card"),
                ],md=5),
            ],className="g-3"),
            html.Div("Aridity index AI = PET/P (PET via Hamon temperature method, basin-centroid latitude); ""evaporative index EI = ET/P. Curve = Fu (1981), w=2.6. Up-and-right drift = ""aridification (less of each storm becomes runoff).",
                     style={"fontSize":"10.5px","color":"#1e293b","marginTop":"6px"}),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("bk-tiles","children"), Input("bk-basin","value"))
    def tiles(basin):
        labels=["Aridity now","Aridity then","Drift","Status"]
        d=_budyko_df(basin)
        if d.empty:
            return [dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3) for l in labels]
        early=d[d["year"]<2004]; late=d[d["year"]>=2004]
        ai_e=early["AI"].mean(); ai_l=late["AI"].mean()
        ei_e=early["EI"].mean(); ei_l=late["EI"].mean()
        drift=np.hypot(ai_l-ai_e, ei_l-ei_e)
        status="More water-limited" if ai_l>ai_e else "Stable"
        tiles_=[
            _tile(f"{ai_l:.2f}","Aridity PET/P (2004–24)","","tile-maroon"),
            _tile(f"{ai_e:.2f}","Aridity PET/P (1984–2003)"," ","tile-blue"),
            _tile(f"+{ai_l-ai_e:.2f}","Δ aridity index","","tile-navy"),
            _tile(status,"Budyko regime shift"," ","tile-green"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("bk-diagram","figure"), Input("bk-basin","value"))
    def diagram(basin):
        d=_budyko_df(basin)
        if d.empty: return _empty("No data")
        fig=go.Figure()
        # Budyko / physical limits
        xmax=max(3.5, d["AI"].max()*1.1); xs=np.linspace(0.01,xmax,100)
        fig.add_trace(go.Scatter(x=xs,y=_budyko_curve(xs),mode="lines",
            line=dict(color="#90a4ae",width=2,dash="dash"),name="Budyko (Fu) curve"))
        fig.add_trace(go.Scatter(x=[0,1,xmax],y=[0,1,1],mode="lines",
            line=dict(color="#cfd8dc",width=1),name="Energy / water limits",hoverinfo="skip"))
        # yearly points colored by year
        fig.add_trace(go.Scatter(x=d["AI"],y=d["EI"],mode="markers",
            marker=dict(size=8,color=d["year"],colorscale="YlOrRd",showscale=True,
                        colorbar=dict(title="WY",thickness=10),line=dict(color="white",width=0.5)),
            text=d["year"],hovertemplate="WY %{text}<br>PET/P %{x:.2f}<br>ET/P %{y:.2f}<extra></extra>",
            name="Water year"))
        # early -> late centroid arrow
        e=d[d["year"]<2004]; l=d[d["year"]>=2004]
        if len(e) and len(l):
            fig.add_trace(go.Scatter(x=[e["AI"].mean()],y=[e["EI"].mean()],mode="markers",
                marker=dict(size=15,color=BLUE,symbol="circle",line=dict(color="white",width=2)),
                name="1984–2003 mean"))
            fig.add_trace(go.Scatter(x=[l["AI"].mean()],y=[l["EI"].mean()],mode="markers",
                marker=dict(size=15,color=MAROON,symbol="circle",line=dict(color="white",width=2)),
                name="2004–2024 mean"))
            fig.add_annotation(x=l["AI"].mean(),y=l["EI"].mean(),ax=e["AI"].mean(),ay=e["EI"].mean(),
                xref="x",yref="y",axref="x",ayref="y",showarrow=True,arrowhead=3,
                arrowwidth=2,arrowcolor=MAROON)
        fig.update_layout(xaxis_title="Aridity index  PET / P  (drier )",
            yaxis_title="Evaporative index  ET / P",
            yaxis=dict(range=[0,1.15]),xaxis=dict(range=[0,xmax]),
            legend=dict(font=dict(size=9),orientation="h",y=-0.22,x=0),
            margin=dict(l=55,r=15,t=10,b=70),height=380,
            paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("bk-ai","figure"), Input("bk-basin","value"))
    def ai_ts(basin):
        # "All sub-basins" → overlay every sub-basin's aridity index (PET/P) on one chart
        # (actual index values, directly comparable across basins).
        if basin == "ALL":
            from utils.multibasin import BASIN_COLORS, BASIN_LABEL
            order=["Green","UpperColo","SanJuan","GlenCanyon","UpperBasin","LowerColo",
                   "GrandCanyon","LittleColo","Gila","LowerBasin","CRB"]
            fig=go.Figure()
            for b in order:
                db=_budyko_df(b)
                if db.empty: continue
                crb=(b=="CRB")
                fig.add_trace(go.Scatter(x=db["year"],y=db["AI"],name=BASIN_LABEL.get(b,b),
                    mode="lines",line=dict(color=BASIN_COLORS.get(b,NAVY),
                        width=3.2 if crb else 1.7,shape="spline",smoothing=0.6),
                    opacity=1.0 if crb else 0.85,
                    hovertemplate=f"{BASIN_LABEL.get(b,b)}<br>WY %{{x}}: PET/P %{{y:.2f}}<extra></extra>"))
            fig.update_layout(xaxis_title="Water Year",yaxis_title="Aridity index PET/P",
                legend=dict(orientation="h",y=-0.16,x=0,font=dict(size=9)),
                margin=dict(l=50,r=15,t=10,b=40),height=380,
                paper_bgcolor="white",plot_bgcolor="white",hovermode="closest")
            return fig
        d=_budyko_df(basin)
        if d.empty: return _empty("No data")
        m,b=np.polyfit(d["year"],d["AI"],1)
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=d["year"],y=d["AI"],mode="lines+markers",
            line=dict(color=MAROON,width=1.8,shape="spline",smoothing=0.4),
            marker=dict(size=4),name="PET/P",
            hovertemplate="WY %{x}<br>PET/P %{y:.2f}<extra></extra>"))
        _tci=trend_ci(d["AI"],d["year"])
        _ci=(f" · 95% CI [{_tci['lo']*10:+.2f}, {_tci['hi']*10:+.2f}]"
             if _tci.get("lo") is not None else "")
        fig.add_trace(go.Scatter(x=d["year"],y=m*d["year"]+b,mode="lines",
            line=dict(color=NAVY,width=2,dash="dot"),name=f"Trend {m*10:+.2f}/decade{_ci}"))
        fig.update_layout(xaxis_title="Water Year",yaxis_title="Aridity index PET/P",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=50,r=15,t=10,b=60),height=380,
            paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("bk-findings","children"), Input("bk-basin","value"))
    def findings(basin):
        d=_budyko_df(basin)
        if d.empty: return " Findings will appear after preprocessing is complete."
        e=d[d["year"]<2004]; l=d[d["year"]>=2004]
        ai_e,ai_l=e["AI"].mean(),l["AI"].mean()
        m,_=np.polyfit(d["year"],d["AI"],1)
        return [html.Strong("Key finding — "),
                f"{basin_label(basin)} aridity index (PET/P) rose from {ai_e:.2f} (1984–2003) to "
                f"{ai_l:.2f} (2004–2024), trending {m*10:+.2f}/decade — the basin is drifting toward the "
                f"water-limited corner of Budyko space, the geometric signature of aridification."]

    @app.callback(Output("bk-dl-data","data"),Input("bk-dl-btn","n_clicks"),
                  Input("bk-basin","value"),prevent_initial_call=True)
    def download(n,basin):
        if not n: return None
        d=_budyko_df(basin)
        if d.empty: return None
        d=d.assign(basin=basin)
        return dcc.send_data_frame(d.to_csv,f"crb_budyko_{basin}.csv",index=False)
