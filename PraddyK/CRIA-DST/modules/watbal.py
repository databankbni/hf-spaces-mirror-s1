"""
modules/watbal.py — Module 2: Water Balance Explorer
Charts:
  1. Stacked area: P ET + Q + ΔSoil  (annual, by basin)
  2. Runoff ratio (Q/P) trend over time
  3. ET partitioning: canopy + transpiration + bare-soil evap (stacked area)
  4. Basin comparison lollipop (any variable, latest decade mean)
  5. Sankey: P components (single-year or mean)
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual, load_vic_monthly, basin_label, trend_slope, trend_ci
from utils.components import howto
from utils.charts import lollipop_h, dot_h, violin_v

MAROON="#8C1D40"; NAVY="#0D2137"; NAVY2="#1a3a5c"; GOLD="#FFC627"
BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; PURPLE="#4527A0"
BASIN_OPTIONS=[
    {"label":"Colorado River Basin","value":"CRB"},
    {"label":"◆ All sub-basins (compare)","value":"ALL"},
    {"label":"Upper Basin","value":"UpperBasin"},
    {"label":"Lower Basin","value":"LowerBasin"},
    {"label":"Green River","value":"Green"},
    {"label":"San Juan","value":"SanJuan"},
    {"label":"Grand Canyon","value":"GrandCanyon"},
    {"label":"Gila River","value":"Gila"},
]
VAR_OPTIONS=[
    {"label":"Precipitation (mm/yr)","value":"OUT_PREC"},
    {"label":"Total ET (mm/yr)","value":"OUT_EVAP"},
    {"label":"Surface Runoff (mm/yr)","value":"OUT_RUNOFF"},
    {"label":"Baseflow (mm/yr)","value":"OUT_BASEFLOW"},
    {"label":"Runoff Efficiency, RBFE (%)","value":"RBFE"},
    {"label":"SWE (mm)","value":"OUT_SWE"},
    {"label":"Soil Moisture, total (mm)","value":"OUT_SOIL_MOIST"},
    {"label":"Soil Moisture L1, 0–10 cm (mm)","value":"OUT_SOIL_MOIST_L1"},
    {"label":"Soil Moisture L2, 10–40 cm (mm)","value":"OUT_SOIL_MOIST_L2"},
    {"label":"Soil Moisture L3, 40–200 cm (mm)","value":"OUT_SOIL_MOIST_L3"},
    {"label":"Air Temperature (°C)","value":"OUT_AIR_TEMP"},
]
BASIN_COLORS={
    "CRB":NAVY,"UpperBasin":BLUE,"LowerBasin":MAROON,
    "Green":GREEN,"SanJuan":ORANGE,"GrandCanyon":PURPLE,"Gila":"#00695C",
}

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


def layout():
    return html.Div([
        html.Div([
            html.H2("Water Balance Explorer"),
            html.P("P ET + Q + ΔS partitioning · Runoff ratio trends · Basin comparison · ET components"),
        ],className="tab-header"),
        html.Div([
            # Tiles
            dbc.Row(id="wb-tiles",className="mb-3 g-2"),
            html.Div(id="wb-findings",
                     style={"background":"#e3f2fd","borderLeft":f"3px solid {BLUE}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#1565c0","marginBottom":"12px"}),
                            howto("Pick a basin. The water balance shows where precipitation goes (runoff, ET, storage); a falling runoff ratio means less of each storm reaches the river."),

            # Controls
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("Basin",className="control-label"),
                        dcc.Dropdown(id="wb-basin",options=BASIN_OPTIONS,
                                     value="CRB",clearable=False,
                                     style={"fontSize":"12.5px"}),
                    ],md=3),
                    dbc.Col([
                        html.Div("Year Range",className="control-label"),
                        dcc.RangeSlider(id="wb-years",min=1983,max=2024,step=1,
                                        value=[1983,2024],
                                        marks={y:str(y) for y in range(1990,2025,10)},
                                        tooltip={"placement":"bottom","always_visible":False}),
                    ],md=5),
                    dbc.Col([
                        html.Div("Compare Variable (Basin Chart)",className="control-label"),
                        dcc.Dropdown(id="wb-compare-var",options=VAR_OPTIONS,
                                     value="OUT_RUNOFF",clearable=False,
                                     style={"fontSize":"12.5px"}),
                    ],md=4),
                ]),
            ],className="control-panel"),

            # Row 1: stacked area + runoff ratio
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Annual Water Balance",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— P = ET + Q + ΔSoil",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                            dbc.Button("CSV",id="wb-dl-btn",size="sm",
                                       className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="wb-stack-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"310px"}),
                        dcc.Download(id="wb-dl-data"),
                    ],className="crb-card"),
                ],md=7),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Runoff Ratio (Q/P)",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— efficiency trend",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="wb-rr-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"310px"}),
                    ],className="crb-card"),
                ],md=5),
            ],className="g-3 mb-2"),

            # Row 2: ET partition + basin comparison
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("ET Partitioning",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— canopy + transpiration + bare soil",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="wb-et-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"310px"}),
                    ],className="crb-card"),
                ],md=6),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span(" Basin Comparison",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— latest decade mean",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="wb-basin-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"310px"}),
                    ],className="crb-card"),
                ],md=6),
            ],className="g-3"),

            # Row 3: Sankey + Aridity Index
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Water Balance Sankey",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— P ET + Q + ΔStorage (mean over selected period)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="wb-sankey-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"320px"}),
                    ],className="crb-card"),
                ],md=7),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span(" Dryness Ratio by Basin",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— ET/P (Budyko aridity proxy)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="wb-aridity-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"320px"}),
                    ],className="crb-card"),
                ],md=5),
            ],className="g-3 mb-2"),

        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("wb-tiles","children"),Input("wb-basin","value"))
    def tiles(basin):
        if basin=="ALL": basin="CRB"   # other panels show whole-basin context
        df=_safe(load_vic_annual)
        if df.empty:
            return [dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3)
                    for l in ["Mean P (mm/yr)","Mean ET (mm/yr)","Mean Q (mm/yr)","Runoff Ratio"]]
        b=df[df["basin"]==basin]
        if b.empty:
            return [dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3)
                    for l in ["Mean P","Mean ET","Mean Q","Runoff Ratio"]]
        p  = b["OUT_PREC"].mean()
        et = b["OUT_EVAP"].mean()
        q  = (b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]).mean()
        rr = q/p if p>0 else 0
        # recent vs early runoff ratio trend
        b_s = b.sort_values("water_year")
        rr_s = (b_s["OUT_RUNOFF"]+b_s["OUT_BASEFLOW"])/b_s["OUT_PREC"]
        t = trend_ci(rr_s, b_s["water_year"])
        rr_trend = (f"{t['slope']*10:+.3f}/dec{' (sig.)' if t['sig'] else ''}"
                    if t["slope"] is not None else "—")
        tiles_=[
            _tile(f"{p:.0f}",   "Mean P (mm/yr)",   "","tile-navy"),
            _tile(f"{et:.0f}",  "Mean ET (mm/yr)",  " ","tile-green"),
            _tile(f"{q:.0f}",   "Mean Q (mm/yr)",   " ","tile-blue"),
            _tile(f"{rr:.2f}",  f"Runoff ratio · trend {rr_trend}"," ","tile-maroon"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("wb-stack-chart","figure"),
                  Input("wb-basin","value"), Input("wb-years","value"))
    def stack_chart(basin, years):
        if basin=="ALL": basin="CRB"
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&(df["water_year"]<=years[1])]
        if b.empty: return _empty("No data")
        b=b.sort_values("water_year")
        # total Q = surface + baseflow
        b=b.copy(); b["OUT_Q"]=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
        # ΔSoil ≈ P - ET - Q (residual)
        b["DELTA_S"]=b["OUT_PREC"]-b["OUT_EVAP"]-b["OUT_Q"]
        fig=go.Figure()
        # Stacked area: ET (green) + Q (blue) + ΔS (orange, can be negative)
        fig.add_trace(go.Scatter(
            x=b["water_year"],y=b["OUT_EVAP"],name="ET",
            mode="lines",fill="tozeroy",fillcolor="rgba(46,125,50,0.35)",
            line=dict(color=GREEN,width=1.5,shape="spline",smoothing=0.4),
            stackgroup="wb",
            hovertemplate="WY %{x}<br>ET: %{y:.0f} mm<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=b["water_year"],y=b["OUT_Q"],name="Runoff (Q)",
            mode="lines",fill="tonexty",fillcolor="rgba(1,87,155,0.35)",
            line=dict(color=BLUE,width=1.5,shape="spline",smoothing=0.4),
            stackgroup="wb",
            hovertemplate="WY %{x}<br>Q: %{y:.0f} mm<extra></extra>"))
        # Precipitation line on top
        fig.add_trace(go.Scatter(
            x=b["water_year"],y=b["OUT_PREC"],name="Precipitation",
            mode="lines",line=dict(color=NAVY,width=2.5,dash="solid"),
            hovertemplate="WY %{x}<br>P: %{y:.0f} mm<extra></extra>"))
        # ΔS = P - ET - Q (storage change; negative = storage loss)
        fig.add_trace(go.Scatter(
            x=b["water_year"],y=b["DELTA_S"],name="ΔS (storage change)",
            mode="lines",
            line=dict(color=ORANGE,width=2,dash="dot"),
            hovertemplate="WY %{x}<br>ΔS: %{y:.0f} mm<extra></extra>"))
        fig.add_hline(y=0,line_dash="dash",line_color="#b0bec5",line_width=1)
        fig.update_layout(
            xaxis_title="Water Year",yaxis_title="mm/yr",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=50,r=15,t=10,b=60),height=310,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("wb-rr-chart","figure"),
                  Input("wb-basin","value"), Input("wb-years","value"))
    def rr_chart(basin, years):
        # "All sub-basins" → overlay every sub-basin's runoff ratio (Q/P) on one chart.
        if basin == "ALL":
            from utils.multibasin import multi_basin_fig
            return multi_basin_fig("RE", years=years, height=310)
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&(df["water_year"]<=years[1])].copy()
        if b.empty: return _empty("No data")
        b=b.sort_values("water_year")
        b["Q"]=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
        b["rr"]=b["Q"]/b["OUT_PREC"]
        b["r5"]=b["rr"].rolling(5,center=True).mean()
        t=trend_slope(b["rr"],b["water_year"])
        fig=go.Figure()
        fig.add_trace(go.Scatter(
            x=b["water_year"],y=b["rr"],mode="lines+markers",
            line=dict(color=BLUE,width=1.5,shape="spline",smoothing=0.4),
            marker=dict(size=4,color=BLUE,opacity=0.6),
            fill="tozeroy",fillcolor="rgba(1,87,155,0.12)",
            name="Q/P",hovertemplate="WY %{x}<br>Q/P: %{y:.3f}<extra></extra>"))
        fig.add_trace(go.Scatter(
            x=b["water_year"],y=b["r5"],mode="lines",
            line=dict(color=NAVY,width=2.5),name="5-yr mean"))
        if t["slope"] is not None:
            xr_=np.array([b["water_year"].min(),b["water_year"].max()])
            yf =t["slope"]*xr_+(b["rr"].mean()-t["slope"]*b["water_year"].mean())
            sig=" " if t["pvalue"]<0.05 else ""
            fig.add_trace(go.Scatter(x=xr_,y=yf,mode="lines",
                line=dict(color=MAROON,width=2,dash="dot"),
                name=f"Trend {t['slope']*10:+.4f}/decade {sig}"))
        fig.update_layout(
            xaxis_title="Water Year",yaxis_title="Runoff Ratio (Q/P)",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=60),height=310,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("wb-et-chart","figure"),
                  Input("wb-basin","value"), Input("wb-years","value"))
    def et_chart(basin, years):
        if basin=="ALL": basin="CRB"
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&(df["water_year"]<=years[1])].copy()
        if b.empty: return _empty("No data")
        b=b.sort_values("water_year")
        fig=go.Figure()
        components=[
            ("OUT_EVAP_CANOP","Canopy Evap","rgba(27,94,32,0.5)",  "#1B5E20"),
            ("OUT_TRANSP_VEG","Transpiration","rgba(46,125,50,0.4)","#2E7D32"),
            ("OUT_EVAP_BARE", "Bare Soil Evap","rgba(165,214,167,0.5)","#81C784"),
        ]
        for vname,label,fill,color in components:
            if vname not in b.columns: continue
            fig.add_trace(go.Scatter(
                x=b["water_year"],y=b[vname],name=label,
                mode="lines",fill="tonexty" if label!="Canopy Evap" else "tozeroy",
                fillcolor=fill,
                line=dict(color=color,width=1.5,shape="spline",smoothing=0.4),
                stackgroup="et",
                hovertemplate=f"WY %{{x}}<br>{label}: %{{y:.0f}} mm<extra></extra>"))
        # Total ET line
        fig.add_trace(go.Scatter(
            x=b["water_year"],y=b["OUT_EVAP"],name="Total ET",
            mode="lines",line=dict(color=NAVY,width=2,dash="dash"),
            hovertemplate="WY %{x}<br>Total ET: %{y:.0f} mm<extra></extra>"))
        fig.update_layout(
            xaxis_title="Water Year",yaxis_title="mm/yr",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=50,r=15,t=10,b=60),height=310,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("wb-basin-chart","figure"),
                  Input("wb-compare-var","value"), Input("wb-years","value"))
    def basin_chart(var, years):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        if var not in df.columns: return _empty(f"{var} not in data")
        # Latest decade mean per basin
        recent=df[df["water_year"]>=years[1]-9]
        means=recent.groupby("basin")[var].mean().reset_index()
        means=means.rename(columns={var:"mean_val"})
        means["label"]=means["basin"].apply(basin_label)
        means=means.sort_values("mean_val")
        means["color"]=means["basin"].map(BASIN_COLORS).fillna(NAVY)
        fig=go.Figure()
        # Lollipop: segment from 0 to value + dot
        for _,row in means.iterrows():
            fig.add_trace(go.Scatter(
                x=[0,row["mean_val"]],y=[row["label"],row["label"]],
                mode="lines",line=dict(color=row["color"],width=3),
                showlegend=False,
                hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=means["mean_val"],y=means["label"],mode="markers",
            marker=dict(color=means["color"],size=14,
                        line=dict(color="white",width=2)),
            text=means["mean_val"].apply(lambda v:f"{v:.1f}"),
            textposition="middle right",
            hovertemplate="%{y}<br>%{x:.1f}<extra></extra>",
            showlegend=False))
        var_labels={
            "OUT_PREC":"Precipitation (mm/yr)","OUT_EVAP":"ET (mm/yr)",
            "OUT_RUNOFF":"Surface Runoff (mm/yr)","OUT_BASEFLOW":"Baseflow (mm/yr)",
            "RBFE":"Runoff Efficiency RBFE (%, hot-drought signal)",
            "OUT_SWE":"Peak SWE (mm)","OUT_SOIL_MOIST":"Total Soil Moisture (mm)",
            "OUT_SOIL_MOIST_L1":"Soil Moisture L1 0–10 cm (mm)",
            "OUT_SOIL_MOIST_L2":"Soil Moisture L2 10–40 cm (mm)",
            "OUT_SOIL_MOIST_L3":"Soil Moisture L3 40–200 cm (mm)",
            "OUT_AIR_TEMP":"Air Temperature (°C)",
        }
        fig.update_layout(
            xaxis_title=var_labels.get(var,var),
            yaxis=dict(tickfont=dict(size=11)),
            margin=dict(l=120,r=40,t=10,b=40),height=310,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("wb-sankey-chart","figure"),
                  Input("wb-basin","value"), Input("wb-years","value"))
    def sankey_chart(basin, years):
        if basin=="ALL": basin="CRB"
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&(df["water_year"]<=years[1])].copy()
        if b.empty: return _empty("No data")
        p   = b["OUT_PREC"].mean()
        et  = b["OUT_EVAP"].mean()
        q   = (b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]).mean()
        ds  = max(0.1, abs(p-et-q))  # storage residual
        canop  = b["OUT_EVAP_CANOP"].mean()  if "OUT_EVAP_CANOP" in b.columns else et*0.12
        transp = b["OUT_TRANSP_VEG"].mean()  if "OUT_TRANSP_VEG" in b.columns else et*0.55
        bare   = b["OUT_EVAP_BARE"].mean()   if "OUT_EVAP_BARE" in b.columns else et*0.33
        surf_q = b["OUT_RUNOFF"].mean()
        base_q = b["OUT_BASEFLOW"].mean()
        labels = [f"Precipitation<br>{p:.0f} mm", f"Total ET<br>{et:.0f} mm",
                  f"Total Q<br>{q:.0f} mm", f"ΔStorage<br>{ds:.0f} mm",
                  "Canopy Evap","Transpiration","Bare-soil ET","Surface Runoff","Baseflow"]
        # vivid, distinct node colours
        node_colors = ["#0277BD","#2E7D32","#00897B","#EF6C00",
                       "#66BB6A","#1B5E20","#9CCC65","#039BE5","#5E35B1"]
        # bright links, coloured by destination
        link_colors = ["rgba(46,125,50,0.55)",   # P → ET
                       "rgba(0,137,123,0.55)",    # P → Q
                       "rgba(239,108,0,0.60)",    # P → ΔStorage
                       "rgba(102,187,106,0.50)",  # ET → canopy
                       "rgba(27,94,32,0.50)",     # ET → transpiration
                       "rgba(156,204,101,0.55)",  # ET → bare soil
                       "rgba(3,155,229,0.55)",    # Q → surface runoff
                       "rgba(94,53,177,0.50)"]    # Q → baseflow
        fig = go.Figure(go.Sankey(
            arrangement="snap",
            node=dict(pad=18,thickness=20,label=labels,color=node_colors,
                      line=dict(color="white",width=1.5)),
            textfont=dict(size=11,color="#1e293b"),
            link=dict(
                source=[0,0,0, 1,1,1, 2,2],
                target=[1,2,3, 4,5,6, 7,8],
                value=[max(0.1,et),max(0.1,q),ds,
                       max(0.1,canop),max(0.1,transp),max(0.1,bare),
                       max(0.1,surf_q),max(0.1,base_q)],
                color=link_colors,
                hovertemplate="%{source.label} → %{target.label}: %{value:.0f} mm/yr<extra></extra>")
        ))
        fig.update_layout(
            margin=dict(l=10,r=10,t=30,b=30),height=340,
            paper_bgcolor="white",font=dict(size=11,color="#1e293b"),
            title=dict(text=f"Mean WY{years[0]}–{years[1]}  ·  P = {p:.0f} mm/yr  →  ET + Q + ΔStorage",
                       font=dict(size=10,color="#1e293b"),x=0.5,xanchor="center",y=0.02,yanchor="bottom"))
        return fig

    @app.callback(Output("wb-aridity-chart","figure"), Input("wb-years","value"))
    def aridity_chart(years):
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        recent=df[(df["water_year"]>=years[0])&(df["water_year"]<=years[1])].copy()
        recent["AI"]=recent["OUT_EVAP"]/recent["OUT_PREC"].replace(0,np.nan)
        recent=recent.dropna(subset=["AI"])
        if recent.empty: return _empty("No data")
        # violin plots — each basin's annual dryness-ratio (ET/P) distribution
        order=recent.groupby("basin")["AI"].median().sort_values().index.tolist()
        cats,series,cols=[],[],[]
        for b in order:
            s=recent[recent["basin"]==b]["AI"].dropna()
            if len(s)<3: continue
            m=s.median()
            cats.append(basin_label(b)); series.append(list(s.values))
            cols.append(MAROON if m>0.8 else ORANGE if m>0.6 else BLUE)
        fig=violin_v(cats, series, cols, y_title="Dryness Ratio (ET / P)", height=320)
        fig.add_hline(y=1.0,line_dash="dash",line_color="#90a4ae",line_width=1.5,
                      annotation_text="P = ET",annotation_font=dict(size=9,color="#546e7a"))
        fig.add_hline(y=0.8,line_dash="dot",line_color=ORANGE,line_width=1,
                      annotation_text="Semi-arid",annotation_font=dict(size=9,color=ORANGE))
        return fig

    @app.callback(Output("wb-findings","children"),
                  Input("wb-basin","value"), Input("wb-years","value"))
    def findings(basin,years):
        if basin=="ALL": basin="CRB"
        df=_safe(load_vic_annual)
        if df.empty: return " Key findings will appear after preprocessing is complete."
        b=df[(df["basin"]==basin)&(df["water_year"]>=years[0])&(df["water_year"]<=years[1])].copy()
        if b.empty: return "No data for selected range."
        p  = b["OUT_PREC"].mean()
        et = b["OUT_EVAP"].mean()
        q  = (b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]).mean()
        rr = q/p if p>0 else 0
        et_frac = et/p*100 if p>0 else 0
        b["rr"]=( b["OUT_RUNOFF"]+b["OUT_BASEFLOW"])/b["OUT_PREC"]
        t=trend_slope(b["rr"],b["water_year"])
        trend_str=(f"Runoff ratio trending {t['slope']*10:+.4f}/decade "
        f"({'significant ' if t['pvalue']<0.05 else 'not significant'})."
        if t["slope"] else "")
        return [html.Strong("Key Findings — "),
                f"{basin_label(basin)}: mean P={p:.0f} mm/yr, ET={et:.0f} mm/yr ({et_frac:.0f}% of P), "
                f"Q={q:.0f} mm/yr. Runoff ratio={rr:.2f}. {trend_str}"]

    @app.callback(Output("wb-dl-data","data"),Input("wb-dl-btn","n_clicks"),
                  Input("wb-basin","value"),prevent_initial_call=True)
    def download(n,basin):
        if not n: return None
        df=_safe(load_vic_annual)
        if df.empty: return None
        b=(df.copy() if basin=="ALL" else df[df["basin"]==basin].copy())
        b["Q"]=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]
        b["runoff_ratio"]=b["Q"]/b["OUT_PREC"]
        cols=["water_year","basin","OUT_PREC","OUT_EVAP","OUT_RUNOFF","OUT_BASEFLOW","Q","runoff_ratio"]
        return dcc.send_data_frame(b[cols].to_csv,"crb_water_balance.csv",index=False)
