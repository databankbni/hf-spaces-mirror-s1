"""
modules/future.py — Module 5: Future Projections
Charts:
  1. Historical VIC time series + WY2100 VICOut2 anchor (real data only)
  2. Decade-by-decade historical means bar (WY1990s/2000s/2010s/2020s)
  3. % change from baseline — all basins at WY2100 anchor
  4. dQ/dT runoff sensitivity scatter (historical only)
All data is REAL: VIC PRISM-calibrated WY1983–2024 + VICOut2.nc WY2100 single snapshot.
No synthetic interpolation anywhere.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import load_vic_annual, load_vic_future, basin_label, trend_slope
from utils.components import howto

MAROON="#8C1D40"; NAVY="#0D2137"; GOLD="#FFC627"
BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; PURPLE="#4527A0"
BASIN_OPTIONS=[
    {"label":"Colorado River Basin","value":"CRB"},
    {"label":"Upper Basin","value":"UpperBasin"},
    {"label":"Lower Basin","value":"LowerBasin"},
    {"label":"Green River","value":"Green"},
    {"label":"San Juan","value":"SanJuan"},
    {"label":"Grand Canyon","value":"GrandCanyon"},
    {"label":"Gila River","value":"Gila"},
]
VAR_OPTIONS=[
    {"label":"Precipitation (mm/yr)",         "value":"OUT_PREC"},
    {"label":"Total ET (mm/yr)",              "value":"OUT_EVAP"},
    {"label":"Surface Runoff (mm/yr)",        "value":"OUT_RUNOFF"},
    {"label":"Baseflow (mm/yr)",              "value":"OUT_BASEFLOW"},
    {"label":"SWE, peak annual (mm)",         "value":"OUT_SWE"},
    {"label":"Soil Moisture (mm)",            "value":"OUT_SOIL_MOIST"},
    {"label":"Air Temperature (°C)",          "value":"OUT_AIR_TEMP"},
]
BASIN_COLORS={
    "CRB":NAVY,"UpperBasin":BLUE,"LowerBasin":MAROON,
    "Green":GREEN,"SanJuan":ORANGE,"GrandCanyon":PURPLE,"Gila":"#00695C",
}
# Historical decades for real-data decadal comparison
HIST_DECADES = {"1990s":(1990,1999),"2000s":(2000,2009),"2010s":(2010,2019),"2020s":(2020,2024)}

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
            html.H2("Hydrologic Projections to 2100 (single scenario run)"),
            html.P("Historical VIC 5.0 PRISM-calibrated record (WY1983–2024) with a downscaled "
                   "WY2100 endpoint from a single VIC run (VICOut2.nc) — a direction under "
                   "continued warming, not an ensemble or a probabilistic projection."),
        ],className="tab-header"),
        html.Div([
            html.Div("Note: the 2100 point is a single illustrative downscaled VIC run, not a "
                     "multi-model ensemble. For ensemble climate-change ranges see the CMIP tab; for "
                     "interactive what-if scenarios see the Climate-Sensitivity Scenario tab.",
                     style={"background":"#fff3e0","borderLeft":"3px solid #E65100",
                            "padding":"8px 13px","borderRadius":"0 6px 6px 0","fontSize":"11px",
                            "color":"#e65100","marginBottom":"12px"}),
            dbc.Row(id="fut-tiles",className="mb-3 g-2"),
            html.Div(id="fut-findings",
                     style={"background":"#ede7f6","borderLeft":f"3px solid {PURPLE}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#4527a0","marginBottom":"12px"}),
                            howto("Pick a variable. These compare the WY2100 projection with the historical record — read it as a direction under continued warming, not a precise forecast."),
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("Basin",className="control-label"),
                        dcc.Dropdown(id="fut-basin",options=BASIN_OPTIONS,
                                     value="CRB",clearable=False,
                                     style={"fontSize":"12.5px"}),
                    ],md=3),
                    dbc.Col([
                        html.Div("Variable",className="control-label"),
                        dcc.Dropdown(id="fut-var",options=VAR_OPTIONS,
                                     value="OUT_RUNOFF",clearable=False,
                                     style={"fontSize":"12.5px"}),
                    ],md=3),
                    dbc.Col([
                        html.Div("Baseline Period",className="control-label"),
                        dcc.RangeSlider(id="fut-baseline",min=1983,max=2024,step=1,
                                        value=[1983,2010],
                                        marks={y:str(y) for y in [1983,1990,2000,2010,2024]},
                                        tooltip={"placement":"bottom","always_visible":False}),
                    ],md=6),
                ]),
            ],className="control-panel"),

            # Row 1: full time series
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Historical Record + VICOut2 WY2100 Endpoint",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— VIC PRISM-calibrated WY1983–2024 (reanalysis) + VICOut2.nc WY2100 anchor ( single scenario point)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                            dbc.Button("CSV",id="fut-dl-btn",size="sm",
                                       className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="fut-ts-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"320px"}),
                        dcc.Download(id="fut-dl-data"),
                    ],className="crb-card"),
                ],md=12),
            ],className="g-3 mb-2"),

            # Row 2: decadal means + % change ranking
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Historical Decadal Means vs Baseline",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— observed decades WY1990s–2020s",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="fut-decade-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"300px"}),
                    ],className="crb-card"),
                ],md=6),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span(" Basin % Change: Baseline VICOut2 WY2100",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— VICOut2.nc single scenario endpoint",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="fut-basin-rank",
                                  config={"displayModeBar":False},
                                  style={"height":"300px"}),
                    ],className="crb-card"),
                ],md=6),
            ],className="g-3"),

            # Row 3: Runoff sensitivity dQ/dT
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span(" Runoff Sensitivity to Temperature (dQ/dT)",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— VIC historical runoff vs air temperature scatter by basin",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="fut-sensitivity-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"300px"}),
                    ],className="crb-card"),
                ],md=12),
            ],className="g-3 mb-2"),

        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("fut-tiles","children"),
                  Input("fut-basin","value"), Input("fut-var","value"),
                  Input("fut-baseline","value"))
    def tiles(basin, var, baseline):
        df_h=_safe(load_vic_annual); df_f=_safe(load_vic_future)
        no_data=[dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3)
                 for l in ["Baseline mean","Sen's trend/decade","WY2100 VICOut2","Δ Baseline WY2100"]]
        if df_h.empty or var not in df_h.columns: return no_data
        bh=df_h[(df_h["basin"]==basin)&(df_h["water_year"]>=baseline[0])&
                (df_h["water_year"]<=baseline[1])]
        base_mean=bh[var].mean() if not bh.empty else np.nan

        # Sen's slope from full historical record
        bh_all=df_h[df_h["basin"]==basin].sort_values("water_year")
        trend_str="—"
        if not bh_all.empty and var in bh_all.columns:
            t=trend_slope(bh_all[var], bh_all["water_year"])
            if t["slope"] is not None:
                sig=" " if t["pvalue"] is not None and t["pvalue"]<0.05 else ""
                trend_str=f"{t['slope']*10:+.2f}/dec{sig}"
        # WY2100 VICOut2 anchor (only real future data)
        vic2100_str="—"; pct_str="—"; t4_color="tile-slate"
        if not df_f.empty and var in df_f.columns:
            r2100=df_f[(df_f["basin"]==basin)&(df_f["water_year"]==2100)]
            if not r2100.empty:
                v2100=r2100[var].values[0]
                vic2100_str=f"{v2100:.1f}"
                if not np.isnan(base_mean) and base_mean!=0:
                    pct=(v2100-base_mean)/abs(base_mean)*100
                    pct_str=f"{pct:+.1f}%"
                    t4_color="tile-maroon" if pct<0 else "tile-green"
        tiles_=[
            _tile(f"{base_mean:.1f}" if not np.isnan(base_mean) else "—",
                  f"Baseline mean ({baseline[0]}–{baseline[1]})"," ","tile-navy"),
            _tile(trend_str, "Sen's trend/decade (WY1983-2024)"," ","tile-slate"),
            _tile(vic2100_str,"VICOut2.nc WY2100"," ","tile-blue"),
            _tile(pct_str,   "% change: baseline WY2100"," " if pct_str.startswith("-") else " ",t4_color),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("fut-ts-chart","figure"),
                  Input("fut-basin","value"), Input("fut-var","value"),
                  Input("fut-baseline","value"))
    def ts_chart(basin, var, baseline):
        df_h=_safe(load_vic_annual); df_f=_safe(load_vic_future)
        if df_h.empty or var not in df_h.columns: return _empty()
        bh=df_h[df_h["basin"]==basin].sort_values("water_year")
        fig=go.Figure()

        # Baseline shading
        fig.add_vrect(x0=baseline[0],x1=baseline[1],
                      fillcolor="rgba(13,33,55,0.06)",line_width=0,
                      annotation_text="Baseline",annotation_position="top left",
                      annotation_font=dict(size=9,color="#546e7a"))

        # Baseline mean line
        bh_base=bh[(bh["water_year"]>=baseline[0])&(bh["water_year"]<=baseline[1])]
        base_mean=bh_base[var].mean() if not bh_base.empty else None
        if base_mean is not None:
            fig.add_hline(y=base_mean,line_dash="dash",line_color="#90a4ae",line_width=1.5,
                          annotation_text=f"Baseline mean: {base_mean:.1f}",
                          annotation_position="right",annotation_font=dict(size=9))

        # Historical record (real data)
        fig.add_trace(go.Scatter(
            x=bh["water_year"],y=bh[var],mode="lines",
            line=dict(color=BLUE,width=2,shape="spline",smoothing=0.4),
            name="Historical VIC PRISM-calibrated (WY1983–2024)",
            hovertemplate="WY %{x}<br>%{y:.1f}<extra></extra>"))

        # 5-year moving average
        bh_c=bh.copy(); bh_c["roll5"]=bh_c[var].rolling(5,center=True).mean()
        fig.add_trace(go.Scatter(
            x=bh_c["water_year"],y=bh_c["roll5"],mode="lines",
            line=dict(color=NAVY,width=2.5),name="5-yr mean",
            hovertemplate="WY %{x}<br>%{y:.1f}<extra></extra>"))

        # WY2100 VICOut2 anchor — single real point
        if not df_f.empty and var in df_f.columns:
            r2100=df_f[(df_f["basin"]==basin)&(df_f["water_year"]==2100)]
            if not r2100.empty:
                v2100=r2100[var].values[0]
                fig.add_trace(go.Scatter(
                    x=[2100],y=[v2100],mode="markers",
                    marker=dict(symbol="star",size=18,color=MAROON,
                                line=dict(color="white",width=1.5)),
                    name=f"VICOut2.nc WY2100: {v2100:.1f}",
                    hovertemplate="WY2100 (VICOut2)<br>%{y:.1f}<extra></extra>"))
                # Dashed line connecting last historical to WY2100 anchor
                last_wy=bh["water_year"].max()
                last_val=bh[bh["water_year"]==last_wy][var].values[0]
                fig.add_trace(go.Scatter(
                    x=[last_wy, 2100],y=[last_val, v2100],mode="lines",
                    line=dict(color="rgba(140,29,64,0.4)",width=1.5,dash="dot"),
                    name="Connect to WY2100 anchor",showlegend=False,
                    hoverinfo="skip"))
                # Label the gap
                fig.add_annotation(x=2062,y=(last_val+v2100)/2,
                    text=" gap: no data 2025–2099 ",
                    showarrow=False,font=dict(size=9,color="#78909c"),
                    bgcolor="rgba(255,255,255,0.7)")

        # WY2024 partial-year marker
        fig.add_vline(x=2024,line_dash="dash",line_color="#FFC627",line_width=1,
                      annotation_text="WY2024 (Jan–Sep)",annotation_position="top left",
                      annotation_font=dict(size=8,color="#B8860B"))

        var_units={"OUT_PREC":"Precipitation (mm/yr)","OUT_EVAP":"ET (mm/yr)",
                   "OUT_RUNOFF":"Runoff (mm/yr)","OUT_BASEFLOW":"Baseflow (mm/yr)",
                   "OUT_SWE":"Peak SWE (mm)","OUT_SOIL_MOIST":"Soil Moisture (mm)",
                   "OUT_AIR_TEMP":"Air Temp (°C)","OUT_LATENT":"Latent Heat (W/m²)"}
        fig.update_layout(
            xaxis=dict(title="Water Year",range=[1980,2108]),
            yaxis_title=var_units.get(var,var),
            legend=dict(orientation="h",y=-0.15,x=0,font=dict(size=10)),
            margin=dict(l=60,r=15,t=10,b=55),height=330,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("fut-decade-chart","figure"),
                  Input("fut-basin","value"), Input("fut-var","value"),
                  Input("fut-baseline","value"))
    def decade_chart(basin, var, baseline):
        """
        Real historical decadal means — no synthetic data."""
        df_h=_safe(load_vic_annual)
        if df_h.empty or var not in df_h.columns: return _empty()
        bh_all=df_h[df_h["basin"]==basin]
        bh_base=bh_all[(bh_all["water_year"]>=baseline[0])&(bh_all["water_year"]<=baseline[1])]
        base_mean=bh_base[var].mean() if not bh_base.empty else np.nan

        labels=["Baseline\n(%d–%d)" % (baseline[0],baseline[1])]
        vals=[base_mean]; colors=[NAVY]; n_yrs=[len(bh_base)]

        for dec,(y0,y1) in HIST_DECADES.items():
            sub=bh_all[(bh_all["water_year"]>=y0)&(bh_all["water_year"]<=y1)]
            if sub.empty: continue
            m=sub[var].mean()
            labels.append(dec); vals.append(m); n_yrs.append(len(sub))
            colors.append(MAROON if m<base_mean else GREEN)

        fig=go.Figure()
        fig.add_trace(go.Bar(
            x=labels,y=vals,marker_color=colors,marker_line_width=0,
            text=[f"{v:.1f}" for v in vals],textposition="outside",
            textfont=dict(size=10),
            hovertemplate="%{x}<br>%{y:.1f} (n=%{customdata} yrs)<extra></extra>",
            customdata=n_yrs))
        fig.add_hline(y=base_mean,line_dash="dash",line_color="#90a4ae",line_width=1.5,
                      annotation_text=f"Baseline: {base_mean:.1f}",
                      annotation_position="right",annotation_font=dict(size=9))
        fig.add_annotation(
            text="Note: 2020s bar = WY2020–2024 (5 years, partial) · All data from the VIC PRISM-calibrated reanalysis",
            xref="paper",yref="paper",x=0.01,y=0.03,showarrow=False,
            font=dict(size=9,color="#78909c"),xanchor="left")
        var_units={"OUT_PREC":"Precipitation (mm/yr)","OUT_EVAP":"ET (mm/yr)",
                   "OUT_RUNOFF":"Runoff (mm/yr)","OUT_BASEFLOW":"Baseflow (mm/yr)",
                   "OUT_SWE":"Peak SWE (mm)","OUT_SOIL_MOIST":"Soil Moisture (mm)",
                   "OUT_AIR_TEMP":"Air Temp (°C)"}
        fig.update_layout(
            xaxis_title="Decade",yaxis_title=var_units.get(var,var),
            margin=dict(l=55,r=15,t=30,b=50),height=300,
            paper_bgcolor="white",plot_bgcolor="white",bargap=0.3,
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("fut-basin-rank","figure"),
                  Input("fut-var","value"), Input("fut-baseline","value"))
    def basin_rank(var, baseline):
        """% change from baseline to WY2100 VICOut2 anchor — real data only."""
        df_h=_safe(load_vic_annual); df_f=_safe(load_vic_future)
        if df_h.empty or var not in df_h.columns: return _empty()
        records=[]
        for bid in ["CRB","UpperBasin","LowerBasin","Green","SanJuan","GrandCanyon","Gila"]:
            bh=df_h[(df_h["basin"]==bid)&(df_h["water_year"]>=baseline[0])&
                    (df_h["water_year"]<=baseline[1])]
            base=bh[var].mean() if not bh.empty else np.nan
            v2100=np.nan
            if not df_f.empty and var in df_f.columns:
                r2100=df_f[(df_f["basin"]==bid)&(df_f["water_year"]==2100)]
                if not r2100.empty: v2100=r2100[var].values[0]
            pct=((v2100-base)/abs(base)*100) if (not np.isnan(base) and base!=0
                                                  and not np.isnan(v2100)) else np.nan
            records.append({"basin":bid,"label":basin_label(bid),"pct":pct,"v2100":v2100,"base":base})
        df_r=pd.DataFrame(records).dropna(subset=["pct"]).sort_values("pct")
        if df_r.empty: return _empty("No VICOut2.nc WY2100 data available")
        colors=[MAROON if v<0 else GREEN for v in df_r["pct"]]
        fig=go.Figure()
        for _,row in df_r.iterrows():
            fig.add_trace(go.Scatter(
                x=[0,row["pct"]],y=[row["label"],row["label"]],mode="lines",
                line=dict(color=MAROON if row["pct"]<0 else GREEN,width=3),
                showlegend=False,hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=df_r["pct"],y=df_r["label"],mode="markers+text",
            marker=dict(color=colors,size=13,line=dict(color="white",width=2)),
            text=df_r["pct"].apply(lambda v:f"{v:+.1f}%"),
            textposition="middle right",textfont=dict(size=9),
            hovertemplate="%{y}<br>Baseline: %{customdata[0]:.1f} WY2100: %{customdata[1]:.1f} (%{x:+.1f}%)<extra></extra>",
            customdata=df_r[["base","v2100"]].values,
            showlegend=False))
        fig.add_vline(x=0,line_dash="dash",line_color="#b0bec5",line_width=1.5)
        fig.update_layout(
            xaxis_title="% Change: Baseline VICOut2.nc WY2100",
            yaxis=dict(tickfont=dict(size=11)),
            margin=dict(l=120,r=70,t=10,b=40),height=300,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("fut-sensitivity-chart","figure"),
                  Input("fut-basin","value"), Input("fut-baseline","value"))
    def sensitivity_chart(basin, baseline):
        from scipy import stats as scipy_stats
        df=_safe(load_vic_annual)
        if df.empty: return _empty()
        if "OUT_AIR_TEMP" not in df.columns or "OUT_RUNOFF" not in df.columns:
            return _empty("Temperature or runoff data not available")
        fig=go.Figure()
        BCOLORS={"CRB":NAVY,"UpperBasin":BLUE,"LowerBasin":MAROON,
                 "Green":GREEN,"SanJuan":ORANGE,"GrandCanyon":PURPLE,"Gila":"#00695C"}
        slopes=[]
        all_basins=["UpperBasin","LowerBasin","Green","SanJuan","GrandCanyon","Gila"]
        # Also plot selected basin more prominently
        plot_basins=list(dict.fromkeys([basin]+all_basins))
        for bid in plot_basins:
            b=df[(df["basin"]==bid)&(df["water_year"]>=baseline[0])&
                 (df["water_year"]<=baseline[1])].copy()
            if b.empty or len(b)<5: continue
            t_arr=b["OUT_AIR_TEMP"].values
            q_arr=(b["OUT_RUNOFF"]+b["OUT_BASEFLOW"]).values
            mask=~(np.isnan(t_arr)|np.isnan(q_arr))
            if mask.sum()<5: continue
            sl,ic,r,p,_=scipy_stats.linregress(t_arr[mask],q_arr[mask])
            slopes.append({"basin":basin_label(bid),"slope":sl,"r2":r**2,"p":p})
            col=BCOLORS.get(bid,NAVY)
            size=7 if bid!=basin else 10
            opacity=0.5 if bid!=basin else 0.9
            fig.add_trace(go.Scatter(
                x=b["OUT_AIR_TEMP"],y=b["OUT_RUNOFF"]+b["OUT_BASEFLOW"],
                mode="markers",
                marker=dict(size=size,color=col,opacity=opacity,line=dict(color="white",width=0.5)),
                name=basin_label(bid) if bid==basin else basin_label(bid),
                text=b["water_year"].astype(str),
                hovertemplate=f"{basin_label(bid)}<br>T: %{{x:.1f}}°C<br>Q: %{{y:.0f}} mm<br>WY%{{text}}<extra></extra>"))
            xl=np.linspace(t_arr[mask].min(),t_arr[mask].max(),50)
            fig.add_trace(go.Scatter(x=xl,y=sl*xl+ic,mode="lines",
                line=dict(color=col,width=2 if bid==basin else 1,
                          dash="solid" if bid==basin else "dot"),
                showlegend=False,
                hovertemplate=f"{basin_label(bid)}: dQ/dT={sl:+.1f} mm/°C<extra></extra>"))
        # Table of sensitivities as annotation
        if slopes:
            df_sl=pd.DataFrame(slopes).sort_values("slope")
            ann_text="<b>dQ/dT (mm/°C)</b><br>" + "<br>".join(
                f"{r['basin']}: {r['slope']:+.1f} (R²={r['r2']:.2f})"for _,r in df_sl.iterrows())
            fig.add_annotation(x=1,y=1,xref="paper",yref="paper",
                text=ann_text,showarrow=False,
                align="left",xanchor="right",yanchor="top",
                font=dict(size=9,color="#37474f"),
                bgcolor="rgba(255,255,255,0.88)",bordercolor="#e0e0e0",borderwidth=1)
        fig.add_annotation(
            text="Note: Historical VIC WY1983–2023 — dQ/dT = runoff change per 1°C warming",
            xref="paper",yref="paper",x=0.01,y=0.03,showarrow=False,
            font=dict(size=9,color="#78909c"),xanchor="left")
        fig.update_layout(
            xaxis_title="Annual Mean Air Temperature (°C)",
            yaxis_title="Annual Runoff (mm/yr)",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=60,r=15,t=10,b=65),height=300,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("fut-findings","children"),
                  Input("fut-basin","value"), Input("fut-var","value"),
                  Input("fut-baseline","value"))
    def findings(basin, var, baseline):
        """
        Key findings — 100% real data: historical trends + VICOut2 WY2100 endpoint."""
        df_h=_safe(load_vic_annual); df_f=_safe(load_vic_future)
        if df_h.empty: return " Run preprocessing to see key findings."
        bh_all=df_h[df_h["basin"]==basin].sort_values("water_year")
        bh_base=bh_all[(bh_all["water_year"]>=baseline[0])&(bh_all["water_year"]<=baseline[1])]
        if bh_base.empty or var not in bh_base.columns: return f"Variable {var} not found."
        base=bh_base[var].mean()

        # Historical trend (Mann-Kendall)
        t=trend_slope(bh_all[var], bh_all["water_year"])
        trend_txt="no significant trend"
        if t["slope"] is not None and t["pvalue"] is not None:
            per_dec=t["slope"]*10
            sig=" significant (p<0.05)" if t["pvalue"]<0.05 else "(p≥0.05, not significant)"
            dir_="declining" if per_dec<0 else "increasing"
            trend_txt=f"{dir_} {abs(per_dec):.2f}/decade {sig}"
        # Recent decade vs baseline
        recent=bh_all[bh_all["water_year"]>=2015][var].dropna()
        rec_txt="—"
        if not recent.empty and base and abs(base)>0.01:
            pct=(recent.mean()-base)/abs(base)*100
            rec_txt=f"{recent.mean():.1f} ({pct:+.1f}% vs baseline)"
        # VICOut2 WY2100 anchor (real VIC simulation)
        v2100_txt="Not available"
        if not df_f.empty and var in df_f.columns:
            r2100=df_f[(df_f["basin"]==basin)&(df_f["water_year"]==2100)]
            if not r2100.empty:
                v2100=r2100[var].values[0]
                pct2100=(v2100-base)/abs(base)*100 if base!=0 else 0
                v2100_txt=f"{v2100:.1f} ({pct2100:+.1f}% vs baseline)"
        # Manager bottom line (MAF only for water-volume fluxes)
        from utils.manager import to_maf, manager_line
        flux = var in ("OUT_RUNOFF", "OUT_BASEFLOW", "OUT_PREC", "OUT_EVAP")
        vol_txt = ""
        if flux:
            base_maf = to_maf(base, basin)
            if base_maf == base_maf:
                vol_txt = f" That baseline is about {base_maf:.1f} MAF of basin water."
        dirn = "declining" if (t["slope"] or 0) < 0 else "rising"
        vlabel = next((o["label"] for o in VAR_OPTIONS if o["value"] == var), var)
        mgr = manager_line(
            f"For {basin_label(basin)}, {vlabel} is "
            f"{dirn} over the record and the recent decade sits at {rec_txt}.{vol_txt} "
            "The 2100 value below is a single downscaled scenario (not an ensemble) and indicates "
            "direction rather than a precise forecast.",
            color="#01579B")
        parts=[
            mgr,
            html.Strong(f"Detail — {basin_label(basin)} ({var}):  "),
            f"Baseline ({baseline[0]}–{baseline[1]}): {base:.1f}.  ",
            f"Historical trend: {trend_txt}.  ",
            f"Recent decade (WY2015–2024): {rec_txt}.  ",
            html.Br(),
            html.Strong("WY2100 scenario (VICOut2.nc): "), v2100_txt, ".  ",
            html.Em("Single downscaled scenario; not an ensemble.",
                    style={"color":"#1e293b"}),
        ]
        return parts

    @app.callback(Output("fut-dl-data","data"),Input("fut-dl-btn","n_clicks"),
                  Input("fut-basin","value"),Input("fut-var","value"),
                  prevent_initial_call=True)
    def download(n,basin,var):
        if not n: return None
        df_h=_safe(load_vic_annual); df_f=_safe(load_vic_future)
        frames=[]
        if not df_h.empty and var in df_h.columns:
            bh=df_h[df_h["basin"]==basin][["water_year","basin",var]].copy()
            bh["source"]="historical_VIC_PRISM"; frames.append(bh)
        # Only export WY2100 row (real VICOut2 data)
        if not df_f.empty and var in df_f.columns:
            r2100=df_f[(df_f["basin"]==basin)&(df_f["water_year"]==2100)][["water_year","basin",var]].copy()
            r2100["source"]="VICOut2_WY2100_real"; frames.append(r2100)
        if not frames: return None
        out=pd.concat(frames)
        return dcc.send_data_frame(out.to_csv,"crb_historical_vic2100.csv",index=False)
