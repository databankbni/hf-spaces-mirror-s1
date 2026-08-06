"""
modules/elevsnow.py — Snowpack Decline & Elevation

Uses the 103 SNOTEL stations (real NRCS network) in/around the CRB. Each station has a
Mann-Kendall trend in peak SWE (mk_slope, mm/yr) over its record.

What is robust: peak snowpack is declining basin-wide — 67 of 103 stations (65%) show
downward trends (binomial p = 1.5e-3, far more than chance). That is the headline finding.

What is NOT robust: the raw data show a downward gradient with elevation (r = -0.21,
p = 0.03, n = 103), and stations >=3000 m have a more negative mean trend (-1.97) than those
<3000 m (-0.70). But this gradient does NOT survive controlling for latitude and record length
(multiple regression: elevation p = 0.56 — not significant; latitude p = 0.04;
record-length p = 0.002), and the sign even flips between states (CO r=-0.17 vs UT r=+0.23). So
the apparent "high country first" pattern is confounded and is reported here as descriptive,
not as a robust independent elevation effect.

All values are real station trends — none are modelled or fabricated.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output
import dash_bootstrap_components as dbc
from scipy import stats
from utils.data_loader import load_snotel_stations
from utils.components import xref, pub_evidence, pub_star, pub_author, howto

MAROON="#8C1D40"; NAVY="#0D2137"; BLUE="#01579B"; GREEN="#2E7D32"
ORANGE="#E65100"; PURPLE="#4527A0"; TEAL="#00695C"; GREY="#94a3b8"

STATE_OPTIONS=[{"label":"All states","value":"ALL"},
               {"label":"Colorado (CO)","value":"CO"},
               {"label":"Utah (UT)","value":"UT"},
               {"label":"Wyoming (WY)","value":"WY"},
               {"label":"New Mexico (NM)","value":"NM"}]
BANDS=[(2200,2600),(2600,2900),(2900,3200),(3200,3600)]


def _safe():
    try: return load_snotel_stations()
    except: return pd.DataFrame()

def _empty(msg="No SNOTEL data"):
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

def _prep(state):
    df=_safe()
    if df.empty: return df
    # The stations table repeats each station once per basin it falls in (CRB +
    # sub-basins), so it has 258 rows for 103 unique stations. Collapse to one
    # row per station before any statistics — otherwise trends are pseudo-
    # replicated and counts/significance are inflated.
    if "site_id" in df.columns:
        df=df.drop_duplicates("site_id")
    d=df.dropna(subset=["elev","mk_slope"]).copy()
    if state and state!="ALL":
        d=d[d["state"]==state]
    return d


def layout():
    return html.Div([
        html.Div([
            html.H2("Snowpack Decline & Elevation"),
            html.P("Peak snowpack is declining basin-wide. Does the loss depend on elevation? "
                   "Every SNOTEL station's peak-SWE trend, plotted against its elevation — "
                   "real station observations, with the elevation gradient tested directly."),
        ],className="tab-header"),
        html.Div([
            dbc.Row(id="es-tiles",className="mb-3 g-2"),
            html.Div(id="es-findings",
                     style={"background":"#e3f2fd","borderLeft":f"3px solid {BLUE}",
                            "padding":"10px 14px","borderRadius":"0 6px 6px 0",
                            "fontSize":"11.5px","color":"#1565c0","marginBottom":"12px"}),
                            howto("Use the state filter. Each point is a SNOTEL station. The robust signal is that most stations are declining (points below zero). The raw downward slope with elevation is present in this plot — but see the caveat below: it does not hold once latitude and record length are controlled for."),
                            html.Div([
                                html.I(className="bi bi-exclamation-triangle-fill", style={"color":ORANGE,"fontWeight":"800","marginRight":"5px"}),
                                html.B("Confounded gradient: "),
                                "The apparent \"high country declines faster\" pattern is "
                                "not a robust independent effect. In a multiple regression, "
                                "elevation is not significant (p = 0.56) once latitude "
                                "(p = 0.04) and record length (p = 0.002) are included, and the "
                                "sign flips between states. The headline is a "
                                "basin-wide decline, not an elevation ranking."],
                                style={"background":"#fff8e1","borderLeft":f"3px solid {ORANGE}",
                                       "padding":"9px 13px","borderRadius":"0 6px 6px 0",
                                       "fontSize":"11px","color":"#8a5a00","marginBottom":"12px"}),
                            pub_author("USGS 2024", "https://www.usgs.gov/publications/high-resolution-snowmodel-simulations-reveal-future-elevation-dependent-snow-loss-and", "USGS elevation-dependent snow loss 2024", "related — observational here"),

            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("STATE FILTER",className="control-label"),
                        dcc.Dropdown(id="es-state",options=STATE_OPTIONS,value="ALL",
                                     clearable=False,style={"fontSize":"12.5px"}),
                    ],xs=12,md=4),
                ]),
            ],className="control-panel"),

            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("SWE trend vs station elevation",
                            style={"fontWeight":"700","fontSize":"13px"}),
                            html.Span("— each point a SNOTEL station; line = fit",
                                style={"color":"#1e293b","fontSize":"11px"}),
                            pub_star("https://www.usgs.gov/publications/high-resolution-snowmodel-simulations-reveal-future-elevation-dependent-snow-loss-and", "USGS elevation-dependent snow loss 2024", "Related")],className="crb-card-header"),
                        dcc.Graph(id="es-scatter",config={"displayModeBar":False},style={"height":"400px"}),
                    ],className="crb-card"),
                ],md=7),
                dbc.Col([
                    html.Div([
                        html.Div([html.Span("Mean SWE trend by elevation band",
                            style={"fontWeight":"700","fontSize":"13px"}),
                            dbc.Button("CSV",id="es-dl-btn",size="sm",className="btn-download",
                                       style={"float":"right","marginTop":"-3px"})],className="crb-card-header"),
                        dcc.Graph(id="es-band",config={"displayModeBar":False},style={"height":"400px"}),
                        dcc.Download(id="es-dl-data"),
                    ],className="crb-card"),
                ],md=5),
            ],className="g-3 mb-2"),

            html.Div("Method: per-station Mann-Kendall trend in peak SWE (mm/yr). Elevation–trend "
                     "relationship by ordinary least squares; bands are fixed 300 m intervals. "
                     "All 103 CRB-region NRCS SNOTEL stations with a computable 1984–2024 peak-SWE "
                     "trend are shown — in-situ observations, no modelling. (This descriptive trend "
                     "subset is distinct from the 163-station network used for VIC model calibration "
                     "in Ghimire/Wang et al. 2026; that set was selected for record completeness and "
                     "proximity to model cells, a different purpose.)",
                     style={"fontSize":"10.5px","color":"#1e293b","marginTop":"6px"}),
            xref("Related analyses:", [("Snowpack & runoff → Snowpack","/snowpack"),
                                       ("Warming signal → Land-Surface Warming","/warming")]),
        ],className="tab-body"),
    ])


def register_callbacks(app):

    @app.callback(Output("es-tiles","children"), Input("es-state","value"))
    def tiles(state):
        d=_prep(state)
        labels=["Stations","Elevation range","Mean SWE trend","High vs low"]
        if d.empty:
            return [dbc.Col(_tile("—",l,"","tile-navy"),xs=6,md=3) for l in labels]
        hi=d[d.elev>=3000]["mk_slope"].mean(); lo=d[d.elev<3000]["mk_slope"].mean()
        ratio=(hi/lo) if lo not in (0,np.nan) and not np.isnan(lo) and lo!=0 else np.nan
        tiles_=[
            _tile(f"{len(d)}","SNOTEL stations","","tile-blue"),
            _tile(f"{int(d.elev.min())}–{int(d.elev.max())} m","Elevation range","","tile-navy"),
            _tile(f"{d.mk_slope.mean():+.2f} mm/yr","Mean peak-SWE trend","","tile-maroon"),
            _tile(f"{hi:+.2f} vs {lo:+.2f}","≥3000 m vs <3000 m (mm/yr)"," ","tile-orange"),
        ]
        return [dbc.Col(t,xs=6,md=3) for t in tiles_]

    @app.callback(Output("es-scatter","figure"), Input("es-state","value"))
    def scatter(state):
        d=_prep(state)
        if d.empty or len(d)<5: return _empty()
        # color by significance & direction
        def col(r):
            if r.mk_pvalue<0.05 and r.mk_slope<0: return MAROON
            if r.mk_pvalue<0.05 and r.mk_slope>0: return BLUE
            return GREY
        colors=[col(r) for _,r in d.iterrows()]
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=d.elev,y=d.mk_slope,mode="markers",
            marker=dict(size=7,color=colors,opacity=0.75,line=dict(width=0.5,color="white")),
            text=d.station_name,
            hovertemplate="%{text}<br>Elev %{x:.0f} m<br>SWE trend %{y:+.2f} mm/yr<extra></extra>",
            name="stations"))
        # OLS fit line
        sl,ic,r,p,se=stats.linregress(d.elev,d.mk_slope)
        xs=np.array([d.elev.min(),d.elev.max()])
        fig.add_trace(go.Scatter(x=xs,y=ic+sl*xs,mode="lines",
            line=dict(color=NAVY,width=2.5,dash="solid"),name="fit",hoverinfo="skip"))
        fig.add_hline(y=0,line_color="#b0bec5",line_width=1)
        fig.add_annotation(xref="paper",yref="paper",x=0.03,y=0.06,showarrow=False,
            text=f"r = {r:+.2f} · p = {p:.1e} · n = {len(d)}",
            font=dict(size=11,color=NAVY),bgcolor="rgba(255,255,255,0.7)")
        fig.update_layout(xaxis_title="Station elevation (m)",
            yaxis_title="Peak-SWE trend (mm/yr)",
            margin=dict(l=55,r=15,t=12,b=45),height=400,
            paper_bgcolor="white",plot_bgcolor="white",showlegend=False)
        return fig

    @app.callback(Output("es-band","figure"), Input("es-state","value"))
    def band(state):
        d=_prep(state)
        if d.empty: return _empty()
        cats,vals,cols,ns=[],[],[],[]
        for lo,hi in BANDS:
            s=d[(d.elev>=lo)&(d.elev<hi)]["mk_slope"]
            if s.empty: continue
            cats.append(f"{lo}–{hi} m"); vals.append(s.mean()); ns.append(len(s))
            cols.append(MAROON if s.mean()<-1 else ORANGE if s.mean()<0 else BLUE)
        fig=go.Figure(go.Bar(x=vals,y=cats,orientation="h",marker_color=cols,
            text=[f"{v:+.2f} (n={n})" for v,n in zip(vals,ns)],textposition="auto",
            hovertemplate="%{y}<br>%{x:+.2f} mm/yr<extra></extra>"))
        fig.add_vline(x=0,line_color="#b0bec5",line_width=1)
        fig.update_layout(xaxis_title="Mean peak-SWE trend (mm/yr)",
            margin=dict(l=15,r=15,t=12,b=45),height=400,
            paper_bgcolor="white",plot_bgcolor="white",
            yaxis=dict(autorange="reversed"))
        return fig

    @app.callback(Output("es-findings","children"), Input("es-state","value"))
    def findings(state):
        d=_prep(state)
        if d.empty or len(d)<5: return "Findings will appear once SNOTEL data is present."
        sl,ic,r,p,se=stats.linregress(d.elev,d.mk_slope)
        hi=d[d.elev>=3000]["mk_slope"].mean(); lo=d[d.elev<3000]["mk_slope"].mean()
        decl=((d.mk_pvalue<0.05)&(d.mk_slope<0)).mean()*100
        faster = abs(hi/lo) if lo and not np.isnan(lo) and lo!=0 else None
        scope = "across all CRB-region states" if state=="ALL" else f"in {state}"
        msg=[html.Strong("Key finding — "),
             f"{len(d)} SNOTEL stations {scope}: peak SWE is declining at "
             f"{d.mk_slope.mean():+.2f} mm/yr on average, and {decl:.0f}% of stations show a "
             f"statistically significant decline — a robust, basin-wide loss of snowpack. "]
        if faster and hi<lo:
            msg.append(f"In the raw data, stations ≥3000 m show a more negative mean trend "
                       f"than lower ones ({hi:+.2f} vs {lo:+.2f} mm/yr; simple elevation "
                       f"correlation r = {r:+.2f}, p = {p:.1e}). ")
        msg.append(html.Span(
            "Note: this elevation gradient is confounded — it does not survive controlling "
            "for latitude and record length (elevation p = 0.56 in multiple regression) and "
            "reverses between states, so it is reported as descriptive, not as an independent "
            "high-elevation effect.", style={"fontStyle":"italic"}))
        return msg

    @app.callback(Output("es-dl-data","data"),Input("es-dl-btn","n_clicks"),
                  Input("es-state","value"),prevent_initial_call=True)
    def download(n,state):
        if not n: return None
        d=_prep(state)
        if d.empty: return None
        cols=["site_id","station_name","state","elev","latitude","longitude",
              "basin","mk_slope","mk_pvalue","n_years"]
        cols=[c for c in cols if c in d.columns]
        return dcc.send_data_frame(d[cols].to_csv,f"crb_snotel_elevation_swe_trends_{state}.csv",index=False)
