"""
modules/drought.py — Module 4: Drought & Shortage Risk
Charts:
  1. VIC basin runoff vs user-defined shortage threshold
  2. P(shortage) — rolling 10-yr exceedance probability
  3. Soil moisture deficit index (z-score of VIC annual soil moisture)
  4. GRACE TWS anomaly with drought flags
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual, load_grace, basin_label, trend_slope, trend_ci
from utils.components import xref, pub_evidence, pub_star, pub_author, howto, info_dot

MAROON="#8C1D40"; NAVY="#0D2137"; GOLD="#FFC627"
BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; RED="#B71C1C"
BASIN_OPTIONS=[
    {"label":"Colorado River Basin","value":"CRB"},
    {"label":"Upper Basin","value":"UpperBasin"},
    {"label":"Lower Basin","value":"LowerBasin"},
    {"label":"Green River","value":"Green"},
    {"label":"San Juan","value":"SanJuan"},
    {"label":"Grand Canyon","value":"GrandCanyon"},
    {"label":"Gila River","value":"Gila"},
]

def _safe(fn):
    try: return fn()
    except: return pd.DataFrame()

def _empty(msg="Run preprocessing scripts first"):
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

def _detect_droughts(series, threshold_pct=20):
    """Flag years where value < threshold_pct of median as drought years."""
    med = series.median()
    thresh = med * (1 - threshold_pct/100)
    return series < thresh


def layout():
    return html.Div([
        html.Div([
            html.H2(" Drought & Shortage Risk"),
            html.P("VIC basin runoff vs user-defined shortage threshold · P(shortage) by decade · Drought event catalogue · Soil moisture deficit index"),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="dr-tiles",className="mb-3 g-2"),
            html.Div(id="dr-findings",
                     style={"background":"#fff3e0","borderLeft":f"3px solid {ORANGE}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#bf360c","marginBottom":"12px"}),
                            howto("Pick a basin, year range and shortage threshold. The charts show how often flow falls below that threshold — higher bars mean more frequent shortage years."),
                            pub_author("Williams 2022; Udall & Overpeck 2017", "https://www.nature.com/articles/s41558-022-01290-z", "Williams et al. 2022 Nat. Clim. Change; Udall & Overpeck 2017 WRR", "published"),
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("Basin",className="control-label"),
                        dcc.Dropdown(id="dr-basin",options=BASIN_OPTIONS,
                                     value="CRB",clearable=False,
                                     style={"fontSize":"12.5px"}),
                    ],md=3),
                    dbc.Col([
                        html.Div("Year Range",className="control-label"),
                        dcc.RangeSlider(id="dr-years",min=1983,max=2024,step=1,
                                        value=[1983,2024],
                                        marks={y:str(y) for y in range(1990,2025,10)},
                                        tooltip={"placement":"bottom","always_visible":False}),
                    ],md=5),
                    dbc.Col([
                        html.Div([html.Span("Shortage Threshold (% of median)",className="control-label"),
                                  info_dot("A 'shortage year' is one where annual streamflow falls more than this "
                                           "percentage below the long-term median. Lower threshold = stricter "
                                           "definition. Use it to gauge how often your basin would fall short.")],
                                 style={"display":"flex","alignItems":"center"}),
                        dcc.Slider(id="dr-thresh",min=5,max=40,step=5,value=20,
                                   marks={v:f"{v}%" for v in [5,10,20,30,40]},
                                   tooltip={"placement":"bottom","always_visible":True}),
                    ],md=4),
                ]),
            ],className="control-panel"),

            # Row 1: runoff vs threshold + exceedance probability
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Annual Runoff vs Shortage Threshold",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            dbc.Button("CSV",id="dr-dl-btn",size="sm",
                                       className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                            pub_star("https://www.nature.com/articles/s41558-022-01290-z", "Williams et al. 2022, Nat. Clim. Change 12:232", "Published"),
                        ],className="crb-card-header"),
                        dcc.Graph(id="dr-runoff-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"310px"}),
                        dcc.Download(id="dr-dl-data"),
                    ],className="crb-card"),
                ],md=12),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("P(Shortage) — 10-yr Rolling",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— fraction of years below threshold",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="dr-prob-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"310px"}),
                        html.Div("Note: Rolling window (10-yr, centered): NaN at edges ±5 yrs",
                                 style={"fontSize":"10px","color":"#78909c","padding":"0 6px 6px"}),
                    ],className="crb-card"),
                ],md=12),
            ],className="g-3 mb-2"),

            # Row 2: drought index + GRACE drought
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Soil Moisture Deficit Index",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— z-score of VIC annual soil moisture (not PDSI)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="dr-index-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"300px"}),
                    ],className="crb-card"),
                ],md=12),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("GRACE Drought Signal",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— TWS anomaly with drought flags",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="dr-grace-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"300px"}),
                    ],className="crb-card"),
                ],md=12),
            ],className="g-3"),

            # Row 3: Compound risk
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Compound Water System Risk",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— combined VIC runoff deficit + GRACE TWS deficit index",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="dr-compound-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"280px"}),
                        html.Div("Note: positive values = drier than normal "
                                 "(combined VIC runoff + GRACE z-score).",
                                 style={"fontSize":"10px","color":"#78909c","padding":"0 6px 6px"}),
                    ],className="crb-card"),
                ],md=12),
            ],className="g-3 mb-2"),

            xref("Related:", [("Dedicated storage analysis → Water Storage", "/tws")]),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("dr-tiles","children"),
                  Input("dr-basin","value"), Input("dr-thresh","value"))
    def tiles(basin, thresh):
        df=_safe(load_vic_annual)
        if df.empty:
            return [dbc.Col(_tile("—",l,"","tile-navy"),xs=6,md=3)
                    for l in ["Drought years","P(shortage)","Worst year","Trend"]]
        b=df[df["basin"]==basin].copy()
        if b.empty:
            return [dbc.Col(_tile("—",l,"","tile-navy"),xs=6,md=3)
                    for l in ["Drought years","P(shortage)","Worst year","Trend"]]
        q=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
        drought=_detect_droughts(q, thresh)
        n_dr=drought.sum()
        p_sh=drought.mean()*100
        worst_yr=b.loc[q.idxmin(),"water_year"] if not q.empty else "—"
        t=trend_slope(q, b["water_year"])
        trend_str=(f"{t['slope']:+.1f} mm/yr" if t["slope"] else "—")
        tiles_=[
            _tile(n_dr,           f"Drought years (>{thresh}% below median)","","tile-maroon"),
            _tile(f"{p_sh:.0f}%", "P(shortage) historical",                  " ","tile-orange"),
            _tile(worst_yr,       "Lowest runoff year",                       " ","tile-navy"),
            _tile(trend_str,      "Runoff trend",                             " ","tile-blue"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("dr-runoff-chart","figure"),
                  Input("dr-basin","value"),
                  Input("dr-years","value"),
                  Input("dr-thresh","value"))
    def runoff_chart(basin, years, thresh):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&
             (df["water_year"]<=years[1])].copy().sort_values("water_year")
        if b.empty: return _empty("No data")
        q=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
        med=q.median()
        t_line=med*(1-thresh/100)
        colors=[RED if v<t_line else BLUE for v in q]
        fig=go.Figure()
        fig.add_hrect(y0=0,y1=t_line,fillcolor="rgba(183,28,28,0.08)",line_width=0)
        # threshold label in the top-left corner with a solid backing (never overlaps the bars)
        fig.add_annotation(text=f"Shortage threshold ({thresh}% below median)",
                           xref="paper",yref="paper",x=0.01,y=1.06,xanchor="left",yanchor="bottom",
                           showarrow=False,font=dict(size=10,color=RED),
                           bgcolor="rgba(255,255,255,0.9)",borderpad=2)
        fig.add_hline(y=med,line_dash="dash",line_color="#90a4ae",line_width=1.5,
                      annotation_text="Median",annotation_position="right")
        fig.add_trace(go.Bar(x=b["water_year"],y=q,marker_color=colors,
                             marker_line_width=0,
                             hovertemplate="<b>WY %{x}</b><br>Q: %{y:.0f} mm<extra></extra>"))
        t=trend_ci(q,b["water_year"])
        if t["slope"] is not None:
            xr_=np.array([b["water_year"].min(),b["water_year"].max()])
            yf =t["slope"]*xr_+(q.mean()-t["slope"]*b["water_year"].mean())
            fig.add_trace(go.Scatter(x=xr_,y=yf,mode="lines",
                line=dict(color=NAVY,width=2,dash="dot"),
                name=(f"Trend {t['slope']:+.1f} mm/yr"
                      + (f" · 95% CI [{t['lo']:+.1f}, {t['hi']:+.1f}]"
                         if t.get('lo') is not None else ""))))
        fig.update_layout(
            xaxis_title="Water Year",yaxis_title="VIC runoff (mm/yr)",
            legend=dict(orientation="h",y=-0.30,x=0,font=dict(size=10)),
            margin=dict(l=52,r=72,t=34,b=78),height=340,
            paper_bgcolor="white",plot_bgcolor="white",bargap=0.15,
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("dr-prob-chart","figure"),
                  Input("dr-basin","value"),
                  Input("dr-years","value"),
                  Input("dr-thresh","value"))
    def prob_chart(basin, years, thresh):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&
             (df["water_year"]<=years[1])].copy().sort_values("water_year")
        if len(b)<10: return _empty("Need ≥10 years of data")
        q=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
        med=q.median(); t_line=med*(1-thresh/100)
        below=(q<t_line).astype(float)
        roll10=below.rolling(10,center=True).mean()*100
        b["prob"]=roll10.values
        fig=go.Figure()
        fig.add_hrect(y0=30,y1=100,fillcolor="rgba(183,28,28,0.06)",line_width=0)
        fig.add_hline(y=30,line_dash="dash",line_color=RED,line_width=1.5,
                      annotation_text="High risk (30%)",annotation_position="right",
                      annotation_font=dict(size=10,color=RED))
        fig.add_trace(go.Scatter(
            x=b["water_year"],y=b["prob"],mode="lines",
            fill="tozeroy",fillcolor="rgba(140,29,64,0.2)",
            line=dict(color=MAROON,width=2.5),
            name="P(shortage) 10-yr",
            hovertemplate="WY %{x}<br>P(shortage): %{y:.0f}%<extra></extra>"))
        fig.update_layout(
            xaxis_title="Water Year",yaxis_title="P(shortage) %",
            yaxis=dict(range=[0,100]),
            margin=dict(l=55,r=72,t=10,b=40),height=310,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("dr-index-chart","figure"),
                  Input("dr-basin","value"),
                  Input("dr-years","value"))
    def index_chart(basin, years):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&
             (df["water_year"]<=years[1])].copy().sort_values("water_year")
        if b.empty or "OUT_SOIL_MOIST" not in b.columns: return _empty("No soil moisture data")
        # Standardised SM anomaly (z-score) as PDSI-proxy
        sm=b["OUT_SOIL_MOIST"]
        z=(sm-sm.mean())/sm.std()
        colors=[RED if v<-1 else ORANGE if v<0 else GREEN for v in z]
        fig=go.Figure()
        fig.add_hline(y=0,line_dash="dash",line_color="#b0bec5",line_width=1)
        fig.add_hrect(y0=-2,y1=-1,fillcolor="rgba(183,28,28,0.08)",line_width=0,
                      annotation_text="Severe drought",annotation_position="top left",
                      annotation_font=dict(size=9,color=RED))
        fig.add_trace(go.Bar(x=b["water_year"],y=z,marker_color=colors,
                             marker_line_width=0,
                             hovertemplate="<b>WY %{x}</b><br>SM z-score: %{y:.2f}<extra></extra>"))
        b["r3"]=z.rolling(3,center=True).mean()
        fig.add_trace(go.Scatter(x=b["water_year"],y=b["r3"],mode="lines",
            line=dict(color=NAVY,width=2),name="3-yr mean"))
        fig.update_layout(
            xaxis_title="Water Year",yaxis_title="Soil Moisture Z-score",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=60),height=300,
            paper_bgcolor="white",plot_bgcolor="white",bargap=0.15,
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("dr-grace-chart","figure"),Input("dr-basin","value"))
    def grace_chart(basin):
        df=_safe(load_grace)
        if df.empty: return _empty("Run 02_snotel_grace_cache.py first")
        b=df[df["basin"]==basin].dropna(subset=["tws_mm"]).sort_values("date").copy()
        if b.empty: return _empty("No GRACE data")
        b["roll12"]=b["tws_mm"].rolling(12,center=True).mean()
        drought_flag=b["roll12"]<-20  # below -20mm = significant deficit
        fig=go.Figure()
        fig.add_hline(y=0,line_dash="dash",line_color="#b0bec5",line_width=1)
        fig.add_hline(y=-20,line_dash="dot",line_color=RED,line_width=1.5,
                      annotation_text="Deficit threshold",annotation_position="right",
                      annotation_font=dict(size=9,color=RED))
        colors=[RED if v<-20 else MAROON if v<0 else BLUE for v in b["tws_mm"]]
        fig.add_trace(go.Bar(x=b["date"],y=b["tws_mm"],marker_color=colors,
                             marker_line_width=0,opacity=0.5,name="Monthly TWS",
                             hovertemplate="%{x|%b %Y}<br>TWS: %{y:.1f} mm<extra></extra>"))
        fig.add_trace(go.Scatter(x=b["date"],y=b["roll12"],mode="lines",
            line=dict(color=NAVY,width=2.5),name="12-mo mean"))
        fig.update_layout(
            xaxis_title="Date",yaxis_title="TWS Anomaly (mm)",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=78,t=10,b=60),height=300,
            paper_bgcolor="white",plot_bgcolor="white",bargap=0.1,
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("dr-compound-chart","figure"),
                  Input("dr-basin","value"), Input("dr-thresh","value"))
    def compound_chart(basin, thresh):
        df_v=_safe(load_vic_annual); df_g=_safe(load_grace)
        if df_v.empty: return _empty()
        bv=df_v[df_v["basin"]==basin].copy().sort_values("water_year")
        if bv.empty: return _empty("No VIC data")
        q=bv["OUT_RUNOFF"]+bv["OUT_BASEFLOW"]
        med=q.median()
        # VIC runoff deficit z-score (negative = below median)
        q_z=(q-q.mean())/q.std()
        # GRACE annual mean anomaly (matched by year if available)
        grace_z=pd.Series(np.nan,index=bv.index)
        if not df_g.empty:
            bg=df_g[df_g["basin"]==basin].dropna(subset=["tws_mm"]).copy()
            if not bg.empty:
                bg["year"]=(pd.to_datetime(bg["date"]).dt.year.where(
                    pd.to_datetime(bg["date"]).dt.month<10,
                    pd.to_datetime(bg["date"]).dt.year+1))  # water year
                grace_ann=bg.groupby("year")["tws_mm"].mean()
                grace_ann_z=(grace_ann-grace_ann.mean())/grace_ann.std()
                # Map to bv index by water_year
                for i,row in bv.iterrows():
                    wy=row["water_year"]
                    if wy in grace_ann_z.index:
                        grace_z.loc[i]=grace_ann_z[wy]
        # Compound index: mean of both z-scores (higher = more stress; invert so negative=bad)
        has_grace=grace_z.notna()
        compound=pd.Series(np.nan,index=bv.index)
        compound[has_grace]=-(q_z[has_grace]+grace_z[has_grace])/2
        compound[~has_grace]=-q_z[~has_grace]
        # Risk bands
        fig=go.Figure()
        fig.add_hrect(y0=1.5,y1=4,fillcolor="rgba(183,28,28,0.08)",line_width=0,
                      annotation_text="Extreme risk",annotation_position="top left",
                      annotation_font=dict(size=9,color=RED))
        fig.add_hrect(y0=0.5,y1=1.5,fillcolor="rgba(230,81,0,0.06)",line_width=0)
        fig.add_hline(y=0,line_dash="dash",line_color="#b0bec5",line_width=1)
        fig.add_hline(y=0.5,line_dash="dot",line_color=ORANGE,line_width=1.2,
                      annotation_text="Moderate risk",annotation_position="right",
                      annotation_font=dict(size=9,color=ORANGE))
        fig.add_hline(y=1.5,line_dash="dot",line_color=RED,line_width=1.2)
        colors=[RED if v>1.5 else ORANGE if v>0.5 else BLUE for v in compound.fillna(0)]
        fig.add_trace(go.Bar(x=bv["water_year"],y=compound,
                             marker_color=colors,marker_line_width=0,
                             hovertemplate="<b>WY %{x}</b><br>Risk index: %{y:.2f}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=bv["water_year"],y=compound.rolling(5,center=True).mean(),
            mode="lines",line=dict(color=NAVY,width=2.5),name="5-yr mean"))
        fig.update_layout(
            xaxis_title="Water Year",yaxis_title="Compound Risk Index",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=78,t=10,b=60),height=280,
            paper_bgcolor="white",plot_bgcolor="white",bargap=0.15,
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("dr-findings","children"),
                  Input("dr-basin","value"),
                  Input("dr-years","value"),
                  Input("dr-thresh","value"))
    def findings(basin,years,thresh):
        df=_safe(load_vic_annual)
        if df.empty: return " Key findings will appear after preprocessing is complete."
        b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&
             (df["water_year"]<=years[1])].copy()
        if b.empty: return "No data for selected range."
        q=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
        med=q.median(); t_line=med*(1-thresh/100)
        drought=q<t_line
        n_dr=drought.sum(); p_sh=drought.mean()*100
        consec=0; max_consec=0; cur=0
        for v in drought:
            if v: cur+=1; max_consec=max(max_consec,cur)
            else: cur=0
        t=trend_ci(q,b["water_year"])
        trend_str=(f"Runoff trend: {t['slope']:+.1f} mm/yr "
        f"(95% CI [{t['lo']:+.1f}, {t['hi']:+.1f}]; "
        f"{'p<0.05' if t['pvalue']<0.05 else 'not significant'})."
        if t["slope"] is not None else "")
        from utils.manager import to_maf, manager_line
        med_maf=to_maf(med,basin); dr_maf=to_maf(t_line,basin)
        mgr=manager_line(
            f"{basin_label(basin)} hit a drought year {p_sh:.0f}% of the time "
            f"({years[0]}–{years[1]}), with up to {max_consec} dry years in a row. "
            f"A drought year here means basin runoff below ~{dr_maf:.1f} MAF "
            f"(vs a typical {med_maf:.1f} MAF). Longer/clustered dry runs are what draw reservoirs "
            "toward shortage tiers.",
            color="#B71C1C")
        return [mgr, html.Strong("Detail — "),
                f"{basin_label(basin)}: {n_dr} drought years ({p_sh:.0f}%) "
                f"in {years[0]}–{years[1]}. "
                f"Longest consecutive drought: {max_consec} years. {trend_str}"]

    @app.callback(Output("dr-dl-data","data"),Input("dr-dl-btn","n_clicks"),
                  Input("dr-basin","value"),prevent_initial_call=True)
    def download(n,basin):
        if not n: return None
        df=_safe(load_vic_annual)
        if df.empty: return None
        b=df[df["basin"]==basin].copy()
        b["total_runoff"]=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
        return dcc.send_data_frame(b[["water_year","basin","total_runoff","OUT_SOIL_MOIST"]].to_csv,
                                   "crb_drought_risk.csv",index=False)
