"""
modules/nmme.py — Seasonal Streamflow Forecasts (NMME + VIC)
Presents the project's published results (Mascaro, Wang, Vivoni & Yue 2025, J. Hydrometeorology;
NASA Quarterly/Annual reports). The underlying NMME gridded forecasts are NOT bundled in
this repo, so this tab summarizes the documented results and shows the project's own figure.
"""
from dash import html
import dash_bootstrap_components as dbc
from pathlib import Path
from utils.components import howto, pub_star

NAVY="#0D2137"; MAROON="#8C1D40"; BLUE="#01579B"; GREEN="#2E7D32"
FIG = "/assets/reports/figs/nmme_forecast.png"
HAS_FIG = (Path(__file__).parent.parent/"assets"/"reports"/"figs"/"nmme_forecast.png").exists()

def _tile(v,l,c):
    return html.Div([html.Div(v,className="info-tile-value"),
        html.Div(l,className="info-tile-label")],className=f"info-tile {c}")

def layout():
    return html.Div([
        html.Div([
            html.H2("Seasonal Streamflow Forecasts (NMME + VIC)"),
            html.P("Can seasonal climate forecasts match the operational outlook? "
                   "Published project result (Mascaro et al. 2025, J. Hydrometeorology): NMME-forced VIC vs the "
                   "U.S. Bureau of Reclamation 24-Month Study."),
        ],className="tab-header"),
        howto("This summarizes the project's NMME+VIC seasonal streamflow forecasts compared with the operational Bureau of Reclamation 24-Month Study."),
        html.Div([
            # KPI tiles
            html.Div([
                _tile("52","Ensemble members","tile-navy"),
                _tile("5 GCMs","NMME climate models","tile-blue"),
                _tile("9 months","Forecast lead time","tile-green"),
                _tile("1982–2011","Hindcast period","tile-maroon"),
            ], style={"display":"grid","gridTemplateColumns":"repeat(auto-fit,minmax(150px,1fr))",
                      "gap":"10px","marginBottom":"16px"}),

            # Method + finding
            html.Div([
                html.Div([html.Span("How it works",style={"fontWeight":"700","fontSize":"13px"})],
                         className="crb-card-header"),
                html.Div([
                    html.P(["The North American Multi-Model Ensemble (NMME) seasonal climate forecasts "
                            "force the VIC hydrologic model (", html.B("NMME+VIC"),
                            ") to issue 9-month streamflow forecasts in the Upper Basin, initialized in "
                            "January and April. These are benchmarked against the operational ",
                            html.B("24-Month Study (24MS)"), " from the U.S. Bureau of Reclamation / "
                            "Colorado Basin River Forecast Center."],
                           style={"fontSize":"12.5px","lineHeight":"1.5"}),
                ], style={"padding":"12px 16px"}),
            ], className="crb-card", style={"marginBottom":"14px"}),

            # Key findings cards
            dbc.Row([
                dbc.Col(html.Div([
                    html.Div("Skill", style={"fontWeight":"700","fontSize":"12px","color":MAROON}),
                    html.P("In the project's published evaluation (Mascaro et al. 2025, J. Hydrometeorology), NMME+VIC "
                           "streamflow forecasts show comparable or better skill than the operational "
                           "24-Month Study, despite errors in the raw NMME precipitation and "
                           "temperature — thanks to accurate initial basin wetness.",
                           style={"fontSize":"11.5px","marginBottom":0}),
                ], className="crb-card", style={"padding":"12px 14px","height":"100%"}), md=4),
                dbc.Col(html.Div([
                    html.Div("January > April", style={"fontWeight":"700","fontSize":"12px","color":MAROON}),
                    html.P("The added value is greatest for January initialization — when the snowpack "
                           "is still building — improving on climatology more than the April forecast.",
                           style={"fontSize":"11.5px","marginBottom":0}),
                ], className="crb-card", style={"padding":"12px 14px","height":"100%"}), md=4),
                dbc.Col(html.Div([
                    html.Div("Fewer dry-bias errors", style={"fontWeight":"700","fontSize":"12px","color":MAROON}),
                    html.P("Statistically post-processing the 52 members across 5 GCMs made NMME+VIC less "
                           "likely to over-forecast dry conditions than the 24MS.",
                           style={"fontSize":"11.5px","marginBottom":0}),
                ], className="crb-card", style={"padding":"12px 14px","height":"100%"}), md=4),
            ], className="g-3 mb-3"),

            # Figure from report
            html.Div([
                html.Div([html.Span("Forecast comparison — project figure",style={"fontWeight":"700","fontSize":"13px"}),
                          html.Span("NMME+VIC (red) vs 24MS (blue) vs observations (black)",
                                    style={"color":"#1e293b","fontSize":"11px"}),
                          pub_star("https://scholar.google.com/scholar?q=Hydrometeorological+Forecast+Skill+North+American+Multi-Model+Ensemble+Upper+Colorado+River+Basin", "Yue, Mascaro, Wang & Vivoni (2025), Journal of Hydrometeorology")],
                         className="crb-card-header"),
                html.Div(
                    (html.Img(src=FIG, style={"width":"100%","maxWidth":"900px","display":"block",
                                              "margin":"0 auto","borderRadius":"6px"})
                     if HAS_FIG else
                     html.P("Figure available in the Annual Progress Report (Feb 2025), Project & Reports tab.",
                            style={"fontSize":"12px","color":"#1e293b"})),
                    style={"padding":"12px 16px"}),
                html.Div("Source: Mascaro, G., Wang, Z., Vivoni, E.R. & Yue, H. (2025), 'Hydrometeorological "
                         "Forecast Skill of the North American Multi-Model Ensemble (NMME) in the Upper "
                         "Colorado River Basin', Journal of Hydrometeorology. Raw NMME forecast data are not "
                         "bundled in this app; this tab presents the published result and the project figure.",
                         style={"fontSize":"10.5px","color":"#1e293b","padding":"0 16px 12px"}),
            ], className="crb-card"),
        ], className="tab-body"),
    ])

def register_callbacks(app):
    pass
