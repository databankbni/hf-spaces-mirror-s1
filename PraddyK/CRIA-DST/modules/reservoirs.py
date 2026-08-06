"""
modules/reservoirs.py — Reservoirs & Shortage Tiers

The operational end of the project: VIC streamflow feeds the Colorado River Simulation
System (CRSS), which informs USBR's 24-Month Study and the Lake Mead shortage tiers that
cut deliveries (e.g. to the Central Arizona Project). Reservoir capacities and shortage-tier
thresholds below are public USBR policy values. Current Lake Mead / Lake Powell elevations
are published daily by USBR (Lower Colorado region); this tab links directly to that live
source rather than re-hosting it.
"""
import plotly.graph_objects as go
from dash import html, dcc
import dash_bootstrap_components as dbc
from utils.charts import lollipop_h
from utils.components import howto

NAVY="#0D2137"; MAROON="#8C1D40"; BLUE="#01579B"; GREEN="#2E7D32"; ORANGE="#E65100"; GOLD="#FFC627"; GREY="#94a3b8"

USBR_LIVE_URL = "https://www.usbr.gov/lc/region/g4000/hourly/levels.html"

# Lake Mead shortage tiers — public (2007 Interim Guidelines + 2019 DCP). Arizona/CAP cuts.
TIERS = [
    ("Normal",    "> 1,075 ft", "—",            "#2E7D32"),
    ("Tier 0",    "1,090–1,075 ft", "−192 KAF (AZ)", "#9E9D24"),
    ("Tier 1",    "1,075–1,050 ft", "−512 KAF (AZ)", "#E65100"),
    ("Tier 2a",   "1,050–1,045 ft", "−592 KAF (AZ)", "#D84315"),
    ("Tier 2b",   "1,045–1,025 ft", "−640 KAF (AZ)", "#BF360C"),
    ("Tier 3",    "≤ 1,025 ft",    "−720 KAF (AZ)", "#B71C1C"),
]


def _tile(v, l, c):
    return html.Div([html.Div(v, className="info-tile-value"),
        html.Div(l, className="info-tile-label")], className=f"info-tile {c}")


def _nodata(msg):
    return html.Div([
        html.I(className="bi bi-exclamation-circle", style={"marginRight": "6px", "color": ORANGE}),
        html.B("No data available — "), msg,
    ], style={"background": "#fff3e0", "borderLeft": f"3px solid {ORANGE}",
              "padding": "10px 14px", "borderRadius": "0 6px 6px 0",
              "fontSize": "11.5px", "color": "#e65100"})


def _src(text):
    return html.Div(text, style={"fontSize": "10px", "color": "#1e293b", "fontStyle": "italic",
                                  "padding": "2px 16px 10px"})


def _capacity_fig():
    return lollipop_h(["Lake Powell", "Lake Mead"], [24.32, 26.12], [NAVY, BLUE],
                      x_title="Full-pool capacity (MAF)", unit=" MAF", height=240)


def _tier_fig():
    """Lake Mead elevation ladder of shortage tiers (public thresholds)."""
    levels = [("Tier 3 / dead-pool risk", 1025, "#B71C1C"),
              ("Tier 2b", 1045, "#BF360C"),
              ("Tier 2a", 1050, "#D84315"),
              ("Tier 1", 1075, "#E65100"),
              ("Tier 0", 1090, "#9E9D24"),
              ("Normal pool", 1105, "#2E7D32")]
    fig = go.Figure()
    for name, elev, col in levels:
        fig.add_hline(y=elev, line_color=col, line_width=2,
                      annotation_text=f"{name} — {elev} ft", annotation_position="right",
                      annotation_font=dict(size=10, color=col))
    fig.add_hrect(y0=895, y1=1025, fillcolor="rgba(183,28,28,0.06)", line_width=0)
    fig.update_layout(height=300, margin=dict(l=15, r=170, t=10, b=20),
        paper_bgcolor="white", plot_bgcolor="white",
        yaxis=dict(title="Lake Mead elevation (ft)", range=[990, 1115], showgrid=False),
        xaxis=dict(visible=False))
    return fig


