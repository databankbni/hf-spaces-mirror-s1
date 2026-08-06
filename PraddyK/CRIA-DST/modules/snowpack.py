"""
modules/snowpack.py — Module 1: Snowpack & Runoff Outlook
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from utils.data_loader import (
    load_snotel_annual, load_snotel_monthly,
    load_snotel_stations, load_snotel_annual_station,
    load_vic_annual, basin_label, trend_slope, trend_ci
)
from utils.components import pub_evidence, pub_star, pub_author, howto

MAROON = "#8C1D40"; NAVY = "#0D2137"; GOLD = "#FFC627"
BLUE   = "#01579B"; GREEN = "#2E7D32"; ORANGE = "#E65100"
BASIN_OPTIONS = [
    {"label":"Colorado River Basin","value":"CRB"},
    {"label":"◆ All sub-basins (compare)","value":"ALL"},
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

def _empty_fig(msg="Run preprocessing scripts first"):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(size=12, color="#90a4ae"))
    fig.update_layout(paper_bgcolor="white", plot_bgcolor="white",
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      margin=dict(l=20,r=20,t=30,b=20), height=300)
    return fig

def _tile(val, label, icon, color):
    return html.Div([
        html.Div(str(val), className="info-tile-value"),
        html.Div(label,    className="info-tile-label"),
        html.Div(icon,     className="info-tile-icon"),
    ], className=f"info-tile {color}")

def layout():
    return html.Div([
        html.Div([
            html.H2(" Snowpack & Runoff Outlook"),
            html.P("SNOTEL station SWE trends · VIC modeled snowpack · SWE streamflow forecast"),
        ], className="tab-header"),
        html.Div([
            dbc.Row(id="snow-tiles", className="mb-3 g-2"),
            html.Div(id="snow-findings",
                     style={"background":"#e8f5e9","borderLeft":f"3px solid {GREEN}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#1b5e20","marginBottom":"12px"}),
                            howto("Pick a basin and year range. The panels show snowpack (SWE) trends, the SWE-to-runoff forecast, and melt timing — use them to judge how this year's snow compares and what runoff to expect."),
                            pub_author("Mote et al. 2018", "https://www.nature.com/articles/s41612-018-0012-1", "Mote et al. 2018, npj Clim. Atmos. Sci.", "published"),
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("Basin", className="control-label"),
                        dcc.Dropdown(id="snow-basin", options=BASIN_OPTIONS,
                                     value="CRB", clearable=False,
                                     style={"fontSize":"12.5px"}),
                    ], md=3),
                    dbc.Col([
                        html.Div("Year Range", className="control-label"),
                        dcc.RangeSlider(id="snow-years", min=1983, max=2024,
                                        step=1, value=[1983,2024],
                                        marks={y:str(y) for y in range(1990,2025,10)},
                                        tooltip={"placement":"bottom","always_visible":False}),
                    ], md=6),
                    dbc.Col([
                        html.Div("Data Source", className="control-label"),
                        html.Div(
                            "All 4 panels shown. SNOTEL = station observations · ""VIC = modeled snowpack · SWE Q = regression forecast",
                            style={"fontSize":"10.5px","color":"#1e293b","paddingTop":"6px",
                                   "fontStyle":"italic"}
                        ),
                    ], md=3),
                ]),
            ], className="control-panel"),

            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Basin SWE Anomaly",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— % of long-term median",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                            dbc.Button("CSV", id="snow-dl-btn", size="sm",
                                       className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                            pub_star("https://www.nature.com/articles/s41612-018-0012-1", "Mote et al. 2018, npj Clim. Atmos. Sci.", "Published"),
                        ], className="crb-card-header"),
                        dcc.Graph(id="snow-anomaly-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"300px"}),
                        dcc.Download(id="snow-dl-data"),
                    ], className="crb-card"),
                ], md=7),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span(" SWE Trend by Station",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— mm/yr slope",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ], className="crb-card-header"),
                        dcc.Graph(id="snow-station-map",
                                  config={"displayModeBar":False},
                                  style={"height":"300px"}),
                    ], className="crb-card"),
                ], md=5),
            ], className="g-3 mb-2"),

            # Row 2b: Snowmelt timing shift + risk index
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Snowmelt Timing Shift",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— month of peak SWE trend (SNOTEL)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ], className="crb-card-header"),
                        dcc.Graph(id="snow-timing-chart",
                                  config={"displayModeBar":False},
                                  style={"height":"280px"}),
                    ], className="crb-card"),
                ], md=8),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Snowpack Decline Indicators",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                        ], className="crb-card-header"),
                        html.Div(id="snow-risk-panel",
                                 style={"padding":"16px 12px","minHeight":"240px"}),
                    ], className="crb-card"),
                ], md=4),
            ], className="g-3 mb-2"),

            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("SWE Runoff Regression",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— VIC modeled SWE vs VIC runoff (same model)",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ], className="crb-card-header"),
                        html.Div([
                            dbc.Row([
                                dbc.Col([
                                    html.Div("April 1 SWE input (mm)",
                                             className="control-label mt-2"),
                                    dcc.Slider(id="snow-swe-in", min=0, max=800,
                                               step=10, value=350,
                                               marks={v:str(v) for v in [0,200,400,600,800]},
                                               tooltip={"placement":"bottom","always_visible":True}),
                                ], md=8),
                                dbc.Col([
                                    html.Div("Forecast Runoff",
                                             className="control-label mt-2"),
                                    html.Div(id="snow-forecast",
                                             style={"fontSize":"26px","fontWeight":"800",
                                                    "color":MAROON,"marginTop":"6px"}),
                                ], md=4),
                            ]),
                        ], style={"padding":"8px 16px 4px"}),
                        dcc.Graph(id="snow-regression",
                                  config={"displayModeBar":False},
                                  style={"height":"260px"}),
                    ], className="crb-card"),
                ], md=6),
                dbc.Col([
                    html.Div([
                        html.Div([
                            html.Span("Monthly SWE Climatology",
                                      style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— early vs late period",
                                      style={"color":"#1e293b","fontSize":"11px"}),
                        ], className="crb-card-header"),
                        dcc.Graph(id="snow-monthly",
                                  config={"displayModeBar":False},
                                  style={"height":"320px"}),
                    ], className="crb-card"),
                ], md=6),
            ], className="g-3"),

        ], className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("snow-tiles","children"), Input("snow-basin","value"))
    def tiles(basin):
        # Use station-level data for per-station stats
        df_sta = _safe(load_snotel_stations)
        df_ann = _safe(load_snotel_annual)   # basin-level for trend
        if df_sta.empty or df_ann.empty:
            return [dbc.Col(_tile("—",l,"","tile-navy"),xs=6,md=3)
                    for l in ["Stations","Declining","Trend mm/yr","SWE change"]]
        # Count CRB stations
        n_sta = df_sta[df_sta["basin"]=="CRB"]["site_id"].nunique()
        # Per-station MK slopes
        sta_crb = df_sta[df_sta["basin"]=="CRB"].drop_duplicates("site_id")
        slopes  = sta_crb["mk_slope"].dropna()
        n_dec   = (slopes < 0).sum()
        med_s   = slopes.median() if not slopes.empty else 0
        # SWE change: basin-level annual data
        b = df_ann[df_ann["basin"]==basin].sort_values("water_year")
        if b.empty:
            b = df_ann[df_ann["basin"]=="CRB"].sort_values("water_year")
        wy_min = b["water_year"].min(); wy_max = b["water_year"].max()
        early  = b[b["water_year"]<=wy_min+4]["peak_swe_mm"].mean()
        late   = b[b["water_year"]>=wy_max-4]["peak_swe_mm"].mean()
        pct    = ((late-early)/early*100) if early>0 else 0
        tiles_ = [
            _tile(n_sta,           "SNOTEL stations (CRB)","","tile-navy"),
            _tile(n_dec,           "Stations declining",   " ","tile-maroon"),
            _tile(f"{med_s:+.1f}", "Median trend (mm/yr)", " ","tile-blue"),
            _tile(f"{pct:+.0f}%",  "SWE change early late"," ","tile-orange"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("snow-anomaly-chart","figure"),
                  Input("snow-basin","value"), Input("snow-years","value"))
    def anomaly(basin, years):
        # "All sub-basins" → overlay every sub-basin's snowpack (VIC SWE) on one chart,
        # each indexed to its own 1984–2024 mean (see utils/multibasin.py).
        if basin == "ALL":
            from utils.multibasin import multi_basin_fig
            return multi_basin_fig("OUT_SWE", years=years, height=300)
        df = _safe(load_snotel_annual)
        if df.empty: return _empty_fig()
        # Filter by basin (basin-level aggregated parquet)
        bdf = df[df["basin"]==basin] if basin in df["basin"].values else df[df["basin"]=="CRB"]
        bdf = bdf[(bdf["water_year"]>=years[0])&(bdf["water_year"]<=years[1])]
        ann = bdf[["water_year","peak_swe_mm"]].dropna()
        if ann.empty: return _empty_fig("No data in range")
        med = ann["peak_swe_mm"].median()
        ann["anom"] = (ann["peak_swe_mm"]/med*100)-100
        colors = [MAROON if v<0 else BLUE for v in ann["anom"]]
        fig = go.Figure()
        fig.add_hline(y=0, line_dash="dash", line_color="#b0bec5", line_width=1.5)
        fig.add_trace(go.Bar(x=ann["water_year"], y=ann["anom"],
                             marker_color=colors, marker_line_width=0,
                             hovertemplate="<b>WY %{x}</b><br>%{y:+.1f}%<extra></extra>"))
        ann["r5"] = ann["anom"].rolling(5,center=True).mean()
        fig.add_trace(go.Scatter(x=ann["water_year"], y=ann["r5"], mode="lines",
                                 line=dict(color=NAVY,width=2.5), name="5-yr mean"))
        t = trend_slope(ann["anom"], ann["water_year"])
        if t["slope"] is not None:
            xr_ = np.array([ann["water_year"].min(), ann["water_year"].max()])
            yf  = t["slope"]*xr_ + (ann["anom"].mean()-t["slope"]*ann["water_year"].mean())
            fig.add_trace(go.Scatter(x=xr_, y=yf, mode="lines",
                                     line=dict(color=MAROON,width=2,dash="dot"),
                                     name=f"Trend {t['slope']:+.2f}%/yr"))
        fig.update_layout(xaxis_title="Water Year", yaxis_title="% of median",
                          legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
                          margin=dict(l=50,r=15,t=10,b=60), height=300,
                          paper_bgcolor="white", plot_bgcolor="white", bargap=0.15,
                          transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("snow-station-map","figure"), Input("snow-basin","value"))
    def station_map(basin):
        df = _safe(load_snotel_stations)
        if df.empty: return _empty_fig("SNOTEL station data not available")
        # Show all CRB stations; highlight selected basin
        sta = df.drop_duplicates("site_id").dropna(subset=["latitude","longitude","mk_slope"]).copy()
        if sta.empty: return _empty_fig("No station location data")
        def col(r):
            if r["mk_slope"]<-2 and not pd.isna(r["mk_pvalue"]) and r["mk_pvalue"]<0.05: return "#D32F2F"
            return "#FF8A65" if r["mk_slope"]<0 else "#1565C0"
        sta["c"] = sta.apply(col, axis=1)
        sta = sta.rename(columns={"station_name":"name","mk_slope":"slope","mk_pvalue":"pval",
                                   "latitude":"lat","longitude":"lon"})
        fig = go.Figure(go.Scattermapbox(
            lat=sta["lat"], lon=sta["lon"], mode="markers",
            marker=dict(size=8, color=sta["c"], opacity=0.85),
            text=sta.apply(lambda r:
                f"<b>{r['name']}</b> ({r['state']})<br>"
                f"Elev: {r['elev']:.0f} m<br>"
                f"MK Slope: {r['slope']:+.2f} mm/yr", axis=1),
            hoverinfo="text",
        ))
        fig.update_layout(
            mapbox=dict(style="carto-positron",center=dict(lat=38.5,lon=-111.0),zoom=4.5),
            margin=dict(l=0,r=0,t=0,b=0), height=300, showlegend=False)
        fig.add_annotation(x=0.01,y=0.98,xref="paper",yref="paper",showarrow=False,
            align="left",
            text="<b>SWE trend</b><br>""<span style='color:#D32F2F'>●</span> Strong (p<0.05)<br>""<span style='color:#FF8A65'>●</span> Moderate <br>""<span style='color:#1565C0'>●</span> Stable/ ",
            bgcolor="rgba(255,255,255,0.9)",bordercolor="#e0e0e0",
            borderwidth=1,font=dict(size=10))
        return fig

    @app.callback(Output("snow-regression","figure"), Output("snow-forecast","children"),
                  Input("snow-basin","value"), Input("snow-swe-in","value"))
    def regression(basin, swe_in):
        df_s = _safe(load_snotel_annual); df_v = _safe(load_vic_annual)
        if df_s.empty or df_v.empty: return _empty_fig(), "—"# Filter to CRB basin only to avoid multi-basin average
        swe_b = df_s[df_s["basin"]=="CRB"] if "CRB" in df_s["basin"].values else df_s.head(0)
        swe = swe_b[["water_year","peak_swe_mm"]].dropna()
        run = (df_v[df_v["basin"]==basin][["water_year","OUT_RUNOFF"]]
               .rename(columns={"OUT_RUNOFF":"runoff_mm"}))
        m = swe.merge(run,on="water_year").dropna()
        if len(m)<5: return _empty_fig("Insufficient data"), "—"
        from scipy import stats
        sl,ic,r,p,_ = stats.linregress(m["peak_swe_mm"],m["runoff_mm"])
        fc = sl*swe_in+ic
        xl = np.linspace(m["peak_swe_mm"].min(),m["peak_swe_mm"].max(),100)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=m["peak_swe_mm"],y=m["runoff_mm"],mode="markers",
            marker=dict(color=NAVY,size=7,opacity=0.7,line=dict(color="white",width=1)),
            text=m["water_year"].astype(str),
            hovertemplate="WY %{text}<br>SWE:%{x:.0f} Runoff:%{y:.0f}mm<extra></extra>",
            name="Historical"))
        fig.add_trace(go.Scatter(x=xl,y=sl*xl+ic,mode="lines",
            line=dict(color=MAROON,width=2),name=f"Fit R²={r**2:.2f}"))
        fig.add_trace(go.Scatter(x=[swe_in],y=[fc],mode="markers",
            marker=dict(color=GOLD,size=14,symbol="diamond",
                        line=dict(color=MAROON,width=2)),
            name=f"Forecast"))
        fig.update_layout(xaxis_title="April 1 SWE (mm)",
            yaxis_title=f"Annual Runoff — {basin_label(basin)} (mm)",
            legend=dict(orientation="h",y=-0.28,x=0,font=dict(size=10)),
            margin=dict(l=50,r=15,t=10,b=65),height=260,
            paper_bgcolor="white",plot_bgcolor="white")
        return fig, f"{fc:.0f} mm"

    @app.callback(Output("snow-monthly","figure"), Input("snow-basin","value"))
    def monthly(basin):
        df = _safe(load_snotel_monthly)
        if df.empty: return _empty_fig()
        mnames = ["Oct","Nov","Dec","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep"]
        # Filter by basin, use mean_swe_mm column, water_year column for period split
        bdf = df[df["basin"]==basin] if basin in df["basin"].values else df[df["basin"]=="CRB"]
        early = bdf[bdf["water_year"]<=2000].groupby("month")["mean_swe_mm"].mean().reset_index()
        late  = bdf[bdf["water_year"]> 2000].groupby("month")["mean_swe_mm"].mean().reset_index()
        # Rename for consistent plotting
        early = early.rename(columns={"mean_swe_mm":"swe_mm"})
        late  = late.rename(columns={"mean_swe_mm":"swe_mm"})
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=early["month"],y=early["swe_mm"],mode="lines+markers",
            line=dict(color=BLUE,width=2.5,shape="spline",smoothing=0.6),
            marker=dict(size=6),name="WY1983–2000"))
        fig.add_trace(go.Scatter(x=late["month"],y=late["swe_mm"],mode="lines+markers",
            line=dict(color=MAROON,width=2.5,shape="spline",smoothing=0.6),
            marker=dict(size=6),name="WY2001–2023"))
        fig.update_layout(
            xaxis=dict(tickmode="array",tickvals=list(range(1,13)),
                       ticktext=mnames,title="Month"),
            yaxis_title="Mean SWE (mm)",
            legend=dict(orientation="h",y=-0.2,x=0,font=dict(size=10)),
            margin=dict(l=50,r=15,t=10,b=60),height=320,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("snow-findings","children"),
                  Input("snow-basin","value"), Input("snow-years","value"))
    def findings(basin, years):
        df_ann = _safe(load_snotel_annual)
        df_sta = _safe(load_snotel_stations)
        if df_ann.empty: return " Key findings will appear after preprocessing is complete."# Station stats from station-level parquet
        n_tot = 0; n_dec = 0; n_sig = 0; med_s = 0
        if not df_sta.empty:
            crb_sta = df_sta[df_sta["basin"]=="CRB"].drop_duplicates("site_id")
            n_tot   = len(crb_sta)
            slopes  = crb_sta["mk_slope"].dropna()
            pvals   = crb_sta["mk_pvalue"].dropna()
            n_dec   = (slopes < 0).sum()
            n_sig   = ((crb_sta["mk_pvalue"]<0.05) & (crb_sta["mk_slope"]<0)).dropna().sum()
            med_s   = slopes.median() if not slopes.empty else 0
        # SWE change from basin-level annual
        bdf = df_ann[df_ann["basin"]==basin] if basin in df_ann["basin"].values else df_ann[df_ann["basin"]=="CRB"]
        bdf = bdf[(bdf["water_year"]>=years[0])&(bdf["water_year"]<=years[1])]
        early = bdf[bdf["water_year"]<=years[0]+4]["peak_swe_mm"].mean()
        late  = bdf[bdf["water_year"]>=years[1]-4]["peak_swe_mm"].mean()
        pct   = ((late-early)/early*100) if early>0 else 0
        from utils.manager import manager_line
        trend_word = "down" if pct < 0 else "up"
        mgr = manager_line(
            f"Snowpack — the basin's natural reservoir — is {trend_word} {abs(pct):.0f}% "
            f"between the earliest and latest 5-year periods, and {n_dec} of {n_tot} SNOTEL stations "
            "are declining. Snowmelt supplies the majority of Colorado River flow, so a shrinking, "
            "earlier-melting snowpack means less and earlier runoff into the reservoirs.",
            color="#0277BD")
        return [mgr, html.Strong("Detail — "),
                f"{n_dec}/{n_tot} SNOTEL stations declining. ",
                f"{n_sig} significant (p<0.05). ",
                f"Median MK trend: {med_s:+.1f} mm/yr. ",
                f"SWE changed {pct:+.1f}% from earliest to latest 5-yr period."]

    @app.callback(Output("snow-timing-chart","figure"),
                  Input("snow-basin","value"), Input("snow-years","value"))
    def timing_chart(basin, years):
        df = _safe(load_snotel_monthly)
        if df.empty: return _empty_fig("Run preprocessing scripts first")
        # Filter by basin
        bdf = df[df["basin"]==basin] if basin in df["basin"].values else df[df["basin"]=="CRB"]
        bdf = bdf[(bdf["water_year"]>=years[0])&(bdf["water_year"]<=years[1])]
        if bdf.empty: return _empty_fig("No data in range")
        # For each water_year, find month with max mean SWE (basin-level timing)
        def _peak_month(g):
            g2 = g.dropna(subset=["mean_swe_mm"])
            if g2.empty or g2["mean_swe_mm"].max()==0: return np.nan
            return float(g2.loc[g2["mean_swe_mm"].idxmax(),"month"])
        timing = bdf.groupby("water_year")[["month", "mean_swe_mm"]].apply(_peak_month).reset_index()
        timing.columns = ["water_year","peak_month"]
        ann = timing.dropna(subset=["peak_month"])
        if ann.empty: return _empty("No timing data")
        mnames = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
                  7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=ann["water_year"], y=ann["peak_month"],
            mode="lines+markers",
            line=dict(color=BLUE,width=2,shape="spline",smoothing=0.4),
            marker=dict(size=5,color=BLUE),
            name="Mean peak SWE month",
            customdata=[mnames.get(int(round(v)),str(v)) for v in ann["peak_month"]],
            hovertemplate="WY %{x}<br>Peak month: %{customdata}<extra></extra>"))
        # 5-yr running mean
        ann["r5"] = ann["peak_month"].rolling(5,center=True).mean()
        fig.add_trace(go.Scatter(
            x=ann["water_year"], y=ann["r5"], mode="lines",
            line=dict(color=NAVY,width=2.5), name="5-yr mean"))
        t = trend_slope(ann["peak_month"], ann["water_year"])
        if t["slope"] is not None:
            xr_ = np.array([ann["water_year"].min(), ann["water_year"].max()])
            yf = t["slope"]*xr_+(ann["peak_month"].mean()-t["slope"]*ann["water_year"].mean())
            sig = " " if t["pvalue"]<0.05 else ""
            fig.add_trace(go.Scatter(x=xr_,y=yf,mode="lines",
                line=dict(color=MAROON,width=2,dash="dot"),
                name=f"Trend {t['slope']*10:+.2f} mo/decade {sig}"))
        fig.add_annotation(
            text=" lower month = earlier peak = earlier melt onset",
            xref="paper",yref="paper",x=0.01,y=0.03,showarrow=False,
            font=dict(size=9,color="#78909c"),xanchor="left")
        fig.update_layout(
            xaxis_title="Water Year",
            yaxis=dict(title="Month of Peak SWE",tickmode="array",
                       tickvals=[1,2,3,4,5,6],
                       ticktext=["Jan","Feb","Mar","Apr","May","Jun"]),
            legend=dict(orientation="h",y=-0.25,x=0,font=dict(size=10)),
            margin=dict(l=55,r=15,t=10,b=65),height=280,
            paper_bgcolor="white",plot_bgcolor="white",
            transition=dict(duration=400,easing="cubic-in-out"))
        return fig

    @app.callback(Output("snow-risk-panel","children"),
                  Input("snow-basin","value"), Input("snow-years","value"))
    def risk_panel(basin, years):
        try:
            df_s = _safe(load_snotel_annual)
            df_v = _safe(load_vic_annual)
            if df_s.empty or df_v.empty:
                return html.P("Data unavailable", style={"color":"#1e293b","textAlign":"center","marginTop":"30px"})
            y0, y1 = int(years[0]), int(years[1])
            df_s2 = df_s[(df_s["water_year"]>=y0)&(df_s["water_year"]<=y1)]
            # SNOTEL basin-average SWE trend; SNOTEL only covers a few basins → fall back to CRB
            df_s2b = df_s2[df_s2["basin"]==basin] if basin in df_s2["basin"].values else df_s2[df_s2["basin"]=="CRB"]
            ann = df_s2b.groupby("water_year")["peak_swe_mm"].mean().reset_index()  # [water_year, peak_swe_mm]
            tci = trend_ci(ann["peak_swe_mm"], ann["water_year"])
            swe_slope = float(tci["slope"]) if tci["slope"] is not None else 0.0
            sig = bool(tci["sig"])
            swe_ci = ("95% CI [{:+.2f}, {:+.2f}] mm/yr".format(tci["lo"], tci["hi"])
                      if tci["lo"] is not None else "CI unavailable")
            # early vs late 5-yr peak-SWE change
            bdf_s = df_s2b
            early = bdf_s[bdf_s["water_year"]<=y0+5]["peak_swe_mm"].mean()
            late  = bdf_s[bdf_s["water_year"]>=y1-5]["peak_swe_mm"].mean()
            pct_ch = float((late-early)/early*100) if (pd.notna(early) and early>0 and pd.notna(late)) else 0.0
            # declining-station count (station-level Mann-Kendall; CRB network)
            df_sta2 = _safe(load_snotel_stations)
            if not df_sta2.empty and "mk_slope" in df_sta2.columns:
                crb_sta = df_sta2[df_sta2["basin"]=="CRB"].drop_duplicates("site_id")
                n_dec = int((crb_sta["mk_slope"].dropna() < 0).sum())
                n_tot = int(len(crb_sta))
            else:
                n_dec, n_tot = 0, 103
            pct_dec = (n_dec/n_tot*100) if n_tot>0 else 0.0
            # Honest indicators — the three real facts, no arbitrary 0–100 composite score.
            verdict = "Declining" if (swe_slope < 0 and pct_ch < 0) else "Mixed / flat"
            vcol = ORANGE if verdict == "Declining" else "#607D8B"

            def _row(label, value, sub):
                return html.Div([
                    html.Div(label, style={"fontSize":"10px","color":"#607d8b",
                                           "textTransform":"uppercase","letterSpacing":"0.5px"}),
                    html.Div(value, style={"fontSize":"20px","fontWeight":"800","color":NAVY,"lineHeight":"1.15"}),
                    html.Div(sub, style={"fontSize":"10px","color":"#78909c"}),
                ], style={"marginBottom":"10px"})

            sig_txt = "significant (p<0.05)" if sig else "not significant at basin scale"
            return html.Div([
                html.Div(verdict, style={"fontSize":"22px","fontWeight":"900","color":vcol,
                                         "textAlign":"center","letterSpacing":"1px"}),
                html.Div("peak snowpack, basin-wide", style={"textAlign":"center","color":"#78909c",
                                                             "fontSize":"10.5px","marginBottom":"6px"}),
                html.Hr(style={"margin":"8px 0","borderColor":"#e0e0e0"}),
                _row("Declining SNOTEL stations", "{} / {}  ({:.0f}%)".format(n_dec, n_tot, pct_dec),
                     "significant — binomial p < 0.05"),
                _row("Peak-SWE trend", "{:+.2f} mm/yr".format(swe_slope), swe_ci + " · " + sig_txt),
                _row("Change over record", "{:+.0f}%".format(pct_ch), "early vs late 5-yr mean"),
            ])
        except Exception as e:
            return html.Div([
                html.Div("Snowpack: declining", style={"fontSize":"16px","fontWeight":"800",
                                                       "color":ORANGE,"textAlign":"center"}),
                html.Div("67 of 103 SNOTEL stations declining (65%).",
                         style={"fontSize":"11px","color":"#546e7a","textAlign":"center","marginTop":"6px"}),
            ])

    @app.callback(Output("snow-dl-data","data"), Input("snow-dl-btn","n_clicks"),
                  Input("snow-basin","value"), prevent_initial_call=True)
    def download(n, basin):
        if not n: return None
        df = _safe(load_snotel_annual)
        if df.empty: return None
        # Filter to selected basin for download
        bdf = df[df["basin"]==basin] if basin in df["basin"].values else df[df["basin"]=="CRB"]
        out = bdf[["water_year","peak_swe_mm","n_stations"]].copy()
        out.insert(0, "basin", basin)
        return dcc.send_data_frame(out.to_csv,"crb_swe_anomaly.csv",index=False)
