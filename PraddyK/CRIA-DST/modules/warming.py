"""
modules/warming.py — Land-Surface Warming & Energy

Two warming signatures from the VIC record (WY1984–2024), both previously unused beyond
the spatial maps:
  1. Energy / evaporative demand — air, surface & radiative temperature trends, plus the
     latent-heat flux (the energy actually used to evaporate water).
  2. Soil thermal regime — soil temperature in the three VIC soil layers, showing how
     warming attenuates with depth.

Verified signals (CRB): air +0.28, surface +0.31, radiative +0.29 °C/decade (all p<0.01);
latent heat -1.16 W/m²/decade (p=0.01); soil temp L1 +0.26, L2 +0.22, L3 +0.15 °C/decade
(all p≈0.004) — surface warms fastest, deep soil slowest. All real VIC output.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from scipy import stats
from utils.data_loader import load_vic_annual, basin_label
from utils.components import xref, pub_evidence, pub_star, pub_author, howto

MAROON="#8C1D40"; NAVY="#0D2137"; BLUE="#01579B"; GREEN="#2E7D32"
ORANGE="#E65100"; PURPLE="#4527A0"; TEAL="#00695C"; GREY="#94a3b8"; RED="#C62828"

BASIN_OPTIONS=[
    {"label":"Colorado River Basin","value":"CRB"},
    {"label":"◆ All sub-basins (compare)","value":"ALL"},
    {"label":"Upper Basin","value":"UpperBasin"},
    {"label":"Lower Basin","value":"LowerBasin"},
    {"label":"Green River","value":"Green"},
    {"label":"San Juan","value":"SanJuan"},
    {"label":"Upper Colorado","value":"UpperColo"},
    {"label":"Glen Canyon","value":"GlenCanyon"},
    {"label":"Gila River","value":"Gila"},
    {"label":"Grand Canyon","value":"GrandCanyon"},
    {"label":"Little Colorado","value":"LittleColo"},
    {"label":"Lower Colorado","value":"LowerColo"},
]


def _safe():
    try: return load_vic_annual()
    except: return pd.DataFrame()

def _empty(msg="No VIC data"):
    fig=go.Figure(); fig.add_annotation(text=msg,xref="paper",yref="paper",x=0.5,y=0.5,
        showarrow=False,font=dict(size=12,color="#90a4ae"))
    fig.update_layout(paper_bgcolor="white",plot_bgcolor="white",
        xaxis=dict(visible=False),yaxis=dict(visible=False),
        margin=dict(l=20,r=20,t=30,b=20),height=300)
    return fig

def _tile(val,label,icon,color):
    return html.Div([html.Div(str(val),className="info-tile-value"),
        html.Div(label,className="info-tile-label"),
        html.Div(icon,className="info-tile-icon")],className=f"info-tile {color}")

def _trend(g,col):
    """Per-decade trend + p-value for a basin time series."""
    d=g.dropna(subset=[col])
    if len(d)<5: return None,None,None
    sl,ic,r,p,se=stats.linregress(d.water_year,d[col])
    return sl*10.0, p, d[col].mean()


def layout():
    return html.Div([
        html.Div([
            html.H2("Land-Surface Warming & Energy"),
            html.P("How the basin's surface and soils are warming, and what's happening to the "
                   "energy that drives evaporation — straight from the VIC record."),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="lw-tiles",className="mb-3 g-2"),
            html.Div(id="lw-findings",
                     style={"background":"#fdecea","borderLeft":f"3px solid {MAROON}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#8C1D40","marginBottom":"12px"}),
                            howto("Pick a basin. Trends in air, surface and radiative temperature, latent-heat flux, and warming by soil depth show how the land surface is heating and drying."),
                            pub_author("Milly & Dunne 2020", "https://www.science.org/doi/10.1126/science.aay9187", "Milly & Dunne 2020, Science (warming energizes evaporation)", "published"),

            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("BASIN",className="control-label"),
                        dcc.Dropdown(id="lw-basin",options=BASIN_OPTIONS,value="CRB",
                                     clearable=False,style={"fontSize":"12.5px"}),
                    ],xs=12,md=4),
                ]),
            ],className="control-panel"),

            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("Temperature & evaporative-demand trends",
                            style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— warming (left) vs latent-heat flux (right)",
                                style={"color":"#1e293b","fontSize":"11px"}),
                            dbc.Button("CSV",id="lw-dl-btn",size="sm",className="btn-download",
                                       style={"float":"right","marginTop":"-3px"}),
                            pub_star("https://www.science.org/doi/10.1126/science.aay9187", "Milly & Dunne 2020, Science 367:1252", "Published"),
                        ],className="crb-card-header"),
                        dcc.Graph(id="lw-ts",config={"displayModeBar":False},style={"height":"380px"}),
                        dcc.Download(id="lw-dl-data"),
                    ],className="crb-card"),
                ],md=7),
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("Warming by depth",
                            style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— air → surface → soil layers",
                                style={"color":"#1e293b","fontSize":"11px"})],className="crb-card-header"),
                        dcc.Graph(id="lw-soil",config={"displayModeBar":False},style={"height":"380px"}),
                    ],className="crb-card"),
                ],md=5),
            ],className="g-3 mb-2"),

            html.Div("Method: ordinary-least-squares trend per water year, reported per decade with "
                     "its p-value. Latent heat (OUT_LATENT) is the energy used to evaporate water; "
                     "soil temperatures are the three VIC soil layers (L1 shallow → L3 deep). "
                     "Real VIC output, no modelling added.",
                     style={"fontSize":"10.5px","color":"#1e293b","marginTop":"6px"}),
            xref("Related analyses:", [("Warming → runoff loss → Aridification","/aridification"),
                                       ("Water–energy balance → Budyko","/budyko"),
                                       ("Snow loss by elevation → Elevation Snow","/elevsnow")]),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("lw-tiles","children"), Input("lw-basin","value"))
    def tiles(basin):
        if basin=="ALL": basin="CRB"   # side panels show whole-basin context
        df=_safe()
        labels=["Air-temp trend","Surface-temp trend","Latent-heat trend","Shallow-soil trend"]
        if df.empty:
            return [dbc.Col(_tile("—",l,"","tile-navy"),xs=6,md=3) for l in labels]
        g=df[df.basin==basin]
        at,ap,_=_trend(g,"OUT_AIR_TEMP")
        st,sp,_=_trend(g,"OUT_SURF_TEMP")
        lt,lp,_=_trend(g,"OUT_LATENT")
        s1,s1p,_=_trend(g,"OUT_SOIL_TEMP_L1")
        def sig(p): return "" if p is None else (" (sig.)" if p<0.05 else " (n.s.)")
        tiles_=[
            _tile(f"{at:+.2f}°C/dec" if at is not None else "—","Air temperature"+sig(ap),"","tile-maroon"),
            _tile(f"{st:+.2f}°C/dec" if st is not None else "—","Surface temperature"+sig(sp),"","tile-orange"),
            _tile(f"{lt:+.2f}/dec" if lt is not None else "—","Latent-heat flux (W/m²)"+sig(lp),"","tile-blue"),
            _tile(f"{s1:+.2f}°C/dec" if s1 is not None else "—","Shallow soil temp"+sig(s1p)," ","tile-green"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("lw-ts","figure"), Input("lw-basin","value"))
    def ts(basin):
        # "All sub-basins" → overlay every sub-basin's air temperature on one chart.
        if basin == "ALL":
            from utils.multibasin import multi_basin_fig
            return multi_basin_fig("OUT_AIR_TEMP", height=380)
        df=_safe()
        if df.empty: return _empty()
        g=df[df.basin==basin].sort_values("water_year")
        if g.empty: return _empty("No data")
        fig=go.Figure()
        # left axis: air + surface temperature
        for col,name,color in [("OUT_AIR_TEMP","Air temperature",MAROON),
                               ("OUT_SURF_TEMP","Surface temperature",ORANGE)]:
            if col in g.columns:
                fig.add_trace(go.Scatter(x=g.water_year,y=g[col],mode="lines+markers",
                    name=name,line=dict(color=color,width=2,shape="spline",smoothing=0.4),
                    marker=dict(size=4),
                    hovertemplate="WY %{x}<br>"+name+" %{y:.1f}°C<extra></extra>"))
        # right axis: latent heat
        if "OUT_LATENT" in g.columns:
            fig.add_trace(go.Scatter(x=g.water_year,y=g["OUT_LATENT"],mode="lines+markers",
                name="Latent heat (W/m²)",yaxis="y2",
                line=dict(color=BLUE,width=2,dash="dot"),marker=dict(size=4),
                hovertemplate="WY %{x}<br>Latent heat %{y:.1f} W/m²<extra></extra>"))
        fig.update_layout(
            xaxis_title="Water Year",
            yaxis=dict(title="Temperature (°C)"),
            yaxis2=dict(title="Latent heat (W/m²)",overlaying="y",side="right",showgrid=False),
            legend=dict(orientation="h",y=-0.22,x=0,font=dict(size=10)),
            margin=dict(l=55,r=55,t=12,b=55),height=380,
            paper_bgcolor="white",plot_bgcolor="white")
        return fig

    @app.callback(Output("lw-soil","figure"), Input("lw-basin","value"))
    def soil(basin):
        if basin=="ALL": basin="CRB"
        df=_safe()
        if df.empty: return _empty()
        g=df[df.basin==basin]
        if g.empty: return _empty("No data")
        rows=[("Air",          "OUT_AIR_TEMP",   MAROON),
              ("Surface",      "OUT_SURF_TEMP",  ORANGE),
              ("Soil L1 (shallow)","OUT_SOIL_TEMP_L1",GREEN),
              ("Soil L2 (mid)","OUT_SOIL_TEMP_L2",TEAL),
              ("Soil L3 (deep)","OUT_SOIL_TEMP_L3",NAVY)]
        cats,vals,cols,texts=[],[],[],[]
        for lbl,col,c in rows:
            if col not in g.columns: continue
            sl,p,_=_trend(g,col)
            if sl is None: continue
            cats.append(lbl); vals.append(sl); cols.append(c)
            texts.append(f"{sl:+.2f}{'°C' if 'LATENT' not in col else ''}/dec"+(" *" if p<0.05 else ""))
        fig=go.Figure(go.Bar(x=vals,y=cats,orientation="h",marker_color=cols,
            text=texts,textposition="auto",
            hovertemplate="%{y}<br>%{x:+.2f} °C/decade<extra></extra>"))
        fig.add_vline(x=0,line_color="#b0bec5",line_width=1)
        fig.update_layout(xaxis_title="Warming rate (°C/decade)",
            margin=dict(l=15,r=15,t=12,b=45),height=380,
            paper_bgcolor="white",plot_bgcolor="white",
            yaxis=dict(autorange="reversed"))
        return fig

    @app.callback(Output("lw-findings","children"), Input("lw-basin","value"))
    def findings(basin):
        if basin=="ALL": basin="CRB"
        df=_safe()
        if df.empty: return "Findings will appear once the VIC cache is present."
        g=df[df.basin==basin]
        if g.empty: return "No data for this basin."
        at,ap,_=_trend(g,"OUT_AIR_TEMP")
        lt,lp,_=_trend(g,"OUT_LATENT")
        s1,_,_=_trend(g,"OUT_SOIL_TEMP_L1"); s3,_,_=_trend(g,"OUT_SOIL_TEMP_L3")
        msg=[html.Strong("Key finding — "),
             f"{basin_label(basin)} is warming at {at:+.2f} °C/decade in air temperature "
             f"({'significant' if ap and ap<0.05 else 'not significant'}). "]
        if lt is not None:
            direction="falling" if lt<0 else "rising"
            msg.append(f"Latent-heat flux is {direction} ({lt:+.2f} W/m²/decade) — "
                       f"{'less energy going into evaporation as the basin dries' if lt<0 else 'more evaporative energy'}. ")
        if s1 is not None and s3 is not None:
            msg.append(f"Soil warming attenuates with depth ({s1:+.2f} °C/decade shallow vs "
                       f"{s3:+.2f} deep) — the surface heats fastest.")
        return msg

    @app.callback(Output("lw-dl-data","data"),Input("lw-dl-btn","n_clicks"),
                  Input("lw-basin","value"),prevent_initial_call=True)
    def download(n,basin):
        if not n: return None
        df=_safe()
        if df.empty: return None
        g=(df if basin=="ALL" else df[df.basin==basin])
        cols=["water_year","basin","OUT_AIR_TEMP","OUT_SURF_TEMP","OUT_RAD_TEMP","OUT_LATENT",
              "OUT_SOIL_TEMP_L1","OUT_SOIL_TEMP_L2","OUT_SOIL_TEMP_L3"]
        cols=[c for c in cols if c in g.columns]
        return dcc.send_data_frame(g[cols].to_csv,f"crb_warming_energy_{basin}.csv",index=False)