def layout():
    tier_rows = [html.Tr([
        html.Td(html.Span("● ", style={"color": c}), style={"padding": "5px 8px"}),
        html.Td(name, style={"padding": "5px 8px", "fontWeight": "600", "fontSize": "12px", "color": NAVY}),
        html.Td(elev, style={"padding": "5px 8px", "fontSize": "12px"}),
        html.Td(cut, style={"padding": "5px 8px", "fontSize": "12px", "color": MAROON}),
    ]) for name, elev, cut, c in TIERS]

    return html.Div([
        html.Div([
            html.H2("Reservoirs & Shortage Tiers"),
            html.P("How basin hydrology becomes water-supply decisions: VIC → CRSS → USBR "
                   "24-Month Study → Lake Mead shortage tiers → delivery cuts (e.g. CAP)."),
        ], className="tab-header"),
        howto("The ladder shows Lake Mead's shortage tiers and the delivery cuts each one triggers (for example, to the Central Arizona Project)."),
        html.Div([
            html.Div([
                _tile("26.1 MAF", "Lake Mead capacity", "tile-blue"),
                _tile("24.3 MAF", "Lake Powell capacity", "tile-navy"),
                _tile("2022", "First-ever Tier 1 shortage", "tile-maroon"),
                _tile("1,075 ft", "Tier 1 trigger (Mead)", "tile-gold"),
            ], style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit,minmax(150px,1fr))",
                      "gap": "10px", "marginBottom": "16px"}),

            dbc.Row([
                dbc.Col(html.Div([
                    html.Div("Major reservoir capacity", className="crb-card-header",
                             style={"fontWeight": "700", "fontSize": "13px"}),
                    dcc.Graph(figure=_capacity_fig(), config={"displayModeBar": False}, style={"height": "240px"}),
                    _src("Source: U.S. Bureau of Reclamation full-pool capacities (public)."),
                ], className="crb-card"), md=5),
                dbc.Col(html.Div([
                    html.Div([html.Span("Lake Mead shortage-tier ladder", style={"fontWeight": "700", "fontSize": "13px"}),
                        html.Span("elevation thresholds", style={"color": "#1e293b", "fontSize": "11px"})],
                        className="crb-card-header"),
                    dcc.Graph(figure=_tier_fig(), config={"displayModeBar": False}, style={"height": "300px"}),
                    _src("Source: 2007 Interim Guidelines + 2019 Drought Contingency Plan (USBR)."),
                ], className="crb-card"), md=7),
            ], className="g-3 mb-3"),

            # Tier table
            html.Div([
                html.Div("Shortage tiers & Arizona (CAP) reductions", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div(html.Table([
                    html.Thead(html.Tr([
                        html.Th("", style={"background": NAVY, "padding": "6px 8px"}),
                        html.Th("Tier", style={"background": NAVY, "color": "white", "padding": "6px 8px", "fontSize": "12px"}),
                        html.Th("Lake Mead elevation", style={"background": NAVY, "color": "white", "padding": "6px 8px", "fontSize": "12px"}),
                        html.Th("Arizona reduction", style={"background": NAVY, "color": "white", "padding": "6px 8px", "fontSize": "12px"}),
                    ])),
                    html.Tbody(tier_rows),
                ], style={"width": "100%", "borderCollapse": "collapse"}), style={"padding": "10px 16px"}),
                _src("Source: USBR 2007 Interim Guidelines & 2019 DCP. KAF = thousand acre-feet."),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # Current levels — link to USBR's authoritative daily source
            html.Div([
                html.Div("Current reservoir levels", className="crb-card-header",
                         style={"fontWeight": "700", "fontSize": "13px"}),
                html.Div([
                    html.P("Lake Mead and Lake Powell elevations are published daily by the U.S. Bureau "
                           "of Reclamation (Lower Colorado region). This tool links directly to that "
                           "authoritative live source rather than re-hosting it — read the current Lake "
                           "Mead elevation against the shortage-tier ladder above to see the operating "
                           "tier.", style={"fontSize": "11.5px", "color": "#37474f", "lineHeight": "1.55",
                                           "marginBottom": "10px"}),
                    _usbr_link_button("View live Lake Mead & Powell levels at USBR →"),
                ], style={"padding": "10px 16px"}),
                _src("Source: USBR Lower Colorado region daily reservoir levels (public)."),
            ], className="crb-card", style={"marginBottom": "16px"}),

            # Link to hydrology
            html.Div([
                html.Div("From hydrology to operations", style={"fontWeight": "700", "fontSize": "12px",
                                                               "color": MAROON, "marginBottom": "4px"}),
                html.P(["The reservoir system's biggest uncertainty is inflow — i.e. the runoff this tool "
                        "analyzes. Use the ", html.A("Climate-Sensitivity Scenario", href="/scenario",
                        style={"color": BLUE, "fontWeight": "600"}),
                        " tab to see how a given warming/precipitation change reduces basin runoff; lower "
                        "inflow pushes Lake Mead down the tier ladder above, deepening CAP cuts."],
                       style={"fontSize": "11.5px", "color": "#37474f", "lineHeight": "1.6", "marginBottom": 0}),
                _src("Linkage per NASA project reports: VIC streamflow feeds CRSS, which informs the "
                     "USBR 24-Month Study (Annual Progress Report, Feb 2025)."),
            ], className="crb-card"),
        ], className="tab-body"),
    ])


def _usbr_link_button(label="View live levels at USBR →"):
    return html.A(label, href=USBR_LIVE_URL, target="_blank",
                  style={"background": BLUE, "color": "white", "textDecoration": "none",
                         "borderRadius": "6px", "padding": "6px 14px", "fontSize": "12px",
                         "fontWeight": "700", "whiteSpace": "nowrap", "display": "inline-block"})


def register_callbacks(app):
    pass
