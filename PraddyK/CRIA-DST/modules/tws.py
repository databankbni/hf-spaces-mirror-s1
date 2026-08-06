"""
modules/tws.py — Module 3: Terrestrial Water Storage
Charts:
  1. GRACE TWS anomaly time series + 12-month rolling mean
  2. TWS deficit accumulation (drought memory)
  3. Seasonal climatology of TWS (monthly mean anomaly)
  4. SMAP soil moisture vs VIC layer-1 SM (validation)
  5. Multi-basin TWS comparison (recent period)
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import (
    load_grace, load_smap, load_vic_annual, load_vic_monthly,
    basin_label, trend_slope, trend_ci
)
from utils.components import xref, pub_evidence, pub_star, pub_author, howto

MAROON="#8C1D40"; NAVY="#0D2137"; GOLD="#FFC627"
BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; TEAL="#00695C"
BASIN_OPTIONS=[
    {"label":"Colorado River Basin","value":"CRB"},
    {"label":"Upper Basin","value":"UpperBasin"},
    {"label":"Lower Basin","value":"LowerBasin"},
    {"label":"Green River","value":"Green"},
    {"label":"San Juan","value":"SanJuan"},
    {"label":"Grand Canyon","value":"GrandCanyon"},
    {"label":"Gila River","value":"Gila"},
]
MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

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
            html.H2("Terrestrial Water Storage"),
            html.P("GRACE JPL mascon RL06 TWS anomaly · Seasonal decomposition · VIC soil moisture (Apr 2002 – Jan 2024)"),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="tws-tiles",className="mb-3 g-2"),
            html.Div(id="tws-findings",
                     style={"background":"#fce4ec","borderLeft":f"3px solid {MAROON}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#880e4f","marginBottom":"12px"}),
                            howto("Pick a basin. GRACE total water storage tracks the basin's overall water balance from space; the cumulative-deficit curve is its 'drought memory'."),
                            pub_author("Castle 2014; Abdelmohsen 2025", "https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2025GL115593", "Castle et al. 2014 GRL; Abdelmohsen et al. 2025 GRL", "published"),
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("Basin",className="control-label"),
                        dcc.Dropdown(id="tws-basin",options=BASIN_OPTIONS,
                                     value="CRB",clearable=False,
                                     style={"fontSize":"12.5px"}),
                    ],md=3),
                    dbc.Col([
                        html.Div("Smoothing Window (months)",className="control-label"),
                        dcc.Slider(id="tws-smooth",min=1,max=24,step=1,value=12,
                                   marks={1:"1",6:"6",12:"12",24:"24"},
                                   tooltip={"placement":"bottom","always_visible":True}),
                    ],md=5),
                    dbc.Col([
                        html.Div("Compare All Basins",className="control-label"),
                        dbc.Switch(id="tws-all-basins",value=False,
                                   label="Show all basins",
                                   style={"fontSize":"12px","marginTop":"6px"}),
                    ],md=4),
                ]),
            ],className="control-panel"),

            # Row 1: TWS time series
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("GRACE TWS Anomaly",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— liquid water equivalent (mm)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                            dbc.Button("CSV",id="tws-dl-btn",size="sm",
                                       className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                            pub_star("https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2025GL115593", "Abdelmohsen et al. 2025, GRL", "Published"),
                        ],className="crb-card-header"),
                        dcc.Graph(id="tws-main-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"320px"}),
                        dcc.Download(id="tws-dl-data"),
                    ],className="crb-card"),
                ],md=8),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("TWS Seasonal Cycle",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— mean by month",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="tws-seasonal-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"320px"}),
                    ],className="crb-card"),
                ],md=4),
            ],className="g-3 mb-2"),

            # Row 2: deficit accumulation + SMAP validation
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span(" TWS Deficit Accumulation",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— cumulative below-zero storage",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="tws-deficit-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"300px"}),
                    ],className="crb-card"),
                ],md=6),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Soil Moisture",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— VIC modeled (SMAP validation when available)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="tws-smap-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"300px"}),
                    ],className="crb-card"),
                ],md=6),
            ],className="g-3"),

            # Row 3: Recovery detection
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Multi-Year Recovery Detection",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— consecutive positive GRACE anomaly runs (recovery episodes)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ],className="crb-card-header"),
                        dcc.Graph(id="tws-recovery-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"280px"}),
                    ],className="crb-card"),
                ],md=12),
            ],className="g-3 mb-2"),

            xref("GRACE storage is also used in:", [("Groundwater residual → Storage", "/storage"), ("2023 recovery → Recovery", "/recovery"), ("Propagation lag → Drought Propagation", "/cascade")]),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("tws-tiles","children"),Input("tws-basin","value"))
    def tiles(basin):
        df=_safe(load_grace)
        if df.empty:
            return [dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3)
                    for l in ["TWS period","Min anomaly (mm)","Max anomaly (mm)","Trend mm/yr"]]
        b=df[df["basin"]==basin].dropna(subset=["tws_mm"])
        if b.empty:
            return [dbc.Col(_tile("—",l," ","tile-navy"),xs=6,md=3)
                    for l in ["TWS period","Min anomaly","Max anomaly","Trend"]]
        t_range=f"{b['date'].min().year}–{b['date'].max().year}"
        mn=b["tws_mm"].min(); mx=b["tws_mm"].max()
        b2=b.copy(); b2["t_num"]=np.arange(len(b2))
        tr=trend_slope(b2["tws_mm"],b2["t_num"])
        trend_val=(f"{tr['slope']*12:+.1f} mm/yr" if tr["slope"] else "—")
        tiles_=[
            _tile(t_range,        "GRACE period",           " ","tile-navy"),
            _tile(f"{mn:.0f} mm", "Min TWS anomaly",        " ","tile-maroon"),
            _tile(f"{mx:.0f} mm", "Max TWS anomaly",        " ","tile-blue"),
            _tile(trend_val,      "Long-term TWS trend",    " ","tile-orange"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("tws-main-chart","figure"),
                  Input("tws-basin","value"),
                  Input("tws-smooth","value"),
                  Input("tws-all-basins","value"))
    def main_chart(basin, smooth, all_basins):
        df=_safe(load_grace)
        if df.empty: return _empty()
        BASIN_COLORS={"CRB":NAVY,"UpperBasin":BLUE,"LowerBasin":MAROON,
                      "Green":GREEN,"SanJuan":ORANGE,"GrandCanyon":"#6A1B9A","Gila":TEAL}
        fig=go.Figure()
        fig.add_hline(y=0,line_dash="dash",line_color="#b0bec5",line_width=1)

        basins_to_plot=[basin] if not all_basins else list(BASIN_COLORS.keys())
        for bid in basins_to_plot:
            b=df[df["basin"]==bid].dropna(subset=["tws_mm"]).sort_values("date")
            if b.empty: continue
            col=BASIN_COLORS.get(bid,NAVY)
            b["roll"]=b["tws_mm"].rolling(smooth,center=True).mean()
            # Raw scatter (thin, low opacity)
            if not all_basins:
                colors_bar=[MAROON if v<0 else BLUE for v in b["tws_mm"]]
                err = (dict(type="data", array=b["tws_unc_mm"], visible=True,
                            color="rgba(110,110,110,0.5)", thickness=0.8, width=0)
                       if "tws_unc_mm" in b.columns and b["tws_unc_mm"].notna().any() else None)
                fig.add_trace(go.Bar(
                    x=b["date"],y=b["tws_mm"],
                    marker_color=colors_bar,marker_line_width=0,
                    opacity=0.5,name="Monthly TWS (± GRACE uncertainty)",
                    error_y=err,
                    hovertemplate="%{x|%b %Y}<br>TWS: %{y:.1f} mm<extra></extra>"))
            # Rolling mean
            fig.add_trace(go.Scatter(
                x=b["date"],y=b["roll"],mode="lines",
                line=dict(color=col,width=2.5),
                name=f"{basin_label(bid)} ({smooth}-mo mean)" if all_basins else f"{smooth}-mo mean",
                hovertemplate="%{x|%b %Y}<br>%{y:.1f} mm<extra></extra>"))

        # GRACE-FO gap annotation (Jun 2017 – Jun 2018)
        fig.add_vrect(
            x0="2017-06-01",x1="2018-06-01",
            fillcolor="rgba(200,200,200,0.25)",layer="below",line_width=0,
            annotation_text="GRACE-FO<br>gap",annotation_position="top left",
            annotation=dict(font_size=9,font_color="#78909c"))

        fig.update_layout(
            xaxis_title="Date",yaxis_title="TWS Anomaly (mm)",
            legend=dict(orientation="h",y=-0.2,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=55),height=320,
            paper_bgcolor="white",plot_bgcolor="white",bargap=0.1,
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("tws-seasonal-chart","figure"),Input("tws-basin","value"))
    def seasonal(basin):
        df=_safe(load_grace)
        if df.empty: return _empty()
        b=df[df["basin"]==basin].dropna(subset=["tws_mm"])
        if b.empty: return _empty("No GRACE data for basin")
        clim=b.groupby("month")["tws_mm"].agg(["mean","std"]).reset_index()
        fig=go.Figure()
        # Uncertainty band
        fig.add_trace(go.Scatter(
            x=list(clim["month"])+list(clim["month"][::-1]),
            y=list(clim["mean"]+clim["std"])+list((clim["mean"]-clim["std"])[::-1]),
            fill="toself",fillcolor="rgba(1,87,155,0.15)",
            line=dict(color="rgba(0,0,0,0)"),showlegend=True,name="±1 std",
            hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=clim["month"],y=clim["mean"],mode="lines+markers",
            line=dict(color=BLUE,width=2.5,shape="spline",smoothing=0.6),
            marker=dict(size=7,color=BLUE,line=dict(color="white",width=1.5)),
            name="Mean TWS",
            hovertemplate="Month %{x}<br>%{y:.1f} mm<extra></extra>"))
        fig.add_hline(y=0,line_dash="dash",line_color="#b0bec5",line_width=1)
        fig.update_layout(
            xaxis=dict(tickmode="array",tickvals=list(range(1,13)),ticktext=MONTHS),
            yaxis_title="TWS Anomaly (mm)",
            legend=dict(orientation="h",y=-0.2,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=55),height=320,
            paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("tws-deficit-chart","figure"),Input("tws-basin","value"))
    def deficit(basin):
        df=_safe(load_grace)
        if df.empty: return _empty()
        b=df[df["basin"]==basin].dropna(subset=["tws_mm"]).sort_values("date").copy()
        if b.empty: return _empty("No GRACE data")
        # Deficit = cumulative sum of negative anomalies (drought memory)
        b["neg"]=b["tws_mm"].clip(upper=0)
        b["deficit"]=b["neg"].cumsum()
        b["roll12"]=b["tws_mm"].rolling(12,center=True).mean()

        fig=go.Figure()
        fig.add_trace(go.Scatter(
            x=b["date"],y=b["deficit"],mode="lines",
            fill="tozeroy",fillcolor="rgba(140,29,64,0.2)",
            line=dict(color=MAROON,width=2),
            name="Cumulative TWS Deficit",
            hovertemplate="%{x|%b %Y}<br>Deficit: %{y:.0f} mm<extra></extra>"))
        fig.add_annotation(
            text="Cumulative TWS deficit = sum of months with negative TWS anomaly — experimental metric, not a calibrated drought index",
            xref="paper",yref="paper",x=0.01,y=0.03,showarrow=False,
            font=dict(size=9,color="#78909c"),xanchor="left")
        fig.update_layout(
            xaxis_title="Date",yaxis_title="Cumulative Deficit (mm)",
            legend=dict(orientation="h",y=-0.2,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=55),height=300,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("tws-smap-chart","figure"),Input("tws-basin","value"))
    def smap_chart(basin):
        df_sm=_safe(load_smap)
        df_v=_safe(load_vic_annual)
        # SMAP parquet is now wide-format with sm_surface/sm_rootzone/sm_profile columns
        bs=pd.DataFrame()
        smap_col = None
        for c in ["sm_surface","sm_rootzone","sm_m3m3"]:
            if not df_sm.empty and c in df_sm.columns:
                smap_col = c; break
        if smap_col:
            bs=df_sm[df_sm["basin"]==basin].dropna(subset=[smap_col]).copy()

        # SMAP unavailable — show VIC soil moisture only with note
        if bs.empty:
            if df_v.empty or "OUT_SOIL_MOIST" not in df_v.columns:
                return _empty("SMAP data unavailable — soil moisture values missing in cache\n(Re-run preprocessing to regenerate)")
            bv=df_v[df_v["basin"]==basin][["water_year","OUT_SOIL_MOIST"]].dropna().copy()
            if bv.empty:
                return _empty("SMAP data unavailable — no soil moisture data for this basin")
            fig=go.Figure()
            fig.add_trace(go.Scatter(
                x=bv["water_year"],y=bv["OUT_SOIL_MOIST"],
                mode="lines+markers",
                line=dict(color=BLUE,width=2.5,shape="spline"),
                marker=dict(size=7),name="VIC Total Soil Moisture (mm)",
                hovertemplate="WY %{x}<br>VIC SM: %{y:.1f} mm<extra></extra>"))
            fig.add_annotation(
                text="SMAP satellite data unavailable — showing VIC modeled soil moisture only",
                xref="paper",yref="paper",x=0.5,y=0.97,showarrow=False,
                font=dict(size=10,color="#e65100"),
                bgcolor="rgba(255,243,224,0.9)",bordercolor="#e65100",borderwidth=1)
            fig.update_layout(
                xaxis_title="Water Year",yaxis_title="Total Soil Moisture (mm)",
                legend=dict(orientation="h",y=-0.2,x=0,font=dict(size=10)),
                margin=dict(l=60,r=15,t=35,b=55),height=300,
                paper_bgcolor="white",plot_bgcolor="white",
                transition=dict(duration=400,easing="cubic-in-out"))
            return fig
        bs["year"]=pd.to_datetime(bs["date"]).dt.year
        smap_ann=bs.groupby("year")[smap_col].mean().reset_index()
        smap_ann.columns=["water_year","sm_smap"]

        fig=go.Figure()
        smap_label = {"sm_surface":"Surface (0–5 cm)","sm_rootzone":"Root Zone (0–100 cm)","sm_profile":"Profile"}.get(smap_col,"SMAP")
        fig.add_trace(go.Scatter(
            x=smap_ann["water_year"],y=smap_ann["sm_smap"],
            mode="lines+markers",
            line=dict(color=ORANGE,width=2.5,shape="spline"),
            marker=dict(size=7),name=f"SMAP {smap_label} (m³/m³)",
            hovertemplate="Year %{x}<br>SMAP SM: %{y:.4f} m³/m³<extra></extra>"))

        if not df_v.empty and "OUT_SOIL_MOIST" in df_v.columns:
            bv=df_v[df_v["basin"]==basin][["water_year","OUT_SOIL_MOIST"]].copy()
            # Normalise VIC soil moisture to same scale for comparison
            vic_norm=(bv["OUT_SOIL_MOIST"]-bv["OUT_SOIL_MOIST"].mean())/bv["OUT_SOIL_MOIST"].std()
            smap_norm=(smap_ann["sm_smap"]-smap_ann["sm_smap"].mean())/smap_ann["sm_smap"].std()
            fig.add_trace(go.Scatter(
                x=bv["water_year"],y=vic_norm,mode="lines+markers",
                line=dict(color=BLUE,width=2,dash="dash",shape="spline"),
                marker=dict(size=6),name="VIC SM (normalised)",
                hovertemplate="WY %{x}<br>VIC SM (z): %{y:.2f}<extra></extra>"))
            # Note on axis
            fig.update_layout(yaxis_title="SMAP SM (m³/m³)  |  VIC SM (z-score, right)")
        else:
            fig.update_layout(yaxis_title="SMAP Soil Moisture (m³/m³)")

        fig.update_layout(
            xaxis_title="Year",
            legend=dict(orientation="h",y=-0.2,x=0,font=dict(size=10)),
            margin=dict(l=60,r=15,t=10,b=55),height=300,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("tws-recovery-chart","figure"),Input("tws-basin","value"))
    def recovery_chart(basin):
        df=_safe(load_grace)
        if df.empty: return _empty()
        b=df[df["basin"]==basin].dropna(subset=["tws_mm"]).sort_values("date").copy()
        if b.empty: return _empty("No GRACE data")
        b["roll6"]=b["tws_mm"].rolling(6,center=True,min_periods=3).mean()
        b["positive"]=(b["roll6"]>0).astype(int)
        # Run-length encode recovery (positive) and deficit (negative) episodes
        run_ids=[]; cur_id=0; prev=None
        for v in b["positive"]:
            if v!=prev: cur_id+=1; prev=v
            run_ids.append(cur_id)
        b["run_id"]=run_ids
        # Compute run lengths
        run_info=b.groupby("run_id").agg(
            start=("date","first"),end=("date","last"),
            sign=("positive","first"),
            n_months=("date","count"),
            mean_tws=("tws_mm","mean")).reset_index()
        fig=go.Figure()
        # Background shading for episodes
        for _,r in run_info.iterrows():
            if r["n_months"]>=3:  # only show runs ≥ 3 months
                c="rgba(46,125,50,0.15)" if r["sign"]==1 else "rgba(140,29,64,0.1)"
                fig.add_vrect(x0=r["start"],x1=r["end"],
                              fillcolor=c,layer="below",line_width=0)
        # Line of 6-month rolling mean
        fig.add_hline(y=0,line_dash="dash",line_color="#b0bec5",line_width=1)
        fig.add_trace(go.Scatter(
            x=b["date"],y=b["roll6"],mode="lines",
            line=dict(color=NAVY,width=2.5),name="6-mo rolling mean",
            hovertemplate="%{x|%b %Y}<br>6-mo mean: %{y:.1f} mm<extra></extra>"))
        # Mark recovery episodes ≥ 6 months with annotation
        for _,r in run_info[run_info["sign"]==1].iterrows():
            if r["n_months"]>=6:
                mid_date=r["start"]+(r["end"]-r["start"])/2
                fig.add_annotation(x=mid_date,y=b["roll6"].max()*0.85,
                    text=f" {r['n_months']}mo",showarrow=False,
                    font=dict(size=8,color=GREEN),bgcolor="rgba(255,255,255,0.7)")
        # Legend patches
        fig.add_trace(go.Scatter(x=[None],y=[None],mode="markers",
            marker=dict(size=12,color="rgba(46,125,50,0.4)",symbol="square"),
            name="Recovery (≥3 mo)", showlegend=True))
        fig.add_trace(go.Scatter(x=[None],y=[None],mode="markers",
            marker=dict(size=12,color="rgba(140,29,64,0.3)",symbol="square"),
            name="Deficit (≥3 mo)", showlegend=True))
        fig.update_layout(
            xaxis_title="Date",yaxis_title="TWS Anomaly — 6-mo mean (mm)",
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=60),height=280,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("tws-findings","children"),Input("tws-basin","value"))
    def findings(basin):
        df=_safe(load_grace)
        if df.empty: return " Key findings will appear after preprocessing is complete."
        b=df[df["basin"]==basin].dropna(subset=["tws_mm"]).sort_values("date")
        if b.empty: return "No GRACE data for selected basin."
        mn=b["tws_mm"].min(); mx=b["tws_mm"].max()
        amp=mx-mn
        b2=b.copy(); b2["t"]=np.arange(len(b2))
        tr=trend_ci(b2["tws_mm"],b2["t"])
        trend_str=(f"Long-term trend: {tr['slope']*12:+.2f} mm/yr "
        f"(95% CI [{tr['lo']*12:+.2f}, {tr['hi']*12:+.2f}]; "
        f"{'significant' if tr['pvalue']<0.05 else 'not significant'})."
        if tr["slope"] is not None else "")
        n_deficit=(b["tws_mm"]<0).sum()
        pct_def=n_deficit/len(b)*100
        return [html.Strong("Key Findings — "),
                f"{basin_label(basin)}: GRACE period {b['date'].min().year}–{b['date'].max().year}. ",
                f"TWS range: {mn:.0f} to {mx:.0f} mm (amplitude {amp:.0f} mm). ",
                f"{pct_def:.0f}% of months show negative TWS anomaly. {trend_str}"]

    @app.callback(Output("tws-dl-data","data"),Input("tws-dl-btn","n_clicks"),
                  Input("tws-basin","value"),prevent_initial_call=True)
    def download(n,basin):
        if not n: return None
        df=_safe(load_grace)
        if df.empty: return None
        b=df[df["basin"]==basin].copy()
        return dcc.send_data_frame(b.to_csv,"crb_grace_tws.csv",index=False)
